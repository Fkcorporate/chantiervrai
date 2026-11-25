"""Organisation du chantier pour le propriétaire : onglets Accueil · Preuves · À valider · Messages · Plus,
accueil court, onglet « À valider », page Plus, « Fonctions de l'appli » (modules allumés ou masqués), API mobile.
Données de démonstration. Lancement : python3 test_fonctions.py
"""
import os, re, sys, tempfile
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_fonctions_")
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
own = web(AMI)

print("Onglets du propriétaire")
h = own.get(P).get_data(as_text=True)
tabs = h.split('class="tabs tabs-5"')[1].split("</nav>")[0]
order = [tabs.index(x) for x in (">Accueil<", ">Preuves<", "onglet=valider", "/conversation", "onglet=plus")]
check(order == sorted(order), "Accueil · Preuves · À valider · Messages · Plus, dans cet ordre")
with A.app.test_request_context():
    from flask import g as _g
    n_dec = A.pending_decisions(vid)
check(n_dec >= 1 and f'aria-label="{n_dec} à valider">{n_dec}</em>' in tabs, f"pastille « À valider » : {n_dec} décision(s) en attente")
check("bb-plus" not in tabs and 'class="tabs-fn"' not in tabs, "ni bouton « + » ni « Toutes les fonctions » en double dans la barre")

print("Accueil court")
check('class="fp-hero"' in h and h.index('class="fp-hero"') < h.index("fp-answers"), "la dernière photo vérifiée en tête, la synthèse par-dessus")
ans = h.split("fp-answers")[1].split("</nav>")[0]
check("onglet=valider" in ans and "à valider" in ans, "troisième chiffre : les décisions, qui mènent à « À valider »")
check(h.count('class="nw"') + h.count('class="nw fp-review"') <= 5 and "Dernières nouvelles" in h and "fil=tout" in h,
      "3 dernières nouvelles (et les messages du chef non lus), lien « Tout le fil »")
check('class="post decision"' not in h and "todo-list" not in h and 'class="fp-chat"' not in h, "plus de décision, de liste d'alertes ni de carte conversation en double")
full = own.get(P + "?fil=tout").get_data(as_text=True)
check(full.count('class="post') >= 4 and "Argent suivi" in full and "Accueil du chantier" in full, "« Tout le fil » : le fil complet et la colonne Argent, avec retour à l'accueil")

print("À valider")
hv = own.get(P + "?onglet=valider").get_data(as_text=True)
check("À valider" in hv and "attendent votre accord" in hv and hv.count('class="dv"') == n_dec, "une carte par décision, avec le total en attente")
buy = s.execute("SELECT id FROM purchase_requests WHERE project_id = ? AND status = 'demande' ORDER BY id LIMIT 1", (vid,)).fetchone()
if buy:
    tk = csrf(own, P + "?onglet=valider")
    r = own.post(f"{P}/achats", data={"id": buy[0], "action": "refuse", "refusal": "", "next": P + "?onglet=valider", "csrf": tk})
    check(r.headers["Location"].endswith("onglet=valider") and s.execute("SELECT status FROM purchase_requests WHERE id = ?", buy).fetchone()[0] == "demande",
          "refus sans raison : refusé, on reste sur « À valider »")
    r = own.post(f"{P}/achats", data={"id": buy[0], "action": "accept", "next": P + "?onglet=valider", "csrf": tk})
    check(s.execute("SELECT status FROM purchase_requests WHERE id = ?", buy).fetchone()[0] == "acceptee" and r.headers["Location"].endswith("onglet=valider"),
          "« Accepter » depuis « À valider » : l'achat passe à payer, retour sur l'onglet")
    check("J&#39;ai payé" in own.get(P + "?onglet=valider").get_data(as_text=True), "puis bouton « J'ai payé »")
    r = own.post(f"{P}/achats", data={"id": buy[0], "action": "accept", "next": "https://pirate.example/", "csrf": tk})
    check("pirate" not in r.headers.get("Location", ""), "le retour ne sort jamais du site")
co = s.execute("SELECT id FROM change_orders WHERE project_id = ? AND status = 'proposee' LIMIT 1", (vid,)).fetchone()
if co:
    n_steps = s.execute("SELECT COUNT(*) FROM steps WHERE project_id = ?", (vid,)).fetchone()[0]
    own.post(f"{P}/avenants", data={"id": co[0], "action": "accept", "next": P + "?onglet=valider", "csrf": csrf(own, P + "?onglet=valider")})
    check(s.execute("SELECT COUNT(*) FROM steps WHERE project_id = ?", (vid,)).fetchone()[0] == n_steps + 1,
          "travaux supplémentaires acceptés depuis « À valider » : nouvelle étape")
chef_c = web("koffi@demo.chantiervrai.ci")
check(chef_c.get(P + "?onglet=valider").status_code == 200 and "attendent votre accord" not in chef_c.get(P + "?onglet=valider").get_data(as_text=True),
      "le chef n'a pas l'onglet « À valider » du propriétaire")

print("Plus et fonctions de l'appli")
plus = lambda c: c.get(P + "?onglet=plus").get_data(as_text=True).split("data-px>")[1].split('id="fn-drawer"')[0]
hp = plus(own)
vis = hp.split("px-hidden")[0]
check("Preuves photo et vidéo" in vis and "Plan de financement" in vis and "Stock du chantier" not in vis and "Export comptable" not in vis,
      "page Plus : l'essentiel et les modules allumés ; stock et export masqués par défaut")
off = hp.split("px-hidden")[1]
check("Stock du chantier" in off and "Éteinte" in off and "Les rallumer" in off and 'data-px-grp hidden' not in hp,
      "les fonctions éteintes restent affichées en bas de Plus, utilisables, avec « Les rallumer »")
app_sec = hp.split("L&#39;application")[1]
check(all(x in app_sec for x in ("Tous mes chantiers", "Carte", "Terrains", "Assistant", "Académie", "Mon compte", "Aide")),
      "menu de l'application dans Plus : chantiers, carte, terrains, assistant, académie, compte, aide")
check(own.get(P + "/stock").status_code == 200, "une fonction éteinte s'ouvre quand même")
check("Fonctions de l&#39;appli" in hp and "Tous mes chantiers" in hp, "réglage « Fonctions de l'appli » et sortie vers tous les chantiers")
hf = own.get("/compte/fonctions").get_data(as_text=True)
check(hf.count('role="switch"') == len(A.FEATURE_MODULES) and "Toujours actif" in hf, "un interrupteur par module, le cœur toujours actif")
on = [k for k in A.enabled_features(s.execute("SELECT * FROM users WHERE email = ?", (AMI,)).fetchone())]
r = own.post("/compte/fonctions", data={"f": on + ["stock"], "next": P + "?onglet=plus", "csrf": csrf(own, "/compte/fonctions")})
check(r.headers["Location"].endswith("onglet=plus") and "Stock du chantier" in plus(own).split("px-hidden")[0],
      "allumer « Stock » : la fonction apparaît, retour sur la page Plus")
own.post("/compte/fonctions", data={"f": ["inspection"], "csrf": csrf(own, "/compte/fonctions")})
hp = plus(own).split("px-hidden")[0]
check("Vues satellite" not in hp and "Preuves photo et vidéo" in hp and "Historique des paiements" in hp, "tout éteindre sauf l'inspection : le cœur reste")
own.post("/compte/fonctions", data={"action": "defaut", "csrf": csrf(own, "/compte/fonctions")})
check(s.execute("SELECT features FROM users WHERE email = ?", (AMI,)).fetchone()[0] is None, "« Réglages par défaut » rétablit le choix d'origine")
check(own.post("/compte/fonctions", data={"f": ["stock"]}).status_code == 400, "réglage refusé sans jeton CSRF")

print("Application mobile")
t = tok(AMI)
j = api.get(f"/api/v1{P}", headers=H(t)).json["project"]
check(j["features"] and "stock" not in j["features"] and j["functions"][-1]["collapsed"] and j["functions"][-1]["title"] == "Fonctions masquées",
      "API : modules allumés, fonctions masquées dans une famille repliée")
m = api.get("/api/v1/compte/fonctions", headers=H(t)).json["modules"]
check(len(m) == len(A.FEATURE_MODULES) and any(x["key"] == "vues" and x["on"] for x in m), "API : liste des modules avec leur état")
api.post("/api/v1/compte/fonctions", json={"features": A.FEATURE_KEYS}, headers=H(t))
j = api.get(f"/api/v1{P}", headers=H(t)).json["project"]
check(not any(g["collapsed"] for g in j["functions"]), "API : tout allumer, plus rien de masqué")
check(api.post("/api/v1/compte/fonctions", json={"features": ["stock"]}).status_code == 401, "API : refusé sans connexion")
api.post("/api/v1/compte/fonctions", json={"features": []}, headers=H(t))
chef = api.get(f"/api/v1{P}", headers=H(tok("koffi@demo.chantiervrai.ci"))).json["project"]
check(chef["features"] is None and not any(g["collapsed"] for g in chef["functions"]), "chef : tout visible, pas de modules")
s.execute("UPDATE users SET role = 'pro', profession = 'architecte', features = NULL WHERE email = ?", (AMI,)); s.commit()
pro = api.get(f"/api/v1{P}", headers=H(tok(AMI))).json["project"]
check(not any(g["collapsed"] for g in pro["functions"]), "professionnel propriétaire : tout allumé par défaut")
s.execute("UPDATE users SET role = 'proprio', profession = NULL WHERE email = ?", (AMI,)); s.commit()

print("Vues : carte satellite nette")
h = web(AMI).get(P + "?onglet=vues").get_data(as_text=True)
check('id="sat-map"' in h and "World_Imagery" in h and h.index('id="sat-map"') < h.index("Suivi mois par mois"),
      "la carte satellite Esri est en tête des vues, le suivi mensuel Sentinel en dessous")
check("Parcelle" in h and "photos vérifiées" in h and "pas du jour" in h, "légende : parcelle, photos vérifiées, date de l'image expliquée")

print("Anglais")
s.execute("UPDATE users SET lang = 'en' WHERE email = ?", (AMI,)); s.commit()
e = web(AMI)
h = e.get(P).get_data(as_text=True)
check("To approve" in h and "Latest news" in h and "paid of" in h, "onglets et accueil traduits")
check("Choose what you see" in e.get("/compte/fonctions").get_data(as_text=True) and "Hidden functions" in e.get(P + "?onglet=plus").get_data(as_text=True),
      "fonctions de l'appli traduites")

print(f"\nOnglets, À valider, Plus et fonctions de l'appli : {ok} vérifications OK")
