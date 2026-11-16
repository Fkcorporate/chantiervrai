"""Test de l'accompagnement foncier, du comptage des livraisons et de la comparaison plan / realite.
Lancement : python3 test_terrain_comptage.py
"""
import io, json, os, re, sys, tempfile
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_terrain_")
os.environ.pop("ANTHROPIC_API_KEY", None)
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
from services import counting as COUNT, land as LAND

A.app.config["TESTING"] = True
PW = "Bingerville-2026"
SITE = (5.3521, -3.8892)
s = A.connect()
ok = 0


def check(cond, label):
    global ok
    assert cond, label
    ok += 1
    print("  ok ", label)


def tok(c, url="/"):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True)).group(1)


def post(c, url, data, page="/", follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)


def html(r):
    return r.get_data(as_text=True).replace("&#39;", "'")


def one(q, *a):
    return s.execute(q, a).fetchone()


def register(email, role="proprio", **extra):
    c = A.app.test_client()
    extra.setdefault("supplier_terms", "1")
    assert post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW,
                                        **extra), "/inscription", follow=False).status_code == 302, email
    return c


def notes(email, title):
    return one("SELECT COUNT(*) FROM notifications n JOIN users u ON u.id = n.user_id WHERE u.email = ? AND n.title LIKE ? "
               "AND n.channel = 'app'", email, f"%{title}%")[0]


def jpg(seed):
    b = io.BytesIO()
    Image.fromarray(np.random.default_rng(seed).integers(0, 255, (480, 640, 3), dtype=np.uint8)).save(b, "JPEG")
    return b.getvalue()


now_ms = lambda: str(datetime.now(timezone.utc).timestamp() * 1000)


def capture(c, url, page, img, **extra):
    h = html(c.get(page))
    tk = re.search(r'name="capture_token" value="([^"]+)"', h).group(1)
    d = dict(tz_offset="0", lat=str(SITE[0]), lng=str(SITE[1]), capture="app", capture_token=tk, captured_at=now_ms(),
             client_now=now_ms(), photo=(io.BytesIO(img), "c.jpg"))
    d.update(extra)
    return html(post(c, url, d, page, files=True))


print("Règles du foncier")
check(LAND.assess("titre_foncier", {}, [])[0] == 1 and LAND.assess("attestation_villageoise", {}, [])[0] == 4, "risque de départ selon le document")
full = {c[0]: True for c in LAND.applicable("titre_foncier")}
check(LAND.assess("titre_foncier", full, [])[0] == 0, "titre foncier entièrement vérifié : risque faible")
check(LAND.assess("attestation_villageoise", {"geometre": True}, [])[0] >= 3 and LAND.assess("attestation_villageoise", {c[0]: True for c in LAND.applicable("attestation_villageoise")}, [])[0] == 2, "attestation villageoise partiellement vérifiée : reste très élevé")
check(LAND.assess("acte_seul", full, [])[0] == 4, "acte de vente seul : critique quoi qu'on vérifie")
check(LAND.assess("titre_foncier", full, ["x"])[0] == 1, "une alerte relève le risque")
poly = LAND.parse_bornes("5.35200, -3.88935\n5.35200, -3.88905\n5.35225; -3.88905\n5.35225, -3.88935")
check(len(poly) == 4 and LAND.inside(5.3521, -3.8892, poly) and not LAND.inside(5.3530, -3.8892, poly), "chantier dans ou hors des bornes")
check(900 <= LAND.area_m2(poly) <= 960, "surface calculée depuis les bornes (≈ 925 m²)")
check(LAND.same_name("Koné Ibrahim", "IBRAHIM KONE") and not LAND.same_name("Koné Ibrahim", "Traoré Awa"), "comparaison des noms sans accents ni ordre")
check(COUNT.compare(100, 100, 99, 0.9) == "ok" and COUNT.compare(100, 100, 82, 0.9) == "a_verifier"
      and COUNT.compare(100, 90, None, None) == "ecart" and COUNT.compare(100, 100, 50, 0.3) == "ok", "trois chiffres comparés, confiance prise en compte")

print("Comptes et chantier")
own = register("a@x.ci"); chef = register("k@x.ci", "chef", phone="0700000000")
sup = register("q@x.ci", "fournisseur", phone="0102030405", zone="Bingerville")
archi = register("arc@x.ci", "pro", profession="architecte"); compta = register("cpt@x.ci", "pro", profession="comptable")
adm = register("admin@x.ci")
A.app.test_cli_runner().invoke(args=["creer-admin", "admin@x.ci"])
verif = register("verif@x.ci")
A.app.test_cli_runner().invoke(args=["creer-admin", "verif@x.ci", "--role", "verification"])
data = dict(name="Villa", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="suivi",
            start_date=datetime.now().date().isoformat())
for i, (n, a, d) in enumerate([("Fondations", 3000000, 20), ("Murs", 4000000, 30)]):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
pid = int(post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])
post(chef, "/rejoindre", dict(code=one("SELECT invite_code FROM projects WHERE id=?", pid)[0]))
for email, role in (("arc@x.ci", "architecte"), ("cpt@x.ci", "comptable")):
    post(own, f"/chantiers/{pid}/membres", dict(email=email, role=role), f"/chantiers/{pid}?onglet=dossier")

print("Accompagnement foncier")
url = f"/chantiers/{pid}/foncier"
check("Terrain : vérifier avant de construire" in html(own.get(f"/chantiers/{pid}?onglet=dossier")), "lien depuis le dossier du chantier")
check(chef.get(url).status_code == 403 and archi.get(url).status_code == 403, "page réservée au propriétaire")
post(own, url, dict(action="save", doc_type="attestation_villageoise", holder_name="Famille Yao", seller_name="Traoré Awa",
                    area_declared="600"), url)
h = html(own.get(url))
check("Critique" in h and "Ne versez plus d'argent" in h and "ne correspond pas au titulaire" in h, "attestation villageoise et vendeur différent : critique")
post(own, url, dict(action="save", doc_type="acd", title_ref="ACD 12345", holder_name="Traoré Awa", seller_name="AWA TRAORE",
                    area_declared="600", bornes="5.35200, -3.88935\n5.35200, -3.88905\n5.35225, -3.88905\n5.35225, -3.88935"), url)
h = html(own.get(url))
check("Arrêté de concession définitive" in h and "le chantier est à l'intérieur des bornes" in h, "ACD enregistré, chantier dans les bornes")
check("très différente de la surface du document" in h, "surface mesurée (≈ 925 m²) très différente des 600 m² déclarés")
check(one("SELECT land_ref FROM projects WHERE id=?", pid)[0] == "ACD 12345", "référence reportée sur la fiche du projet")
for cid in ("vendeur", "authenticite", "geometre", "notaire", "mutation", "voisinage", "urbanisme"):
    post(own, url, dict(action="check", check=cid, done="1"), url)
post(own, url, dict(action="upload", kind="titre", file=(io.BytesIO(b"%PDF ACD"), "acd.pdf")), url, files=True)
h = html(own.get(url))
check("Modéré" in h or "Faible" in h, "vérifications faites : risque abaissé (reste l'alerte de surface)")
post(own, url, dict(action="save", doc_type="acd", title_ref="ACD 12345", holder_name="Traoré Awa", seller_name="Awa Traoré",
                    area_declared="925", bornes="5.35200, -3.88935\n5.35200, -3.88905\n5.35225, -3.88905\n5.35225, -3.88935"), url)
check("Faible" in html(own.get(url)), "surface cohérente et tout vérifié : risque faible")
check("Fourni" in html(own.get(f"/chantiers/{pid}/financement/dossier")) and
      any(i["id"] == "titre" and i["ok"] for i in __import__("services.finance", fromlist=["x"]).checklist("fr", {"titre": [1]}, {}, False)),
      "le document du terrain sert au dossier de crédit")
doc = one("SELECT id FROM fin_documents WHERE kind='titre'")[0]
check(chef.get(f"/financement/pieces/{doc}").status_code == 403, "pièce du terrain privée")
post(own, url, dict(action="request", message="Le vendeur est un héritier"), url)
check(notes("admin@x.ci", "Vérification foncière demandée") == 1 and notes("verif@x.ci", "Vérification foncière demandée") == 1,
      "demande envoyée à l'équipe de vérification")
check("Une demande est déjà en cours" in html(post(own, url, dict(action="request"), url)), "pas de seconde demande en parallèle")
rid = one("SELECT id FROM land_requests")[0]
h = html(adm.get("/admin"))
check("Vérifications foncières demandées" in h and "Le vendeur est un héritier" in h, "demande visible dans l'administration")
post(adm, "/admin/action", dict(action="land_request", id=str(rid), status="faite", result="Notaire partenaire : titre vérifié, aucune opposition."), "/admin")
check(one("SELECT status FROM land_requests WHERE id=?", rid)[0] == "faite" and notes("a@x.ci", "Vérification foncière") >= 1
      and "aucune opposition" in html(own.get(url)), "réponse transmise au propriétaire")

print("Comptage des livraisons")
post(sup, "/fournisseur/catalogue", dict(action="add", name="Ciment CPJ 42,5", unit="sac", price="5500"), "/fournisseur/catalogue")
post(sup, "/fournisseur/catalogue", dict(action="add", name="Sable lagunaire", unit="voyage", price="90000"), "/fournisseur/catalogue")
sup_id = one("SELECT id FROM users WHERE email='q@x.ci'")[0]
s.execute("UPDATE users SET verified=1 WHERE id=?", (sup_id,)); s.commit()
cim, sab = (r[0] for r in s.execute("SELECT id FROM products ORDER BY id"))
step1 = one("SELECT id FROM steps WHERE project_id=? ORDER BY position", pid)[0]
post(chef, f"/chantiers/{pid}/commandes/nouvelle", {"fournisseur": sup_id, "step_id": step1, f"qty_{cim}": "100", f"qty_{sab}": "2"},
     f"/chantiers/{pid}/commandes/nouvelle?fournisseur={sup_id}")
oid = one("SELECT id FROM orders ORDER BY id DESC")[0]
post(own, f"/commandes/{oid}", dict(action="approve"), f"/commandes/{oid}")
post(sup, f"/commandes/{oid}", dict(action="accept", delivery_date=datetime.now().date().isoformat()), f"/commandes/{oid}")
calls = []


def fake_count(images, items, context, lang="fr"):
    calls.append([x["nom"] for x in items])
    return {items[0]["id"]: {"compte": 82, "confiance": 0.85, "methode": "8 rangées de 10 sacs, plus 2", "remarque": ""}}, "Photo nette"


COUNT.count = fake_count
os.environ["ANTHROPIC_API_KEY"] = "test"
h = capture(sup, f"/commandes/{oid}/livraison", f"/commandes/{oid}", jpg(1))
check("Photo de livraison vérifiée" in h, "photo de livraison du fournisseur")
os.environ.pop("ANTHROPIC_API_KEY")
lines = {r["name"]: r for r in s.execute("SELECT * FROM order_lines WHERE order_id=?", (oid,))}
c = one("SELECT * FROM delivery_counts WHERE order_id=? AND line_id=?", oid, lines["Ciment CPJ 42,5"]["id"])
check(calls and calls[0] == ["Ciment CPJ 42,5"] and c["ai_count"] == 82, "ciment compté sur la photo (82) ; le sable au volume n'est pas compté")
h = html(chef.get(f"/commandes/{oid}"))
check("Comptage de la livraison" in h and "compté sur la photo : 82" in h and "Photo de comptage" in h and "rangées régulières" in h,
      "le chef voit le comptage, le guide et la photo de comptage")
h = html(post(chef, f"/commandes/{oid}", {"action": "receive", f"qty_{lines['Ciment CPJ 42,5']['id']}": "100",
                                          f"qty_{lines['Sable lagunaire']['id']}": "2"}, f"/commandes/{oid}"))
o = one("SELECT * FROM orders WHERE id=?", oid)
check(o["status"] == "litige" and "100 déclarés, 82 comptés" in o["problem"] and o["received_total"] is None,
      "chef déclare 100 sacs, photo 82 : paiement suspendu")
check(notes("a@x.ci", "Écart de comptage") == 1, "propriétaire prévenu")
check("Je confirme ces quantités malgré l'écart" in html(own.get(f"/commandes/{oid}")), "le propriétaire peut trancher")
h = html(post(own, f"/commandes/{oid}", {"action": "receive", f"qty_{lines['Ciment CPJ 42,5']['id']}": "82",
                                         f"qty_{lines['Sable lagunaire']['id']}": "2"}, f"/commandes/{oid}"))
o = one("SELECT * FROM orders WHERE id=?", oid)
check(o["status"] != "litige" and o["received_total"] == 82 * 5500 + 2 * 90000, "réception corrigée à 82 sacs : le fournisseur est payé pour 82")
check(one("SELECT SUM(qty) FROM stock_moves WHERE project_id=? AND material='Ciment'", pid)[0] == 82, "stock à 82 sacs")

print("Plan et réalité")
purl = f"/chantiers/{pid}/plan-reel"
check("Plan et réalité" in html(own.get(f"/chantiers/{pid}?onglet=etapes")), "lien depuis l'onglet Étapes")
s.execute("INSERT INTO plan_readings (project_id, user_id, result, created_at) VALUES (?,?,?,?)",
          (pid, 1, json.dumps({"windows": 8, "doors": 6, "rooms": [{"name": "Salon"}, {"name": "Chambre 1"}, {"name": "Chambre 2"}]}), A.now_iso()))
s.commit()
check("3 éléments ajoutés" in html(post(own, purl, dict(action="from_plan"), purl)), "fenêtres, portes et pièces repris de la lecture du plan")
post(archi, purl, dict(action="add", label="Poteaux", expected="12", level="Rez-de-chaussée"), purl)
check(one("SELECT COUNT(*) FROM plan_items WHERE project_id=?", pid)[0] == 4, "l'architecte ajoute les poteaux")
check(post(compta, purl, dict(action="add", label="x", expected="1"), purl, follow=False).status_code == 403
      and post(chef, purl, dict(action="add", label="x", expected="1"), purl, follow=False).status_code == 403, "ni le comptable ni le chef ne modifient la liste")
items = {A.I18N.render(r["label"], "fr"): r["id"] for r in s.execute("SELECT * FROM plan_items")}
post(chef, purl, dict(action="declare", item_id=str(items["Fenêtres"]), count="8"), purl)
check(one("SELECT status FROM plan_items WHERE id=?", items["Fenêtres"])[0] == "ok", "8 fenêtres sur 8 : conforme")
post(chef, purl, dict(action="declare", item_id=str(items["Poteaux"]), count="10", note="2 poteaux pas encore coulés"), purl)
check(one("SELECT status FROM plan_items WHERE id=?", items["Poteaux"])[0] == "ecart" and notes("a@x.ci", "Écart avec le plan") == 1,
      "10 poteaux pour 12 : écart signalé au propriétaire")
COUNT.count = lambda images, items_, context, lang="fr": ({"x": {"compte": 5, "confiance": 0.9, "methode": "comptées sur la façade", "remarque": ""}}, "")
os.environ["ANTHROPIC_API_KEY"] = "test"
h = capture(chef, f"/chantiers/{pid}/plan-reel/photo", purl, jpg(7), item_id=str(items["Portes"]))
os.environ.pop("ANTHROPIC_API_KEY")
check("rattachée à l'élément" in h and one("SELECT ai_count FROM plan_items WHERE id=?", items["Portes"])[0] == 5, "photo des portes comptée par l'IA (5)")
post(chef, purl, dict(action="declare", item_id=str(items["Portes"]), count="6"), purl)
check(one("SELECT status FROM plan_items WHERE id=?", items["Portes"])[0] == "a_verifier", "chef 6, photo 5 : à vérifier")
h = html(own.get(purl))
check("Écart avec le plan" in h and "À vérifier : la photo ne confirme pas" in h and "Conforme au plan" in h, "page plan et réalité")
check(register("z@x.ci").get(purl).status_code == 403, "inaccessible à un étranger")

print("Anglais")
own.get("/?lang=en")
check("Land: check before building" in html(own.get(url)) and "Plan versus reality" in html(own.get(purl)), "pages en anglais")
print(f"\n{ok} contrôles réussis.")
