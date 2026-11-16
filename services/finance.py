"""Plan de financement du chantier et dossier de credit.

Sans lien avec une banque : le proprietaire declare ses sources (epargne, credit, famille, tontine, transferts
mensuels...), ChantierVrai les confronte au planning des etapes, montre le mois ou l'argent manque, suit ce qui est
recu et prepare le dossier a presenter a une banque. Aucun avis sur l'acceptation d'un credit.
"""
from datetime import date, datetime

EUR_XOF = 655.957          # parite fixe euro / franc CFA


def t(fr, en):
    return {"fr": fr, "en": en}


def _p(d, lang):
    return (d or {}).get(lang) or (d or {}).get("fr") or ""


KINDS = {
    "epargne": t("Épargne personnelle", "Personal savings"),
    "transferts": t("Transferts mensuels (salaire)", "Monthly transfers (salary)"),
    "credit": t("Crédit bancaire", "Bank loan"),
    "microfinance": t("Microfinance", "Microfinance"),
    "famille": t("Aide de la famille", "Family support"),
    "tontine": t("Tontine", "Tontine (rotating savings)"),
    "vente": t("Vente d'un bien", "Sale of an asset"),
    "autre": t("Autre", "Other"),
}
LOAN_KINDS = ("credit", "microfinance")
STATUS = {"prevue": t("Prévue", "Planned"), "confirmee": t("Confirmée", "Confirmed"),
          "recue": t("Reçue", "Received"), "en_retard": t("En retard", "Late")}
COST_SUGGESTIONS = [t("Achat du terrain", "Land purchase"), t("Titre foncier et notaire", "Land title and notary"),
                    t("Permis de construire", "Building permit"), t("Plans et études", "Drawings and studies"),
                    t("Raccordements eau et électricité", "Water and power connections"),
                    t("Imprévus (5 à 10 % du budget)", "Contingency (5 to 10% of budget)")]
CURRENCIES = {"XOF": "FCFA", "EUR": "EUR", "USD": "USD", "CAD": "CAD", "GBP": "GBP", "CHF": "CHF"}
DEBT_REFERENCE = 33        # repere courant (%), chaque banque applique sa propre regle


def parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def mkey(d):
    return f"{d.year:04d}-{d.month:02d}"


def add_month(k, n=1):
    y, m = int(k[:4]), int(k[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def months_between(a, b):
    out, k = [], a
    while k <= b and len(out) < 240:
        out.append(k)
        k = add_month(k)
    return out


def annuity(principal, annual_rate, months):
    """Mensualite constante d'un pret (taux annuel en %, duree en mois)."""
    if not principal or not months:
        return 0
    r = (annual_rate or 0) / 1200
    if r == 0:
        return round(principal / months)
    return round(principal * r / (1 - (1 + r) ** -months))


def loan_payment(src):
    if src["kind"] not in LOAN_KINDS:
        return 0
    return src["monthly_payment"] or annuity(src["amount"], src["rate"], src["months"])


def loan_cost(src):
    """Cout total des interets, si la duree est connue."""
    pay = loan_payment(src)
    if not pay or not src["months"]:
        return None
    return max(pay * src["months"] - (src["amount"] or 0), 0)


def to_xof(amount, currency, rate=None):
    if amount is None:
        return None
    if currency in (None, "", "XOF"):
        return round(amount)
    if currency == "EUR":
        return round(amount * EUR_XOF)
    return round(amount * rate) if rate else None


def source_schedule(src):
    """[(mois, montant)] prevus pour une source : une fois, ou chaque mois pour des transferts."""
    d = parse_date(src["expected_on"]) or date.today()
    if src["kind"] == "transferts" and (src["months"] or 0) > 0:
        return [(add_month(mkey(d), i), src["amount"] or 0) for i in range(int(src["months"]))]
    return [(mkey(d), src["amount"] or 0)]


def source_total(src):
    return sum(a for _m, a in source_schedule(src))


def plan(sources, receipts, outflows, today=None):
    """Tresorerie du chantier, mois par mois.

    sources : lignes avec kind, amount, expected_on, months, status
    receipts : {source_id: [(date, montant)]}
    outflows : [(date_prevue_ou_payee, montant, libelle, paye)]
    Retourne totaux, mois, premier manque et alertes.
    """
    today = today or date.today()
    now = mkey(today)
    inflow_plan, inflow_real = {}, {}
    late = []
    per_source = []
    for s in sources:
        got = receipts.get(s["id"], [])
        received = sum(a for _d, a in got)
        for d, a in got:
            k = mkey(parse_date(d) or today)
            inflow_real[k] = inflow_real.get(k, 0) + a
        rest = received
        remaining = []
        for k, a in source_schedule(s):
            take = min(rest, a)
            rest -= take
            if a - take > 0:
                remaining.append((k, a - take))
        total = source_total(s)
        status = "recue" if received >= total and total else s["status"]
        overdue = [(k, a) for k, a in remaining if k < now]
        if overdue and status != "recue":
            late.append((s, sum(a for _k, a in overdue)))
            status = "en_retard"
        for k, a in remaining:
            k = max(k, now)
            inflow_plan[k] = inflow_plan.get(k, 0) + a
        per_source.append({"row": s, "total": total, "received": received, "remaining": total - received, "status": status,
                           "payment": loan_payment(s), "cost": loan_cost(s)})
    out_plan, out_real = {}, {}
    for d, amount, _label, paid in outflows:
        k = mkey(parse_date(d) or today)
        if paid:
            out_real[k] = out_real.get(k, 0) + amount
        else:
            k = max(k, now)
            out_plan[k] = out_plan.get(k, 0) + amount
    keys = set(inflow_plan) | set(inflow_real) | set(out_plan) | set(out_real) | {now}
    months = []
    cum = 0
    first_gap = None
    worst = None
    for k in months_between(min(keys), max(keys)):
        i = inflow_real.get(k, 0) + inflow_plan.get(k, 0)
        o = out_real.get(k, 0) + out_plan.get(k, 0)
        cum += i - o
        row = {"month": k, "in": i, "in_real": inflow_real.get(k, 0), "out": o, "out_real": out_real.get(k, 0),
               "balance": cum, "past": k < now, "current": k == now}
        months.append(row)
        if cum < 0 and k >= now and first_gap is None:
            first_gap = row
        if cum < 0 and k >= now and (worst is None or cum < worst["balance"]):
            worst = row
    budget = sum(a for _d, a, _l, _p in outflows)
    spent = sum(a for _d, a, _l, p in outflows if p)
    total_src = sum(x["total"] for x in per_source)
    confirmed = sum(x["total"] for x in per_source if x["row"]["status"] in ("confirmee",) or x["status"] == "recue")
    received = sum(x["received"] for x in per_source)
    return {"months": months, "first_gap": first_gap, "worst": worst, "late": late, "sources": per_source,
            "budget": budget, "spent": spent, "total_sources": total_src, "confirmed": confirmed, "received": received,
            "shortfall": max(budget - total_src, 0), "coverage": round(100 * total_src / budget) if budget else None,
            "cash": received - spent}


def debt(profile, sources):
    """Mensualites des credits et taux d'endettement, si les revenus sont connus."""
    if not profile:
        return None
    income = to_xof(profile["monthly_income"], profile["income_currency"], profile["fx_rate"])
    charges = to_xof(profile["other_charges"] or 0, profile["income_currency"], profile["fx_rate"]) or 0
    loans = sum(loan_payment(s) for s in sources if s["kind"] in LOAN_KINDS)
    if not income:
        return {"income": None, "loans": loans, "charges": charges, "ratio": None}
    ratio = round(100 * (loans + charges) / income, 1)
    return {"income": income, "loans": loans, "charges": charges, "ratio": ratio, "over": ratio > DEBT_REFERENCE,
            "room": max(round(income * DEBT_REFERENCE / 100) - loans - charges, 0)}


# --------------------------------------------------------------------------
# Dossier de credit
# --------------------------------------------------------------------------
DOC_KINDS = {
    "identite": t("Pièce d'identité ou passeport", "ID card or passport"),
    "bulletins": t("3 derniers bulletins de salaire", "Last 3 payslips"),
    "contrat": t("Contrat de travail ou attestation d'emploi", "Employment contract or certificate"),
    "impots": t("Dernier avis d'imposition", "Latest tax notice"),
    "releves": t("Relevés bancaires des 6 derniers mois", "Bank statements for the last 6 months"),
    "residence": t("Titre de séjour ou justificatif de domicile à l'étranger", "Residence permit or proof of address abroad"),
    "titre": t("Titre foncier, ACD ou acte du terrain", "Land title, ACD or land deed"),
    "permis": t("Permis de construire", "Building permit"),
    "apport": t("Justificatif de l'apport personnel", "Proof of personal contribution"),
    "credits": t("Tableaux d'amortissement des crédits en cours", "Repayment schedules of current loans"),
    "autre": t("Autre pièce", "Other document"),
}
CHECKLIST = [
    # (id, libelle, section, obligatoire, diaspora seulement, pieces acceptees, controle automatique)
    ("identite", DOC_KINDS["identite"], "emprunteur", True, False, ("identite",), None),
    ("residence", DOC_KINDS["residence"], "emprunteur", False, True, ("residence",), None),
    ("bulletins", DOC_KINDS["bulletins"], "revenus", True, False, ("bulletins",), None),
    ("contrat", DOC_KINDS["contrat"], "revenus", True, False, ("contrat",), None),
    ("impots", DOC_KINDS["impots"], "revenus", False, False, ("impots",), None),
    ("releves", DOC_KINDS["releves"], "revenus", True, False, ("releves",), None),
    ("credits", DOC_KINDS["credits"], "revenus", False, False, ("credits",), "has_other_charges"),
    ("titre", DOC_KINDS["titre"], "projet", True, False, ("titre",), None),
    ("permis", DOC_KINDS["permis"], "projet", True, False, ("permis",), "permit"),
    ("plans", t("Plans du bâtiment", "Building drawings"), "projet", True, False, (), "plans"),
    ("devis", t("Devis de l'entrepreneur", "Contractor's quote"), "projet", True, False, (), "devis"),
    ("budget", t("Budget détaillé par étape", "Budget broken down by stage"), "projet", True, False, (), "budget"),
    ("planning", t("Planning des travaux", "Works schedule"), "projet", True, False, (), "planning"),
    ("financement", t("Plan de financement", "Financing plan"), "financement", True, False, (), "sources"),
    ("apport", DOC_KINDS["apport"], "financement", True, False, ("apport",), None),
    ("avancement", t("Avancement prouvé du chantier (pour débloquer une tranche)", "Proven site progress (to release a tranche)"),
     "financement", False, False, (), "progress"),
]
SECTIONS = {"emprunteur": t("Emprunteur", "Borrower"), "revenus": t("Revenus et charges", "Income and expenses"),
            "projet": t("Projet et terrain", "Project and land"), "financement": t("Financement", "Financing")}


def checklist(lang, docs_by_kind, auto, diaspora):
    """Etat de chaque piece : fournie (fichier ou donnee de ChantierVrai) ou manquante, dans l'ordre des sections."""
    out = []
    for cid, label, section, required, dias_only, kinds, auto_key in CHECKLIST:
        if dias_only and not diaspora:
            continue
        files = [d for k in kinds for d in docs_by_kind.get(k, [])]
        auto_ok = bool(auto.get(auto_key)) if auto_key else False
        if auto_key == "has_other_charges":
            required, auto_ok = bool(auto.get(auto_key)), False
        out.append({"id": cid, "label": _p(label, lang), "section": section, "section_label": _p(SECTIONS[section], lang),
                    "required": required, "files": files, "auto": auto_ok, "ok": bool(files) or auto_ok,
                    "upload_kind": kinds[0] if kinds else None})
    order = list(SECTIONS)
    return sorted(out, key=lambda x: order.index(x["section"]))


def sections(items):
    """[(libelle de section, [pieces])] dans l'ordre emprunteur, revenus, projet, financement."""
    out = []
    for it in items:
        if not out or out[-1][0] != it["section_label"]:
            out.append((it["section_label"], []))
        out[-1][1].append(it)
    return out


def label(d, lang):
    return _p(d, lang)


def month_label(k, lang="fr"):
    names = {"fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
             "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
    return f"{names.get(lang, names['fr'])[int(k[5:7]) - 1]} {k[:4]}"


def today_iso():
    return datetime.utcnow().date().isoformat()
