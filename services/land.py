"""Accompagnement foncier : verifier le terrain avant de construire.

ChantierVrai ne certifie aucun titre. Il guide le proprietaire : ce que vaut son document, les verifications a faire
et aupres de qui, les pieces a garder, et un niveau de risque explique. Une verification par un professionnel
(notaire, geometre) peut etre demandee a l'equipe ChantierVrai, qui la confie a un partenaire.
Contenu indicatif, a faire relire par un professionnel du foncier ivoirien avant publication.
"""
import json
import math


def t(fr, en):
    return {"fr": fr, "en": en}


def _p(d, lang):
    return (d or {}).get(lang) or (d or {}).get("fr") or ""


# Document detenu -> (libelle, explication, risque de depart 0..4)
DOCS = {
    "titre_foncier": (t("Titre foncier", "Land title (titre foncier)"),
                      t("Le document le plus solide : le terrain est immatriculé au livre foncier. Il faut quand même vérifier qu'il est à jour, au nom du vendeur et sans hypothèque ni opposition.",
                        "The strongest document: the land is registered in the land register. You still need to check it is up to date, in the seller's name and free of mortgage or objection."), 1),
    "acd": (t("Arrêté de concession définitive (ACD)", "Final concession order (ACD)"),
            t("Un titre de propriété délivré par l'État. Vérifiez son authenticité auprès des services du ministère chargé de la construction et son inscription à la conservation foncière.",
              "A property title issued by the State. Check it is genuine with the ministry in charge of construction and that it is entered at the land registry."), 1),
    "acp": (t("Arrêté de concession provisoire (ACP)", "Provisional concession order (ACP)"),
            t("Une étape avant l'ACD : le droit n'est pas encore définitif et dépend de conditions (mise en valeur, paiements). Vérifiez où en est la procédure.",
              "A step before the ACD: the right is not final yet and depends on conditions (development, payments). Check where the procedure stands."), 2),
    "lettre_attribution": (t("Lettre d'attribution", "Allocation letter"),
                           t("Elle attribue le lot mais ne vaut pas titre de propriété. Il faut engager la procédure jusqu'à l'ACD, et vérifier que le lot n'a pas été attribué deux fois.",
                             "It allocates the plot but is not a property title. The procedure must be taken to the ACD, and you must check the plot was not allocated twice."), 3),
    "certificat_foncier": (t("Certificat foncier (terrain rural)", "Land certificate (rural land)"),
                           t("Il constate des droits coutumiers sur une terre rurale. Il doit ensuite être transformé en titre foncier dans les délais prévus par la loi.",
                             "It records customary rights on rural land. It must then be turned into a land title within the legal deadlines."), 2),
    "attestation_villageoise": (t("Attestation villageoise ou convention coutumière", "Village certificate or customary agreement"),
                                t("Document courant mais fragile : il ne protège pas contre une double vente ou une revendication familiale. Faites intervenir un géomètre et un notaire avant de construire.",
                                  "Common but fragile: it does not protect against a double sale or a family claim. Involve a surveyor and a notary before building."), 4),
    "acte_seul": (t("Acte de vente ou reçu seul", "Sale deed or receipt only"),
                  t("Un papier de vente sans titre derrière ne prouve pas que le vendeur était propriétaire. Risque élevé : ne construisez pas avant d'avoir un document de propriété.",
                    "A sale paper with no title behind it does not prove the seller owned the land. High risk: do not build before you have a property document."), 4),
    "aucun": (t("Aucun document", "No document"),
              t("Sans document, rien ne protège la construction. Commencez par obtenir un document de propriété.",
                "Without a document, nothing protects the building. Start by obtaining a property document."), 4),
}

# Verifications : (id, libelle, aupres de qui, poids dans la reduction du risque, documents concernes ou None = tous)
CHECKS = [
    ("copie", t("Copie lisible du document du terrain", "Readable copy of the land document"),
     t("À joindre ici : elle sert au dossier de crédit et au permis.", "Attach it here: it is used for the loan file and the permit."), 0, None),
    ("vendeur", t("Le vendeur est bien le titulaire du document", "The seller is the holder of the document"),
     t("Comparez le nom du document avec la pièce d'identité du vendeur ; pour une famille, tous les ayants droit doivent signer.",
       "Compare the name on the document with the seller's ID; for a family, all rightful owners must sign."), 1, None),
    ("etat_foncier", t("État foncier ou certificat de propriété récent", "Recent land status or ownership certificate"),
     t("À demander à la conservation foncière : il indique le propriétaire actuel, les hypothèques et les oppositions.",
       "Ask the land registry: it shows the current owner, mortgages and objections."), 1, ("titre_foncier", "acd")),
    ("authenticite", t("Authenticité de l'arrêté vérifiée", "Order verified as genuine"),
     t("Auprès des services du ministère chargé de la construction ou d'un notaire.", "With the ministry in charge of construction or a notary."), 1,
     ("acd", "acp", "lettre_attribution")),
    ("geometre", t("Bornage par un géomètre expert agréé", "Boundary survey by a licensed surveyor"),
     t("Il pose les bornes et remet un plan avec leurs coordonnées : saisissez-les ci-dessous pour vérifier que le chantier est bien sur votre terrain.",
       "They set the boundary markers and give a plan with their coordinates: enter them below to check the site is on your land."), 1, None),
    ("notaire", t("Vente passée devant notaire", "Sale signed before a notary"),
     t("Le notaire vérifie les titres, rédige l'acte et fait enregistrer la mutation à votre nom.",
       "The notary checks the titles, drafts the deed and has the transfer registered in your name."), 1, None),
    ("mutation", t("Mutation à votre nom enregistrée", "Transfer to your name registered"),
     t("Le titre ou l'arrêté doit être à votre nom, pas seulement l'acte de vente.", "The title or order must be in your name, not just the sale deed."), 1,
     ("titre_foncier", "acd", "acp")),
    ("voisinage", t("Pas de litige connu sur le terrain", "No known dispute over the land"),
     t("Renseignez-vous auprès des voisins, du chef de village ou de la mairie : bornes déplacées, autre acheteur, revendication familiale.",
       "Ask the neighbours, the village chief or the town hall: moved markers, another buyer, family claim."), 1, None),
    ("urbanisme", t("Terrain constructible", "Land can be built on"),
     t("À la mairie ou aux services de l'urbanisme : pas de zone non constructible, de servitude ou de réserve publique.",
       "At the town hall or planning department: no no-build zone, easement or public reserve."), 1, None),
]
RISK = {0: t("Faible", "Low"), 1: t("Modéré", "Moderate"), 2: t("Élevé", "High"), 3: t("Très élevé", "Very high"),
        4: t("Critique", "Critical")}
DOC_KINDS = ("titre", "etat_foncier", "bornage", "acte_vente", "piece_vendeur")
DOC_LABELS = {"titre": t("Document du terrain (titre, ACD, lettre…)", "Land document (title, ACD, letter…)"),
              "etat_foncier": t("État foncier ou certificat de propriété", "Land status or ownership certificate"),
              "bornage": t("Plan de bornage du géomètre", "Surveyor's boundary plan"),
              "acte_vente": t("Acte de vente notarié", "Notarised sale deed"),
              "piece_vendeur": t("Pièce d'identité du vendeur", "Seller's ID")}
CHECK_DOC = {"copie": "titre", "etat_foncier": "etat_foncier", "geometre": "bornage", "notaire": "acte_vente", "vendeur": "piece_vendeur"}


def applicable(doc_type):
    return [c for c in CHECKS if c[4] is None or doc_type in c[4]]


def assess(doc_type, done, flags):
    """Niveau de risque 0..4 et raisons. done : {check_id: bool}. flags : alertes calculees (hors terrain, surface, nom)."""
    if doc_type not in DOCS:
        return None, []
    base = DOCS[doc_type][2]
    checks = applicable(doc_type)
    weight = sum(c[3] for c in checks)
    got = sum(c[3] for c in checks if done.get(c[0]))
    level = base
    if weight and doc_type not in ("acte_seul", "aucun"):
        level = base - round(min(base, 2) * got / weight)     # les verifications retirent au plus 2 niveaux
        if doc_type == "attestation_villageoise" and got / weight < 1:
            level = max(level, 3)
    level += len(flags)
    return max(0, min(4, level)), flags


# --------------------------------------------------------------------------
# Bornes du geometre : le chantier est-il sur le terrain ?
# --------------------------------------------------------------------------
def parse_bornes(text):
    """« 5.35210, -3.88920 » par ligne -> [(lat, lng)]."""
    pts = []
    for line in (text or "").replace("|", "\n").splitlines():
        nums = [x for x in line.replace(",", " ").replace(";", " ").split() if x]
        if len(nums) >= 2:
            try:
                lat, lng = float(nums[0]), float(nums[1])
            except ValueError:
                continue
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                pts.append((lat, lng))
    return pts


def inside(lat, lng, poly):
    """Point dans le polygone (lancer de rayon)."""
    n, ok = len(poly), False
    j = n - 1
    for i in range(n):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            ok = not ok
        j = i
    return ok


def area_m2(poly):
    """Surface approchee du polygone (projection locale), en m2."""
    if len(poly) < 3:
        return None
    lat0 = sum(p[0] for p in poly) / len(poly)
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    pts = [(p[1] * kx, p[0] * ky) for p in poly]
    s = sum(pts[i][0] * pts[i - 1][1] - pts[i - 1][0] * pts[i][1] for i in range(len(pts)))
    return round(abs(s) / 2)


def same_name(a, b):
    import unicodedata
    def n(x):
        x = unicodedata.normalize("NFD", (x or "").lower())
        return sorted(w for w in "".join(c for c in x if unicodedata.category(c) != "Mn" and (c.isalnum() or c == " ")).split() if len(w) > 1)
    return bool(a and b) and (set(n(a)) <= set(n(b)) or set(n(b)) <= set(n(a)))


def flags_for(f, project, lang="fr", done=None):
    """Alertes calculees : noms differents, chantier hors des bornes, surface tres differente."""
    out = []
    fr = lang != "en"
    if f.get("holder_name") and f.get("seller_name") and not (done or {}).get("vendeur") and not same_name(f["holder_name"], f["seller_name"]):
        out.append("Le nom du vendeur ne correspond pas au titulaire du document." if fr
                   else "The seller's name does not match the holder of the document.")
    poly = parse_bornes(f.get("bornes"))
    if len(poly) >= 3 and project.get("lat") is not None:
        if not inside(project["lat"], project["lng"], poly):
            out.append("La position du chantier est en dehors des bornes du géomètre." if fr
                       else "The site position is outside the surveyor's markers.")
        a, decl = area_m2(poly), f.get("area_declared")
        if a and decl and abs(a - decl) / decl > 0.15:
            out.append((f"Surface mesurée par les bornes ({a} m²) très différente de la surface du document ({int(decl)} m²)." if fr
                        else f"Area measured from the markers ({a} m²) very different from the document's area ({int(decl)} m²)."))
    return out


def label(d, lang):
    return _p(d, lang)


def load(row):
    return json.loads(row["checks"] or "{}") if row and row["checks"] else {}


# --------------------------------------------------------------------------
# Carte des terrains : coordonnées des géomètres, chevauchements, références
# --------------------------------------------------------------------------
def utm_to_latlng(easting, northing, zone=30, north=True):
    """Coordonnées UTM (WGS84) -> (lat, lng). Les plans de géomètre en Côte d'Ivoire sont en UTM 30N
    (29N à l'ouest du méridien 6° O). Formules de Snyder, précision bien meilleure que le mètre."""
    a, f = 6378137.0, 1 / 298.257223563
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    k0 = 0.9996
    x = easting - 500000.0
    y = northing if north else northing - 10000000.0
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    t1 = math.tan(phi1) ** 2
    c1 = ep2 * math.cos(phi1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                              + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lng0 = math.radians((zone - 1) * 6 - 180 + 3)
    lng = lng0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(phi1)
    return math.degrees(lat), math.degrees(lng)


def parse_points(text, utm_zone=30):
    """Bornes saisies à la main : « lat, lng » (degrés) ou « X Y » en mètres UTM (repérés à leur grandeur).
    Renvoie (points [(lat, lng)], nombre de lignes ignorées)."""
    pts, bad = [], 0
    for line in (text or "").replace("|", "\n").splitlines():
        nums = []
        for tok in line.replace(";", " ").replace("\t", " ").split():
            tok = tok.strip().rstrip(",")
            if tok.count(",") == 1 and tok.count(".") == 0:      # « 5,3521 » écrit à la française
                tok = tok.replace(",", ".")
            for part in tok.split(","):
                try:
                    nums.append(float(part))
                except ValueError:
                    pass
        if len(nums) < 2:
            if line.strip():
                bad += 1
            continue
        u, v = nums[-2], nums[-1]                                # un numéro de borne en tête de ligne est ignoré
        if abs(u) > 1000 and abs(v) > 1000:                      # mètres UTM : X (est) puis Y (nord)
            lat, lng = utm_to_latlng(u, v, utm_zone)
        else:
            lat, lng = u, v
        if 3.5 <= lat <= 11.5 and -9.5 <= lng <= -1.5:           # Côte d'Ivoire et un peu autour
            pts.append((round(lat, 7), round(lng, 7)))
        else:
            bad += 1
    return pts, bad


def bbox(poly):
    return (min(p[0] for p in poly), max(p[0] for p in poly), min(p[1] for p in poly), max(p[1] for p in poly))


def overlap_m2(a, b, steps=48):
    """Surface commune approchée de deux polygones (grille de points sur la zone commune des deux cadres).
    Suffisant pour distinguer un vrai chevauchement (plusieurs m²) du bruit d'un clic sur la carte."""
    if len(a) < 3 or len(b) < 3:
        return 0
    la0, la1, lo0, lo1 = bbox(a)
    lb0, lb1, mo0, mo1 = bbox(b)
    s0, s1, w0, w1 = max(la0, lb0), min(la1, lb1), max(lo0, mo0), min(lo1, mo1)
    if s0 >= s1 or w0 >= w1:
        return 0
    hit = 0
    for i in range(steps):
        lat = s0 + (i + 0.5) * (s1 - s0) / steps
        for j in range(steps):
            lng = w0 + (j + 0.5) * (w1 - w0) / steps
            if inside(lat, lng, a) and inside(lat, lng, b):
                hit += 1
    cell = (s1 - s0) * 110540 * (w1 - w0) * 111320 * math.cos(math.radians((s0 + s1) / 2)) / (steps * steps)
    return round(hit * cell)


def norm_ref(ref):
    """« ACD n° 2019-0457 » et « acd 2019 0457 » -> « 20190457 » : on compare les chiffres et lettres utiles."""
    import unicodedata
    if not ref:
        return None
    x = unicodedata.normalize("NFD", ref.upper())
    import re
    x = "".join(c for c in x if c.isalnum())
    x = re.sub(r"^(?:ACD|ACP|TF|TITREFONCIER)?(?:NUMERO|NO|N)?(?=\d)", "", x)
    return x if len(x) >= 4 else None


# Preuves officielles (montants et délais indicatifs, d'après servicepublic.gouv.ci : à faire confirmer)
OFFICIAL = {
    "etat_foncier": (t("État foncier et état historique", "Land status and history"),
                     t("Conservation de la propriété foncière et des hypothèques (direction des impôts). Indique le propriétaire actuel, "
                       "les hypothèques et les oppositions. Environ 3 000 FCFA, 2 jours.",
                       "Land registry (tax directorate). Shows the current owner, mortgages and objections. About 3,000 FCFA, 2 days.")),
    "position": (t("Position foncière", "Land position"),
                 t("Ministère de la Construction, du Logement et de l'Urbanisme. À partir de la lettre d'attribution et d'un plan de situation. "
                   "Environ 5 000 FCFA par lot, 10 jours.",
                   "Ministry of Construction, Housing and Urban Planning. From the allocation letter and a location plan. About 5,000 FCFA per plot, 10 days.")),
    "adu": (t("Attestation de droit d'usage (ADU) : QR code", "Right-of-use certificate (ADU): QR code"),
            t("Depuis 2025, l'ADU porte un QR code : scannez-le avec votre téléphone, la page officielle indique si le terrain est conforme "
              "ou déjà vendu. Notez ici ce qu'elle affiche et joignez une capture.",
              "Since 2025 the ADU has a QR code: scan it with your phone and the official page shows whether the plot is compliant or already sold. "
              "Record what it shows here and attach a screenshot.")),
}
EF_RESULTS = {"libre": t("Aucune hypothèque ni opposition", "No mortgage or objection"),
              "hypotheque": t("Hypothèque inscrite", "Mortgage registered"),
              "opposition": t("Opposition ou litige inscrit", "Objection or dispute registered"),
              "autre_proprio": t("Le propriétaire n'est pas le vendeur", "The owner is not the seller")}
ADU_RESULTS = {"conforme": t("Conforme, non vendu", "Compliant, not sold"),
               "vendu": t("Déjà vendu", "Already sold"),
               "introuvable": t("Introuvable ou non conforme", "Not found or not compliant")}
POS_RESULTS = {"conforme": t("Conforme au lotissement approuvé", "Matches the approved subdivision"),
               "non_conforme": t("Non conforme ou lot attribué à un autre", "Not compliant or plot allocated to someone else")}
FRESH_DAYS = 90       # au-delà, un état foncier ne dit plus rien de la situation actuelle

LEVELS = {0: t("À compléter", "To complete"), 1: t("Déclaré", "Declared"), 2: t("Pièces fournies", "Documents provided"),
          3: t("Confirmé par l'administration", "Confirmed by the authorities")}
LEVEL_HELP = {
    0: t("Indiquez le document du terrain et placez les bornes sur la carte.", "Enter the land document and place the markers on the map."),
    1: t("Joignez la copie du document et la pièce d'identité du vendeur.", "Attach a copy of the document and the seller's ID."),
    2: t("Demandez un état foncier récent (ou scannez le QR code de l'ADU) : c'est la seule preuve qui vient de l'administration.",
         "Request a recent land status (or scan the ADU QR code): it is the only proof that comes from the authorities."),
    3: t("Une pièce officielle récente confirme le terrain. Faites quand même passer l'acte devant notaire.",
         "A recent official document confirms the plot. Still have the sale signed before a notary."),
}
