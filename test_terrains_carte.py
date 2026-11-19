"""Test de la cartographie des terrains : vérifier un terrain avant d'acheter (ACD, bornes, double vente).
Lancement : python3 test_terrains_carte.py
"""
import io, json, os, re, sys, tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_terrains_")

import app as A
from services import land as LAND

A.app.config["TESTING"] = True
PW = "Bingerville-2026"
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


def post(c, url, data, page=None, follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page or url)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)


def html(r):
    return r.get_data(as_text=True)


def register(c, email, role, name, **extra):
    r = post(c, "/inscription", dict(terms="1", role=role, name=name, email=email, password=PW, **extra), "/inscription", follow=False)
    assert r.status_code == 302, email


s = A.connect()
buyer, seller, other, chef = (A.app.test_client() for _ in range(4))
register(buyer, "acheteur@x.ci", "proprio", "Mariam Acheteuse")
register(seller, "premier@x.ci", "proprio", "Yao Premier")
register(other, "pro@x.ci", "pro", "Bureau Pro", profession="architecte", company="Cabinet Pro")
register(chef, "chef@x.ci", "chef", "Koffi Chef", phone="0700000000")
uid = {e: s.execute("SELECT id FROM users WHERE email = ?", (e,)).fetchone()[0] for e in ("acheteur@x.ci", "premier@x.ci", "pro@x.ci")}

print("Calculs")
lat, lng = LAND.utm_to_latlng(387610, 588080, 30)
check(abs(lat - 5.31956) < 1e-4 and abs(lng + 4.01431) < 1e-4, "UTM 30N → latitude, longitude")
pts, bad = LAND.parse_points("B1 387610 588080\nB2 387640 588080\nB3 387640 588110\nB4 387610 588110\nn'importe quoi", 30)
check(len(pts) == 4 and bad == 1, "bornes UTM lues, ligne illisible comptée")
check(abs(LAND.area_m2(pts) - 900) < 20, "surface d'un carré de 30 m ≈ 900 m²")
pts2, _b = LAND.parse_points("387620 588080\n387650 588080\n387650 588110\n387620 588110", 30)
check(500 < LAND.overlap_m2(pts, pts2) < 700, "chevauchement de deux carrés décalés de 10 m ≈ 600 m²")
far, _b = LAND.parse_points("387910 588080\n387940 588080\n387940 588110\n387910 588110", 30)
check(LAND.overlap_m2(pts, far) == 0, "terrains éloignés : aucun chevauchement")
check(LAND.norm_ref("ACD n° 2019-0457") == LAND.norm_ref("acd 2019 0457") == LAND.norm_ref("ACD N°2019/0457") == "20190457",
      "numéros d'ACD écrits différemment reconnus")
check(LAND.parse_points("48.85, 2.35", 30)[0] == [], "coordonnées hors de Côte d'Ivoire refusées")

print("Accès")
check(chef.get("/terrains").status_code == 404, "chef de chantier : pas de page Terrains")
check(buyer.get("/terrains").status_code == 200, "propriétaire : page Terrains")
check(other.get("/terrains").status_code == 200, "bureau pro : page Terrains")
check("Terrains" in html(buyer.get("/")), "entrée Terrains dans le menu")

print("Premier propriétaire : son terrain")
r = post(seller, "/terrains", {"name": "Mon lot Bingerville", "commune": "Bingerville"}, follow=False)
p1 = int(r.headers["Location"].split("/terrains/")[1].split("#")[0])
url1 = f"/terrains/{p1}"
post(seller, url1, {"action": "save", "name": "Mon lot Bingerville", "commune": "Bingerville", "doc_type": "acd",
                    "title_ref": "ACD n° 2019-0457", "holder_name": "Yao Premier", "seller_name": "", "area_declared": "900"})
post(seller, url1, {"action": "bornes", "bornes": "B1 387610 588080\nB2 387640 588080\nB3 387640 588110\nB4 387610 588110", "zone": "30"})
pl = s.execute("SELECT * FROM plots WHERE id = ?", (p1,)).fetchone()
check(pl["ref_norm"] == "20190457" and abs(pl["area_m2"] - 900) < 20, "numéro et bornes UTM enregistrés")
check(not s.execute("SELECT 1 FROM plot_alerts").fetchone(), "aucune alerte quand le terrain est seul")

print("Acheteur : le même terrain lui est proposé")
check(buyer.get(url1).status_code == 404, "le terrain d'un autre est introuvable (404)")
r = post(buyer, "/terrains", {"name": "Lot proposé par M. Kouassi", "commune": "Bingerville"}, follow=False)
p2 = int(r.headers["Location"].split("/terrains/")[1].split("#")[0])
url2 = f"/terrains/{p2}"
poly = [[a, b] for a, b in pts2]
post(buyer, url2, {"action": "bornes", "poly": json.dumps(poly)})
page = html(buyer.get(url2))
check("Alerte : terrain peut-être vendu deux fois" in page, "chevauchement détecté depuis la carte")
check("Yao" not in page and "premier@x.ci" not in page and "Mon lot Bingerville" not in page,
      "l'acheteur ne voit ni le nom, ni l'email, ni le terrain de l'autre")
n_seller = s.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND channel = 'app' AND title LIKE '%deux fois%'",
                     (uid["premier@x.ci"],)).fetchone()[0]
n_buyer = s.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND channel = 'app' AND title LIKE '%deux fois%'",
                    (uid["acheteur@x.ci"],)).fetchone()[0]
check(n_seller == 1 and n_buyer == 1, "les deux propriétaires sont prévenus")
body = s.execute("SELECT body FROM notifications WHERE user_id = ? AND channel = 'app' ORDER BY id DESC",
                 (uid["premier@x.ci"],)).fetchone()[0]
check("Mariam" not in body and "acheteur" not in body, "la notification ne dit pas qui a déclaré le terrain")
post(buyer, url2, {"action": "bornes", "poly": json.dumps(poly)})
n_seller2 = s.execute("SELECT COUNT(*) FROM notifications WHERE user_id = ? AND channel = 'app' AND title LIKE '%deux fois%'",
                      (uid["premier@x.ci"],)).fetchone()[0]
check(n_seller2 == 1, "pas de nouvelle alerte quand on réenregistre")
check("Alerte double vente" in html(seller.get("/terrains")), "le premier propriétaire voit l'alerte dans sa liste")

print("Même numéro d'ACD, sans bornes")
r = post(other, "/terrains", {"name": "Dossier client", "commune": "Cocody"}, follow=False)
p3 = int(r.headers["Location"].split("/terrains/")[1].split("#")[0])
post(other, f"/terrains/{p3}", {"action": "save", "name": "Dossier client", "doc_type": "acd", "title_ref": "ACD N°2019/0457"})
page = html(other.get(f"/terrains/{p3}"))
check("Même numéro de titre" in page, "même ACD écrit autrement : alerte")
check(s.execute("SELECT COUNT(*) FROM plot_alerts WHERE reason = 'same_ref'").fetchone()[0] >= 1, "alerte mémorisée une fois")

print("Preuves officielles et niveau")
post(buyer, url2, {"action": "save", "name": "Lot proposé", "doc_type": "acd", "title_ref": "ACD 2021-0999",
                   "holder_name": "Kouassi Jean", "seller_name": "Kouassi Jean", "area_declared": "900"})
r = post(buyer, url2, {"action": "official", "kind": "etat_foncier", "date": "2099-01-01", "result": "libre"})
check("Date invalide" in html(r), "date future refusée")
post(buyer, url2, {"action": "official", "kind": "etat_foncier", "date": A.datetime.now(A.timezone.utc).date().isoformat(),
                   "owner": "Koné Awa", "result": "libre"})
page = html(buyer.get(url2))
check("un autre propriétaire que le vendeur" in page, "état foncier au nom d'un autre : signalé")
for kind in ("titre", "piece_vendeur", "etat_foncier"):
    post(buyer, url2, {"action": "upload", "kind": kind, "file": (io.BytesIO(b"%PDF-1.4 test"), f"{kind}.pdf")}, files=True)
with A.app.test_request_context():
    A.g.lang = "fr"
    pl2 = s.execute("SELECT * FROM plots WHERE id = ?", (p2,)).fetchone()
    ev = A.plot_assessment(A.connect(), pl2, "fr")
check(ev["vlevel"] == 2, "conflit en cours : jamais « confirmé », même avec pièces")
doc = s.execute("SELECT id FROM plot_documents WHERE plot_id = ? LIMIT 1", (p2,)).fetchone()[0]
check(buyer.get(f"/terrains/{p2}/pieces/{doc}").status_code == 200, "pièce consultable par son propriétaire")
check(seller.get(f"/terrains/{p2}/pieces/{doc}").status_code == 404, "pièce introuvable pour un autre")

print("Terrain sans conflit confirmé")
r = post(buyer, "/terrains", {"name": "Terrain Assinie", "commune": "Assinie"}, follow=False)
p4 = int(r.headers["Location"].split("/terrains/")[1].split("#")[0])
u4 = f"/terrains/{p4}"
post(buyer, u4, {"action": "save", "name": "Terrain Assinie", "doc_type": "acd", "title_ref": "ACD 2022-1111",
                 "holder_name": "Diallo Sali", "seller_name": "Diallo Sali", "area_declared": "500"})
post(buyer, u4, {"action": "bornes", "bornes": "5.1330, -3.2830\n5.1330, -3.2828\n5.1332, -3.2828\n5.1332, -3.2830"})
for kind in ("titre", "piece_vendeur", "etat_foncier"):
    post(buyer, u4, {"action": "upload", "kind": kind, "file": (io.BytesIO(b"%PDF-1.4 x"), f"{kind}.pdf")}, files=True)
post(buyer, u4, {"action": "official", "kind": "etat_foncier", "date": A.datetime.now(A.timezone.utc).date().isoformat(),
                 "owner": "Diallo Sali", "result": "libre"})
page = html(buyer.get(u4))
check('class="done now"' in page and "Confirmé par l" in page, "état foncier récent et libre : niveau 3")
check("ChantierVrai ne certifie aucun titre" in page, "rappel : pas de certification")

print("Rattachement à un chantier")
data = dict(name="Villa Assinie", address="Assinie", lat="5.1331", lng="-3.2829", radius="100", pay_mode="manuel",
            start_date=A.datetime.now().date().isoformat())
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
post(buyer, "/chantiers/nouveau", data)
pid = s.execute("SELECT id FROM projects WHERE name = 'Villa Assinie'").fetchone()[0]
r = post(buyer, u4, {"action": "link", "project_id": str(pid)})
lf = s.execute("SELECT * FROM land_files WHERE project_id = ?", (pid,)).fetchone()
check(lf and lf["title_ref"] == "ACD 2022-1111" and lf["bornes"].count("\n") == 3, "document et bornes repris dans le chantier")
check(s.execute("SELECT COUNT(*) FROM fin_documents WHERE project_id = ?", (pid,)).fetchone()[0] == 3, "pièces reprises")
check(r.status_code == 200 and "Terrain" in html(r), "page Terrain du chantier affichée")
check("vendu deux fois" not in html(buyer.get(f"/chantiers/{pid}/foncier")), "le terrain rattaché ne s'alerte pas lui-même")

print("Chantier existant d'un autre propriétaire")
post(seller, "/chantiers/nouveau", dict(data, name="Chantier Yao"))
pid2 = s.execute("SELECT id FROM projects WHERE name = 'Chantier Yao'").fetchone()[0]
post(seller, f"/chantiers/{pid2}/foncier", {"action": "save", "doc_type": "acd", "title_ref": "ACD 2022/1111"})
page = html(seller.get(f"/chantiers/{pid2}/foncier"))
check("Le même numéro de titre a déjà été déclaré" in page, "page Terrain d'un chantier : même ACD signalé")
check("Mariam" not in page and "Villa Assinie" not in page, "sans révéler l'autre propriétaire")


print("Création de chantier à partir d'un terrain vérifié")
r = post(buyer, "/terrains", {"name": "Lot 7 Cocody", "commune": "Cocody"}, follow=False)
p5 = int(r.headers["Location"].split("/terrains/")[1].split("#")[0])
post(buyer, f"/terrains/{p5}", {"action": "save", "name": "Lot 7 Cocody", "doc_type": "acd", "title_ref": "ACD 2023-7777"})
post(buyer, f"/terrains/{p5}", {"action": "bornes", "bornes": "5.3600, -3.9870\n5.3600, -3.9868\n5.3602, -3.9868\n5.3602, -3.9870"})
page = html(buyer.get(f"/chantiers/nouveau?terrain={p5}"))
check("un terrain que vous avez vérifié" in page and "Lot 7 Cocody" in page, "le terrain vérifié est proposé à la création")
data = dict(name="Villa Cocody", address="Cocody", lat="5.3601", lng="-3.9869", radius="100", pay_mode="suivi", plot_id=str(p5),
            building_type="immeuble", levels="2", surface_floor="240", start_date=A.datetime.now().date().isoformat())
plan = A.step_plan(2)
for i, (n, w, d) in enumerate(plan):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, f"{int(30000000 * w):,}".replace(",", " "), str(d)
post(buyer, "/chantiers/nouveau", data)
pr = s.execute("SELECT * FROM projects WHERE name = 'Villa Cocody'").fetchone()
check(pr["building_type"] == "immeuble" and pr["levels"] == 2 and pr["surface_floor"] == 240, "type, niveaux et surface enregistrés")
check(s.execute("SELECT COUNT(*) FROM steps WHERE project_id = ?", (pr["id"],)).fetchone()[0] == len(plan) == 9, "R+2 : 9 étapes proposées")
check(abs(sum(w for _n, w, _d in plan) - 1) < 0.001, "les parts des étapes font 100 %")
check(s.execute("SELECT SUM(amount) FROM steps WHERE project_id = ?", (pr["id"],)).fetchone()[0] > 29000000, "montants avec espaces lus")
check(s.execute("SELECT project_id FROM plots WHERE id = ?", (p5,)).fetchone()[0] == pr["id"], "terrain rattaché au nouveau chantier")
check(pr["parcel"] and s.execute("SELECT title_ref FROM land_files WHERE project_id = ?", (pr["id"],)).fetchone()[0] == "ACD 2023-7777",
      "bornes et ACD repris")
print("Archivage")
post(buyer, u4, {"action": "archive"})
check("Terrain Assinie" not in html(buyer.get("/terrains")), "terrain retiré de la liste")

print("Notifications")
r = seller.get("/notifications")
check(r.status_code == 200 and "vendu deux fois" in html(r), "l'alerte s'affiche dans les notifications")
print(f"\n{ok} vérifications OK")
