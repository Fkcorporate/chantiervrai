# ChantierVrai – application Android et iPhone

Application native construite avec Expo (React Native) : un seul code pour Android et iPhone. Elle parle au serveur ChantierVrai par son API (`/api/v1`).

## Ce que fait l'application

- **Connexion** avec la double authentification, et une langue au choix (français ou anglais, celle du téléphone par défaut).
- **Mes chantiers** : avancement vérifié, retard prévu, étape à valider.
- **Chef de chantier** :
  - photos et vidéos prises par la caméra de l'application ; la galerie est inaccessible (l'application ne demande même pas l'accès aux photos) ;
  - position GPS jointe à chaque preuve ; un faux GPS signalé par Android fait refuser la preuve ;
  - **sans réseau**, la preuve est gardée sur le téléphone et part toute seule au retour du réseau (72 heures maximum) ;
  - déclaration de fin d'étape.
- **Propriétaire** : progression, argent bloqué et versé, alertes, galerie des preuves avec les motifs de refus, validation (avec paiement depuis le séquestre) ou refus d'une étape.
- **Inspecteur** : photos d'inspection contrôlées sur le terrain.
- **Notifications sur le téléphone** (étape à valider, preuve refusée, paiement…). Toucher une notification ouvre le chantier.
- Les fonctions plus rares (satellite, documents, matériaux, litiges, administration) s'ouvrent sur le site web.

## Prérequis

- Node.js 20 ou plus récent.
- Un compte Expo gratuit : <https://expo.dev/signup>.
- Pour publier :
  - **Google Play** : compte développeur (25 $ une fois) ;
  - **App Store** : programme Apple Developer (99 $ par an). Pas besoin de Mac : la compilation se fait dans le cloud d'Expo (EAS).

## Installation

```bash
cd mobile
npm install
npx expo install --fix       # aligne les versions des modules sur la version d'Expo
npm install -g eas-cli
eas login
eas init                     # crée le projet Expo et renseigne extra.eas.projectId (notifications)
```

Dans `app.json`, mettez l'adresse de votre serveur dans `extra.apiUrl` (en HTTPS). Elle se change aussi depuis l'écran Réglages, pratique pour tester.

## Essayer sur un téléphone

```bash
eas build -p android --profile preview      # fichier APK à installer directement sur un Android
eas build -p ios --profile preview          # iPhone enregistrés dans votre compte Apple
```

Expo Go ne suffit pas : la caméra, les notifications et le stockage sécurisé demandent une vraie compilation, dite « development build ».

## Comptes pour les testeurs d'Apple et de Google

Sur le serveur en ligne (Shell Render) : `flask compte-revue`. La commande crée le chantier de démonstration s'il n'existe pas,
donne des mots de passe neufs aux comptes propriétaire et chef (et désactive le mot de passe public de la démonstration),
et élargit la zone du chantier de démonstration pour que les testeurs puissent prendre une photo de n'importe où.
Relancez-la après la revue pour changer les mots de passe.

## Suppression du compte

Réglages → Supprimer mon compte (mot de passe demandé). Exigée par l'App Store. Même règle que sur le site : impossible tant que
de l'argent reste au séquestre d'un chantier ou qu'un litige est en cours.

## Publier sur les stores

```bash
eas build -p android --profile production   # fichier AAB pour Google Play
eas build -p ios --profile production
eas submit -p android
eas submit -p ios
```

Les stores demandent :
- l'adresse de la politique de confidentialité : `https://votre-domaine/confidentialite` ;
- pour Google Play, le formulaire « Sécurité des données » : position précise (vérification des preuves), photos et vidéos (preuves), nom, e-mail et téléphone (compte) ; données chiffrées en transit ; suppression du compte possible depuis le site ;
- pour Apple, la même liste dans « App Privacy » ;
- un compte de démonstration pour les testeurs des stores (propriétaire et chef de chantier sur un chantier d'essai).

## Attestation de l'appareil (recommandé avant le lancement)

C'est le principal intérêt d'une application native contre la fraude : prouver que la photo vient de la vraie application, installée depuis le store, sur un téléphone non modifié. Le serveur est prêt (défi à usage unique, contrôle Play Integrity, statut affiché sur chaque preuve). Côté téléphone, il reste à brancher un module natif dans `src/services/device.js`, fonction `attest(nonce)` :

- **Android** : Play Integrity (par exemple le module `@expo/app-integrity` s'il est disponible pour votre version d'Expo, ou `react-native-google-play-integrity`). Côté serveur : `PLAY_INTEGRITY_PACKAGE=ci.chantiervrai.app` et `PLAY_INTEGRITY_SERVICE_ACCOUNT` (compte de service Google Cloud).
- **iPhone** : App Attest (module DeviceCheck). La vérification côté serveur (chaîne de certificats Apple) reste à ajouter dans `services/attestation.py`.

Tant que ce n'est pas branché, les preuves sont acceptées et marquées « attestation absente ». Une attestation présente mais fausse fait refuser la preuve.

## Tests

```bash
npm test          # traductions, file hors ligne, et parcours complet contre un vrai serveur ChantierVrai
npm run check     # vérification de la syntaxe
```

Le parcours complet lance le serveur Python du dossier parent : il faut Python et ses dépendances installés.

## Organisation

```
App.js                    navigation, envoi automatique des preuves au retour du réseau, notifications
src/core/                 logique sans dépendance au téléphone (testée avec Node)
  apiClient.js            appels à l'API du serveur
  queue.js                file d'attente hors ligne
  i18n.js                 textes français et anglais
src/services/             session, stockage sécurisé, fichiers, position, notifications, attestation
src/screens/              écrans
app.json, eas.json        configuration Expo et compilation
```

## Limites de cette version

- Testée sur ordinateur (logique, API, rendu des écrans), pas encore sur un vrai téléphone : faites un essai complet sur un Android et un iPhone avant la publication.
- Attestation de l'appareil à brancher (voir plus haut).
- La création de compte et le mot de passe oublié ouvrent le site web.
