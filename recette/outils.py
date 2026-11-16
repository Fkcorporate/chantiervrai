"""Outils de la recette : serveur reel, clients HTTP par acteur, photos de terrain avec GPS, voyage dans le temps."""
import io, json, os, re, signal, socket, sqlite3, subprocess, sys, tempfile, time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PW = "Bingerville-2026"
SITE = (5.3521, -3.8892)          # terrain du chantier, Bingerville


# --------------------------------------------------------------------------
# Serveur
# --------------------------------------------------------------------------
class Serveur:
    """Lance ChantierVrai comme en production : pas de mode test, facturation appliquee, 2FA de l'equipe exigee."""

    def __init__(self, port=None):
        self.port = port or self._free_port()
        self.instance = tempfile.mkdtemp(prefix="cv_recette_")
        self.env = dict(os.environ, CV_INSTANCE=self.instance, SECRET_KEY="recette-" + "x" * 40,
                        COMPANY_NAME="ChantierVrai SAS", CONTACT_EMAIL="contact@chantiervrai.ci")
        self.env.pop("CV_SYNC", None)
        self.url = f"http://127.0.0.1:{self.port}"
        self.proc = None

    @staticmethod
    def _free_port():
        s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

    def start(self):
        code = f"import app; app.app.run(host='127.0.0.1', port={self.port}, threaded=True)"
        self.log = open(os.path.join(self.instance, "serveur.log"), "w")
        self.proc = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, env=self.env, stdout=self.log,
                                     stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                requests.get(self.url + "/connexion", timeout=1)
                return self
            except Exception:
                time.sleep(0.2)
        raise RuntimeError("Le serveur ne demarre pas : " + open(self.log.name).read()[-2000:])

    def stop(self):
        if self.proc:
            self.proc.send_signal(signal.SIGTERM)
            self.proc.wait(timeout=10)

    def flask(self, *args):
        r = subprocess.run([sys.executable, "-m", "flask", "--app", "app", *args], cwd=ROOT, env=self.env,
                           capture_output=True, text=True, timeout=600)
        return r.stdout + r.stderr

    def db(self):
        c = sqlite3.connect(os.path.join(self.instance, "chantiervrai.db"))
        c.row_factory = sqlite3.Row
        return c

    def sql(self, q, *a):
        c = self.db()
        try:
            cur = c.execute(q, a)
            rows = cur.fetchall()
            c.commit()
            return rows
        finally:
            c.close()

    def one(self, q, *a):
        rows = self.sql(q, *a)
        return rows[0] if rows else None

    def errors_in_log(self):
        txt = open(self.log.name, encoding="utf-8", errors="replace").read()
        return [ln for ln in txt.splitlines() if "Traceback" in ln or " 500 " in ln]


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------
class Web(requests.Session):
    """Navigation web d'un acteur (formulaires avec jeton CSRF)."""

    def __init__(self, base):
        super().__init__()
        self.base = base
        self.headers["Accept-Language"] = "fr"
        self.n_requests = 0

    def get(self, path, **kw):
        self.n_requests += 1
        return super().get(self.base + path, **kw)

    def token(self, page):
        m = re.search(r'name="csrf" value="([^"]+)"', self.get(page).text)
        if not m:
            raise RuntimeError(f"pas de jeton CSRF sur {page}")
        return m.group(1)

    def form(self, path, data=None, page="/", files=None, follow=True):
        data = dict(data or {})
        data["csrf"] = self.token(page)
        self.n_requests += 1
        return self.post(self.base + path, data=data, files=files, allow_redirects=follow)

    def register(self, email, role="proprio", **extra):
        data = dict(terms="1", role=role, name=extra.pop("name", email.split("@")[0].title()), email=email, password=PW,
                    **extra)
        r = self.form("/inscription", data, "/inscription", follow=False)
        assert r.status_code == 302, (email, r.status_code, r.text[:500])
        return self


class Api(requests.Session):
    """Application mobile : API /api/v1 avec jeton."""

    def __init__(self, base):
        super().__init__()
        self.base = base
        self.n_requests = 0

    def login(self, email):
        r = self.post(self.base + "/api/v1/connexion", json=dict(email=email, password=PW))
        assert r.status_code == 200, r.text
        self.headers["Authorization"] = "Bearer " + r.json()["token"]
        return self

    def call(self, method, path, **kw):
        self.n_requests += 1
        return self.request(method, self.base + path, **kw)

    def proof(self, pid, img_bytes, lat=None, lng=None, captured_at=None, mocked=False, token=None, capture="native",
              offline=False, extra=None):
        """Envoie une preuve comme l'application : jeton de capture, horodatage, GPS du telephone."""
        if token is None:
            token = self.call("GET", f"/api/v1/chantiers/{pid}").json()["project"].get("capture_token", "")
        now_ms = time.time() * 1000
        data = dict(capture=capture, capture_token=token, captured_at=str(round(captured_at or now_ms)),
                    client_now=str(round(now_ms)), tz_offset="0", offline="1" if offline else "0", platform="android")
        if lat is not None:
            data.update(lat=str(lat), lng=str(lng), acc="8")
        if mocked:
            data["mocked"] = "1"
        data.update(extra or {})
        r = self.call("POST", f"/api/v1/chantiers/{pid}/preuves", data=data,
                      files={"photo": ("photo.jpg", img_bytes, "image/jpeg")})
        return r


# --------------------------------------------------------------------------
# Photos de terrain
# --------------------------------------------------------------------------
def scene(seed, size=(960, 720)):
    """Une scene de chantier procedurale : ciel, sol, blocs de murs, ouvertures, ombres."""
    rng = np.random.default_rng(seed)
    w, h = size
    img = Image.new("RGB", size, tuple(int(x) for x in rng.integers(150, 220, 3)))
    d = ImageDraw.Draw(img)
    horizon = int(h * rng.uniform(0.35, 0.55))
    d.rectangle([0, horizon, w, h], fill=tuple(int(x) for x in rng.integers(90, 160, 3)))
    for _ in range(int(rng.integers(4, 9))):
        x0 = int(rng.integers(0, w - 120)); bw = int(rng.integers(80, 320))
        y1 = horizon + int(rng.integers(-20, 60)); bh = int(rng.integers(60, 300))
        d.rectangle([x0, y1 - bh, x0 + bw, y1], fill=tuple(int(x) for x in rng.integers(60, 230, 3)))
        for _k in range(int(rng.integers(0, 4))):
            ox = x0 + int(rng.integers(5, max(6, bw - 30))); oy = y1 - bh + int(rng.integers(5, max(6, bh - 30)))
            d.rectangle([ox, oy, ox + 25, oy + 25], fill=(30, 30, 35))
    for _ in range(int(rng.integers(3, 8))):
        x = int(rng.integers(0, w)); d.line([x, horizon - 200, x + int(rng.integers(-40, 40)), h], fill=(90, 70, 50), width=6)
    arr = np.asarray(img).astype(np.int16) + rng.integers(-12, 12, (h, w, 3))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def reshoot(img, seed):
    """Nouvelle photo du meme endroit : cadrage decale de 15 a 25 %, lumiere differente, nouveau bruit."""
    rng = np.random.default_rng(seed)
    w, h = img.size
    dx, dy = int(w * rng.uniform(0.15, 0.25)), int(h * rng.uniform(0.05, 0.15))
    out = img.crop((dx, dy, dx + int(w * 0.75), dy + int(h * 0.8))).resize((w, h))
    arr = np.asarray(out).astype(np.float32) * rng.uniform(0.8, 1.2) + rng.normal(0, 8, (h, w, 3))
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def recrop(img, seed):
    """Fraude : recadrage leger d'une preuve deja envoyee, recompressee."""
    rng = np.random.default_rng(seed)
    w, h = img.size
    m = rng.uniform(0.02, 0.06)
    out = img.crop((int(w * m), int(h * m), int(w * (1 - m)), int(h * (1 - m)))).resize((w, h))
    b = io.BytesIO(); out.save(b, "JPEG", quality=70); b.seek(0)
    return Image.open(b).convert("RGB")


def screen_photo(img, seed, bezel=False):
    """Fraude : photo d'un ecran qui affiche une preuve (flou, moire, dominante, legere rotation, bord d'ecran)."""
    rng = np.random.default_rng(seed)
    w, h = img.size
    shot = img.filter(ImageFilter.GaussianBlur(1.2))
    arr = np.asarray(shot).astype(np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    arr += 10 * np.sin((xx + yy * 0.7) / rng.uniform(2.5, 4.0))[..., None]            # moire
    arr *= np.array([rng.uniform(0.9, 1.0), rng.uniform(0.95, 1.05), rng.uniform(1.0, 1.15)])  # dominante bleue
    shot = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).rotate(rng.uniform(-3, 3), fillcolor=(10, 10, 12))
    if bezel:
        canvas = Image.new("RGB", (w, h), (15, 15, 18))
        inner = shot.resize((int(w * 0.8), int(h * 0.8)))
        canvas.paste(inner, (int(w * 0.1), int(h * 0.1)))
        shot = canvas
    return shot


def jpeg(img, lat=None, lng=None, when=None, quality=88):
    """Encode avec EXIF : GPS et date de prise de vue (heure locale = UTC a Abidjan)."""
    ex = Image.Exif()

    def dms(x):
        x = abs(x); d = int(x); m = int((x - d) * 60); s = round(((x - d) * 60 - m) * 60, 4)
        return (float(d), float(m), s)
    if lat is not None:
        ex[0x8825] = {1: "N" if lat >= 0 else "S", 2: dms(lat), 3: "E" if lng >= 0 else "W", 4: dms(lng)}
    if when is not None:
        ex.get_ifd(0x8769)[0x9003] = when.strftime("%Y:%m:%d %H:%M:%S")
    b = io.BytesIO()
    img.save(b, "JPEG", quality=quality, exif=ex.tobytes())
    return b.getvalue()


def offset(lat, lng, meters_north, meters_east):
    return lat + meters_north / 111_320, lng + meters_east / (111_320 * np.cos(np.radians(lat)))


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
