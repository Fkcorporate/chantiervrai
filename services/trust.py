"""Indice de confiance du chantier.

Un score de 0 a 100 qui resume la maitrise du chantier a partir de six criteres mesurables.
Chaque critere donne son score, la raison et ce qu'il faut faire. Un critere sans donnees est
ecarte du calcul et l'indique. Ce n'est pas une certification technique.
"""
from .i18n import L

CRITERIA = [
    # cle, poids, titre
    ("avancement", 20, L("Avancement vérifié")),
    ("calendrier", 15, L("Respect du calendrier")),
    ("depenses", 20, L("Justification des dépenses")),
    ("preuves", 15, L("Disponibilité des preuves")),
    ("procedures", 15, L("Respect des procédures de contrôle")),
    ("conformite", 15, L("Conformité technique documentée")),
]


def clamp(x):
    return max(0, min(100, round(x)))


def compute(d):
    """d : dictionnaire de mesures preparees par l'application (voir trust_inputs dans app.py).
    Retourne {"score", "level", "level_label", "criteria": [...], "used": n}."""
    out = []

    # 1. Avancement verifie : ce qui est declare doit etre prouve et valide
    if d["declared_pct"] or d["verified_pct"]:
        gap = max(0, d["declared_pct"] - d["verified_pct"])
        stale = d.get("stale_pct", gap)
        sc = 100 - stale * 2 - min(30, d["ai_doubtful"] * 10)
        why = L("%(v)s %% vérifié pour %(d)s %% déclaré.", v=d["verified_pct"], d=d["declared_pct"])
        if stale:
            why = why + L(" Des étapes déclarées attendent leur vérification depuis plus de 7 jours.")
        elif gap:
            why = why + L(" Une étape déclarée attend votre vérification.")
        if d["ai_doubtful"]:
            why = why + L(" %(n)s photo(s) douteuse(s) selon l'IA.", n=d["ai_doubtful"])
        tip = L("Validez les étapes déclarées après avoir regardé les preuves.") if gap else None
        out.append(("avancement", clamp(sc), why, tip))
    else:
        out.append(("avancement", None, L("Aucune étape déclarée pour l'instant."), None))

    # 2. Calendrier
    if d["delay"] is None:
        out.append(("calendrier", None, L("Pas de planning : indiquez la date de début et la durée des étapes."), None))
    else:
        sc = 100 if d["delay"] <= 0 else 100 - d["delay"] * 2
        why = L("Fin prévue à l'heure.") if d["delay"] <= 0 else L("Retard prévu de %(n)s jours.", n=d["delay"])
        out.append(("calendrier", clamp(sc), why, L("Demandez un plan de rattrapage au chef de chantier.") if d["delay"] > 7 else None))

    # 3. Depenses justifiees : materiaux prevus, factures, stock coherent
    if not d["has_material_data"]:
        out.append(("depenses", None, L("Aucun prévu de matériaux ni facture : les dépenses ne peuvent pas être rapprochées."),
                    L("Utilisez le calculateur pour remplir le prévu des étapes.")))
    else:
        n = d["material_alerts"] + d["stock_alerts"]
        sc = 100 - 15 * n - (10 if d["unpaid_orders"] else 0)
        why = L("Factures, livraisons et consommations concordent.") if n == 0 else \
            L("%(n)s écart(s) entre prévu, acheté, livré et utilisé.", n=n)
        out.append(("depenses", clamp(sc), why, L("Ouvrez le stock et le contrôle des matériaux pour voir les écarts.") if n else None))

    # 4. Preuves recentes et acceptees
    if d["proofs_total"] == 0:
        out.append(("preuves", 0 if d["started"] else None,
                    L("Aucune preuve envoyée.") if d["started"] else L("Le chantier n'a pas commencé."),
                    L("Le chef de chantier doit envoyer des photos depuis l'application.") if d["started"] else None))
    else:
        age = d["days_silent"] if d["days_silent"] is not None else 0
        sc = 100 if age <= 7 else 70 if age <= 14 else 40 if age <= 30 else 10
        sc -= round(d["refused"] * 100 / d["proofs_total"] * 0.5)
        why = L("Dernière preuve il y a %(n)s jour(s), %(r)s refusée(s) sur %(t)s.", n=age, r=d["refused"], t=d["proofs_total"])
        out.append(("preuves", clamp(sc), why, L("Demandez des photos récentes du chantier.") if age > 7 else None))

    # 5. Procedures de controle respectees
    if not d["checks_total"]:
        out.append(("procedures", None, L("Aucun point de contrôle sur les étapes."), None))
    else:
        sc = 100 - 30 * d["paid_without_checks"] - 10 * d["checks_made_optional"] - 5 * d["checks_overdue"]
        if d["paid_without_checks"]:
            why = L("%(n)s étape(s) payée(s) sans tous les contrôles obligatoires.", n=d["paid_without_checks"])
        elif d["checks_made_optional"]:
            why = L("%(n)s contrôle(s) rendu(s) facultatif(s) par le propriétaire.", n=d["checks_made_optional"])
        elif d["checks_overdue"]:
            why = L("%(n)s contrôle(s) obligatoire(s) en attente sur des étapes déclarées.", n=d["checks_overdue"])
        else:
            why = L("Les contrôles obligatoires sont faits avant chaque paiement.")
        tip = L("Faites passer un contrôleur habilité avant de valider.") if sc < 100 else None
        out.append(("procedures", clamp(sc), why, tip))

    # 6. Conformite technique documentee (controles, inspections, controle qualite des photos, plan et realite)
    documented = d["checks_done"] + d["inspections_done"] + d.get("quality_reviews", 0)
    qp, qc, pg = d.get("quality_problems", 0), d.get("quality_critical", 0), d.get("plan_gaps", 0)
    if not documented:
        out.append(("conformite", 50 if d["started"] else None,
                    L("Aucun contrôle technique documenté.") if d["started"] else L("Le chantier n'a pas commencé."),
                    L("Réservez un inspecteur indépendant ou ajoutez votre bureau de contrôle.") if d["started"] else None))
    else:
        sc = (100 - 25 * d["checks_nonconform"] - 30 * d["inspections_nc"] - 10 * d["inspections_reserves"]
              - 25 * qc - 10 * (qp - qc) - 10 * pg)
        bad = d["checks_nonconform"] + d["inspections_nc"]
        why = L("%(n)s contrôle(s) documenté(s), tous conformes.", n=documented) if not (bad or qp or pg) else \
            L("%(n)s non-conformité(s) relevée(s) sur %(t)s contrôle(s).", n=bad, t=documented)
        if qp:
            why = why + L(" %(n)s problème(s) probable(s) non résolu(s) au contrôle qualité.", n=qp)
        if pg:
            why = why + L(" %(n)s écart(s) entre le plan et le chantier.", n=pg)
        out.append(("conformite", clamp(sc), why, L("Faites corriger puis contrôler à nouveau.") if (bad or qp or pg) else None))

    weights = {k: w for k, w, _t in CRITERIA}
    titles = {k: t for k, _w, t in CRITERIA}
    used = [(k, s) for k, s, _w, _t in out if s is not None]
    total_w = sum(weights[k] for k, _s in used)
    score = round(sum(weights[k] * s for k, s in used) / total_w) if total_w else None
    if score is not None and (d.get("quality_critical") or d.get("paid_without_checks")):
        score = min(score, 79)           # un probleme de solidite ouvert interdit « bonne maitrise »
    if score is None:
        level, label = "none", L("Pas encore assez de données")
    elif score >= 80:
        level, label = "good", L("Bonne maîtrise du chantier")
    elif score >= 60:
        level, label = "medium", L("Maîtrise moyenne : des points à surveiller")
    else:
        level, label = "low", L("Maîtrise faible : intervenez")
    return {"score": score, "level": level, "level_label": label, "used": len(used),
            "criteria": [{"key": k, "title": titles[k], "weight": weights[k], "score": s, "why": why, "tip": tip}
                         for k, s, why, tip in out]}
