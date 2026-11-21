"""Accueil des métiers sur les données de démonstration : inspecteur, fournisseur, télépilote.
Lancement : python3 test_metiers.py
"""
import os, re, sys, tempfile
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_metiers_")
import app as A

A.app.config["TESTING"] = True
A.app.test_cli_runner().invoke(args=["demo"])
ok = 0


def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("  ✓", msg)


def login(email):
    c = A.app.test_client()
    t = re.search(r'name="csrf" value="([^"]+)"', c.get("/connexion").get_data(as_text=True)).group(1)
    c.post("/connexion", data={"csrf": t, "email": email, "password": "Demo-Chantier-2026"})
    return c


print("Inspectrice")
h = login("awa@demo.chantiervrai.ci").get("/").get_data(as_text=True)
check("Prochaine inspection" in h and "Faire l&#39;inspection" in h and "Itinéraire" in h, "prochaine inspection en grand, avec itinéraire")
check("Nouvelle demande" in h and "answer_inspection" not in h and "/inspections/" in h and "Accepter" in h, "demande à accepter ou refuser sur place")
check("aplomb des murs" in h, "le message du propriétaire est visible")
check("Gagné ce mois" in h and "contrôleur habilité" in h, "chiffres du mois et chantiers contrôlés")
print("Fournisseur")
h = login("quincaillerie@demo.chantiervrai.ci").get("/").get_data(as_text=True)
check("Prochaine livraison" in h and "CMD-DEMO-0002" in h and "Demain" in h, "livraison de demain en grand")
check("CMD-DEMO-0003" in h and "À accepter" in h, "commande à accepter dans « À faire »")
check("/photos/" not in h, "aucune photo privée du chantier montrée au fournisseur")
print("Télépilote")
h = login("pilote@demo.chantiervrai.ci").get("/").get_data(as_text=True)
check("Prochain vol" in h and "Envoyer les photos du vol" in h, "prochain vol en grand")
check("Vous achetez un terrain" not in h and "Aucun chantier pour l" not in h, "pas de blocs sans rapport avec le métier")
print("Propriétaire inchangé")
h = login("aminata@demo.chantiervrai.ci").get("/").get_data(as_text=True)
check("ph-hero" not in h and "Vos chantiers" in h, "l'accueil du propriétaire garde son fil")
print(f"\nAccueil des métiers : {ok} vérifications OK")
