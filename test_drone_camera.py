"""Test des vues aériennes : formule drone, télépilote agréé, mission, et caméra de chantier.
Lancement : python3 test_drone_camera.py
"""
import io, os, re, sys, tempfile
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_drone_")

import numpy as np
from PIL import Image
import app as A

A.app.config["TESTING"] = True
PW = "Bingerville-2026"
SITE = (5.3521, -3.8892)
ok = 0


def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("  ✓", msg)


def tok(c, url="/"):
    m = re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True))
    assert m, url
    return m.group(1)


def post(c, url, data, page=None, follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page or url)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)


def html(r):
    return r.get_data(as_text=True)


def register(c, email, role, name, **extra):
    r = post(c, "/inscription", dict(terms="1", role=role, name=name, email=email, password=PW, **extra), "/inscription", follow=False)
    assert r.status_code == 302, email


def gps_jpg(lat, lng, seed=1):
    im = Image.fromarray(np.random.default_rng(seed).integers(0, 255, (120, 160, 3), dtype=np.uint8))
    ex = Image.Exif()

    def dms(x):
        x = abs(x); d = int(x); m = int((x - d) * 60); s = round(((x - d) * 60 - m) * 60, 4)
        return (float(d), float(m), s)
    ex[0x8825] = {1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lng >= 0 else "W", 4: dms(lng)}
    ex.get_ifd(0x8769)[0x9003] = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
    b = io.BytesIO(); im.save(b, "JPEG", exif=ex.tobytes()); return b.getvalue()


def plain_jpg(seed, shade=None):
    if shade is not None:
        arr = np.full((90, 160, 3), shade, dtype=np.uint8)
    else:
        arr = np.random.default_rng(seed).integers(0, 255, (90, 160, 3), dtype=np.uint8)
    b = io.BytesIO(); Image.fromarray(arr).save(b, "JPEG"); return b.getvalue()


s = A.connect()
own, chef, pilot, other, adm = (A.app.test_client() for _ in range(5))
register(own, "own@x.ci", "proprio", "Aminata Koné")
register(chef, "chef@x.ci", "chef", "Koffi Chef", phone="0700000000")
register(pilot, "pilote@x.ci", "pro", "Ibrahim Pilote", profession="pilote_drone", company="Vue d'en haut")
register(other, "autre@x.ci", "proprio", "Autre Proprio")
register(adm, "admin@x.ci", "proprio", "Équipe CV")
s.execute("UPDATE users SET is_admin = 1, staff_role = 'super' WHERE email = 'admin@x.ci'"); s.commit()
uid = lambda e: s.execute("SELECT id FROM users WHERE email = ?", (e,)).fetchone()[0]

data = dict(name="Villa Bingerville", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="manuel",
            start_date=datetime.now().date().isoformat())
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
post(own, "/chantiers/nouveau", data)
pid = s.execute("SELECT id FROM projects WHERE name = 'Villa Bingerville'").fetchone()[0]
URL = f"/chantiers/{pid}/drone-camera"

print("Accès")
check(own.get(URL).status_code == 200, "propriétaire : page Drone et caméra")
check(other.get(URL).status_code == 403, "autre propriétaire : refusé")
check("Drone et caméra" in html(own.get(f"/chantiers/{pid}")), "entrée dans le menu des fonctions")
check(pilot.get("/missions-drone").status_code == 200 and own.get("/missions-drone").status_code == 404, "page Missions réservée aux télépilotes")

print("Télépilote : vérification ANAC")
post(pilot, "/compte", {"name": "Ibrahim Pilote", "anac_ref": "ANAC/DSV/2025-0142", "zone": "Abidjan"})
check(s.execute("SELECT anac_ref FROM users WHERE id = ?", (uid("pilote@x.ci"),)).fetchone()[0] == "ANAC/DSV/2025-0142", "numéro ANAC enregistré")
check("Ibrahim Pilote" in html(adm.get("/admin")), "télépilote proposé à la vérification")
post(adm, "/admin/action", {"action": "verify", "id": uid("pilote@x.ci")}, page="/admin")
check(s.execute("SELECT verified FROM users WHERE id = ?", (uid("pilote@x.ci"),)).fetchone()[0] == 1, "télépilote vérifié")

print("Formule drone")
r = post(own, URL, {"action": "request", "frequency": "mensuel", "message": "Derrière l'église"})
check("Demande envoyée" in html(r), "demande enregistrée")
r = post(own, URL, {"action": "request", "frequency": "hebdo"})
check("déjà en cours" in html(r), "une seule formule à la fois")
plan = s.execute("SELECT * FROM aerial_plans WHERE project_id = ?", (pid,)).fetchone()
check(plan["status"] == "demande" and plan["price"] == A.AERIAL_FREQ["mensuel"][2], "prix indicatif repris")
check(post(chef, URL, {"action": "request", "frequency": "mensuel"}).status_code == 403, "le chef ne peut pas commander")
first = (datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat()
post(adm, "/admin/action", {"action": "aerial_assign", "id": plan["id"], "pilot_id": uid("pilote@x.ci"), "price": "40000", "first": first},
     page="/admin")
plan = s.execute("SELECT * FROM aerial_plans WHERE id = ?", (plan["id"],)).fetchone()
m = s.execute("SELECT * FROM aerial_missions WHERE plan_id = ?", (plan["id"],)).fetchone()
check(plan["status"] == "actif" and plan["price"] == 40000 and m and m["due_on"] == first, "attribuée : premier passage programmé")
check(s.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND channel = 'app' AND title LIKE '%mission drone%'",
                (uid("pilote@x.ci"),)).fetchone()[0] == 1, "le télépilote est prévenu")
page = html(own.get(URL))
check("40 000" in page and "ANAC/DSV/2025-0142" in page, "le propriétaire voit le prix et l'autorisation du télépilote")

print("Mission")
MU = f"/missions-drone/{m['id']}"
check(other.get(MU).status_code == 404, "mission introuvable pour un autre")
r = post(pilot, MU, {"action": "finish"})
check("au moins une photo" in html(r), "impossible de terminer sans photo")
r = post(pilot, MU, {"action": "upload", "kind": "drone", "files": [(io.BytesIO(gps_jpg(5.40, -3.70)), "loin.jpg"),
                                                                   (io.BytesIO(plain_jpg(3)), "sansgps.jpg"),
                                                                   (io.BytesIO(gps_jpg(*SITE, seed=4)), "dji_0001.jpg"),
                                                                   (io.BytesIO(gps_jpg(SITE[0] + 0.0003, SITE[1], seed=5)), "dji_0002.jpg")]},
         files=True)
page = html(r)
check("du terrain" in page and "pas de position GPS" in page, "photo lointaine et photo sans GPS refusées")
check(s.execute("SELECT COUNT(*) FROM media3d WHERE mission_id = ?", (m["id"],)).fetchone()[0] == 2, "deux photos acceptées")
mid = s.execute("SELECT id FROM media3d WHERE mission_id = ? LIMIT 1", (m["id"],)).fetchone()[0]
check(pilot.get(f"/drone3d/{mid}").status_code == 200, "le télépilote revoit ses photos")
check(other.get(f"/drone3d/{mid}").status_code == 403, "un inconnu ne les voit pas")
post(pilot, MU, {"action": "finish", "note": "Dalle du R+1 coulée"})
m2 = s.execute("SELECT * FROM aerial_missions WHERE plan_id = ? ORDER BY id", (plan["id"],)).fetchall()
check(m2[0]["status"] == "faite" and len(m2) == 2, "mission faite, la suivante est programmée")
check(m2[1]["due_on"] == (datetime.fromisoformat(first) + timedelta(days=30)).date().isoformat(), "passage suivant 30 jours plus tard")
check(s.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND title LIKE '%Passage du drone%' AND channel = 'app'",
                (uid("own@x.ci"),)).fetchone()[0] == 1, "le propriétaire est prévenu")
post(pilot, f"/missions-drone/{m2[1]['id']}", {"action": "upload", "kind": "orthophoto",
                                                "files": [(io.BytesIO(plain_jpg(9)), "ortho.jpg")]}, files=True)
post(pilot, f"/missions-drone/{m2[1]['id']}", {"action": "upload", "kind": "drone",
                                                "files": [(io.BytesIO(gps_jpg(*SITE, seed=8)), "dji_0101.jpg")]}, files=True)
post(pilot, f"/missions-drone/{m2[1]['id']}", {"action": "finish"})
page = html(own.get(URL))
check("Avant / maintenant" in page and "Dalle du R+1 coulée" in page, "comparaison des deux derniers passages")

print("Retard")
m3 = s.execute("SELECT id FROM aerial_missions WHERE plan_id = ? AND status = 'prevue'", (plan["id"],)).fetchone()[0]
s.execute("UPDATE aerial_missions SET due_on = ? WHERE id = ?", ((datetime.now(timezone.utc).date() - timedelta(days=5)).isoformat(), m3)); s.commit()
with A.app.test_request_context():
    db = A.connect(); out = A.aerial_daily(db); db.commit(); db.close()
check(out.startswith("1 passage"), "passage en retard signalé à l'équipe et au télépilote")

print("Caméra")
page = html(post(own, URL, {"action": "add_camera", "name": "Poteau côté rue"}))
key = re.search(r"cle=([A-Za-z0-9_\-]+)", page).group(1)
check("ne sera plus jamais affichée" in page, "clé affichée une fois")
check("cle=" + key not in html(own.get(URL)), "clé masquée ensuite")
check(s.execute("SELECT token_hash FROM site_cameras").fetchone()[0] != key, "clé conservée chiffrée (empreinte)")
c = A.app.test_client()
check(c.post("/api/v1/cameras/photo?cle=mauvaise", data=plain_jpg(1)).status_code == 401, "mauvaise clé refusée")
check(c.post(f"/api/v1/cameras/photo?cle={key}", data=b"pas une image").status_code == 400, "fichier qui n'est pas une image refusé")
r = c.post("/api/v1/cameras/photo", headers={"X-Camera-Key": key}, data={"file": (io.BytesIO(plain_jpg(1)), "a.jpg")},
           content_type="multipart/form-data")
check(r.status_code == 200 and r.get_json()["kept"], "photo reçue (multipart, en-tête)")
r = c.post(f"/api/v1/cameras/photo?cle={key}", data=plain_jpg(2))
check(r.get_json()["kept"] is False, "trop rapproché : ignorée")
# Une semaine de photos simulées : chantier actif, puis trois jours sans mouvement
cam = s.execute("SELECT id FROM site_cameras").fetchone()[0]
s.execute("DELETE FROM camera_shots"); s.commit()
os.makedirs(A.CAM_DIR, exist_ok=True)
today = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
for back in range(6, -1, -1):
    day = today - timedelta(days=back)
    for h in (8, 10, 12, 14, 16):
        name = f"t{back}_{h}.jpg"
        Image.new("RGB", (32, 18), (100, 100, 100)).save(os.path.join(A.CAM_DIR, name))
        moving = back >= 3
        s.execute("INSERT INTO camera_shots (camera_id, project_id, filename, taken, change, created_at) VALUES (?,?,?,?,?,?)",
                  (cam, pid, name, day.replace(hour=h).isoformat(timespec="seconds"), 0.2 if moving else 0.01, A.now_iso()))
s.execute("UPDATE site_cameras SET last_seen = ? WHERE id = ?", (today.isoformat(), cam)); s.commit()
with A.app.test_request_context():
    days = A.camera_activity(A.connect(), cam)
check([d["state"] for d in days] == ["active"] * 4 + ["calm"] * 3, "jours actifs puis jours sans mouvement")
with A.app.test_request_context():
    db = A.connect(); A.aerial_daily(db); db.commit(); db.close()
n = s.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND channel = 'app' AND title LIKE '%Aucune activité%'",
              (uid("own@x.ci"),)).fetchone()[0]
wk = [datetime.fromisoformat(d["day"]).weekday() for d in days[-3:]]
check(n == 1 or 6 in wk, "propriétaire alerté : aucune activité visible")
with A.app.test_request_context():
    db = A.connect(); A.aerial_daily(db); db.commit(); db.close()
check(s.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND channel = 'app' AND title LIKE '%Aucune activité%'",
                (uid("own@x.ci"),)).fetchone()[0] == n, "pas d'alerte en double le lendemain")
page = html(own.get(URL))
check("Timelapse 7 jours" in page and 'class="act calm"' in page, "timelapse et bandeau d'activité affichés")
shot = s.execute("SELECT id FROM camera_shots LIMIT 1").fetchone()[0]
check(other.get(f"/cameras/photo/{shot}").status_code == 403, "photos de caméra privées")
post(own, URL, {"action": "remove_camera", "camera_id": cam})
check(c.post(f"/api/v1/cameras/photo?cle={key}", data=plain_jpg(5)).status_code == 401, "caméra retirée : clé désactivée")

print("Arrêt")
post(own, URL, {"action": "stop"})
check(s.execute("SELECT status FROM aerial_plans WHERE id = ?", (plan["id"],)).fetchone()[0] == "termine", "formule arrêtée")
check(not s.execute("SELECT 1 FROM aerial_missions WHERE plan_id = ? AND status = 'prevue'", (plan["id"],)).fetchone(), "passages à venir annulés")
print(f"\n{ok} vérifications OK")
