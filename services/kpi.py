"""Pilotage de l'activité : chiffres clés, évolutions sur 12 mois, entonnoir, points à surveiller.

Toutes les dates de la base sont des textes ISO en UTC : les comparaisons et les découpages par mois
(substr(…, 1, 7)) marchent à l'identique sur SQLite et PostgreSQL.
"""
from datetime import datetime, timedelta, timezone

from services import billing as BILL

PERIODS = {"30": 30, "90": 90, "365": 365}


def _iso(d):
    return d.isoformat(timespec="seconds")


def months_back(n=12, now=None):
    now = now or datetime.now(timezone.utc)
    y, m = now.year, now.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def _one(db, q, args=()):
    r = db.execute(q, args).fetchone()
    return (r[0] or 0) if r else 0


def _by_month(db, q, args, months):
    got = {r[0]: (r[1] or 0) for r in db.execute(q, args).fetchall()}
    return [int(got.get(m, 0)) for m in months]


def revenue(db, start, end):
    """Encaissé HT : factures payées (abonnements, inspections) + commissions sur les matériaux reçus."""
    inv = _one(db, "SELECT SUM(amount_ht) FROM billing_invoices WHERE status = 'payee' AND paid_at >= ? AND paid_at < ?", (start, end))
    com = _one(db, "SELECT SUM(commission) FROM orders WHERE status = 'receptionnee' AND received_at >= ? AND received_at < ?",
               (start, end))
    return int(inv), int(com)


def mrr(db, prices):
    """Revenu mensuel récurrent : abonnements actifs ramenés au mois (prix sur mesure compris)."""
    total, n = 0, 0
    for s in db.execute("SELECT plan, custom_price FROM subscriptions WHERE status = 'actif'").fetchall():
        if s["plan"] not in BILL.PAID_PLANS:
            continue
        p = BILL.monthly_price(s["plan"], prices, s["custom_price"])
        if p:
            total += p
            n += 1
    return total, n


def tiles(db, days, prices, now=None):
    """Chiffres de la période et de la période précédente de même durée."""
    now = now or datetime.now(timezone.utc)
    end, start = _iso(now), _iso(now - timedelta(days=days))
    pstart = _iso(now - timedelta(days=2 * days))

    def both(fn):
        return fn(start, end), fn(pstart, start)

    def rev(a, b):
        i, c = revenue(db, a, b)
        return i + c

    def money(a, b):
        return int(_one(db, "SELECT SUM(amount) FROM steps WHERE paid_at >= ? AND paid_at < ?", (a, b)))

    def clients(a, b):
        return _one(db, "SELECT COUNT(*) FROM users WHERE role IN ('proprio', 'pro') AND created_at >= ? AND created_at < ?", (a, b))

    def proofs(a, b):
        return _one(db, "SELECT COUNT(*) FROM proofs WHERE created_at >= ? AND created_at < ?", (a, b))

    def active(a, b):
        return _one(db, "SELECT COUNT(DISTINCT project_id) FROM proofs WHERE created_at >= ? AND created_at < ?", (a, b))

    m, n_paid = mrr(db, prices)
    out = [
        {"key": "revenue", "label": "Chiffre d'affaires encaissé", "unit": "FCFA HT", "money": True, "v": both(rev),
         "hint": "Abonnements, inspections et commissions sur les matériaux"},
        {"key": "mrr", "label": "Revenu mensuel récurrent", "unit": "FCFA HT / mois", "money": True, "v": (m, None),
         "hint": "%(n)s abonnement(s) payant(s) actif(s)", "hint_n": n_paid},
        {"key": "money", "label": "Argent suivi sur les chantiers", "unit": "FCFA", "money": True, "v": both(money),
         "hint": "Étapes payées sur la période"},
        {"key": "active", "label": "Chantiers actifs", "unit": "", "v": both(active),
         "hint": "Au moins une preuve reçue sur la période"},
        {"key": "clients", "label": "Nouveaux clients", "unit": "", "v": both(clients),
         "hint": "Propriétaires et professionnels inscrits"},
        {"key": "proofs", "label": "Preuves reçues", "unit": "", "v": both(proofs),
         "hint": "Photos et vidéos des chantiers"},
    ]
    for t in out:
        cur, prev = t["v"]
        t["cur"], t["prev"] = cur, prev
        t["delta"] = None if prev in (None, 0) else round(100 * (cur - prev) / prev)
        t["new"] = prev == 0 and cur > 0
    return out


def trends(db, now=None):
    """Séries mensuelles sur 12 mois."""
    months = months_back(12, now)
    first = months[0] + "-01"
    inv = _by_month(db, "SELECT substr(paid_at, 1, 7), SUM(amount_ht) FROM billing_invoices WHERE status = 'payee' AND paid_at >= ? "
                        "GROUP BY substr(paid_at, 1, 7)", (first,), months)
    com = _by_month(db, "SELECT substr(received_at, 1, 7), SUM(commission) FROM orders WHERE status = 'receptionnee' "
                        "AND received_at >= ? GROUP BY substr(received_at, 1, 7)", (first,), months)
    money = _by_month(db, "SELECT substr(paid_at, 1, 7), SUM(amount) FROM steps WHERE paid_at >= ? GROUP BY substr(paid_at, 1, 7)",
                      (first,), months)
    clients = _by_month(db, "SELECT substr(created_at, 1, 7), COUNT(*) FROM users WHERE role IN ('proprio', 'pro') "
                            "AND created_at >= ? GROUP BY substr(created_at, 1, 7)", (first,), months)
    active = _by_month(db, "SELECT substr(created_at, 1, 7), COUNT(DISTINCT project_id) FROM proofs WHERE created_at >= ? "
                           "GROUP BY substr(created_at, 1, 7)", (first,), months)
    return {"months": months, "revenue": [a + b for a, b in zip(inv, com)], "rev_inv": inv, "rev_com": com,
            "money": money, "clients": clients, "active": active}


def funnel(db, days=None, now=None):
    """Du compte au premier paiement suivi, pour les propriétaires inscrits (sur la période si donnée)."""
    now = now or datetime.now(timezone.utc)
    cond, args = "", ()
    if days:
        cond, args = " AND u.created_at >= ?", (_iso(now - timedelta(days=days)),)
    base = "FROM users u WHERE u.role IN ('proprio', 'pro')" + cond
    n_users = _one(db, "SELECT COUNT(*) " + base, args)
    n_site = _one(db, "SELECT COUNT(*) " + base + " AND EXISTS (SELECT 1 FROM projects p WHERE p.owner_id = u.id)", args)
    n_proof = _one(db, "SELECT COUNT(*) " + base + " AND EXISTS (SELECT 1 FROM projects p JOIN proofs pr ON pr.project_id = p.id "
                       "WHERE p.owner_id = u.id)", args)
    n_paid = _one(db, "SELECT COUNT(*) " + base + " AND EXISTS (SELECT 1 FROM projects p JOIN steps s ON s.project_id = p.id "
                      "WHERE p.owner_id = u.id AND s.paid_at IS NOT NULL)", args)
    n_sub = _one(db, "SELECT COUNT(*) " + base + " AND EXISTS (SELECT 1 FROM subscriptions s WHERE s.user_id = u.id "
                     "AND s.status = 'actif' AND s.plan IN ('essentiel', 'pro', 'entreprise'))", args)
    rows = [("Comptes créés", n_users), ("Chantier créé", n_site), ("Première preuve reçue", n_proof),
            ("Première étape payée", n_paid), ("Abonnement payant", n_sub)]
    top = max(n_users, 1)
    return [{"label": l, "n": n, "pct": round(100 * n / top), "step": (round(100 * n / rows[i - 1][1]) if i and rows[i - 1][1] else None)}
            for i, (l, n) in enumerate(rows)]


def watch(db, now=None):
    """Ce qui mérite un coup d'œil : chantiers silencieux, validations qui traînent, impayés, litiges."""
    now = now or datetime.now(timezone.utc)
    d14, d7, today = _iso(now - timedelta(days=14)), _iso(now - timedelta(days=7)), now.date().isoformat()
    silent = db.execute(
        "SELECT p.id, p.name, MAX(pr.created_at) AS last FROM projects p "
        "JOIN steps s ON s.project_id = p.id AND s.status IN ('en_cours', 'attente') "
        "LEFT JOIN proofs pr ON pr.project_id = p.id GROUP BY p.id, p.name "
        "HAVING MAX(pr.created_at) IS NULL OR MAX(pr.created_at) < ? ORDER BY last LIMIT 8", (d14,)).fetchall()
    waiting = db.execute(
        "SELECT p.id, p.name, s.name AS step, s.declared_at FROM steps s JOIN projects p ON p.id = s.project_id "
        "WHERE s.status = 'declare' AND s.declared_at < ? ORDER BY s.declared_at LIMIT 8", (d7,)).fetchall()
    unpaid = db.execute(
        "SELECT i.number, i.amount, i.due_date, u.name FROM billing_invoices i JOIN users u ON u.id = i.user_id "
        "WHERE i.status = 'a_payer' AND i.due_date < ? ORDER BY i.due_date LIMIT 8", (today,)).fetchall()
    disputes = _one(db, "SELECT COUNT(*) FROM disputes WHERE status NOT IN ('clos', 'resolu')")
    return {"silent": silent, "waiting": waiting, "unpaid": unpaid, "disputes": disputes}


def top_projects(db, days, now=None):
    now = now or datetime.now(timezone.utc)
    return db.execute(
        "SELECT p.id, p.name, SUM(s.amount) AS paid, COUNT(*) AS n FROM steps s JOIN projects p ON p.id = s.project_id "
        "WHERE s.paid_at >= ? GROUP BY p.id, p.name ORDER BY paid DESC LIMIT 5", (_iso(now - timedelta(days=days)),)).fetchall()


def bars(values, labels, width=640, height=200, pad_left=8, pad_bottom=26, pad_top=18):
    """Géométrie d'un histogramme : barres fines, arrondies en haut, partant de la ligne de base."""
    n = max(len(values), 1)
    top = max(values) if values and max(values) > 0 else 1
    step = (width - pad_left) / n
    bw = max(6, min(36, step * 0.56))
    plot_h = height - pad_bottom - pad_top
    out = []
    for i, (v, lab) in enumerate(zip(values, labels)):
        h = 0 if v <= 0 else max(3, plot_h * v / top)
        x = pad_left + i * step + (step - bw) / 2
        out.append({"x": round(x, 1), "y": round(height - pad_bottom - h, 1), "w": round(bw, 1), "h": round(h, 1),
                    "v": v, "label": lab, "cx": round(pad_left + i * step + step / 2, 1), "col_x": round(pad_left + i * step, 1),
                    "col_w": round(step, 1)})
    return {"bars": out, "w": width, "h": height, "base": height - pad_bottom, "top": top, "pad_top": pad_top}


def line(values, labels, width=640, height=200, pad_left=8, pad_bottom=26, pad_top=18):
    g = bars(values, labels, width, height, pad_left, pad_bottom, pad_top)
    plot_h = height - pad_bottom - pad_top
    pts = []
    for b in g["bars"]:
        y = height - pad_bottom - (plot_h * b["v"] / g["top"] if g["top"] else 0)
        b["py"] = round(y, 1)
        pts.append(f"{b['cx']},{b['py']}")
    g["points"] = " ".join(pts)
    return g
