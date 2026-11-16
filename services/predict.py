"""Prediction des retards.

Methode : on mesure le rythme reel du chantier sur les etapes terminees
(duree reelle / duree prevue), on l'applique a ce qui reste, puis on ajoute
les signaux d'arret (aucune preuve depuis plusieurs jours, preuves refusees,
inspection non conforme). Le resultat est une estimation, pas une certitude :
plus il y a d'etapes terminees, plus elle est fiable.
"""
from datetime import date, datetime, timedelta, timezone

from .i18n import _


def _d(iso):
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def predict(project, steps, days_silent=None, refused=0, total_proofs=0, non_conforme=0, now=None):
    now = now or datetime.now(timezone.utc)
    if not project["start_date"] or not any(s["planned_days"] for s in steps):
        return None
    start = datetime.fromisoformat(project["start_date"]).replace(tzinfo=timezone.utc)
    planned_total = sum(s["planned_days"] or 0 for s in steps)
    planned_end = start + timedelta(days=planned_total)

    ratios, weights = [], []
    for s in steps:
        if s["status"] in ("declare", "paye") and s["planned_days"]:
            b, e = _d(s["started_at"]), _d(s["declared_at"] or s["paid_at"])
            if b and e:
                ratios.append(max((e - b).total_seconds() / 86400, 0.5) / s["planned_days"])
                weights.append(s["planned_days"])
    pace = sum(r * w for r, w in zip(ratios, weights)) / sum(weights) if weights else 1.0
    pace = min(max(pace, 0.6), 3.0)

    reasons = []
    if weights:
        if pace > 1.1:
            reasons.append(_('Les étapes terminées ont pris %(round)s %% de temps en plus que prévu', round=round((pace - 1) * 100)))
        elif pace < 0.95:
            reasons.append(_('Le chantier avance plus vite que prévu'))
    remaining = 0.0
    for s in steps:
        pd = s["planned_days"] or 0
        if s["status"] == "en_cours":
            b = _d(s["started_at"]) or now
            elapsed = (now - b).total_seconds() / 86400
            expected = pd * pace
            if elapsed > expected:
                reasons.append(_('« %(name)s » dépasse déjà sa durée de %(round)s jour(s)', name=s['name'], round=round(elapsed - pd)))
                remaining += max(pd * 0.15, 2)
            else:
                remaining += expected - elapsed
        elif s["status"] == "declare":
            remaining += 2                     # temps de validation
        elif s["status"] == "attente":
            remaining += pd * pace

    if days_silent is not None and days_silent > 7:
        remaining += days_silent - 7
        reasons.append(_("Aucune preuve depuis %(days_silent)s jours : chantier possiblement à l'arrêt", days_silent=days_silent))
    if total_proofs >= 4 and refused / total_proofs > 0.3:
        remaining *= 1.1
        reasons.append(_('%(refused)s preuves refusées sur %(total_proofs)s', refused=refused, total_proofs=total_proofs))
    if non_conforme:
        remaining += 10 * non_conforme
        reasons.append(_('Inspection non conforme : reprise de travaux probable'))

    done = all(s["status"] == "paye" for s in steps)
    if done:
        last = max((_d(s["paid_at"]) for s in steps if s["paid_at"]), default=now)
        predicted_end = last
    else:
        predicted_end = now + timedelta(days=remaining)
    delay = (predicted_end.date() - planned_end.date()).days
    if done:
        risk = "terminé"
    elif delay <= 7:
        risk = "faible"
    elif delay <= 30:
        risk = "moyen"
    else:
        risk = "élevé"
    return {
        "planned_end": planned_end.date(), "predicted_end": predicted_end.date(), "delay": delay,
        "risk": risk, "pace": round(pace, 2), "reasons": reasons, "done": done,
        "reliability": "faible" if len(weights) < 2 else ("moyenne" if len(weights) < 4 else "bonne"),
    }


def step_schedule(project, steps):
    """Dates de fin prevues par etape."""
    if not project["start_date"]:
        return {}
    d = date.fromisoformat(project["start_date"])
    out = {}
    for s in steps:
        d = d + timedelta(days=s["planned_days"] or 0)
        out[s["id"]] = d
    return out
