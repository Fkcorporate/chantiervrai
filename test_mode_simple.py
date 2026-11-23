"""Mode simple du particulier : l'essentiel d'abord, le reste replié dans « Autres fonctions », bascule vers le mode complet.
Données de démonstration. Lancement : python3 test_mode_simple.py
"""
import os, re, sys, tempfile
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_simple_")
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

A.app.config["TESTING"] = True
A.app.test_cli_runner().invoke(args=["demo"])
PW = "Demo-Chantier-2026"
s = A.connect()
ok = 0


def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("  ✓", msg)


def web(email):
    c = A.app.test_client()
    page = c.get("/connexion").get_data(as_text=True)
    c.post("/connexion", data={"email": email, "password": PW, "csrf": re.search(r'name="csrf" value="([^"]+)"', page).group(1)})
    return c


def csrf(c, url):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)


api = A.app.test_client()
tok = lambda e: api.post("/api/v1/connexion", json=dict(email=e, password=PW)).json["token"]
H = lambda t: {"Authorization": f"Bearer {t}"}
AMI = "aminata@demo.chantiervrai.ci"
vid = s.execute("SELECT id FROM projects WHERE name LIKE 'Villa%'").fetchone()[0]
P = f"/chantiers/{vid}"
labels = lambda groups: [i["label"] for g in groups for i in g["items"]]

print("Particulier : mode simple par défaut")
check(s.execute("SELECT role, advanced FROM users WHERE email = ?", (AMI,)).fetchone()[:] == ("proprio", 0), "Aminata est particulière, réglage d'origine")
own = web(AMI)
h = own.get(P).get_data(as_text=True)
check('class="fp-answers' in h and "Avancement" in h and "versés sur" in h and "point(s) à voir" not in h
      and ("points à voir" in h or "point à voir" in h or "Rien à décider" in h),
      "les trois réponses en haut : avancement, argent versé, points à voir")
check('class="fp-hero"' in h and h.index('class="fp-hero"') < h.index('fp-answers'), "la dernière photo vérifiée en tête, la synthèse par-dessus")
check('class="actionbar"' not in h and h.count('class="post decision"') <= 1, "une seule carte de décision, plus de barre collante en double")
check("Inviter la famille" in h and "Faire inspecter" in h and "fp-shortcuts" not in h, "trois gestes directs à la place des familles de fonctions")
check(f'href="{P}/conversation"' in h and ">Messages<" in h and "onglet=vues" not in h.split('class="tabs"')[1].split("</nav>")[0],
      "onglets : Accueil, Preuves, Paiements, Messages (Vues et Dossier passent dans le panneau)")
check("Tous mes chantiers" in h and h.count('class="dr-foot') == 1 and "Académie" not in h.split('id="fn-drawer"')[1].split("</dialog>")[0],
      "le panneau ne parle que du chantier : une sortie « Tous mes chantiers »")
check("Autres fonctions" in h and "data-collapsed" in h, "le reste est replié dans « Autres fonctions »")
check("Activité récente" not in h, "pas de doublon « Activité récente » sous le fil")
check("Toujours tout afficher" in h, "la bascule vers le mode complet est proposée")
j = api.get(f"/api/v1{P}", headers=H(tok(AMI))).json["project"]
fn = j["functions"]
core = [g for g in fn if not g["collapsed"]]
check(j["simple_mode"] is True and fn[-1]["collapsed"] and sum(not g["collapsed"] for g in fn) == len(fn) - 1,
      "application : même tri, une seule famille repliée, en dernier")
n_core = len(labels(core))
check(12 <= n_core <= 18, f"{n_core} fonctions essentielles visibles")
for need in ("Preuves photo et vidéo", "Étapes et paiements", "Conversation du chantier", "Plan et réalité", "Plan de financement",
             "Intervenants et accès", "Inspection indépendante", "Demandes d'achat du chef", "Historique des paiements"):
    check(need in labels(core), f"essentiel visible : {need}")
for later in ("Stock du chantier", "Export comptable (CSV)", "Calculateur de matériaux", "Journal de chantier"):
    check(later in labels(fn[-1:]), f"rangé dans « Autres fonctions » : {later}")

print("Rien n'est perdu")
own.post("/compte/mode", data={"mode": "complet", "csrf": csrf(own, P), "next": P})
full = api.get(f"/api/v1{P}", headers=H(tok(AMI))).json["project"]
check(full["simple_mode"] is False and not any(g["collapsed"] for g in full["functions"]), "mode complet : plus rien de replié")
check(sorted(labels(fn)) == sorted(labels(full["functions"])), f"les {len(labels(fn))} fonctions sont les mêmes dans les deux modes")
h = own.get(P).get_data(as_text=True)
check("Revenir au mode simple" in h and "data-collapsed" not in h and "Activité récente" in h, "page complète, retour au mode simple proposé")
r = own.post("/compte/mode", data={"mode": "simple", "csrf": csrf(own, P), "next": "//pirate.example"}, follow_redirects=False)
check(r.status_code == 302 and "pirate" not in r.headers["Location"], "retour au mode simple, sans redirection extérieure")
check(s.execute("SELECT advanced FROM users WHERE email = ?", (AMI,)).fetchone()[0] == 0, "réglage enregistré")
t = tok(AMI)
check(api.post("/api/v1/compte/mode", json={"mode": "complet"}, headers=H(t)).json["simple_mode"] is False, "application : bascule en mode complet")
check(api.post("/api/v1/compte/mode", json={"mode": "simple"}, headers=H(t)).json["simple_mode"] is True, "application : retour au mode simple")
check(api.post("/api/v1/compte/mode", json={"mode": "complet"}).status_code == 401, "application : bascule refusée sans connexion")
check(own.post("/compte/mode", data={"mode": "complet"}).status_code == 400, "site : bascule refusée sans jeton CSRF")

print("Les autres profils ne changent pas")
chef = api.get(f"/api/v1{P}", headers=H(tok("koffi@demo.chantiervrai.ci"))).json["project"]
check(chef["simple_mode"] is None and not any(g["collapsed"] for g in chef["functions"]), "chef : tout visible, pas de bascule")
check(labels(chef["functions"]).count("Drone et caméra") <= 1, "chef : plus de « Drone et caméra » en double")
s.execute("UPDATE users SET role = 'pro', profession = 'architecte' WHERE email = ?", (AMI,)); s.commit()
pro = api.get(f"/api/v1{P}", headers=H(tok(AMI))).json["project"]
check(pro["simple_mode"] is None and not any(g["collapsed"] for g in pro["functions"]), "professionnel propriétaire : tout visible")
s.execute("UPDATE users SET role = 'proprio', profession = NULL WHERE email = ?", (AMI,)); s.commit()

print("Anglais")
s.execute("UPDATE users SET lang = 'en' WHERE email = ?", (AMI,)); s.commit()
h = web(AMI).get(P + "?lang=en").get_data(as_text=True)
check("Other functions" in h and "paid of" in h and "Always show everything" in h and "Book an inspection" in h, "mode simple traduit")

print("Vues : carte satellite nette")
s.execute("UPDATE users SET lang = 'fr' WHERE email = ?", (AMI,)); s.commit()
h = web(AMI).get(P + "?onglet=vues").get_data(as_text=True)
check('id="sat-map"' in h and "World_Imagery" in h and h.index('id="sat-map"') < h.index("Suivi mois par mois"),
      "la carte satellite Esri est en tête des vues, le suivi mensuel Sentinel en dessous")
check("Parcelle" in h and "photos vérifiées" in h and "pas du jour" in h, "légende : parcelle, photos vérifiées, date de l'image expliquée")
check("tile.openstreetmap.org" in h and h.count("leaflet.js") == 1, "bouton Plan disponible, Leaflet chargé une seule fois")

print(f"\nMode simple : {ok} vérifications OK")
