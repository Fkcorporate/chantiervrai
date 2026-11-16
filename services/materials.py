"""Controle des materiaux : facture contre prevu, et prevu contre construit."""
import unicodedata

from .i18n import _

# Nom canonique -> mots qui le designent sur une facture
CATALOG = {
    "Ciment": ["ciment", "cpj", "cem", "sac de ciment"],
    "Fer à béton": ["fer", "acier", "ha8", "ha10", "ha12", "ha14", "ha16", "tor", "armature"],
    "Sable": ["sable"],
    "Gravier": ["gravier", "gravillon", "granulat", "concasse"],
    "Parpaings": ["parpaing", "agglo", "brique", "bloc"],
    "Bois de coffrage": ["bois", "planche", "chevron", "madrier", "coffrage"],
    "Tôles": ["tole", "bac acier", "couverture"],
    "Carreaux": ["carreau", "carrelage"],
    "Peinture": ["peinture", "enduit"],
    "Plomberie": ["tuyau", "pvc", "robinet", "plomberie"],
    "Électricité": ["cable", "fil electrique", "gaine", "disjoncteur", "electricite"],
}

OVER_QTY = 1.15     # alerte si la quantite facturee depasse le prevu de 15 %
OVER_PRICE = 1.20   # alerte si le prix unitaire depasse la reference de 20 %


def plain(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def normalize(name):
    p = plain(name)
    for canon, words in CATALOG.items():
        if any(w in p for w in words):
            return canon
    return (name or "").strip().capitalize()[:60] or "Autre"


def compare(plans, lines, steps):
    """plans : lignes materials_plan ; lines : lignes de facture (avec step_id) ;
    steps : etapes du chantier. Retourne (tableau, alertes)."""
    status = {s["id"]: s["status"] for s in steps}
    names = {s["id"]: s["name"] for s in steps}
    rows = {}
    for pl in plans:
        k = (pl["step_id"], pl["material"])
        rows[k] = {"step_id": pl["step_id"], "step": names.get(pl["step_id"], "?"), "material": pl["material"],
                   "unit": pl["unit"], "planned": pl["qty_planned"] or 0, "ref_price": pl["unit_price_ref"] or 0,
                   "invoiced": 0.0, "spent": 0.0, "max_price": 0.0}
    for ln in lines:
        k = (ln["step_id"], ln["material"])
        r = rows.setdefault(k, {"step_id": ln["step_id"], "step": names.get(ln["step_id"], "?"),
                                "material": ln["material"], "unit": ln["unit"], "planned": 0, "ref_price": 0,
                                "invoiced": 0.0, "spent": 0.0, "max_price": 0.0})
        r["invoiced"] += ln["qty"] or 0
        r["spent"] += (ln["qty"] or 0) * (ln["unit_price"] or 0)
        r["max_price"] = max(r["max_price"], ln["unit_price"] or 0)
    alerts = []
    for r in rows.values():
        st = status.get(r["step_id"])
        r["pct"] = round(r["invoiced"] * 100 / r["planned"]) if r["planned"] else None
        r["flags"] = []
        if r["planned"] and r["invoiced"] > r["planned"] * OVER_QTY:
            r["flags"].append(_("%(pct)s %% du prévu facturé", pct=r["pct"]))
        if not r["planned"] and r["invoiced"]:
            r["flags"].append(_("Matériau non prévu pour cette étape"))
        if r["ref_price"] and r["max_price"] > r["ref_price"] * OVER_PRICE:
            r["flags"].append(_("Prix jusqu'à %(pct)s %% de la référence", pct=round(r["max_price"] * 100 / r["ref_price"])))
        if st == "attente" and r["invoiced"]:
            r["flags"].append(_("Acheté pour une étape pas encore commencée"))
        if st == "paye" and r["planned"] and r["invoiced"] < r["planned"] * 0.6:
            r["flags"].append(_("Étape payée mais moins de 60 % des matériaux facturés"))
        for f in r["flags"]:
            alerts.append(f"{r['step']} · {_(r['material'])} : {f}")
    order = {s["id"]: s["position"] for s in steps}
    table = sorted(rows.values(), key=lambda r: (order.get(r["step_id"], 99), r["material"]))
    return table, alerts
