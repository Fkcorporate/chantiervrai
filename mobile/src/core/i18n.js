// Textes de l'application mobile, en francais et en anglais.
// Les messages venant du serveur (refus, statuts, alertes) arrivent deja traduits.

const EN = {
  '%(n)s point(s) à voir': '%(n)s point(s) to review',
  'Voir les %(n)s autres': 'See the other %(n)s',
  'Réduire': 'Show less',
  'Votre décision': 'Your decision',
  '%(name)s terminée': '%(name)s completed',
  '%(n)s photo(s) vérifiée(s) sur le terrain': '%(n)s photo(s) verified on site',
  '%(n)s contrôle(s) obligatoire(s) à faire': '%(n)s mandatory check(s) to do',
  'Contrôles techniques conformes': 'Technical checks passed',
  'Glisser pour valider': 'Slide to approve',
  'Glisser pour payer': 'Slide to pay',
  'Refuser avec un motif': 'Reject with a reason',
  'Bonsoir': 'Good evening',
  'Bonjour': 'Good morning',
  'FCFA versés': 'FCFA paid',
  'Masquer le mot de passe': 'Hide password',
  'Afficher le mot de passe': 'Show password',
  'Enregistrement…': 'Recording…',
  'Faites construire au pays. Payez seulement ce qui est bâti.': 'Build back home. Pay only for what is built.',
  'Étape %(i)s sur %(n)s': 'Stage %(i)s of %(n)s',
  '%(n)s preuve(s) vérifiée(s) pour cette étape': '%(n)s verified proof(s) for this stage',
  'Étape déclarée terminée': 'Stage declared complete',
  'Connexion': 'Sign in',
  'E-mail': 'Email',
  'Mot de passe': 'Password',
  'Se connecter': 'Sign in',
  'Code de double authentification': 'Two-factor authentication code',
  'Mot de passe oublié ?': 'Forgotten password?',
  'Créer un compte': 'Create an account',
  'Suivez votre chantier à distance, avec des preuves vérifiées.': 'Follow your construction site remotely, with verified evidence.',
  'Mes chantiers': 'My sites',
  'Aucun chantier pour l\'instant.': 'No sites yet.',
  'Rejoindre un chantier': 'Join a site',
  'Code d\'invitation': 'Invitation code',
  'Rejoindre': 'Join',
  'Avancement vérifié': 'Verified progress',
  'Déclaré par le chantier': 'Declared by the site',
  'À valider': 'To approve',
  'Retard prévu : %(n)s j': 'Expected delay: %(n)s d',
  'Dans les temps': 'On schedule',
  'Alertes': 'Alerts',
  'Dernière photo vérifiée du chantier': 'Latest verified photo of the site',
  'Photo vérifiée': 'Verified photo',
  'Chantier': 'Site',
  'Pas encore de photo': 'No photo yet',
  'vérifiée': 'verified',
  'Photo': 'Photo',
  'Terminé': 'Completed',
  'j': 'd',
  'Retard prévu': 'Expected delay',
  'Étape à valider': 'Stage to approve',
  'Vos chantiers': 'Your sites',
  '%(n)s étape(s)': '%(n)s stage(s)',
  'sur un budget de': 'out of a budget of',
  'Argent suivi sur votre chantier': 'Money tracked on your site',
  'Argent suivi sur vos %(n)s chantiers': 'Money tracked on your %(n)s sites',
  'Missions': 'Assignments',
  'Commandes': 'Orders',
  'Chantiers': 'Sites',
  'Réglages': 'Settings',
  'Étape en cours': 'Current stage',
  'Toutes les étapes sont terminées.': 'All stages are completed.',
  'Paiement à la validation : %(n)s': 'Payment on approval: %(n)s',
  'Prendre une photo': 'Take a photo',
  'Filmer (90 s max)': 'Record video (90 s max)',
  'Arrêter': 'Stop',
  'Déclarer l\'étape terminée': 'Declare the stage complete',
  'Envoyez au moins une preuve vérifiée d\'abord.': 'Send at least one verified piece of evidence first.',
  'En attente de validation par le propriétaire.': 'Waiting for the owner\'s approval.',
  'Valider et payer': 'Approve and pay',
  'Refuser': 'Reject',
  'Motif du refus': 'Reason for rejection',
  'Référence du paiement (facultatif)': 'Payment reference (optional)',
  'Confirmer': 'Confirm',
  'Annuler': 'Cancel',
  'Preuves': 'Evidence',
  'Étapes': 'Stages',
  'Aucune preuve.': 'No evidence.',
  'Vérifiée': 'Verified',
  'Refusée': 'Rejected',
  'Bloqué sur le séquestre': 'Secured in escrow',
  'Valider et émettre le bon à payer': 'Approve and issue the payment order',
  'Vous payez ensuite le bénéficiaire, puis vous déclarez le paiement sur le site web.': 'You then pay the recipient and declare the payment on the website.',
  'Reste à payer': 'Left to pay',
  'Déjà versé': 'Already paid',
  'Fin estimée le %(d)s': 'Estimated end %(d)s',
  'Ouvrir sur le site web': 'Open on the website',
  'Satellite, documents, matériaux et inspections sont sur le site web.': 'Satellite, documents, materials and inspections are on the website.',
  'Recherche de votre position…': 'Finding your location…',
  'Position : précision %(n)s m': 'Location: accuracy %(n)s m',
  'Position refusée : la preuve sera refusée.': 'Location refused: the evidence will be rejected.',
  'Autorisez la caméra pour prendre les preuves.': 'Allow the camera to take evidence.',
  'Autoriser': 'Allow',
  'Description (facultatif)': 'Description (optional)',
  'Envoyer la preuve': 'Send the evidence',
  'Reprendre': 'Retake',
  'Envoi…': 'Sending…',
  'Preuve vérifiée et envoyée au propriétaire.': 'Evidence verified and sent to the owner.',
  'Preuve refusée': 'Evidence rejected',
  'Pas de réseau : preuve gardée sur le téléphone. Elle partira toute seule au retour du réseau.':
    'No network: evidence kept on the phone. It will be sent automatically when the network is back.',
  '%(n)s preuve(s) en attente de réseau': '%(n)s piece(s) of evidence waiting for network',
  '%(n)s preuve(s) envoyée(s) au retour du réseau': '%(n)s piece(s) of evidence sent when the network came back',
  'Notifications': 'Notifications',
  'Aucune notification.': 'No notifications.',
  'Tout marquer lu': 'Mark all as read',
  'Langue': 'Language',
  'Adresse du serveur': 'Server address',
  'Compte': 'Account',
  'Se déconnecter': 'Sign out',
  'Supprimer mon compte': 'Delete my account',
  'Vos données personnelles sont effacées et vous ne pourrez plus vous connecter. Les chantiers partagés avec d\'autres personnes restent visibles pour elles, sans votre nom.': 'Your personal data is erased and you will no longer be able to sign in. Sites shared with other people remain visible to them, without your name.',
  'Cette action est définitive. Confirmez avec votre mot de passe.': 'This cannot be undone. Confirm with your password.',
  'Supprimer définitivement': 'Delete permanently',
  'Suppression…': 'Deleting…',
  'Entrez votre mot de passe pour confirmer.': 'Enter your password to confirm.',
  'Votre compte a été supprimé et vos données personnelles effacées.': 'Your account has been deleted and your personal data erased.',
  'Me prévenir par WhatsApp': 'Notify me by WhatsApp',
  'Me prévenir par SMS': 'Notify me by SMS',
  'Me prévenir par e-mail': 'Notify me by email',
  'Téléphone (WhatsApp, Mobile Money)': 'Phone (WhatsApp, Mobile Money)',
  'Enregistrer': 'Save',
  'Enregistré.': 'Saved.',
  'Retour': 'Back',
  'Pas de connexion au serveur.': 'No connection to the server.',
  'Erreur': 'Error',
  'Inspection': 'Inspection',
  'Photos d\'inspection': 'Inspection photos',
  'Rédigez le rapport sur le site web.': 'Write the report on the website.',
  'Vidéo': 'Video',
  'Envoyée sans réseau': 'Sent without network',
  'Appareil certifié': 'Certified device',
  'Version': 'Version',
  'Indice de confiance': 'Trust index',
  'Contrôles obligatoires avant paiement': 'Mandatory checks before payment',
  'Mes commandes': 'My orders',
  'Aucune commande pour l\'instant.': 'No orders yet.',
  'Commandes de matériaux': 'Materials orders',
  'Commandez sur le site web : le fournisseur est payé seulement pour ce qui est livré et compté.':
    'Order on the website: the supplier is paid only for what is delivered and counted.',
  'Total': 'Total',
  'Date de livraison (AAAA-MM-JJ)': 'Delivery date (YYYY-MM-DD)',
  'Accepter la commande': 'Accept the order',
  'Photographiez les matériaux déchargés sur le chantier : la position GPS prouve la livraison.':
    'Photograph the materials unloaded on site: the GPS position proves the delivery.',
  'Itinéraire': 'Directions',
  'Photo de livraison': 'Delivery photo',
  'Approuver et envoyer': 'Approve and send',
  'Confirmer ce qui est arrivé': 'Confirm what arrived',
  'Le fournisseur est payé seulement pour ce que vous confirmez.': 'The supplier is paid only for what you confirm.',
  'Confirmer la réception': 'Confirm receipt',
  'Signaler un problème': 'Report a problem',
  'Signaler et suspendre le paiement': 'Report and hold the payment',
  'Cette version de l\'application est trop ancienne. Mettez-la à jour depuis le store.':
    'This version of the app is too old. Update it from the store.',
  'Paiements': 'Payments',
  'ChantierVrai ne touche pas l\'argent : le payeur paie directement, puis le bénéficiaire confirme.': 'ChantierVrai never handles the money: the payer pays directly, then the recipient confirms.',
  'À confirmer': 'To confirm',
  'À payer': 'To pay',
  'Historique': 'History',
  'Payé par %(who)s le %(d)s': 'Paid by %(who)s on %(d)s',
  'Vérifiez sur votre compte Mobile Money ou bancaire avant de confirmer.': 'Check your Mobile Money or bank account before confirming.',
  'Ce qui ne va pas': 'What is wrong',
  'Rien reçu ; montant différent…': 'Nothing received; different amount…',
  'Signaler au payeur': 'Report to the payer',
  'J\'ai bien reçu %(v)s': 'I received %(v)s',
  'Bénéficiaire : %(who)s': 'Recipient: %(who)s',
  '%(v)s déjà déclarés, en attente de confirmation.': '%(v)s already declared, awaiting confirmation.',
  'Montant payé (FCFA)': 'Amount paid (FCFA)',
  'Moyen de paiement': 'Payment method',
  'Référence de la transaction': 'Transaction reference',
  'Pour joindre la photo du reçu, utilisez le site web.': 'To attach a photo of the receipt, use the website.',
  'Déclarer le paiement': 'Declare the payment',
  'J\'ai payé : déclarer le paiement': 'I paid: declare the payment',
  'Aucun paiement pour l\'instant.': 'No payments yet.',
  '%(n)s paiement(s) à confirmer': '%(n)s payment(s) to confirm',
  'Vérifiez votre compte, puis confirmez la réception.': 'Check your account, then confirm receipt.',
};

const CATALOGS = { fr: {}, en: EN };
let current = 'fr';

export function setLang(lang) {
  current = CATALOGS[lang] ? lang : 'fr';
}

export function getLang() {
  return current;
}

// « 1 preuve(s) en attente » -> « 1 preuve en attente », « 3 preuves en attente » (comme sur le site).
// Français : singulier pour 0 et 1 ; anglais : singulier pour 1 seulement.
function pluralize(s, n) {
  const one = current === 'en' ? n === 1 : Math.abs(n) < 2;
  // « %(s)s » est un paramètre, pas une marque de pluriel : on garde le caractère qui précède et on saute les « %( ».
  return s.replace(/(^|[^%])\((s|x|es)\)/g, (m, pre, g) => pre + (one ? '' : g));
}

export function t(msg, params) {
  let s = (CATALOGS[current] && CATALOGS[current][msg]) || msg;
  if (params) {
    const nums = Object.values(params).filter((v) => typeof v === 'number');
    if (nums.length === 1) s = pluralize(s, nums[0]);
    Object.keys(params).forEach((k) => { s = s.split(`%(${k})s`).join(String(params[k])); });
  }
  return s;
}

export function missing(lang = 'en') {
  return Object.keys(EN).filter((k) => !CATALOGS[lang][k]);
}

export const KEYS = Object.keys(EN);
