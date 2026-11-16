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
