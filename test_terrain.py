"""Test du suivi de terrain et de l'API ouverte : zones et etages, visites 360, quantites installees,
rapport d'avancement physique, cles d'API, webhooks signes.
Lancement : python3 test_terrain.py   (PostgreSQL : DATABASE_URL=postgresql://... python3 test_terrain.py)
"""
import hashlib, hmac, io, json, os, re, sys, tempfile
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_terrain_")
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
from services import ifc as IFC, webhooks as HOOKS, vision as VISION, demo as DEMO

A.app.config["TESTING"] = True
SITE = (5.3521, -3.8892)
PW = "Bingerville-2026"
own, own2, chef, insp = (A.app.test_client() for _ in range(4))
s = A.connect()
sent = []


def fake_send(url, body, headers, timeout=8):
    sent.append({"url": url, "body": body, "headers": headers})
    return 500 if "panne" in url else 200


HOOKS.send = fake_send


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


def pano_bytes(stage, seed, lat=SITE[0], lng=SITE[1], days=0, size=None):
    im = DEMO.pano(stage, seed)
    if size:
        im = im.resize(size)
    ex = Image.Exif()
    if lat is not None:
        dms = lambda v: (int(abs(v)), int(abs(v) * 60 % 60), round(abs(v) * 3600 % 60, 4))
        ex[0x8825] = {1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lng >= 0 else "W", 4: dms(lng)}
    ex[0x8769] = {0x9003: (datetime.now() - timedelta(days=days)).strftime("%Y:%m:%d %H:%M:%S")}
    b = io.BytesIO()
    im.save(b, "JPEG", exif=ex, quality=85)
    return b.getvalue()


now_ms = lambda: datetime.now(timezone.utc).timestamp() * 1000


def register(c, email, role, **extra):
    r_ = post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW, **extra),
              "/inscription", follow=False)
    assert r_.status_code == 302, email


register(own, "a@x.ci", "proprio"); register(own2, "b@x.ci", "proprio")
register(chef, "k@x.ci", "chef", phone="0700000000"); register(insp, "i@x.ci", "inspecteur", zone="Abidjan", tarif="1")
s.execute("UPDATE users SET verified=1 WHERE email='i@x.ci'"); s.commit()


def new_project(c, name):
    data = dict(name=name, address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="manuel",
                start_date=datetime.now().date().isoformat())
    for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
        data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
    return int(post(c, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])


pid = new_project(own, "Immeuble")
other = new_project(own2, "Autre")
code = one("SELECT invite_code FROM projects WHERE id=?", pid)[0]
post(chef, "/rejoindre", dict(code=code))
post(own, f"/chantiers/{pid}/membres", dict(email="i@x.ci", role="controleur"), f"/chantiers/{pid}?onglet=dossier")
steps = s.execute("SELECT * FROM steps WHERE project_id=? ORDER BY position", (pid,)).fetchall()

# --- 1. Zones et etages ---
zp = f"/chantiers/{pid}/zones"
assert insp.get(zp).status_code == 200 and post(insp, zp, dict(action="add", name="X"), zp).status_code == 403
bim = f"/chantiers/{pid}/maquette"
post(own, bim, dict(action="upload", file=(io.BytesIO(IFC.sample(2).encode()), "m.ifc")), bim, files=True)
post(own, zp, dict(action="from_bim"), zp)
zones = {z["name"]: z for z in s.execute("SELECT * FROM zones WHERE project_id=?", (pid,))}
assert set(zones) == {"Fondations", "Rez-de-chaussée", "Étage 1", "Toiture"} and zones["Étage 1"]["kind"] == "etage"
post(own, zp, dict(action="from_bim"), zp)
assert one("SELECT COUNT(*) FROM zones WHERE project_id=?", pid)[0] == 4                 # pas de doublon
post(chef, zp, dict(action="add", name="Aile nord", kind="zone", parent_id=zones["Étage 1"]["id"]), zp)
nord = one("SELECT * FROM zones WHERE name='Aile nord'")
assert nord["parent_id"] == zones["Étage 1"]["id"]
assert post(chef, zp, dict(action="add", name="Y", parent_id=999999), zp).status_code == 400
h = html(own.get(zp))
assert "Aile nord" in h and "Rez-de-chaussée" in h
# photo rattachee a une zone
h = html(chef.get(f"/chantiers/{pid}"))
assert 'name="zone_id"' in h and "Aile nord" in h
tk = re.search(r'name="capture_token" value="([^"]+)"', h).group(1)


def proof(seed, zone=None):
    d = dict(tz_offset="0", lat=str(SITE[0]), lng=str(SITE[1]), photo=(io.BytesIO(jpg(seed)), "c.jpg"), capture="app",
             capture_token=tk, captured_at=str(now_ms()), client_now=str(now_ms()))
    if zone:
        d["zone_id"] = str(zone)
    return post(chef, f"/chantiers/{pid}/preuves", d, f"/chantiers/{pid}", files=True)


proof(1, zones["Fondations"]["id"])
assert one("SELECT zone_id FROM proofs ORDER BY id DESC")[0] == zones["Fondations"]["id"]
proof(2, 999999)
assert one("SELECT zone_id FROM proofs ORDER BY id DESC")[0] is None                    # zone d'un autre chantier ignoree
print("zones et étages ok")

# --- 2. Visites 360 ---
vp = f"/chantiers/{pid}/visites-360"
z1 = zones["Étage 1"]["id"]


def visit(data, c=chef):
    return html(post(c, vp, dict(zone_id=str(z1), file=(io.BytesIO(data), "pano.jpg")), vp, files=True))


assert "Ce n&#39;est pas une photo 360°" in visit(jpg(3))
assert "Pas de position GPS" in visit(pano_bytes(1, 1, lat=None))
assert "du terrain (limite 100 m)" in visit(pano_bytes(1, 2, lat=5.36))
assert "plus de 3 jours" in visit(pano_bytes(1, 3, days=8))
h = visit(pano_bytes(1, 4))
assert "Visite 360° enregistrée" in h
first = pano_bytes(1, 4)
v1 = one("SELECT * FROM pano_visits WHERE ok=1")
assert v1["zone_id"] == z1 and v1["distance"] is not None and v1["change_pct"] is None
assert "Presque identique" in visit(pano_bytes(1, 4, size=(3998, 1999)))
seen_ai = {}
os.environ["ANTHROPIC_API_KEY"] = "test"
VISION.compare_panos = lambda a, b, zn: seen_ai.update(zone=zn) or {"progress": "Murs montés sur quatre travées.",
                                                                     "changes": ["Murs en parpaings"], "check": ["Aplomb des murs"],
                                                                     "same_place": True}
VISION.analyse_photo = lambda *a, **k: {"construction": True, "same_site": True, "step": "", "confidence": 0.9, "description": ""}
h = visit(pano_bytes(2, 5))
os.environ.pop("ANTHROPIC_API_KEY", None)
v2 = one("SELECT * FROM pano_visits WHERE ok=1 ORDER BY id DESC")
assert v2["change_pct"] > 2 and seen_ai["zone"] == "Étage 1" and "Murs montés" in v2["ai_note"]
h = html(own.get(f"{vp}?zone={z1}"))
assert "de l&#39;image a changé" in h and "Murs montés sur quatre travées" in h and "Aplomb des murs" in h
assert one("SELECT COUNT(*) FROM pano_visits WHERE ok=0")[0] == 5
assert own.get(f"/visites-360/{v2['id']}/image").status_code == 200 and own2.get(f"/visites-360/{v2['id']}/image").status_code == 403
assert one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Nouvelle visite 360%' AND channel='app'")[0] == 2
assert "Visites 360°" in html(own.get(zp)) and A.zones_progress(s, pid)[2]["last_pano"]
print("visites 360° : contrôles, comparaison, analyse IA ok")

# --- 3. Quantites installees ---
qp = f"/chantiers/{pid}/quantites"
post(own, qp, dict(action="from_bim"), qp)
items = {(r["zone_id"], r["label"]): r for r in s.execute("SELECT * FROM work_items WHERE project_id=?", (pid,))}
pot = items[(z1, "Poteaux")]
assert pot["qty_planned"] == 12 and pot["source"] == "bim"
post(own, qp, dict(action="from_bim"), qp)
assert one("SELECT COUNT(*) FROM work_items WHERE project_id=?", pid)[0] == len(items)             # pas de doublon
post(chef, qp, dict(action="add", label="Carrelage aile nord", unit="m²", qty_planned="48", zone_id=nord["id"]), qp)
assert "Indiquez l&#39;ouvrage" in html(post(chef, qp, dict(action="add", label="X", unit="pieds", qty_planned="3"), qp))
assert "photo vérifiée de moins de 7 jours" in html(post(chef, qp, dict(action="declare", item_id=pot["id"], qty="8"), qp))
pr = one("SELECT id FROM proofs WHERE project_id=? AND ok=1 ORDER BY id DESC", pid)[0]
s.execute("UPDATE proofs SET created_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=9)).isoformat(), pr)); s.commit()
assert "photo vérifiée de moins de 7 jours" in html(post(chef, qp, dict(action="declare", item_id=pot["id"], qty="8", proof_id=pr), qp))
s.execute("UPDATE proofs SET created_at=? WHERE id=?", (A.now_iso(), pr)); s.commit()
post(chef, qp, dict(action="declare", item_id=pot["id"], qty="8", proof_id=pr, note="Poteaux coulés"), qp)
post(chef, qp, dict(action="declare", item_id=pot["id"], qty="5", proof_id=pr), qp)
w = s.execute("SELECT * FROM work_progress ORDER BY id").fetchall()
assert [x["status"] for x in w] == ["declare", "declare"]
assert post(chef, qp, dict(action="validate", progress_id=w[0]["id"]), qp).status_code == 403
post(own, qp, dict(action="validate", progress_id=w[0]["id"]), qp)
post(insp, qp, dict(action="refuse", progress_id=w[1]["id"]), qp)
assert [r_["status"] for r_ in s.execute("SELECT status FROM work_progress ORDER BY id")] == ["valide", "refuse"]
rows = {r_["label"]: r_ for r_ in A.physical_report_rows(s, pid) if r_["zone"] == "Étage 1"}
assert rows["Poteaux"]["done"] == 8 and rows["Poteaux"]["pct"] == 67
r = own.get(f"/chantiers/{pid}/avancement-physique.csv")
txt = r.data.decode("utf-8-sig")
assert r.mimetype == "text/csv" and "Étage 1;" in txt and ";Poteaux;u;12;8;0;67" in txt, txt[:500]
h = html(own.get(f"/chantiers/{pid}/avancement-physique"))
assert "Rapport d&#39;avancement physique" in h and "Avancement physique (quantités validées)" in h
assert own2.get(qp).status_code == 403
print("quantités installées, validation, rapport et CSV ok")

# --- 4. Cles d'API ---
assert chef.get("/compte/api").status_code == 403
h = html(post(own, "/compte/api", dict(action="key", name="Compta"), "/compte/api"))
key = re.search(r"(cvk_[A-Za-z0-9_\-]+)", h).group(1)
assert key not in html(own.get("/compte/api"))                                          # affichee une seule fois
h = html(post(own, "/compte/api", dict(action="key", name="Devis", scope="write", project_id=pid), "/compte/api"))
wkey = re.search(r"(cvk_[A-Za-z0-9_\-]+)", h).group(1)
assert post(own, "/compte/api", dict(action="key", name="X", project_id=other), "/compte/api").status_code == 403
api = A.app.test_client()
H = lambda k: {"Authorization": f"Bearer {k}"}
assert api.get("/api/ext/v1/chantiers").status_code == 401
assert api.get("/api/ext/v1/chantiers", headers=H("cvk_faux")).status_code == 401
j = api.get("/api/ext/v1/chantiers", headers=H(key)).json
assert [c["nom"] for c in j["chantiers"]] == ["Immeuble"] and "indice_confiance" in j["chantiers"][0]
assert api.get(f"/api/ext/v1/chantiers/{other}", headers=H(key)).status_code == 404
for path in ("", "/etapes", "/preuves", "/paiements", "/stock", "/avancement", "/anomalies"):
    r = api.get(f"/api/ext/v1/chantiers/{pid}{path}", headers=H(key))
    assert r.status_code == 200 and r.json["ok"], path
assert len(api.get(f"/api/ext/v1/chantiers/{pid}/preuves?depuis=2000-01-01", headers=H(key)).json["preuves"]) == 2
etapes = api.get(f"/api/ext/v1/chantiers/{pid}/etapes", headers=H(key)).json["etapes"]
assert etapes[0]["nom"] == "Fondations" and etapes[0]["controles"]
av = api.get(f"/api/ext/v1/chantiers/{pid}/avancement", headers={"X-Api-Key": key}).json
assert any(z_["nom"] == "Étage 1 › Aile nord" for z_ in av["zones"]) and any(q["label"] == "Poteaux" for q in av["quantites"])
body = {"quantites": [{"ouvrage": "Peinture séjour", "unite": "m²", "quantite": 120, "zone": "Étage 1", "etape_id": steps[5]["id"]},
                      {"ouvrage": "X", "unite": "pieds", "quantite": 1}]}
assert api.post(f"/api/ext/v1/chantiers/{pid}/quantites-prevues", json=body, headers=H(key)).status_code == 403
r = api.post(f"/api/ext/v1/chantiers/{pid}/quantites-prevues", json=body, headers=H(wkey))
assert r.status_code == 207 and r.json["crees"] == 1 and r.json["erreurs"][0]["ligne"] == 1
it = one("SELECT * FROM work_items WHERE label='Peinture séjour'")
assert it["zone_id"] == z1 and it["source"] == "api" and it["step_id"] == steps[5]["id"]
assert api.get("/api/ext/v1/chantiers", headers=H(wkey)).json["chantiers"][0]["id"] == pid
kid = one("SELECT id FROM api_keys WHERE name='Compta'")[0]
post(own, "/compte/api", dict(action="revoke", key_id=kid), "/compte/api")
assert api.get("/api/ext/v1/chantiers", headers=H(key)).status_code == 401
assert "Authorization: Bearer cvk_" in html(A.app.test_client().get("/api/docs"))
print("clés d'API : lecture, écriture, périmètre, révocation ok")

# --- 5. Webhooks signes ---
assert "Adresse https publique" in html(post(own, "/compte/api", dict(action="hook", url="http://exemple.com/x", events="etape.payee"), "/compte/api"))
assert not HOOKS.url_ok("https://10.0.0.5/x") and not HOOKS.url_ok("https://localhost/x") and HOOKS.url_ok("https://erp.exemple.com/x")
h = html(post(own, "/compte/api", {"action": "hook", "url": "https://erp.exemple.com/cv", "project_id": pid,
                                   "events": ["etape.declaree", "etape.payee", "preuve.verifiee", "anomalie", "quantite.validee"]}, "/compte/api"))
secret = re.search(r"(whsec_[A-Za-z0-9_\-]+)", h).group(1)
sent.clear()
proof(7, zones["Fondations"]["id"])
post(chef, f"/chantiers/{pid}/etapes/{steps[0]['id']}/declarer", {}, f"/chantiers/{pid}")
post(own, f"/chantiers/{pid}/etapes/{steps[0]['id']}/valider", dict(override="1", pay_ref="OM-9"), f"/chantiers/{pid}")
events = [json.loads(x["body"])["event"] for x in sent]
assert events == ["preuve.verifiee", "etape.declaree", "etape.payee"], events
paid = sent[-1]
assert json.loads(paid["body"])["data"]["reference"] == "OM-9"
sig = "sha256=" + hmac.new(secret.encode(), (paid["headers"]["X-ChantierVrai-Timestamp"] + ".").encode() + paid["body"],
                           hashlib.sha256).hexdigest()
assert hmac.compare_digest(sig, paid["headers"]["X-ChantierVrai-Signature"])
assert one("SELECT COUNT(*) FROM webhook_deliveries WHERE status='livre'")[0] == 3
post(chef, qp, dict(action="declare", item_id=pot["id"], qty="2", proof_id=one("SELECT id FROM proofs WHERE ok=1 ORDER BY id DESC")[0]), qp)
post(insp, qp, dict(action="validate", progress_id=one("SELECT id FROM work_progress ORDER BY id DESC")[0]), qp)
assert json.loads(sent[-1]["body"])["event"] == "quantite.validee"
sn = f"/chantiers/{pid}/capteurs"
post(own, sn, dict(action="add", kind="vibration", name="Vibration dalle"), sn)
skey = one("SELECT token FROM sensors WHERE project_id=?", pid)[0]
api.post("/api/v1/capteurs/mesures", json={"value": 25}, headers={"X-Sensor-Key": skey})
last = json.loads(sent[-1]["body"])
assert last["event"] == "anomalie" and last["data"]["type"] == "capteur"
# echec puis relance
post(own, "/compte/api", {"action": "hook", "url": "https://panne.exemple.com/cv", "events": ["etape.declaree"]}, "/compte/api")
hid = one("SELECT id FROM webhooks WHERE url LIKE '%panne%'")[0]
post(own, "/compte/api", dict(action="hook_test", hook_id=hid), "/compte/api")
d_ = one("SELECT * FROM webhook_deliveries WHERE webhook_id=? ORDER BY id DESC", hid)
assert d_["status"] == "en_attente" and d_["attempts"] == 1 and d_["response_code"] == 500 and d_["next_at"] > A.now_iso()
s.execute("UPDATE webhook_deliveries SET next_at=? WHERE id=?", ("2000-01-01", d_["id"])); s.commit()
A.deliver_webhooks()
assert one("SELECT attempts FROM webhook_deliveries WHERE id=?", d_["id"])[0] == 2
s.execute("UPDATE webhooks SET failures=29 WHERE id=?", (hid,)); s.execute("UPDATE webhook_deliveries SET next_at='2000' WHERE id=?", (d_["id"],)); s.commit()
A.deliver_webhooks()
assert one("SELECT active FROM webhooks WHERE id=?", hid)[0] == 0                       # mis en pause
assert "En pause" in html(own.get("/compte/api"))
# les webhooks d'un autre proprietaire ne recoivent rien
n = len(sent)
post(own2, "/compte/api", {"action": "hook", "url": "https://autre.exemple.com/cv", "events": ["preuve.verifiee"]}, "/compte/api")
proof(8)
assert not any("autre.exemple.com" in x["url"] for x in sent[n:])
print("webhooks : événements, signature, relances, pause, cloisonnement ok")

# --- 6. Anglais ---
own.get("/?lang=en")
assert "Progress by zone" in html(own.get(zp)) and "360° walkthroughs" in html(own.get(vp)) and "Installed quantities" in html(own.get(qp))
assert "API and webhooks" in html(own.get("/compte/api"))
print("anglais ok")
print("\nTOUS LES TESTS DU SUIVI DE TERRAIN ET DE L'API PASSENT")
