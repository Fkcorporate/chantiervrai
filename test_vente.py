"""Test des fonctions de mise en vente : securite des comptes, etapes modifiables, co-proprietaires,
administration, litiges, paiement de l'inspecteur, camera integree, hors ligne, publication, sauvegardes.
Lancement : python3 test_vente.py
"""
import io, json, os, re, shutil, sys, tempfile
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
inst = tempfile.mkdtemp(prefix="cv_vente_")
os.environ["CV_INSTANCE"] = inst
# --- Base de donnees : SQLite par defaut ; PostgreSQL si DATABASE_URL est defini (pilote de test inclus) ---
if os.environ.get("DATABASE_URL", "").startswith("postgres"):
    from services import db as _DB
    try:
        import psycopg  # noqa: F401
    except ImportError:
        from tests_support import pgwire
        _DB.set_driver(pgwire)
    _c = _DB.connect("")
    _c.execute("DROP SCHEMA public CASCADE"); _c.execute("CREATE SCHEMA public"); _c.commit(); _c.close()
PG = os.environ.get("DATABASE_URL", "").startswith("postgres")

import numpy as np
from PIL import Image
import app as A
from services import security as SEC

A.app.config["TESTING"] = True
A.app.config["ESCROW_ENABLED"] = True     # sequestre active comme par le super-admin
SITE = (5.3521, -3.8892)
PW = "Bingerville-2026"
own, chef, insp, co, adm, other = (A.app.test_client() for _ in range(6))
s = A.connect()


def tok(c, url="/"):
    r = c.get(url)
    m = re.search(r'name="csrf" value="([^"]+)"', r.get_data(as_text=True))
    assert m, (url, r.status_code)
    return m.group(1)


def post(c, url, data, page="/", follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)


def html(r):
    return r.get_data(as_text=True)


def jpg(seed, exif_when=None, lat=None, lng=None):
    im = Image.fromarray(np.random.default_rng(seed).integers(0, 255, (240, 320, 3), dtype=np.uint8))
    b = io.BytesIO()
    if exif_when or lat is not None:
        ex = Image.Exif()
        if exif_when:
            ex.get_ifd(0x8769)[0x9003] = exif_when.strftime('%Y:%m:%d %H:%M:%S')
        im.save(b, "JPEG", exif=ex.tobytes())
    else:
        im.save(b, "JPEG")
    return b.getvalue()


def register(c, email, role, **extra):
    return post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email,
                                        password=PW, **extra), "/inscription", follow=False)


# --- 1. Inscription : CGU et mot de passe ---
assert "trop courant" in html(post(other, "/inscription", dict(terms="1", role="proprio", name="X", email="x@x.ci",
                                                               password="password1"), "/inscription"))
assert "Acceptez les conditions" in html(post(other, "/inscription", dict(role="proprio", name="X", email="x@x.ci",
                                                                          password=PW), "/inscription"))
for c, e, r, ex in [(own, "a@x.ci", "proprio", {}), (chef, "k@x.ci", "chef", {"phone": "0700000000"}),
                    (insp, "i@x.ci", "inspecteur", {"zone": "Bingerville", "tarif": "40000", "phone": "0500000000"}),
                    (co, "frere@x.ci", "proprio", {}), (adm, "admin@x.ci", "proprio", {})]:
    assert register(c, e, r, **ex).status_code == 302
assert s.execute("SELECT terms_at FROM users WHERE email='a@x.ci'").fetchone()[0]
print("inscription : CGU obligatoires, mots de passe faibles refusés")

# --- 2. Blocage apres 5 echecs ---
bad = A.app.test_client()
for _ in range(5):
    post(bad, "/connexion", dict(email="a@x.ci", password="faux"), "/connexion")
r = post(bad, "/connexion", dict(email="a@x.ci", password=PW), "/connexion")
assert r.status_code == 429 and "Trop d&#39;essais" in html(r)
s.execute("DELETE FROM login_attempts"); s.commit()
print("blocage après 5 essais ratés ok")

# --- 3. Mot de passe oublie : lien, changement, autres sessions deconnectees ---
post(other, "/mot-de-passe-oublie", dict(email="k@x.ci"), "/mot-de-passe-oublie")
link = s.execute("SELECT link FROM notifications WHERE title LIKE 'Réinitialisation%' AND channel='email'").fetchone()[0]
assert link.startswith("/reinitialiser/")
post(other, "/mot-de-passe-oublie", dict(email="inconnu@x.ci"), "/mot-de-passe-oublie")     # meme reponse
r = post(other, link, dict(password="Nouveau-Chef-77", password2="Nouveau-Chef-77"), link)
assert "Mot de passe changé" in html(r)
assert chef.get("/compte").status_code == 302                 # ancienne session du chef invalidee
assert other.get(link, follow_redirects=True).request.path == "/mot-de-passe-oublie"   # lien a usage unique
post(chef, "/connexion", dict(email="k@x.ci", password="Nouveau-Chef-77"), "/connexion")
assert chef.get("/").status_code == 200
print("mot de passe oublié ok (lien unique, sessions déconnectées)")

# --- 4. Double authentification + code de secours ---
post(own, "/compte/securite", dict(action="totp_start"), "/compte/securite")
with own.session_transaction() as sess:
    secret = sess["totp_setup"]
r = post(own, "/compte/securite", dict(action="totp_confirm", code=SEC.totp_now(secret)), "/compte/securite")
codes = re.findall(r"<span>(\d{4} \d{4})</span>", html(r))
assert len(codes) == 8, html(r)[:1500]
own2 = A.app.test_client()
r = post(own2, "/connexion", dict(email="a@x.ci", password=PW), "/connexion", follow=False)
assert r.headers["Location"].endswith("/connexion/code")
assert own2.get("/compte").status_code == 302                 # pas connecte sans le code
post(own2, "/connexion/code", dict(code="000000"), "/connexion/code")
r = post(own2, "/connexion/code", dict(code=SEC.totp_now(secret)), "/connexion/code", follow=False)
assert r.status_code == 302 and own2.get("/").status_code == 200
own3 = A.app.test_client()
post(own3, "/connexion", dict(email="a@x.ci", password=PW), "/connexion")
assert "Code de secours utilisé" in html(post(own3, "/connexion/code", dict(code=codes[0]), "/connexion/code"))
own4 = A.app.test_client()
post(own4, "/connexion", dict(email="a@x.ci", password=PW), "/connexion")
assert "Code incorrect" in html(post(own4, "/connexion/code", dict(code=codes[0]), "/connexion/code"))  # deja utilise
print("double authentification ok (application + codes de secours à usage unique)")

# --- 5. Administration : creer-admin, verification inspecteur ---
res = A.app.test_cli_runner().invoke(args=["creer-admin", "admin@x.ci"]); assert "Administrateur ajouté" in res.output
assert own.get("/admin").status_code == 403 and adm.get("/admin").status_code == 200
insp_id = s.execute("SELECT id FROM users WHERE email='i@x.ci'").fetchone()[0]
assert "I" in html(adm.get("/admin")) and "Inspecteurs et fournisseurs à vérifier" in html(adm.get("/admin"))
post(adm, "/admin/action", dict(action="verify", id=insp_id), "/admin")
assert s.execute("SELECT verified FROM users WHERE id=?", (insp_id,)).fetchone()[0] == 1
print("administration ok")

# --- 6. Chantier, co-proprietaire, camera exigee ---
data = dict(name="Villa", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="sequestre",
            require_app_capture="1", start_date=datetime.now().date().isoformat())
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
pid = int(post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])
code = re.search(r'class="code">(\w+)<', html(own.get(f"/chantiers/{pid}"))).group(1)
post(chef, "/rejoindre", dict(code=code))
assert co.get(f"/chantiers/{pid}").status_code == 403
post(own, f"/chantiers/{pid}/membres", dict(email="frere@x.ci"), f"/chantiers/{pid}?onglet=dossier")
assert co.get(f"/chantiers/{pid}").status_code == 200 and "Villa" in html(co.get("/"))
print("co-propriétaire ok")


# --- 7. Camera integree, jeton, hors ligne ---
def page_token(c):
    return re.search(r'name="capture_token" value="([^"]+)"', html(c.get(f"/chantiers/{pid}"))).group(1)


def send(c, img, url=None, **f):
    d = dict(tz_offset="0", lat=str(SITE[0]), lng=str(SITE[1]), photo=(io.BytesIO(img), "capture.jpg")); d.update(f)
    return html(post(c, url or f"/chantiers/{pid}/preuves", d, f"/chantiers/{pid}", files=True))


now_ms = lambda: datetime.now(timezone.utc).timestamp() * 1000
t = page_token(chef)
h = send(chef, jpg(1), capture="app", capture_token=t, captured_at=str(now_ms() - 5000), client_now=str(now_ms()))
assert "Preuve vérifiée" in h, h[:1500]
h = send(chef, jpg(2), capture="fichier", last_modified=str(now_ms()), client_now=str(now_ms()))
assert "exige la caméra" in h
h = send(chef, jpg(3, exif_when=datetime.now()), capture="app", capture_token=t, captured_at=str(now_ms()), client_now=str(now_ms()))
assert "présenté comme une capture" in h
h = send(chef, jpg(4), capture="app", capture_token="faux", captured_at=str(now_ms()), client_now=str(now_ms()))
assert "Jeton de capture invalide" in h
s.execute("UPDATE capture_tokens SET issued_at=? WHERE token=?", ((datetime.now(timezone.utc) - timedelta(hours=10)).isoformat(), t)); s.commit()
h = send(chef, jpg(5), capture="app", capture_token=t, captured_at=str(now_ms() - 11 * 3600 * 1000), client_now=str(now_ms()))
assert "antérieure à l&#39;ouverture" in h or "antérieure à l'ouverture" in h
# horloge du telephone en avance de 2 h : corrigee grace a client_now
skew = 2 * 3600 * 1000
h = send(chef, jpg(6), capture="app", capture_token=t, captured_at=str(now_ms() + skew - 60000), client_now=str(now_ms() + skew))
assert "Preuve vérifiée" in h
# prise sans reseau il y a 5 h, envoyee au retour du reseau
h = send(chef, jpg(7), capture="app", capture_token=t, offline="1", captured_at=str(now_ms() - 5 * 3600 * 1000), client_now=str(now_ms()))
assert "Preuve vérifiée" in h, h[:1500]
assert "Envoyée sans réseau, 5.0 h après la prise" in html(own.get(f"/chantiers/{pid}?onglet=preuves"))
h = send(chef, jpg(8), capture="app", capture_token=t, captured_at=str(now_ms() - 5 * 3600 * 1000), client_now=str(now_ms()))
assert "ancienne" in h                                         # sans le drapeau hors ligne : refusee
assert chef.get(f"/chantiers/{pid}").headers.get("X-CV-Offline") == "1"
print("caméra intégrée, jeton, horloge décalée, hors ligne ok")

# --- 8. Etapes modifiables ---
steps = s.execute("SELECT * FROM steps WHERE project_id=? ORDER BY position", (pid,)).fetchall()
st1, st2, st3, st4 = steps[0], steps[1], steps[2], steps[3]
post(chef, f"/chantiers/{pid}/etapes/{st1['id']}/declarer", {}, f"/chantiers/{pid}")
r = post(own, f"/chantiers/{pid}/etapes/modifier", {"action": "save", f"name_{st1['id']}": "Fondations et semelles",
                                                    f"amount_{st1['id']}": "999", f"amount_{st3['id']}": "4000000"},
         f"/chantiers/{pid}?onglet=etapes")
assert "ne peut plus changer" in html(r)
st = {x["id"]: x for x in s.execute("SELECT * FROM steps WHERE project_id=?", (pid,))}
assert st[st1["id"]]["name"] == "Fondations et semelles" and st[st1["id"]]["amount"] == 3000000 and st[st3["id"]]["amount"] == 4000000
post(own, f"/chantiers/{pid}/etapes/modifier", dict(action="add", new_name="Clôture", new_amount="800000", new_days="10"), f"/chantiers/{pid}?onglet=etapes")
post(own, f"/chantiers/{pid}/etapes/modifier", dict(action="up", step_id=st4["id"]), f"/chantiers/{pid}?onglet=etapes")
order = [x[0] for x in s.execute("SELECT name FROM steps WHERE project_id=? ORDER BY position", (pid,))]
assert order[2] == "Élévation des murs" and order[3] == "Dalle basse" and order[-1] == "Clôture", order
assert "Seules les étapes à venir" in html(post(own, f"/chantiers/{pid}/etapes/modifier", dict(action="delete", step_id=st1["id"]), f"/chantiers/{pid}?onglet=etapes"))
post(own, f"/chantiers/{pid}/etapes/modifier", dict(action="delete", step_id=st4["id"]), f"/chantiers/{pid}?onglet=etapes")
assert s.execute("SELECT COUNT(*) FROM steps WHERE project_id=?", (pid,)).fetchone()[0] == 6
assert s.execute("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Étapes du chantier modifiées%' AND user_id=(SELECT id FROM users WHERE email='k@x.ci')").fetchone()[0] >= 3
print("étapes modifiables ok (montants verrouillés après déclaration)")

# --- 9. Co-proprietaire valide, litige, mediation ---
post(co, f"/chantiers/{pid}/paiements/depot", dict(amount="6000000"), f"/chantiers/{pid}?onglet=etapes")
r = post(chef, f"/chantiers/{pid}/litiges", dict(step_id=st1["id"], subject="Validation bloquée",
                                                 text="L'étape est terminée depuis 10 jours, les photos le montrent."), f"/chantiers/{pid}")
did = s.execute("SELECT id FROM disputes").fetchone()[0]
assert "Validation bloquée" in html(r)
assert s.execute("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Litige ouvert%' AND channel='app' AND user_id=(SELECT id FROM users WHERE email='admin@x.ci')").fetchone()[0] == 1
assert "1 litige en cours" in html(own.get(f"/chantiers/{pid}"))
post(own, f"/litiges/{did}", dict(action="message", text="Je veux voir le ferraillage."), f"/litiges/{did}")
assert adm.get(f"/litiges/{did}").status_code == 200 and insp.get(f"/litiges/{did}").status_code == 403
okp = s.execute("SELECT id FROM proofs WHERE project_id=? AND ok=1", (pid,)).fetchone()[0]
assert adm.get(f"/photos/{okp}").status_code == 200              # le mediateur voit les preuves
assert adm.get(f"/chantiers/{pid}").status_code == 403          # mais pas le reste du chantier
post(adm, f"/litiges/{did}", dict(action="resolve", text="Preuves suffisantes. Recommandation : valider l'étape."), f"/litiges/{did}")
assert s.execute("SELECT status FROM disputes WHERE id=?", (did,)).fetchone()[0] == "resolu"
for c_ in s.execute("SELECT id FROM step_checks WHERE step_id=? AND required=1", (st1["id"],)).fetchall():
    s.execute("UPDATE step_checks SET status='conforme', checked_at=? WHERE id=?", (A.now_iso(), c_[0]))   # controles faits
s.commit()
r = post(co, f"/chantiers/{pid}/etapes/{st1['id']}/valider", {}, f"/chantiers/{pid}?onglet=etapes")
assert "versés au chef de chantier" in html(r)
print("litige, médiation, validation par le co-propriétaire ok")

# --- 10. Inspection vendue par ChantierVrai, inspecteur paye par ChantierVrai ---
r = post(own, f"/chantiers/{pid}/inspections", dict(step_id=st2["id"]), f"/chantiers/{pid}?onglet=dossier", follow=False)
inv_id = int(r.headers["Location"].split("/")[-1])
post(own, f"/compte/factures/{inv_id}", {}, f"/compte/factures/{inv_id}")
rid = s.execute("SELECT id FROM inspection_requests").fetchone()[0]
post(adm, "/admin/inspections", dict(action="assign", id=rid, inspector_id=insp_id), "/admin")
iid = s.execute("SELECT id FROM inspections").fetchone()[0]
post(insp, f"/inspections/{iid}/reponse", dict(decision="accepter"))
it = re.search(r'name="capture_token" value="([^"]+)"', html(insp.get(f"/chantiers/{pid}"))).group(1)
h = send(insp, jpg(20), url=f"/inspections/{iid}/preuves", capture="app", capture_token=it, captured_at=str(now_ms()), client_now=str(now_ms()))
assert "Photo d&#39;inspection vérifiée" in h or "Photo d'inspection vérifiée" in h, h[:1200]
post(insp, f"/inspections/{iid}/rapport", dict(verdict="conforme", report="Ferraillage conforme, enrobage correct."), f"/chantiers/{pid}")
before = A.escrow(pid, s)["balance"]
assert "pas à payer" in html(post(own, f"/inspections/{iid}/payer", {}, f"/chantiers/{pid}?onglet=dossier"))
assert A.escrow(pid, s)["balance"] == before                       # le proprietaire ne paie pas l'inspecteur
assert "Inspecteurs à payer" in html(adm.get("/admin"))
post(adm, "/admin/inspections", dict(action="payout", id=iid, reference="WAVE-INSP-1"), "/admin")
assert s.execute("SELECT paid, payout_status, pay_ref FROM inspections WHERE id=?", (iid,)).fetchone()[:] == (1, "verse", "WAVE-INSP-1")
print("inspection vendue par ChantierVrai : attribution, rapport, inspecteur payé par la finance")

# --- 11. Publication sur le portail (visages floutes) et moderation ---
post(own, f"/chantiers/{pid}/marche", dict(kind="public", is_public="1", autorite="Mairie"), f"/chantiers/{pid}?onglet=dossier")
pub = A.app.test_client()
assert "/portail/photos/" not in html(pub.get(f"/portail/{pid}"))
r = post(own, f"/preuves/{okp}/publier", {}, f"/chantiers/{pid}?onglet=preuves")
assert "Photo publiée" in html(r)
assert pub.get(f"/portail/photos/{okp}").status_code == 200
face_img, n, available = A.VISION.blur_faces(Image.new("RGB", (100, 100), (200, 200, 200)))
assert available is not None
post(pub, f"/portail/{pid}/signaler", dict(text="Message insultant pour tester la modération"), f"/portail/{pid}")
sid = s.execute("SELECT id FROM signalements").fetchone()[0]
post(adm, "/admin/action", dict(action="hide_sig", id=sid), "/admin")
assert "insultant" not in html(pub.get(f"/portail/{pid}"))
print("publication des photos et modération ok")

# --- 12. Admin : lien de reinitialisation, blocage ---
k_id = s.execute("SELECT id FROM users WHERE email='k@x.ci'").fetchone()[0]
r = post(adm, "/admin/action", dict(action="reset_link", id=k_id), "/admin")
assert "/reinitialiser/" in html(r) and "/reinitialiser/" not in html(adm.get("/admin"))   # affiche une seule fois
post(adm, "/admin/action", dict(action="block", id=k_id), "/admin")
assert chef.get("/compte").status_code == 302
assert "suspendu" in html(post(A.app.test_client(), "/connexion", dict(email="k@x.ci", password="Nouveau-Chef-77"), "/connexion"))
post(adm, "/admin/action", dict(action="unblock", id=k_id), "/admin")
assert s.execute("SELECT COUNT(*) FROM admin_log").fetchone()[0] >= 5
print("blocage et journal d'administration ok")

# --- 13. Donnees personnelles : export et suppression ---
data = json.loads(own.get("/compte/export").get_data())
assert data["compte"]["email"] == "a@x.ci" and "password_hash" not in data["compte"] and data["chantiers"]
assert "argent" in html(post(own, "/compte/supprimer", dict(current=PW), "/compte/securite"))   # sequestre non vide
register(other, "jetable@x.ci", "proprio")
post(other, "/compte/supprimer", dict(current=PW), "/compte/securite")
u = s.execute("SELECT * FROM users WHERE name='Compte supprimé'").fetchone()
assert u and u["deleted"] == 1 and "jetable" not in u["email"]
assert A.app.test_client().get("/cgu").status_code == 200 and A.app.test_client().get("/confidentialite").status_code == 200
print("export, suppression du compte, CGU ok")

# --- 14. En-tetes de securite, relances, sauvegarde ---
r = own.get("/")
assert r.headers["X-Frame-Options"] == "SAMEORIGIN" and "default-src 'self'" in r.headers["Content-Security-Policy"]
assert "no-store" in r.headers["Cache-Control"]
s.execute("UPDATE notifications SET status='en_attente', created_at=? WHERE id=(SELECT MAX(id) FROM notifications WHERE channel='whatsapp')",
          ((datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),)); s.commit()
res = A.app.test_cli_runner().invoke(args=["relancer"]); assert "1 message(s)" in res.output, res.output
res = A.app.test_cli_runner().invoke(args=["sauvegarde", "--garder", "2"]); assert res.output.count("Sauvegardé") == 2, res.output
bk = os.path.join(inst, "sauvegardes")
if PG:
    import gzip
    dump = [f for f in os.listdir(bk) if f.endswith(".sql.gz")][0]
    assert b"CREATE TABLE public.users" in gzip.decompress(open(os.path.join(bk, dump), "rb").read())
else:
    copy = [f for f in os.listdir(bk) if f.endswith(".db")][0]
    import sqlite3
    assert sqlite3.connect(os.path.join(bk, copy)).execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 6
res = A.app.test_cli_runner().invoke(args=["quotidien"]); assert "Sauvegardé" in res.output, res.output
print("en-têtes de sécurité, relances, sauvegardes ok")

post(chef, "/connexion", dict(email="k@x.ci", password="Nouveau-Chef-77"), "/connexion")   # deconnecte par le blocage
for c, pages in [(own, ["/", "/compte", "/compte/securite", f"/chantiers/{pid}?onglet=etapes", f"/chantiers/{pid}?onglet=dossier",
                        f"/chantiers/{pid}?onglet=preuves", f"/litiges/{did}"]),
                 (chef, [f"/chantiers/{pid}", f"/litiges/{did}"]), (adm, ["/admin", "/admin?q=koffi"])]:
    for u in pages:
        assert c.get(u).status_code == 200, u
shutil.rmtree(inst, ignore_errors=True)
print("TOUT OK")
