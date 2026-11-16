"""Test des blocs 6 a 9 : fiche du projet et parcelle, profils professionnels, maquette IFC, capteurs,
images tres haute resolution, export comptable, Academie du BTP.
Lancement : python3 test_avance.py   (PostgreSQL : DATABASE_URL=postgresql://... python3 test_avance.py)
"""
import io, json, os, re, sys, tempfile
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_avance_")
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
from services import geo as GEO, ifc as IFC, academy as ACAD

A.app.config["TESTING"] = True
SITE = (5.3521, -3.8892)
PW = "Bingerville-2026"
own, chef, arch, ing, compta, cond, adm = (A.app.test_client() for _ in range(7))
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

# --- 1. Geometrie de la parcelle ---
sq = [[5.3523, -3.8894], [5.3523, -3.8890], [5.3519, -3.8890], [5.3519, -3.8894]]     # ~44 m x 44 m
assert GEO.contains(sq, 5.3521, -3.8892) and not GEO.contains(sq, 5.3530, -3.8892)
assert 1800 < GEO.area_m2(sq) < 2100, GEO.area_m2(sq)
assert GEO.distance_m(sq, 5.3521, -3.8892) == 0 and 95 < GEO.distance_m(sq, 5.3532, -3.8892) < 105
assert GEO.parse("[[1,2],[3,4]]") is None and GEO.parse("nope") is None and GEO.parse([[91, 0], [0, 0], [1, 1]]) is None
print("géométrie de la parcelle ok")

# --- 2. Comptes professionnels et roles sur le chantier ---
def register(c, email, role, **extra):
    r_ = post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW, **extra),
              "/inscription", follow=False)
    return r_


assert register(own, "a@x.ci", "proprio").status_code == 302
register(chef, "k@x.ci", "chef", phone="0700000000")
assert "Choisissez votre métier" in html(post(A.app.test_client(), "/inscription", dict(terms="1", role="pro", name="X", email="x@x.ci",
                                                                                     password=PW), "/inscription"))
for c, e, prof in ((arch, "arch@x.ci", "architecte"), (ing, "ing@x.ci", "ingenieur"), (compta, "compta@x.ci", "comptable"),
                   (cond, "cond@x.ci", "conducteur")):
    assert register(c, e, "pro", profession=prof, company="Cabinet " + prof).status_code == 302
assert one("SELECT profession FROM users WHERE email='ing@x.ci'")[0] == "ingenieur"
register(adm, "admin@x.ci", "proprio")
A.app.test_cli_runner().invoke(args=["creer-admin", "admin@x.ci"])
data = dict(name="Immeuble", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="manuel",
            start_date=datetime.now().date().isoformat())
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
pid = int(post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])
code = re.search(r'class="code">(\w+)<', html(own.get(f"/chantiers/{pid}"))).group(1)
post(chef, "/rejoindre", dict(code=code))
dossier = f"/chantiers/{pid}?onglet=dossier"
mem = f"/chantiers/{pid}/membres"
assert "Aucun compte « Professionnel du BTP »" in html(post(own, mem, dict(email="a@x.ci", role="architecte"), dossier))
post(own, mem, dict(email="arch@x.ci", role="architecte"), dossier)
assert "Aucun compte vérifié de ce métier" in html(post(own, mem, dict(email="ing@x.ci", role="ingenieur"), dossier))
assert "ING" in html(adm.get("/admin"))                                       # ingenieur a verifier
ing_id = one("SELECT id FROM users WHERE email='ing@x.ci'")[0]
post(adm, "/admin/action", dict(action="verify", id=ing_id), "/admin")
assert one("SELECT verified FROM users WHERE id=?", ing_id)[0] == 1
post(own, mem, dict(email="ing@x.ci", role="ingenieur"), dossier)
assert "Aucun compte vérifié de ce métier" in html(post(own, mem, dict(email="arch@x.ci", role="controleur"), dossier))
post(own, mem, dict(email="compta@x.ci", role="comptable"), dossier)
post(own, mem, dict(email="cond@x.ci", role="conducteur"), dossier)
assert one("SELECT COUNT(*) FROM project_members WHERE project_id=?", pid)[0] == 4
p = one("SELECT * FROM projects WHERE id=?", pid)
assert A.owners_of(p, s) == [p["owner_id"]]                                   # les professionnels ne sont pas proprietaires
for c in (arch, ing, compta, cond):
    assert "Immeuble" in html(c.get("/"))
h = html(arch.get(f"/chantiers/{pid}"))
assert "Architecte" in h and "Ajouter un plan ou un document" in h and "Export comptable" not in h
assert "Contrôles techniques" in html(ing.get(f"/chantiers/{pid}/etapes/{one('SELECT id FROM steps WHERE project_id=? ORDER BY position', pid)[0]}"))
assert "Saisir le résultat" in html(ing.get(f"/chantiers/{pid}/etapes/{one('SELECT id FROM steps WHERE project_id=? ORDER BY position', pid)[0]}"))
assert compta.get(f"/chantiers/{pid}/decompte").status_code == 200 and arch.get(f"/chantiers/{pid}/decompte").status_code == 403
assert arch.get(f"/chantiers/{pid}/stock").status_code == 403 and "Enregistrer un mouvement" in html(cond.get(f"/chantiers/{pid}/stock"))
post(cond, f"/chantiers/{pid}/stock", dict(action="entree", material="Ciment", qty="40", unit="sac"), f"/chantiers/{pid}/stock")
assert one("SELECT COUNT(*) FROM stock_moves WHERE project_id=?", pid)[0] == 1
assert compta.get(f"/chantiers/{pid}?onglet=etapes").status_code == 200
assert post(compta, f"/chantiers/{pid}/etapes/1/valider", {}, f"/chantiers/{pid}").status_code == 403
post(arch, f"/chantiers/{pid}/documents", dict(category="Plan", title="Plans RDC", file=(io.BytesIO(b"%PDF plans"), "rdc.pdf")),
     f"/chantiers/{pid}", files=True)
doc = one("SELECT * FROM documents WHERE project_id=? AND category='Plan'", pid)
assert doc and arch.get(f"/documents/{doc['id']}").status_code == 200
assert post(compta, f"/chantiers/{pid}/documents", dict(category="Plan", title="x", file=(io.BytesIO(b"x"), "x.pdf")),
            f"/chantiers/{pid}", files=True).status_code == 403
tk_arch = A.app.test_client().post("/api/v1/connexion", json=dict(email="arch@x.ci", password=PW)).json["token"]
j = A.app.test_client().get(f"/api/v1/chantiers/{pid}", headers={"Authorization": f"Bearer {tk_arch}"}).json
assert j["project"]["role"] == "intervenant" and "trust" not in j["project"]
print("profils professionnels : architecte, ingénieur vérifié, comptable, conducteur ok")

# --- 3. Fiche du projet et parcelle : controle GPS sur la parcelle ---
sheet = f"/chantiers/{pid}/fiche"
for c in (own, chef, arch, compta):
    assert c.get(sheet).status_code == 200
assert post(chef, sheet, dict(building_type="immeuble"), sheet).status_code == 403
assert "Parcelle invalide" in html(post(own, sheet, dict(parcel="[[5.35,-3.88]]"), sheet))
assert "plus de 5 km" in html(post(own, sheet, dict(parcel=json.dumps([[6.0, -3.0], [6.0, -3.01], [6.01, -3.01]])), sheet))
r = post(own, sheet, dict(building_type="immeuble", levels="3", surface_land="1900", surface_floor="1200", land_title="TF 9921",
                          land_ref="Lot 3", commune="Bingerville", permit_ref="PC 1/2026", parcel=json.dumps(sq)), sheet)
assert "Fiche du projet enregistrée" in html(r)
h = html(own.get(sheet))
assert "Immeuble (R+1 et plus)" in h and "R+3" in h and "TF 9921" in h and "ARCH" in h and "Plans RDC" in h
p = one("SELECT * FROM projects WHERE id=?", pid)
assert A.site_distance(p, 5.3521, -3.8892) == (0, 30, True)
assert A.site_distance(p, 5.3532, -3.8892)[0] > 90
tk = re.search(r'name="capture_token" value="([^"]+)"', html(chef.get(f"/chantiers/{pid}"))).group(1)


def proof(lat, lng, seed):
    d = dict(tz_offset="0", lat=str(lat), lng=str(lng), photo=(io.BytesIO(jpg(seed)), "c.jpg"), capture="app",
             capture_token=tk, captured_at=str(now_ms()), client_now=str(now_ms()))
    return html(post(chef, f"/chantiers/{pid}/preuves", d, f"/chantiers/{pid}", files=True))


assert "de la parcelle (limite 30 m)" in proof(5.3527, -3.8892, 1)            # ~44 m au nord du bord : refusee
assert "vérifiée" in proof(5.35225, -3.88925, 2)                              # dans la parcelle
assert one("SELECT COUNT(*) FROM activity WHERE project_id=? AND text LIKE '%Parcelle dessinée%'", pid)[0] == 1
print("fiche du projet et contrôle GPS sur la parcelle ok")

# --- 4. Maquette IFC : versions, niveaux, liens, modifications ---
bim = f"/chantiers/{pid}/maquette"
assert "Choisissez un fichier IFC" in html(post(arch, bim, dict(action="upload", file=(io.BytesIO(b"x"), "plan.pdf")), bim, files=True))
assert "pas une maquette IFC" in html(post(arch, bim, dict(action="upload", file=(io.BytesIO(b"hello"), "m.ifc")), bim, files=True))
assert post(compta, bim, dict(action="upload", file=(io.BytesIO(IFC.sample(3).encode()), "m.ifc")), bim, files=True).status_code == 403
post(arch, bim, dict(action="upload", note="Permis", file=(io.BytesIO(IFC.sample(3).encode()), "immeuble.ifc")), bim, files=True)
m1 = one("SELECT * FROM bim_models WHERE project_id=?", pid)
summ = json.loads(m1["summary"])
assert [x["name"] for x in summ["storeys"]] == ["Fondations", "Rez-de-chaussée", "Étage 1", "Étage 2", "Toiture"]
assert summ["totals"]["Poteaux"] == 36 and summ["volume"] > 0
links = {r_["storey"]: r_["step_id"] for r_ in s.execute("SELECT * FROM bim_storeys WHERE project_id=?", (pid,))}
st_by = {r_["id"]: r_["name"] for r_ in s.execute("SELECT * FROM steps WHERE project_id=?", (pid,))}
assert st_by.get(links.get("Fondations")) == "Fondations", links         # liaison automatique par le nom
h = html(own.get(bim))
assert "Éléments par niveau" in h and "Rez-de-chaussée" in h and "12 poteaux" in h
post(arch, bim, dict(action="upload", note="Terrasse", file=(io.BytesIO(IFC.sample(3, extra_columns=2).encode()), "v2.ifc")), bim, files=True)
h = html(own.get(bim))
assert "Modifications par rapport à la version 1" in h and "+2 poteaux" in h, h[h.find("Modifications"):][:600]
assert one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Nouvelle version de la maquette%' AND channel='app'")[0] >= 1
steps = s.execute("SELECT * FROM steps WHERE project_id=? ORDER BY position", (pid,)).fetchall()
post(own, bim, {"action": "link", "storey_Étage 1": steps[2]["id"]}, bim)
assert one("SELECT step_id FROM bim_storeys WHERE project_id=? AND storey='Étage 1'", pid)[0] == steps[2]["id"]
assert post(arch, bim, {"action": "link", "storey_Étage 1": ""}, bim).status_code == 403
m2 = one("SELECT id FROM bim_models WHERE project_id=? AND version=2", pid)[0]
r = ing.get(f"/maquettes/{m2}")
assert r.status_code == 200 and b"ISO-10303-21" in r.data
print("maquette IFC : niveaux, liens, versions et modifications ok")

# --- 5. Capteurs : ajout, envoi de mesures, alerte, meteo ---
sp = f"/chantiers/{pid}/capteurs"
assert post(compta, sp, dict(action="add", kind="vibration", name="X"), sp).status_code == 403
post(own, sp, dict(action="add", kind="deformation", name="Fissuromètre façade"), sp)
post(ing, sp, dict(action="add", kind="humidite", name="Humidité dalle"), sp)
sn = one("SELECT * FROM sensors WHERE project_id=? AND kind='deformation'", pid)
assert (sn["min_value"], sn["max_value"], sn["unit"]) == (-2, 2, "mm")
cli = A.app.test_client()
assert cli.post("/api/v1/capteurs/mesures", json={"value": 1}).status_code == 401
r = cli.post("/api/v1/capteurs/mesures", json={"value": 0.4}, headers={"X-Sensor-Key": sn["token"]})
assert r.json == {"ok": True, "received": 1, "alarms": 0}
r = cli.post("/api/v1/capteurs/mesures", json={"readings": [{"value": 1.1, "at": "2026-11-13T10:00:00Z"}, {"value": 2.6}, {"value": 2.9},
                                                            {"value": "x"}]}, headers={"X-Sensor-Key": sn["token"]})
assert r.json["received"] == 3 and r.json["alarms"] == 2
assert one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Alerte capteur%' AND channel='app'")[0] == 3   # proprio, chef, ingenieur ; une fois
sn = one("SELECT * FROM sensors WHERE id=?", sn["id"])
assert sn["alarm"] == 1 and sn["last_value"] == 2.9
cli.post(f"/api/v1/capteurs/mesures?cle={sn['token']}", json={"value": 0.5})
assert one("SELECT alarm FROM sensors WHERE id=?", sn["id"])[0] == 0
h = html(own.get(sp))
assert "Fissuromètre façade" in h and "polyline" in h and sn["token"] in h
assert sn["token"] not in html(compta.get(sp))                                 # la cle n'est pas montree aux autres
post(own, sp, dict(action="mesure", sensor_id=sn["id"], value="3.5"), sp)
assert one("SELECT alarm FROM sensors WHERE id=?", sn["id"])[0] == 1
assert A.daily_weather(s) == 0                                                # meteo automatique desactivee par defaut
print("capteurs : mesures, alertes, seuils ok")

# --- 6. Images tres haute resolution ---
post(own, f"/chantiers/{pid}/images-thr", dict(provider="pleiades", note="Après la dalle"), dossier)
o = one("SELECT * FROM imagery_orders WHERE project_id=?", pid)
assert o["status"] == "demandee"
assert "déjà en cours" in html(post(own, f"/chantiers/{pid}/images-thr", dict(provider="skysat"), dossier))
assert "Pléiades Neo" in html(adm.get("/admin"))
assert post(own, f"/admin/images-thr/{o['id']}", dict(month="2026-11"), "/").status_code == 403
b = io.BytesIO(); Image.new("RGB", (400, 400), (120, 110, 90)).save(b, "PNG"); b.seek(0)
post(adm, f"/admin/images-thr/{o['id']}", dict(action="deliver", month="2026-11", file=(b, "pleiades.png")), "/admin", files=True)
o = one("SELECT * FROM imagery_orders WHERE id=?", o["id"])
assert o["status"] == "livree" and o["sat_image_id"]
assert one("SELECT layer FROM sat_images WHERE id=?", o["sat_image_id"])[0] == "thr"
h = html(own.get(f"/chantiers/{pid}?onglet=vues&couche=thr"))
assert "30 à 50 cm par pixel" in h and "Livrée" in h
print("images très haute résolution : demande, livraison, affichage ok")

# --- 7. Export comptable ---
s.execute("UPDATE steps SET status='paye', paid_at=?, pay_ref='OM-77' WHERE id=?", (A.now_iso(), steps[0]["id"])); s.commit()
r = compta.get(f"/chantiers/{pid}/export-comptable.csv")
assert r.status_code == 200 and r.mimetype == "text/csv"
txt = r.data.decode("utf-8-sig")
assert txt.splitlines()[0].startswith("Date;Journal;Libellé") and "OM-77" in txt and "Fondations" in txt
assert arch.get(f"/chantiers/{pid}/export-comptable.csv").status_code == 403
assert own.get(f"/chantiers/{pid}/export-comptable.csv").status_code == 200
print("export comptable ok")

# --- 8. Academie : cours, quiz, progression, assistant ---
assert len(ACAD.COURSES) == 13
for c in ACAD.COURSES:
    for lang in ("fr", "en"):
        cc = ACAD.course(c["slug"], lang)
        assert cc["title"] and len(cc["sections"]) >= 4 and len(cc["checklist"]) >= 5 and len(cc["quiz"]) == 3
        assert all(0 <= q["answer"] < len(q["options"]) for q in cc["quiz"])
    assert c["calc"] is None or c["calc"] in A.CALC.TYPES
anon = A.app.test_client()
h = html(anon.get("/academie"))
assert "Comment construire une maison ?" in h and "Comment contrôler un entrepreneur ?" in h
h = html(anon.get("/academie?q=combien+de+sacs+de+ciment+pour+un+m%C3%A8tre+cube"))
assert "Comment doser le ciment ?" in h
h = html(anon.get("/academie?q=quelle+section+de+poutre+et+quel+diam%C3%A8tre+de+fer"))
assert "Question de structure" in h
course = "/academie/doser-le-ciment"
h = html(post(anon, course, dict(q0="1", q1="2", q2="0"), course))
assert "2 / 3" in h and "Connectez-vous" in h
h = html(post(own, course, dict(q0="1", q1="2", q2="1"), course))
assert "3 / 3" in h
assert one("SELECT score, total FROM academy_progress WHERE course='doser-le-ciment'")[0] == 3
assert "100 %" in html(own.get("/academie"))
assert anon.get("/academie/inconnu").status_code == 404
anon.get("/?lang=en")
h = html(anon.get("/academie/plan-de-ferraillage"))
assert "Understanding a reinforcement drawing" in h and "Checklist" in h and "concrete cover" in h.lower()
print("Académie : 13 cours FR/EN, quiz, progression, assistant ok")

# --- 9. Anglais ---
own.get("/?lang=en")
assert "Project sheet" in html(own.get(sheet)) and "Digital model" in html(own.get(bim)) and "Sensors and weather" in html(own.get(sp))
print("anglais ok")
print("\nTOUS LES TESTS DES BLOCS 6 À 9 PASSENT")
