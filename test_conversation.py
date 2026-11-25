"""Test de la conversation du chantier : messages, photos, notes vocales, cartes de décision, alertes sans doublon.
Lancement : python3 test_conversation.py
"""
import io, os, re, sys, tempfile
from urllib.parse import quote
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_chat_")

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


X = f"/chantiers/{pid}/conversation"
FETCH = {"X-Requested-With": "fetch"}


def send(c, data, files=False):
    data = dict(data); data["csrf"] = tok(c, X)
    return c.post(X, data=data, headers=FETCH, content_type="multipart/form-data" if files else None)


print("Accès")
check(other.get(X).status_code == 403, "autre propriétaire : refusé")
h = html(own.get(X))
check("Démarrez la conversation" in h and 'id="compose"' in h, "conversation vide prête à écrire")
check("Conversation du chantier" in html(own.get(f"/chantiers/{pid}")), "entrée sur l'accueil du propriétaire")
check("Parler au propriétaire" in html(chef.get(f"/chantiers/{pid}")), "entrée sur l'accueil du chef")

print("Messages")
r = send(chef, {"body": "Bonjour madame, on coule la dalle demain."})
check(r.status_code == 200 and r.get_json()["ok"], "le chef écrit")
check(notif("own@x.ci", "Nouveau message") == 1, "le propriétaire est prévenu")
send(chef, {"body": "Il faudra 3 camions de sable."})
check(notif("own@x.ci", "Nouveau message") == 1, "pas de pluie d'alertes : une seule tant que non lue")
check("2 non lus" in html(own.get(f"/chantiers/{pid}")), "pastille des non lus sur l'onglet Messages")
h = html(own.get(X))
check("on coule la dalle" in h and "Nouveaux messages" in h, "le propriétaire lit, avec le repère des nouveaux")
check(s.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND link = ? AND is_read = 0", (uid("own@x.ci"), X)).fetchone()[0] == 0,
      "l'alerte est marquée lue")
check(send(own, {"body": "   "}).status_code == 400, "message vide refusé")
send(own, {"body": "D'accord, envoyez une photo du ferraillage."})
check(notif("chef@x.ci", "Nouveau message") == 1, "le chef est prévenu de la réponse")

print("Photo et note vocale")
r = send(chef, {"file": (io.BytesIO(gps_jpg(*SITE, seed=5)), "fer.jpg"), "body": "Ferraillage"}, files=True)
m = s.execute("SELECT * FROM project_messages WHERE kind = 'photo'").fetchone()
check(r.get_json()["ok"] and m and m["distance"] is not None and m["distance"] < 50, "photo envoyée avec la distance au chantier")
check(own.get(f"{X}/fichier/{m['id']}").status_code == 200 and other.get(f"{X}/fichier/{m['id']}").status_code == 403, "photo privée")
r = send(chef, {"file": (io.BytesIO(b"\x1aE\xdf\xa3" + b"0" * 800), "note.webm"), "duration": "14"}, files=True)
v = s.execute("SELECT * FROM project_messages WHERE kind = 'voice'").fetchone()
check(r.get_json()["ok"] and v and v["duration"] == 14, "note vocale enregistrée avec sa durée")
check(own.get(f"{X}/fichier/{v['id']}").status_code == 200, "note vocale lisible par le propriétaire")
check(send(chef, {"file": (io.BytesIO(b"MZ..."), "virus.exe")}, files=True).status_code == 400, "format inconnu refusé")
h = html(own.get(X))
check("ch-voice" in h and "0:14" in h and "du chantier" in h, "bulles vocale et photo affichées")

print("Arrivée sans recharger")
last = s.execute("SELECT MAX(created_at) FROM project_messages").fetchone()[0]
j = own.get(f"{X}/nouveaux?apres={quote(last)}").get_json()
check(j["n"] == 0, "rien de nouveau")
send(chef, {"body": "Photo envoyée."})
j = own.get(f"{X}/nouveaux?apres={quote(last)}").get_json()
check(j["n"] >= 1 and "Photo envoyée." in j["html"] and j["last"] > last, "le nouveau message arrive en direct")
check(other.get(f"{X}/nouveaux").status_code == 403, "flux privé")

print("Décisions dans la conversation")
post(chef, f"/chantiers/{pid}/achats", {"action": "create", "title": "40 sacs de ciment", "amount": "224000"})
post(chef, f"/chantiers/{pid}/avenants", {"action": "create", "title": "Mur de clôture", "amount": "1850000", "extra_days": "10"})
h = html(own.get(X))
check("Demande d&#39;achat" in h and "40 sacs de ciment" in h and "224 000" in h, "carte de demande d'achat dans le fil")
check("Travaux supplémentaires" in h and "Mur de clôture" in h and "Accepter" in h, "carte de travaux supplémentaires")
rq = s.execute("SELECT id FROM purchase_requests").fetchone()[0]
r = post(own, f"/chantiers/{pid}/achats", {"action": "paid", "id": rq, "next": X + "#fin"}, page=X, follow=False)
check(r.status_code == 302 and r.headers["Location"].split("#")[0].endswith(X), "payer depuis la conversation y ramène")
check(s.execute("SELECT status FROM purchase_requests WHERE id = ?", (rq,)).fetchone()[0] == "payee", "achat payé")
r = post(own, f"/chantiers/{pid}/achats", {"action": "cancel", "id": rq, "next": "https://evil.example/"}, page=X, follow=False)
check("evil" not in r.headers.get("Location", ""), "pas de redirection vers un autre site")
co = s.execute("SELECT id FROM change_orders").fetchone()[0]
post(own, f"/chantiers/{pid}/avenants", {"action": "accept", "id": co, "next": X}, page=X)
check(s.execute("SELECT status FROM change_orders WHERE id = ?", (co,)).fetchone()[0] == "acceptee", "travaux acceptés depuis le fil")
check("Payer" not in html(chef.get(X)).split("40 sacs")[-1][:400], "le chef ne voit pas les boutons du propriétaire")

print("Menus")
check("Conversation" in html(chef.get(f"/chantiers/{pid}")), "action rapide « Conversation » côté chef")
print(f"\nConversation du chantier : {ok} vérifications OK")
