"""Test des abonnements ChantierVrai : essai, offres, factures, paiement, renouvellement, relances, suspension.
Lancement : python3 test_abonnements.py
"""
import os, re, sys, tempfile
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_abo_")
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
from services import billing as BILL

A.app.config["TESTING"] = True
A.app.config["BILLING_ENFORCED"] = True          # comme en production
PW = "Bingerville-2026"
SITE = (5.3521, -3.8892)
s = A.connect()


def tok(c, url="/"):
    m = re.search(r'name="csrf" value="([^"]+)"', c.get(url).get_data(as_text=True))
    assert m, url
    return m.group(1)


def post(c, url, data, page="/", follow=True):
    data = dict(data); data["csrf"] = tok(c, page)
    return c.post(url, data=data, follow_redirects=follow)


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


def new_project(c, name):
    data = dict(name=name, address="Bingerville", lat=str(SITE[0]), lng=str(SITE[1]), radius="100",
                start_date=datetime.now().date().isoformat(), step_name_0="Fondations", step_amount_0="1000000", step_days_0="10")
    return post(c, "/chantiers/nouveau", data, "/compte/abonnement", follow=False)


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def daily():
    with A.app.test_request_context():
        db = A.connect()
        out = A.billing_daily(db)
        db.close()
    return out


# --- 0. Logique pure ---
assert BILL.add_months(datetime(2026, 1, 31), 1) == datetime(2026, 2, 28)
assert BILL.period_price("pro", "an") == 45000 * 10 and BILL.with_vat(10000, 18) == (1800, 11800)
assert BILL.from_ttc(11800, 18) == (10000, 1800) and BILL.from_ttc(15000, 0) == (15000, 0)
assert BILL.invoice_number(2026, 7) == "CV-2026-0007"
print("calculs : périodes, prix annuel, TVA, numérotation")

own = register("a@x.ci"); chef = register("k@x.ci", "chef")
boss = register("boss@cv.ci"); fin = register("fin@cv.ci")
A.app.test_cli_runner().invoke(args=["creer-admin", "boss@cv.ci"])
A.app.test_cli_runner().invoke(args=["creer-admin", "fin@cv.ci", "--role", "finance"])
A.app.config["STAFF_2FA"] = False
uid = one("SELECT id FROM users WHERE email='a@x.ci'")[0]

# --- 1. Essai gratuit : 30 jours, 1 chantier ; le chef ne paie rien ---
h = html(own.get("/compte/abonnement"))
assert "Essai gratuit" in h and "Essentiel" in h and "15 000" in h and "Sur devis" in h
sub = one("SELECT status, plan, trial_end FROM subscriptions WHERE user_id=?", uid)
assert sub[0] == "essai" and (datetime.fromisoformat(sub[2]) - datetime.now(timezone.utc)).days >= 29
assert chef.get("/compte/abonnement").status_code == 403
assert one("SELECT COUNT(*) FROM subscriptions WHERE user_id=(SELECT id FROM users WHERE email='k@x.ci')")[0] == 0
assert new_project(own, "Villa").status_code == 302
r = new_project(own, "Duplex")
assert r.headers["Location"].endswith("/compte/abonnement")                         # limite de l'essai : 1 chantier
assert "1 chantier en cours" in html(own.get("/compte/abonnement"))
print("essai : 30 jours, 1 chantier, intervenants gratuits")

# --- 2. Fin d'essai : alerte, bandeau, creation bloquee, chantier existant toujours accessible ---
s.execute("UPDATE subscriptions SET trial_end=? WHERE user_id=?", (ago(-3), uid)); s.commit()
assert daily()["fin_essai"] == 1 and daily()["fin_essai"] == 0                          # une seule alerte
assert "se termine dans" in html(own.get("/"))
s.execute("UPDATE subscriptions SET trial_end=? WHERE user_id=?", (ago(1), uid)); s.commit()
assert "essai gratuit est terminé" in html(own.get("/"))
pid = one("SELECT id FROM projects WHERE owner_id=?", uid)[0]
assert own.get(f"/chantiers/{pid}").status_code == 200
assert "Votre essai est terminé" in html(own.get("/chantiers/nouveau", follow_redirects=True))
print("fin d'essai : alertes, bandeau, création bloquée, chantier en cours accessible")

# --- 3. Choix de l'offre Pro annuelle : facture numerotee, TVA, paiement en ligne (simulation) ---
post(boss, "/admin/abonnements", dict(action="prices", price_essentiel="15000", price_pro="45000", vat_rate="18",
                                       seller="ChantierVrai SAS\nAbidjan, Cocody\nRCCM CI-ABJ-2026-B-0001",
                                       bank="Banque X - IBAN CI00 0000"), "/admin")
r = post(own, "/compte/abonnement", dict(action="choose", plan="pro", cycle="an"), "/compte/abonnement", follow=False)
inv_id = int(r.headers["Location"].split("/")[-1])
inv = one("SELECT number, amount_ht, vat, amount, status FROM billing_invoices WHERE id=?", inv_id)
year = datetime.now(timezone.utc).year
assert inv[:] == (f"CV-{year}-0001", 381356, 68644, 450000, "a_payer")       # prix TTC, facture HT + TVA
h = html(own.get(f"/compte/factures/{inv_id}"))
assert "RCCM CI-ABJ-2026-B-0001" in h and "450 000" in h and "381 356" in h and "IBAN CI00" in h and "Payer en ligne" in h
assert "FCFA TTC par mois" in html(own.get("/compte/abonnement"))
assert chef.get(f"/compte/factures/{inv_id}").status_code == 403
post(own, f"/compte/factures/{inv_id}", {}, f"/compte/factures/{inv_id}")
sub = one("SELECT status, plan, cycle, period_end FROM subscriptions WHERE user_id=?", uid)
assert sub[:3] == ("actif", "pro", "an") and one("SELECT status FROM billing_invoices WHERE id=?", inv_id)[0] == "payee"
assert (datetime.fromisoformat(sub[3]) - datetime.now(timezone.utc)).days >= 364
assert new_project(own, "Duplex").headers["Location"].startswith("/chantiers/")      # Pro : jusqu'a 5 chantiers
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=? AND title LIKE '%Paiement reçu%' AND channel='app'", uid)[0] == 1
print("offre Pro annuelle : facture CV-…, TVA 18 %, paiement en ligne, abonnement actif un an")

# --- 4. Renouvellement : facture 7 jours avant, relances, impaye, suspension, puis reprise par virement ---
s.execute("UPDATE subscriptions SET period_end=?, cycle='mois' WHERE user_id=?", (ago(-5), uid)); s.commit()
out = daily()
assert out["factures"] == 1
inv2 = one("SELECT id, number, amount, status, due_date FROM billing_invoices WHERE user_id=? AND status='a_payer'", uid)
assert inv2[2] == 45000 and inv2[1] == f"CV-{year}-0002"
assert daily()["factures"] == 0                                                         # pas de doublon
s.execute("UPDATE billing_invoices SET due_date=? WHERE id=?", (ago(4)[:10], inv2[0]))
s.execute("UPDATE subscriptions SET period_end=? WHERE user_id=?", (ago(4), uid)); s.commit()
out = daily()
assert out["relances"] == 1 and one("SELECT status FROM subscriptions WHERE user_id=?", uid)[0] == "impaye"
assert "Facture en retard" in html(own.get("/"))
assert daily()["relances"] == 0                                                         # relance J+3 deja faite
s.execute("UPDATE billing_invoices SET due_date=? WHERE id=?", (ago(16)[:10], inv2[0]))
s.execute("UPDATE subscriptions SET period_end=? WHERE user_id=?", (ago(16), uid)); s.commit()
assert daily()["suspendus"] == 1
assert one("SELECT status FROM subscriptions WHERE user_id=?", uid)[0] == "suspendu"
assert "Abonnement suspendu" in html(own.get("/"))
assert new_project(own, "Immeuble").headers["Location"].endswith("/compte/abonnement")
assert own.get(f"/chantiers/{pid}").status_code == 200                                  # donnees jamais bloquees
assert one("SELECT COUNT(*) FROM notifications WHERE user_id=(SELECT id FROM users WHERE email='fin@cv.ci') AND title LIKE "
           "'%Abonnement suspendu%' AND channel='app'")[0] == 1
h = html(fin.get("/admin"))
assert "Factures à encaisser" in h and inv2[1] in h and "Revenu mensuel récurrent" in h
assert "référence du virement" in html(post(fin, "/admin/abonnements", dict(action="inv_paid", id=inv2[0], method="virement"),
                                            "/admin"))
post(fin, "/admin/abonnements", dict(action="inv_paid", id=inv2[0], method="virement", reference="VIR-ABO-1"), "/admin")
assert one("SELECT status FROM subscriptions WHERE user_id=?", uid)[0] == "actif"
assert one("SELECT method, reference FROM billing_invoices WHERE id=?", inv2[0])[:] == ("virement", "VIR-ABO-1")
assert one("SELECT staff_role FROM admin_log WHERE action LIKE 'inv_paid:%'")[0] == "finance"
print("renouvellement : facture J-7, relance, impayé, suspension, reprise après virement validé par la finance")

# --- 5. Resiliation a l'echeance ---
post(own, "/compte/abonnement", dict(action="cancel"), "/compte/abonnement")
assert one("SELECT cancel_at_end FROM subscriptions WHERE user_id=?", uid)[0] == 1
s.execute("UPDATE subscriptions SET period_end=? WHERE user_id=?", (ago(-3), uid)); s.commit()
assert daily()["factures"] == 0                                                         # pas de facture apres resiliation
s.execute("UPDATE subscriptions SET period_end=? WHERE user_id=?", (ago(1), uid)); s.commit()
daily()
assert one("SELECT status FROM subscriptions WHERE user_id=?", uid)[0] == "resilie"
assert own.get(f"/chantiers/{pid}").status_code == 200
print("résiliation : s'arrête à l'échéance, données toujours accessibles")

# --- 6. Offre Entreprise : demande de devis, puis offre sur mesure par le super-admin ---
own2 = register("mairie@x.ci")
post(own2, "/compte/abonnement", dict(action="choose", plan="entreprise", message="12 écoles, marchés publics"),
     "/compte/abonnement")
assert one("SELECT COUNT(*) FROM notifications WHERE title LIKE '%Demande d''offre Entreprise%' AND channel='app' AND "
           "user_id=(SELECT id FROM users WHERE email='boss@cv.ci')")[0] == 1
assert post(fin, "/admin/abonnements", dict(action="custom", email="mairie@x.ci", plan="entreprise", price="250000",
                                            months="12"), "/admin", follow=False).status_code == 403
post(boss, "/admin/abonnements", dict(action="custom", email="mairie@x.ci", plan="entreprise", price="250000", sites="",
                                      months="12"), "/admin")
sub = one("SELECT status, plan, custom_price, sites_limit FROM subscriptions WHERE user_id=(SELECT id FROM users WHERE "
          "email='mairie@x.ci')")
assert sub[:] == ("actif", "entreprise", 250000, None)
for k in range(3):
    assert new_project(own2, f"École {k}").headers["Location"].startswith("/chantiers/")     # illimite
print("offre Entreprise : devis demandé, offre sur mesure appliquée par le super-admin")
print("TOUS LES TESTS ABONNEMENTS PASSENT")
