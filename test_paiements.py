"""Test du paiement suivi (ChantierVrai ne touche pas l'argent) et de l'interrupteur du sequestre (super-admin).
Lancement : python3 test_paiements.py
"""
import io, os, re, sys, tempfile
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_paie_")
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

A.app.config["TESTING"] = True             # sequestre : reglage de la base (desactive par defaut)
PW = "Bingerville-2026"
SITE = (5.3521, -3.8892)
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


def one(q, *a):
    return s.execute(q, a).fetchone()


def register(email, role="proprio", **extra):
    c = A.app.test_client()
    r = post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW, **extra),
             "/inscription", follow=False)
    assert r.status_code == 302, email
    return c


def png():
    b = io.BytesIO(); Image.new("RGB", (60, 40), (200, 30, 30)).save(b, "PNG"); return b.getvalue()


def new_project(c, mode, name="Villa"):
    data = dict(name=name, address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100", pay_mode=mode,
                start_date=datetime.now().date().isoformat())
    for i, (n, a, d) in enumerate(A.DEFAULT_STEPS[:3]):
        data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
    return int(post(c, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])


own = register("a@x.ci"); chef = register("k@x.ci", "chef", phone="0700000000")
insp = register("i@x.ci", "inspecteur", zone="Bingerville", tarif="40000", phone="0500000000")
sup = register("depot@x.ci", "fournisseur", phone="0102030405", supplier_terms="1")
boss = register("boss@cv.ci"); fin = register("fin@cv.ci"); stranger = register("z@x.ci")
A.app.test_cli_runner().invoke(args=["creer-admin", "boss@cv.ci"])
A.app.test_cli_runner().invoke(args=["creer-admin", "fin@cv.ci", "--role", "finance"])
ids = {r["email"]: r["id"] for r in s.execute("SELECT id, email FROM users")}

# --- 1. Sequestre desactive par defaut : pas propose, pas de depot, repli sur le paiement suivi ---
assert not A.escrow_enabled(s)
assert "Séquestre : je dépose" not in html(own.get("/chantiers/nouveau"))
assert "Paiement suivi" in html(own.get("/chantiers/nouveau"))
pid = new_project(own, "sequestre")
assert one("SELECT pay_mode FROM projects WHERE id=?", pid)[0] == "suivi"
assert "aucun nouveau dépôt" in html(post(own, f"/chantiers/{pid}/paiements/depot", dict(amount="1000000"),
                                         f"/chantiers/{pid}?onglet=etapes"))
assert one("SELECT COUNT(*) FROM transactions")[0] == 0
h = html(boss.get("/admin"))
assert "Séquestre désactivé" in h and "ChantierVrai ne touche pas l&#39;argent" in h
print("séquestre désactivé par défaut : non proposé, dépôt refusé, chantier en paiement suivi")

code = re.search(r'class="code">(\w+)<', html(own.get(f"/chantiers/{pid}"))).group(1)
post(chef, "/rejoindre", dict(code=code))
st1, st2 = [r["id"] for r in s.execute("SELECT id FROM steps WHERE project_id=? ORDER BY position LIMIT 2", (pid,))]
amount = one("SELECT amount FROM steps WHERE id=?", st1)[0]

# --- 2. Validation : bon a payer emis, l'etape n'est pas encore payee ---
s.execute("UPDATE steps SET status='declare', declared_at=? WHERE id=?", (A.now_iso(), st1)); s.commit()
r = post(own, f"/chantiers/{pid}/etapes/{st1}/valider", dict(override="1"), f"/chantiers/{pid}?onglet=etapes", follow=False)
assert r.headers["Location"].endswith(f"/paiements/etape/{st1}")
st = one("SELECT status, pay_ref FROM steps WHERE id=?", st1)
assert st[0] == "versement" and st[1] == f"BAP-{pid}-E{st1}"
h = html(own.get(f"/paiements/etape/{st1}"))
assert "Bon à payer" in h and f"BAP-{pid}-E{st1}" in h and "0700000000" in h and "ne détient pas cet argent" in h
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=? AND title LIKE '%Paiement à venir%' AND channel='app'",
           ids["k@x.ci"])[0] == 1
assert one("SELECT status FROM steps WHERE project_id=? AND position=1", pid)[0] == "en_cours"   # etape suivante ouverte
print("validation : bon à payer émis, bénéficiaire prévenu, étape pas encore payée")

# --- 3. Declaration : reference ou recu obligatoire, montant plafonne, paiement en plusieurs fois ---
url = f"/paiements/etape/{st1}"
assert "référence de la transaction ou le reçu" in html(post(own, url, dict(amount="100000", method="mobile_money"), url))
assert "Montant trop élevé" in html(post(own, url, dict(amount=str(amount + 1), method="mobile_money", reference="X"), url))
assert post(chef, url, dict(amount="1000", method="mobile_money", reference="X"), url, follow=False).status_code == 403
post(own, url, dict(amount="1000000", method="mobile_money", reference="WAVE-TX-1"), url)
assert one("SELECT status, payee_id FROM payment_records WHERE reference='WAVE-TX-1'")[:] == ("declare", ids["k@x.ci"])
assert "paiement à confirmer" in html(chef.get(f"/chantiers/{pid}"))
rid1 = one("SELECT id FROM payment_records WHERE reference='WAVE-TX-1'")[0]
assert post(own, f"/paiements/recus/{rid1}", dict(action="confirm"), "/paiements/recus", follow=False).status_code == 403
post(chef, f"/paiements/recus/{rid1}", dict(action="confirm"), "/paiements/recus")
assert one("SELECT status FROM payment_records WHERE id=?", rid1)[0] == "confirme"
assert one("SELECT status FROM steps WHERE id=?", st1)[0] == "versement"          # pas encore tout paye
rest = amount - 1000000
post(own, url, dict(amount=str(rest), method="virement", receipt=(io.BytesIO(png()), "recu.png")), url, files=True)
rid2 = one("SELECT id FROM payment_records WHERE payee_id=? AND status='declare'", ids["k@x.ci"])[0]
assert one("SELECT receipt_sha FROM payment_records WHERE id=?", rid2)[0]
print("déclaration : preuve obligatoire, plafond, paiement en deux fois, seul le payeur déclare")

# --- 4. Recu : visible par les parties seulement ; contestation puis nouvelle declaration ---
assert chef.get(f"/paiements/recu/{rid2}/fichier").status_code == 200
assert stranger.get(f"/paiements/recu/{rid2}/fichier").status_code == 403
assert stranger.get(url).status_code == 403
assert "10 caractères" in html(post(chef, f"/paiements/recus/{rid2}", dict(action="contest", text="non"), "/paiements/recus"))
post(chef, f"/paiements/recus/{rid2}", dict(action="contest", text="Rien reçu sur mon compte bancaire"), "/paiements/recus")
assert one("SELECT status FROM payment_records WHERE id=?", rid2)[0] == "conteste"
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=? AND title LIKE '%Paiement contesté%' AND channel='app'",
           ids["a@x.ci"])[0] == 1
assert "Rien reçu" in html(own.get(url))
post(own, url, dict(amount=str(rest), method="virement", reference="VIR-778"), url)
rid3 = one("SELECT id FROM payment_records WHERE reference='VIR-778'")[0]
post(chef, f"/paiements/recus/{rid3}", dict(action="confirm"), "/paiements/recus")
st = one("SELECT status, paid_at, pay_ref FROM steps WHERE id=?", st1)
assert st[0] == "paye" and st[1] and "WAVE-TX-1" in st[2] and "VIR-778" in st[2]
assert "Ce paiement a déjà reçu une réponse" in html(post(chef, f"/paiements/recus/{rid3}", dict(action="confirm"),
                                                           "/paiements/recus"))
print("contestation, nouvelle déclaration, confirmation : étape payée avec les références")

# --- 5. Registre, export CSV et export comptable ---
h = html(own.get(f"/chantiers/{pid}/paiements"))
assert "Registre des paiements" in h and "VIR-778" in h and "Payé et confirmé" in h
csv_ = own.get(f"/chantiers/{pid}/paiements?format=csv").get_data(as_text=True)
assert f"BAP-{pid}-E{st1}" in csv_ and "Contesté" in csv_ and "WAVE-TX-1" in csv_
assert stranger.get(f"/chantiers/{pid}/paiements").status_code == 403
assert "VIR-778" in html(chef.get(f"/chantiers/{pid}/paiements"))           # le chef voit ses paiements
acc = own.get(f"/chantiers/{pid}/export-comptable.csv").get_data(as_text=True)
assert "WAVE-TX-1" in acc and "VIR-778" in acc
print("registre des paiements, CSV et export comptable ok")

# --- 6. Inspection et commande de materiaux en paiement suivi ---
s.execute("INSERT INTO inspections (project_id, step_id, inspector_id, requested_by, fee, status, created_at, done_at, paid) "
          "VALUES (?,?,?,?,?,?,?,?,?)", (pid, st1, ids["i@x.ci"], ids["a@x.ci"], 40000, "realisee", A.now_iso(), A.now_iso(), 0))
iid = one("SELECT id FROM inspections WHERE project_id=?", pid)[0]
s.commit()
r = post(own, f"/inspections/{iid}/payer", {}, f"/chantiers/{pid}?onglet=dossier", follow=False)
assert r.headers["Location"].endswith(f"/paiements/inspection/{iid}")
iu = f"/paiements/inspection/{iid}"
post(own, iu, dict(amount="40000", method="mobile_money", reference="OM-55"), iu)
assert one("SELECT paid FROM inspections WHERE id=?", iid)[0] == 0
post(insp, f"/paiements/recus/{one('SELECT id FROM payment_records WHERE reference=?', 'OM-55')[0]}", dict(action="confirm"),
     "/paiements/recus")
assert one("SELECT paid FROM inspections WHERE id=?", iid)[0] == 1
now = A.now_iso()
s.execute("INSERT INTO orders (ref, project_id, step_id, supplier_id, created_by, status, pay_mode, total, received_total, "
          "commission, created_at, updated_at, received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
          ("CMD-T1", pid, st2, ids["depot@x.ci"], ids["a@x.ci"], "a_payer", "suivi", 500000, 480000, 14400, now, now, now))
oid = one("SELECT id FROM orders WHERE ref='CMD-T1'")[0]
s.commit()
assert "Déclarez le paiement" in html(own.get(f"/commandes/{oid}"))
assert "Marquer payée" not in html(own.get(f"/commandes/{oid}"))
ou = f"/paiements/commande/{oid}"
assert "480 000" in html(own.get(ou))
post(own, ou, dict(amount="480000", method="virement", reference="VIR-CMD"), ou)
post(sup, f"/paiements/recus/{one('SELECT id FROM payment_records WHERE reference=?', 'VIR-CMD')[0]}", dict(action="confirm"),
     "/paiements/recus")
assert one("SELECT status, pay_ref FROM orders WHERE id=?", oid)[:] == ("receptionnee", "VIR-CMD")
print("inspection et commande : bon à payer, déclaration, confirmation par l'inspecteur et le fournisseur")

# --- 7. Commissions a facturer aux fournisseurs (finance) ---
h = html(fin.get("/admin"))
assert "Commissions à facturer aux fournisseurs" in h and "14 400" in h
assert "Paiements de la plateforme" not in h                                    # interrupteur : super-admin seulement
c = fin.get(f"/admin/commissions.csv?mois={now[:7]}").get_data(as_text=True)
assert "DEPOT" in c and "14400" in c
assert own.get("/admin/commissions.csv").status_code == 403
print("relevé des commissions fournisseurs : écran finance et CSV")

# --- 8. Relance du beneficiaire apres 3 jours ---
s.execute("UPDATE steps SET status='declare' WHERE id=?", (st2,)); s.commit()
post(own, f"/chantiers/{pid}/etapes/{st2}/valider", dict(override="1"), f"/chantiers/{pid}?onglet=etapes")
u2 = f"/paiements/etape/{st2}"
post(own, u2, dict(amount="1000", method="especes", reference="RECU-12"), u2)
old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
s.execute("UPDATE payment_records SET created_at=? WHERE reference='RECU-12'", (old,)); s.commit()
with A.app.test_request_context():
    db = A.connect()
    assert A.remind_payments(db) == 1 and A.remind_payments(db) == 0
    db.close()
print("relance automatique du bénéficiaire ok")

# --- 9. Interrupteur du sequestre : super-admin, partenaire et confirmation exigés ---
assert post(fin, "/admin/action", dict(action="escrow_on", partner="Banque X", confirm="1"), "/admin",
            follow=False).status_code == 403
assert "partenaire agréé" in html(post(boss, "/admin/action", dict(action="escrow_on"), "/admin"))
assert not A.escrow_enabled(s)
post(boss, "/admin/action", dict(action="escrow_on", partner="Banque Atlantique (séquestre)", confirm="1"), "/admin")
assert A.escrow_enabled(s) and one("SELECT value FROM settings WHERE key='escrow_partner'")[0].startswith("Banque")
assert 'value="sequestre"' in html(own.get("/chantiers/nouveau"))
pid2 = new_project(own, "sequestre", "Duplex")
assert one("SELECT pay_mode FROM projects WHERE id=?", pid2)[0] == "sequestre"
post(own, f"/chantiers/{pid2}/paiements/depot", dict(amount="2000000"), f"/chantiers/{pid2}?onglet=etapes")
assert A.escrow(pid2, s)["balance"] == 2000000
post(boss, "/admin/action", dict(action="escrow_off"), "/admin")
assert not A.escrow_enabled(s)
h = html(own.get(f"/chantiers/{pid2}?onglet=etapes"))
assert "n&#39;accepte plus de nouveaux dépôts" in h and "Déposer sur le séquestre" not in h
assert "aucun nouveau dépôt" in html(post(own, f"/chantiers/{pid2}/paiements/depot", dict(amount="1000"),
                                         f"/chantiers/{pid2}?onglet=etapes"))
assert "Il reste 2 000 000 FCFA" in html(post(own, f"/chantiers/{pid2}/paiements/mode", dict(pay_mode="suivi"),
                                              f"/chantiers/{pid2}?onglet=etapes"))
assert one("SELECT pay_mode FROM projects WHERE id=?", pid2)[0] == "sequestre"     # fonds restants proteges
assert one("SELECT COUNT(*) FROM admin_log WHERE action IN ('escrow_on', 'escrow_off')")[0] == 2
print("interrupteur du séquestre : super-admin seul, fonds restants protégés après désactivation")

# --- 10. API ouverte : paiements suivis lisibles par le logiciel du client ---
import secrets as _sec, hashlib as _h
raw = "cvk_" + _sec.token_hex(16)
s.execute("INSERT INTO api_keys (user_id, name, key_hash, prefix, scope, created_at) VALUES (?,?,?,?,?,?)",
          (ids["a@x.ci"], "compta", _h.sha256(raw.encode()).hexdigest(), raw[:10], "read", A.now_iso())); s.commit()
j = A.app.test_client().get(f"/api/ext/v1/chantiers/{pid}/paiements", headers={"Authorization": "Bearer " + raw}).get_json()
b = next(x for x in j["paiements_suivis"] if x["bon_a_payer"] == f"BAP-{pid}-E{st1}")
assert b["paye"] and b["confirme"] == amount and {p_["statut"] for p_ in b["paiements"]} == {"confirme", "conteste"}
print("API ouverte : bons à payer et paiements suivis ok")
print("TOUS LES TESTS PAIEMENTS PASSENT")
