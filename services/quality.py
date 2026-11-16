"""Controle visuel de la qualite des ouvrages.

Pour chaque ouvrage (escalier, carrelage, douche...) :
- des prises de vue guidees (quoi photographier, a quel moment, avec quel instrument dans le cadre) ;
- une liste de points a controler, avec ce qu'il faut regarder sur la photo ;
- des mesures que le chef saisit (hauteur de chaque marche, pente de la douche...) controlees par des regles fixes,
  et relues par l'IA sur la photo de l'instrument quand elle est activee.

Trois sources, de la plus sure a la moins sure : mesure saisie et photographiee, avis d'un professionnel du chantier,
analyse de l'IA. Le resultat est une aide a la decision, jamais un verdict : les valeurs sont indicatives et les plans,
les normes locales et le bureau d'etudes priment.
"""
import io
import json
import re
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import env, http_json

API = "https://api.anthropic.com/v1/messages"
MAX_PHOTOS = 10                      # par analyse : au-dela, le cout et la precision se degradent
STATUSES = ("ok", "a_verifier", "probleme", "non_visible")
STATUS_LABEL = {"ok": {"fr": "Semble correct", "en": "Looks right"},
                "a_verifier": {"fr": "À vérifier", "en": "To check"},
                "probleme": {"fr": "Problème probable", "en": "Likely problem"},
                "non_visible": {"fr": "Pas visible sur les photos", "en": "Not visible on the photos"},
                "a_controler": {"fr": "À contrôler vous-même", "en": "Check it yourself"}}
SEVERITY = {"critique": 3, "majeur": 2, "mineur": 1}
SEVERITY_LABEL = {"critique": {"fr": "Sécurité ou solidité", "en": "Safety or strength"},
                  "majeur": {"fr": "Important", "en": "Important"},
                  "mineur": {"fr": "Finition", "en": "Finish"}}
SOURCE_LABEL = {"mesure": {"fr": "Mesure saisie", "en": "Measurement entered"},
                "ia": {"fr": "Analyse des photos par l'IA", "en": "AI photo analysis"},
                "expert": {"fr": "Avis d'un professionnel", "en": "Professional opinion"},
                "proprio": {"fr": "Contrôlé par le propriétaire", "en": "Checked by the owner"},
                "photo": {"fr": "Qualité des photos", "en": "Photo quality"}}


def t(fr, en):
    return {"fr": fr, "en": en}


def shot(id, label, hint, required=True, instrument=False):
    return {"id": id, "label": label, "hint": hint, "required": required, "instrument": instrument}


def point(id, label, look, severity="majeur", question=None):
    return {"id": id, "label": label, "look": look, "severity": severity, "question": question}


def measure(id, label, unit, rule, point, **kw):
    return dict(id=id, label=label, unit=unit, rule=rule, point=point, **kw)


YES_NO = [("oui", t("Oui", "Yes")), ("non", t("Non", "No"))]

OUVRAGES = [
    {"slug": "fondations", "keywords": ("fondation", "fouille", "semelle", "soubassement", "implantation"),
     "name": t("Fondations (fouilles et semelles)", "Foundations (trenches and footings)"),
     "moment": t("Avant le coulage du béton, fouilles ouvertes et ferraillage en place.",
                 "Before pouring concrete, with trenches open and reinforcement in place."),
     "shots": [shot("ensemble", t("Vue d'ensemble des fouilles", "Overview of the trenches"),
                    t("Depuis un angle du terrain, toutes les fouilles visibles.", "From a corner of the plot, all trenches visible.")),
               shot("profondeur", t("Profondeur avec un mètre", "Depth with a tape"),
                    t("Mètre ruban déplié verticalement au fond de la fouille, chiffres lisibles.",
                      "Tape measure held vertically at the bottom of the trench, numbers readable."), instrument=True),
               shot("ferraillage", t("Ferraillage des semelles", "Footing reinforcement"),
                    t("De près, on doit voir les cales sous les fers.", "Close-up, the spacers under the bars must show.")),
               shot("fond", t("Fond de fouille", "Trench bottom"),
                    t("Le fond : propre, sans eau ni terre éboulée, béton de propreté si prévu.",
                      "The bottom: clean, no water or fallen soil, blinding concrete if planned."), required=False)],
     "points": [point("fond_propre", t("Fond de fouille propre et sec", "Clean, dry trench bottom"),
                      t("Pas d'eau stagnante, pas de terre éboulée ni de racines au fond.", "No standing water, fallen soil or roots at the bottom.")),
                point("profondeur", t("Profondeur conforme au plan", "Depth as per drawing"),
                      t("Lire le mètre au fond de la fouille et comparer au plan de fondation.", "Read the tape at the bottom and compare with the foundation drawing."),
                      "critique", t("Quelle profondeur est prévue sur le plan de fondation ?", "What depth does the foundation drawing require?")),
                point("cales", t("Fers posés sur des cales (enrobage)", "Bars on spacers (concrete cover)"),
                      t("Les fers ne touchent ni la terre ni les parois : des cales les soulèvent de quelques centimètres.",
                        "Bars touch neither soil nor walls: spacers lift them a few centimetres."), "critique"),
                point("ferraillage_propre", t("Fers propres et bien ligaturés", "Clean, well-tied bars"),
                      t("Pas de rouille qui s'effrite, pas de boue ; les croisements sont attachés.", "No flaking rust or mud; crossings are tied.")),
                point("attentes", t("Attentes des poteaux en place", "Column starter bars in place"),
                      t("Les fers verticaux qui sortent des semelles sont à l'emplacement des poteaux du plan.",
                        "Vertical bars coming out of the footings are where the drawing puts the columns."), "critique")],
     "measures": [measure("profondeur", t("Profondeur de la fouille (cm)", "Trench depth (cm)"), "cm", "min_ref", "profondeur",
                          ref=t("profondeur prévue au plan (cm)", "depth on the drawing (cm)")),
                  measure("enrobage", t("Hauteur des cales sous les fers (cm)", "Spacer height under bars (cm)"), "cm", "min", "cales",
                          lo=3.0, hint=t("3 cm au moins dans le sol (valeur courante)", "at least 3 cm in the ground (usual value)"))]},

    {"slug": "ferraillage", "keywords": ("ferraill", "armature", "coffrage", "poteau", "poutre", "chaînage", "chainage", "dalle", "plancher"),
     "name": t("Ferraillage avant coulage (poteaux, poutres, dalle)", "Reinforcement before pouring (columns, beams, slab)"),
     "moment": t("Coffrage et fers en place, juste avant le béton : après, plus rien n'est visible.",
                 "Formwork and bars in place, just before concrete: afterwards nothing can be seen."),
     "shots": [shot("ensemble", t("Vue d'ensemble", "Overview"), t("Toute la zone qui va être coulée.", "The whole area about to be poured.")),
               shot("cadres", t("Cadres avec un mètre", "Stirrups with a tape"),
                    t("Mètre posé le long d'une poutre ou d'un poteau : on lit l'espacement des cadres.",
                      "Tape laid along a beam or column: stirrup spacing can be read."), instrument=True),
               shot("cales", t("Cales d'enrobage", "Cover spacers"), t("De près, sous les fers de la dalle ou contre le coffrage.",
                                                                     "Close-up, under the slab bars or against the formwork.")),
               shot("recouvrement", t("Recouvrement des fers", "Bar laps"), t("Là où deux barres se prolongent l'une l'autre.",
                                                                            "Where two bars continue one another."), required=False)],
     "points": [point("cales", t("Cales d'enrobage présentes partout", "Cover spacers everywhere"),
                      t("Les fers ne touchent pas le coffrage : cales en plastique ou en béton régulièrement réparties.",
                        "Bars do not touch the formwork: plastic or concrete spacers evenly spread."), "critique"),
                point("espacement", t("Cadres régulièrement espacés", "Evenly spaced stirrups"),
                      t("Espacement identique d'un cadre à l'autre, plus serré près des appuis si le plan le prévoit.",
                        "Same spacing between stirrups, tighter near supports if the drawing says so."), "critique"),
                point("recouvrement", t("Recouvrements suffisants", "Sufficient laps"),
                      t("Deux barres qui se prolongent se chevauchent largement (souvent 40 à 50 fois leur diamètre) et sont ligaturées.",
                        "Two bars that continue overlap well (often 40 to 50 times their diameter) and are tied."), "critique"),
                point("proprete", t("Fers et coffrage propres", "Clean bars and formwork"),
                      t("Pas de terre, de bois ou de déchets dans le coffrage ; rouille légère acceptable, pas de rouille qui s'effrite.",
                        "No soil, wood or rubbish in the formwork; light rust is fine, flaking rust is not.")),
                point("coffrage", t("Coffrage droit et étayé", "Straight, propped formwork"),
                      t("Planches jointives, étais verticaux et rapprochés sous la dalle.", "Tight boards, vertical props close together under the slab."))],
     "measures": [measure("espacement", t("Espacement des cadres mesurés (cm, séparés par des espaces)", "Measured stirrup spacing (cm, separated by spaces)"),
                          "cm", "regular", "espacement", tol=2.0, hint=t("écart de 2 cm au plus entre cadres (indicatif)", "2 cm difference at most (indicative)")),
                  measure("enrobage", t("Enrobage mesuré (cm)", "Measured cover (cm)"), "cm", "min", "cales", lo=2.5,
                          hint=t("2,5 cm au moins à l'intérieur, 3 cm à l'extérieur (valeurs courantes)", "at least 2.5 cm inside, 3 cm outside (usual values)"))]},

    {"slug": "beton", "keywords": ("béton", "beton", "décoffr", "decoffr", "dalle", "poteau", "poutre", "structure", "gros œuvre", "gros oeuvre"),
     "name": t("Béton après décoffrage (poteaux, poutres, dalle)", "Concrete after formwork removal (columns, beams, slab)"),
     "moment": t("Dans les jours qui suivent le décoffrage, avant tout enduit.", "In the days after removing formwork, before any render."),
     "shots": [shot("ensemble", t("Vue d'ensemble", "Overview"), t("Poteaux et poutres de l'étage.", "Columns and beams of the floor.")),
               shot("surface", t("Surface de près", "Surface close-up"), t("À 1 m, en lumière rasante si possible.", "From 1 m, with low-angle light if possible.")),
               shot("aplomb", t("Poteau avec un niveau", "Column with a level"), t("Niveau à bulle posé verticalement contre le poteau, bulle lisible.",
                                                                                 "Spirit level held vertically against the column, bubble readable."), instrument=True),
               shot("dessous", t("Dessous de dalle", "Slab underside"), t("Depuis le niveau inférieur.", "From the floor below."), required=False)],
     "points": [point("nids", t("Pas de nids de cailloux", "No honeycombing"),
                      t("Zones où les graviers apparaissent sans ciment : béton mal vibré.", "Areas where gravel shows without cement: poorly vibrated concrete."), "critique"),
                point("fers_apparents", t("Pas de fers apparents", "No exposed bars"),
                      t("Aucun fer ne doit se voir en surface : sinon enrobage insuffisant, risque de rouille et d'éclatement.",
                        "No bar should show on the surface: otherwise poor cover, risk of rust and spalling."), "critique"),
                point("fissures", t("Pas de fissure", "No cracks"),
                      t("Fissures fines en surface possibles ; une fissure qui traverse ou s'élargit est un problème.",
                        "Fine surface cracks can happen; a crack that goes through or widens is a problem."), "critique"),
                point("aplomb", t("Poteaux d'aplomb", "Plumb columns"), t("Bulle du niveau centrée, poteau droit sur toute sa hauteur.",
                                                                         "Level bubble centred, column straight all the way up.")),
                point("cure", t("Béton arrosé les premiers jours", "Concrete kept wet the first days"),
                      t("Surface humide ou couverte ; par forte chaleur, un béton séché trop vite fissure.",
                        "Surface wet or covered; in strong heat, concrete drying too fast cracks."), "mineur",
                      t("Le béton a-t-il été arrosé chaque jour pendant au moins 7 jours ?", "Was the concrete watered every day for at least 7 days?"))],
     "measures": [measure("aplomb", t("Écart d'aplomb sur la hauteur du poteau (mm)", "Plumb deviation over the column height (mm)"),
                          "mm", "max", "aplomb", hi=10.0, hint=t("1 cm au plus sur un étage (indicatif)", "1 cm at most per floor (indicative)"))]},

    {"slug": "maconnerie", "keywords": ("maçonn", "maconn", "élévation", "elevation", "mur", "agglo", "parpaing", "brique"),
     "name": t("Murs en agglos ou briques", "Block or brick walls"),
     "moment": t("Pendant ou juste après la montée des murs, avant l'enduit.", "During or just after building the walls, before render."),
     "shots": [shot("ensemble", t("Mur entier de face", "Whole wall, front view"), t("Bien en face, tout le mur dans le cadre.", "Straight on, the whole wall in frame.")),
               shot("aplomb", t("Mur avec un niveau", "Wall with a level"), t("Niveau ou fil à plomb contre le mur.", "Level or plumb line against the wall."), instrument=True),
               shot("joints", t("Joints de près", "Joints close-up"), t("Une zone d'1 m environ, avec un mètre pour l'épaisseur des joints.",
                                                                      "About 1 m of wall, with a tape for joint thickness."), instrument=True),
               shot("ouverture", t("Au-dessus d'une porte ou fenêtre", "Above a door or window"), t("Le linteau et ses appuis.", "The lintel and its bearings."), required=False)],
     "points": [point("aplomb", t("Mur d'aplomb et droit", "Plumb, straight wall"), t("Bulle centrée ; le mur ne bombe pas.", "Bubble centred; the wall does not bulge.")),
                point("joints", t("Joints réguliers et pleins", "Even, full joints"),
                      t("Joints d'épaisseur régulière (environ 1 cm), remplis de mortier, décalés d'un rang à l'autre.",
                        "Joints of even thickness (about 1 cm), filled with mortar, staggered between courses.")),
                point("chainages", t("Chaînages et raidisseurs", "Tie beams and stiffeners"),
                      t("Poteaux raidisseurs aux angles et croisements, chaînage en tête de mur.", "Stiffener columns at corners and junctions, tie beam on top of the wall."), "critique"),
                point("linteaux", t("Linteaux au-dessus des ouvertures", "Lintels above openings"),
                      t("Un linteau en béton armé qui dépasse de chaque côté de l'ouverture (souvent 20 cm au moins).",
                        "A reinforced concrete lintel extending past each side of the opening (often at least 20 cm)."), "critique"),
                point("agglos", t("Agglos entiers et de bonne qualité", "Whole, good-quality blocks"),
                      t("Pas d'agglos cassés, effrités ou trop sableux.", "No broken, crumbling or sandy blocks."), "mineur")],
     "measures": [measure("aplomb", t("Écart d'aplomb sur la hauteur du mur (mm)", "Plumb deviation over wall height (mm)"), "mm", "max", "aplomb",
                          hi=10.0, hint=t("1 cm au plus sur un étage (indicatif)", "1 cm at most per floor (indicative)")),
                  measure("joints", t("Épaisseur de joints mesurés (mm, séparés par des espaces)", "Measured joint thickness (mm, separated by spaces)"),
                          "mm", "range_list", "joints", lo=8.0, hi=15.0)]},

    {"slug": "enduit", "keywords": ("enduit", "crépi", "crepi", "ravalement"),
     "name": t("Enduits intérieurs et extérieurs", "Interior and exterior render"),
     "moment": t("Enduit sec, avant peinture.", "Render dry, before painting."),
     "shots": [shot("ensemble", t("Mur enduit en lumière rasante", "Rendered wall with low-angle light"),
                    t("Photographiez de biais, lumière venant du côté : les bosses se voient.", "Shoot at an angle, light from the side: bumps show.")),
               shot("regle", t("Règle de 2 m posée", "2 m straightedge laid"), t("Règle contre le mur, on doit voir le jour entre règle et mur.",
                                                                               "Straightedge against the wall, any gap must show."), instrument=True),
               shot("angle", t("Angle ou tableau de fenêtre", "Corner or window reveal"), t("Un angle sortant de près.", "An outer corner close-up."), required=False)],
     "points": [point("planeite", t("Surface plane", "Flat surface"), t("Pas de creux ni de bosse visibles en lumière rasante.", "No visible hollows or bumps in low-angle light.")),
                point("fissures", t("Pas de fissure", "No cracks"), t("Fissures en étoile ou en ligne : à noter avant peinture.", "Star or line cracks: to note before painting.")),
                point("angles", t("Angles droits et nets", "Straight, clean corners"), t("Arêtes droites, sans éclat.", "Straight edges, no chips."), "mineur"),
                point("adherence", t("Enduit bien accroché", "Well-bonded render"),
                      t("Pas de cloque ni de partie qui se décolle ; un enduit qui sonne creux au tapotement est décollé.",
                        "No blisters or peeling; render that sounds hollow when tapped is detached."), "majeur",
                      t("Avez-vous tapoté l'enduit ? Des zones sonnent-elles creux ?", "Did you tap the render? Do some areas sound hollow?"))],
     "measures": [measure("planeite", t("Plus grand écart sous la règle de 2 m (mm)", "Largest gap under the 2 m straightedge (mm)"), "mm", "max",
                          "planeite", hi=5.0, hint=t("5 mm au plus pour une finition soignée (indicatif)", "5 mm at most for a neat finish (indicative)"))]},

    {"slug": "escalier", "keywords": ("escalier", "marche", "volée", "volee"),
     "name": t("Escalier", "Staircase"),
     "moment": t("Marches coulées et décoffrées, puis à nouveau une fois le revêtement posé.",
                 "Steps poured and stripped, then again once the finish is laid."),
     "shots": [shot("profil", t("Escalier de profil", "Staircase side view"),
                    t("Bien de côté, toute la volée dans le cadre : on compare les hauteurs des marches.",
                      "Straight from the side, the whole flight in frame: step heights can be compared.")),
               shot("face", t("Escalier de face, d'en bas", "Staircase from the bottom, front"), t("Depuis le pied de l'escalier.", "From the foot of the stairs.")),
               shot("hauteur", t("Hauteur d'une marche avec un mètre", "Step height with a tape"),
                    t("Mètre vertical posé sur une marche, chiffres lisibles.", "Tape held vertically on a step, numbers readable."), instrument=True),
               shot("garde_corps", t("Garde-corps ou main courante", "Guardrail or handrail"), t("Avec un mètre pour la hauteur.", "With a tape for the height."),
                    required=False, instrument=True),
               shot("nez", t("Nez de marches de près", "Step nosings close-up"), t("Les bords des marches.", "The step edges."), required=False)],
     "points": [point("hauteurs", t("Marches de même hauteur", "Steps of equal height"),
                      t("Toutes les marches ont la même hauteur : une marche différente de quelques millimètres fait trébucher.",
                        "All steps are the same height: one step a few millimetres off makes people trip."), "critique"),
                point("girons", t("Marches de même profondeur", "Steps of equal depth"),
                      t("La partie où l'on pose le pied (giron) est identique sur toutes les marches.", "The tread depth is the same on every step.")),
                point("confort", t("Escalier confortable", "Comfortable stairs"),
                      t("Hauteur d'environ 16 à 18 cm et profondeur d'environ 25 à 30 cm ; règle de Blondel : 2 hauteurs + 1 profondeur ≈ 60 à 64 cm.",
                        "Rise about 16–18 cm and tread about 25–30 cm; Blondel rule: 2 rises + 1 tread ≈ 60–64 cm.")),
                point("garde_corps", t("Garde-corps ou main courante", "Guardrail or handrail"),
                      t("Côté vide protégé par un garde-corps d'environ 1 m, solide, sans barreaux trop écartés pour un enfant.",
                        "Open side protected by a sturdy guardrail about 1 m high, bars not too wide apart for a child."), "critique"),
                point("echappee", t("Hauteur libre au-dessus des marches", "Headroom above the steps"),
                      t("On ne se cogne pas la tête : environ 2 m libres au-dessus de chaque marche.", "Nobody hits their head: about 2 m clear above every step."), "majeur"),
                point("nez", t("Nez de marches intacts", "Intact nosings"), t("Bords des marches nets, sans éclat ni fer apparent.", "Clean step edges, no chips or exposed steel."), "mineur")],
     "measures": [measure("hauteurs", t("Hauteur de chaque marche (cm, de bas en haut, séparées par des espaces)", "Height of each step (cm, bottom to top, separated by spaces)"),
                          "cm", "regular", "hauteurs", tol=0.5, lo=15.0, hi=19.0,
                          hint=t("écart de 5 mm au plus entre marches (indicatif)", "5 mm difference at most between steps (indicative)")),
                  measure("girons", t("Profondeur de chaque marche (cm, séparées par des espaces)", "Depth of each step (cm, separated by spaces)"),
                          "cm", "regular", "girons", tol=1.0, lo=24.0, hi=32.0),
                  measure("garde_corps", t("Hauteur du garde-corps (cm)", "Guardrail height (cm)"), "cm", "min", "garde_corps", lo=100.0,
                          hint=t("environ 1 m (valeur courante)", "about 1 m (usual value)")),
                  measure("echappee", t("Hauteur libre la plus faible (cm)", "Lowest headroom (cm)"), "cm", "min", "echappee", lo=200.0)]},

    {"slug": "carrelage", "keywords": ("carrel", "revêtement de sol", "revetement de sol", "sol", "finition"),
     "name": t("Carrelage au sol", "Floor tiling"),
     "moment": t("Joints faits et secs, avant la pose des meubles.", "Grout done and dry, before furniture goes in."),
     "shots": [shot("ensemble", t("Pièce entière en enfilade", "Whole room along the joints"),
                    t("Photo prise dans l'axe des joints, à hauteur d'homme : les lignes doivent être droites.",
                      "Photo taken along the joint lines at eye level: lines should be straight.")),
               shot("rasant", t("Sol en lumière rasante", "Floor in low-angle light"), t("Appareil près du sol, lumière de côté : les carreaux qui dépassent se voient.",
                                                                                         "Camera near the floor, light from the side: proud tiles show.")),
               shot("regle", t("Règle de 2 m posée au sol", "2 m straightedge on the floor"), t("Avec une cale ou un mètre sous la règle là où elle ne touche pas.",
                                                                                                "With a wedge or tape under the straightedge where it does not touch."), instrument=True),
               shot("bords", t("Coupes le long d'un mur", "Cuts along a wall"), t("Les carreaux coupés au bord et la plinthe.", "Cut tiles along the edge and the skirting.")),
               shot("seuil", t("Seuil ou passage de porte", "Threshold or doorway"), t("La jonction entre deux pièces.", "The junction between two rooms."), required=False)],
     "points": [point("alignement", t("Joints alignés", "Aligned joints"), t("Les lignes de joints sont droites et parallèles aux murs principaux.",
                                                                            "Joint lines are straight and parallel to the main walls.")),
                point("joints", t("Joints réguliers et pleins", "Even, full joints"), t("Même largeur partout, joint rempli sans trou.", "Same width everywhere, grout filled with no holes."), "mineur"),
                point("desaffleure", t("Carreaux à la même hauteur", "Tiles level with each other"),
                      t("Un bord de carreau qui dépasse de son voisin se voit en lumière rasante et accroche le pied.",
                        "A tile edge proud of its neighbour shows in low-angle light and catches the foot.")),
                point("planeite", t("Sol plan", "Flat floor"), t("La règle de 2 m touche partout, sans jour important.", "The 2 m straightedge touches everywhere, no large gap.")),
                point("casse", t("Carreaux sans fissure ni éclat", "Tiles without cracks or chips"), t("Aucun carreau fendu, ébréché ou taché.", "No cracked, chipped or stained tile.")),
                point("coupes", t("Coupes propres en bordure", "Clean edge cuts"), t("Coupes droites, pas de petites bandes de carreau, plinthes bien posées.",
                                                                                   "Straight cuts, no thin slivers of tile, skirting well fitted."), "mineur"),
                point("creux", t("Carreaux bien collés", "Well-bonded tiles"),
                      t("Un carreau qui sonne creux sous un petit coup est mal collé et finira par casser.", "A tile that sounds hollow when tapped is poorly bonded and will crack."),
                      "majeur", t("En tapotant les carreaux avec le manche d'un outil, certains sonnent-ils creux ?",
                                  "When tapping the tiles with a tool handle, do some sound hollow?"))],
     "measures": [measure("planeite", t("Plus grand écart sous la règle de 2 m (mm)", "Largest gap under the 2 m straightedge (mm)"), "mm", "max", "planeite",
                          hi=4.0, hint=t("4 à 5 mm au plus (indicatif)", "4 to 5 mm at most (indicative)")),
                  measure("desaffleure", t("Plus grand dépassement entre deux carreaux (mm)", "Largest lip between two tiles (mm)"), "mm", "max", "desaffleure", hi=1.0),
                  measure("joints", t("Largeur de joints mesurés (mm, séparés par des espaces)", "Measured joint widths (mm, separated by spaces)"), "mm", "regular", "joints", tol=1.0),
                  measure("creux", t("Carreaux qui sonnent creux", "Tiles that sound hollow"), "", "choice", "creux",
                          choices=[("aucun", t("Aucun", "None"), "ok"), ("quelques", t("Un ou deux", "One or two"), "a_verifier"),
                                   ("plusieurs", t("Plusieurs", "Several"), "probleme")])]},

    {"slug": "faience", "keywords": ("faïence", "faience", "crédence", "credence", "carrelage mural"),
     "name": t("Faïence murale", "Wall tiling"),
     "moment": t("Joints faits, avant la pose des équipements.", "Grout done, before fittings go in."),
     "shots": [shot("ensemble", t("Mur entier de face", "Whole wall, front view"), t("Bien en face, tout le mur carrelé.", "Straight on, the whole tiled wall.")),
               shot("niveau", t("Rang avec un niveau", "Course with a level"), t("Niveau posé sur une ligne de joint horizontale.", "Level on a horizontal joint line."), instrument=True),
               shot("decoupes", t("Découpes autour des sorties", "Cuts around outlets"), t("Autour des robinets, prises et tuyaux.", "Around taps, sockets and pipes."))],
     "points": [point("niveau", t("Rangs horizontaux", "Level courses"), t("Lignes de joints horizontales, bulle centrée.", "Joint lines level, bubble centred.")),
                point("joints", t("Joints réguliers", "Even joints"), t("Même largeur, joints pleins, croisements nets.", "Same width, full joints, clean crossings."), "mineur"),
                point("decoupes", t("Découpes propres", "Clean cuts"), t("Trous ajustés autour des sorties, pas de carreau fendu.", "Holes fitted around outlets, no cracked tile."), "mineur"),
                point("casse", t("Carreaux intacts", "Intact tiles"), t("Aucun carreau fendu ou ébréché.", "No cracked or chipped tile."))],
     "measures": []},

    {"slug": "douche", "keywords": ("douche", "salle d'eau", "salle de bain", "sdb", "sanitaire", "étanch", "etanch"),
     "name": t("Douche et salle d'eau", "Shower and bathroom"),
     "moment": t("Deux fois : l'étanchéité avant le carrelage, puis la douche finie avec un test d'eau.",
                 "Twice: waterproofing before tiling, then the finished shower with a water test."),
     "shots": [shot("etancheite", t("Étanchéité avant carrelage", "Waterproofing before tiling"),
                    t("Sol et bas des murs de la douche : la membrane ou le produit d'étanchéité doit se voir, avec les bandes dans les angles.",
                      "Shower floor and lower walls: the membrane or waterproofing product must show, with tape in the corners.")),
               shot("siphon", t("Siphon de près", "Drain close-up"), t("La grille et le raccord autour.", "The grate and its surround.")),
               shot("pente", t("Niveau posé au sol de la douche", "Level on the shower floor"),
                    t("Niveau orienté vers le siphon : la bulle doit être décalée du côté opposé au siphon.",
                      "Level pointing at the drain: the bubble should sit away from the drain."), instrument=True),
               shot("test_eau", t("Test d'eau", "Water test"), t("Versez un seau d'eau, attendez une minute, photographiez le sol.",
                                                               "Pour a bucket of water, wait one minute, photograph the floor.")),
               shot("angles", t("Joints dans les angles", "Corner seals"), t("Joint souple entre sol et murs, et autour du receveur.",
                                                                           "Flexible seal between floor and walls, and around the tray.")),
               shot("ensemble", t("Salle d'eau entière", "Whole bathroom"), t("Depuis la porte.", "From the door."), required=False)],
     "points": [point("etancheite", t("Étanchéité sous le carrelage", "Waterproofing under the tiles"),
                      t("Membrane ou produit continu au sol et remonté sur les murs de la douche, bandes dans les angles. Sans elle, l'eau passe et abîme la dalle.",
                        "Continuous membrane or product on the floor and up the shower walls, tape in corners. Without it, water gets through and damages the slab."), "critique",
                      t("Une étanchéité a-t-elle été posée avant le carrelage ? Avez-vous une photo ?", "Was waterproofing laid before tiling? Do you have a photo?")),
                point("pente", t("Sol qui descend vers le siphon", "Floor sloping to the drain"),
                      t("Pente légère et continue vers le siphon (environ 1 à 2 %).", "A slight, continuous slope towards the drain (about 1–2%)."), "critique"),
                point("ecoulement", t("Pas d'eau qui stagne", "No standing water"),
                      t("Une minute après le seau d'eau, il ne reste pas de flaque.", "One minute after the bucket of water, no puddle remains."), "critique"),
                point("siphon", t("Siphon bien placé et accessible", "Drain well placed and reachable"),
                      t("Grille au point le plus bas, démontable pour le nettoyage.", "Grate at the lowest point, removable for cleaning.")),
                point("joints_souples", t("Joints souples dans les angles", "Flexible seals in corners"),
                      t("Joint silicone continu entre sol et murs et autour du receveur, sans trou ni moisissure.",
                        "Continuous silicone seal between floor and walls and around the tray, no holes or mould.")),
                point("robinetterie", t("Robinetterie droite et fixée", "Straight, fixed taps"), t("Mitigeur et colonne droits, pas de fuite visible.",
                                                                                                 "Mixer and riser straight, no visible leak."), "mineur")],
     "measures": [measure("pente", t("Pente mesurée vers le siphon (%)", "Measured slope to the drain (%)"), "%", "range", "pente", lo=1.0, hi=3.0,
                          hint=t("1 à 3 % (indicatif) : 1 cm pour 1 m = 1 %", "1 to 3% (indicative): 1 cm per 1 m = 1%")),
                  measure("ecoulement", t("Après une minute, l'eau du seau est-elle partie ?", "After one minute, has the bucket of water drained?"), "", "choice", "ecoulement",
                          choices=[("oui", t("Oui, tout est parti", "Yes, all gone"), "ok"), ("flaque", t("Une petite flaque reste", "A small puddle remains"), "a_verifier"),
                                   ("non", t("Non, l'eau stagne", "No, water stands"), "probleme")])]},

    {"slug": "electricite", "keywords": ("électri", "electri", "câblage", "cablage", "tableau"),
     "name": t("Électricité", "Electrical"),
     "moment": t("Gaines posées avant enduit, puis tableau et prises une fois posés.", "Conduits before render, then the panel and sockets once fitted."),
     "shots": [shot("tableau", t("Tableau électrique ouvert", "Open distribution board"), t("Capot ouvert, tous les disjoncteurs visibles.", "Cover open, all breakers visible.")),
               shot("gaines", t("Gaines dans les murs", "Conduits in the walls"), t("Avant l'enduit : gaines, boîtes d'encastrement.", "Before render: conduits, back boxes.")),
               shot("prise", t("Prise ouverte", "Open socket"), t("Une prise sans son cache : on voit les fils.", "A socket without its cover: wires visible."), required=False),
               shot("terre", t("Barrette de terre", "Earth bar"), t("Le fil vert et jaune qui va au piquet de terre.", "The green-and-yellow wire going to the earth rod."), required=False)],
     "points": [point("differentiel", t("Interrupteur différentiel 30 mA", "30 mA residual current device"),
                      t("Au moins un appareil marqué 30 mA protège les circuits : il coupe en cas de fuite vers une personne.",
                        "At least one device marked 30 mA protects the circuits: it trips when current leaks through a person."), "critique"),
                point("terre", t("Mise à la terre", "Earthing"), t("Fils vert et jaune présents jusqu'aux prises et au tableau.", "Green-and-yellow wires present up to sockets and the board."), "critique"),
                point("fils", t("Pas de fil dénudé ni de raccord volant", "No bare wires or loose joints"),
                      t("Fils sous gaine, raccords dans des boîtes, pas de scotch.", "Wires in conduit, joints in boxes, no tape."), "critique"),
                point("reperage", t("Circuits repérés", "Labelled circuits"), t("Chaque disjoncteur porte le nom de son circuit.", "Each breaker carries the name of its circuit."), "mineur"),
                point("gaines", t("Gaines et boîtes bien posées", "Conduits and boxes properly fitted"), t("Gaines fixées, boîtes d'encastrement au bon niveau.",
                                                                                                         "Conduits fixed, back boxes at the right level."), "mineur")],
     "measures": [measure("test_diff", t("Le bouton « test » du différentiel coupe-t-il le courant ?", "Does the RCD “test” button cut the power?"), "", "choice", "differentiel",
                          choices=[("oui", t("Oui", "Yes"), "ok"), ("non", t("Non", "No"), "probleme"), ("absent", t("Pas de différentiel", "No RCD"), "probleme")])]},

    {"slug": "plomberie", "keywords": ("plomberie", "canalisation", "évacuation", "evacuation", "réseaux", "reseaux", "assainissement"),
     "name": t("Plomberie et évacuations", "Plumbing and drainage"),
     "moment": t("Réseaux posés, avant de les recouvrir, avec l'essai de mise en eau.", "Pipes laid, before covering them, with the water test."),
     "shots": [shot("reseau", t("Réseau d'évacuation", "Drain pipes"), t("Tuyaux d'évacuation sur toute leur longueur visible.", "Drain pipes along their whole visible length.")),
               shot("pente", t("Tuyau avec un niveau", "Pipe with a level"), t("Niveau posé sur un tuyau d'évacuation.", "Level laid on a drain pipe."), instrument=True),
               shot("alimentation", t("Arrivées d'eau", "Water supply pipes"), t("Tuyaux d'alimentation et leurs fixations.", "Supply pipes and their brackets.")),
               shot("essai", t("Manomètre de l'essai", "Test pressure gauge"), t("Si un essai de pression est fait : le manomètre au début et à la fin.",
                                                                                 "If a pressure test is done: the gauge at start and end."), required=False, instrument=True)],
     "points": [point("pente", t("Évacuations en pente régulière", "Drains with a steady slope"),
                      t("Pente continue vers la sortie (environ 1 à 3 %), aucune contre-pente où l'eau stagnerait.",
                        "Continuous slope to the outlet (about 1–3%), no back-fall where water would sit."), "critique"),
                point("fixations", t("Tuyaux fixés", "Pipes fixed"), t("Colliers réguliers, tuyaux qui ne pendent pas.", "Regular brackets, pipes not sagging.")),
                point("raccords", t("Raccords propres et étanches", "Clean, tight joints"), t("Pas de colle qui coule, pas de trace d'eau.", "No glue dripping, no water marks.")),
                point("essai", t("Essai d'étanchéité fait", "Leak test done"), t("Réseau mis en eau ou sous pression avant d'être caché.", "Network filled or pressurised before being hidden."),
                      "majeur", t("Un essai de mise en eau ou de pression a-t-il été fait ? Combien de temps et quel résultat ?",
                                  "Was a fill or pressure test done? How long and what result?"))],
     "measures": [measure("pente", t("Pente mesurée de l'évacuation (%)", "Measured drain slope (%)"), "%", "range", "pente", lo=1.0, hi=3.0),
                  measure("essai", t("Essai de pression ou de mise en eau tenu sans baisse ?", "Pressure or fill test held without drop?"), "", "choice", "essai",
                          choices=[("oui", t("Oui", "Yes"), "ok"), ("baisse", t("Baisse constatée", "Drop seen"), "probleme"), ("non_fait", t("Pas fait", "Not done"), "a_verifier")])]},

    {"slug": "toiture", "keywords": ("toit", "charpente", "couverture", "tôle", "tole", "tuile"),
     "name": t("Charpente et toiture", "Roof structure and covering"),
     "moment": t("Charpente posée avant la couverture, puis toiture finie.", "Structure in place before covering, then the finished roof."),
     "shots": [shot("charpente", t("Charpente avant couverture", "Structure before covering"), t("Toutes les pannes ou fermes visibles.", "All purlins or trusses visible.")),
               shot("entraxe", t("Entraxe avec un mètre", "Spacing with a tape"), t("Mètre tendu entre deux pannes ou chevrons.", "Tape stretched between two purlins or rafters."), instrument=True),
               shot("couverture", t("Couverture finie", "Finished covering"), t("Depuis le sol ou un point haut, tout le pan.", "From the ground or a high point, the whole slope.")),
               shot("interieur", t("Sous la toiture, de l'intérieur", "Under the roof, from inside"), t("En journée : on ne doit voir aucun jour.", "In daytime: no daylight should show."), required=False)],
     "points": [point("entraxe", t("Pannes régulièrement espacées", "Evenly spaced purlins"), t("Espacement identique, conforme au plan ou au fabricant des tôles.",
                                                                                              "Same spacing, as per the drawing or the sheet maker."), "critique"),
                point("fixations", t("Fixations solides", "Solid fixings"), t("Pannes ancrées dans le chaînage, tôles vissées avec rondelles étanches.",
                                                                            "Purlins anchored in the tie beam, sheets screwed with sealing washers."), "critique"),
                point("recouvrement", t("Recouvrement des tôles ou tuiles", "Sheet or tile overlap"), t("Chaque tôle recouvre la suivante, sens du vent respecté.",
                                                                                                       "Each sheet overlaps the next, laid with the prevailing wind.")),
                point("etancheite", t("Pas d'infiltration", "No leaks"), t("Faîtage et rives fermés, aucun jour depuis l'intérieur.", "Ridge and edges closed, no daylight from inside."), "critique"),
                point("bois", t("Bois traité et sain", "Treated, sound timber"), t("Bois sans fente importante ni attaque d'insectes.", "Timber without large splits or insect damage."), "mineur")],
     "measures": [measure("entraxe", t("Entraxe des pannes mesurés (cm, séparés par des espaces)", "Measured purlin spacing (cm, separated by spaces)"), "cm", "regular", "entraxe", tol=5.0)]},

    {"slug": "menuiseries", "keywords": ("menuiser", "porte", "fenêtre", "fenetre", "huisserie", "baie"),
     "name": t("Portes et fenêtres", "Doors and windows"),
     "moment": t("Menuiseries posées, avant la peinture.", "Frames fitted, before painting."),
     "shots": [shot("face", t("Menuiserie de face", "Frame front view"), t("La porte ou la fenêtre entière.", "The whole door or window.")),
               shot("niveau", t("Avec un niveau", "With a level"), t("Niveau contre le montant vertical.", "Level against the upright."), instrument=True),
               shot("calfeutrement", t("Jonction avec le mur", "Joint with the wall"), t("Le tour du cadre, de près.", "Around the frame, close-up.")),
               shot("appui", t("Appui de fenêtre", "Window sill"), t("De côté : l'appui doit pencher vers l'extérieur.", "From the side: the sill should slope outward."), required=False)],
     "points": [point("aplomb", t("Cadre d'aplomb et de niveau", "Plumb, level frame"), t("Bulle centrée ; jeu régulier entre ouvrant et cadre.", "Bubble centred; even gap between leaf and frame.")),
                point("calfeutrement", t("Tour du cadre bouché", "Frame surround sealed"), t("Pas de vide entre cadre et mur, joint continu.", "No gap between frame and wall, continuous seal.")),
                point("appui", t("Appui qui évacue l'eau", "Sill that sheds water"), t("Pente vers l'extérieur, goutte d'eau sous l'appui.", "Slope outward, drip groove underneath."), "mineur"),
                point("etat", t("Menuiserie intacte", "Undamaged frame"), t("Pas de vitre fêlée, de choc ou de rayure.", "No cracked glass, dents or scratches."), "mineur")],
     "measures": [measure("aplomb", t("Écart d'aplomb sur la hauteur (mm)", "Plumb deviation over the height (mm)"), "mm", "max", "aplomb", hi=3.0)]},

    {"slug": "peinture", "keywords": ("peinture", "finition"),
     "name": t("Peinture", "Painting"),
     "moment": t("Peinture sèche, deuxième couche passée.", "Paint dry, second coat applied."),
     "shots": [shot("ensemble", t("Mur peint en lumière rasante", "Painted wall in low-angle light"), t("De biais, lumière de côté.", "At an angle, light from the side.")),
               shot("raccords", t("Raccords avec plafond et menuiseries", "Edges at ceiling and frames"), t("Les angles et bords de près.", "Corners and edges close-up."))],
     "points": [point("uniformite", t("Teinte uniforme", "Even colour"), t("Pas de zones plus claires, de traces de rouleau ni de reprises.", "No lighter patches, roller marks or patch-ups."), "mineur"),
                point("coulures", t("Pas de coulure", "No runs"), t("Aucune goutte figée.", "No dried drips."), "mineur"),
                point("bords", t("Bords nets", "Clean edges"), t("Pas de peinture sur les menuiseries, prises ou carrelage.", "No paint on frames, sockets or tiles."), "mineur"),
                point("support", t("Support préparé", "Prepared surface"), t("Pas de fissure ni de trou visibles sous la peinture.", "No cracks or holes visible under the paint."), "mineur")],
     "measures": []},
]
BY_SLUG = {o["slug"]: o for o in OUVRAGES}


def _p(d, lang):
    return (d or {}).get(lang) or (d or {}).get("fr") or ""


def localize(o, lang):
    return {"slug": o["slug"], "name": _p(o["name"], lang), "moment": _p(o["moment"], lang),
            "shots": [dict(s, label=_p(s["label"], lang), hint=_p(s["hint"], lang)) for s in o["shots"]],
            "points": [dict(pt, label=_p(pt["label"], lang), look=_p(pt["look"], lang), question=_p(pt["question"], lang) or None,
                            severity_label=_p(SEVERITY_LABEL[pt["severity"]], lang)) for pt in o["points"]],
            "measures": [dict(m, label=_p(m["label"], lang), hint=_p(m.get("hint"), lang), ref=_p(m.get("ref"), lang),
                              choices=[(k, _p(lbl, lang), st) for k, lbl, st in m.get("choices", [])]) for m in o["measures"]]}


def catalog(lang):
    return [{"slug": o["slug"], "name": _p(o["name"], lang)} for o in OUVRAGES]


def suggest(step_name):
    """Ouvrages qui correspondent au nom d'une etape, les plus probables d'abord."""
    n = (step_name or "").lower()
    hits = [o["slug"] for o in OUVRAGES if any(k in n for k in o["keywords"])]
    return hits


# --------------------------------------------------------------------------
# Mesures : regles fixes, independantes de l'IA
# --------------------------------------------------------------------------
def parse_numbers(text):
    vals = []
    for tok in re.split(r"[\s;/]+", str(text or "").strip()):
        tok = tok.replace(",", ".")
        try:
            v = float(tok)
        except ValueError:
            continue
        if v == v and abs(v) < 100000:
            vals.append(v)
    return vals


def fmt(v):
    return (f"{v:.1f}".rstrip("0").rstrip(".")).replace(".", ",")


def check_measure(m, raw, lang="fr", ref_value=None):
    """(statut, explication) d'une mesure saisie, ou None si rien d'exploitable."""
    u = (" " + m["unit"]) if m["unit"] else ""
    fr = lang != "en"
    if m["rule"] == "choice":
        for k, lbl, st in m.get("choices", []):
            if raw == k:
                return st, (_p(lbl, lang) if isinstance(lbl, dict) else lbl)
        return None
    vals = parse_numbers(raw)
    if not vals:
        return None
    if m["rule"] in ("regular", "range_list"):
        lo, hi, tol = m.get("lo"), m.get("hi"), m.get("tol")
        out = [v for v in vals if (lo is not None and v < lo) or (hi is not None and v > hi)]
        spread = max(vals) - min(vals)
        parts, status = [], "ok"
        if m["rule"] == "regular" and len(vals) >= 2 and tol is not None:
            parts.append((f"écart entre la plus petite et la plus grande valeur : {fmt(spread)}{u} (tolérance indicative {fmt(tol)}{u})" if fr
                          else f"spread between smallest and largest value: {fmt(spread)}{u} (indicative tolerance {fmt(tol)}{u})"))
            if spread > 2 * tol:
                status = "probleme"
            elif spread > tol:
                status = "a_verifier"
            if status != "ok":
                i_min, i_max = vals.index(min(vals)), vals.index(max(vals))
                parts.append((f"valeur la plus faible n° {i_min + 1} ({fmt(min(vals))}{u}), la plus forte n° {i_max + 1} ({fmt(max(vals))}{u})" if fr
                              else f"lowest is no. {i_min + 1} ({fmt(min(vals))}{u}), highest no. {i_max + 1} ({fmt(max(vals))}{u})"))
        if out:
            parts.append((f"{len(out)} valeur(s) hors de la plage courante {fmt(lo)}–{fmt(hi)}{u} : " if fr
                           else f"{len(out)} value(s) outside the usual range {fmt(lo)}–{fmt(hi)}{u}: ") + ", ".join(fmt(v) for v in out))
            status = "probleme" if m["rule"] == "range_list" and len(out) > len(vals) / 3 else ("a_verifier" if status == "ok" else status)
        if not parts:
            parts.append((f"{len(vals)} valeur(s) entre {fmt(min(vals))} et {fmt(max(vals))}{u}" if fr
                          else f"{len(vals)} value(s) between {fmt(min(vals))} and {fmt(max(vals))}{u}"))
        return status, "; ".join(parts)
    v = vals[0]
    if m["rule"] == "min":
        lo = m["lo"]
        if v >= lo:
            return "ok", (f"{fmt(v)}{u}, au moins {fmt(lo)}{u}" if fr else f"{fmt(v)}{u}, at least {fmt(lo)}{u}")
        return ("a_verifier" if v >= lo * 0.9 else "probleme"), (f"{fmt(v)}{u}, moins que les {fmt(lo)}{u} courants" if fr
                                                                  else f"{fmt(v)}{u}, less than the usual {fmt(lo)}{u}")
    if m["rule"] == "max":
        hi = m["hi"]
        if v <= hi:
            return "ok", (f"{fmt(v)}{u}, {fmt(hi)}{u} au plus" if fr else f"{fmt(v)}{u}, {fmt(hi)}{u} at most")
        return ("a_verifier" if v <= hi * 1.5 else "probleme"), (f"{fmt(v)}{u}, plus que les {fmt(hi)}{u} admis couramment" if fr
                                                                  else f"{fmt(v)}{u}, more than the usual {fmt(hi)}{u}")
    if m["rule"] == "range":
        lo, hi = m["lo"], m["hi"]
        if lo <= v <= hi:
            return "ok", (f"{fmt(v)}{u}, dans la plage {fmt(lo)}–{fmt(hi)}{u}" if fr else f"{fmt(v)}{u}, within {fmt(lo)}–{fmt(hi)}{u}")
        near = lo * 0.75 <= v <= hi * 1.33
        return ("a_verifier" if near else "probleme"), (f"{fmt(v)}{u}, hors de la plage {fmt(lo)}–{fmt(hi)}{u}" if fr
                                                         else f"{fmt(v)}{u}, outside {fmt(lo)}–{fmt(hi)}{u}")
    if m["rule"] == "min_ref":
        refs = parse_numbers(ref_value)
        if not refs:
            return "a_verifier", (f"{fmt(v)}{u} mesurés : indiquez la valeur du plan pour comparer" if fr
                                  else f"{fmt(v)}{u} measured: enter the drawing value to compare")
        r = refs[0]
        if v >= r:
            return "ok", (f"{fmt(v)}{u} pour {fmt(r)}{u} prévus" if fr else f"{fmt(v)}{u} for {fmt(r)}{u} planned")
        return ("a_verifier" if v >= r * 0.95 else "probleme"), (f"{fmt(v)}{u} pour {fmt(r)}{u} prévus au plan" if fr
                                                                  else f"{fmt(v)}{u} for {fmt(r)}{u} on the drawing")
    return None


def derived_checks(slug, values, lang="fr"):
    """Controles calcules a partir de plusieurs mesures (ex. regle de Blondel pour l'escalier)."""
    out = {}
    fr = lang != "en"
    if slug == "escalier":
        h, gi = parse_numbers(values.get("hauteurs")), parse_numbers(values.get("girons"))
        if h and gi:
            hm, gm = sum(h) / len(h), sum(gi) / len(gi)
            b = 2 * hm + gm
            st = "ok" if 59 <= b <= 66 else ("a_verifier" if 56 <= b <= 69 else "probleme")
            out["confort"] = (st, (f"hauteur moyenne {fmt(hm)} cm, profondeur moyenne {fmt(gm)} cm : 2 h + g = {fmt(b)} cm (confortable entre 60 et 64 cm environ)" if fr
                                   else f"average rise {fmt(hm)} cm, average tread {fmt(gm)} cm: 2 r + t = {fmt(b)} cm (comfortable around 60–64 cm)"))
    return out


def rule_results(slug, values, lang="fr"):
    """{point: (statut, explication)} pour toutes les mesures saisies."""
    o = BY_SLUG[slug]
    res = {}
    rank = {"ok": 0, "a_verifier": 1, "probleme": 2}
    for m in o["measures"]:
        r = check_measure(m, values.get(m["id"]), lang, values.get(m["id"] + "_ref"))
        if r is None:
            continue
        prev = res.get(m["point"])
        if prev is None or rank[r[0]] > rank[prev[0]]:
            res[m["point"]] = r if prev is None else (r[0], prev[1] + " ; " + r[1])
        else:
            res[m["point"]] = (prev[0], prev[1] + " ; " + r[1])
    res.update({k: v for k, v in derived_checks(slug, values, lang).items() if k not in res or rank[v[0]] > rank[res[k][0]]})
    return res


# --------------------------------------------------------------------------
# Qualite des photos : toujours, en local
# --------------------------------------------------------------------------
def photo_quality(img):
    """Nettete (variance du laplacien), luminosite et taille : une photo floue ou sombre ne permet aucun avis."""
    g = img.convert("L")
    w, h = g.size
    small = g.copy()
    small.thumbnail((800, 800))
    a = np.asarray(small, dtype=np.float32)
    lap = (a[1:-1, 2:] + a[1:-1, :-2] + a[2:, 1:-1] + a[:-2, 1:-1] - 4 * a[1:-1, 1:-1])
    sharp = float(lap.var())
    bright = float(a.mean())
    issues = []
    if sharp < 60:
        issues.append("floue")
    if bright < 45:
        issues.append("sombre")
    elif bright > 235:
        issues.append("surexposee")
    if min(w, h) < 480:
        issues.append("petite")
    return {"sharpness": round(sharp, 1), "brightness": round(bright, 1), "issues": issues}


ISSUE_LABEL = {"floue": t("photo floue", "blurred photo"), "sombre": t("photo trop sombre", "photo too dark"),
               "surexposee": t("photo trop claire", "photo too bright"), "petite": t("photo trop petite", "photo too small")}


# --------------------------------------------------------------------------
# Analyse par l'IA, sur toutes les photos de l'ouvrage a la fois
# --------------------------------------------------------------------------
def ai_enabled():
    return bool(env("ANTHROPIC_API_KEY"))


def _b64(img, max_side=1280):
    import base64
    im = img.convert("RGB")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def build_prompt(o, photos, values, rules, previous, step_name, lang):
    """photos : liste de dict(shot_label, note, taken, zone). previous : points d'une analyse precedente a recontroler."""
    L = localize(o, "fr")
    lines = [
        "Tu es un conducteur de travaux expérimenté. Tu aides un propriétaire qui vit loin de son chantier, en Côte d'Ivoire, "
        "à juger la qualité d'un ouvrage à partir de photos prises sur place par le chef de chantier.",
        f"Ouvrage : {L['name']}. Étape du chantier : {step_name}.",
        "Règles : ne juge que ce qui se voit vraiment. Si un point ne se voit pas, dis-le (non_visible) au lieu de deviner. "
        "Une photo ne permet pas de mesurer au millimètre : sans instrument lisible dans le cadre, reste prudent (a_verifier). "
        "Quand un instrument de mesure (mètre, niveau, règle, manomètre) est visible, lis sa valeur si tu le peux.",
        "", "Points à contrôler (id : intitulé — ce qu'il faut regarder) :"]
    for pt in L["points"]:
        lines.append(f"- {pt['id']} : {pt['label']} — {pt['look']} [gravité : {pt['severity']}]")
    if values:
        lines += ["", "Mesures saisies par le chef de chantier :"]
        for m in L["measures"]:
            v = values.get(m["id"])
            if v not in (None, ""):
                lines.append(f"- {m['id']} ({m['label']}) : {v}")
        if rules:
            lines.append("Résultat des règles appliquées à ces mesures : " + "; ".join(f"{k} = {s} ({e})" for k, (s, e) in rules.items()))
        lines.append("Si une photo montre l'instrument, vérifie que la valeur lue correspond à la mesure saisie.")
    if previous:
        lines += ["", "Contre-visite : lors du contrôle précédent, ces problèmes avaient été relevés. Dis pour chacun s'il est corrigé :"]
        for pv in previous:
            lines.append(f"- {pv['point']} : {pv['explanation']}")
    lines += ["", "Photos (numérotées à partir de 0) :"]
    for i, ph in enumerate(photos):
        lines.append(f"- photo {i} : {ph['shot_label']}" + (f" — note du chef : {ph['note']}" if ph.get("note") else "")
                     + (f" — zone : {ph['zone']}" if ph.get("zone") else "") + (f" — prise le {ph['taken']}" if ph.get("taken") else ""))
    lang_name = "anglais" if lang == "en" else "français"
    lines += ["", f"Réponds uniquement par un objet JSON, textes en {lang_name}, phrases courtes et concrètes pour un non-spécialiste :",
              '{"meme_lieu": true|false (toutes les photos montrent le même ouvrage et le même chantier),',
              ' "points": [{"id": "<id du point>", "statut": "ok"|"a_verifier"|"probleme"|"non_visible", "confiance": 0..1,',
              '   "photo": <numéro de la photo qui montre le mieux le point, ou null>,',
              '   "zone": {"x": 0..1, "y": 0..1, "w": 0..1, "h": 0..1} (rectangle sur cette photo, proportions de la largeur et de la hauteur, ou null),',
              '   "constat": "ce que tu vois", "conseil": "ce qu\'il faut faire", "question": "question à poser au chef, ou null"}],',
              ' "autres_constats": [{"constat": "...", "gravite": "critique"|"majeur"|"mineur", "photo": <n>, "zone": {...}|null, "conseil": "..."}],',
              ' "mesures_lues": [{"mesure": "<id de la mesure>", "valeur_lue": "...", "coherent": true|false, "commentaire": "..."}],',
              ' "photos_inutilisables": [{"photo": <n>, "raison": "..."}],',
              ' "photos_a_ajouter": ["photo précise qui permettrait de conclure"],',
              ' "corrige": [{"point": "<id>", "statut": "corrige"|"pas_corrige"|"non_visible", "commentaire": "..."}],',
              ' "resume": "2 ou 3 phrases pour le propriétaire", "inspection_conseillee": true|false}']
    return "\n".join(lines)


def call_ai(o, images, photos, values, rules, previous, step_name, lang):
    content = []
    for i, img in enumerate(images):
        content.append({"type": "text", "text": f"Photo {i} :"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _b64(img)}})
    content.append({"type": "text", "text": build_prompt(o, photos, values, rules, previous, step_name, lang)})
    model = env("QUALITY_MODEL") or env("AI_MODEL", "claude-sonnet-5-5")
    code, body = http_json(API, {"model": model, "max_tokens": 4000, "messages": [{"role": "user", "content": content}]},
                           headers={"x-api-key": env("ANTHROPIC_API_KEY"), "anthropic-version": "2023-06-01"}, timeout=180)
    if code != 200 or not isinstance(body, dict):
        raise RuntimeError(f"API vision : {code} {str(body)[:200]}")
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError("Réponse de l'IA illisible")
    return json.loads(m.group(0))


def _zone(z):
    try:
        x, y, w, h = (max(0.0, min(1.0, float(z[k]))) for k in ("x", "y", "w", "h"))
    except (TypeError, KeyError, ValueError):
        return None
    if w <= 0.005 or h <= 0.005:
        return None
    return [round(x, 4), round(y, 4), round(min(w, 1 - x), 4), round(min(h, 1 - y), 4)]


def _photo_idx(v, n):
    try:
        i = int(v)
    except (TypeError, ValueError):
        return None
    return i if 0 <= i < n else None


def merge(o, ai, rules, n_photos, lang="fr"):
    """Fusionne regles et IA en une liste de points. La mesure prime sur l'IA quand elle est plus severe ;
    si l'IA voit un probleme que la mesure ne montre pas, le point passe a verifier."""
    fr = lang != "en"
    by_ai = {}
    for r in (ai or {}).get("points") or []:
        if isinstance(r, dict) and r.get("id") in {p["id"] for p in o["points"]}:
            by_ai[r["id"]] = r
    out = []
    rank = {"ok": 0, "non_visible": 0, "a_verifier": 1, "probleme": 2}
    for pt in o["points"]:
        a, rr = by_ai.get(pt["id"]), rules.get(pt["id"])
        row = {"point": pt["id"], "label": _p(pt["label"], lang), "severity": pt["severity"], "status": None, "source": None,
               "confidence": None, "photo": None, "zone": None, "explanation": "", "advice": "", "question": _p(pt["question"], lang) or None,
               "measure_note": rr[1] if rr else None, "extra": 0}
        if a:
            st = a.get("statut") if a.get("statut") in STATUSES else "a_verifier"
            row.update(status=st, source="ia", confidence=max(0.0, min(1.0, float(a.get("confiance") or 0))),
                       photo=_photo_idx(a.get("photo"), n_photos), explanation=str(a.get("constat") or "")[:600],
                       advice=str(a.get("conseil") or "")[:600], question=(str(a.get("question"))[:300] if a.get("question") else row["question"]))
            row["zone"] = _zone(a.get("zone")) if row["photo"] is not None else None
            if row["confidence"] < 0.5 and st in ("ok", "probleme"):
                row["status"] = "a_verifier"
        if rr:
            if row["status"] is None or rank[rr[0]] >= rank[row["status"]]:
                row["status"], row["source"] = rr[0], "mesure"
                row["explanation"] = (row["explanation"] + " " if row["explanation"] else "") + \
                    ((("Mesure : " if fr else "Measurement: ") + rr[1]))
            elif row["status"] == "probleme" and rr[0] == "ok":
                row["status"] = "a_verifier"
                row["explanation"] += (" La mesure saisie est pourtant correcte : vérifiez sur place." if fr
                                       else " Yet the measurement entered is fine: check on site.")
        if row["status"] is None:
            row["status"], row["source"] = "a_controler", "proprio"
        out.append(row)
    for x in (ai or {}).get("autres_constats") or []:
        if not isinstance(x, dict) or not x.get("constat"):
            continue
        sev = x.get("gravite") if x.get("gravite") in SEVERITY else "mineur"
        ph = _photo_idx(x.get("photo"), n_photos)
        out.append({"point": "autre", "label": ("Autre constat" if fr else "Other finding"), "severity": sev,
                    "status": "probleme" if sev == "critique" else "a_verifier", "source": "ia", "confidence": None,
                    "photo": ph, "zone": _zone(x.get("zone")) if ph is not None else None,
                    "explanation": str(x["constat"])[:600], "advice": str(x.get("conseil") or "")[:600], "question": None,
                    "measure_note": None, "extra": 1})
    return out


def score(points):
    """Note sur 100 des points juges (hors non visibles et a controler) et nombre de points juges."""
    num = den = 0
    for p in points:
        if p["status"] in ("non_visible", "a_controler"):
            continue
        w = SEVERITY.get(p["severity"], 1)
        den += w
        num += w * {"ok": 1.0, "a_verifier": 0.5, "probleme": 0.0}.get(p["status"], 0)
    return (round(100 * num / den) if den else None), sum(1 for p in points if p["status"] not in ("non_visible", "a_controler"))


def needs_inspection(points, ai):
    if (ai or {}).get("inspection_conseillee"):
        return True
    return any(p["status"] == "probleme" and p["severity"] == "critique" for p in points)


# --------------------------------------------------------------------------
# Photo annotee
# --------------------------------------------------------------------------
COLORS = {"probleme": (200, 40, 30), "a_verifier": (225, 140, 0), "ok": (20, 130, 70), "non_visible": (120, 120, 120),
          "a_controler": (120, 120, 120)}


def annotate(img, marks, max_side=1600):
    """marks : liste de (numero, statut, [x, y, w, h]). Rectangle et numero sur la photo."""
    im = img.convert("RGB")
    im.thumbnail((max_side, max_side))
    W, H = im.size
    d = ImageDraw.Draw(im)
    lw = max(3, W // 260)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", max(18, W // 40))
    except OSError:
        font = ImageFont.load_default()
    for num, status, z in marks:
        if not z:
            continue
        x, y, w, h = z
        box = [x * W, y * H, (x + w) * W, (y + h) * H]
        col = COLORS.get(status, (225, 140, 0))
        d.rectangle(box, outline=col, width=lw)
        label = str(num)
        tb = d.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        bx, by = box[0], max(0, box[1] - th - 2 * lw)
        d.rectangle([bx, by, bx + tw + 4 * lw, by + th + 2 * lw], fill=col)
        d.text((bx + 2 * lw, by + lw - tb[1] / 2), label, fill=(255, 255, 255), font=font)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def now_month():
    return datetime.utcnow().strftime("%Y-%m")
