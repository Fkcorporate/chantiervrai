"""Test de bout en bout des nouvelles fonctions (sans reseau, mode simulation).
Lancement : CV_SYNC=1 python3 test_complet.py
"""
import io, os, re, shutil, sqlite3, subprocess, sys, tempfile
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
inst = os.environ.get("CV_TEST_DIR") or tempfile.mkdtemp(prefix="cv_test_")
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

# --- 1. Migration d'une ancienne base (schema d'origine, role sans inspecteur) ---
os.makedirs(inst, exist_ok=True)
old_db = os.path.join(inst, "chantiervrai.db") if not PG else os.path.join(inst, "ancienne.db")
old = sqlite3.connect(old_db)
old.executescript("""
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, phone TEXT,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('proprio', 'chef')), created_at TEXT NOT NULL);
CREATE TABLE projects (id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL REFERENCES users(id),
 chef_id INTEGER REFERENCES users(id), name TEXT NOT NULL, address TEXT, lat REAL NOT NULL, lng REAL NOT NULL,
 radius INTEGER NOT NULL DEFAULT 100, invite_code TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
CREATE TABLE steps (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, name TEXT NOT NULL, amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'attente',
 declared_at TEXT, paid_at TEXT, pay_ref TEXT);
INSERT INTO users VALUES (1,'Ancien','old@x.ci','', 'x','proprio','2025-01-01T00:00:00+00:00');
INSERT INTO projects VALUES (1,1,NULL,'Ancien chantier','',5.0,-4.0,100,'OLD001','2025-01-01T00:00:00+00:00');
INSERT INTO steps VALUES (1,1,0,'Fondations',1000,'en_cours',NULL,NULL,NULL);
""")
old.commit(); old.close()

import app as A
from PIL import Image

if PG:
    res = A.app.test_cli_runner().invoke(args=["migrer-vers-postgres", old_db])
    assert "Migration terminée" in res.output, res.output
    A.init_db()                                   # complete started_at comme pour une base SQLite
db = A.connect()
if not PG:
    assert "inspecteur" in db.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
assert db.execute("SELECT name FROM users WHERE id=1").fetchone()[0] == "Ancien"
assert db.execute("SELECT started_at FROM steps WHERE id=1").fetchone()[0]
db.close(); print("migration ok" + (" (SQLite -> PostgreSQL)" if PG else ""))

A.app.config["TESTING"] = True
A.app.config["ESCROW_ENABLED"] = True     # sequestre active comme par le super-admin
own, chef, insp, citizen = (A.app.test_client() for _ in range(4))
SITE = (5.3521, -3.8892)


def tok(c, url="/"):
    r = c.get(url)
    m = re.search(r'name="csrf" value="([^"]+)"', r.get_data(as_text=True))
    assert m, (url, r.status_code, r.get_data(as_text=True)[:500])
    return m.group(1)


def post(c, url, data, page="/", follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page)
    r = c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)
    return r


def jpg(lat, lng, when, seed=1, size=(320, 240)):
    import numpy as np
    rng = np.random.default_rng(seed)
    im = Image.fromarray(rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8))
    ex = Image.Exif()
    def dms(x):
        x = abs(x); d = int(x); m = int((x - d) * 60); s = round(((x - d) * 60 - m) * 60, 4)
        return (float(d), float(m), s)
    if lat is not None:
        ex[0x8825] = {1: 'N' if lat >= 0 else 'S', 2: dms(lat), 3: 'E' if lng >= 0 else 'W', 4: dms(lng)}
    ex.get_ifd(0x8769)[0x9003] = when.strftime('%Y:%m:%d %H:%M:%S')
    b = io.BytesIO(); im.save(b, 'JPEG', exif=ex.tobytes()); return b.getvalue()


nowu = datetime.now(timezone.utc).replace(tzinfo=None)

# --- 2. Comptes : proprietaire, chef, inspecteur ---
for c, role, email, extra in [(own, "proprio", "a@x.ci", {}), (chef, "chef", "k@x.ci", {"phone": "0700000000"}),
                              (insp, "inspecteur", "i@x.ci", {"zone": "Bingerville", "tarif": "50000", "phone": "0500000000"})]:
    r = post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password="Bingerville-2026", **extra),
             "/inscription", follow=False)
    assert r.status_code == 302, (role, r.status_code)
print("comptes ok (dont inspecteur)")

# --- 3. Chantier en sequestre, avec planning ---
data = dict(name="Villa R+1", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100",
            start_date=(datetime.now().date() - timedelta(days=40)).isoformat(), pay_mode="sequestre", kind="prive")
for i, (n, a, dd) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(dd)
r = post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False)
pid = int(r.headers["Location"].rstrip("/").split("/")[-1])
code = re.search(r'class="code">(\w+)<', own.get(f"/chantiers/{pid}").get_data(as_text=True)).group(1)
post(chef, "/rejoindre", dict(code=code))
print("chantier sequestre ok")

# --- 4. Preuves : photo, doublon visuel, video ---
def up(img, client=chef, url=None, name="p.jpg", **extra):
    d = dict(tz_offset="0", note="test", photo=(io.BytesIO(img), name)); d.update(extra)
    return post(client, url or f"/chantiers/{pid}/preuves", d, f"/chantiers/{pid}", files=True).get_data(as_text=True)

good = jpg(*SITE, nowu, seed=1)
h = up(good); assert "Preuve vérifiée et envoyée" in h, h[:2000]
# meme image re-encodee (photo d'ecran / recompression) -> empreinte visuelle identique
im = Image.open(io.BytesIO(good)); b = io.BytesIO(); im.save(b, "JPEG", quality=60, exif=im.getexif().tobytes())
h = up(b.getvalue()); assert "quasi identique" in h, h[:2000]; print("doublon visuel refuse")

vid = os.path.join(inst, "v.mp4")
when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
                "-metadata", f"creation_time={when}", "-metadata", "location=+05.3522-003.8891/", vid], check=True)
with open(vid, "rb") as fh:
    vbytes = fh.read()
info = A.MEDIA.probe(vid); assert info.get("lat") and info.get("created"), info
raw = A.MEDIA._parse_mp4(vid); assert raw.get("lat") and raw.get("created"), raw
d = dict(tz_offset="0", note="video", photo=(io.BytesIO(vbytes), "v.mp4"))
h = post(chef, f"/chantiers/{pid}/preuves", d, f"/chantiers/{pid}", files=True).get_data(as_text=True)
assert "Preuve vérifiée et envoyée" in h, h[:2000]
pr = A.connect().execute("SELECT * FROM proofs WHERE kind='video'").fetchone()
assert pr["thumb"] and pr["distance"] is not None and pr["ok"] == 1
assert chef.get(f"/photos/{pr['id']}").status_code == 200 and own.get(f"/photos/{pr['id']}/vignette").status_code == 200
old_vid = os.path.join(inst, "old.mp4")
subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=5",
                "-metadata", "creation_time=2025-01-01T10:00:00Z", "-metadata", "location=+05.3522-003.8891/", old_vid], check=True)
with open(old_vid, "rb") as fh:
    h = post(chef, f"/chantiers/{pid}/preuves", dict(tz_offset="0", photo=(io.BytesIO(fh.read()), "o.mp4")),
             f"/chantiers/{pid}", files=True).get_data(as_text=True)
assert "ancienne" in h; print("video ok (GPS, date, vignette, ancienne refusee)")

# --- 5. Sequestre : validation refusee sans fonds, depot simule, versement auto ---
step1 = A.connect().execute("SELECT id FROM steps WHERE project_id=? ORDER BY position", (pid,)).fetchone()[0]
post(chef, f"/chantiers/{pid}/etapes/{step1}/declarer", {}, f"/chantiers/{pid}")
h = post(own, f"/chantiers/{pid}/etapes/{step1}/valider", {"override": "1"}, f"/chantiers/{pid}?onglet=etapes").get_data(as_text=True)
assert "Solde du séquestre insuffisant" in h
h = post(own, f"/chantiers/{pid}/paiements/depot", dict(amount="5 000 000"), f"/chantiers/{pid}?onglet=etapes").get_data(as_text=True)
assert "Dépôt de 5 000 000 FCFA confirmé (simulation)" in h, h[:1500]
h = post(own, f"/chantiers/{pid}/etapes/{step1}/valider", {"override": "1"}, f"/chantiers/{pid}?onglet=etapes").get_data(as_text=True)
assert "versés au chef de chantier (simulation)" in h, h[:1500]
s = A.connect()
st = s.execute("SELECT * FROM steps WHERE id=?", (step1,)).fetchone(); assert st["status"] == "paye" and st["pay_ref"].startswith("SIM-V")
assert s.execute("SELECT COUNT(*) FROM documents WHERE project_id=? AND category='PV'", (pid,)).fetchone()[0] == 1
pv = s.execute("SELECT id FROM documents WHERE category='PV'").fetchone()[0]
assert "Procès-verbal" in own.get(f"/documents/{pv}").get_data(as_text=True)
with A.app.app_context():
    esc = A.escrow(pid, s)
assert esc["balance"] == 2000000 and esc["released"] == 3000000, esc
print("sequestre ok : depot, versement automatique, PV genere")

# --- 6. Notifications : app + WhatsApp/SMS/e-mail simules ---
n = s.execute("SELECT channel, status FROM notifications WHERE user_id=(SELECT id FROM users WHERE email='k@x.ci')").fetchall()
chans = {(r["channel"], r["status"]) for r in n}
assert ("whatsapp", "simule") in chans and ("app", "envoye") in chans, chans
assert "Paiement envoyé" in chef.get("/notifications").get_data(as_text=True)
post(chef, "/compte", dict(name="KOFFI", phone="+225 0700000000", notify_sms="1", notify_whatsapp="1"), "/compte")
assert s.execute("SELECT notify_sms, notify_email FROM users WHERE email='k@x.ci'").fetchone()[:] == (1, 0)
print("notifications ok")

# --- 7. Materiaux : prevu, facture saisie, alertes ---
step2 = s.execute("SELECT id FROM steps WHERE project_id=? ORDER BY position LIMIT 1 OFFSET 1", (pid,)).fetchone()[0]
post(own, f"/chantiers/{pid}/materiaux/prevu", dict(step_id=step2, material="Ciment", qty="100", unit="sacs", price="5000"),
     f"/chantiers/{pid}?onglet=dossier")
inv_img = jpg(None, None, nowu, seed=9)
r = post(chef, f"/chantiers/{pid}/factures", dict(step_id=step2, supplier="Quincaillerie A", number="F-12",
                                                  file=(io.BytesIO(inv_img), "f.jpg")), f"/chantiers/{pid}?onglet=factures",
         files=True, follow=False)
iid = int(r.headers["Location"].split("/")[-1])
post(chef, f"/chantiers/{pid}/factures/{iid}", dict(action="line", material="Ciment", material_other="Ciment CPJ 42,5",
                                                    qty="140", unit="sacs", unit_price="6500"),
     f"/chantiers/{pid}/factures/{iid}")
r = post(chef, f"/chantiers/{pid}/factures", dict(step_id=step2, supplier="quincaillerie a", number="F-12",
                                                  file=(io.BytesIO(jpg(None, None, nowu, seed=10)), "f2.jpg")),
         f"/chantiers/{pid}?onglet=factures", files=True, follow=False)
iid2 = int(r.headers["Location"].split("/")[-1])
assert s.execute("SELECT status FROM invoices WHERE id=?", (iid2,)).fetchone()[0] == "doublon"
h = own.get(f"/chantiers/{pid}?onglet=dossier").get_data(as_text=True)
assert "140 % du prévu facturé" in h and "Prix jusqu&#39;à 130 % de la référence" in h, re.findall(r"Ciment[^<]*", h)[:5]
assert re.search(r"alertes? sur les matériaux", own.get(f"/chantiers/{pid}?onglet=valider").get_data(as_text=True))   # « À surveiller »
assert own.get(f"/factures/{iid}/fichier").status_code == 200
print("materiaux ok : depassement quantite, prix, facture en double")

# --- 8. Inspecteur : reservation, acceptation, photo, rapport ---
insp_id = s.execute("SELECT id FROM users WHERE email='i@x.ci'").fetchone()[0]
assert "I · Bingerville" not in own.get(f"/chantiers/{pid}?onglet=dossier").get_data(as_text=True)  # non verifie
s.execute("UPDATE users SET verified=1 WHERE id=?", (insp_id,)); s.commit()
assert insp.get(f"/chantiers/{pid}").status_code == 403
# Inspection vendue par ChantierVrai : le proprietaire paie ChantierVrai, l'equipe attribue l'inspecteur
r = post(own, f"/chantiers/{pid}/inspections", dict(step_id=step2, message="Ferraillage"), f"/chantiers/{pid}?onglet=dossier",
         follow=False)
inv_id = int(r.headers["Location"].split("/")[-1])
assert s.execute("SELECT amount, kind FROM billing_invoices WHERE id=?", (inv_id,)).fetchone()[:] == (50000, "inspection")
post(own, f"/compte/factures/{inv_id}", {}, f"/compte/factures/{inv_id}")
rid, rst = s.execute("SELECT id, status FROM inspection_requests").fetchone()[:]
assert rst == "a_attribuer"
staff = A.app.test_client()
post(staff, "/inscription", dict(terms="1", role="proprio", name="VERIF", email="verif@cv.ci", password="Bingerville-2026"),
     "/inscription", follow=False)
A.app.test_cli_runner().invoke(args=["creer-admin", "verif@cv.ci", "--role", "verification"])
assert "Inspections indépendantes" in staff.get("/admin").get_data(as_text=True)
assert own.get("/admin").status_code == 403
post(staff, "/admin/inspections", dict(action="assign", id=rid, inspector_id=insp_id), "/admin")
ins = s.execute("SELECT id FROM inspections").fetchone()[0]
assert s.execute("SELECT sold, fee FROM inspections WHERE id=?", (ins,)).fetchone()[:] == (1, 35000)
assert "Ferraillage" in insp.get("/").get_data(as_text=True)
post(insp, f"/inspections/{ins}/reponse", dict(decision="accepter"))
assert insp.get(f"/chantiers/{pid}").status_code == 200
h = post(insp, f"/inspections/{ins}/rapport", dict(verdict="non_conforme", report="Enrobage insuffisant sur la dalle nord, à reprendre."),
         f"/chantiers/{pid}").get_data(as_text=True)
assert "au moins une photo" in h
h = up(jpg(*SITE, nowu, seed=3), client=insp, url=f"/inspections/{ins}/preuves")
assert "Photo d&#39;inspection vérifiée" in h or "Photo d'inspection vérifiée" in h, h[:1500]
post(insp, f"/inspections/{ins}/rapport", dict(verdict="non_conforme", report="Enrobage insuffisant sur la dalle nord, à reprendre."),
     f"/chantiers/{pid}")
assert s.execute("SELECT status, verdict FROM inspections WHERE id=?", (ins,)).fetchone()[:] == ("realisee", "non_conforme")
assert "Inspection non conforme" in own.get(f"/chantiers/{pid}?onglet=valider").get_data(as_text=True)
assert s.execute("SELECT payout_status FROM inspections WHERE id=?", (ins,)).fetchone()[0] == "a_verser"
assert "Attribuée et payée" not in own.get(f"/chantiers/{pid}?onglet=dossier").get_data(as_text=True)
print("inspection ok (vendue par ChantierVrai, inspecteur attribué par l'équipe)")

# --- 9. Prediction des retards ---
s.execute("UPDATE steps SET started_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=40)).isoformat(), step1))
s.execute("UPDATE steps SET declared_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(), step1))
s.execute("UPDATE steps SET started_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=25)).isoformat(), step2))
s.commit()
with A.app.test_request_context():
    p = s.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    st = A.project_stats(pid, s); pred = A.project_prediction(p, st, s)
assert pred and pred["delay"] > 0 and pred["pace"] > 1, pred
h = own.get(f"/chantiers/{pid}?onglet=etapes").get_data(as_text=True)
assert "Fin estimée le" in h and "Rythme mesuré" in h
post(own, f"/chantiers/{pid}/planning", {"start_date": "2026-01-05", f"days_{step2}": "25"}, f"/chantiers/{pid}?onglet=etapes")
print(f"prediction ok : retard {pred['delay']} j, rythme {pred['pace']}")

# --- 10. Satellite : deux mois, comparaison, carte des changements ---
import numpy as np
a = np.full((256, 256, 3), 120, np.uint8); b = a.copy(); b[80:180, 80:180] = 230
for month, arr in (("2026-09", a), ("2026-10", b)):
    buf = io.BytesIO(); Image.fromarray(arr).save(buf, "PNG")
    post(own, f"/chantiers/{pid}/satellite", dict(month=month, layer="optique", file=(io.BytesIO(buf.getvalue()), "s.png")),
         f"/chantiers/{pid}?onglet=vues", files=True)
sat = s.execute("SELECT * FROM sat_images WHERE project_id=? ORDER BY month", (pid,)).fetchall()
assert len(sat) == 2 and sat[1]["change_pct"] > 5, [dict(x) for x in sat]
h = own.get(f"/chantiers/{pid}?onglet=vues").get_data(as_text=True)
assert "% de changement" in h and "cmp-range" in h
assert own.get(f"/satellite/changements/{sat[0]['id']}/{sat[1]['id']}").mimetype == "image/jpeg"
print(f"satellite ok : {sat[1]['change_pct']} % de changement detecte")

# --- 11. Drone et 3D ---
h = post(chef, f"/chantiers/{pid}/drone", dict(kind="drone", files=[(io.BytesIO(jpg(5.3530, -3.8880, nowu, 5)), "d1.jpg"),
                                                                  (io.BytesIO(jpg(5.50, -3.80, nowu, 6)), "loin.jpg")]),
         f"/chantiers/{pid}", files=True).get_data(as_text=True)
assert "1 fichier ajouté" in h and "loin.jpg : prise à" in h
glb = b"glTF" + (2).to_bytes(4, "little") + (12).to_bytes(4, "little")
post(own, f"/chantiers/{pid}/drone", dict(kind="modele3d", files=[(io.BytesIO(glb), "maison.glb")]), f"/chantiers/{pid}?onglet=vues", files=True)
h = own.get(f"/chantiers/{pid}?onglet=vues").get_data(as_text=True)
assert "model-viewer" in h and "drone-map" in h
m3 = s.execute("SELECT id FROM media3d WHERE kind='modele3d'").fetchone()[0]
assert own.get(f"/drone3d/{m3}").mimetype == "model/gltf-binary"
print("drone et 3D ok")

# --- 12. Compte rendu hebdomadaire ---
s.execute("UPDATE projects SET created_at=? WHERE id=?", ((datetime.now(timezone.utc) - timedelta(days=8)).isoformat(), pid)); s.commit()
h = own.get(f"/chantiers/{pid}?fil=tout").get_data(as_text=True)      # « Tout le fil » : colonne d'à-côté
i = h.find("Compte rendu de la semaine"); assert "Compte rendu de la semaine" in h and re.search(r"preuves? vérifiées? cette semaine", h), h[i:i+700]
rid = s.execute("SELECT id FROM reports WHERE project_id=?", (pid,)).fetchone()[0]
assert "Photos de la semaine" in own.get(f"/chantiers/{pid}/rapports/{rid}").get_data(as_text=True)
runner = A.app.test_cli_runner(); res = runner.invoke(args=["rapports-hebdo"]); assert "compte(s) rendu(s)" in res.output, res.output
assert s.execute("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Compte rendu%' AND channel='email'").fetchone()[0] >= 1
print("compte rendu hebdo ok (page, commande planifiable, envoi e-mail simule)")

# --- 13. Documents du chantier, et plus de portail public ni de marchés publics ---
post(own, f"/chantiers/{pid}/documents", dict(category="DAO", title="DAO lot unique",
                                              file=(io.BytesIO(b"%PDF-1.4 test"), "dao.pdf")), f"/chantiers/{pid}?onglet=dossier", files=True)
assert "DAO lot unique" in own.get(f"/chantiers/{pid}?onglet=dossier").get_data(as_text=True)
for u in ("/portail", f"/portail/{pid}", "/marches/import"):
    assert citizen.get(u).status_code == 404 and own.get(u).status_code == 404, u
okp = s.execute("SELECT id FROM proofs WHERE project_id=? AND ok=1 AND kind='photo'", (pid,)).fetchone()[0]
assert citizen.get(f"/photos/{okp}").status_code == 302
assert "Portail citoyen" not in own.get("/").get_data(as_text=True)
print("documents ok, portail citoyen et marchés publics retirés")

# --- 14. Carte ---
h = own.get("/carte").get_data(as_text=True); assert "Villa R+1" in h and "L.map" in h
h = own.get("/").get_data(as_text=True); assert "Argent suivi sur votre chantier" in h and "sur un budget de" in h
print("carte ok")

# --- 15. Application installable et pages diverses ---
assert own.get("/manifest.webmanifest").json["display"] == "standalone"
assert own.get("/sw.js").headers["Service-Worker-Allowed"] == "/"
assert own.get("/static/icons/icon-512.png").status_code == 200
assert citizen.get("/hors-ligne").status_code == 200
for t in ["accueil", "preuves", "etapes", "vues", "dossier"]:
    assert own.get(f"/chantiers/{pid}?onglet={t}").status_code == 200, t
for t in ["accueil", "preuves", "factures"]:
    assert chef.get(f"/chantiers/{pid}?onglet={t}").status_code == 200, t
for u in ["/", "/compte", "/notifications", "/carte"]:
    for c in (own, chef, insp):
        assert c.get(u).status_code == 200, u
assert own.get(f"/chantiers/{pid}/rapports").status_code == 200
assert chef.get(f"/chantiers/{pid}/rapports").status_code == 403
assert chef.post(f"/chantiers/{pid}/paiements/depot", data=dict(csrf=tok(chef), amount="1000")).status_code == 403
assert own.post("/paiements/cinetpay/notification/faux", data={}).status_code == 404
print("PWA et controles d'acces ok")
if not os.environ.get("CV_TEST_DIR"):
    shutil.rmtree(inst, ignore_errors=True)
print("TOUT OK")
