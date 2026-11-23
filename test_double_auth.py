"""Double authentification : QR code lisible, mise en place, nouvelle clé, session expirée, connexion avec le code.
Lancement : python3 test_double_auth.py
"""
import os, re, sys, tempfile, time
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_2fa_")
os.environ.pop("SECRET_KEY", None)
import app as A
from services import qr as QR, security as SEC

A.app.config.update(TESTING=True, STAFF_2FA=True)
ok = 0


def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("  ✓", msg)


def tok(c, url):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)


print("Clé des sessions")
k1 = A.app.config["SECRET_KEY"]
check(len(k1) == 64 and A._stable_secret_key() == k1, "sans SECRET_KEY : une seule clé, partagée par tous les processus")
check(os.path.exists(os.path.join(A.INSTANCE_DIR, ".secret_key")), "gardée dans le dossier de données (survit aux redémarrages)")

print("Codes")
check(SEC.totp_now("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", at=59) == "287082"
      and SEC.totp_now("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", at=1111111109) == "081804", "algorithme conforme aux vecteurs de la RFC 6238")
sec = SEC.new_secret(); t = time.time()
check(SEC.totp_ok(sec, SEC.totp_now(sec, t - 60), at=t, drift=2) and not SEC.totp_ok(sec, SEC.totp_now(sec, t - 60), at=t),
      "mise en place : une minute de marge ; connexion : 30 secondes")

print("QR code")
try:
    import numpy as np, cv2
    uri = SEC.otpauth_uri(sec, "contact@egalyx.com")
    m = QR.matrix(uri); n, q, sc = len(m), 4, 8
    img = np.full(((n + 2 * q) * sc,) * 2, 255, np.uint8)
    for r in range(n):
        for c in range(n):
            if m[r][c]:
                img[(r + q) * sc:(r + q + 1) * sc, (c + q) * sc:(c + q + 1) * sc] = 0
    check(cv2.QRCodeDetector().detectAndDecode(img)[0] == uri, "le QR code se relit à l'identique (lecteur OpenCV)")
except ImportError:
    print("  (OpenCV absent : relecture du QR non testée)")

print("Mise en place")
c = A.app.test_client()
page = c.get("/inscription").get_data(as_text=True)
c.post("/inscription", data=dict(terms="1", role="proprio", name="Fabrice Konan", email="contact@egalyx.com",
                                 password="Bingerville-2026", csrf=re.search(r'name="csrf" value="([^"]+)"', page).group(1)))
A.app.test_cli_runner().invoke(args=["creer-admin", "contact@egalyx.com"])
check(c.get("/admin").status_code == 302, "administration fermée tant que la 2FA n'est pas active")
c.post("/compte/securite", data={"action": "totp_start", "csrf": tok(c, "/compte/securite")})
h = c.get("/compte/securite").get_data(as_text=True)
check("<svg" in h and "Scanner un code QR" in h and "Basé sur l" in h and "heure »" in h, "page : QR code, clé à saisir à la main, type « Basé sur l'heure »")
with c.session_transaction() as s_:
    first = s_["totp_setup"]
c.post("/compte/securite", data={"action": "totp_start", "csrf": tok(c, "/compte/securite")})
with c.session_transaction() as s_:
    second = s_["totp_setup"]
check(first != second and "Nouvelle clé" in h, "« Nouvelle clé » : on peut recommencer proprement")
r = c.post("/compte/securite", data={"action": "totp_confirm", "code": SEC.totp_now(first), "csrf": tok(c, "/compte/securite")},
           follow_redirects=True)
check("Code incorrect" in r.get_data(as_text=True), "le code de l'ancienne clé est refusé, avec une explication")
with c.session_transaction() as s_:
    s_.pop("totp_setup")
r = c.post("/compte/securite", data={"action": "totp_confirm", "code": "123456", "csrf": tok(c, "/compte/securite")},
           follow_redirects=True)
check("a expiré" in r.get_data(as_text=True), "mise en place expirée : message clair au lieu de « code incorrect »")
c.post("/compte/securite", data={"action": "totp_start", "csrf": tok(c, "/compte/securite")})
with c.session_transaction() as s_:
    sec = s_["totp_setup"]
r = c.post("/compte/securite", data={"action": "totp_confirm", "code": SEC.totp_now(sec)[:3] + " " + SEC.totp_now(sec)[3:],
                                     "csrf": tok(c, "/compte/securite")})
check(r.status_code == 200 and "Double authentification activée" in r.get_data(as_text=True), "bon code (même tapé avec un espace) : 2FA activée")
check(c.get("/admin").status_code == 200, "administration ouverte")

print("Connexion")
c2 = A.app.test_client()
r = c2.post("/connexion", data={"email": "contact@egalyx.com", "password": "Bingerville-2026", "csrf": tok(c2, "/connexion")})
r = c2.post(r.headers.get("Location", "/connexion/code"), data={"code": SEC.totp_now(sec), "csrf": tok(c2, r.headers.get("Location", "/connexion"))},
            follow_redirects=False)
check(c2.get("/admin").status_code == 200, "connexion avec le code du téléphone, administration accessible")

print(f"\nDouble authentification : {ok} vérifications OK")
