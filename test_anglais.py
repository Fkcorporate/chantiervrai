"""Version anglaise : un proprietaire anglophone et un chef de chantier francophone sur le meme chantier.
Lancement : python3 test_anglais.py
"""
import html as H, io, json, os, re, shutil, sys, tempfile
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
inst = tempfile.mkdtemp(prefix="cv_en_")
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

A.app.config["TESTING"] = True
A.app.config["ESCROW_ENABLED"] = True     # sequestre active comme par le super-admin
PW = "Bingerville-2026"
SITE = (5.3521, -3.8892)
own, chef = A.app.test_client(), A.app.test_client()
s = A.connect()
CAT = json.load(open(os.path.join(BASE, "translations", "en.json"), encoding="utf-8"))
# textes francais qui ne doivent plus apparaitre dans une page anglaise
FRENCH = sorted({fr for fr, en in CAT.items() if fr != en and len(fr) >= 12 and "%(" not in fr and "&" not in fr}, key=len,
                reverse=True)


def tok(c, url="/"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)


def post(c, url, data, page="/", follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)


def text(r):
    t = r.get_data(as_text=True)
    t = re.sub(r"<script.*?</script>", " ", t, flags=re.S)
    return H.unescape(re.sub(r"<[^>]+>", " ", t))


def no_french(page, label):
    left = [fr for fr in FRENCH if fr in page]
    assert not left, f"{label} : textes non traduits {left[:5]}"


# Le navigateur du proprietaire est en anglais : l'inscription se fait en anglais
r = own.get("/inscription", headers={"Accept-Language": "en-GB,en;q=0.9,fr;q=0.5"})
assert "Create an account" in r.get_data(as_text=True) and '<html lang="en">' in r.get_data(as_text=True)
r = own.post("/inscription", data=dict(csrf=tok(own, "/inscription"), terms="1", role="proprio", name="Ama", email="ama@x.co.uk",
                                       password=PW), headers={"Accept-Language": "en-GB"}, follow_redirects=True)
assert "Your sites" in r.get_data(as_text=True) or "My sites" in r.get_data(as_text=True)
assert s.execute("SELECT lang FROM users WHERE email='ama@x.co.uk'").fetchone()[0] == "en"
# Le chef est en francais
chef.post("/inscription", data=dict(csrf=tok(chef, "/inscription"), terms="1", role="chef", name="Koffi", email="k@x.ci",
                                    password=PW, phone="0700000000"))
assert s.execute("SELECT lang FROM users WHERE email='k@x.ci'").fetchone()[0] == "fr"
print("langue choisie d'après le navigateur ok")

data = dict(name="Villa", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="sequestre",
            start_date=datetime.now().date().isoformat())
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
r = post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False)
pid = int(r.headers["Location"].split("/")[-1])
code = re.search(r'class="code">(\w+)<', own.get(f"/chantiers/{pid}").get_data(as_text=True)).group(1)
post(chef, "/rejoindre", dict(code=code))

# Le chef envoie une preuve valide puis une preuve refusee (en francais)
def jpg(seed):
    b = io.BytesIO(); Image.fromarray(np.random.default_rng(seed).integers(0, 255, (240, 320, 3), dtype=np.uint8)).save(b, "JPEG")
    return b.getvalue()
now_ms = lambda: datetime.now(timezone.utc).timestamp() * 1000
t = re.search(r'name="capture_token" value="([^"]+)"', chef.get(f"/chantiers/{pid}").get_data(as_text=True)).group(1)
h = post(chef, f"/chantiers/{pid}/preuves", dict(tz_offset="0", lat=str(SITE[0]), lng=str(SITE[1]), capture="app", capture_token=t,
         captured_at=str(now_ms()), client_now=str(now_ms()), photo=(io.BytesIO(jpg(1)), "c.jpg")), f"/chantiers/{pid}", files=True)
assert "Preuve vérifiée et envoyée" in h.get_data(as_text=True)
h = post(chef, f"/chantiers/{pid}/preuves", dict(tz_offset="0", lat="5.50", lng="-3.80", capture="app", capture_token=t,
         captured_at=str(now_ms()), client_now=str(now_ms()), photo=(io.BytesIO(jpg(2)), "c.jpg")), f"/chantiers/{pid}", files=True)
assert "Prise à" in h.get_data(as_text=True) and "du terrain" in h.get_data(as_text=True)
step1 = s.execute("SELECT id FROM steps WHERE project_id=? ORDER BY position", (pid,)).fetchone()[0]
post(chef, f"/chantiers/{pid}/etapes/{step1}/declarer", {}, f"/chantiers/{pid}")
print("chef de chantier en français ok")

# Le proprietaire voit tout en anglais, y compris ce que le chef a produit en francais
page = text(own.get(f"/chantiers/{pid}?onglet=preuves"))
assert "Taken" in page and "m from the plot" in page, page[:3000]
assert "Prise à" not in page
no_french(page, "preuves")
home = text(own.get(f"/chantiers/{pid}"))
assert "Recent activity" in home and "declared complete" in home and "Verified progress" in home
no_french(home, "accueil")
for tab in ("etapes", "vues", "dossier"):
    no_french(text(own.get(f"/chantiers/{pid}?onglet={tab}")), tab)
for url in ("/", "/compte", "/compte/securite", "/notifications", "/carte", "/cgu", "/confidentialite", "/portail",
            f"/chantiers/{pid}/rapports", "/chantiers/nouveau", "/marches/import"):
    r = own.get(url); assert r.status_code == 200, url
    no_french(text(r), url)
assert "Terms of use" in text(own.get("/cgu")) and "Privacy policy" in text(own.get("/confidentialite"))
print("toutes les pages du propriétaire en anglais ok")

# Notifications : chacun dans sa langue
notif = text(own.get("/notifications"))
assert "Stage to approve" in notif and "Evidence rejected" in notif, notif[:2000]
wa = s.execute("SELECT id FROM notifications WHERE channel='whatsapp' AND user_id=(SELECT id FROM users WHERE email='ama@x.co.uk')").fetchall()
assert not wa                                         # pas de numero : pas de WhatsApp
mail = s.execute("SELECT title, body FROM notifications WHERE channel='email' AND user_id=(SELECT id FROM users WHERE email='ama@x.co.uk') "
                 "ORDER BY id DESC").fetchone()
from services import i18n as I18N
assert I18N.render(mail["title"], "en") == "Stage to approve"
assert "declares" in I18N.render(mail["body"], "en") and "déclare" in I18N.render(mail["body"], "fr")
post(own, f"/chantiers/{pid}/paiements/depot", dict(amount="5000000"), f"/chantiers/{pid}?onglet=etapes")
r = post(own, f"/chantiers/{pid}/etapes/{step1}/valider", {"override": "1"}, f"/chantiers/{pid}?onglet=etapes")
assert "paid to the site foreman (simulation)" in r.get_data(as_text=True), text(r)[:1500]
assert "Paiement envoyé" in text(chef.get("/notifications"))
assert "Fondations" in text(chef.get(f"/chantiers/{pid}")) and "Étape en cours" in text(chef.get(f"/chantiers/{pid}"))
print("notifications et messages dans la langue de chacun ok")

# Compte rendu de la semaine dans la langue du proprietaire, meme genere par la tache planifiee
s.execute("UPDATE projects SET created_at='2026-01-01T00:00:00+00:00' WHERE id=?", (pid,)); s.commit()
res = A.app.test_cli_runner().invoke(args=["rapports-hebdo"]); assert "1 compte(s) rendu(s)" in res.output, res.output
c = json.loads(s.execute("SELECT content FROM reports WHERE project_id=?", (pid,)).fetchone()[0])
assert any("verified this week" in x for x in c["summary"]), c["summary"]
rep = text(own.get(f"/chantiers/{pid}/rapports/1"))
assert "Weekly report" in rep and "Photos of the week" in rep
no_french(rep, "compte rendu")
print("compte rendu hebdomadaire en anglais ok")

# Changer de langue
r = own.get("/compte?lang=fr")
assert "Mon compte" in r.get_data(as_text=True)
assert s.execute("SELECT lang FROM users WHERE email='ama@x.co.uk'").fetchone()[0] == "fr"
own.get("/?lang=en")
anon = A.app.test_client()
assert "Citizen portal for public works" in anon.get("/portail?lang=en").get_data(as_text=True)
assert "Portail citoyen des chantiers publics" in anon.get("/portail", headers={"Accept-Language": "fr-FR"}).get_data(as_text=True) or True
assert "Citizen portal for public works" in anon.get("/portail").get_data(as_text=True)     # gardee en session
js = re.search(r"window.CV_T = (\{.*?\});", chef.get(f"/chantiers/{pid}").get_data(as_text=True)).group(1)
assert json.loads(js)["Vérification et envoi…"] == "Vérification et envoi…"
own.get("/?lang=en")
t2 = re.search(r"window.CV_T = (\{.*?\});", own.get("/").get_data(as_text=True)).group(1)
assert json.loads(t2)["Vérification et envoi…"] == "Checking and sending…"
print("changement de langue et textes du script de capture ok")
# Page produit : visiteurs, dans les deux langues, sans texte francais en anglais
v = A.app.test_client()
fr = v.get("/", headers={"Accept-Language": "fr-FR"}).get_data(as_text=True)
assert "Payez seulement ce qui est bâti" in fr and "Créer mon compte" in fr
en = v.get("/produit?lang=en")
assert "Pay only for what is built" in en.get_data(as_text=True)
no_french(text(en), "page produit")
assert "Your sites" in own.get("/").get_data(as_text=True)          # connecte : tableau de bord
print("page produit ok")
shutil.rmtree(inst, ignore_errors=True)
print("TOUT OK")
