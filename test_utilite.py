"""Corrections issues du test d'utilite par acteur : vignettes legeres, libelle de l'etape pour le chef,
pas de « Bien demarrer » pour un co-proprietaire, indice de confiance coherent avec le controle qualite,
liste « A traiter » de l'equipe, menu adapte au role, action a valider en tete de l'accueil.
Lancement : python3 test_utilite.py
"""
import io, os, re, sys, tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_utilite_")
if os.environ.get("DATABASE_URL", "").startswith("postgres"):
    from services import db as _DB
    try:
        import psycopg  # noqa: F401
    except ImportError:
        from tests_support import pgwire
        _DB.set_driver(pgwire)
    _c = _DB.connect("")
    _c.execute("DROP SCHEMA public CASCADE"); _c.execute("CREATE SCHEMA public"); _c.commit(); _c.close()

from PIL import Image
import app as A

A.app.config["TESTING"] = True
A.app.config["STAFF_2FA"] = False
assert "Propriétaire" in A.app.test_cli_runner().invoke(args=["demo"]).output
s = A.connect()
ok = 0


def check(cond, label):
    global ok
    assert cond, label
    ok += 1
    print("  ok ", label)


def login(email):
    c = A.app.test_client()
    t = re.search(r'name="csrf" value="([^"]+)"', c.get("/connexion").get_data(as_text=True)).group(1)
    r = c.post("/connexion", data=dict(email=email, password="Demo-Chantier-2026", csrf=t))
    assert r.status_code == 302, email
    return c


def html(r):
    return r.get_data(as_text=True).replace("&#39;", "'")


pid = s.execute("SELECT id FROM projects WHERE name LIKE 'Villa%'").fetchone()[0]
own, chef, sup = login("aminata@demo.chantiervrai.ci"), login("koffi@demo.chantiervrai.ci"), login("quincaillerie@demo.chantiervrai.ci")

pr = s.execute("SELECT * FROM proofs WHERE project_id = ? AND ok = 1 AND kind = 'photo' LIMIT 1", (pid,)).fetchone()
full, small = own.get(f"/photos/{pr['id']}").data, own.get(f"/photos/{pr['id']}/vignette").data
check(len(small) < len(full) / 2 and max(Image.open(io.BytesIO(small)).size) == 640, "vignette de 640 px, bien plus légère que la photo")
check(f"/photos/{pr['id']}/vignette" in html(own.get(f"/chantiers/{pid}?onglet=preuves")), "les cartes de preuve chargent la vignette")
check(A.app.test_client().get(f"/photos/{pr['id']}/vignette").status_code in (302, 401, 403), "vignette protégée")

check("en attente de la validation du propriétaire" in html(chef.get(f"/chantiers/{pid}")), "le chef voit que l'étape attend le propriétaire")

h = html(own.get(f"/chantiers/{pid}"))
check('class="actionbar"' not in h and 'class="post decision"' not in h and 'onglet=valider' in h.split('fp-answers')[1][:1500],
      "accueil : l'étape à valider est comptée dans la synthèse, qui mène à l'onglet « À valider »")
hv = html(own.get(f"/chantiers/{pid}?onglet=valider"))
check(hv.count('class="dv"') >= 1 and "Étape terminée" in hv and "Vérifier et payer" in hv and hv.index('class="dv"') < hv.index("À surveiller"),
      "onglet « À valider » : une carte par décision, avec ses boutons, puis les points à surveiller")
t = A.TRUST.compute(dict(A.trust_inputs(s, s.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone(),
                                        A.project_stats(pid, s), None)))
check(t["score"] <= 79, "problème de solidité ouvert : l'indice ne peut pas dire « bonne maîtrise »")

c = A.app.test_client()
t_ = re.search(r'name="csrf" value="([^"]+)"', c.get("/inscription").get_data(as_text=True)).group(1)
c.post("/inscription", data=dict(terms="1", role="proprio", name="Ibrahim", email="ib@x.ci", password="Bingerville-2026", csrf=t_))
uid = s.execute("SELECT id FROM users WHERE email='ib@x.ci'").fetchone()[0]
s.execute("INSERT INTO project_members (project_id, user_id, role, created_at) VALUES (?,?,?,?)", (pid, uid, "coproprio", A.now_iso())); s.commit()
h = html(c.get("/"))
check("Bien démarrer" not in h and "Villa R+1" in h, "co-propriétaire : pas de liste « Bien démarrer », le chantier tout de suite")

h = html(sup.get("/"))
check(">Carte<" not in h and ">Académie<" not in h and ">Assistant<" not in h and ">Paiements<" in h, "menu du fournisseur réduit à l'essentiel")
check(">Carte<" not in html(chef.get("/")) and ">Assistant<" in html(chef.get("/")), "menu du chef sans la carte")

A.app.test_cli_runner().invoke(args=["creer-admin", "awa@demo.chantiervrai.ci", "--role", "verification"])
s.execute("UPDATE users SET verified = 0 WHERE email = 'quincaillerie@demo.chantiervrai.ci'"); s.commit()
h = html(login("awa@demo.chantiervrai.ci").get("/admin"))
check("À traiter" in h and "Comptes à vérifier" in h and 'href="#verifier"' in h, "équipe : liste « À traiter » en tête de l'administration")

h = html(own.get(f"/chantiers/{pid}?onglet=dossier"))
check(h.index("Inviter quelqu'un") < h.index("Contrôle des matériaux") and 'href="#membres"' in h, "dossier : bouton « Inviter quelqu'un » en haut de l'onglet")
h = html(chef.get("/aide"))
secs = re.findall(r'<details class="card help-sec" id="s\d+"( open)?>', h)
check(len(secs) > 5 and all(secs[:5]) and not any(secs[5:]), "aide : les 5 premières sections ouvertes, les autres repliées")
pub = s.execute("SELECT id FROM projects WHERE is_public = 1 LIMIT 1").fetchone()
if pub:
    h = html(A.app.test_client().get(f"/portail/{pub[0]}"))
    check('class="btn report-fab" href="#signaler"' in h, "portail public : bouton « Signaler un problème » toujours visible")

def url_for_home_in_drawer(h):
    """Le pied du panneau « Toutes les fonctions » offre la sortie vers tous les chantiers."""
    foot = h[h.index('class="dr-foot'):]
    return 'href="/"' in foot[:foot.index("</div>")]


h = html(own.get(f"/chantiers/{pid}?onglet=valider"))
check('class="dv-watch"' in h and h.count('class="card alert"') == 0, "« À valider » : les points à surveiller regroupés dans une seule liste")
check("(s)" not in re.sub(r"<script.*?</script>", "", h, flags=re.S), "accueil : pluriels accordés (« 1 preuve refusée », pas « 1 preuve(s) refusée(s) »)")
check('class="appbar"' in h and 'class="tabs tabs-5"' in h and 'class="bottombar"' not in h and 'onglet=plus' in h
      and 'class="dr-foot' in h and url_for_home_in_drawer(h),
      "chantier du propriétaire sur téléphone : barre du haut (retour, alertes), onglets Accueil · Preuves · À valider · Messages · Plus")
h_home = html(own.get("/"))
bb = re.search(r'<nav class="bottombar".*?</nav>', h_home, re.S).group(0)
check(len(re.findall(r"<a href=", bb)) == 4 and "bb-more" in bb and 'class="on" aria-current="page"' in bb,
      "accueil sur téléphone : 4 onglets en bas + « Plus », onglet actif signalé")
check('<dialog class="sheet" id="nav-sheet"' in h_home and "Déconnexion" in h_home.split('id="nav-sheet"')[1],
      "panneau « Plus » : compte, autres rubriques, langue, déconnexion")
h_chef = html(chef.get("/"))
bb = re.search(r'<nav class="(?:bottombar|tabs)".*?</nav>', h_chef, re.S).group(0)
check("Paiements" in h_chef and ("Paiements" in bb or 'data-sheet="nav-sheet"' in h_chef), "chef : Paiements accessible en un geste")
with A.app.test_request_context():
    from services import i18n as I
    check(I.translate("%(n)s preuve(s) refusée(s)", "fr", n=1) == "1 preuve refusée" and I.translate("%(n)s preuve(s) refusée(s)", "fr", n=3) == "3 preuves refusées"
          and I.translate("%(n)s preuve(s) refusée(s)", "en", n=0).startswith("0 ") , "accord automatique des pluriels en français et en anglais")
h = html(chef.get(f"/chantiers/{pid}"))
check(h.index("Preuves de cette étape") < h.index("Règles de ce chantier") and "<summary><b>Règles" in h
      and h.index("more-actions") < h.index("Règles de ce chantier"), "chef : l'étape et ses preuves d'abord, les règles repliées")
A.app.test_cli_runner().invoke(args=["creer-admin", "awa@demo.chantiervrai.ci", "--role", "super"])
h = html(login("awa@demo.chantiervrai.ci").get("/admin"))
check('<details class="card fold-section" id="reglages">' in h and h.index('id="reglages"') < h.index('id="plateforme"')
      and 'href="#reglages"' in h, "administration : réglages rarement modifiés repliés, sommaire des sections")

h = html(own.get(f"/chantiers/{pid}/financement"))
check("window.CV_GLOSS" in h and "Trou de trésorerie" in h and "/static/ui.js?v=" in h and "/static/style.css?v=" in h,
      "glossaire des mots techniques et fichiers versionnés envoyés à la page")
from services import glossary as GL
check(all(len(e[0]) and len(e[1]) > 30 for e in GL.for_lang("fr") + GL.for_lang("en")) and len(GL.ENTRIES) >= 20, "glossaire complet en français et en anglais")
c2 = A.app.test_client()
t2 = re.search(r'name="csrf" value="([^"]+)"', c2.get("/connexion").get_data(as_text=True)).group(1)
r = c2.post("/connexion", data=dict(email="aminata@demo.chantiervrai.ci", password="Demo-Chantier-2026", csrf=t2), headers={"X-CV-Fetch": "1"})
check(r.status_code == 200 and r.is_json and r.get_json().get("redirect"), "envoi en arrière-plan : la redirection revient en JSON (réseau faible)")
h = html(chef.get(f"/chantiers/{pid}"))
print(f"\n{ok} contrôles réussis.")
