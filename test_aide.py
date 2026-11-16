"""Test du guide d'utilisation : page Aide par profil, francais et anglais, guide de l'equipe reserve, captures.
Lancement : python3 test_aide.py
"""
import os, re, sys, tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_aide_")
if os.environ.get("DATABASE_URL", "").startswith("postgres"):
    from services import db as _DB
    try:
        import psycopg  # noqa: F401
    except ImportError:
        from tests_support import pgwire
        _DB.set_driver(pgwire)
    _c = _DB.connect("")
    _c.execute("DROP SCHEMA public CASCADE"); _c.execute("CREATE SCHEMA public"); _c.commit(); _c.close()

import app as A
from services import guide_content as GUIDE

A.app.config["TESTING"] = True
PW = "Bingerville-2026"
ok = 0


def check(cond, label):
    global ok
    assert cond, label
    ok += 1
    print("  ok ", label)


def tok(c, url):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True).replace('&#39;', "'")).group(1)


def register(email, role, **extra):
    c = A.app.test_client()
    data = dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW, **extra)
    data["csrf"] = tok(c, "/inscription")
    r = c.post("/inscription", data=data)
    assert r.status_code == 302, email
    return c


print("Contenu")
for gd in GUIDE.GUIDES:
    for lang in ("fr", "en"):
        x = GUIDE.localize(gd, lang)
        texts = [x["title"], x["who"], x["intro"]] + [s["title"] for s in x["sections"]] + \
                [st for s in x["sections"] for st in s["steps"]] + [s["tip"] for s in x["sections"] if s["tip"]]
        assert all(t and t.strip() for t in texts), (gd["slug"], lang)
    for s in gd["sections"]:
        for d in [s["title"]] + s["steps"] + ([s["tip"]] if s["tip"] else []):
            assert d["fr"] != d["en"], d["fr"]
check(True, "6 guides complets en français et en anglais")
imgs = {s["img"] for gd in GUIDE.GUIDES for s in gd["sections"] if s["img"]}
check(all(os.path.exists(os.path.join(BASE, "static", "aide", i + ".png")) for i in imgs), f"{len(imgs)} captures présentes")

print("Page publique")
c = A.app.test_client()
h = c.get("/aide").get_data(as_text=True).replace('&#39;', "'")
check("Propriétaire ou maître d'ouvrage" in h and "Valider une étape" in h, "visiteur : guide du propriétaire")
check("Équipe ChantierVrai" not in h and c.get("/aide/equipe").status_code == 404, "guide de l'équipe caché au public")
check(c.get("/aide/inexistant").status_code == 404, "profil inconnu : 404")
h = c.get("/aide/chef?lang=en").get_data(as_text=True).replace('&#39;', "'")
check("Site foreman" in h and "Send proof" in h and "Good to know" in h, "version anglaise")
check('href="/aide"' in c.get("/connexion?lang=fr").get_data(as_text=True).replace('&#39;', "'"), "lien Aide dans le menu public")

print("Guide selon le profil")
for role, word, extra in (("chef", "Rejoindre le chantier", {}), ("pro", "Ce que chaque métier fait", {"profession": "architecte"}),
                          ("fournisseur", "Remplir votre catalogue", {"supplier_terms": "1"}),
                          ("inspecteur", "Faire une inspection", {})):
    cl = register(f"{role}@aide.ci", role, **extra)
    cl.get("/?lang=fr")
    h = cl.get("/aide").get_data(as_text=True).replace('&#39;', "'")
    check(word in h and 'class="on" aria-current="page">Aide' in h, f"{role} : son guide, menu Aide actif")
own = register("proprio@aide.ci", "proprio")
own.get("/?lang=fr")
check("Créer votre compte et votre chantier" in own.get("/aide").get_data(as_text=True).replace('&#39;', "'"), "propriétaire : son guide")
check(own.get("/aide/equipe").status_code == 404, "propriétaire : pas de guide équipe")
s = A.connect()
s.execute("UPDATE users SET is_admin = 1, staff_role = 'support' WHERE email = 'proprio@aide.ci'"); s.commit()
h = own.get("/aide").get_data(as_text=True).replace('&#39;', "'")
check("Équipe ChantierVrai" in h and "Support et médiation" in own.get("/aide/equipe").get_data(as_text=True).replace('&#39;', "'"),
      "membre de l'équipe : guide équipe visible")
print(f"\n{ok} contrôles réussis.")
