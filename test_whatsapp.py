"""Test du fil WhatsApp du chef de chantier : identification par numero, photos et position partagee,
photos en attente, refus, commandes (ETAPE, TERMINE, PAIEMENTS, RECU), notes vocales et messages,
plusieurs chantiers, webhook Twilio signe, simulateur.
Lancement : python3 test_whatsapp.py
"""
import base64, hashlib, hmac, io, os, re, sys, tempfile
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_wa_")
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM"):
    os.environ.pop(k, None)
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
from services import whatsapp as WA, voice as VOICE

A.app.config["TESTING"] = True
PW = "Bingerville-2026"
SITE = (5.3521, -3.8892)
CHEF = "+2250700000000"
s = A.connect()
ok = 0


def check(cond, label):
    global ok
    assert cond, label
    ok += 1
    print("  ok ", label)


def tok(c, url="/"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)


def post(c, url, data, page="/", follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)


def html(r):
    return r.get_data(as_text=True).replace("&#39;", "'")


def one(q, *a):
    return s.execute(q, a).fetchone()


def register(email, role="proprio", **extra):
    c = A.app.test_client()
    assert post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW,
                                        **extra), "/inscription", follow=False).status_code == 302, email
    return c


def notes(email, title):
    return one("SELECT COUNT(*) FROM notifications n JOIN users u ON u.id = n.user_id WHERE u.email = ? AND n.title LIKE ? "
               "AND n.channel = 'app'", email, f"%{title}%")[0]


def img(seed):
    """Photo telle que WhatsApp la transmet : recompressee, sans EXIF."""
    arr = np.random.default_rng(seed).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    b = io.BytesIO(); Image.fromarray(arr).save(b, "JPEG", quality=80); return b.getvalue()


def wa(text="", media=(), lat=None, lng=None, phone=CHEF):
    with A.app.test_request_context():
        A.g.lang = "fr"
        return A.wa_handle("whatsapp:" + phone, text, list(media), lat, lng)


def project(owner, name, require_app=False):
    data = dict(name=name, address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="suivi",
                start_date=datetime.now().date().isoformat())
    for i, (n, a) in enumerate([("Fondations", 1000000), ("Murs", 800000)]):
        data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), "10"
    pid = int(post(owner, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])
    if require_app:
        s.execute("UPDATE projects SET require_app_capture = 1 WHERE id = ?", (pid,)); s.commit()
    return pid


own = register("a@x.ci"); chef = register("k@x.ci", "chef", phone="07 00 00 00 00")
pid = project(own, "Villa Bingerville")
s.execute("UPDATE projects SET require_app_capture = 0 WHERE id = ?", (pid,)); s.commit()
post(chef, "/rejoindre", dict(code=one("SELECT invite_code FROM projects WHERE id=?", pid)[0]))

print("Identification et aide")
check("n'est lié à aucun compte" in wa("bonjour", phone="+2250500000000")[0], "numéro inconnu : explication pour s'inscrire")
r = wa("AIDE")
check("Villa Bingerville" in r[0] and "TERMINE" in r[0], "chef reconnu par son numéro, aide du chantier")
check(one("SELECT project_id FROM wa_sessions WHERE phone=?", CHEF)[0] == pid, "chantier choisi automatiquement (un seul)")

print("Photos et position")
r = wa(media=[(img(1), "image/jpeg")])
check("partagez votre position" in r[0], "photo sans position : mise en attente, position demandée")
check(one("SELECT COUNT(*) FROM proofs")[0] == 0, "rien n'est enregistré sans position")
r = wa(lat=SITE[0] + 0.0002, lng=SITE[1])
check("Position reçue (22 m" in r[0] and "vérifiée" in r[1], "position sur le terrain : la photo en attente est vérifiée")
pr = one("SELECT * FROM proofs ORDER BY id DESC LIMIT 1")
check(pr["ok"] == 1 and pr["capture"] == "whatsapp" and pr["note"] == "Reçue par WhatsApp" and pr["device_lat"], "preuve marquée « reçue par WhatsApp »")
check(notes("a@x.ci", "Nouvelle preuve vérifiée") == 1, "propriétaire prévenu comme pour une photo de l'application")
check("vérifiée" in wa(media=[(img(2), "image/jpeg")])[0], "position récente : photo vérifiée tout de suite")
check("Fichier déjà envoyé" in wa(media=[(img(2), "image/jpeg")])[0], "même photo renvoyée : refusée")
s.execute("UPDATE wa_sessions SET loc_at = ? WHERE phone = ?", ((datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat(), CHEF)); s.commit()
check("partagez votre position" in wa(media=[(img(3), "image/jpeg")])[0], "position trop ancienne : nouvelle position demandée")
s.execute("UPDATE wa_sessions SET pending = ? WHERE phone = ?",
          (A.json.dumps([dict(A.json.loads(one("SELECT pending FROM wa_sessions WHERE phone=?", CHEF)[0])[0],
                               at=(datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat())]), CHEF)); s.commit()
r = wa(lat=SITE[0], lng=SITE[1])
check(any("sans position partagée à temps" in x for x in r), "photo en attente trop longtemps : périmée, à renvoyer")
r = wa(lat=5.40, lng=-3.80)
check("à 10" in r[0] or "m du terrain (limite" in r[0], "position loin du terrain signalée")
check("Photo refusée" in wa(media=[(img(4), "image/jpeg")])[0], "photo avec une position hors du terrain : refusée")
wa(lat=SITE[0], lng=SITE[1])
check("vidéos" in wa(media=[(b"x", "video/mp4")])[0], "vidéo : renvoyée vers l'application")
h = html(own.get(f"/chantiers/{pid}?onglet=preuves"))
check("Reçue par WhatsApp" in h, "le propriétaire voit l'origine WhatsApp de la preuve")

print("Commandes")
r = wa("Etape ?")
check("Étape en cours : Fondations" in r[0] and "Photos vérifiées pour cette étape : 2" in r[0], "ETAPE : état de l'étape")
check("Répondez OUI" in wa("terminé")[0] and wa("non")[0] == "Annulé.", "TERMINE puis NON : annulé")
wa("TERMINE"); r = wa("oui")
check(one("SELECT status FROM steps WHERE project_id=? ORDER BY position LIMIT 1", pid)[0] == "declare" and "déclarée terminée" in r[0],
      "TERMINE puis OUI : étape déclarée")
check(notes("a@x.ci", "Étape à valider") == 1, "propriétaire prévenu de la déclaration")
check("Rien à confirmer" in wa("oui")[0], "OUI sans question : rien à confirmer")
sid = one("SELECT id FROM steps WHERE project_id=? ORDER BY position LIMIT 1", pid)[0]
uid_own, uid_chef = one("SELECT id FROM users WHERE email='a@x.ci'")[0], one("SELECT id FROM users WHERE email='k@x.ci'")[0]
s.execute("UPDATE steps SET status='versement' WHERE id=?", (sid,))
cur = s.execute("INSERT INTO payment_records (project_id, kind, ref_id, payer_id, payee_id, amount, method, reference, paid_on, status, "
                "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (pid, "etape", sid, uid_own, uid_chef, 1000000, "mobile_money", "WAVE-123",
                                                               datetime.now().date().isoformat(), "declare", A.now_iso()))
s.commit()
rid = one("SELECT MAX(id) FROM payment_records")[0]
r = wa("paiements")
check(f"{rid} : 1 000 000 FCFA" in r[0] and "WAVE-123" in r[0], "PAIEMENTS : paiements à confirmer listés")
check("introuvable" in wa("RECU 9999")[0], "RECU d'un paiement inconnu : refusé")
wa(f"reçu {rid}")
check(one("SELECT status FROM payment_records WHERE id=?", rid)[0] == "confirme" and notes("a@x.ci", "Paiement confirmé") == 1,
      "RECU : paiement confirmé, propriétaire prévenu")

print("Notes vocales et messages")
r = wa(media=[(b"OggS-fake-audio", "audio/ogg")])
n = one("SELECT * FROM site_notes ORDER BY id DESC LIMIT 1")
check("Note vocale reçue" in r[0] and n["kind"] == "vocal" and n["filename"] and n["transcript"] is None, "note vocale gardée sans transcription")
check(notes("a@x.ci", "Note vocale du chef") == 1, "propriétaire prévenu : note à écouter")
VOICE.transcribe = lambda raw, name="x": "Il manque vingt sacs de ciment pour finir la dalle, c'est urgent."
wa(media=[(b"OggS-2", "audio/ogg")])
n = one("SELECT * FROM site_notes ORDER BY id DESC LIMIT 1")
check(n["transcript"].startswith("Il manque") and n["urgent"] == 1 and n["category"] == "probleme", "transcrite, résumée, classée urgente")
check(one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Note vocale du chef%' AND channel != 'app'")[0] >= 1,
      "urgence : alerte envoyée aussi hors de l'application")
check("Message transmis" in wa("Le ferrailleur arrive demain matin.")[0] and notes("a@x.ci", "Message du chef") == 1, "message texte transmis")
h = html(own.get(f"/chantiers/{pid}/notes"))
check("Il manque vingt sacs" in h and "Urgent" in h and "ferrailleur" in h and "<audio" in h, "page des notes du chantier")
check(own.get(f"/notes/{n['id']}/audio").status_code == 200, "note vocale écoutable")
check("Notes du chantier" in html(own.get(f"/chantiers/{pid}?onglet=plus")), "page Plus : les notes du chef")
check(register("z@x.ci").get(f"/chantiers/{pid}/notes").status_code == 403, "notes inaccessibles à un étranger")

print("Plusieurs chantiers, chantier exigeant l'application")
pid2 = project(own, "Duplex Cocody", require_app=True)
post(chef, "/rejoindre", dict(code=one("SELECT invite_code FROM projects WHERE id=?", pid2)[0]))
check("Villa Bingerville" in wa("aide")[0], "nouveau chantier : le chantier en cours reste choisi")
r = wa("chantier")
check("Répondez par le numéro" in r[0] and "Duplex Cocody" in r[0], "CHANTIER : liste des chantiers")
check("Chantier choisi : Duplex Cocody" in wa("1")[0], "choix par numéro")
wa(lat=SITE[0], lng=SITE[1])
check("exige la caméra de l'application" in wa(media=[(img(9), "image/jpeg")])[0], "chantier exigeant l'application : photo WhatsApp refusée")
wa("chantier"); wa("2")
check(one("SELECT project_id FROM wa_sessions WHERE phone=?", CHEF)[0] == pid, "retour au premier chantier")

print("Webhook Twilio et simulateur")
c = A.app.test_client()
check(c.post("/whatsapp/entrant", data={"From": "whatsapp:" + CHEF, "Body": "AIDE"}).status_code == 404, "webhook fermé sans Twilio")
h = html(chef.get("/whatsapp/simulateur"))
check("Simulateur" in h and "Villa Bingerville" in h, "simulateur ouvert au chef")
h = html(post(chef, "/whatsapp/simulateur", dict(text="ETAPE"), "/whatsapp/simulateur"))
check("Étape en cours" in h, "simulateur : réponse affichée dans le fil")
check(own.get("/whatsapp/simulateur").status_code == 403, "simulateur fermé au propriétaire")
os.environ.update(TWILIO_ACCOUNT_SID="AC1", TWILIO_AUTH_TOKEN="secret", TWILIO_WHATSAPP_FROM="+14155238886",
                  TWILIO_WEBHOOK_URL="https://chantiervrai.example/whatsapp/entrant")
params = {"From": "whatsapp:" + CHEF, "Body": "", "NumMedia": "1", "MediaUrl0": "https://api.twilio.com/m/1",
          "MediaContentType0": "image/jpeg"}


def sign(p):
    data = os.environ["TWILIO_WEBHOOK_URL"] + "".join(k + v for k, v in sorted(p.items()))
    return base64.b64encode(hmac.new(b"secret", data.encode(), hashlib.sha1).digest()).decode()


check(c.post("/whatsapp/entrant", data=params, headers={"X-Twilio-Signature": "faux"}).status_code == 403, "signature invalide refusée")
WA.fetch_media = lambda url: (img(20), "image/jpeg")
s.execute("UPDATE steps SET status = 'en_cours' WHERE project_id = ? AND position = (SELECT MAX(position) FROM steps WHERE project_id = ?)", (pid, pid))
s.commit()
r = c.post("/whatsapp/entrant", data=params, headers={"X-Twilio-Signature": sign(params)})
check(r.status_code == 200 and r.mimetype == "application/xml" and "vérifiée" in html(r), "webhook signé : photo téléchargée, réponse TwiML")
check(chef.get("/whatsapp/simulateur").status_code == 404, "Twilio branché : simulateur fermé au chef")
check("Ouvrir WhatsApp" in html(chef.get(f"/chantiers/{pid}")), "le chef voit le numéro WhatsApp de ChantierVrai")
for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM", "TWILIO_WEBHOOK_URL"):
    os.environ.pop(k)
print(f"\n{ok} contrôles réussis.")
