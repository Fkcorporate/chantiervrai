"""API de l'application mobile (/api/v1), utilisee comme le ferait l'application Android ou iPhone.
Lancement : python3 test_api.py
"""
import io, os, re, shutil, sys, tempfile
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["EXPO_PUSH"] = "0"
inst = tempfile.mkdtemp(prefix="cv_api_")
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
PW = "Bingerville-2026"
SITE = (5.3521, -3.8892)
web = A.app.test_client()
s = A.connect()


def tok(c, url="/"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)


# Comptes crees sur le site web (proprietaire en anglais, chef en francais)
own_web, chef_web = A.app.test_client(), A.app.test_client()
own_web.post("/inscription?lang=en", data=dict(csrf=tok(own_web, "/inscription?lang=en"), terms="1", role="proprio", name="Ama",
                                               email="ama@x.co.uk", password=PW))
chef_web.post("/inscription", data=dict(csrf=tok(chef_web, "/inscription"), terms="1", role="chef", name="Koffi", email="k@x.ci",
                                        password=PW, phone="0700000000"))
data = dict(csrf=tok(own_web, "/chantiers/nouveau"), name="Villa", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]),
            radius="100", pay_mode="sequestre", require_app_capture="1", start_date=datetime.now().date().isoformat())
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
pid = int(own_web.post("/chantiers/nouveau", data=data).headers["Location"].split("/")[-1])


def api(method, url, token=None, **kw):
    h = kw.pop("headers", {})
    if token:
        h["Authorization"] = f"Bearer {token}"
    c = A.app.test_client()                       # aucun cookie : comme une application mobile
    return getattr(c, method)(url, headers=h, **kw)


# --- Connexion ---
r = api("post", "/api/v1/connexion", json=dict(email="k@x.ci", password="faux"))
assert r.status_code == 401 and r.json["error"] == "E-mail ou mot de passe incorrect."
r = api("post", "/api/v1/connexion", json=dict(email="k@x.ci", password=PW, device="Pixel 8"))
assert r.status_code == 200 and r.json["user"]["role"] == "chef"
chef = r.json["token"]
own = api("post", "/api/v1/connexion", json=dict(email="ama@x.co.uk", password=PW)).json["token"]
assert api("get", "/api/v1/chantiers").status_code == 401
assert api("get", "/api/v1/chantiers", "faux-jeton").status_code == 401
print("connexion par jeton ok")

# --- Rejoindre le chantier (route web reutilisee avec le jeton, sans jeton CSRF) ---
code = re.search(r'class="code">(\w+)<', own_web.get(f"/chantiers/{pid}").get_data(as_text=True)).group(1)
r = api("post", "/rejoindre", chef, data=dict(code=code))
assert r.status_code == 302
projects = api("get", "/api/v1/chantiers", chef).json["projects"]
assert projects[0]["id"] == pid and projects[0]["role"] == "chef" and projects[0]["current"]["name"] == "Fondations"
detail = api("get", f"/api/v1/chantiers/{pid}", chef).json["project"]
assert detail["capture_token"] and len(detail["steps"]) == 6 and detail["require_app_capture"]
print("liste et détail des chantiers ok")


# --- Preuve prise avec l'application native ---
def jpg(seed, exif=False):
    b = io.BytesIO(); im = Image.fromarray(np.random.default_rng(seed).integers(0, 255, (240, 320, 3), dtype=np.uint8))
    if exif:                                       # la camera native ecrit des EXIF (date) : c'est normal
        ex = Image.Exif(); ex.get_ifd(0x8769)[0x9003] = datetime.now().strftime('%Y:%m:%d %H:%M:%S'); im.save(b, "JPEG", exif=ex.tobytes())
    else:
        im.save(b, "JPEG")
    return b.getvalue()


now_ms = lambda: datetime.now(timezone.utc).timestamp() * 1000
nonce = api("post", "/api/v1/attestation/defi", chef).json["nonce"]
form = dict(capture="native", capture_token=detail["capture_token"], captured_at=str(now_ms() - 3000), client_now=str(now_ms()),
            lat=str(SITE[0]), lng=str(SITE[1]), acc="6", tz_offset="0", note="façade", platform="android",
            attestation="jeton-play-integrity", attestation_nonce=nonce, photo=(io.BytesIO(jpg(1, exif=True)), "p.jpg"))
r = api("post", f"/api/v1/chantiers/{pid}/preuves", chef, data=form, content_type="multipart/form-data")
assert r.status_code == 201 and r.json["ok"], r.json
proof_id = r.json["proof_id"]
row = s.execute("SELECT capture, attestation, ok FROM proofs WHERE id=?", (proof_id,)).fetchone()
assert row["capture"] == "native" and row["attestation"] == "non_verifiee" and row["ok"] == 1
# le meme defi ne peut pas servir deux fois
form.update(photo=(io.BytesIO(jpg(2)), "p.jpg"), captured_at=str(now_ms()), client_now=str(now_ms()))
r = api("post", f"/api/v1/chantiers/{pid}/preuves", chef, data=form, content_type="multipart/form-data")
assert not r.json["ok"] and "non reconnus" in r.json["reasons"][0], r.json
# hors du terrain : refusee, raisons renvoyees a l'application
nonce = api("post", "/api/v1/attestation/defi", chef).json["nonce"]
form.update(photo=(io.BytesIO(jpg(3)), "p.jpg"), lat="5.40", lng="-3.80", attestation_nonce=nonce, captured_at=str(now_ms()), client_now=str(now_ms()))
r = api("post", f"/api/v1/chantiers/{pid}/preuves", chef, data=form, content_type="multipart/form-data")
assert r.json["ok"] is False and "du terrain" in r.json["reasons"][0]
assert api("get", f"/photos/{proof_id}", chef).status_code == 200            # photo lue avec le jeton
assert api("post", f"/api/v1/chantiers/{pid}/preuves", own, data={}, content_type="multipart/form-data").status_code == 403
print("preuve native, attestation, défi à usage unique ok")

# --- Etapes : declarer (chef), refuser puis valider (proprietaire) ---
st = detail["steps"][0]["id"]
r = api("post", f"/api/v1/chantiers/{pid}/etapes/{st}/declarer", chef)
assert r.status_code == 200 and r.json["ok"], r.json
r = api("post", f"/api/v1/chantiers/{pid}/etapes/{st}/refuser", own, json=dict(motif="Ferraillage invisible"))
assert r.json["ok"] and "sent back" in r.json["messages"][0], r.json        # proprietaire anglophone
api("post", f"/api/v1/chantiers/{pid}/etapes/{st}/declarer", chef)
r = api("post", f"/api/v1/chantiers/{pid}/etapes/{st}/valider", own, json=dict(override=True))
assert r.status_code == 400 and "Escrow balance too low" in r.json["messages"][0], r.json
own_web.post(f"/chantiers/{pid}/paiements/depot", data=dict(csrf=tok(own_web, f"/chantiers/{pid}?onglet=etapes"), amount="3000000"))
r = api("post", f"/api/v1/chantiers/{pid}/etapes/{st}/valider", own, json=dict(override=True))
assert r.json["ok"] and "paid to the site foreman" in r.json["messages"][0], r.json
d = api("get", f"/api/v1/chantiers/{pid}", own).json["project"]
assert d["steps"][0]["status"] == "paye" and d["steps"][0]["status_label"] == "Approved and paid" and d["escrow"]["released"] == 3000000
assert "alerts" in d and "capture_token" not in d
print("déclarer, refuser, valider par l'API ok (messages dans la langue de chacun)")

# --- Notifications et push ---
r = api("post", "/api/v1/appareils", chef, json=dict(push_token="ExponentPushToken[abc123]", platform="android"))
assert r.json["ok"]
api("post", f"/api/v1/chantiers/{pid}/etapes/{d['steps'][1]['id']}/declarer", chef)      # sans preuve : refuse
n = api("get", "/api/v1/notifications", chef).json
assert any(x["title"] == "Paiement envoyé" for x in n["notifications"]), n
n_own = api("get", "/api/v1/notifications", own).json
assert any(x["title"] == "Stage to approve" for x in n_own["notifications"])
nonce = api("post", "/api/v1/attestation/defi", chef).json["nonce"]
t2 = api("get", f"/api/v1/chantiers/{pid}", chef).json["project"]["capture_token"]
form.update(photo=(io.BytesIO(jpg(9)), "p.jpg"), lat=str(SITE[0]), lng=str(SITE[1]), capture_token=t2, attestation_nonce=nonce,
            captured_at=str(now_ms()), client_now=str(now_ms()))
api("post", f"/api/v1/chantiers/{pid}/preuves", chef, data=form, content_type="multipart/form-data")
api("post", f"/api/v1/chantiers/{pid}/etapes/{d['steps'][1]['id']}/declarer", chef)
api("post", f"/api/v1/chantiers/{pid}/etapes/{d['steps'][1]['id']}/refuser", own, json=dict(motif="x"))
push = s.execute("SELECT status FROM notifications WHERE channel='push'").fetchall()
assert push and all(p["status"] == "simule" for p in push), [tuple(p) for p in push]
assert api("post", "/api/v1/notifications", chef).json["ok"] and api("get", "/api/v1/notifications", chef).json["unread"] == 0
print("notifications et push ok")

# --- Langue, profil, double authentification, deconnexion ---
r = api("put", "/api/v1/moi", own, json=dict(lang="fr", phone="+44 7700 900123"))
assert r.json["user"]["lang"] == "fr" and r.json["user"]["phone"].startswith("+44")
assert api("get", "/api/v1/notifications", own).json["notifications"][0]["title"].startswith(("Étape", "Preuve", "Paiement", "Fonds"))
api("put", "/api/v1/moi", own, json=dict(lang="en"))
s.execute("UPDATE users SET totp_on=1, totp_secret=? WHERE email='ama@x.co.uk'", (SEC.new_secret(),)); s.commit()
secret = s.execute("SELECT totp_secret FROM users WHERE email='ama@x.co.uk'").fetchone()[0]
r = api("post", "/api/v1/connexion", json=dict(email="ama@x.co.uk", password=PW))
assert r.json.get("need_2fa") and "token" not in r.json
r = api("post", "/api/v1/connexion", json=dict(email="ama@x.co.uk", password=PW, code=SEC.totp_now(secret)))
assert r.json["ok"] and r.json["token"]
assert api("post", "/api/v1/deconnexion", chef, json=dict(push_token="ExponentPushToken[abc123]")).json["ok"]
assert api("get", "/api/v1/chantiers", chef).status_code == 401
assert s.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0
# un changement de mot de passe deconnecte aussi l'application
s.execute("UPDATE users SET session_version = session_version + 1 WHERE email='ama@x.co.uk'"); s.commit()
assert api("get", "/api/v1/chantiers", own).status_code == 401
assert api("get", "/api/v1/version").json["api"] == 1
print("langue, double authentification, déconnexion, révocation ok")

# Suppression du compte depuis l'application (App Store) : mot de passe, blocages, effacement, jetons coupés
tok_k = api("post", "/api/v1/connexion", json=dict(email="k@x.ci", password=PW)).json["token"]
assert api("post", "/api/v1/compte/supprimer", tok_k, json=dict(password="faux")).status_code == 401
kid = s.execute("SELECT id FROM users WHERE email='k@x.ci'").fetchone()[0]
pid_k = s.execute("SELECT project_id FROM project_members WHERE user_id = ? LIMIT 1", (kid,)).fetchone()
r = api("post", "/api/v1/compte/supprimer", tok_k, json=dict(password=PW))
assert r.status_code == 200 and r.json["ok"], r.json
u = s.execute("SELECT name, email, phone, deleted FROM users WHERE id = ?", (kid,)).fetchone()
assert u["deleted"] == 1 and u["name"] == "Compte supprimé" and u["phone"] is None and u["email"].endswith(".invalid")
assert api("get", "/api/v1/chantiers", tok_k).status_code == 401
assert api("post", "/api/v1/connexion", json=dict(email="k@x.ci", password=PW)).status_code == 401
assert s.execute("SELECT COUNT(*) FROM api_tokens WHERE user_id = ? AND revoked = 0", (kid,)).fetchone()[0] == 0
print("suppression du compte depuis l'application ok")

# Comptes pour les testeurs des stores : mots de passe neufs, mot de passe public de la démo désactivé
r = A.app.test_cli_runner().invoke(args=["compte-revue"])
pws = re.findall(r"mot de passe : (\S+)", r.output)
from werkzeug.security import check_password_hash
hashes = {x["email"]: x["password_hash"] for x in s.execute("SELECT email, password_hash FROM users WHERE email LIKE '%@demo.chantiervrai.ci'")}
assert len(pws) == 2 and check_password_hash(hashes["aminata@demo.chantiervrai.ci"], pws[0])
assert not any(check_password_hash(h, "Demo-Chantier-2026") for h in hashes.values())
assert api("post", "/api/v1/connexion", json=dict(email="koffi@demo.chantiervrai.ci", password=pws[1])).json["ok"]
print("comptes de revue des stores ok")
shutil.rmtree(inst, ignore_errors=True)
print("TOUT OK")
