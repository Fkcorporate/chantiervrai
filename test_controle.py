"""Test de la phase « intelligence et controle » : calculateur, stock, controles obligatoires,
circuit de paiement a deux niveaux, situation des travaux, indice de confiance.
Lancement : python3 test_controle.py   (PostgreSQL : DATABASE_URL=postgresql://... python3 test_controle.py)
"""
import io, os, re, sys, tempfile
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_controle_")
if os.environ.get("DATABASE_URL", "").startswith("postgres"):
    from services import db as _DB
    try:
        import psycopg  # noqa: F401
    except ImportError:
        from tests_support import pgwire
        _DB.set_driver(pgwire)
    _c = _DB.connect("")
    _c.execute("DROP SCHEMA public CASCADE"); _c.execute("CREATE SCHEMA public"); _c.commit(); _c.close()

import numpy as np
from PIL import Image
import app as A
from services import calc as CALC, trust as TRUST

A.app.config["TESTING"] = True
SITE = (5.3521, -3.8892)
PW = "Bingerville-2026"
own, chef, fin, ctrl, other = (A.app.test_client() for _ in range(5))
s = A.connect()


def tok(c, url="/"):
    m = re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True))
    assert m, url
    return m.group(1)


def post(c, url, data, page="/", follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)


def html(r):
    return r.get_data(as_text=True)


def one(sql, *a):
    return s.execute(sql, a).fetchone()


def jpg(seed):
    b = io.BytesIO()
    Image.fromarray(np.random.default_rng(seed).integers(0, 255, (240, 320, 3), dtype=np.uint8)).save(b, "JPEG")
    return b.getvalue()


now_ms = lambda: datetime.now(timezone.utc).timestamp() * 1000

# --- 1. Calculateur : formules ---
r = CALC.compute("beton", {"element": "poteau", "count": "10", "long": "3", "larg": "0.2", "haut": "0.2", "dosage": "350", "pertes": "5"})
q = {m: v for m, _u, v in r["lines"]}
assert r["details"][0][1] == "1.20 m³" and q["Ciment"] == 9 and q["Sable"] == 0.6 and q["Gravier"] == 1.1 and q["Eau"] == 221, r
r = CALC.compute("fer", {"diam": "10", "lng": "240", "pertes": "10"})
assert r["lines"] == [("Fer à béton", "barre", 22)] and "163 kg" in r["details"][-1][1], r
r = CALC.compute("maconnerie", {"long": "40", "haut": "3", "ouv": "10", "parpaing": "15", "pertes": "5"})
q = {m: v for m, _u, v in r["lines"]}
assert q["Parpaings"] == 1444 and q["Ciment"] == 13, q        # 110 m2 x 12,5 x 1,05 ; 1,73 m3 de mortier a 350 kg
r = CALC.compute("parpaings", {"nombre": "1000", "parpaing": "15", "pertes": "5"})
assert dict((m, v) for m, _u, v in r["lines"])["Ciment"] == 30
r = CALC.compute("fondation", {"long": "60", "larg": "0.6", "haut": "0.3", "prof": "0.8", "prop": "0.05", "dosage": "300", "pertes": "5"})
assert r["details"][0][1] == "38.4 m³" and dict((m, v) for m, _u, v in r["lines"])["Ciment"] == 6 + 69
assert CALC.compute("peinture", {"surface": "200", "couches": "2", "rend": "10", "pertes": "5"})["lines"] == [("Peinture", "L", 42)]
assert CALC.compute("carrelage", {"long": "5", "larg": "4", "pieces": "2", "pertes": "10"})["lines"][0] == ("Carreaux", "m²", 44)
assert CALC.compute("beton", {"long": "-3", "larg": "x"})["lines"] == []          # saisie invalide : rien, pas d'erreur
assert CALC.compute("inconnu", {}) is None
h = html(A.app.test_client().get("/calculateur?type=beton&go=1&count=4&long=3&larg=0.25&haut=0.25&dosage=350&pertes=5"))
assert "À acheter" in h and "ingénieur" in h
print("calculateur ok")

# --- 2. Comptes, chantier, controleur habilite et responsable financier ---
def register(c, email, role, **extra):
    r_ = post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW, **extra),
              "/inscription", follow=False)
    assert r_.status_code == 302, email


register(own, "a@x.ci", "proprio"); register(chef, "k@x.ci", "chef", phone="0700000000")
register(fin, "f@x.ci", "proprio"); register(ctrl, "bureau@x.ci", "inspecteur", zone="Abidjan", tarif="50000")
register(other, "o@x.ci", "inspecteur")
ctrl_id = one("SELECT id FROM users WHERE email='bureau@x.ci'")[0]
fin_id = one("SELECT id FROM users WHERE email='f@x.ci'")[0]
data = dict(name="Villa", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="manuel",
            start_date=datetime.now().date().isoformat())
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
pid = int(post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])
code = re.search(r'class="code">(\w+)<', html(own.get(f"/chantiers/{pid}"))).group(1)
post(chef, "/rejoindre", dict(code=code))
steps = s.execute("SELECT * FROM steps WHERE project_id=? ORDER BY position", (pid,)).fetchall()
st1 = steps[0]
dossier = f"/chantiers/{pid}?onglet=dossier"
assert "Inspecteurs vérifié" not in html(post(own, f"/chantiers/{pid}/membres", dict(email="bureau@x.ci", role="controleur"), dossier))
assert one("SELECT COUNT(*) FROM project_members WHERE project_id=?", pid)[0] == 0          # pas encore verifie
s.execute("UPDATE users SET verified=1 WHERE id=?", (ctrl_id,)); s.commit()
assert "est ajouté au chantier" in html(post(own, f"/chantiers/{pid}/membres", dict(email="bureau@x.ci", role="controleur"), dossier))
assert "Aucun compte « Propriétaire »" in html(post(own, f"/chantiers/{pid}/membres", dict(email="o@x.ci", role="finance"), dossier))
post(own, f"/chantiers/{pid}/membres", dict(email="f@x.ci", role="finance"), dossier)
h = html(own.get(dossier))
assert "contrôleur habilité" in h and "responsable financier" in h
assert "Villa" in html(ctrl.get("/"))                                    # le controleur voit le chantier
assert ctrl.get(f"/chantiers/{pid}").status_code == 200 and other.get(f"/chantiers/{pid}").status_code == 403
p = one("SELECT * FROM projects WHERE id=?", pid)
with A.app.test_request_context():
    assert ctrl_id not in A.owners_of(p, s) and fin_id in A.owners_of(p, s)
print("intervenants : contrôleur habilité et responsable financier ok")

# --- 3. Calculateur sur le chantier -> prevu ; stock ---
cp = f"/chantiers/{pid}/calculateur"
assert chef.get(cp).status_code == 200 and ctrl.get(cp).status_code == 403
r = post(own, cp, dict(type="fondation", go="1", long="60", larg="0.6", haut="0.3", prof="0.8", prop="0.05", dosage="300",
                       pertes="5", step_id=st1["id"]), cp)
assert "Quantités ajoutées au prévu" in html(r)
post(own, cp, dict(type="fer", go="1", diam="10", lng="240", pertes="10", step_id=st1["id"]), cp)
plan = {r_["material"]: r_["qty_planned"] for r_ in s.execute("SELECT * FROM materials_plan WHERE step_id=?", (st1["id"],))}
assert plan == {"Ciment": 75, "Sable": 6.2, "Gravier": 10.8, "Fer à béton": 22}, plan    # l eau n est pas un achat
sp = f"/chantiers/{pid}/stock"
post(chef, sp, dict(action="entree", material="ciment", qty="60", unit="sac", step_id=st1["id"], note="BL 4512"), sp)
post(chef, sp, dict(action="seuil", material="Ciment", qty="15"), sp)
post(chef, sp, dict(action="sortie", material="Ciment", qty="40", step_id=st1["id"]), sp)
assert one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Stock bas%'")[0] == 0
post(chef, sp, dict(action="sortie", material="Ciment", qty="8", step_id=st1["id"]), sp)          # 12 restants <= 15
assert one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Stock bas%' AND channel='app'")[0] == 3   # proprio, finance, chef
h = html(own.get(sp))
assert "Stock bas : à recommander" in h and "BL 4512" in h
post(chef, sp, dict(action="inventaire", material="Ciment", qty="9"), sp)           # il en manque 3
assert one("SELECT qty FROM stock_moves WHERE kind='inventaire'")[0] == -3
assert one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Écart d%inventaire%' AND channel='app'")[0] >= 1
post(chef, sp, dict(action="sortie", material="Fer à béton", qty="5", unit="barre"), sp)
with A.app.test_request_context():
    table, alerts = A.stock_summary(s, pid)
rows = {r_["material"]: r_ for r_ in table}
assert rows["Ciment"]["available"] == 9 and rows["Ciment"]["planned"] == 75
assert any("Plus consommé que livré" in a_ for a_ in alerts), alerts
assert ctrl.get(sp).status_code == 200 and "Enregistrer un mouvement" not in html(ctrl.get(sp))
assert post(ctrl, sp, dict(action="sortie", material="Ciment", qty="1"), sp).status_code == 403
assert "Indiquez le matériau" in html(post(chef, sp, dict(action="sortie", material="Ciment", qty="-2"), sp))
print("calculateur sur le chantier, stock, ruptures et inventaire ok")

# --- 4. Controles obligatoires : bibliotheque, blocage, personne habilitee ---
checks = s.execute("SELECT * FROM step_checks WHERE step_id=? ORDER BY id", (st1["id"],)).fetchall()
names = [A.I18N.render(c["name"]) for c in checks]
assert any("ferraillage" in n for n in names) and any(c["kind"] == "essai" and c["min_value"] == 20 for c in checks), names
req = [c for c in checks if c["required"]]
assert len(req) == 2
tk = re.search(r'name="capture_token" value="([^"]+)"', html(chef.get(f"/chantiers/{pid}"))).group(1)
d = dict(tz_offset="0", lat=str(SITE[0]), lng=str(SITE[1]), photo=(io.BytesIO(jpg(1)), "c.jpg"), capture="app",
         capture_token=tk, captured_at=str(now_ms()), client_now=str(now_ms()))
assert "vérifiée" in html(post(chef, f"/chantiers/{pid}/preuves", d, f"/chantiers/{pid}", files=True))
post(chef, f"/chantiers/{pid}/etapes/{st1['id']}/declarer", {}, f"/chantiers/{pid}")
assert one("SELECT status FROM steps WHERE id=?", st1["id"])[0] == "declare"
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=? AND title LIKE '%Contrôle demandé%' AND channel='app'", ctrl_id)[0] == 1
etapes = f"/chantiers/{pid}?onglet=etapes"
assert "Vérifier avant de payer" in html(own.get(etapes)) and "obligatoire à faire" in html(own.get(etapes))
h = html(post(own, f"/chantiers/{pid}/etapes/{st1['id']}/valider", {}, etapes))
assert "Validation impossible : 2 contrôles obligatoires manquants" in h, h[:3000]
assert one("SELECT status FROM steps WHERE id=?", st1["id"])[0] == "declare"
stp = f"/chantiers/{pid}/etapes/{st1['id']}"
act = f"{stp}/controles"
h = html(own.get(stp))
assert "Paiement bloqué" in h and "Vérification avant paiement" in h and "1. Montant prévu au contrat" in h
assert "Seul un contrôleur habilité" in html(post(own, act, dict(action="result", check_id=req[0]["id"], status="conforme"), stp))
assert "Seul un contrôleur habilité" in html(post(chef, act, dict(action="result", check_id=req[0]["id"], status="conforme"), stp))
assert "Expliquez la non-conformité" in html(post(ctrl, act, dict(action="result", check_id=req[0]["id"], status="non_conforme"), stp))
post(ctrl, act, dict(action="result", check_id=req[0]["id"], status="non_conforme", note="Enrobage insuffisant côté nord"), stp)
assert one("SELECT status FROM step_checks WHERE id=?", req[0]["id"])[0] == "non_conforme"
assert one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Non-conformité%' AND channel='app'")[0] >= 1
post(ctrl, act, dict(action="result", check_id=req[0]["id"], status="conforme", note="Corrigé",
                     file=(io.BytesIO(b"%PDF-1.4 rapport"), "pv.pdf")), stp, files=True)
c0 = one("SELECT * FROM step_checks WHERE id=?", req[0]["id"])
assert c0["status"] == "conforme" and c0["checked_by"] == ctrl_id and c0["doc_id"]
assert one("SELECT category FROM documents WHERE id=?", c0["doc_id"])[0] == "Contrôle technique"
essai = next(c for c in checks if c["kind"] == "essai")
post(ctrl, act, dict(action="result", check_id=essai["id"], value="17,5"), stp)
assert tuple(one("SELECT status, value FROM step_checks WHERE id=?", essai["id"])) == ("non_conforme", 17.5)
post(ctrl, act, dict(action="add", name="Contrôle de l'étanchéité du regard", kind="visuel", required="1"), stp)
assert one("SELECT COUNT(*) FROM step_checks WHERE step_id=?", st1["id"])[0] == 4
# le proprietaire rend un controle facultatif : note dans l'historique
assert "Seul le propriétaire principal" in html(post(fin, act, dict(action="optional", check_id=req[1]["id"]), stp))
post(own, act, dict(action="optional", check_id=req[1]["id"]), stp)
assert tuple(one("SELECT required, made_optional FROM step_checks WHERE id=?", req[1]["id"])) == (0, 1)
assert one("SELECT COUNT(*) FROM activity WHERE project_id=? AND text LIKE '%facultatif%'", pid)[0] == 1
added = one("SELECT id FROM step_checks WHERE step_id=? ORDER BY id DESC", st1["id"])[0]
post(ctrl, act, dict(action="result", check_id=added, status="conforme"), stp)
assert post(chef, act, dict(action="demander"), stp).status_code == 200
print("contrôles obligatoires : bibliothèque, blocage, contrôleur habilité, essai béton ok")

# --- 5. Circuit a deux niveaux : maitre d'ouvrage puis responsable financier ---
h = html(post(fin, f"/chantiers/{pid}/etapes/{st1['id']}/valider", {}, stp))
assert "maître d&#39;ouvrage doit d&#39;abord approuver" in h, h[:2000]
h = html(post(own, f"/chantiers/{pid}/etapes/{st1['id']}/valider", {}, stp))
assert "Le responsable financier va vérifier et payer" in h
assert one("SELECT status FROM steps WHERE id=?", st1["id"])[0] == "declare"
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=? AND title LIKE '%Paiement à valider%' AND channel='app'", fin_id)[0] == 1
assert "déjà approuvée" in html(post(own, f"/chantiers/{pid}/etapes/{st1['id']}/valider", {}, stp))
assert "Approuvée par A" in html(fin.get(stp))
post(fin, f"/chantiers/{pid}/etapes/{st1['id']}/valider", dict(pay_ref="WAVE-889"), stp)
st = one("SELECT * FROM steps WHERE id=?", st1["id"])
assert st["status"] == "paye" and st["pay_ref"] == "WAVE-889"
assert [r_["level"] for r_ in s.execute("SELECT level FROM payment_approvals WHERE step_id=? ORDER BY id", (st1["id"],))] == ["ouvrage", "finance"]
print("circuit de paiement à deux niveaux ok")

# --- 5b. Derogation du proprietaire (chantier prive, sans responsable financier) ---
st2 = steps[1]
tk = re.search(r'name="capture_token" value="([^"]+)"', html(chef.get(f"/chantiers/{pid}"))).group(1)
d = dict(tz_offset="0", lat=str(SITE[0]), lng=str(SITE[1]), photo=(io.BytesIO(jpg(2)), "c.jpg"), capture="app",
         capture_token=tk, captured_at=str(now_ms()), client_now=str(now_ms()))
post(chef, f"/chantiers/{pid}/preuves", d, f"/chantiers/{pid}", files=True)
post(chef, f"/chantiers/{pid}/etapes/{st2['id']}/declarer", {}, f"/chantiers/{pid}")
stp2 = f"/chantiers/{pid}/etapes/{st2['id']}"
assert "Valider quand même" not in html(own.get(stp2))                 # pas avec un responsable financier
post(own, f"/chantiers/{pid}/membres", dict(action="remove", user_id=fin_id), dossier)
s.execute("UPDATE projects SET kind='public' WHERE id=?", (pid,)); s.commit()
assert "Valider quand même" not in html(own.get(stp2))
assert "Validation impossible" in html(post(own, f"/chantiers/{pid}/etapes/{st2['id']}/valider", {"override": "1"}, stp2))
s.execute("UPDATE projects SET kind='prive' WHERE id=?", (pid,)); s.commit()
assert "Valider quand même" in html(own.get(stp2))
post(own, f"/chantiers/{pid}/etapes/{st2['id']}/valider", {"override": "1", "pay_ref": "OM-1"}, stp2)
assert one("SELECT status FROM steps WHERE id=?", st2["id"])[0] == "paye"
assert one("SELECT COUNT(*) FROM activity WHERE project_id=? AND text LIKE '%sans %(n)s%'", pid)[0] == 1, \
    s.execute("SELECT text FROM activity WHERE project_id=? ORDER BY id DESC LIMIT 3", (pid,)).fetchall()
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=? AND title LIKE '%sans contrôle%' AND channel='app'", ctrl_id)[0] == 1
print("dérogation du propriétaire ok (notée, signalée, interdite sur les marchés publics)")

# --- 6. Situation des travaux et indice de confiance ---
h = html(own.get(f"/chantiers/{pid}/decompte"))
assert "Situation des travaux et décompte" in h and "WAVE-889" in h and "3 000 000" in h
assert chef.get(f"/chantiers/{pid}/decompte").status_code == 200
with A.app.test_request_context():
    t = A.project_trust(one("SELECT * FROM projects WHERE id=?", pid), db=s)
crit = {c["key"]: c for c in t["criteria"]}
assert t["score"] is not None and 0 <= t["score"] <= 100
assert crit["procedures"]["score"] == 70, crit["procedures"]           # 3 controles rendus facultatifs
assert crit["conformite"]["score"] == 75, crit["conformite"]           # essai beton non conforme
assert crit["depenses"]["score"] < 100                                  # ecarts de stock
h = html(own.get(f"/chantiers/{pid}/confiance"))
assert "Indice de confiance du chantier" in h and "pas une certification" in h and "Respect des procédures de contrôle" in h
assert "Indice de confiance" in html(own.get(f"/chantiers/{pid}"))
# les poids : un chantier vide n'a pas de score ; un critere sans donnees est ecarte
base = (dict(declared_pct=0, verified_pct=0, ai_doubtful=0, delay=None, has_material_data=False, material_alerts=0,
                           stock_alerts=0, unpaid_orders=0, proofs_total=0, refused=0, days_silent=None, started=False,
                           checks_total=0, paid_without_checks=0, checks_made_optional=0, checks_overdue=0, checks_done=0,
                           checks_nonconform=0, inspections_done=0, inspections_nc=0, inspections_reserves=0))
empty = TRUST.compute(base)
assert empty["score"] is None and empty["level"] == "none"
paid_wo = TRUST.compute(dict(base, declared_pct=50, verified_pct=50, started=True, checks_total=3, paid_without_checks=1,
                             proofs_total=4, days_silent=2))
assert {c["key"]: c["score"] for c in paid_wo["criteria"]}["procedures"] == 70
print("situation des travaux et indice de confiance ok")

# --- 7. API mobile : indice de confiance et controles ---
cli = A.app.test_client()
tk_own = cli.post("/api/v1/connexion", json=dict(email="a@x.ci", password=PW)).json["token"]
j = cli.get(f"/api/v1/chantiers/{pid}", headers={"Authorization": f"Bearer {tk_own}"}).json["project"]
assert j["trust"]["score"] == t["score"] and len(j["trust"]["criteria"]) == 6
assert any(c["status"] == "non_conforme" and c["value"] == 17.5 for c in j["checks"])
print("API ok")

# --- 8. Anglais ---
own.get("/?lang=en")
assert "Material calculator" in html(own.get(cp)) and "Stock and materials" in html(own.get(sp)) and "Footings" not in html(own.get(sp))
assert "Site trust index" in html(own.get(f"/chantiers/{pid}/confiance"))
print("anglais ok")
print("\nTOUS LES TESTS DE CONTRÔLE PASSENT")
