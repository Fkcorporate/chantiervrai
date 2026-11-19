"""Test des recours : validation automatique (recours du chef), litiges avec delais, decision et recours,
reattribution d'une inspection, conditions fournisseur.
Lancement : python3 test_recours.py
"""
import os, re, sys, tempfile
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_recours_")
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

A.app.config["TESTING"] = True
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
    assert post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW,
                                        **extra), "/inscription", follow=False).status_code == 302, email
    return c


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def job(fn):
    with A.app.test_request_context():
        db = A.connect()
        out = fn(db)
        db.close()
    return out


def notes(email, title):
    return one("SELECT COUNT(*) FROM notifications n JOIN users u ON u.id = n.user_id WHERE u.email = ? AND n.title LIKE ? "
               "AND n.channel = 'app'", email, f"%{title}%")[0]


own = register("a@x.ci"); chef = register("k@x.ci", "chef", phone="0700000000")
sup_staff = register("support@cv.ci"); boss = register("boss@cv.ci")
A.app.test_cli_runner().invoke(args=["creer-admin", "boss@cv.ci"])
A.app.test_cli_runner().invoke(args=["creer-admin", "support@cv.ci", "--role", "support"])

data = dict(name="Villa", address="Bingerville", lat="5.3521", lng="-3.8892", radius="100", pay_mode="suivi",
            start_date=datetime.now().date().isoformat())
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS[:5]):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
pid = int(post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])
code = one("SELECT invite_code FROM projects WHERE id=?", pid)[0]
post(chef, "/rejoindre", dict(code=code))
steps = [r[0] for r in s.execute("SELECT id FROM steps WHERE project_id=? ORDER BY position", (pid,))]
with A.app.test_request_context():
    db = A.connect(); A.seed_checks(db, pid); db.close()


def declare(sid, days):
    s.execute("UPDATE steps SET status='declare', declared_at=?, owner_reminders=0 WHERE id=?", (ago(days), sid)); s.commit()


def checks_done(sid):
    s.execute("UPDATE step_checks SET status='conforme', checked_at=? WHERE step_id=? AND required=1", (A.now_iso(), sid))
    s.commit()


# --- 1a. Par defaut : pas de validation automatique, relances explicites, chef invite au litige ---
assert not A.auto_validate_on(s)
assert "J&#39;accepte la validation automatique" not in html(own.get("/chantiers/nouveau"))
assert "Pas de validation automatique" in html(chef.get(f"/chantiers/{pid}"))
declare(steps[0], 2)
assert "validée automatiquement" not in html(chef.get(f"/chantiers/{pid}/etapes/{steps[0]}"))
assert job(A.auto_validate_steps)["relances"] == 1
assert one("SELECT body FROM notifications n JOIN users u ON u.id=n.user_id WHERE u.email='a@x.ci' AND n.title LIKE "
           "'%Étape à valider%' AND n.channel='app' ORDER BY n.id DESC LIMIT 1")[0].find("attend votre décision") >= 0
s.execute("UPDATE steps SET declared_at=? WHERE id=?", (ago(7), steps[0])); s.commit()
out = job(A.auto_validate_steps)
assert out["validees"] == 0 and out["arbitrage"] == 1 and notes("k@x.ci", "Sans réponse du propriétaire") == 1
assert one("SELECT status FROM steps WHERE id=?", steps[0])[0] == "declare"
assert post(own, f"/chantiers/{pid}/reglages", dict(setting="auto_validate", on="1"), f"/chantiers/{pid}",
            follow=False).status_code == 400                                   # option non proposee par la plateforme
print("par défaut : aucune validation automatique, relances explicites, chef invité au litige")

# --- 1b. Le super-admin la propose (delai 10 j), le proprietaire l'accepte sur son chantier ---
post(boss, "/admin/action", dict(action="auto_validate", on="1", days="10"), "/admin")
assert A.auto_validate_on(s) and A.auto_validate_days(s) == 10
assert "Validation automatique après 10 jours" in html(own.get("/chantiers/nouveau"))
assert "Une étape attend votre réponse" not in html(post(own, f"/chantiers/{pid}/reglages", dict(setting="auto_validate", on="1"),
                                                         f"/chantiers/{pid}?onglet=etapes"))
assert one("SELECT auto_validate FROM projects WHERE id=?", pid)[0] == 1
assert notes("k@x.ci", "Règle du chantier modifiée") == 1 and "Validation automatique : une étape" in html(chef.get(f"/chantiers/{pid}"))
assert "Une étape attend votre réponse" in html(post(own, f"/chantiers/{pid}/reglages", dict(setting="auto_validate"),
                                                     f"/chantiers/{pid}?onglet=etapes"))   # retrait impossible pendant l'attente
declare(steps[0], 2)
assert "validée automatiquement" in html(chef.get(f"/chantiers/{pid}/etapes/{steps[0]}"))
assert job(A.auto_validate_steps)["relances"] == 1
msg = one("SELECT body FROM notifications n JOIN users u ON u.id=n.user_id WHERE u.email='a@x.ci' AND n.title LIKE "
          "'%Étape à valider%' AND n.channel='app' ORDER BY n.id DESC LIMIT 1")[0]
assert "ouvrez un litige avant cette date" in msg and "validée automatiquement le" in msg
for d_, n_ in ((7, 2), (9, 3)):                                               # 3 jours puis 1 jour avant l'echeance
    s.execute("UPDATE steps SET declared_at=? WHERE id=?", (ago(d_), steps[0])); s.commit()
    assert job(A.auto_validate_steps)["relances"] == 1
    assert one("SELECT owner_reminders FROM steps WHERE id=?", steps[0])[0] == n_
s.execute("UPDATE steps SET declared_at=? WHERE id=?", (ago(10), steps[0])); s.commit()
has_checks = one("SELECT COUNT(*) FROM step_checks WHERE step_id=? AND required=1", steps[0])[0]
if has_checks:
    out = job(A.auto_validate_steps)
    assert out["bloquees"] == 1 and out["validees"] == 0                     # controles obligatoires manquants
    assert notes("k@x.ci", "Validation automatique impossible") == 1
    assert one("SELECT status FROM steps WHERE id=?", steps[0])[0] == "declare"
    s.execute("UPDATE steps SET owner_reminders=3 WHERE id=?", (steps[0],)); s.commit()
    checks_done(steps[0])
out = job(A.auto_validate_steps)
assert out["validees"] == 1
st = one("SELECT status, auto_validated, pay_ref FROM steps WHERE id=?", steps[0])
assert st[:2] == ("versement", 1) and st[2] == f"BAP-{pid}-E{steps[0]}"
assert notes("a@x.ci", "Étape validée automatiquement") == 1 and notes("k@x.ci", "Paiement à venir") == 1
assert one("SELECT COUNT(*) FROM documents WHERE step_id=? AND category='PV'", steps[0])[0] == 1
assert "Validée automatiquement" in html(own.get(f"/chantiers/{pid}/etapes/{steps[0]}"))
assert "Validation automatique (option)" in html(own.get("/cgu"))
print("validation automatique : proposée par le super-admin, acceptée par le propriétaire, relances datées, contrôles exigés")

# --- 1c. Inspection obligatoire sur les etapes critiques ---
assert A.is_critical("Fondations") and not A.is_critical("Peinture")
crit = one("SELECT id, name FROM steps WHERE id=?", steps[4])
assert A.is_critical(crit[1])
post(own, f"/chantiers/{pid}/reglages", dict(setting="inspection", on="1"), f"/chantiers/{pid}?onglet=dossier")
assert one("SELECT require_inspection FROM projects WHERE id=?", pid)[0] == 1
assert "Inspection indépendante obligatoire" in html(chef.get(f"/chantiers/{pid}"))
if True:
    declare(crit[0], 1); checks_done(crit[0])
    h = html(post(own, f"/chantiers/{pid}/etapes/{crit[0]}/valider", dict(override="1"), f"/chantiers/{pid}?onglet=etapes"))
    assert "exige une inspection indépendante conforme" in h and one("SELECT status FROM steps WHERE id=?", crit[0])[0] == "declare"
    assert "Commander l&#39;inspection" in html(own.get(f"/chantiers/{pid}/etapes/{crit[0]}"))
    s.execute("UPDATE steps SET declared_at=?, owner_reminders=3 WHERE id=?", (ago(11), crit[0])); s.commit()
    assert job(A.auto_validate_steps)["bloquees"] == 1                        # pas de validation automatique non plus
    insp_id = None
    s.execute("INSERT INTO inspections (project_id, step_id, inspector_id, requested_by, status, verdict, created_at, done_at) "
              "VALUES (?,?,?,?,?,?,?,?)", (pid, crit[0], one("SELECT id FROM users WHERE email='support@cv.ci'")[0],
                                         one("SELECT id FROM users WHERE email='a@x.ci'")[0], "realisee", "conforme",
                                         A.now_iso(), A.now_iso())); s.commit()
    post(own, f"/chantiers/{pid}/etapes/{crit[0]}/valider", dict(override="1"), f"/chantiers/{pid}?onglet=etapes")
    assert one("SELECT status FROM steps WHERE id=?", crit[0])[0] == "versement"
post(own, f"/chantiers/{pid}/reglages", dict(setting="inspection"), f"/chantiers/{pid}?onglet=dossier")
assert one("SELECT require_inspection FROM projects WHERE id=?", pid)[0] == 0
f = html(own.get("/chantiers/nouveau"))
assert 'name="require_inspection"' in f and "Recommandé." in f
print("inspection obligatoire réglable : bloque la validation manuelle et automatique des étapes critiques")

# --- 2. Un litige ouvert bloque la validation automatique ---
declare(steps[1], 8); checks_done(steps[1])
post(own, f"/chantiers/{pid}/litiges", dict(step_id=steps[1], subject="Fissures sur le mur",
                                            text="Fissures visibles sur le mur est, à reprendre avant validation."), f"/chantiers/{pid}")
did = one("SELECT id FROM disputes")[0]
assert job(A.auto_validate_steps)["validees"] == 0 and one("SELECT status FROM steps WHERE id=?", steps[1])[0] == "declare"
print("litige ouvert : pas de validation automatique")

# --- 3. Litige : echanges 5 jours, mediation, decision motivee, recours, decision finale ---
d = one("SELECT stage, respond_by FROM disputes WHERE id=?", did)
assert d[0] == "echanges" and (datetime.fromisoformat(d[1]) - datetime.now(timezone.utc)).days >= 4
h = html(chef.get(f"/litiges/{did}"))
assert "Pièces recevables" in h and "5 jours pour trouver un accord" in h and "Demander la médiation" in h
s.execute("UPDATE disputes SET respond_by=? WHERE id=?", (ago(1), did)); s.commit()
assert job(A.disputes_daily)["mediation"] == 1
assert one("SELECT stage FROM disputes WHERE id=?", did)[0] == "mediation" and notes("support@cv.ci", "Litige en médiation") == 1
assert post(chef, f"/litiges/{did}", dict(action="resolve", text="Je décide moi-même que c'est bon."), f"/litiges/{did}",
            follow=False).status_code == 302
assert one("SELECT status FROM disputes WHERE id=?", did)[0] == "ouvert"                 # le chef ne tranche pas
post(sup_staff, f"/litiges/{did}", dict(action="resolve", outcome="chef", amount="500000",
                                        text="Les photos vérifiées du chantier montrent un mur conforme ; fissures superficielles."),
     f"/litiges/{did}")
d = one("SELECT status, outcome, amount, appeal_until FROM disputes WHERE id=?", did)
assert d[:3] == ("resolu", "chef", 500000) and d[3]
assert one("SELECT staff_role FROM admin_log WHERE action='dispute_decision:chef'")[0] == "support"
assert "Torts" not in html(own.get(f"/litiges/{did}")) and "Faire un recours" in html(own.get(f"/litiges/{did}"))
assert "20 caractères" in html(post(own, f"/litiges/{did}", dict(action="appeal", text="Pas d'accord"), f"/litiges/{did}"))
post(own, f"/litiges/{did}", dict(action="appeal", text="Le rapport d'un bureau de contrôle, joint au dossier, montre des fissures structurelles."),
     f"/litiges/{did}")
assert one("SELECT status FROM disputes WHERE id=?", did)[0] == "en_appel" and notes("boss@cv.ci", "Recours sur un litige") == 1
assert post(sup_staff, f"/litiges/{did}", dict(action="final", text="Décision finale par le support"), f"/litiges/{did}",
            follow=False).status_code == 403
post(boss, f"/litiges/{did}", dict(action="final", text="Expertise demandée : paiement de 50 % maintenant, solde après reprise."),
     f"/litiges/{did}")
assert one("SELECT status, final_decision IS NOT NULL FROM disputes WHERE id=?", did)[:] == ("clos", 1)
assert "Décision finale" in html(chef.get(f"/litiges/{did}"))
# un second litige : decision sans recours -> clos apres 7 jours
declare(steps[2], 1)
post(chef, f"/chantiers/{pid}/litiges", dict(step_id=steps[2], subject="Validation bloquée",
                                             text="Étape terminée depuis longtemps, le propriétaire ne répond pas."), f"/chantiers/{pid}")
did2 = one("SELECT MAX(id) FROM disputes")[0]
post(chef, f"/litiges/{did2}", dict(action="mediation"), f"/litiges/{did2}")
assert one("SELECT stage FROM disputes WHERE id=?", did2)[0] == "mediation"
post(sup_staff, f"/litiges/{did2}", dict(action="resolve", outcome="partage", text="Chacun reprend sa part, validation ensuite."),
     f"/litiges/{did2}")
s.execute("UPDATE disputes SET appeal_until=? WHERE id=?", (ago(1), did2)); s.commit()
assert job(A.disputes_daily)["clos"] == 1 and one("SELECT status FROM disputes WHERE id=?", did2)[0] == "clos"
print("litiges : échanges 5 j, médiation, décision motivée, recours unique, décision finale du fondateur")


# --- 5. Inspection : l'inspecteur refuse -> retour a l'attribution ; annulation avant paiement ---
insp = register("i@x.ci", "inspecteur", zone="Bingerville", phone="0500000000")
insp2 = register("j@x.ci", "inspecteur", zone="Bingerville", phone="0500000001")
s.execute("UPDATE users SET verified=1 WHERE role='inspecteur'"); s.commit()
r = post(own, f"/chantiers/{pid}/inspections", dict(step_id=steps[3]), f"/chantiers/{pid}?onglet=dossier", follow=False)
inv = int(r.headers["Location"].split("/")[-1])
rid = one("SELECT id FROM inspection_requests WHERE invoice_id=?", inv)[0]
post(own, f"/inspections/demandes/{rid}/annuler", {}, f"/chantiers/{pid}?onglet=dossier")
assert one("SELECT status FROM inspection_requests WHERE id=?", rid)[0] == "annulee"
assert one("SELECT status FROM billing_invoices WHERE id=?", inv)[0] == "annulee"
r = post(own, f"/chantiers/{pid}/inspections", dict(step_id=steps[3]), f"/chantiers/{pid}?onglet=dossier", follow=False)
inv = int(r.headers["Location"].split("/")[-1])
post(own, f"/compte/factures/{inv}", {}, f"/compte/factures/{inv}")
rid = one("SELECT id FROM inspection_requests WHERE invoice_id=?", inv)[0]
assert notes("support@cv.ci", "Inspection à attribuer") == 1
i1 = one("SELECT id FROM users WHERE email='i@x.ci'")[0]
post(sup_staff, "/admin/inspections", dict(action="assign", id=rid, inspector_id=i1), "/admin")
iid = one("SELECT id FROM inspections WHERE request_id=?", rid)[0]
assert notes("a@x.ci", "Inspecteur attribué") == 1
assert "écrivez au support" in html(post(own, f"/inspections/{iid}/annuler", {}, f"/chantiers/{pid}?onglet=dossier"))
post(insp, f"/inspections/{iid}/reponse", dict(decision="refuser"))
assert one("SELECT status FROM inspection_requests WHERE id=?", rid)[0] == "a_attribuer"
i2 = one("SELECT id FROM users WHERE email='j@x.ci'")[0]
post(sup_staff, "/admin/inspections", dict(action="assign", id=rid, inspector_id=i2), "/admin")
assert one("SELECT inspector_id FROM inspections WHERE request_id=? AND status='demandee'", rid)[0] == i2
assert post(sup_staff, "/admin/inspections", dict(action="payout", id=iid, reference="X"), "/admin", follow=False).status_code == 403
print("inspection : annulation avant paiement, refus de l'inspecteur puis réattribution, versement réservé à la finance")

# --- 6. Conditions fournisseur : un fournisseur sans acceptation n'est pas propose ---
sup = register("depot@x.ci", "fournisseur", phone="0102030405", supplier_terms="1")
s.execute("UPDATE users SET verified=1, supplier_terms_at=NULL WHERE email='depot@x.ci'"); s.commit()
assert "Acceptez les conditions fournisseur" in html(sup.get("/"))
assert "commission" in html(sup.get("/fournisseur/conditions"))
post(sup, "/fournisseur/conditions", dict(accept="1"), "/fournisseur/conditions")
assert one("SELECT supplier_terms_at FROM users WHERE email='depot@x.ci'")[0]
assert "Acceptées le" in html(sup.get("/fournisseur/conditions"))
print("conditions fournisseur : acceptation exigée avant d'être proposé aux chantiers")
print("TOUS LES TESTS RECOURS PASSENT")
