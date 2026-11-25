"""Test du quotidien du chef de chantier : argent pour les achats, travaux supplémentaires, journal du jour.
Lancement : python3 test_chef_quotidien.py
"""
import io, os, re, sys, tempfile
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_chef_")

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
own, chef, other = (A.app.test_client() for _ in range(3))
register(own, "own@x.ci", "proprio", "Aminata Koné")
register(chef, "chef@x.ci", "chef", "Koffi Chef", phone="0700000000")
register(other, "autre@x.ci", "proprio", "Autre Proprio")
uid = lambda e: s.execute("SELECT id FROM users WHERE email = ?", (e,)).fetchone()[0]
data = dict(name="Villa Bingerville", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="manuel",
            start_date=datetime.now().date().isoformat())
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
post(own, "/chantiers/nouveau", data)
pid = s.execute("SELECT id FROM projects").fetchone()[0]
s.execute("UPDATE projects SET chef_id = ? WHERE id = ?", (uid("chef@x.ci"), pid)); s.commit()
notif = lambda e, t: s.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND channel = 'app' AND title LIKE ?", (uid(e), f"%{t}%")).fetchone()[0]

print("Accueil du chef")
h = html(chef.get(f"/chantiers/{pid}"))
check("Journal du jour" in h and "Argent pour un achat" in h and "Travaux en plus" in h, "trois actions du jour en tête de page")
check("À remplir" in h, "le journal du jour est à remplir")

print("Argent pour un achat")
B = f"/chantiers/{pid}/achats"
check(other.get(B).status_code == 403, "autre propriétaire : refusé")
r = post(chef, B, {"action": "create", "title": "40 sacs de ciment", "amount": "224 000", "supplier": "Quincaillerie",
                   "quote": (io.BytesIO(plain_jpg(1)), "devis.jpg")}, files=True)
rq = s.execute("SELECT * FROM purchase_requests").fetchone()
check(rq and rq["amount"] == 224000 and rq["quote_file"], "demande enregistrée avec le devis (montant avec espaces lu)")
check(notif("own@x.ci", "achat") == 1, "le propriétaire est prévenu")
h = html(own.get(f"/chantiers/{pid}?onglet=valider"))
check("Demande d&#39;achat" in h and "224" in h and 'value="accept"' in h,
      "la demande attend le propriétaire dans l'onglet « À valider », avec ses boutons")
check(own.get(f"{B}/{rq['id']}/devis").status_code == 200 and other.get(f"{B}/{rq['id']}/devis").status_code == 403, "devis privé")
check(post(chef, B, {"action": "paid", "id": rq["id"]}).status_code == 403, "le chef ne peut pas se marquer payé")
r = post(own, B, {"action": "refuse", "id": rq["id"], "refusal": ""})
check("Dites pourquoi" in html(r), "refus sans motif impossible")
post(own, B, {"action": "paid", "id": rq["id"], "pay_ref": "OM-123"})
rq = s.execute("SELECT * FROM purchase_requests WHERE id = ?", (rq["id"],)).fetchone()
check(rq["status"] == "payee" and rq["pay_ref"] == "OM-123", "accepté et payé en une fois")
check(notif("chef@x.ci", "Argent envoyé") == 1, "le chef est prévenu")
post(chef, B, {"action": "received", "id": rq["id"]})
r = post(chef, B, {"action": "delivered", "id": rq["id"], "photo": (io.BytesIO(gps_jpg(5.40, -3.70)), "loin.jpg")}, files=True)
check("prenez-la sur place" in html(r), "photo de livraison loin du chantier refusée")
post(chef, B, {"action": "delivered", "id": rq["id"], "photo": (io.BytesIO(gps_jpg(*SITE, seed=3)), "livraison.jpg")}, files=True)
rq = s.execute("SELECT * FROM purchase_requests WHERE id = ?", (rq["id"],)).fetchone()
check(rq["status"] == "livree" and rq["received_at"] and rq["delivery_distance"] is not None, "livraison photographiée sur place")
page = html(own.get(f"/chantiers/{pid}?fil=tout"))
check("40 sacs de ciment" in page and "Livrée" in page, "l'achat livré apparaît dans le fil du propriétaire")
check("40 sacs de ciment" in html(own.get(f"/chantiers/{pid}")), "et dans les dernières nouvelles de l'accueil")
post(chef, B, {"action": "create", "title": "Sable", "amount": "90000"})
r2 = s.execute("SELECT id FROM purchase_requests WHERE title = 'Sable'").fetchone()[0]
post(own, B, {"action": "refuse", "id": r2, "refusal": "Trop cher, deuxième devis"})
check(s.execute("SELECT status, refusal FROM purchase_requests WHERE id = ?", (r2,)).fetchone()[0] == "refusee", "demande refusée avec motif")

print("Travaux supplémentaires")
C = f"/chantiers/{pid}/avenants"
n_steps = s.execute("SELECT COUNT(*) FROM steps WHERE project_id = ?", (pid,)).fetchone()[0]
total0 = s.execute("SELECT SUM(amount) FROM steps WHERE project_id = ?", (pid,)).fetchone()[0]
post(chef, C, {"action": "create", "title": "Mur de clôture", "amount": "1 850 000", "extra_days": "10", "reason": "Vols la nuit"})
co = s.execute("SELECT * FROM change_orders").fetchone()
check(co["status"] == "proposee" and notif("own@x.ci", "Travaux supplémentaires") == 1, "proposition envoyée au propriétaire")
check(post(chef, C, {"action": "accept", "id": co["id"]}).status_code == 403, "le chef ne peut pas accepter lui-même")
post(own, C, {"action": "accept", "id": co["id"]})
co = s.execute("SELECT * FROM change_orders WHERE id = ?", (co["id"],)).fetchone()
st = s.execute("SELECT * FROM steps WHERE id = ?", (co["step_id"],)).fetchone()
check(co["status"] == "acceptee" and st and st["amount"] == 1850000 and "Mur de clôture" in st["name"], "accepté : nouvelle étape créée")
check(s.execute("SELECT SUM(amount) FROM steps WHERE project_id = ?", (pid,)).fetchone()[0] == total0 + 1850000, "budget du chantier augmenté")
check(notif("chef@x.ci", "Travaux supplémentaires acceptés") == 1, "le chef est prévenu")
post(chef, C, {"action": "create", "title": "Piscine", "amount": "9000000"})
c2 = s.execute("SELECT id FROM change_orders WHERE title = 'Piscine'").fetchone()[0]
post(own, C, {"action": "refuse", "id": c2, "refusal": "Pas dans le budget"})
check(s.execute("SELECT status FROM change_orders WHERE id = ?", (c2,)).fetchone()[0] == "refusee", "proposition refusée")
post(own, C, {"action": "create", "title": "Carrelage terrasse", "amount": "600000"})
check(s.execute("SELECT status FROM change_orders WHERE title = 'Carrelage terrasse'").fetchone()[0] == "acceptee"
      and s.execute("SELECT COUNT(*) FROM steps WHERE project_id = ?", (pid,)).fetchone()[0] == n_steps + 2, "ajout par le propriétaire : accepté d'office")

print("Journal du jour")
J = f"/chantiers/{pid}/journal"
today = datetime.now(timezone.utc).date()
check(post(own, J, {"workers": "5"}).status_code == 403, "le propriétaire lit le journal mais ne l'écrit pas")
r = post(chef, J, {"day": (today + timedelta(days=1)).isoformat(), "workers": "5"})
check("dans les 7 jours" in html(r), "date future refusée")
post(chef, J, {"day": today.isoformat(), "workers": "6", "weather": "soleil", "done": "Murs du salon à 1,20 m"})
post(chef, J, {"day": today.isoformat(), "workers": "7", "weather": "pluie", "done": "Murs du salon à 1,40 m"})
rows = s.execute("SELECT * FROM site_journal WHERE project_id = ?", (pid,)).fetchall()
check(len(rows) == 1 and rows[0]["workers"] == 7 and rows[0]["weather"] == "pluie", "un seul journal par jour, modifiable")
post(chef, J, {"day": (today - timedelta(days=1)).isoformat(), "workers": "0", "weather": "forte_pluie", "stopped": "1", "stop_reason": "Forte pluie"})
check(notif("own@x.ci", "arrêté") == 1, "arrêt du chantier signalé au propriétaire")
page = html(own.get(J))
check("Forte pluie" in page and "Murs du salon" in page, "le propriétaire lit le journal")
check("7 ouvriers sur le chantier" in html(own.get(f"/chantiers/{pid}")), "journal dans le fil du propriétaire (pluriel accordé)")
check("À remplir" not in html(chef.get(f"/chantiers/{pid}")), "journal du jour rempli : badge retiré")
print(f"\n{ok} vérifications OK")
