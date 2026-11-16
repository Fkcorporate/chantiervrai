"""Glossaire : les mots techniques de l'application, expliqués en une phrase simple.

Dans les pages, ui.js repère la première apparition de chaque mot dans le contenu et en fait
un mot souligné en pointillés : un toucher affiche l'explication dans une bulle.
Chaque entrée : (formes du mot en français, explication, formes en anglais, explication en anglais).
Les formes sont cherchées sans tenir compte des majuscules, en mot entier.
"""

ENTRIES = [
    (["séquestre"],
     "Compte tenu par un partenaire agréé : l'argent y est déposé avant les travaux et versé au chef "
     "seulement quand l'étape est validée.",
     ["escrow"],
     "Account held by a licensed partner: the money is deposited before the work and paid to the site "
     "manager only once the stage is approved."),
    (["paiement suivi"],
     "Vous payez vous-même (Mobile Money ou banque) ; ChantierVrai garde la trace et le bénéficiaire "
     "confirme qu'il a bien reçu.",
     ["tracked payment"],
     "You pay yourself (Mobile Money or bank); ChantierVrai keeps the record and the payee confirms receipt."),
    (["bon à payer"],
     "Document émis quand vous validez une étape : montant, bénéficiaire et numéro où payer.",
     ["payment voucher"],
     "Document issued when you approve a stage: amount, payee and the number to pay."),
    (["non-conformité", "non-conformités", "non conforme"],
     "Écart constaté par un contrôleur entre ce qui est construit et ce qui est prévu (plan, norme). "
     "À corriger avant de payer.",
     ["non-conformity", "non-conformities", "non-compliant"],
     "A gap found by an inspector between what is built and what was planned (drawings, standards). "
     "To be fixed before paying."),
    (["indice de confiance"],
     "Note sur 100 qui résume si le chantier est bien tenu : preuves régulières, contrôles faits, "
     "paiements tracés, qualité.",
     ["trust index"],
     "Score out of 100 summing up how well the site is run: regular proofs, checks done, payments traced, quality."),
    (["contrôleur habilité"],
     "Professionnel dont les qualifications ont été vérifiées par ChantierVrai : lui seul peut valider "
     "un contrôle technique obligatoire.",
     ["certified inspector"],
     "Professional whose qualifications ChantierVrai has checked: only they can sign off a mandatory technical check."),
    (["contrôle obligatoire", "contrôles obligatoires"],
     "Vérification à faire sur place avant de payer l'étape, par exemple le ferraillage avant de couler le béton.",
     ["mandatory check", "mandatory checks"],
     "On-site check required before paying the stage, for example the rebar before pouring concrete."),
    (["ferraillage"],
     "Les barres d'acier placées dans le béton. Une fois le béton coulé, on ne peut plus les voir : "
     "il faut les contrôler avant.",
     ["rebar"],
     "Steel bars placed in the concrete. Once it is poured they can no longer be seen: check them before."),
    (["enrobage"],
     "Épaisseur de béton qui recouvre l'acier. Trop faible, l'acier rouille et la structure s'affaiblit.",
     ["concrete cover"],
     "Thickness of concrete over the steel. Too thin, the steel rusts and the structure weakens."),
    (["procès-verbal de réception", "PV de réception"],
     "Document signé à la fin des travaux : vous acceptez l'ouvrage, avec ou sans réserves.",
     ["handover report"],
     "Document signed at the end of the works: you accept the building, with or without reservations."),
    (["réserves"],
     "Défauts notés à la réception, que l'entreprise doit corriger après la remise des clés.",
     ["reservations"],
     "Defects noted at handover that the contractor must fix after handing over the keys."),
    (["décompte"],
     "Calcul de ce qui est dû à l'entreprise : travaux réalisés moins ce qui a déjà été payé et les retenues.",
     ["payment statement"],
     "Calculation of what is owed to the contractor: work done minus what has been paid and any holdbacks."),
    (["maître d'ouvrage"],
     "La personne ou l'organisme qui fait construire et qui paie : vous, en général.",
     ["project owner"],
     "The person or body that commissions and pays for the building: usually you."),
    (["titre foncier"],
     "Le document le plus sûr pour un terrain en Côte d'Ivoire : il est inscrit au livre foncier "
     "et ne peut pas être contesté.",
     ["land title"],
     "The safest document for land in Côte d'Ivoire: registered in the land register and cannot be challenged."),
    (["ACD", "arrêté de concession définitive"],
     "Acte de l'État qui donne la pleine propriété d'un terrain, étape avant le titre foncier.",
     ["ACD", "final concession order"],
     "State act granting full ownership of a plot, the step before the land title."),
    (["attestation villageoise"],
     "Document du village qui reconnaît un droit coutumier sur le terrain. Il ne suffit pas seul : "
     "il faut faire avancer la procédure.",
     ["village certificate"],
     "Village document recognising customary rights to the land. Not enough on its own: the procedure must move forward."),
    (["bornage"],
     "Pose des bornes aux coins du terrain par un géomètre, pour fixer ses limites exactes.",
     ["boundary survey"],
     "A surveyor places markers at the corners of the plot to fix its exact limits."),
    (["taux d'endettement"],
     "Part de vos revenus mensuels qui part dans les crédits. Les banques regardent souvent un repère "
     "autour d'un tiers.",
     ["debt ratio"],
     "Share of your monthly income that goes to loans. Banks often look at a benchmark around one third."),
    (["apport"],
     "L'argent que vous mettez vous-même dans le projet, sans emprunter.",
     ["down payment"],
     "The money you put into the project yourself, without borrowing."),
    (["différé"],
     "Période au début du crédit pendant laquelle vous ne remboursez pas encore (ou seulement les intérêts).",
     ["deferral"],
     "Period at the start of the loan when you do not repay yet (or only the interest)."),
    (["trou de trésorerie"],
     "Mois où l'argent disponible ne suffit pas pour payer ce qui est prévu, même si le total finit par suffire.",
     ["cash gap"],
     "A month when the money available does not cover what is due, even if the total is enough in the end."),
    (["RCCM"],
     "Registre du commerce : le numéro qui prouve qu'une entreprise existe officiellement.",
     ["RCCM"],
     "Trade register: the number that proves a company officially exists."),
    (["DAO"],
     "Dossier d'appel d'offres : le document qui décrit un marché public et les règles pour y répondre.",
     ["DAO"],
     "Tender file: the document describing a public contract and the rules for bidding."),
]


def for_lang(lang):
    """[[formes…], explication] pour la langue demandée."""
    out = []
    for fr, fr_def, en, en_def in ENTRIES:
        out.append([en, en_def] if lang == "en" else [fr, fr_def])
    return out
