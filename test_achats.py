"""Test de l'achat direct des materiaux : fournisseur verifie, catalogue, commande proposee par le chef,
approbation et reservation sur le sequestre, livraison prouvee par photo GPS, reception partielle,
paiement du fournisseur moins la commission, facture automatique, refus et annulation, litige.
Lancement : python3 test_achats.py   (PostgreSQL : DATABASE_URL=postgresql://... python3 test_achats.py)
"""
import io, os, re, sys, tempfile
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["COMMISSION_MATERIAUX"] = "3"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_achats_")
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

A.app.config["TESTING"] = True
A.app.config["ESCROW_ENABLED"] = True     # sequestre active comme par le super-admin
SITE = (5.3521, -3.8892)
PW = "Bingerville-2026"
own, chef, sup, sup2, adm = (A.app.test_client() for _ in range(5))
s = A.connect()


def tok(c, url="/"):
    m = re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True))
    assert m, url
    return m.group(1)


def post(c, url, data, page="/", follow=True, files=False):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow, content_type="multipart/form-data" if files else None)


def html(r):
    return r.get_data(as_text=True)


def jpg(seed):
    b = io.BytesIO()
    Image.fromarray(np.random.default_rng(seed).integers(0, 255, (240, 320, 3), dtype=np.uint8)).save(b, "JPEG")
    return b.getvalue()


def one(sql, *a):
    return s.execute(sql, a).fetchone()


def register(c, email, role, **extra):
    extra.setdefault("supplier_terms", "1")
    return post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email,
                                        password=PW, **extra), "/inscription", follow=False)


now_ms = lambda: datetime.now(timezone.utc).timestamp() * 1000

# --- 1. Inscription du fournisseur, catalogue, verification ---
for c, e, r, ex in [(own, "a@x.ci", "proprio", {}), (chef, "k@x.ci", "chef", {"phone": "0700000000"}),
                    (sup, "quinca@x.ci", "fournisseur", {"phone": "0102030405", "zone": "Bingerville",
                                                         "company": "Quincaillerie du Carrefour, RCCM CI-ABJ-2020-B-1"}),
                    (sup2, "depot@x.ci", "fournisseur", {"phone": "0102030406"}), (adm, "admin@x.ci", "proprio", {})]:
    r_ = register(c, e, r, **ex)
    assert r_.status_code == 302, e
assert register(A.app.test_client(), "q2@x.ci", "fournisseur").headers["Location"].endswith("/fournisseur/catalogue")
assert register(A.app.test_client(), "q3@x.ci", "fournisseur", supplier_terms="").status_code == 200   # conditions refusees
assert one("SELECT supplier_terms_at FROM users WHERE email='quinca@x.ci'")[0]
assert one("SELECT COUNT(*) FROM users WHERE email='q3@x.ci'")[0] == 0
assert "Quincaillerie du Carrefour" in one("SELECT bio FROM users WHERE email='quinca@x.ci'")[0]
assert "Commandes en cours" in html(sup.get("/")) and "en attente de vérification" in html(sup.get("/"))
assert own.get("/fournisseur/catalogue").status_code == 403
for name, mat, unit, price in [("Ciment CPJ 42,5 (sac 50 kg)", "", "sac", "5500"), ("Fer à béton HA 10", "", "barre", "4200"),
                               ("Sable lagunaire", "", "voyage", "90000")]:
    post(sup, "/fournisseur/catalogue", dict(action="add", name=name, material=mat, unit=unit, price=price), "/fournisseur/catalogue")
prods = {r["name"]: r for r in s.execute("SELECT * FROM products ORDER BY id")}
assert prods["Ciment CPJ 42,5 (sac 50 kg)"]["material"] == "Ciment", dict(prods["Ciment CPJ 42,5 (sac 50 kg)"])
assert "Indiquez le nom" in html(post(sup, "/fournisseur/catalogue", dict(action="add", name="X", price="0"), "/fournisseur/catalogue"))
cim, fer, sab = (prods[k]["id"] for k in ("Ciment CPJ 42,5 (sac 50 kg)", "Fer à béton HA 10", "Sable lagunaire"))
post(sup, "/fournisseur/catalogue", dict(action="price", product_id=cim, price="5800"), "/fournisseur/catalogue")
assert one("SELECT price FROM products WHERE id=?", cim)[0] == 5800
post(sup2, "/fournisseur/catalogue", dict(action="add", name="Gravier 5/15", unit="voyage", price="120000"), "/fournisseur/catalogue")
assert post(sup2, "/fournisseur/catalogue", dict(action="toggle", product_id=cim), "/fournisseur/catalogue").status_code == 404

A.app.test_cli_runner().invoke(args=["creer-admin", "admin@x.ci"])
sup_id = one("SELECT id FROM users WHERE email='quinca@x.ci'")[0]
sup2_id = one("SELECT id FROM users WHERE email='depot@x.ci'")[0]
assert "Inspecteurs et fournisseurs à vérifier" in html(adm.get("/admin")) and "QUINCA" in html(adm.get("/admin"))
post(adm, "/admin/action", dict(action="verify", id=sup_id), "/admin")
post(adm, "/admin/action", dict(action="verify", id=sup2_id), "/admin")
assert one("SELECT verified FROM users WHERE id=?", sup_id)[0] == 1
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=? AND title LIKE '%Entreprise vérifiée%' AND channel='app'", sup_id)[0] == 1
print("fournisseur : inscription, catalogue, vérification ok")

# --- 2. Chantier avec sequestre et prix de reference ---
data = dict(name="Villa", address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode="sequestre",
            start_date=datetime.now().date().isoformat())
for i, (n, a, d) in enumerate(A.DEFAULT_STEPS):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
pid = int(post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])
code = re.search(r'class="code">(\w+)<', html(own.get(f"/chantiers/{pid}"))).group(1)
post(chef, "/rejoindre", dict(code=code))
step1 = one("SELECT * FROM steps WHERE project_id=? ORDER BY position", pid)
s.execute("INSERT INTO materials_plan (project_id, step_id, material, unit, qty_planned, unit_price_ref) VALUES (?,?,?,?,?,?)",
          (pid, step1["id"], "Ciment", "sac", 200, 4500)); s.commit()

# --- 3. Le chef propose ; avertissement de prix ; le proprietaire approuve sans fonds puis avec ---
h = html(chef.get(f"/chantiers/{pid}?onglet=factures"))
assert "Achat direct des matériaux" in h and "Proposer une commande" in h
h = html(chef.get(f"/chantiers/{pid}/commandes/nouvelle"))
assert "QUINCA" in h and "DEPOT" in h
h = html(chef.get(f"/chantiers/{pid}/commandes/nouvelle?fournisseur={sup_id}"))
assert "Plus cher que votre prix de référence" in h                       # 5800 > 4500 x 1,2
page = f"/chantiers/{pid}/commandes/nouvelle?fournisseur={sup_id}"
assert "au moins une quantité" in html(post(chef, f"/chantiers/{pid}/commandes/nouvelle", dict(fournisseur=sup_id, step_id=step1["id"]), page))
r = post(chef, f"/chantiers/{pid}/commandes/nouvelle", {"fournisseur": sup_id, "step_id": step1["id"], f"qty_{cim}": "100",
                                                         f"qty_{fer}": "50", "note": "Livrer le matin"}, page)
assert "Commande proposée au propriétaire" in html(r)
o = one("SELECT * FROM orders ORDER BY id DESC")
oid = o["id"]
assert o["status"] == "proposee" and o["total"] == 100 * 5800 + 50 * 4200 == 790000
assert sup.get(f"/commandes/{oid}").status_code == 200                    # le fournisseur voit, mais ne peut rien faire
assert "Action impossible" in html(post(sup, f"/commandes/{oid}", dict(action="accept"), f"/commandes/{oid}"))
assert sup2.get(f"/commandes/{oid}").status_code == 403
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=(SELECT owner_id FROM projects WHERE id=?) AND title LIKE '%à approuver%' AND channel='app'", pid)[0] == 1
assert "Solde du séquestre insuffisant" in html(post(own, f"/commandes/{oid}", dict(action="approve"), f"/commandes/{oid}"))
post(own, f"/chantiers/{pid}/paiements/depot", dict(amount="3000000"), f"/chantiers/{pid}?onglet=etapes")
assert A.escrow(pid, s)["balance"] == 3000000
assert "Commande envoyée au fournisseur" in html(post(own, f"/commandes/{oid}", dict(action="approve"), f"/commandes/{oid}"))
assert one("SELECT status FROM orders WHERE id=?", oid)[0] == "envoyee"
assert A.escrow(pid, s)["balance"] == 3000000 - 790000                    # argent reserve
print("commande proposée, approuvée, argent réservé ok")

# --- 4. Le fournisseur accepte ; photo de livraison obligatoirement avec la camera, au bon endroit ---
assert "Nouvelle commande" in html(sup.get("/notifications"))
post(sup, f"/commandes/{oid}", dict(action="accept", delivery_date=datetime.now().date().isoformat()), f"/commandes/{oid}")
assert one("SELECT status FROM orders WHERE id=?", oid)[0] == "acceptee"
h = html(sup.get(f"/commandes/{oid}"))
assert "Photo de livraison" in h and "Itinéraire" in h
tk = re.search(r'name="capture_token" value="([^"]+)"', h).group(1)


def deliver(img, **f):
    d = dict(tz_offset="0", lat=str(SITE[0]), lng=str(SITE[1]), photo=(io.BytesIO(img), "capture.jpg"))
    d.update(f)
    return html(post(sup, f"/commandes/{oid}/livraison", d, f"/commandes/{oid}", files=True))


h = deliver(jpg(1), last_modified=str(now_ms()), client_now=str(now_ms()))     # import depuis la galerie
assert "caméra de l&#39;application" in h, h[:3000]
h = deliver(jpg(2), capture="app", capture_token=tk, captured_at=str(now_ms()), client_now=str(now_ms()),
            lat="5.40", lng="-3.80")                                         # a 10 km : refusee
assert "Photo refusée" in h and one("SELECT status FROM orders WHERE id=?", oid)[0] == "acceptee"
h = deliver(jpg(3), capture="app", capture_token=tk, captured_at=str(now_ms()), client_now=str(now_ms()))
assert "Photo de livraison vérifiée" in h, h[:3000]
o = one("SELECT * FROM orders WHERE id=?", oid)
assert o["status"] == "livree" and o["delivered_at"]
pr = one("SELECT * FROM proofs WHERE order_id=? AND ok=1", oid)
assert pr["source"] == "fournisseur"
assert sup.get(f"/photos/{pr['id']}").status_code == 200 and sup2.get(f"/photos/{pr['id']}").status_code == 403
assert "Livraison du fournisseur" in html(own.get(f"/commandes/{oid}"))
print("livraison prouvée par photo GPS ok (galerie et mauvais lieu refusés)")

# --- 5. Reception partielle : paiement de ce qui est recu, moins la commission ; le reste est libere ---
lines = {r["product_id"]: r for r in s.execute("SELECT * FROM order_lines WHERE order_id=?", (oid,))}
h = html(post(chef, f"/commandes/{oid}", {"action": "receive", f"qty_{lines[cim]['id']}": "90", f"qty_{lines[fer]['id']}": "50"},
              f"/commandes/{oid}"))
assert "Réception enregistrée" in h and "Le fournisseur est payé" in h, h[:2000]
o = one("SELECT * FROM orders WHERE id=?", oid)
received = 90 * 5800 + 50 * 4200
assert o["status"] == "receptionnee" and o["received_total"] == received and o["commission"] == round(received * 0.03)
tx = one("SELECT * FROM transactions WHERE order_id=?", oid)
assert tx["status"] == "reussi" and tx["amount"] == received
assert A.escrow(pid, s)["balance"] == 3000000 - received                   # les 10 sacs manquants restent au sequestre
inv = one("SELECT * FROM invoices WHERE media_type='commande'")
assert inv["status"] == "validee" and inv["total"] == received and inv["supplier"] == "QUINCA"
assert one("SELECT qty FROM invoice_lines WHERE invoice_id=? AND material='Ciment'", inv["id"])[0] == 90
assert own.get(f"/chantiers/{pid}/factures/{inv['id']}").headers["Location"].endswith(f"/commandes/{oid}")
h = html(own.get(f"/chantiers/{pid}?onglet=dossier"))
assert "Contrôle des matériaux" in h and o["ref"] in h and "Reçue et payée" in h
assert one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Livraison incomplète%' AND channel='app'")[0] >= 1
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=? AND title LIKE '%Paiement envoyé%' AND channel='app'", sup_id)[0] == 1
h = html(sup.get(f"/commandes/{oid}"))
assert "Commission ChantierVrai" in h and "Commission ChantierVrai" not in html(own.get(f"/commandes/{oid}"))
h = html(adm.get("/admin"))
assert "Achat direct des matériaux" in h
print("réception partielle, paiement du fournisseur moins 3 %, facture automatique ok")

# --- 6. Le proprietaire commande directement ; le fournisseur refuse ; l'argent est libere ---
page = f"/chantiers/{pid}/commandes/nouvelle?fournisseur={sup2_id}"
gr = one("SELECT id FROM products WHERE supplier_id=?", sup2_id)[0]
post(own, f"/chantiers/{pid}/commandes/nouvelle", {"fournisseur": sup2_id, "step_id": step1["id"], f"qty_{gr}": "2"}, page)
o2 = one("SELECT * FROM orders ORDER BY id DESC")
assert o2["status"] == "envoyee" and A.escrow(pid, s)["balance"] == 3000000 - received - 240000
post(sup2, f"/commandes/{o2['id']}", dict(action="refuse", motif="Rupture de stock"), f"/commandes/{o2['id']}")
assert one("SELECT status FROM orders WHERE id=?", o2["id"])[0] == "refusee"
assert A.escrow(pid, s)["balance"] == 3000000 - received
assert "Rupture de stock" in html(own.get(f"/commandes/{o2['id']}"))
print("commande directe et refus du fournisseur ok (argent libéré)")

# --- 7. Probleme signale : paiement suspendu, admin alerte ; annulation ---
post(own, f"/chantiers/{pid}/commandes/nouvelle", {"fournisseur": sup_id, "step_id": step1["id"], f"qty_{sab}": "1"},
     f"/chantiers/{pid}/commandes/nouvelle?fournisseur={sup_id}")
o3 = one("SELECT * FROM orders ORDER BY id DESC")["id"]
post(sup, f"/commandes/{o3}", dict(action="accept", delivery_date="2026-12-01"), f"/commandes/{o3}")
assert "10 caractères" in html(post(chef, f"/commandes/{o3}", dict(action="problem", text="court"), f"/commandes/{o3}"))
post(chef, f"/commandes/{o3}", dict(action="problem", text="Sable plein de terre, refusé au déchargement"), f"/commandes/{o3}")
assert one("SELECT status FROM orders WHERE id=?", o3)[0] == "litige"
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=(SELECT id FROM users WHERE email='admin@x.ci') AND title LIKE '%Problème sur une livraison%' AND channel='app'")[0] == 1
assert "Sable plein de terre" in html(adm.get(f"/commandes/{o3}"))
assert "Action impossible" in html(post(chef, f"/commandes/{o3}", dict(action="cancel"), f"/commandes/{o3}"))
post(own, f"/commandes/{o3}", dict(action="cancel"), f"/commandes/{o3}")
assert one("SELECT status FROM orders WHERE id=?", o3)[0] == "annulee"
assert A.escrow(pid, s)["balance"] == 3000000 - received
print("problème signalé, médiation, annulation ok")

# --- 8. Paiement manuel quand le chantier n'a pas de sequestre ; echec de versement ---
s.execute("UPDATE projects SET pay_mode='manuel' WHERE id=?", (pid,)); s.commit()
post(own, f"/chantiers/{pid}/commandes/nouvelle", {"fournisseur": sup_id, "step_id": step1["id"], f"qty_{cim}": "10"},
     f"/chantiers/{pid}/commandes/nouvelle?fournisseur={sup_id}")
o4 = one("SELECT * FROM orders ORDER BY id DESC")
assert o4["pay_mode"] == "manuel" and o4["status"] == "envoyee"
s.execute("UPDATE orders SET status='livree' WHERE id=?", (o4["id"],)); s.commit()
post(chef, f"/commandes/{o4['id']}", dict(action="receive"), f"/commandes/{o4['id']}")
assert one("SELECT status FROM orders WHERE id=?", o4["id"])[0] == "a_payer"
post(own, f"/commandes/{o4['id']}", dict(action="paid", pay_ref="OM-123"), f"/commandes/{o4['id']}")
assert tuple(one("SELECT status, pay_ref FROM orders WHERE id=?", o4["id"])) == ("receptionnee", "OM-123")
s.execute("UPDATE projects SET pay_mode='sequestre' WHERE id=?", (pid,))
s.execute("UPDATE users SET phone=NULL WHERE id=?", (sup_id,)); s.commit()   # le versement echoue sans numero
post(own, f"/chantiers/{pid}/commandes/nouvelle", {"fournisseur": sup_id, "step_id": step1["id"], f"qty_{cim}": "10"},
     f"/chantiers/{pid}/commandes/nouvelle?fournisseur={sup_id}")
o5 = one("SELECT * FROM orders ORDER BY id DESC")["id"]
s.execute("UPDATE orders SET status='livree' WHERE id=?", (o5,)); s.commit()
post(chef, f"/commandes/{o5}", dict(action="receive"), f"/commandes/{o5}")
assert one("SELECT status FROM orders WHERE id=?", o5)[0] == "a_payer"
assert one("SELECT status FROM transactions WHERE order_id=?", o5)[0] == "echoue"
print("paiement manuel et échec de versement ok")

# --- 9. API de l'application mobile : le fournisseur livre, le chef receptionne ---
s.execute("UPDATE users SET phone='0102030405' WHERE id=?", (sup_id,)); s.commit()


def api(c, method, url, token, **kw):
    return getattr(c, method)(url, headers={"Authorization": f"Bearer {token}"}, **kw)


cli = A.app.test_client()
t_sup = cli.post("/api/v1/connexion", json=dict(email="quinca@x.ci", password=PW)).json["token"]
t_chef = cli.post("/api/v1/connexion", json=dict(email="k@x.ci", password=PW)).json["token"]
post(own, f"/chantiers/{pid}/commandes/nouvelle", {"fournisseur": sup_id, "step_id": step1["id"], f"qty_{fer}": "20"},
     f"/chantiers/{pid}/commandes/nouvelle?fournisseur={sup_id}")
o6 = one("SELECT * FROM orders ORDER BY id DESC")["id"]
assert api(cli, "get", "/api/v1/commandes", t_chef).status_code == 403
r = api(cli, "post", f"/api/v1/commandes/{o6}/accepter", t_sup, json=dict(delivery_date="2026-12-02"))
assert r.status_code == 200 and r.json["ok"], r.json
lst = api(cli, "get", "/api/v1/commandes", t_sup).json["orders"]
mine = next(x for x in lst if x["id"] == o6)
assert mine["status"] == "acceptee" and mine["capture_token"] and mine["site"]["radius"] == 100 and mine["lines"][0]["qty"] == 20
r = api(cli, "post", f"/api/v1/commandes/{o6}/livraison", t_sup, content_type="multipart/form-data",
        data=dict(capture="app", capture_token=mine["capture_token"], captured_at=str(now_ms()), client_now=str(now_ms()),
                  tz_offset="0", lat=str(SITE[0]), lng=str(SITE[1]), photo=(io.BytesIO(jpg(9)), "c.jpg")))
assert r.status_code == 200 and r.json["ok"], r.json
d = api(cli, "get", f"/api/v1/chantiers/{pid}", t_chef).json["project"]
od = next(x for x in d["orders"] if x["id"] == o6)
assert od["status"] == "livree"
r = api(cli, "post", f"/api/v1/commandes/{o6}/receptionner", t_chef, json={f"qty_{od['lines'][0]['id']}": 20})
assert r.json["ok"] and one("SELECT status FROM orders WHERE id=?", o6)[0] == "receptionnee"
assert api(cli, "post", f"/api/v1/commandes/{o6}/accepter", t_sup).status_code == 400
print("API mobile ok (acceptation, photo de livraison, réception)")

# --- 10. Anglais ---
sup.get("/?lang=en")
h = html(sup.get("/"))
assert "Open orders" in h, h[:2000]
assert "Received and paid" in html(sup.get(f"/commandes/{oid}"))
print("anglais ok")
print("\nTOUS LES TESTS DE L'ACHAT DIRECT PASSENT")
