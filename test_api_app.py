"""API de l'application : conversation du chantier, décisions depuis le fil, accueil des métiers (données de démonstration).
Lancement : python3 test_api_app.py
"""
import io, os, sys, tempfile
from urllib.parse import quote
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_apiapp_")
import app as A

A.app.config["TESTING"] = True
A.app.test_cli_runner().invoke(args=["demo"])
cli = A.app.test_client()
ok = 0


def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("  ✓", msg)


def tok(email):
    return cli.post("/api/v1/connexion", json=dict(email=email, password="Demo-Chantier-2026")).json["token"]


H = lambda t: {"Authorization": f"Bearer {t}"}
own, chef, awa, sup, pil = (tok(f"{u}@demo.chantiervrai.ci") for u in ("aminata", "koffi", "awa", "quincaillerie", "pilote"))
X = "/api/v1/chantiers/1/conversation"

print("Conversation")
j = cli.get(X, headers=H(own)).json
check(j["ok"] and j["can_write"] and j["chef"] and len(j["items"]) >= 5, "le fil se charge avec messages et événements")
types = {i["type"] for i in j["items"]}
check({"text", "photo", "buy", "change"} <= types, "messages, photo, demande d'achat et travaux dans le même fil")
ph = next(i for i in j["items"] if i["type"] == "photo")
check(ph["file_url"] and cli.get(ph["file_url"], headers=H(own)).status_code == 200 and ph["distance"] is not None, "photo lisible avec la distance")
check(all(i["day"] and i["time"] for i in j["items"]), "jour et heure prêts à afficher")
last = j["last"]
r = cli.post(X, headers=H(chef), data={"body": "Le camion arrive à 15h"})
check(r.status_code == 201, "le chef écrit depuis l'application")
j2 = cli.get(f"{X}?apres={quote(last)}", headers=H(own)).json
check(len(j2["items"]) == 1 and j2["items"][0]["body"] == "Le camion arrive à 15h" and not j2["items"][0]["mine"], "seul le nouveau message revient")
r = cli.post(X, headers=H(own), data={"file": (io.BytesIO(b"\x1aE\xdf\xa3" + b"0" * 500), "note.m4a"), "duration": "7"}, content_type="multipart/form-data")
check(r.status_code == 201, "note vocale envoyée (m4a du téléphone)")
check(cli.post(X, headers=H(own), data={"body": ""}).status_code == 400, "message vide refusé")
check(cli.get(X, headers=H(sup)).status_code == 403, "le fournisseur n'a pas accès")
check(cli.get(X).status_code in (302, 401), "connexion requise")

print("Décisions depuis le fil")
buy = next(i for i in j["items"] if i["type"] == "buy" and i["status"] == "demande")
r = cli.post("/api/v1/chantiers/1/achats", headers=H(chef), json={"action": "paid", "id": buy["id"]})
check(r.status_code in (400, 403), "le chef ne peut pas payer sa propre demande")
r = cli.post("/api/v1/chantiers/1/achats", headers=H(own), json={"action": "paid", "id": buy["id"], "pay_ref": "OM-APP-1"})
check(r.status_code == 200 and r.json["ok"], "le propriétaire paie depuis l'application")
co = next(i for i in j["items"] if i["type"] == "change")
r = cli.post("/api/v1/chantiers/1/avenants", headers=H(own), json={"action": "accept", "id": co["id"]})
check(r.status_code == 200, "travaux supplémentaires acceptés")
st = {i["id"]: i["status"] for i in cli.get(X, headers=H(own)).json["items"] if i["type"] in ("buy", "change")}
check(st[buy["id"]] == "payee" and st[co["id"]] == "acceptee", "le fil montre les nouveaux statuts")

print("Accueil des métiers")
h = cli.get("/api/v1/accueil", headers=H(awa)).json
check(h["pro"]["hero"]["kicker"] == "Prochaine inspection" and h["pro"]["hero"]["cta"]["path"].startswith("/chantiers/"), "inspectrice : prochaine inspection")
req = next(i for i in h["pro"]["todo"] if i["answer_inspection"])
check(req["note"] and len(h["pro"]["kpis"]) == 3, "demande avec message du propriétaire et chiffres du mois")
r = cli.post(f"/api/v1/inspections/{req['answer_inspection']}/accepter", headers=H(awa))
check(r.status_code == 200 and A.connect().execute("SELECT status FROM inspections WHERE id = ?", (req["answer_inspection"],)).fetchone()[0] == "acceptee",
      "demande acceptée depuis l'application")
check(cli.post(f"/api/v1/inspections/{req['answer_inspection']}/accepter", headers=H(sup)).status_code == 403, "réservé à l'inspecteur")
h = cli.get("/api/v1/accueil", headers=H(sup)).json
check(h["pro"]["hero"]["kicker"] == "Prochaine livraison" and h["pro"]["hero"]["thumb_url"] is None, "fournisseur : prochaine livraison, sans photo privée")
h = cli.get("/api/v1/accueil", headers=H(pil)).json
check(h["pilot"] and h["pro"]["hero"]["kicker"] == "Prochain vol", "télépilote : prochain vol")
check(cli.get("/api/v1/accueil", headers=H(own)).json["pro"] is None, "propriétaire : pas d'accueil métier")
print("Viseur")
pj = cli.get("/api/v1/chantiers/1", headers=H(chef)).json["project"]
check(isinstance(pj["zones"], list) and len(pj["photo_tags"]) == 6 and "chat_unread" in pj, "zones, sujets de photo et non-lus fournis à l'application")
print(f"\nAPI de l'application : {ok} vérifications OK")
