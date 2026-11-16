"""Guide d'utilisation de ChantierVrai, par profil, en francais et en anglais.

Chaque guide : titre, a qui il s'adresse, introduction, puis des sections (titre, etapes numerotees, conseil).
Les libelles entre guillemets sont ceux des boutons de l'application : a garder en phase avec les modeles.
"""


def t(fr, en):
    return {"fr": fr, "en": en}


def sec(title, steps, tip=None, img=None):
    return {"title": title, "steps": steps, "tip": tip, "img": img}


GUIDES = [
    {
        "slug": "proprietaire", "roles": ("proprio",),
        "title": t("Propriétaire ou maître d'ouvrage", "Owner or project owner"),
        "who": t("Vous faites construire, souvent à distance, et vous payez les étapes.",
                 "You are having a building built, often from abroad, and you pay for the stages."),
        "intro": t("Vous ne payez une étape que lorsque des photos vérifiées montrent qu'elle est faite. Le chef de chantier envoie les preuves, vous validez, puis vous payez.",
                   "You only pay for a stage once verified photos show it is done. The site foreman sends the proof, you approve, then you pay."),
        "sections": [
            sec(t("1. Créer votre compte et votre chantier", "1. Create your account and your site"), [
                t("Sur « Créer un compte », choisissez « Propriétaire ou maître d'ouvrage ».",
                  "On “Create an account”, choose “Owner or project owner”."),
                t("Touchez « Créer un chantier » : nom, adresse, budget total et date de début.",
                  "Tap “Create a site”: name, address, total budget and start date."),
                t("Placez le terrain : « Utiliser ma position actuelle » si vous y êtes, sinon saisissez latitude et longitude (relevées par le chef ou sur une carte). Les photos prises hors de cette zone seront refusées.",
                  "Set the plot: “Use my current location” if you are there, otherwise enter latitude and longitude (from the foreman or a map). Photos taken outside this area will be rejected."),
                t("Vérifiez les étapes proposées (fondations, murs, dalle…) et leur montant. Videz le nom d'une étape pour la supprimer.",
                  "Check the proposed stages (foundations, walls, slab…) and their amount. Clear a stage name to remove it."),
                t("Choisissez le mode de paiement. « Paiement suivi » est recommandé : vous payez vous-même, le bénéficiaire confirme la réception.",
                  "Choose the payment mode. “Tracked payment” is recommended: you pay yourself, the payee confirms receipt."),
            ], t("La liste « Bien démarrer » sur votre accueil se coche toute seule : suivez-la pour les premiers jours.",
                 "The “Getting started” list on your home page ticks itself: follow it for the first days."), "creer_chantier"),
            sec(t("2. Inviter votre chef de chantier", "2. Invite your site foreman"), [
                t("Ouvrez le chantier, onglet « Accueil » : le code d'invitation y est affiché.",
                  "Open the site, “Home” tab: the invitation code is shown there."),
                t("Envoyez-lui ce code (par WhatsApp par exemple). Il crée un compte « Chef de chantier » et touche « Rejoindre un chantier ».",
                  "Send him this code (by WhatsApp for example). He creates a “Site foreman” account and taps “Join a site”."),
                t("Son nom apparaît ensuite sur le chantier, avec son numéro Mobile Money.",
                  "His name then appears on the site, with his Mobile Money number."),
            ]),
            sec(t("3. Suivre le chantier", "3. Follow the site"), [
                t("« Accueil » : avancement vérifié, fin estimée, indice de confiance, activité récente et compte rendu de la semaine.",
                  "“Home”: verified progress, estimated end, trust score, recent activity and weekly report."),
                t("« Preuves » : toutes les photos et vidéos reçues, avec leur date, leur position et le résultat des contrôles.",
                  "“Proof”: all photos and videos received, with their date, location and check results."),
                t("« Vues » : images satellite mois par mois, drone et 3D.",
                  "“Views”: month-by-month satellite images, drone and 3D."),
                t("« Dossier » : documents, factures, contrôle des matériaux, intervenants, litiges.",
                  "“File”: documents, invoices, materials check, participants, disputes."),
                t("Les « Alertes » vous préviennent : étape à valider, preuve refusée, paiement, rapport de la semaine.",
                  "“Alerts” tell you when: a stage needs approval, proof was rejected, a payment, the weekly report."),
            ], t("Une preuve marquée « À vérifier » ressemble beaucoup à une photo déjà envoyée : comparez les deux avant de valider.",
                 "Proof marked “To check” looks very similar to a photo already sent: compare both before approving."), "proprio_accueil"),
            sec(t("4. Valider une étape", "4. Approve a stage"), [
                t("Quand le chef déclare une étape terminée, vous recevez une alerte. Ouvrez l'onglet « Étapes ».",
                  "When the foreman declares a stage finished, you get an alert. Open the “Stages” tab."),
                t("Regardez les preuves vérifiées et la « Vérification avant paiement (5 points) ».",
                  "Look at the verified proof and the “Check before paying (5 points)”."),
                t("Si tout est bon : « Valider l'étape et émettre le bon à payer ». Si des contrôles techniques obligatoires manquent, le paiement est bloqué : « Vérifier avant de payer » ouvre la page de l'étape.",
                  "If everything is fine: “Approve the stage and issue the payment order”. If mandatory technical checks are missing, payment is blocked: “Check before paying” opens the stage page."),
                t("Sinon : écrivez le motif et touchez « Refuser et renvoyer au chantier ». Le chef est prévenu et doit envoyer de nouvelles preuves.",
                  "Otherwise: write the reason and tap “Reject and send back to the site”. The foreman is notified and must send new proof."),
            ], t("Une étape critique (dalle, poteaux…) peut exiger un rapport d'inspection conforme avant d'être validée. Vous réglez cette règle dans « Dossier ».",
                 "A critical stage (slab, columns…) can require a compliant inspection report before approval. You set this rule in “File”."), "valider_etape"),
            sec(t("5. Payer et garder la trace", "5. Pay and keep a record"), [
                t("Après la validation, ouvrez « Bon à payer : déclarer le paiement ». Le bon indique le montant et le numéro Mobile Money du bénéficiaire.",
                  "After approval, open “Payment order: declare the payment”. It shows the amount and the payee's Mobile Money number."),
                t("Payez comme d'habitude (Wave, Orange Money, MTN, virement), puis saisissez le montant et la référence de la transaction, ou joignez le reçu.",
                  "Pay as usual (Wave, Orange Money, MTN, transfer), then enter the amount and the transaction reference, or attach the receipt."),
                t("Le bénéficiaire confirme « J'ai bien reçu ». Le paiement passe à « Payé et confirmé ».",
                  "The payee confirms “I received it”. The payment becomes “Paid and confirmed”."),
                t("La page « Paiements » du chantier tient le registre complet, exportable en CSV.",
                  "The site's “Payments” page keeps the full register, exportable as CSV."),
            ], t("ChantierVrai ne touche jamais votre argent en paiement suivi : il garde la preuve de ce qui est dû et de ce qui a été payé.",
                 "ChantierVrai never touches your money with tracked payment: it keeps proof of what is due and what was paid.")),
            sec(t("6. Ajouter la famille et les professionnels", "6. Add family and professionals"), [
                t("Onglet « Dossier », section « Intervenants et responsabilités ».",
                  "“File” tab, “Participants and responsibilities” section."),
                t("Choisissez le rôle, saisissez l'e-mail de son compte, touchez « Ajouter ».",
                  "Choose the role, enter their account email, tap “Add”."),
                t("Co-propriétaire ou responsable financier : la personne doit avoir un compte « Propriétaire ». Architecte, ingénieur, conducteur de travaux, entrepreneur, comptable : un compte « Professionnel du BTP ».",
                  "Co-owner or finance manager: the person needs an “Owner” account. Architect, engineer, works supervisor, contractor, accountant: a “Construction professional” account."),
                t("« Retirer » coupe son accès immédiatement.", "“Remove” cuts their access immediately."),
            ], t("Avec un responsable financier, chaque paiement demande deux validations : la vôtre, puis la sienne.",
                 "With a finance manager, each payment needs two approvals: yours, then theirs."), "intervenants"),
            sec(t("7. Matériaux, stock et commandes", "7. Materials, stock and orders"), [
                t("« Stock » : livraisons, consommations par étape, pertes et inventaire. Les écarts (acheté mais pas livré, plus consommé que prévu) vous sont signalés.",
                  "“Stock”: deliveries, use per stage, losses and stocktake. Gaps (bought but not delivered, more used than planned) are flagged to you."),
                t("Le chef peut proposer une commande à un fournisseur vérifié : vous l'approuvez avant qu'elle parte.",
                  "The foreman can propose an order to a verified supplier: you approve it before it is sent."),
                t("À la livraison, une photo sur le terrain est exigée ; vous payez le fournisseur après la réception confirmée.",
                  "On delivery, a photo on site is required; you pay the supplier after receipt is confirmed."),
            ]),
            sec(t("8. Inspection et litige", "8. Inspection and dispute"), [
                t("« Commander une inspection indépendante » : ChantierVrai envoie un inspecteur vérifié sur place, qui vous remet un rapport avec photos.",
                  "“Order an independent inspection”: ChantierVrai sends a verified inspector on site, who gives you a report with photos."),
                t("En cas de désaccord avec le chef, « Ouvrir un litige » : 5 jours d'échanges, puis décision motivée de la médiation ChantierVrai, et un recours possible.",
                  "If you disagree with the foreman, “Open a dispute”: 5 days of exchanges, then a reasoned mediation decision by ChantierVrai, and one appeal."),
            ]),
            sec(t("9. Contrôler la qualité d'un ouvrage", "9. Check the quality of a piece of work"), [
                t("Onglet « Étapes », « Contrôle qualité des ouvrages » : choisissez l'ouvrage (escalier, carrelage, douche, ferraillage…) puis « Ouvrir le contrôle ». Le chef reçoit la liste des photos à prendre.",
                  "“Stages” tab, “Quality check of the works”: choose the work (stairs, tiling, shower, reinforcement…) then “Open the check”. The foreman gets the list of photos to take."),
                t("Le chef prend les photos guidées sur place et saisit quelques mesures (hauteur de chaque marche, pente de la douche…). Les mesures sont contrôlées par des règles fixes.",
                  "The foreman takes the guided photos on site and enters a few measurements (height of each step, shower slope…). Measurements are checked by fixed rules."),
                t("« Lancer l'analyse » : chaque point est marqué « Semble correct », « À vérifier » ou « Problème probable », avec la photo annotée et ce qu'il faut faire.",
                  "“Run the analysis”: each point is marked “Looks right”, “To check” or “Likely problem”, with the annotated photo and what to do."),
                t("Sur chaque point : demandez une photo ou une réponse au chef, donnez votre propre avis ou acceptez-le tel quel. Un ingénieur ou un contrôleur du chantier peut donner son avis, qui prime.",
                  "On each point: ask the foreman for a photo or an answer, give your own opinion or accept it as is. An engineer or inspector on the site can give their opinion, which comes first."),
                t("Après correction, « Demander une contre-visite » : les points signalés sont recontrôlés et marqués corrigés ou non.",
                  "After the fix, “Request a follow-up check”: the reported points are checked again and marked fixed or not."),
            ], t("C'est une aide à la décision, pas un verdict : une photo ne mesure pas au millimètre et ne montre pas ce qui est caché. Un problème probable non résolu apparaît dans la vérification avant paiement ; pour la structure, commandez une inspection.",
                 "It is a decision aid, not a verdict: a photo does not measure to the millimetre and does not show what is hidden. An unresolved likely problem shows in the check before paying; for structural work, order an inspection.")),
            sec(t("Vérifier le terrain avant de construire", "Check the land before building"), [
                t("Onglet « Dossier », « Terrain : vérifier avant de construire » : indiquez le document que vous détenez (titre foncier, ACD, lettre d'attribution, attestation villageoise…).",
                  "“File” tab, “Land: check before building”: enter the document you hold (land title, ACD, allocation letter, village certificate…)."),
                t("ChantierVrai explique ce qu'il vaut et liste les vérifications à faire, et auprès de qui : état foncier, géomètre, notaire, voisinage, urbanisme.",
                  "ChantierVrai explains what it is worth and lists the checks to do, and with whom: land status, surveyor, notary, neighbours, planning."),
                t("Saisissez les bornes relevées par le géomètre : l'outil vérifie que le chantier est bien sur votre terrain et compare la surface.",
                  "Enter the markers recorded by the surveyor: the tool checks the site is on your land and compares the area."),
                t("Le niveau de risque baisse à mesure que vous cochez les vérifications. « Demander une vérification » vous met en relation avec un notaire ou un géomètre partenaire.",
                  "The risk level drops as you tick the checks. “Request a check” puts you in touch with a partner notary or surveyor."),
            ], t("Guide indicatif : ChantierVrai ne certifie aucun titre.", "Indicative guide: ChantierVrai certifies no title.")),
            sec(t("Comparer le plan et la réalité", "Compare the drawing and reality"), [
                t("« Plan et réalité » : ajoutez les éléments à compter (fenêtres, portes et pièces repris de la lecture du plan ; poteaux saisis par l'architecte ou l'ingénieur).",
                  "“Plan versus reality”: add the items to count (windows, doors and rooms from the drawing reading; columns entered by the architect or engineer)."),
                t("Le chef compte sur place et photographie chaque élément ; la photo est comptée par l'IA quand elle est activée. Un écart vous est signalé.",
                  "The foreman counts on site and photographs each item; the photo is counted by the AI when enabled. A gap is flagged to you."),
            ]),
            sec(t("Plan de financement et dossier de crédit", "Financing plan and loan file"), [
                t("Onglet « Étapes », « Plan de financement » : ajoutez vos sources (épargne, crédit, aide de la famille, tontine, transferts mensuels) avec leur montant et leur date d'arrivée.",
                  "“Stages” tab, “Financing plan”: add your sources (savings, loan, family support, tontine, monthly transfers) with their amount and arrival date."),
                t("ChantierVrai les confronte au planning des étapes et vous montre, mois par mois, s'il manquera de l'argent et quand.",
                  "ChantierVrai checks them against the stage schedule and shows you, month by month, whether money will be missing and when."),
                t("Enregistrez chaque montant reçu ; une source en retard ou un trou de trésorerie proche vous est signalé.",
                  "Record each amount received; a late source or an upcoming cash gap is flagged to you."),
                t("Indiquez vos revenus (en euros, dollars ou FCFA) : votre taux d'endettement est calculé comme le fera la banque.",
                  "Enter your income (in euros, dollars or FCFA): your debt ratio is calculated as the bank will."),
                t("« Dossier de crédit » : la liste des pièces demandées par les banques, celles qui manquent, et un dossier prêt à imprimer avec le budget, le planning, le plan de financement et l'avancement prouvé.",
                  "“Loan file”: the list of documents banks ask for, those missing, and a print-ready file with the budget, schedule, financing plan and proven progress."),
            ], t("Aucun lien avec votre banque, et aucun avis sur l'obtention du crédit. Les pièces du dossier restent privées : ni le chef ni les professionnels ne les voient.",
                 "No link with your bank, and no opinion on obtaining the loan. The file documents stay private: neither the foreman nor the professionals see them.")),
            sec(t("Messages et notes vocales du chef", "Messages and voice notes from the foreman"), [
                t("Le chef peut envoyer messages et notes vocales sur WhatsApp : ils arrivent dans « Notes du chantier », transcrits et résumés.",
                  "The foreman can send messages and voice notes on WhatsApp: they arrive in “Site notes”, transcribed and summarised."),
                t("Une note urgente (accident, arrêt du chantier, décision à prendre) vous est envoyée aussi par WhatsApp ou e-mail.",
                  "An urgent note (accident, site stoppage, decision needed) is also sent to you by WhatsApp or email."),
            ]),
            sec(t("10. Votre abonnement", "10. Your subscription"), [
                t("« Compte » puis « Mon abonnement et mes factures » : essai gratuit, choix de l'offre, rythme mensuel ou annuel, factures.",
                  "“Account” then “My subscription and invoices”: free trial, plan choice, monthly or yearly, invoices."),
                t("Les prix affichés sont TTC ; chaque facture détaille HT et TVA.",
                  "Prices shown include VAT; each invoice details the amount before tax and the VAT."),
            ]),
        ],
    },
    {
        "slug": "chef", "roles": ("chef",),
        "title": t("Chef de chantier", "Site foreman"),
        "who": t("Vous dirigez les travaux sur place et vous êtes payé à l'étape.",
                 "You run the works on site and get paid per stage."),
        "intro": t("Vos photos, prises dans l'application sur le terrain, prouvent votre travail. Plus elles sont nettes et régulières, plus vite vous êtes payé.",
                   "Your photos, taken in the app on site, prove your work. The clearer and more regular they are, the faster you get paid."),
        "sections": [
            sec(t("1. Rejoindre le chantier", "1. Join the site"), [
                t("Créez un compte « Chef de chantier » avec votre numéro de téléphone.",
                  "Create a “Site foreman” account with your phone number."),
                t("Sur l'accueil, saisissez le code donné par le propriétaire et touchez « Rejoindre ».",
                  "On the home page, enter the code given by the owner and tap “Join”."),
                t("Dans « Compte », renseignez votre numéro Mobile Money : il apparaît sur les bons à payer.",
                  "In “Account”, enter your Mobile Money number: it appears on payment orders."),
                t("La carte « Installer l'application » de « Compte » explique comment mettre ChantierVrai sur l'écran d'accueil du téléphone.",
                  "The “Install the app” card in “Account” explains how to put ChantierVrai on the phone's home screen."),
            ]),
            sec(t("2. Envoyer une preuve", "2. Send proof"), [
                t("Sur le terrain, ouvrez le chantier et allez à « Envoyer une preuve ».",
                  "On site, open the site and go to “Send proof”."),
                t("Autorisez la localisation et la caméra quand le téléphone le demande.",
                  "Allow location and camera when the phone asks."),
                t("Touchez « Prendre une photo » (ou « Filmer », 90 secondes maximum), choisissez la zone et ajoutez une courte description. La preuve est rattachée à l'étape en cours.",
                  "Tap “Take a photo” (or “Film”, 90 seconds maximum), choose the area and add a short description. The proof is attached to the current stage."),
                t("Touchez « Envoyer la preuve ». L'application vérifie la position, l'heure et que la photo est nouvelle.",
                  "Tap “Send proof”. The app checks the location, the time and that the photo is new."),
            ], t("Sans réseau, la photo reste sur le téléphone et part toute seule au retour du réseau (72 heures maximum). Les photos de la galerie, anciennes, prises ailleurs ou déjà envoyées sont refusées.",
                 "Without network, the photo stays on the phone and is sent automatically when the network returns (72 hours maximum). Photos from the gallery, old ones, taken elsewhere or already sent are rejected."), "envoyer_preuve"),
            sec(t("Ou tout envoyer par WhatsApp", "Or send everything through WhatsApp"), [
                t("Enregistrez le numéro WhatsApp de ChantierVrai affiché sur votre chantier. Écrivez depuis le numéro de votre compte.",
                  "Save the ChantierVrai WhatsApp number shown on your site. Write from your account's number."),
                t("Sur le terrain, partagez votre position (📎 > Position), puis envoyez vos photos : elles sont vérifiées comme dans l'application.",
                  "On site, share your location (📎 > Location), then send your photos: they are checked as in the app."),
                t("Envoyez une note vocale pour expliquer l'avancement, un problème ou un besoin de matériaux : le propriétaire la reçoit transcrite.",
                  "Send a voice note to explain progress, a problem or a materials need: the owner receives it transcribed."),
                t("Commandes : ETAPE (état du chantier), TERMINE puis OUI (déclarer l'étape finie), PAIEMENTS puis RECU <numéro> (confirmer un paiement), CHANTIER (changer de chantier), AIDE.",
                  "Commands: STAGE (site status), DONE then YES (declare the stage finished), PAYMENTS then RECEIVED <number> (confirm a payment), SITE (switch site), HELP."),
            ], t("WhatsApp retire la position et la date des photos : la position partagée doit dater de moins de 30 minutes. Si le propriétaire exige la caméra de l'application, les photos WhatsApp sont refusées.",
                 "WhatsApp removes location and date from photos: the shared location must be less than 30 minutes old. If the owner requires the app camera, WhatsApp photos are rejected.")),
            sec(t("3. Déclarer une étape terminée", "3. Declare a stage finished"), [
                t("Quand l'étape est finie et qu'au moins une preuve est vérifiée, touchez « Déclarer l'étape terminée ».",
                  "When the stage is done and at least one proof is verified, tap “Declare the stage finished”."),
                t("Le propriétaire est prévenu. Si des contrôles techniques sont obligatoires, ils doivent être faits avant le paiement.",
                  "The owner is notified. If technical checks are mandatory, they must be done before payment."),
                t("Si l'étape est refusée, le motif s'affiche : envoyez de nouvelles preuves puis déclarez de nouveau.",
                  "If the stage is rejected, the reason is shown: send new proof then declare again."),
            ], t("Le propriétaire ne répond pas ? Il est relancé automatiquement. À l'échéance, vous pouvez ouvrir un litige.",
                 "The owner does not answer? They get automatic reminders. At the deadline, you can open a dispute.")),
            sec(t("4. Confirmer vos paiements", "4. Confirm your payments"), [
                t("Menu « Paiements » : chaque paiement déclaré par le propriétaire y apparaît avec sa référence.",
                  "“Payments” menu: each payment declared by the owner appears with its reference."),
                t("Vérifiez sur votre téléphone, puis touchez « J'ai bien reçu ».",
                  "Check on your phone, then tap “I received it”."),
                t("Rien reçu, ou un montant différent ? « Signaler un problème » avec une explication.",
                  "Nothing received, or a different amount? “Report a problem” with an explanation."),
            ]),
            sec(t("5. Matériaux et stock", "5. Materials and stock"), [
                t("Onglet « Matériaux » : « Commander des matériaux » chez un fournisseur vérifié puis « Proposer au propriétaire ».",
                  "“Materials” tab: “Order materials” from a verified supplier then “Propose to the owner”."),
                t("À la livraison, le fournisseur prend la photo sur le terrain ; vous comptez et confirmez ce qui est arrivé.",
                  "On delivery, the supplier takes the photo on site; you count and confirm what arrived."),
                t("« Stock » : enregistrez chaque livraison faite ailleurs et chaque consommation, avec l'étape concernée.",
                  "“Stock”: record each delivery made elsewhere and each use, with the stage concerned."),
                t("Envoyez aussi les factures d'achats faits hors de l'application (photo ou PDF).",
                  "Also send invoices for purchases made outside the app (photo or PDF)."),
            ]),
            sec(t("Compter les livraisons et le plan", "Count deliveries and the drawing"), [
                t("À la livraison, rangez les matériaux comme indiqué (sacs en rangées, barres par le bout) et prenez la « Photo de comptage » sur la page de la commande.",
                  "On delivery, arrange the materials as shown (bags in rows, bars end-on) and take the “Count photo” on the order page."),
                t("Déclarez ce que vous avez compté. Si votre chiffre ne correspond pas au comptage de la photo, le propriétaire doit confirmer avant que le fournisseur soit payé.",
                  "Declare what you counted. If your number does not match the photo count, the owner must confirm before the supplier is paid."),
                t("« Plan et réalité » : pour chaque élément du plan, photographiez-le en entier et indiquez le nombre compté.",
                  "“Plan versus reality”: for each item on the drawing, photograph it whole and enter the number counted."),
            ]),
            sec(t("6. Photos guidées pour le contrôle qualité", "6. Guided photos for the quality check"), [
                t("Quand un contrôle qualité est ouvert, vous recevez une alerte. Ouvrez-le : chaque photo à prendre est décrite (quoi, d'où, avec quel instrument).",
                  "When a quality check is opened, you get an alert. Open it: each photo to take is described (what, from where, with which instrument)."),
                t("Choisissez la photo dans « Photo à prendre », puis « Prendre une photo ». Quand un mètre ou un niveau est demandé, il doit être lisible sur la photo.",
                  "Pick the photo in “Photo to take”, then “Take a photo”. When a tape or level is asked for, it must be readable in the photo."),
                t("Saisissez les mesures demandées et « Enregistrer les mesures ». Une photo floue ou sombre vous est signalée : reprenez-la.",
                  "Enter the requested measurements and “Save the measurements”. A blurred or dark photo is flagged to you: retake it."),
                t("Répondez aux questions du propriétaire dans « Échanges ». Après correction, refaites les photos de la contre-visite.",
                  "Answer the owner's questions in “Messages”. After the fix, retake the photos of the follow-up check."),
            ], t("Photographiez au bon moment : le ferraillage avant le béton, l'étanchéité avant le carrelage. Après, plus rien n'est visible.",
                 "Shoot at the right time: reinforcement before concrete, waterproofing before tiling. Afterwards nothing can be seen.")),
            sec(t("7. Votre réputation", "7. Your reputation"), [
                t("Dans « Compte », renseignez votre entreprise et votre RCCM puis demandez la vérification.",
                  "In “Account”, enter your company and registration number then request verification."),
                t("Vérifié, vous apparaissez dans l'annuaire des entrepreneurs avec l'historique mesuré par l'application et les avis des propriétaires.",
                  "Once verified, you appear in the contractors directory with the history measured by the app and owners' reviews."),
            ]),
        ],
    },
    {
        "slug": "professionnel", "roles": ("pro",),
        "title": t("Professionnel du BTP", "Construction professional"),
        "who": t("Architecte, ingénieur, bureau de contrôle, conducteur de travaux, entrepreneur ou comptable.",
                 "Architect, engineer, inspection body, works supervisor, contractor or accountant."),
        "intro": t("Le propriétaire vous ajoute à son chantier avec un rôle. Vous voyez le chantier et vous faites ce qui relève de votre métier ; vous ne validez pas les étapes et vous ne payez pas.",
                   "The owner adds you to their site with a role. You see the site and do what belongs to your trade; you do not approve stages or pay."),
        "sections": [
            sec(t("1. Créer votre compte", "1. Create your account"), [
                t("Sur « Créer un compte », choisissez « Professionnel du BTP », puis votre métier, votre entreprise et votre zone.",
                  "On “Create an account”, choose “Construction professional”, then your trade, company and area."),
                t("Donnez au propriétaire l'e-mail de ce compte : il vous ajoute depuis « Dossier », « Intervenants et responsabilités ».",
                  "Give the owner this account's email: they add you from “File”, “Participants and responsibilities”."),
                t("Ingénieur et bureau de contrôle : vos qualifications sont vérifiées par ChantierVrai avant que vous puissiez valider des contrôles.",
                  "Engineer and inspection body: your qualifications are checked by ChantierVrai before you can approve checks."),
            ], None, "inscription_pro"),
            sec(t("2. Ce que chaque métier fait", "2. What each trade does"), [
                t("Architecte : ajoute plans et documents, dépose la maquette numérique (IFC).",
                  "Architect: adds drawings and documents, uploads the digital model (IFC)."),
                t("Ingénieur : plans, maquette, capteurs ; saisit le résultat des contrôles techniques sur la page de l'étape.",
                  "Engineer: drawings, model, sensors; enters technical check results on the stage page."),
                t("Bureau de contrôle : « Saisir le résultat » puis « Enregistrer le contrôle » (conforme ou non conforme, rapport joint).",
                  "Inspection body: “Enter the result” then “Save the check” (compliant or not, report attached)."),
                t("Architecte, ingénieur, bureau de contrôle, conducteur de travaux : dans « Contrôle qualité », donnez votre avis de professionnel sur chaque point ; il prime sur l'analyse des photos.",
                  "Architect, engineer, inspection body, works supervisor: in “Quality check”, give your professional opinion on each point; it comes before the photo analysis."),
                t("Conducteur de travaux : tient le stock, suit les capteurs, demande les contrôles.",
                  "Works supervisor: keeps the stock, follows sensors, requests checks."),
                t("Entrepreneur : voit la situation des travaux, le décompte et le stock.",
                  "Contractor: sees the works status, the statement and the stock."),
                t("Comptable : voit le décompte et les paiements, télécharge l'« Export comptable (CSV) ».",
                  "Accountant: sees the statement and payments, downloads the “Accounting export (CSV)”."),
            ], t("Le propriétaire peut vous retirer à tout moment ; vous perdez alors l'accès au chantier.",
                 "The owner can remove you at any time; you then lose access to the site."), "vue_architecte"),
        ],
    },
    {
        "slug": "fournisseur", "roles": ("fournisseur",),
        "title": t("Fournisseur de matériaux", "Materials supplier"),
        "who": t("Quincaillerie ou dépôt qui livre les chantiers.", "Hardware store or depot that delivers to sites."),
        "intro": t("Les chefs de chantier commandent dans votre catalogue, le propriétaire approuve, vous livrez avec une photo sur place, vous êtes payé.",
                   "Site foremen order from your catalogue, the owner approves, you deliver with a photo on site, you get paid."),
        "sections": [
            sec(t("1. Ouvrir votre compte", "1. Open your account"), [
                t("Choisissez « Fournisseur de matériaux » : entreprise, RCCM, zone de livraison.",
                  "Choose “Materials supplier”: company, registration number, delivery area."),
                t("Acceptez les conditions fournisseur (commission ChantierVrai facturée chaque mois).",
                  "Accept the supplier terms (ChantierVrai commission invoiced monthly)."),
                t("Attendez la vérification : vous n'êtes proposé aux chantiers qu'ensuite.",
                  "Wait for verification: you are only offered to sites after that."),
            ]),
            sec(t("2. Remplir votre catalogue", "2. Fill your catalogue"), [
                t("« Mon catalogue » : « Ajouter un produit » avec l'unité et le prix livré.",
                  "“My catalogue”: “Add a product” with the unit and delivered price."),
                t("« Changer le prix » quand il bouge ; « Masquer » un produit en rupture.",
                  "“Change the price” when it moves; “Hide” an out-of-stock product."),
            ]),
            sec(t("3. Traiter une commande", "3. Handle an order"), [
                t("Une commande approuvée arrive dans « Mes commandes » : « Accepter la commande » avec la date de livraison, ou « Refuser » avec le motif.",
                  "An approved order arrives in “My orders”: “Accept the order” with the delivery date, or “Refuse” with the reason."),
                t("Sur le terrain, prenez la photo de livraison dans l'application : sa position est vérifiée.",
                  "On site, take the delivery photo in the app: its location is checked."),
                t("Le chef confirme ce qui est arrivé ; le paiement est déclaré, vous confirmez la réception dans « Paiements ».",
                  "The foreman confirms what arrived; the payment is declared, you confirm receipt in “Payments”."),
            ], t("Un problème signalé (mauvais ciment, sacs abîmés) suspend le paiement jusqu'à ce qu'il soit réglé.",
                 "A reported problem (wrong cement, damaged bags) suspends payment until it is settled.")),
        ],
    },
    {
        "slug": "inspecteur", "roles": ("inspecteur",),
        "title": t("Inspecteur indépendant", "Independent inspector"),
        "who": t("Vous contrôlez les chantiers pour le compte des propriétaires.", "You inspect sites on behalf of owners."),
        "intro": t("ChantierVrai vous attribue des inspections. Vous allez sur place, vous prenez les photos dans l'application et vous rendez un rapport.",
                   "ChantierVrai assigns inspections to you. You go on site, take the photos in the app and file a report."),
        "sections": [
            sec(t("1. Être vérifié", "1. Get verified"), [
                t("Créez un compte « Inspecteur indépendant » : zone, tarif, diplômes et expérience.",
                  "Create an “Independent inspector” account: area, rate, qualifications and experience."),
                t("ChantierVrai vérifie votre profil avant de vous attribuer des missions.",
                  "ChantierVrai checks your profile before assigning you missions."),
            ]),
            sec(t("2. Faire une inspection", "2. Carry out an inspection"), [
                t("Les demandes apparaissent dans « Mes inspections » : « Accepter » ou « Refuser ».",
                  "Requests appear in “My inspections”: “Accept” or “Refuse”."),
                t("« Itinéraire vers le terrain » vous guide jusqu'au chantier.",
                  "“Route to the plot” guides you to the site."),
                t("Sur place, envoyez vos photos : les mêmes contrôles s'appliquent (GPS, date, doublons).",
                  "On site, send your photos: the same checks apply (GPS, date, duplicates)."),
                t("Remplissez le rapport (avis, constats et recommandations) et touchez « Envoyer le rapport au propriétaire ».",
                  "Fill in the report (opinion, findings and recommendations) and tap “Send the report to the owner”."),
            ], t("Vous pouvez aussi être nommé « contrôleur habilité » sur un chantier : vous validez alors ses contrôles techniques.",
                 "You can also be named “approved inspector” on a site: you then approve its technical checks.")),
            sec(t("3. Être payé", "3. Get paid"), [
                t("Pour une inspection vendue par ChantierVrai, la rémunération vous est versée par ChantierVrai après le rapport.",
                  "For an inspection sold by ChantierVrai, your fee is paid by ChantierVrai after the report."),
            ]),
        ],
    },
    {
        "slug": "equipe", "roles": (), "staff": True,
        "title": t("Équipe ChantierVrai", "ChantierVrai team"),
        "who": t("Vos salariés : vérification, support, commercial, finance, et le fondateur.",
                 "Your staff: verification, support, sales, finance, and the founder."),
        "intro": t("Chaque membre ne voit dans « Admin » que les sections de son rôle. La double authentification est obligatoire.",
                   "Each member only sees the sections of their role in “Admin”. Two-factor authentication is mandatory."),
        "sections": [
            sec(t("1. Accéder à l'administration", "1. Access the administration"), [
                t("Créez votre compte dans l'application, puis le fondateur vous ajoute dans « Admin », « Équipe » avec votre rôle.",
                  "Create your account in the app, then the founder adds you in “Admin”, “Team” with your role."),
                t("Au premier accès, « Activer la double authentification » : scannez le QR code avec Google Authenticator ou Authy, saisissez le code à 6 chiffres.",
                  "On first access, “Enable two-factor authentication”: scan the QR code with Google Authenticator or Authy, enter the 6-digit code."),
                t("Gardez vos codes de secours en lieu sûr.", "Keep your backup codes somewhere safe."),
            ], t("Premier super-admin : commande « flask --app app creer-admin votre@email » sur le serveur, ou variable ADMIN_EMAILS avant l'inscription.",
                 "First super-admin: command “flask --app app creer-admin your@email” on the server, or the ADMIN_EMAILS variable before sign-up.")),
            sec(t("2. Vérification", "2. Verification"), [
                t("« Inspecteurs et fournisseurs à vérifier » : contrôlez diplômes, RCCM et références, puis validez ou refusez.",
                  "“Inspectors and suppliers to verify”: check qualifications, registration and references, then approve or refuse."),
                t("« Inspections indépendantes » : attribuez chaque demande payée à un inspecteur vérifié de la zone.",
                  "“Independent inspections”: assign each paid request to a verified inspector in the area."),
            ]),
            sec(t("3. Support et médiation", "3. Support and mediation"), [
                t("« Litiges » : lisez les échanges et les pièces, puis « Rendre la décision » (sens, montant retenu, motifs) sous 10 jours.",
                  "“Disputes”: read the exchanges and evidence, then “Give the decision” (outcome, amount, reasons) within 10 days."),
                t("« Modération du portail citoyen » : traitez les signalements avec une réponse publique, ou rejetez-les avec une note.",
                  "“Citizen portal moderation”: handle reports with a public answer, or reject them with a note."),
                t("« Comptes » : bloquer un compte. Le lien de mot de passe et le retrait de la double authentification d'un client sont réservés au fondateur.",
                  "“Accounts”: block an account. The password link and removing a customer's two-factor authentication are reserved for the founder."),
            ]),
            sec(t("4. Commercial et finance", "4. Sales and finance"), [
                t("Commercial : suivre l'activité des achats de matériaux et traiter les devis d'images satellite.",
                  "Sales: follow materials purchase activity and handle satellite image quotes."),
                t("Finance : « Abonnements » (revenu, factures à encaisser, « Marquer payée » à réception du virement) et « Commissions à facturer aux fournisseurs », avec un export CSV chaque mois.",
                  "Finance: “Subscriptions” (revenue, invoices to collect, “Mark as paid” when the transfer arrives) and “Commissions to invoice to suppliers”, with a CSV export every month."),
                t("Finance : « Inspecteurs à payer », enregistrer le versement à l'inspecteur après son rapport.",
                  "Finance: “Inspectors to pay”, record the payout to the inspector after their report."),
            ]),
            sec(t("5. Fondateur (super-admin)", "5. Founder (super-admin)"), [
                t("« Équipe » : ajouter un membre, changer son rôle, retirer son accès.",
                  "“Team”: add a member, change their role, remove their access."),
                t("Régler les tarifs, la TVA et les mentions de facture ; la validation automatique des étapes ; le séquestre. Faire une offre sur mesure à un client. Remettre un lien de mot de passe ou retirer la double authentification d'un client.",
                  "Set prices, VAT and invoice details; automatic stage approval; escrow. Make a custom offer to a customer. Give a customer a password link or remove their two-factor authentication."),
                t("Rendre la décision finale sur un recours de litige ; consulter le « Journal d'administration ».",
                  "Give the final decision on a dispute appeal; read the “Administration log”."),
            ]),
        ],
    },
]

FAQ = [
    (t("Ma photo est refusée, pourquoi ?", "My photo was rejected, why?"),
     t("Elle a été prise hors du terrain, sans GPS, il y a trop longtemps, depuis la galerie, ou elle ressemble à une photo déjà envoyée. Le motif s'affiche sous la preuve : reprenez la photo sur place, dans l'application.",
       "It was taken outside the plot, without GPS, too long ago, from the gallery, or it looks like a photo already sent. The reason appears under the proof: retake the photo on site, in the app.")),
    (t("Je n'ai pas de réseau sur le chantier.", "I have no network on site."),
     t("Prenez la photo quand même : elle est gardée sur le téléphone et envoyée automatiquement au retour du réseau, dans les 72 heures.",
       "Take the photo anyway: it is kept on the phone and sent automatically when the network returns, within 72 hours.")),
    (t("ChantierVrai garde-t-il mon argent ?", "Does ChantierVrai hold my money?"),
     t("Non, en paiement suivi vous payez directement le bénéficiaire. L'application garde la preuve de ce qui est dû et payé.",
       "No, with tracked payment you pay the payee directly. The app keeps proof of what is due and paid.")),
    (t("J'ai oublié mon mot de passe.", "I forgot my password."),
     t("Sur la page de connexion, « Mot de passe oublié ». Si vous n'avez plus accès à votre e-mail ou à votre application d'authentification, contactez le support.",
       "On the login page, “Forgot password”. If you no longer have access to your email or authenticator app, contact support.")),
    (t("Comment changer de langue ?", "How do I change the language?"),
     t("Le lien de langue est en bas de chaque page (Français ou English).",
       "The language link is at the bottom of every page (Français or English).")),
]


def _pick(d, lang):
    return d.get(lang) or d["fr"]


def localize(guide, lang):
    import re
    return {"slug": guide["slug"], "title": _pick(guide["title"], lang), "who": _pick(guide["who"], lang),
            "intro": _pick(guide["intro"], lang),
            "sections": [{"title": f"{i}. " + re.sub(r"^\d+\.\s*", "", _pick(s["title"], lang)), "steps": [_pick(x, lang) for x in s["steps"]],
                          "tip": _pick(s["tip"], lang) if s["tip"] else None, "img": s["img"]} for i, s in enumerate(guide["sections"], 1)]}


def catalog(lang, staff=False):
    return [{"slug": g["slug"], "title": _pick(g["title"], lang), "who": _pick(g["who"], lang)}
            for g in GUIDES if staff or not g.get("staff")]


def guide(slug, lang, staff=False):
    for g in GUIDES:
        if g["slug"] == slug and (staff or not g.get("staff")):
            return localize(g, lang)
    return None


def for_role(role):
    for g in GUIDES:
        if role in g["roles"]:
            return g["slug"]
    return "proprietaire"


def faq(lang):
    return [(_pick(q, lang), _pick(a, lang)) for q, a in FAQ]
