"""Version ordinateur : tableau de bord, fiche chantier, conversation en trois panneaux, palette de recherche.
Lancement : python3 test_bureau.py
"""
import os, re, sys, tempfile
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_bureau_")
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


print("Tableau de bord du propriétaire")
own = login("aminata@demo.chantiervrai.ci")
h = own.get("/").get_data(as_text=True)
check('class="dk-only dk"' in h and "Versé au total" in h and "Décisions en attente" in h, "chiffres clés")
check('class="dk-table"' in h and "Villa R+1 à Bingerville" in h and "Groupe scolaire" in h, "tableau des chantiers")
check("À décider" in h and "Dalle basse terminée" in h and "/achats#a" in h and "/avenants#c" in h, "étape, achat et avenant à décider")
check('class="mb-only"' in h and "Vos chantiers" in h, "le fil du téléphone reste dans la page")
check('id="dk-cmd"' in h and "/chantiers/1" in h.split('id="dk-cmd"')[1], "palette de recherche avec les chantiers")
check("desktop.css" in h and 'media="(min-width: 1100px)"' in h, "styles ordinateur chargés seulement sur grand écran")
print("Fiche chantier")
h = own.get("/chantiers/1").get_data(as_text=True)
check("dk-proj" in h and "Étapes et paiements" in h and "dk-flow" in h, "frise et tableau des étapes")
check("dk-decide" in h and "Vérifier et valider" in h and "Reste au contrat" in h, "décision et argent à droite")
check('class="dk-crumb"' in h and "Toutes les fonctions" in h, "fil d'Ariane et accès aux fonctions")
print("Conversation")
h = own.get("/chantiers/1/conversation").get_data(as_text=True)
check('class="dk-threads"' in h and h.count('class="dk-thread') >= 2, "liste des conversations")
check('class="dk-info"' in h and "En attente de décision" in h and "Photos échangées" in h, "panneau d'information")
print("Chef et métiers")
h = login("koffi@demo.chantiervrai.ci").get("/chantiers/1").get_data(as_text=True)
check("dk-proj" not in h and 'class="dk-top"' in h, "le chef a la barre ordinateur, sans la fiche du propriétaire")
check("dk-chef" in h and "Demandes d&#39;achat" in h and "Journal de la semaine" in h and "Hier" in h, "chef : achats et journal de la semaine en tableaux")
check("Remplir le journal du jour" in h and "Propriétaire" in h and "Aminata" in h, "chef : à faire aujourd'hui, propriétaire, conversation")
check('id="shoot"' in h or "Déclarer" in h or "Preuves de cette étape" in h, "chef : preuves et déclaration toujours accessibles")
h = login("quincaillerie@demo.chantiervrai.ci").get("/").get_data(as_text=True)
check("Livraisons de la semaine" in h and "CMD-DEMO-0003" in h and "À accepter" in h and "/commandes/" in h, "fournisseur : tableau des commandes et livraisons de la semaine")
check('class="mb-only"' in h and "ph-hero" in h, "fournisseur : l'accueil du téléphone reste en place")
h = login("awa@demo.chantiervrai.ci").get("/").get_data(as_text=True)
check("dk-only" in h and "Demandes à accepter" in h and "/inspections/" in h and "Prochaine inspection" in h, "inspectrice : missions en tableau, demandes à accepter")
check('class="mb-only"' in h and "ph-hero" in h, "inspectrice : l'accueil du téléphone reste en place")
h = login("pilote@demo.chantiervrai.ci").get("/").get_data(as_text=True)
check("Avant chaque vol" in h and "Prochain vol" in h and "Tous les mois" in h and "ANAC" in h, "télépilote : vols en tableau et consignes")
print(f"\nVersion ordinateur : {ok} vérifications OK")
