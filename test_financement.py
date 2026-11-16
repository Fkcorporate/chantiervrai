"""Test du plan de financement et du dossier de credit : calculs (mensualite, tresorerie mois par mois, retard,
endettement), saisie des sources, montants recus, autres couts, revenus en devise, dossier et pieces privees,
alerte quotidienne, droits d'acces, anglais.
Lancement : python3 test_financement.py
"""
import io, os, re, sys, tempfile
from datetime import date, datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
os.environ["CV_SYNC"] = "1"
os.environ["CV_INSTANCE"] = tempfile.mkdtemp(prefix="cv_fin_")
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
from services import finance as F

A.app.config["TESTING"] = True
PW = "Bingerville-2026"
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
    assert post(c, "/inscription", dict(terms="1", role=role, name=email.split("@")[0].upper(), email=email, password=PW,
                                        **extra), "/inscription", follow=False).status_code == 302, email
    return c


def notes(email, title):
    return one("SELECT COUNT(*) FROM notifications n JOIN users u ON u.id = n.user_id WHERE u.email = ? AND n.title LIKE ? "
               "AND n.channel = 'app'", email, f"%{title}%")[0]


def months(n):
    d = date.today().replace(day=15)
    y, m = divmod(d.month - 1 + n, 12)
    return d.replace(year=d.year + y, month=m + 1).isoformat()


print("Calculs")
check(F.annuity(1000000, 12, 12) == 88849 and F.annuity(1200000, 0, 12) == 100000, "mensualité d'un prêt (avec et sans intérêts)")
check(F.to_xof(1000, "EUR") == 655957 and F.to_xof(100, "USD", 600) == 60000 and F.to_xof(100, "USD") is None, "conversion en FCFA")
row = lambda **k: dict(dict(id=1, kind="epargne", amount=0, expected_on=None, months=None, status="prevue", rate=None,
                            monthly_payment=None, label=None), **k)
today = date(2027, 1, 10)
src = [row(id=1, amount=3000000, expected_on="2027-01-05"), row(id=2, kind="transferts", amount=500000, months=6, expected_on="2027-01-20"),
       row(id=3, kind="credit", amount=4000000, expected_on="2027-04-01", rate=10, months=60)]
outs = [("2027-01-31", 2000000, "Fondations", False), ("2027-02-28", 3000000, "Murs", False), ("2027-05-31", 4000000, "Dalle", False)]
pl = F.plan(src, {1: [("2027-01-06", 3000000)]}, outs, today=today)
check(pl["budget"] == 9000000 and pl["total_sources"] == 10000000 and pl["shortfall"] == 0, "budget, total des sources, aucun manque global")
check(pl["first_gap"]["month"] == "2027-02" and pl["first_gap"]["balance"] == -1000000, "trou de trésorerie de 1 000 000 FCFA en février")
check(pl["worst"]["month"] == "2027-03" and pl["worst"]["balance"] == -500000 or pl["worst"]["month"] == "2027-02",
      "manque le plus fort repéré")
check(next(x for x in pl["sources"] if x["row"]["id"] == 1)["status"] == "recue", "source entièrement reçue : « Reçue »")
check(next(x for x in pl["sources"] if x["row"]["id"] == 2)["total"] == 3000000, "transferts : 6 mois × 500 000")
pl2 = F.plan([row(id=1, amount=1000000, expected_on="2026-12-01")], {}, [], today=today)
check(pl2["late"] and pl2["sources"][0]["status"] == "en_retard", "source attendue et non reçue : en retard")
dbt = F.debt({"monthly_income": 2500, "income_currency": "EUR", "fx_rate": None, "other_charges": 300}, src)
check(dbt["income"] == round(2500 * F.EUR_XOF) and dbt["loans"] == F.annuity(4000000, 10, 60) and dbt["ratio"] == round(100 * (dbt["loans"] + round(300 * F.EUR_XOF)) / dbt["income"], 1),
      "taux d'endettement avec revenus en euros")

print("Plan de financement")
own = register("a@x.ci"); chef = register("k@x.ci", "chef", phone="0700000000")
archi = register("arc@x.ci", "pro", profession="architecte"); compta = register("cpt@x.ci", "pro", profession="comptable")
data = dict(name="Villa", address="Bingerville", lat="5.3521", lng="-3.8892", radius="100", pay_mode="suivi",
            start_date=date.today().isoformat())
for i, (n, a, d) in enumerate([("Fondations", 3000000, 20), ("Murs", 4000000, 30), ("Toiture", 3000000, 30)]):
    data[f"step_name_{i}"], data[f"step_amount_{i}"], data[f"step_days_{i}"] = n, str(a), str(d)
pid = int(post(own, "/chantiers/nouveau", data, "/chantiers/nouveau", follow=False).headers["Location"].split("/")[-1])
post(chef, "/rejoindre", dict(code=one("SELECT invite_code FROM projects WHERE id=?", pid)[0]))
for email, role in (("arc@x.ci", "architecte"), ("cpt@x.ci", "comptable")):
    post(own, f"/chantiers/{pid}/membres", dict(email=email, role=role), f"/chantiers/{pid}?onglet=dossier")
url = f"/chantiers/{pid}/financement"
h = html(own.get(url))
check("Aucune source pour l'instant" in h and "10 000 000" in h, "page vide : budget des étapes affiché")
check("Plan de financement" in html(own.get(f"/chantiers/{pid}?onglet=etapes")), "lien depuis l'onglet Étapes")
post(own, url, dict(action="source", kind="epargne", amount="4000000", expected_on=date.today().isoformat(), status="confirmee", label="Épargne Paris"), url)
post(own, url, dict(action="source", kind="credit", amount="5000000", expected_on=months(3), rate="9", months="120", lender="Banque X"), url)
post(own, url, dict(action="source", kind="transferts", amount="250000", months="12", expected_on=date.today().isoformat()), url)
check(one("SELECT COUNT(*) FROM fin_sources WHERE project_id=?", pid)[0] == 3, "trois sources enregistrées")
h = html(own.get(url))
check("Trou de trésorerie en" in h and "Épargne Paris" in h and "Banque X" in h, "trou de trésorerie annoncé avec le mois")
check(A.fcfa_txt(F.annuity(5000000, 9, 120)) in h and "coût des intérêts" in h, "mensualité et coût du crédit affichés")
check("Financement incomplet" not in h, "sources suffisantes au total (12 000 000 pour 10 000 000)")
sid = one("SELECT id FROM fin_sources WHERE kind='epargne'")[0]
post(own, url, dict(action="receipt", source_id=str(sid), amount="2500000", received_on=date.today().isoformat()), url)
h = html(own.get(url))
check("2 500 000 / " in h and "1 500 000 FCFA à recevoir" in h, "montant reçu partiel suivi")
post(own, url, dict(action="cost", label="Titre foncier et notaire", amount="1500000", due_on=months(1)), url)
check(one("SELECT COUNT(*) FROM fin_costs WHERE project_id=?", pid)[0] == 1 and "11 500 000" in html(own.get(url)), "autre coût ajouté au budget")
cid = one("SELECT id FROM fin_costs")[0]
post(own, url, dict(action="cost_paid", cost_id=str(cid)), url)
check(one("SELECT paid FROM fin_costs WHERE id=?", cid)[0] == 1, "coût marqué payé")
post(own, url, dict(action="source", source_id=str(sid), kind="epargne", amount="4000000", expected_on=date.today().isoformat(),
                    status="confirmee", label="Épargne Paris et Abidjan"), url)
check(one("SELECT label FROM fin_sources WHERE id=?", sid)[0] == "Épargne Paris et Abidjan", "source modifiée")
post(own, url, dict(action="profile", monthly_income="3000", income_currency="EUR", other_charges="400", country="France", diaspora="1"), url)
h = html(own.get(url))
check("Taux d'endettement" in h and "1 967 871" in h, "revenus en euros convertis, taux d'endettement calculé")
check(post(own, url, dict(action="source", kind="inconnu", amount="1"), url).status_code == 200
      and one("SELECT COUNT(*) FROM fin_sources")[0] == 3, "type de source inconnu refusé")

print("Accès")
check(archi.get(url).status_code == 403 and chef.get(url).status_code == 403, "architecte et chef n'ont pas accès au financement")
check(compta.get(url).status_code == 200 and "Ajouter une source" not in html(compta.get(url)), "comptable : lecture seule")
check(post(compta, url, dict(action="cost", label="x", amount="1"), url, follow=False).status_code == 403, "comptable : pas de modification")

print("Dossier de crédit")
durl = f"/chantiers/{pid}/financement/dossier"
h = html(own.get(durl))
check(re.search(r"pièces? obligatoires? manquantes?", h) and "Pièce d'identité ou passeport" in h, "pièces manquantes listées")
check("Titre de séjour" in h, "pièce propre à la diaspora demandée")
check("Budget détaillé par étape" in h and "Fourni par ChantierVrai" in h, "budget et planning fournis par ChantierVrai")
r = post(own, durl, dict(kind="identite", file=(io.BytesIO(b"%PDF-1.4 passeport"), "passeport.pdf")), durl, files=True)
check("Pièce ajoutée" in html(r), "pièce ajoutée")
doc = one("SELECT id FROM fin_documents")[0]
check(own.get(f"/financement/pieces/{doc}").status_code == 200, "pièce consultable par le propriétaire")
check(archi.get(f"/financement/pieces/{doc}").status_code == 403 and chef.get(f"/financement/pieces/{doc}").status_code == 403,
      "pièces privées : ni l'architecte ni le chef")
check("passeport" not in html(own.get(f"/chantiers/{pid}?onglet=dossier")), "pièces absentes du dossier technique partagé")
h = html(own.get(durl))
check("Taux d'endettement" in h and "France" in h and "Épargne Paris et Abidjan" in h, "dossier : emprunteur, revenus et plan de financement")
check("pas d'avis sur l'obtention d'un crédit" in h, "mention : pas d'avis sur le crédit")
post(own, durl, dict(action="delete", doc_id=str(doc)), durl)
check(one("SELECT COUNT(*) FROM fin_documents")[0] == 0, "pièce retirée")

print("Alerte quotidienne")
with A.app.test_request_context():
    n1 = A.finance_daily(A.connect())
    n2 = A.finance_daily(A.connect())
check(n1 == 1 and n2 == 0 and notes("a@x.ci", "Financement : argent manquant") == 1, "trou proche : une alerte, pas de doublon")
s.execute("UPDATE fin_sources SET expected_on = ? WHERE kind = 'credit'", ((date.today() - timedelta(days=40)).isoformat(),)); s.commit()
with A.app.test_request_context():
    A.finance_daily(A.connect())
check(notes("a@x.ci", "Financement : source en retard") == 1, "crédit attendu non reçu : alerte de retard")
r = A.app.test_cli_runner().invoke(args=["quotidien"])
check("Financement :" in r.output, "intégré à la tâche quotidienne")

print("Anglais")
own.get("/?lang=en")
h = html(own.get(url))
check("Financing plan" in h and "Bank loan" in h and "Debt ratio" in h, "plan de financement en anglais")
check("Financing file" in html(own.get(durl)), "dossier en anglais")
print(f"\n{ok} contrôles réussis.")
