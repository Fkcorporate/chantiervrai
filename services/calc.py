"""Calculateur de materiaux et de dosages.

Donne des quantites d'achat a partir des dimensions, avec les pertes. Les dosages sont des valeurs
courantes de chantier, a titre indicatif : la formulation du beton structurel, les dimensions des
elements porteurs et le ferraillage viennent des etudes techniques et sont valides par un ingenieur.
"""
import math

from .i18n import _, L

SAC_KG = 50          # sac de ciment
BARRE_M = 12         # barre de fer a beton

# Dosages par m3 de beton : ciment (kg), sable (m3), gravier (m3), eau (L)
BETON = {
    "350": {"label": L("350 kg/m³ : béton armé (poteaux, poutres, dalles)"), "ciment": 350, "sable": 0.40, "gravier": 0.80, "eau": 175},
    "300": {"label": L("300 kg/m³ : semelles, longrines, dallage"), "ciment": 300, "sable": 0.45, "gravier": 0.80, "eau": 165},
    "250": {"label": L("250 kg/m³ : béton non armé, regards"), "ciment": 250, "sable": 0.50, "gravier": 0.80, "eau": 150},
    "150": {"label": L("150 kg/m³ : béton de propreté"), "ciment": 150, "sable": 0.50, "gravier": 0.85, "eau": 120},
}
# Mortiers par m3 : ciment (kg), sable (m3), eau (L)
MORTIER = {"pose": {"ciment": 350, "sable": 1.10, "eau": 200}, "enduit": {"ciment": 400, "sable": 1.05, "eau": 210}}
# Parpaings creux 40 x 20 : nombre au m2, mortier de pose au m2 (m3), parpaings par sac pour la fabrication
PARPAING = {"10": {"m2": 12.5, "mortier": 0.010, "par_sac": 45}, "15": {"m2": 12.5, "mortier": 0.015, "par_sac": 35},
            "20": {"m2": 12.5, "mortier": 0.020, "par_sac": 28}}
SABLE_PAR_SAC_PARPAING = 0.30     # m3 de sable par sac de ciment pour fabriquer des parpaings
EAU_PAR_SAC_PARPAING = 25         # litres
# Masse lineique du fer HA (kg/m)
FER = {"6": 0.222, "8": 0.395, "10": 0.617, "12": 0.888, "14": 1.208, "16": 1.578, "20": 2.466, "25": 3.853}

ELEMENTS = {"poteau": L("Poteaux"), "poutre": L("Poutres"), "dalle": L("Dalle"), "semelle": L("Semelles isolées"),
            "longrine": L("Longrines"), "autre": L("Autre élément")}

TYPES = {
    "beton": {
        "title": L("Béton"), "hint": L("Poteaux, poutres, dalles, semelles : volume, ciment, sable, gravier et eau."),
        "fields": [("element", L("Élément"), "poteau", ELEMENTS), ("count", L("Nombre d'éléments"), "1", None),
                   ("long", L("Longueur ou hauteur (m)"), "3", None), ("larg", L("Largeur (m)"), "0.2", None),
                   ("haut", L("Épaisseur ou profondeur (m)"), "0.2", None),
                   ("dosage", L("Dosage"), "350", {k: v["label"] for k, v in BETON.items()}),
                   ("pertes", L("Pertes (%)"), "5", None)],
    },
    "fondation": {
        "title": L("Fondations"), "hint": L("Semelles filantes : terre à creuser, béton de propreté et béton de la semelle."),
        "fields": [("long", L("Longueur totale des semelles (m)"), "60", None), ("larg", L("Largeur de semelle (m)"), "0.6", None),
                   ("haut", L("Hauteur de semelle (m)"), "0.3", None), ("prof", L("Profondeur de fouille (m)"), "0.8", None),
                   ("prop", L("Épaisseur du béton de propreté (m)"), "0.05", None),
                   ("dosage", L("Dosage de la semelle"), "300", {k: v["label"] for k, v in BETON.items() if k != "150"}),
                   ("pertes", L("Pertes (%)"), "5", None)],
    },
    "fer": {
        "title": L("Fer à béton"), "hint": L("Poids et nombre de barres de 12 m à partir des longueurs du plan de ferraillage."),
        "fields": [("diam", L("Diamètre"), "10", {k: f"HA {k}" for k in FER}),
                   ("lng", L("Longueur totale de ce diamètre (m)"), "240", None),
                   ("diam2", L("Second diamètre (facultatif)"), "", {"": "–", **{k: f"HA {k}" for k in FER}}),
                   ("lng2", L("Longueur totale du second diamètre (m)"), "", None),
                   ("pertes", L("Pertes et recouvrements (%)"), "10", None)],
    },
    "maconnerie": {
        "title": L("Maçonnerie"), "hint": L("Murs en parpaings : nombre de parpaings et mortier de pose."),
        "fields": [("long", L("Longueur des murs (m)"), "40", None), ("haut", L("Hauteur des murs (m)"), "3", None),
                   ("ouv", L("Surface des ouvertures à déduire (m²)"), "10", None),
                   ("parpaing", L("Parpaing"), "15", {"10": L("Creux de 10"), "15": L("Creux de 15"), "20": L("Creux de 20")}),
                   ("pertes", L("Pertes (%)"), "5", None)],
    },
    "parpaings": {
        "title": L("Fabrication de parpaings"), "hint": L("Ciment, sable et eau pour fabriquer vos parpaings sur place."),
        "fields": [("nombre", L("Nombre de parpaings"), "1000", None),
                   ("parpaing", L("Parpaing"), "15", {"10": L("Creux de 10"), "15": L("Creux de 15"), "20": L("Creux de 20")}),
                   ("pertes", L("Casse (%)"), "5", None)],
    },
    "enduit": {
        "title": L("Enduit"), "hint": L("Mortier d'enduit pour les murs, sur une ou deux faces."),
        "fields": [("surface", L("Surface de mur (m²)"), "100", None), ("faces", L("Nombre de faces"), "2", None),
                   ("ep", L("Épaisseur (cm)"), "1.5", None), ("pertes", L("Pertes (%)"), "10", None)],
    },
    "carrelage": {
        "title": L("Carrelage"), "hint": L("Surface de carreaux à acheter et mortier de pose."),
        "fields": [("long", L("Longueur de la pièce (m)"), "5", None), ("larg", L("Largeur de la pièce (m)"), "4", None),
                   ("pieces", L("Nombre de pièces identiques"), "1", None), ("pertes", L("Coupes et casse (%)"), "10", None)],
    },
    "peinture": {
        "title": L("Peinture"), "hint": L("Litres de peinture selon la surface, le nombre de couches et le rendement."),
        "fields": [("surface", L("Surface à peindre (m²)"), "200", None), ("couches", L("Nombre de couches"), "2", None),
                   ("rend", L("Rendement (m² par litre et par couche)"), "10", None), ("pertes", L("Pertes (%)"), "5", None)],
    },
}


def num(v, default=0.0):
    try:
        x = float(str(v).replace(",", ".").replace(" ", ""))
        return x if math.isfinite(x) and x >= 0 else default
    except (TypeError, ValueError):
        return default


def up(x, step=0.1):
    """Arrondi a l'achat : toujours vers le haut."""
    return round(math.ceil(round(x / step, 6)) * step, 3)


def _concrete(vol, dosage):
    d = BETON.get(dosage, BETON["350"])
    return [("Ciment", "sac", math.ceil(vol * d["ciment"] / SAC_KG)), ("Sable", "m³", up(vol * d["sable"])),
            ("Gravier", "m³", up(vol * d["gravier"])), ("Eau", "L", math.ceil(vol * d["eau"]))]


def compute(kind, form):
    """Retourne {"lines": [(materiau, unite, quantite)], "details": [(libelle, valeur)], "notes": [...]}
    ou None si le type est inconnu. Les quantites incluent les pertes."""
    if kind not in TYPES:
        return None
    f = {k: form.get(k, dflt) for k, _l, dflt, _o in TYPES[kind]["fields"]}
    k_loss = 1 + min(num(f.get("pertes"), 0), 50) / 100
    lines, details, notes = [], [], []
    if kind == "beton":
        n = max(1, int(num(f["count"], 1)))
        vol = n * num(f["long"]) * num(f["larg"]) * num(f["haut"])
        details.append((_("Volume de béton"), f"{vol:.2f} m³"))
        lines = _concrete(vol * k_loss, f["dosage"])
        notes.append(_("Dosage courant à titre indicatif. Pour le béton armé, suivez la formulation et les dimensions de l'étude de structure."))
    elif kind == "fondation":
        lg, lr, h, pr, ep = (num(f[x]) for x in ("long", "larg", "haut", "prof", "prop"))
        fouille = lg * (lr + 0.2) * pr
        propre = lg * lr * ep
        semelle = lg * lr * h
        details += [(_("Terre à creuser"), f"{fouille:.1f} m³"), (_("Béton de propreté"), f"{propre:.2f} m³"),
                    (_("Béton de semelle"), f"{semelle:.2f} m³")]
        merged = {}
        for mat, unit, q in _concrete(propre * k_loss, "150") + _concrete(semelle * k_loss, f["dosage"]):
            merged[(mat, unit)] = merged.get((mat, unit), 0) + q
        lines = [(m, u, up(q) if u == "m³" else q) for (m, u), q in merged.items()]
        notes.append(_("Fouille comptée 10 cm plus large de chaque côté. Les dimensions des fondations viennent de l'étude de sol et de structure."))
    elif kind == "fer":
        total_kg, bars = 0.0, 0
        for dk, lk in (("diam", "lng"), ("diam2", "lng2")):
            d, length = f.get(dk), num(f.get(lk))
            if d in FER and length > 0:
                kg = length * k_loss * FER[d]
                n = math.ceil(length * k_loss / BARRE_M)
                total_kg += kg
                bars += n
                details.append((f"HA {d}", _("%(n)s barres de 12 m, %(kg)s kg", n=n, kg=round(kg))))
                lines.append(("Fer à béton", "barre", n))
        if len(lines) > 1:
            lines = [("Fer à béton", "barre", bars)]
        details.append((_("Poids total"), f"{round(total_kg)} kg"))
        notes.append(_("Les diamètres et longueurs viennent du plan de ferraillage établi par l'ingénieur."))
    elif kind == "maconnerie":
        t = PARPAING.get(f["parpaing"], PARPAING["15"])
        surf = max(0.0, num(f["long"]) * num(f["haut"]) - num(f["ouv"]))
        mortar = surf * t["mortier"] * k_loss
        m = MORTIER["pose"]
        details += [(_("Surface de mur"), f"{surf:.1f} m²"), (_("Mortier de pose"), f"{mortar:.2f} m³")]
        lines = [("Parpaings", "unité", math.ceil(surf * t["m2"] * k_loss)),
                 ("Ciment", "sac", math.ceil(mortar * m["ciment"] / SAC_KG)),
                 ("Sable", "m³", up(mortar * m["sable"])), ("Eau", "L", math.ceil(mortar * m["eau"]))]
    elif kind == "parpaings":
        t = PARPAING.get(f["parpaing"], PARPAING["15"])
        n = num(f["nombre"]) * k_loss
        sacs = math.ceil(n / t["par_sac"])
        details.append((_("Rendement"), _("%(n)s parpaings par sac de ciment", n=t["par_sac"])))
        lines = [("Ciment", "sac", sacs), ("Sable", "m³", up(sacs * SABLE_PAR_SAC_PARPAING)),
                 ("Eau", "L", math.ceil(sacs * EAU_PAR_SAC_PARPAING))]
        notes.append(_("Laissez sécher les parpaings à l'ombre et arrosez-les pendant 7 jours avant de les poser."))
    elif kind == "enduit":
        vol = num(f["surface"]) * max(1, num(f["faces"], 1)) * num(f["ep"], 1.5) / 100 * k_loss
        m = MORTIER["enduit"]
        details.append((_("Mortier d'enduit"), f"{vol:.2f} m³"))
        lines = [("Ciment", "sac", math.ceil(vol * m["ciment"] / SAC_KG)), ("Sable", "m³", up(vol * m["sable"])),
                 ("Eau", "L", math.ceil(vol * m["eau"]))]
    elif kind == "carrelage":
        surf = num(f["long"]) * num(f["larg"]) * max(1, num(f["pieces"], 1))
        vol = surf * 0.03            # 3 cm de mortier de pose
        details += [(_("Surface au sol"), f"{surf:.1f} m²"), (_("Mortier de pose (3 cm)"), f"{vol:.2f} m³")]
        lines = [("Carreaux", "m²", up(surf * k_loss, 1)), ("Ciment", "sac", math.ceil(vol * k_loss * 300 / SAC_KG)),
                 ("Sable", "m³", up(vol * k_loss * 1.1))]
    elif kind == "peinture":
        rend = num(f["rend"], 10) or 10
        litres = num(f["surface"]) * max(1, num(f["couches"], 1)) / rend * k_loss
        details.append((_("Peinture"), f"{litres:.1f} L"))
        lines = [("Peinture", "L", math.ceil(litres))]
    lines = [(m, u, q) for m, u, q in lines if q]
    return {"lines": lines, "details": details, "notes": notes}
