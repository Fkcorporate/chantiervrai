"""Test des acces equipe ChantierVrai : roles, sections visibles, actions autorisees, 2FA obligatoire, journal.
Lancement : python3 test_equipe.py
"""
import os, re, sys, tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_equipe_")
if os.environ.get("DATABASE_URL", "").startswith("postgres"):
    from services import db as _DB
    try:
        import psycopg  # noqa: F401
    except ImportError:
        from tests_support import pgwire
        _DB.set_driver(pgwire)
    _c = _DB.connect("")
    _c.execute("DROP SCHEMA public CASCADE"); _c.execute("CREATE SCHEMA public"); _c.commit(); _c.close()

import app as A
from services import security as SEC

A.app.config["TESTING"] = True
A.app.config["STAFF_2FA"] = True          # comme en production
PW = "Bingerville-2026"
s = A.connect()


def tok(c, url="/"):
    m = re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True))
    assert m, url
    return m.group(1)


def post(c, url, data, page="/", follow=True):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow)


def html(r):
    return r.get_data(as_text=True)


def one(q, *a):
    return s.execute(q, a).fetchone()


def register(email, role="proprio", **extra):
    c = A.app.test_client()
    r = post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW,
                                     **extra), "/inscription", follow=False)
    assert r.status_code == 302, email
    return c


def enable_2fa(c):
    post(c, "/compte/securite", dict(action="totp_start"), "/compte/securite")
    with c.session_transaction() as sess:
        secret = sess["totp_setup"]
    post(c, "/compte/securite", dict(action="totp_confirm", code=SEC.totp_now(secret)), "/compte/securite")


boss = register("fondateur@cv.ci")
client = register("client@x.ci")
insp = register("insp@x.ci", "inspecteur", zone="Cocody", tarif="40000", phone="0500000001")
staff = {k: register(f"{k}@cv.ci") for k in ("verification", "support", "commercial", "finance")}
ids = {r["email"]: r["id"] for r in s.execute("SELECT id, email FROM users")}

# --- 1. CLI : super-admin, 2FA exigee avant d'ouvrir l'administration ---
assert "Administrateur ajouté" in A.app.test_cli_runner().invoke(args=["creer-admin", "fondateur@cv.ci"]).output
assert one("SELECT staff_role FROM users WHERE email='fondateur@cv.ci'")[0] == "super"
r = boss.get("/admin")
assert r.status_code == 302 and r.headers["Location"].endswith("/compte/securite")
assert "2FA obligatoire" in html(boss.get("/compte/securite"))
enable_2fa(boss)
assert boss.get("/admin").status_code == 200
assert client.get("/admin").status_code == 403 and client.get("/admin/equipe").status_code == 403
print("super-admin : 2FA obligatoire avant l'administration")

# --- 2. Ecran Equipe : ajout par role, compte inconnu refuse ---
assert "Aucun compte avec cet e-mail" in html(post(boss, "/admin/equipe", dict(action="add", email="nobody@cv.ci",
                                                                              role="support"), "/admin/equipe"))
for k in staff:
    assert "a rejoint l&#39;équipe" in html(post(boss, "/admin/equipe", dict(action="add", email=f"{k}@cv.ci", role=k),
                                                   "/admin/equipe"))
    assert one("SELECT COUNT(*) FROM notifications WHERE user_id=? AND title LIKE '%Accès équipe ChantierVrai%' AND channel='app'",
               ids[f"{k}@cv.ci"])[0] == 1
    assert staff[k].get("/admin").status_code == 302          # pas encore de 2FA
    enable_2fa(staff[k])
    assert staff[k].get("/admin").status_code == 200
h = html(boss.get("/admin/equipe"))
assert all(v in h for v in ("Vérification", "Commercial", "Finance", "Professionnel du BTP"))
print("équipe : ajout par rôle, notification, 2FA exigée pour chacun")

# --- 3. Donnees de travail : chantier, commande d'image ---
s.execute("INSERT INTO projects (owner_id, name, lat, lng, invite_code, created_at) VALUES (?,?,?,?,?,?)",
          (ids["client@x.ci"], "Villa Cocody", 5.35, -3.98, "INV-EQ1", A.now_iso()))
pid = one("SELECT id FROM projects WHERE invite_code='INV-EQ1'")[0]
prov = next(iter(A.IMAGERY_PROVIDERS))
s.execute("INSERT INTO imagery_orders (project_id, user_id, provider, status, created_at) VALUES (?,?,?,?,?)",
          (pid, ids["client@x.ci"], prov, "demandee", A.now_iso()))
oid = one("SELECT id FROM imagery_orders")[0]
s.commit()

# --- 4. Chaque role ne voit que ses sections ---
SECTIONS = {"images": "Images satellite très haute résolution", "verify": "Inspecteurs et fournisseurs à vérifier",
            "disputes": "Litiges", "accounts": "Rechercher un compte",
            "journal": "Journal d&#39;administration", "escrow": "En séquestre", "commission": "FCFA de commission",
            "team": "/admin/equipe"}
SEES = {"verification": {"verify"}, "support": {"disputes", "accounts"},
        "commercial": {"images"}, "finance": {"images", "escrow", "commission"}}
for k, c in staff.items():
    h = html(c.get("/admin"))
    for sec, text in SECTIONS.items():
        assert (text in h) == (sec in SEES[k]), (k, sec)
h = html(boss.get("/admin"))
assert all(t in h for t in SECTIONS.values())
print("sections : chacun voit seulement son périmètre, le fondateur voit tout")

# --- 5. Actions autorisees et refusees ---
v, sp, cm, fn = (staff[k] for k in ("verification", "support", "commercial", "finance"))
iid = ids["insp@x.ci"]
assert post(sp, "/admin/action", dict(action="verify", id=iid), "/admin", follow=False).status_code == 403
assert post(cm, "/admin/action", dict(action="verify", id=iid), "/admin", follow=False).status_code == 403
post(v, "/admin/action", dict(action="verify", id=iid), "/admin")
assert one("SELECT verified FROM users WHERE id=?", iid)[0] == 1
assert post(v, "/admin/action", dict(action="block", id=ids["client@x.ci"]), "/admin", follow=False).status_code == 403
assert post(sp, "/admin/action", dict(action="reset_link", id=ids["client@x.ci"]), "/admin", follow=False).status_code == 403
assert post(sp, "/admin/action", dict(action="block", id=ids["fondateur@cv.ci"]), "/admin", follow=False).status_code == 403
post(sp, "/admin/action", dict(action="block", id=ids["client@x.ci"]), "/admin")
assert one("SELECT blocked FROM users WHERE id=?", ids["client@x.ci"])[0] == 1
post(sp, "/admin/action", dict(action="unblock", id=ids["client@x.ci"]), "/admin")
assert "/reinitialiser/" in html(post(boss, "/admin/action", dict(action="reset_link", id=ids["client@x.ci"]), "/admin"))
assert post(v, f"/admin/images-thr/{oid}", dict(action="cancel"), "/admin", follow=False).status_code == 403
post(cm, f"/admin/images-thr/{oid}", dict(action="cancel"), "/admin")
assert one("SELECT status FROM imagery_orders WHERE id=?", oid)[0] == "annulee"
assert v.get("/admin/equipe").status_code == 403 and fn.get("/admin/equipe").status_code == 403
print("actions : vérification, modération, blocage, récupération et images limités au bon rôle")

# --- 6. Acces aux chantiers clients : seulement support et fondateur ---
for k, c in staff.items():
    assert (c.get(f"/chantiers/{pid}/fiche").status_code == 200) == (k == "support"), k
assert boss.get(f"/chantiers/{pid}/fiche").status_code == 200
print("chantiers clients : ouverts au support et au fondateur seulement")

# --- 7. Notifications ciblees par role ---
s.execute("INSERT INTO imagery_orders (project_id, user_id, provider, status, created_at) VALUES (?,?,?,?,?)",
          (pid, ids["client@x.ci"], prov, "demandee", A.now_iso())); s.commit()
with A.app.app_context():
    db = A.get_db()
    assert set(A.admins(db, "imagery")) == {ids["fondateur@cv.ci"], ids["commercial@cv.ci"], ids["finance@cv.ci"]}
    assert set(A.admins(db, "verify")) == {ids["fondateur@cv.ci"], ids["verification@cv.ci"]}
    assert set(A.admins(db, "disputes")) == {ids["fondateur@cv.ci"], ids["support@cv.ci"]}
print("alertes : envoyées seulement aux rôles concernés")

# --- 8. Journal avec role ; changement de role ; retrait ; pas d'auto-modification ---
assert one("SELECT staff_role FROM admin_log WHERE action='verify'")[0] == "verification"
assert one("SELECT staff_role FROM admin_log WHERE action='imagery_cancel'")[0] == "commercial"
assert "(Support, litiges et modération)" in html(boss.get("/admin"))
post(boss, "/admin/equipe", dict(action="role", id=ids["commercial@cv.ci"], role="finance"), "/admin/equipe")
assert "FCFA de commission" in html(cm.get("/admin"))
post(boss, "/admin/equipe", dict(action="remove", id=ids["finance@cv.ci"]), "/admin/equipe")
assert one("SELECT is_admin, staff_role FROM users WHERE email='finance@cv.ci'")[0] == 0
assert fn.get("/admin").status_code in (302, 403)
assert "propre accès" in html(post(boss, "/admin/equipe", dict(action="remove", id=ids["fondateur@cv.ci"]), "/admin/equipe"))
assert one("SELECT COUNT(*) FROM admin_log WHERE action LIKE 'team_%'")[0] >= 6
print("journal avec rôle, changement de rôle, retrait d'accès ok")

# --- 9. 2FA retiree : acces equipe suspendu ---
with v.session_transaction():
    pass
post(v, "/compte/securite", dict(action="totp_off", current=PW), "/compte/securite")
assert v.get("/admin").status_code == 302
print("2FA désactivée : administration fermée jusqu'à réactivation")
print("TOUS LES TESTS EQUIPE PASSENT")
