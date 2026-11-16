"""Tableau de pilotage : accès réservé (fondateur, finance), calculs justes, rendu, SQLite et PostgreSQL.
Lancement : python3 test_pilotage.py   (ou avec DATABASE_URL=postgresql://… pour PostgreSQL)
"""
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_pil_")
PG = os.environ.get("DATABASE_URL", "").startswith("postgres")
if PG:
    from services import db as _DB
    try:
        import psycopg  # noqa: F401
    except ImportError:
        from tests_support import pgwire
        _DB.set_driver(pgwire)
    _c = _DB.connect("")
    _c.execute("DROP SCHEMA public CASCADE"); _c.execute("CREATE SCHEMA public"); _c.commit(); _c.close()

import app as A
from services import kpi as KPI

A.app.config["TESTING"] = True
A.app.config["STAFF_2FA"] = False
ok = 0


def check(cond, label):
    global ok
    assert cond, label
    ok += 1
    print("  ok ", label)


assert "Propriétaire" in A.app.test_cli_runner().invoke(args=["demo"]).output
cli = A.app.test_cli_runner()
cli.invoke(args=["creer-admin", "awa@demo.chantiervrai.ci"])                       # fondateur
cli.invoke(args=["creer-admin", "architecte@demo.chantiervrai.ci", "--role", "finance"])
cli.invoke(args=["creer-admin", "quincaillerie@demo.chantiervrai.ci", "--role", "verification"])


def login(email):
    c = A.app.test_client()
    t = re.search(r'name="csrf" value="([^"]+)"', c.get("/connexion").get_data(as_text=True)).group(1)
    c.post("/connexion", data=dict(email=email, password="Demo-Chantier-2026", csrf=t))
    return c


print("Accès")
check(login("aminata@demo.chantiervrai.ci").get("/admin/pilotage").status_code == 403, "propriétaire : refusé")
check(login("quincaillerie@demo.chantiervrai.ci").get("/admin/pilotage").status_code == 403, "équipe vérification : refusé")
check(login("architecte@demo.chantiervrai.ci").get("/admin/pilotage").status_code == 200, "équipe finance : autorisé")
boss = login("awa@demo.chantiervrai.ci")
check('href="/admin/pilotage"' in boss.get("/admin").get_data(as_text=True), "lien vers le pilotage en tête de l'administration")

print("Calculs")
s = A.connect()
now = datetime.now(timezone.utc)
uid = s.execute("SELECT id FROM users WHERE email = 'aminata@demo.chantiervrai.ci'").fetchone()[0]
pid = s.execute("SELECT id FROM projects LIMIT 1").fetchone()[0]
before = {t["key"]: t["cur"] for t in KPI.tiles(s, 30, A.plan_prices(s))}
d5 = (now - timedelta(days=5)).isoformat(timespec="seconds")
d40 = (now - timedelta(days=40)).isoformat(timespec="seconds")
for num, amt, paid in (("T1", 15000, d5), ("T2", 45000, d5), ("T3", 99000, d40)):
    s.execute("INSERT INTO billing_invoices (number, user_id, plan, cycle, period_start, period_end, amount_ht, vat_rate, vat, amount, "
              "status, due_date, paid_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
              (num, uid, "essentiel", "mois", paid[:10], paid[:10], amt, 18, 0, amt, "payee", paid[:10], paid, paid))
s.execute("INSERT INTO billing_invoices (number, user_id, plan, cycle, period_start, period_end, amount_ht, vat_rate, vat, amount, "
          "status, due_date, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
          ("T4", uid, "essentiel", "mois", d40[:10], d40[:10], 15000, 18, 2700, 17700, "a_payer", d40[:10], d40))
s.execute("INSERT INTO steps (project_id, position, name, amount, status, paid_at) VALUES (?,?,?,?,?,?)", (pid, 99, "Test", 2_000_000, "paye", d5))
s.commit()
t = {x["key"]: x for x in KPI.tiles(s, 30, A.plan_prices(s))}
check(t["revenue"]["cur"] - before["revenue"] == 60000, "chiffre d'affaires : factures payées de la période seulement (HT)")
check(t["revenue"]["prev"] >= 99000, "période précédente comptée à part (comparaison)")
check(t["money"]["cur"] - before["money"] == 2_000_000, "argent suivi : étapes payées de la période")
tr = KPI.trends(s)
check(len(tr["months"]) == 12 and tr["months"][-1] == now.strftime("%Y-%m") and tr["revenue"][-1] >= 60000
      and all(a + b == r for a, b, r in zip(tr["rev_inv"], tr["rev_com"], tr["revenue"])), "12 mois, le dernier est le mois en cours ; total = détail")
f = KPI.funnel(s)
check([x["label"] for x in f][0] == "Comptes créés" and all(f[i]["n"] >= f[i + 1]["n"] for i in range(3)), "entonnoir décroissant")
w = KPI.watch(s)
check(any(i["number"] == "T4" for i in w["unpaid"]), "facture échue repérée dans « À surveiller »")
m, n = KPI.mrr(s, A.plan_prices(s))
check(m >= 0 and n >= 0, "revenu mensuel récurrent calculé")
with A.app.test_request_context():
    check(A.compact(1_250_000) == "1,3 M" and A.compact(45_000) == "45 k" and A.compact(950) == "950", "montants abrégés : 1,3 M, 45 k")

print("Rendu")
for per in ("30", "90", "365", "nimporte"):
    r = boss.get(f"/admin/pilotage?periode={per}")
    check(r.status_code == 200, f"période {per} : page affichée")
h = boss.get("/admin/pilotage?periode=30").get_data(as_text=True)
check(h.count('class="card pl-tile"') == 6 and h.count('class="card pl-chart"') == 4, "6 chiffres clés et 4 graphiques")
check(len(re.findall(r'class="pl-col[ "]', h)) == 48 and h.count("data-tip=") == 48, "chaque mois a son info-bulle")
check(h.count("Voir les chiffres") == 4, "chaque graphique a sa vue en tableau")
check('aria-current="true"' in h and "T4" in h, "période choisie signalée ; facture en retard listée")
e = login("awa@demo.chantiervrai.ci")
h = e.get("/admin/pilotage?lang=en").get_data(as_text=True)
check("Business dashboard" in h and "Revenue collected" in h, "page traduite en anglais")
print(f"\n{ok} contrôles réussis{' (PostgreSQL)' if PG else ''}.")
