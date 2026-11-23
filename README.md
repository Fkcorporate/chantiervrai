# ChantierVrai

Suivi de chantier à distance : pour la diaspora qui fait construire au pays, et pour les grands chantiers publics. Preuves photo et vidéo vérifiées, étapes payées seulement après validation, inspection indépendante, portail citoyen.

Tout fonctionne **sans aucune clé** : les services externes (paiement, WhatsApp, satellite, IA) tournent alors en mode simulation ou en mode local, clairement signalé dans l'interface. Chaque service passe en réel dès que ses variables d'environnement sont renseignées.

## Ce que fait l'application

### Suivi diaspora
- **Comptes séparés** : propriétaire, chef de chantier, inspecteur indépendant. Invitation du chef par code.
- **Preuves photo et vidéo contrôlées** : position GPS (dans le fichier ou du téléphone) comparée au terrain, cohérence des deux positions, date de prise de vue (moins de 15 min), doublon exact (SHA-256), **doublon visuel** (photo d'écran, recadrage d'une ancienne preuve), vidéo de 90 s maximum.
- **Intelligence artificielle** :
  - toujours active, en local : empreinte visuelle de chaque photo, ressemblance avec les photos déjà vérifiées du chantier ;
  - avec `ANTHROPIC_API_KEY` : reconnaissance de l'étape visible, « même chantier ou non » par comparaison à une photo de référence, signes de fraude. Le propriétaire est alerté si une photo est douteuse.
- **Étapes et paiement** :
  - mode manuel : le propriétaire paie et note la référence ;
  - mode **séquestre** : le propriétaire dépose l'argent (Mobile Money ou carte via CinetPay), il est bloqué puis **versé automatiquement** au chef de chantier quand l'étape est validée. Validation impossible si le solde est insuffisant.
- **PV de réception** généré automatiquement à chaque étape validée (page imprimable en PDF, avec empreintes des preuves et avis d'inspection).
- **Contrôle des matériaux** : quantités et prix de référence prévus par étape, factures envoyées par le chef ou le propriétaire, lecture automatique par l'IA (ou saisie manuelle), alertes : quantité dépassée de plus de 15 %, prix supérieur de plus de 20 %, matériau non prévu, achat pour une étape pas commencée, étape payée avec moins de 60 % des matériaux facturés, facture en double.
- **Inspecteur indépendant à réserver** : profil (zone, tarif), demande par le propriétaire, acceptation, photos de terrain soumises aux mêmes contrôles, rapport et avis (conforme, avec réserves, non conforme).
- **Notifications WhatsApp, SMS, e-mail** (Twilio et SMTP) pour les événements importants, choisies par chaque utilisateur. Toujours visibles dans l'onglet Alertes.
- **Compte rendu automatique chaque semaine** : preuves, étapes, argent versé, prédiction, alertes, photos de la semaine. Envoyé par les canaux choisis.
- **Satellite dans l'application** : images mensuelles optiques (Sentinel-2) et **radar** (Sentinel-1, voit à travers les nuages), comparaison avant/après avec curseur, pourcentage de changement, carte des changements, alerte si le satellite ne voit rien bouger alors que des étapes sont déclarées.

### Achat direct des matériaux
La fraude la plus courante, ce sont les matériaux surfacturés ou jamais livrés. Avec l'achat direct, l'argent va au fournisseur, et seulement pour ce qui arrive vraiment sur le terrain.

- **Fournisseurs vérifiés** : une quincaillerie s'inscrit avec le rôle « Fournisseur de matériaux » (entreprise, RCCM, zone de livraison) et remplit son **catalogue** (`/fournisseur/catalogue`) : produits, unités, prix livrés. L'administrateur la vérifie avant qu'elle soit proposée aux chantiers.
- **Commande** : le chef de chantier **propose** une commande (onglet Matériaux) ; le propriétaire l'**approuve**, ou commande directement (Dossier › Contrôle des matériaux). Un avertissement s'affiche si un prix dépasse de plus de 20 % le prix de référence du devis.
- **Argent réservé** : en mode séquestre, le montant est réservé dès l'envoi. Il est libéré si le fournisseur refuse ou si le propriétaire annule.
- **Livraison prouvée** : le fournisseur accepte avec une date, puis photographie les matériaux déchargés **avec la caméra de l'application, sur le chantier**. La photo passe les mêmes contrôles que les preuves d'avancement : GPS dans le périmètre, horodatage, jeton de capture et anti-doublon. Une photo importée depuis la galerie ou prise ailleurs est refusée.
- **Réception comptée** : le chef (ou le propriétaire) confirme les quantités reçues ligne par ligne. Le fournisseur est **payé automatiquement sur son Mobile Money pour ce qui est reçu**, moins la commission. Ce qui manque reste au séquestre.
- **Facture automatique** : la commande reçue devient une facture vérifiée, qui alimente directement le contrôle des matériaux (devis contre réel).
- **Problème** : le chef ou le propriétaire signale un problème (mauvaise qualité, sacs abîmés). Le paiement est alors suspendu, et le propriétaire, le fournisseur et l'administrateur sont alertés.
- **Sans séquestre** : la commande est reçue puis marquée « à payer », et le propriétaire indique la référence de son paiement. Même chose si le versement Mobile Money échoue.
- **Revenu** : commission `COMMISSION_MATERIAUX` (3 % par défaut) prise sur la part du fournisseur, à chaque commande livrée. Le volume et les commissions apparaissent dans l'administration.
- **Mobile** : le fournisseur voit ses commandes, les accepte, ouvre l'itinéraire et prend la photo de livraison. Le chef confirme la réception depuis la fiche du chantier. Côté API : `GET /api/v1/commandes` et `POST /api/v1/commandes/<id>/<accepter|refuser|livraison|receptionner|probleme|approuver|annuler|payee>`.

### Intelligence et contrôle
- **Calculateur de matériaux** (`/calculateur`, et dans chaque chantier) : béton (poteaux, poutres, dalles, semelles), fondations filantes (terre à creuser, béton de propreté, semelle), fer à béton (poids, barres de 12 m), maçonnerie en parpaings, fabrication de parpaings, enduit, carrelage, peinture, avec les pertes. Le résultat s'ajoute au prévu d'une étape en un clic et sert au contrôle des factures et du stock. Les dosages sont des valeurs courantes, données à titre indicatif : la formulation du béton structurel, les dimensions des éléments porteurs et le ferraillage viennent des études et d'un ingénieur, ce que l'outil rappelle.
- **Stock du chantier** : livraisons reçues (celles des commandes ChantierVrai entrent toutes seules), consommations par étape, pertes, inventaire compté, seuils d'alerte. Pour chaque matériau, le tableau rapproche prévu, acheté, livré, utilisé et disponible, et signale les écarts : acheté mais pas livré, plus consommé que livré, consommation au-dessus du prévu, rupture. Les écarts d'inventaire et les stocks bas sont notifiés.
- **Contrôles techniques obligatoires** : chaque étape reçoit des points de contrôle tirés d'une bibliothèque selon son nom (implantation, fond de fouille, ferraillage, coffrage, validation avant bétonnage, essai d'écrasement du béton avec seuil en MPa, aplomb, installations, réception…). Seul un **contrôleur habilité** les saisit : l'inspecteur indépendant du chantier, ou un bureau de contrôle ajouté comme « contrôleur habilité » (compte inspecteur vérifié). Rapport ou PV joint, rangé dans les documents. **Le paiement d'une étape est bloqué** tant qu'un contrôle obligatoire n'est pas conforme. Sur un chantier privé sans responsable financier, le propriétaire principal peut passer outre : la dérogation est notée, signalée aux autres intervenants et baisse l'indice de confiance. Sur un marché public, c'est impossible.
- **Vérification avant paiement** (page de chaque étape) : 1. montant prévu au contrat et cumul payé ; 2. quantités prévues, achetées et utilisées ; 3. contrôles et inspection ; 4. preuves, factures et rapports ; 5. validations.
- **Circuit de paiement à deux niveaux** : en ajoutant un « responsable financier » au chantier, chaque paiement demande l'approbation du maître d'ouvrage puis celle du responsable financier, qui ne peut pas être la même personne. Séparation des rôles : le chef déclare, le contrôleur contrôle, le financier paie.
- **Situation des travaux et décompte** imprimable : montant du contrat, payé, reste à payer, état et contrôles de chaque étape, matériaux achetés en direct.
- **Indice de confiance du chantier** (0 à 100) : avancement vérifié, respect du calendrier, justification des dépenses, disponibilité des preuves, respect des procédures de contrôle, conformité technique documentée. Chaque critère donne son score, la raison et quoi faire ; un critère sans données est écarté. Affiché sur l'accueil du chantier, la liste des chantiers (avec la moyenne du portefeuille) et dans l'application mobile. Présenté comme un indicateur, pas comme une certification.

### Fiche du projet, profils, maquette, capteurs, Académie
- **Fiche du projet** (`/chantiers/<id>/fiche`) : type de projet (maison, immeuble R+n, résidence, école, santé, administratif, infrastructure, zone industrielle), niveaux, surfaces, titre foncier ou ACD, lot et îlot, commune, permis, budget et calendrier, intervenants, plans. **Parcelle dessinée** sur la vue satellite : les photos, livraisons et images de drone sont alors contrôlées sur la parcelle (30 m de tolérance) au lieu du cercle autour du point.
- **Profils professionnels** : compte « Professionnel du BTP » (architecte, ingénieur, bureau de contrôle, conducteur de travaux, entrepreneur, comptable). Le propriétaire les ajoute au chantier avec un rôle, et chacun n'accède qu'à ce qui le concerne :
  - l'architecte et l'ingénieur ajoutent plans et maquettes ;
  - l'ingénieur et le bureau de contrôle (vérifiés par l'administrateur) valident les contrôles techniques ;
  - le conducteur de travaux tient le stock et les capteurs ;
  - l'entrepreneur voit le décompte et le stock ;
  - le comptable voit le décompte et télécharge l'**export comptable CSV** (dépôts, paiements, achats, factures), lisible par Excel et les logiciels comptables.
- **Maquette numérique BIM/IFC** (`/chantiers/<id>/maquette`) : lecture des fichiers IFC2x3 et IFC4 sans dépendance (niveaux, altitudes, éléments par niveau, volumes de béton quand la maquette les contient). Chaque niveau se relie à une étape : la coupe du bâtiment se colore selon l'avancement vérifié. Chaque nouvelle version est comparée à la précédente (niveaux ajoutés ou supprimés, éléments en plus ou en moins). La vue 3D passe par l'export GLB, déjà pris en charge dans Vues.
- **Capteurs et météo** (`/chantiers/<id>/capteurs`) : humidité, vibration, déformation (fissuromètre), mouvement, température, pluie, vent. Chaque capteur a une clé et envoie ses mesures à `POST /api/v1/capteurs/mesures` (en-tête `X-Sensor-Key`, corps `{"value": 12.5}` ou `{"readings": [...]}`). Dès qu'une valeur sort des seuils, le propriétaire, le chef et les contrôleurs sont alertés (une alerte par passage en alarme). Les relevés manuels sont aussi possibles. Avec `METEO_AUTO=1`, la tâche `quotidien` relève la météo de la veille (Open-Meteo, gratuit) pour chaque chantier en cours.
- **Images satellite très haute résolution** (Pléiades Neo, SkySat, Vantor, 30 à 50 cm) : le propriétaire demande une image depuis Vues ; l'administrateur la commande chez le fournisseur (devis, contrat) puis la dépose. Elle s'ajoute à la comparaison mois par mois dans la couche « Très haute résolution ».
- **Académie du BTP** (`/academie`, publique) : 13 cours en français et en anglais :
  - construire une maison, un immeuble R+1 à R+5 ;
  - lire un plan, un plan de ferraillage ;
  - fondations, parpaings, dosage du ciment, préparation du béton, bétonnage des poteaux ;
  - contrôle des matériaux, malfaçons, gestion de chantier, contrôle de l'entrepreneur.

  Chaque cours a des schémas, une liste de contrôle, un quiz corrigé (progression gardée) et son calculateur. L'**assistant** retrouve dans les cours le passage qui répond à une question et le cite. Il n'invente rien, et pour une question de dimensionnement il renvoie vers l'ingénieur.

### Entrepreneurs vérifiés, assistant IA, lecture des plans
- **Entrepreneurs vérifiés** (`/entrepreneurs`) : un chef de chantier, ou un professionnel « entrepreneur », renseigne son entreprise et son RCCM dans son compte et demande la vérification ; l'administrateur la valide. Il apparaît alors dans l'annuaire, avec un **historique mesuré par l'application** sur tous ses chantiers ChantierVrai : chantiers terminés et en cours, montant suivi, retard moyen, indice de confiance moyen, non-conformités, photos refusées, **avis des propriétaires** (une note sur 5 et un commentaire par chantier, après le paiement d'une première étape). Le propriétaire invite un entrepreneur depuis son profil : celui-ci reçoit le code du chantier. La vérification confirme que l'entreprise existe ; elle ne garantit pas la qualité, ce que la page rappelle.
- **Assistant IA** (`/assistant`, avec `ANTHROPIC_API_KEY`) :
  - il répond **uniquement à partir de sources fournies à chaque question** : les passages des cours relus de l'Académie et, si l'utilisateur choisit un de ses chantiers, l'état mesuré de ce chantier (étapes, contrôles manquants, retard, stock, indice de confiance, alertes) ;
  - il cite ses sources, suit la conversation et renvoie vers l'ingénieur pour tout dimensionnement ;
  - il est limité à 40 questions par jour et par utilisateur ;
  - sans clé, ou si l'IA ne répond pas, il affiche les passages des cours.
- **Lecture des plans par IA** (`/chantiers/<id>/lecture-plan`) : l'IA lit un plan d'architecte en PDF ou en image (pièces, surfaces, longueurs de murs, portes, fenêtres, échelle). L'utilisateur corrige les valeurs, puis la maçonnerie, l'enduit, le carrelage et la peinture sont calculés et ajoutés au prévu des étapes choisies. L'IA ne dessine pas de plan et ne dit rien de la structure. Sans clé, les mesures se saisissent à la main et le calcul fonctionne de la même façon.

### Suivi de terrain : zones, 360°, quantités posées
- **Zones et étages** (`/chantiers/<id>/zones`) : le chantier se découpe en bâtiments, étages et zones, à la main ou depuis les niveaux de la maquette IFC. Chaque photo (champ « Zone » du formulaire d'envoi), chaque visite 360° et chaque quantité posée se rattache à une zone. Le tableau montre, zone par zone, l'avancement posé, les photos, la dernière visite.
- **Visites 360°** (`/chantiers/<id>/visites-360`) :
  - photos équirectangulaires (Insta360, Ricoh Theta, téléphone en mode 360) ;
  - contrôles à l'envoi : format 2:1, position GPS sur la parcelle, date de moins de 3 jours, photo ni renvoyée ni quasi identique ;
  - visionneuse panoramique (Pannellum) avec deux visites côte à côte qui tournent ensemble ;
  - mesure du pourcentage de l'image qui a changé depuis la visite précédente de la zone ;
  - avec `ANTHROPIC_API_KEY`, l'IA décrit ce qui a avancé et ce qu'il faut vérifier sur place.
- **Quantités installées** (`/chantiers/<id>/quantites`) : ouvrages prévus par zone, importés de la maquette (poteaux, poutres, dalles, murs, fenêtres par étage), saisis à la main ou envoyés par l'API. Le chef ou le conducteur déclare la quantité posée avec une photo vérifiée de moins de 7 jours ; le propriétaire ou le contrôleur valide. Seules les quantités validées comptent.
- **Rapport d'avancement physique** (`/chantiers/<id>/avancement-physique`, et `.csv`) : avancement physique (quantités validées) face à l'avancement financier et au planning, par zone et par ouvrage, imprimable.

### API ouverte et webhooks
- **Clés d'API** (Compte › API et webhooks, propriétaires) : une clé couvre tous les chantiers du propriétaire ou un seul, en lecture seule ou en lecture et écriture. Elle n'est affichée qu'une fois et seule son empreinte est gardée ; elle est révocable.
- **Points d'accès** `GET /api/ext/v1/chantiers[/<id>[/etapes|preuves|paiements|stock|avancement|anomalies]]` et `POST /api/ext/v1/chantiers/<id>/quantites-prevues` (import depuis un logiciel de devis ou de métré). En-tête `Authorization: Bearer cvk_…`. Documentation publique sur `/api/docs`.
- **Webhooks** : POST JSON vers une adresse https publique (les adresses internes sont refusées), signé HMAC-SHA256 avec horodatage (`X-ChantierVrai-Signature`, `X-ChantierVrai-Timestamp`). Événements : `etape.declaree`, `etape.payee`, `preuve.verifiee`, `preuve.refusee`, `controle.resultat`, `anomalie`, `commande.receptionnee`, `quantite.validee`. L'envoi se fait juste après l'action ; en cas d'échec, il est retenté 6 fois, de 1 min à 12 h, par la tâche `relancer`. Après 30 échecs de suite, le webhook est mis en pause. Un bouton « Tester » et le journal des derniers envois aident à brancher le logiciel.

### Grands chantiers
- **Carte de tous les chantiers**, couleur selon le retard prévu.
- **Prédiction des retards** : rythme réel mesuré sur les étapes terminées, appliqué à ce qui reste, plus les signaux d'arrêt (silence, preuves refusées, inspection non conforme). Fiabilité indiquée.
- **Drone et 3D** : photos de drone (position vérifiée, placées sur une carte), orthophotos, modèles 3D (GLB/GLTF) visibles en 3D dans le navigateur.
- **Documents** : DAO, contrats, PV, plans, permis, devis, avec empreinte et option de publication.
- **Marché public et SIGOMAP** : n° du marché et de l'appel d'offres, autorité contractante, attributaire, montant, lien vers le dossier SIGOMAP, **import d'un export CSV** (création ou mise à jour des chantiers). SIGOMAP ne propose pas d'accès direct pour les applications ; si un accès est ouvert un jour, l'import est le point à brancher.
- **Portail citoyen** (`/portail`, sans compte) : carte, avancement vérifié, budget payé, photos vérifiées, PV et documents publics, avis d'inspection, **signalements** avec photo et position, réponses publiques du maître d'ouvrage.

### Sécurité, confiance et exploitation
- **Comptes** : mot de passe oublié (lien à usage unique valable 1 h), mots de passe trop courants refusés, blocage après 5 essais ratés, **double authentification** par application (Google Authenticator…) avec 8 codes de secours, déconnexion de tous les appareils, sessions coupées après un changement de mot de passe.
- **Données personnelles** : acceptation des CGU et de la politique de confidentialité à l'inscription (modèles fournis, à faire relire), export des données en un clic, suppression du compte avec anonymisation.
- **Étapes modifiables** : renommer, changer le montant, ajouter, déplacer ou supprimer les étapes à venir. Le montant d'une étape déclarée ou payée est verrouillé. Le chef de chantier est prévenu de chaque changement.
- **Co-propriétaires** : la famille ou des associés suivent, valident et paient avec les mêmes droits ; ils reçoivent les mêmes alertes.
- **Administration** (`/admin`) : vérification des inspecteurs avant qu'ils soient proposés, blocage de comptes, lien de réinitialisation remis par le support, retrait de la double authentification, modération du portail citoyen, journal des actions.
- **Litiges et médiation** : le chef ou le propriétaire ouvre un litige sur une étape ; échanges dans l'application ; le médiateur voit les preuves et l'historique et tranche, ou les parties closent à l'amiable.
- **Paiement de l'inspecteur** depuis le séquestre, ou noté à la main.
- **Caméra intégrée** : la photo est prise dans l'application, sans accès à la galerie (option par chantier, activée par défaut). Un jeton émis par le serveur prouve que la photo est postérieure à l'ouverture de la page, et l'heure du téléphone est corrigée s'il est mal réglé. Un fichier importé présenté comme une capture est détecté.
- **Mode hors ligne** : sans réseau, la photo est gardée sur le téléphone avec son heure et sa position, puis envoyée automatiquement au retour du réseau (72 h maximum). Elle est marquée « envoyée sans réseau » pour le propriétaire.
- **Portail citoyen** : seules les photos choisies par le maître d'ouvrage sont publiées, avec les visages floutés automatiquement.
- **Exploitation** : relance automatique des messages, analyses et paiements interrompus par un redémarrage, sauvegardes avec rotation, en-têtes de sécurité HTTP.

### Applications mobiles
- **Applications natives Android et iPhone** (dossier `mobile/`, Expo / React Native) : caméra sans accès à la galerie, détection du faux GPS, envoi automatique des preuves prises sans réseau, notifications sur le téléphone, validation des étapes par le propriétaire. Compilation et publication : voir `mobile/README.md`.
- **API** `/api/v1` utilisée par les applications : connexion par jeton (double authentification comprise), chantiers, preuves, étapes, notifications, enregistrement du téléphone pour les notifications, défi d'attestation de l'appareil.
- **Application installable depuis le navigateur** (PWA), toujours disponible pour ceux qui n'installent rien depuis les stores.

### Application web et page produit
- **Visiteurs** : l'adresse du site (`/`, ou `/produit`) affiche la page de présentation du produit, en français et en anglais, avec de vraies captures de l'application.
- **Utilisateurs connectés** : la même adresse ouvre l'application web. Sur ordinateur, menu latéral, onglets du chantier en haut, chantiers en grille et tableau de bord sur deux colonnes. Sur téléphone, mise en page mobile.
- **Liens des stores** : quand les applications sont publiées, renseignez `ANDROID_STORE_URL` et `IOS_STORE_URL` ; les boutons apparaissent sur la page produit.
- **Démonstration** : `flask --app app demo` crée sur une base vide des comptes propriétaire, chef, inspectrice et fournisseur (quincaillerie@demo.chantiervrai.ci, avec son catalogue), un chantier en cours avec photos, paiements, inspection, compte rendu, une commande de matériaux livrée et payée, du stock, des contrôles techniques, son indice de confiance, une parcelle dessinée, un architecte, une maquette IFC en deux versions, des capteurs, des zones par étage, des quantités posées et deux visites 360°, et un chantier public. Mot de passe des comptes : `Demo-Chantier-2026`. À utiliser sur un serveur de démonstration, jamais sur la base réelle.

### Langues
Français et anglais. La langue est choisie d'après le navigateur ou le téléphone, se change en bas de chaque page et dans le compte, et suit chaque utilisateur : un propriétaire anglophone et un chef de chantier francophone sur le même chantier reçoivent chacun l'interface, les notifications (WhatsApp, SMS, e-mail, téléphone), le journal et le compte rendu de la semaine dans leur langue. Le PV de réception reste en français (document officiel en Côte d'Ivoire).

Traductions : `translations/en.json`. Après l'ajout d'un texte, `python3 tools_check_translations.py` liste ce qui manque.

## Installation

Python 3.10 ou plus récent. ffmpeg est recommandé pour les vidéos (vignette, lecture fiable des métadonnées) : `apt install ffmpeg` ou `brew install ffmpeg`.

```bash
cd chantiervrai
python3 -m venv venv
source venv/bin/activate          # Windows : venv\Scripts\activate
pip install -r requirements.txt
export SECRET_KEY="une-longue-phrase-secrete-a-changer"
python3 app.py
```

Ouvrez http://127.0.0.1:5000. La base de données et les fichiers sont dans `instance/` (à sauvegarder). Une base existante de la version précédente est mise à jour automatiquement au démarrage.

### Recours, litiges, inspections et portail citoyen
- **Validation automatique (option, désactivée par défaut)** : le super-admin la propose (Admin → Validation automatique des étapes, délai réglable de 5 à 30 jours, 7 par défaut). Le propriétaire l'accepte ou non, chantier par chantier, avec un texte d'acceptation explicite ; le chef voit la règle sur son chantier. Relances datées à J+2, puis 3 jours et 1 jour avant l'échéance, avec la possibilité de refuser ou d'ouvrir un litige. Jamais sans les contrôles obligatoires, sans l'inspection exigée, ou avec un litige ouvert ; jamais en séquestre. Sans l'option, le propriétaire est relancé et le chef est invité à ouvrir un litige à l'échéance. Le propriétaire ne peut retirer l'option que si aucune étape n'attend sa réponse. Clause dans les conditions d'utilisation.
- **Inspection obligatoire sur les étapes critiques (réglable par chantier)** : fondations, structure, élévation, dalle, plancher, charpente, toiture. Cochée par défaut pour les chantiers publics (toujours obligatoire) et l'offre Entreprise, proposée et recommandée aux particuliers. Une étape critique ne se valide (ni à la main, ni automatiquement) qu'après un rapport d'inspection conforme.
- **Litiges** : 5 jours d'échanges entre les parties (ou médiation demandée plus tôt), puis décision écrite et motivée de la médiation (support) sous 10 jours : sens de la décision, montant retenu. Chaque partie peut faire **un recours** sous 7 jours ; le fondateur (super-admin) rend la décision finale. Pièces recevables : preuves vérifiées, PV, rapports d'inspection, bons à payer et paiements, historique, messages.
- **Inspection indépendante vendue par ChantierVrai** : prix fixe TTC payé à ChantierVrai (50 000 FCFA par défaut), inspecteur vérifié attribué par l'équipe (vérification ou support), rémunéré par ChantierVrai (35 000 FCFA par défaut) après son rapport ; la Finance enregistre le versement. Si l'inspecteur refuse, la demande revient à l'attribution. Le propriétaire ne choisit ni ne paie l'inspecteur.
- **Portail citoyen** : statuts Reçu → Pris en charge → Traité (réponse publique obligatoire) ; rappel au maître d'ouvrage à J+5, alerte au support à J+10 ; la modération écarte un signalement injurieux, hors sujet ou exposant des données personnelles, avec un motif.
- **Conditions fournisseur** : acceptées à l'inscription (commission, facturation mensuelle, impayés) ; un fournisseur qui ne les a pas acceptées n'est pas proposé aux chantiers. Page `/fournisseur/conditions`.
- **Suppression de compte** : les données personnelles sont effacées (nom, e-mail, téléphone, 2FA) ; les preuves, PV, paiements et l'historique restent attachés au chantier sous « Compte supprimé ». Suppression impossible pendant un litige ouvert ou en recours.

Toutes ces échéances tournent dans la tâche `flask --app app quotidien`, avec les relances de paiement et les abonnements.

### Recette en conditions réelles
`python3 recette/recette.py` lance ChantierVrai comme en production (vrai serveur HTTP, double authentification de l'équipe et facturation appliquées), puis :
1. joue un chantier complet avec tous les acteurs : propriétaire dans un vrai navigateur (Chrome), chef et inspectrice par l'API de l'application mobile, équipe ChantierVrai avec 2FA, temps simulé pour les relances et le litige ;
2. envoie 220 vraies et fausses photos (hors zone, sans GPS, faux GPS, ancienne, galerie, jeton inventé, doublon, recadrage, photo d'écran…) et mesure ce qui est accepté, signalé ou refusé ;
3. mesure les temps de réponse avec 120 chantiers et 3 000 preuves, à 5 puis 20 utilisateurs simultanés.

Résultats dans `recette/sortie/resultats.json`, captures d'écran comprises. Il faut Chrome et Playwright.

### Abonnements : comment ChantierVrai est payé
Seuls les propriétaires paient ; le chef de chantier, les inspecteurs, les fournisseurs et les professionnels invités sont gratuits.

| Offre | Chantiers en cours | Prix par défaut (TTC) |
|---|---|---|
| Essai gratuit | 1 | 30 jours offerts à l'inscription |
| Essentiel | 1 | 15 000 FCFA TTC / mois |
| Pro | 5 | 45 000 FCFA TTC / mois |
| Entreprise | illimité | sur devis (offre sur mesure) |

Paiement annuel : 12 mois pour le prix de 10. Les prix sont saisis **TTC** (ce que le client paie) ; chaque facture détaille HT et TVA (18 % par défaut). Les prix, le taux de TVA, les mentions du vendeur (raison sociale, RCCM, numéro de compte contribuable) et les coordonnées bancaires se règlent dans **Admin → Tarifs, TVA et mentions de facture** (super-admin). Faites valider la TVA et les mentions par votre comptable.

- **Factures** numérotées `CV-AAAA-0001`, imprimables en PDF, payables en ligne (Mobile Money ou carte via CinetPay ; simulation sans clés) ou par virement validé par le rôle Finance.
- **Renouvellement** : la facture part 7 jours avant l'échéance ; relances 3 jours avant, puis 3 et 10 jours après ; « paiement en retard » à l'échéance, **suspension** 15 jours après. Tâche `flask --app app quotidien`.
- **Suspension** : seules la création de chantiers, la commande d'images satellite et la création de clés d'API sont bloquées. Les chantiers en cours, les preuves, les paiements et l'export des données continuent : on ne prend jamais les données en otage.
- **Résiliation** à l'échéance, par le client. **Offre sur mesure** (prix, nombre de chantiers, mois offerts) par le super-admin.
- **Finance** : revenu mensuel récurrent, encaissements du mois, factures à encaisser, dernières factures payées.

La facturation s'applique en production ; en test, elle s'active avec `BILLING_ENFORCED = True`.

### Terrain, livraisons, plan et réalité
- **Accompagnement foncier** (`services/land.py`, page « Terrain : vérifier avant de construire », propriétaire seulement) : document détenu (titre foncier, ACD, ACP, lettre d'attribution, certificat foncier, attestation villageoise, acte seul), ce qu'il vaut, vérifications à faire et auprès de qui, pièces privées (reprises dans le dossier de crédit). Bornes du géomètre : chantier dans le terrain ou non, surface calculée comparée au document. Nom du vendeur comparé au titulaire. Niveau de risque de faible à critique, expliqué. Demande de vérification par un notaire ou géomètre partenaire, traitée par l'équipe « vérification » dans l'administration. Contenu indicatif à faire relire par un professionnel du foncier ivoirien.
- **Comptage des livraisons** (`services/counting.py`) : guide de photo par matériau (sacs en rangées, barres par le bout, agglos par rangs…), « Photo de comptage » du chef sur la page de la commande, comptage par l'IA sur les photos de livraison et de comptage (sable et gravier au volume exclus). Trois chiffres : commandé, compté sur la photo, déclaré reçu. Si le chef déclare autre chose que la photo (IA confiante à 60 % au moins, tolérance 2 % au-delà de 50 unités, au chiffre près en dessous), la commande passe en litige, le paiement du fournisseur attend la décision du propriétaire.
- **Plan et réalité** : éléments à compter repris de la lecture du plan (fenêtres, portes, pièces) ou saisis par l'architecte, l'ingénieur, le contrôleur ou le conducteur de travaux (poteaux…). Le chef compte et photographie ; l'IA compte la photo. Statut conforme, écart avec le plan, ou à vérifier si la photo contredit le chef ; le propriétaire est prévenu.

### WhatsApp pour le chef de chantier
- Le chef écrit au numéro WhatsApp de ChantierVrai depuis le numéro de son compte : il est reconnu, son chantier choisi (ou proposé s'il en a plusieurs).
- **Photos** : WhatsApp retire la position et la date des fichiers. La position est celle que le chef partage dans le fil (moins de 30 minutes d'écart, photos gardées en attente sinon), la date celle de réception. Les mêmes contrôles s'appliquent ensuite (distance au terrain, doublons, photo d'écran). Ces preuves sont marquées « Reçue par WhatsApp » ; un chantier qui exige la caméra de l'application les refuse. Les vidéos restent dans l'application.
- **Notes vocales et messages** : gardés, transcrits (`OPENAI_API_KEY`, modèle `TRANSCRIBE_MODEL`, whisper-1 par défaut), résumés et classés (avancement, problème, matériaux, question) avec l'IA (`ANTHROPIC_API_KEY`), sinon par mots-clés. Une note urgente part aussi par WhatsApp ou e-mail. Page « Notes du chantier » et carte sur l'accueil du propriétaire.
- **Commandes** : AIDE, ETAPE, TERMINE puis OUI (déclarer l'étape), PAIEMENTS puis RECU <n> ou PROBLEME <n> <explication>, CHANTIER (changer de chantier). En anglais aussi.
- **Branchement** : le même compte Twilio que les alertes (`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, numéro WhatsApp Business validé par Meta). Dans Twilio, « A message comes in » → `https://<domaine>/whatsapp/entrant` (POST). Signature `X-Twilio-Signature` vérifiée ; derrière un proxy, `TWILIO_WEBHOOK_URL` = adresse publique exacte. `WHATSAPP_DISPLAY_NUMBER` : numéro affiché aux chefs.
- Sans Twilio : **simulateur** `/whatsapp/simulateur` (chef connecté, ou super-admin pour n'importe quel numéro), mêmes règles et mêmes réponses.

### Plan de financement et dossier de crédit
- Sans lien avec une banque. Le propriétaire déclare ses **sources** : épargne, transferts mensuels, crédit bancaire, microfinance (taux, durée, différé, mensualité calculée), famille, tontine, vente d'un bien. Il enregistre ce qu'il reçoit et ses **autres coûts** (terrain, notaire, permis, raccordements, imprévus).
- **Trésorerie mois par mois** : entrées prévues et reçues face aux étapes (à leur fin prévue) et aux coûts ; premier trou de trésorerie, manque le plus fort, manque global, sources en retard. Alerte une fois par mois dans la tâche quotidienne quand un trou approche (2 mois) ou qu'une source est en retard.
- **Revenus et taux d'endettement** : revenus en FCFA, euro (parité fixe 655,957) ou autre devise (taux saisi), charges, mensualités ; repère courant d'environ 33 % affiché comme tel.
- **Dossier de crédit** : pièces habituellement demandées (identité, bulletins, contrat, avis d'imposition, relevés, titre du terrain, permis, plans, devis, apport, titre de séjour pour la diaspora…), fournies ou manquantes ; budget, planning, plan de financement et avancement prouvé repris automatiquement ; dossier imprimable ou enregistrable en PDF. Les pièces sont privées (propriétaire, co-propriétaires, responsable financier ; comptable du chantier en lecture du plan).
- Mentions : aucun avis sur l'obtention d'un crédit ; ChantierVrai n'est pas intermédiaire bancaire (à faire confirmer par un juriste avant tout partenariat rémunéré avec une banque).

### Contrôle qualité des ouvrages (photos guidées, mesures, IA)
- 14 ouvrages : fondations, ferraillage avant coulage, béton décoffré, maçonnerie, enduits, escalier, carrelage, faïence, douche et salle d'eau, électricité, plomberie, charpente et toiture, menuiseries, peinture (`services/quality.py`, en français et en anglais).
- Pour chacun : **prises de vue guidées** (quoi, d'où, à quel moment, avec quel instrument dans le cadre), **points à contrôler** classés par gravité (sécurité ou solidité, important, finition) et **mesures** à saisir.
- Les photos passent par les mêmes contrôles que toute preuve (GPS, date, galerie, doublons) ; une photo floue, sombre ou trop petite est signalée tout de suite au chef.
- **Mesures contrôlées par des règles fixes, sans IA** : régularité des marches (écart > 5 mm à vérifier, > 10 mm problème), règle de Blondel, garde-corps, hauteur libre, pente de douche, planéité et désaffleure du carrelage, enrobage, espacement des cadres, aplomb, profondeur des fouilles comparée au plan… Valeurs indicatives, affichées comme telles.
- **Avec `ANTHROPIC_API_KEY`** : l'IA analyse toutes les photos de l'ouvrage ensemble (`QUALITY_MODEL`, sinon `AI_MODEL`), dit pour chaque point ce qu'elle voit, entoure l'endroit sur la photo, lit les instruments (mètre, niveau, manomètre) et compare avec la mesure saisie, signale les photos inutilisables, celles qui manquent et si les photos montrent bien le même ouvrage. La mesure l'emporte quand l'IA est moins sévère ; une IA peu sûre d'elle donne « à vérifier », jamais « problème ». Si l'IA est en panne, le contrôle aboutit sur les mesures.
- Sans IA (ou quota atteint), les points non mesurés sont marqués « à contrôler vous-même », avec un guide pour chacun.
- Le propriétaire peut demander une photo ou une réponse au chef, donner son propre avis ou accepter un point ; un ingénieur, un contrôleur, un architecte, un conducteur de travaux ou l'inspecteur donne un **avis de professionnel**, qui prime. **Contre-visite** après correction : les points signalés sont recontrôlés et marqués corrigés ou non. Fiche imprimable, photos annotées.
- Un problème probable non résolu apparaît sur la carte de l'étape et dans la vérification avant paiement ; un problème de sécurité ou une mesure contredite par la photo conseille une inspection.
- Analyses par l'IA comprises par mois : Essai et Essentiel 3, Pro 30, Entreprise illimité (`QUALITY_AI_MONTH` dans `services/billing.py`). Le super-admin peut couper l'IA dans l'administration.

### Guide d'utilisation (menu « Aide »)
- Page **Aide** (`/aide`), dans le menu de tous les utilisateurs et des visiteurs : chacun voit d'abord le guide de son profil (propriétaire, chef de chantier, professionnel du BTP, fournisseur, inspecteur), avec un sommaire, les étapes à suivre, des conseils, des captures d'écran et des questions fréquentes, en français et en anglais. Le guide de l'**équipe ChantierVrai** n'est visible que par les membres de l'équipe.
- Le contenu est dans `services/guide_content.py` (libellés des boutons entre guillemets : à mettre à jour si un bouton change de nom). Les captures sont dans `static/aide/`.

### Bien démarrer et fonctions avancées
- Le propriétaire et le chef de chantier voient une liste **Bien démarrer** qui se coche toute seule : créer le chantier, inviter le chef (message WhatsApp prêt à envoyer avec le code), téléphone pour les alertes, première photo vérifiée, première étape validée et payée, choix de l'offre. Elle disparaît quand tout est fait, ou sur demande.
- Création de chantier simplifiée : le **budget total** se répartit sur les étapes types en un clic ; le rayon, la caméra obligatoire et la description sont dans « Options avancées ».
- **Fonctions avancées** (maquette numérique, capteurs, visites 360°, zones, quantités) masquées par défaut pour les propriétaires et les chefs : elles s'affichent sur demande (Mon compte), pour les professionnels et les inspecteurs, ou dès que le chantier s'en sert.

### Application mobile : paiements
Écran **Paiements** : le chef, le fournisseur ou l'inspecteur confirme ou conteste un paiement reçu ; le propriétaire voit ses bons à payer et déclare un paiement (référence de la transaction ; la photo du reçu se joint sur le site). Les notifications de paiement ouvrent directement cet écran. API : `GET /api/v1/paiements`, `GET|POST /api/v1/paiements/<objet>/<id>`, `POST /api/v1/paiements/recus/<id>`.

### Paiements : ChantierVrai ne touche pas l'argent (paiement suivi)
Par défaut, **le séquestre est désactivé** : la plateforme ne détient aucun fonds, donc aucun agrément de paiement n'est nécessaire. Les chantiers utilisent le **paiement suivi** :

1. Une étape validée (ou une commande reçue, ou une inspection réalisée) émet un **bon à payer** imprimable : référence `BAP-…`, montant, bénéficiaire, numéro Mobile Money, approbations, preuves, code de contrôle.
2. Le payeur (le propriétaire, ou le responsable financier si le circuit à deux niveaux est actif) paie **hors de ChantierVrai**, puis **déclare le paiement** : montant, moyen, date, référence de la transaction ou reçu (PDF ou photo, empreinte SHA-256 conservée). Le paiement peut se faire en plusieurs fois.
3. Le bénéficiaire (chef de chantier, fournisseur, inspecteur) reçoit une alerte et **confirme la réception** ou **la conteste** avec un motif. Sans réponse, il est relancé après 3 jours par la tâche `quotidien`.
4. Quand tout le montant est confirmé, l'étape passe à « payée » (ou la commande à « reçue et payée », l'inspection à « payée »).

Chaque chantier a un **registre des paiements** (`/chantiers/<id>/paiements`) avec un export CSV ; l'export comptable reprend les paiements déclarés et confirmés. Les webhooks reçoivent `etape.validee`, `paiement.declare`, `paiement.confirme` et `paiement.conteste`. Le mode « simple » (je valide et je note la référence) reste disponible.

Pour les achats de matériaux sans séquestre, le fournisseur est payé directement ; la commission lui est facturée chaque mois. Le rôle Finance la voit dans **Admin → Commissions à facturer aux fournisseurs**, avec un export CSV par mois.

**Réactiver le séquestre** : le code est intact. Le super-admin l'active dans **Admin → Paiements de la plateforme**, en indiquant le partenaire agréé qui garde les fonds et en confirmant que le contrat est validé. Quand il est désactivé, les chantiers déjà en séquestre ne reçoivent plus de dépôts mais utilisent leurs fonds restants, et ne peuvent pas quitter le séquestre tant qu'il reste de l'argent.

### Équipe ChantierVrai (administration)
Les accès équipe sont pour vos salariés. Ils n'ont rien à voir avec le compte « Professionnel du BTP », qui sert aux architectes, ingénieurs ou comptables qu'un client invite sur son chantier.

Chaque membre a un rôle et ne voit, dans `/admin`, que les sections de ce rôle :

| Rôle | Voit et fait | Ne voit pas |
|---|---|---|
| Super-admin (fondateur) | Tout : équipe, récupération des comptes (lien de mot de passe, retrait de 2FA), journal | — |
| Vérification | Valide ou refuse inspecteurs, fournisseurs, entrepreneurs, ingénieurs et bureaux de contrôle | Montants, litiges, comptes |
| Support, litiges et modération | Litiges et commandes en problème, portail citoyen, blocage des comptes ; ouvre les pages d'un chantier pour traiter un dossier | Séquestre, commissions, récupération des comptes |
| Commercial | Activité des achats de matériaux, devis et livraison des images satellite | Commissions, séquestre, chantiers clients |
| Finance | Séquestre, commissions, volumes d'achats, images satellite | Vérifications, chantiers clients |

Les clients ne voient jamais les commissions de ChantierVrai. Un fournisseur ne voit que la commission prélevée sur ses propres ventes.

Règles :
- **double authentification obligatoire** : sans 2FA, un membre est renvoyé vers « Sécurité » et n'ouvre pas l'administration ;
- chaque action est inscrite au journal avec le rôle de son auteur ;
- les alertes (vérification à faire, litige, image à commander) ne vont qu'aux rôles concernés ;
- personne ne modifie son propre accès, et seul un super-admin bloque un autre super-admin.

Pour créer le premier super-admin, créez votre compte dans l'application, puis :
```bash
flask --app app creer-admin vous@exemple.com
flask --app app creer-admin agent@exemple.com --role verification   # rôle précis (verification, support, commercial, finance)
```
(ou mettez `ADMIN_EMAILS=vous@exemple.com` avant l'inscription). Ensuite, ajoutez l'équipe depuis **Admin → Équipe** (`/admin/equipe`) : la personne crée son compte, vous saisissez son e-mail et son rôle, vous pouvez changer le rôle ou retirer l'accès (ses sessions sont alors déconnectées). Les comptes admin existants deviennent super-admin à la mise à jour.

### Tâches planifiées (cron)
```cron
*/5 * * * *  cd /srv/chantiervrai && venv/bin/flask --app app relancer
30 2 * * *   cd /srv/chantiervrai && venv/bin/flask --app app quotidien
```
`quotidien` fait les comptes rendus de la semaine, les images satellite du mois, les relances et une sauvegarde (base et fichiers, 14 conservées dans `instance/sauvegardes/` ou `BACKUP_DIR`). **Copiez ces sauvegardes hors du serveur.** `flask --app app sauvegarde` lance une sauvegarde à la demande.

### Base de données : SQLite ou PostgreSQL
SQLite par défaut, sans rien installer : idéal pour démarrer. Pour beaucoup de chantiers et plusieurs serveurs, passez à **PostgreSQL** :

```bash
pip install "psycopg[binary]"
export DATABASE_URL=postgresql://chantiervrai:motdepasse@localhost:5432/chantiervrai
flask --app app migrer-vers-postgres instance/chantiervrai.db   # une seule fois : copie la base SQLite existante
```

Le schéma est créé automatiquement. Les sauvegardes utilisent alors `pg_dump` (fichiers `.sql.gz`). Photos et documents restent dans `instance/uploads/` : sur plusieurs serveurs, placez ce dossier sur un disque partagé.

## Configuration des services (variables d'environnement)

| Service | Variables | Sans configuration |
|---|---|---|
| Adresse publique (liens dans les messages, retours de paiement) | `PUBLIC_URL=https://votre-domaine` | liens absents des messages |
| Paiement séquestre CinetPay | `CINETPAY_APIKEY`, `CINETPAY_SITE_ID`, `CINETPAY_TRANSFER_PASSWORD` | simulation, aucun argent réel |
| WhatsApp et SMS (Twilio) | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `TWILIO_SMS_FROM` | messages enregistrés « simulé » |
| E-mail | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | idem |
| Indicatif des numéros locaux | `DEFAULT_COUNTRY_CODE` (225) | |
| IA de vision | `ANTHROPIC_API_KEY`, `AI_MODEL` (facultatif) | contrôles locaux seulement, factures à saisir |
| Satellite (Copernicus Data Space, gratuit) | `SH_CLIENT_ID`, `SH_CLIENT_SECRET` (+ `SH_BASE`, `SH_TOKEN_URL` pour Sentinel Hub commercial) | images ajoutées à la main |
| Lien vers le portail SIGOMAP | `SIGOMAP_URL` | |
| Nom de la société et contact (CGU, confidentialité) | `COMPANY_NAME`, `CONTACT_EMAIL` | texte entre crochets |
| Administrateurs créés à l'inscription | `ADMIN_EMAILS` | commande `creer-admin` |
| Dossier des sauvegardes | `BACKUP_DIR` | `instance/sauvegardes` |
| Base PostgreSQL | `DATABASE_URL` | SQLite |
| Notifications sur le téléphone (Expo) | actives par défaut ; `EXPO_PUSH=0` pour couper, `EXPO_ACCESS_TOKEN` si besoin | |
| Attestation Android (Play Integrity) | `PLAY_INTEGRITY_PACKAGE`, `PLAY_INTEGRITY_SERVICE_ACCOUNT` | preuves marquées « non vérifiée » |
| Version minimale de l'application mobile | `MIN_APP_VERSION` | 1.0.0 |
| Commission sur l'achat direct des matériaux (en %) | `COMMISSION_MATERIAUX` | 3 |
| Météo automatique quotidienne (Open-Meteo) | `METEO_AUTO` | désactivée (mettre 1) |
| Liens des applications sur les stores (page produit) | `ANDROID_STORE_URL`, `IOS_STORE_URL` | « bientôt sur les stores » |

## Avant la mise en production

Prêt côté application. Reste à faire côté entreprise :

1. **Juridique** : faire relire les CGU et la politique de confidentialité (`/cgu`, `/confidentialite`) ; déclaration auprès de l'ARTCI (loi n° 2013-450) ; contrat avec un **partenaire agréé pour le séquestre** : garder l'argent du propriétaire avant de le verser est une activité réglementée.
2. **Services externes** : clés CinetPay, Twilio, SMTP, Copernicus, IA (voir le tableau). Valider l'API de transfert CinetPay dans leur environnement de test avant de verser de l'argent réel. Twilio WhatsApp exige un numéro WhatsApp Business et des modèles de messages approuvés.
3. **Hébergement** : sur Render, suivre « Mise en ligne sur Render » ci-dessous. Sur un serveur à soi : `gunicorn -w 2 -b 127.0.0.1:8000 app:app` derrière Nginx en **HTTPS** (obligatoire pour le GPS et la caméra), avec `SESSION_COOKIE_SECURE=1`, une `SECRET_KEY` fixe et longue, `PROXY_HOPS` = nombre de relais devant l'application (1 derrière Nginx ou Render, 0 sans relais : sert à reconnaître la vraie adresse IP pour le blocage des essais de connexion), `PUBLIC_URL`, les deux tâches cron (`flask relancer`, `flask quotidien`) et la copie distante des sauvegardes (`OFFSITE_*`). Installer ffmpeg et opencv-python-headless.
4. **Support** : créer le compte administrateur, vérifier les premiers inspecteurs et fournisseurs, décider qui traite les litiges.
5. **Fournisseurs** : signer un contrat simple avec chaque quincaillerie (commission, délais, qualité, reprise des produits non conformes) et lui faire tester une livraison avec l'application.

## Mise en ligne sur Render

Le fichier `render.yaml` décrit tout : sur Render, « New + » → « Blueprint » → choisir le dépôt. Render crée :

| Élément | Rôle |
|---|---|
| Service web `chantiervrai` (offre Starter) | l'application, avec contrôle de santé sur `/sante` |
| Disque permanent de 10 Go monté sur `/var/data` | photos, documents, sauvegardes locales : **gardés d'un déploiement à l'autre** (`CV_INSTANCE=/var/data`) |
| Base PostgreSQL `chantiervrai-db` | les données ; Render en fait aussi une sauvegarde quotidienne |
| Tâche `chantiervrai-relances` (toutes les 5 min) | relances, et alerte si la sauvegarde de la nuit manque |
| Tâche `chantiervrai-quotidien` (2 h 30) | comptes rendus, échéances, sauvegarde, copie distante |

Les tâches planifiées n'ont pas accès au disque : elles appellent le service web (`POST /taches/<nom>`, protégé par `CRON_TOKEN`, généré par Render), qui exécute la tâche une seule fois à la fois.

**À faire après la création** (tableau de bord Render → service web → Environment) :

1. `PUBLIC_URL` : l'adresse du site (`https://…onrender.com`, puis le nom de domaine).
2. **Copie des sauvegardes hors de Render** (indispensable : un disque peut tomber en panne). Créer un bucket **privé** chez un fournisseur compatible S3 et une clé limitée à ce bucket :
   - Cloudflare R2 (sans frais de sortie) : `OFFSITE_ENDPOINT=https://<id-du-compte>.r2.cloudflarestorage.com`, `OFFSITE_REGION=auto` ;
   - Backblaze B2 : `OFFSITE_ENDPOINT=https://s3.<région>.backblazeb2.com`, `OFFSITE_REGION=<région>` ;
   - AWS S3 : `OFFSITE_ENDPOINT=https://s3.<région>.amazonaws.com`, `OFFSITE_REGION=<région>`.

   Puis `OFFSITE_BUCKET`, `OFFSITE_KEY_ID`, `OFFSITE_SECRET`. Chaque nuit, la base est sauvegardée, **relue pour vérification**, puis copiée (30 dernières gardées) ; les photos et documents partent au fil de l'eau, seuls les nouveaux.
3. `SMTP_*` et `ALERT_EMAILS` : qui reçoit les alertes (erreur serveur, sauvegarde en échec ou de plus de 36 h, copie distante en échec). Une même alerte part au plus une fois par heure.
4. Créer le compte administrateur : Shell du service web → `flask creer-admin vous@exemple.ci`.
5. Brancher un service de surveillance externe gratuit (UptimeRobot, Better Stack) sur `https://…/sante` : il prévient si le site ne répond plus du tout.

**Surveiller** : la page `/sante` (JSON : base, disque, âge de la sauvegarde, état de la copie distante) et la carte « Sauvegardes et surveillance » de l'administration.

**Restaurer** (Shell du service web) :

```bash
flask restaurer --distant --avec-fichiers --oui   # dernière sauvegarde distante + photos manquantes
flask restaurer --fichier /var/data/sauvegardes/chantiervrai-AAAAMMJJ-HHMMSS.sql.gz --oui
flask restaurer --avec-fichiers --oui             # seulement redescendre les photos (nouveau disque)
```

À faire une fois avant l'ouverture, puis chaque trimestre : restaurer sur un service de test et vérifier qu'on se connecte et qu'on voit les photos.

**Limites** : avec un disque, Render n'autorise qu'une seule instance et le redéploiement coupe le service quelques secondes. Pour grandir au-delà, déplacer les photos vers le stockage objet (même bucket) : c'est la prochaine étape technique, pas un besoin du pilote.

## Limites connues

- **Applications mobiles** : écrites et testées sur ordinateur (logique, API, parcours complet contre le serveur, rendu de tous les écrans), mais pas encore compilées ni essayées sur un vrai téléphone. L'attestation de l'appareil reste à brancher côté téléphone (voir `mobile/README.md`) ; sa vérification iPhone reste à ajouter côté serveur.
- **Calcul 3D** : l'application affiche les modèles 3D, elle ne les calcule pas (WebODM, Pix4D).
- **Satellite** : 10 m par pixel. On voit le terrain se transformer, pas le détail des murs.
- **Floutage des visages** : détection automatique des visages de face et de profil ; un visage très petit ou caché peut échapper. Le maître d'ouvrage choisit chaque photo publiée.
- **Traduction** : l'analyse IA des photos rédige sa description en français.

## Tests

```bash
CV_SYNC=1 python3 test_parcours.py     # parcours d'origine
python3 test_complet.py                # suivi diaspora et grands chantiers, en simulation
python3 test_vente.py                  # sécurité, administration, litiges, caméra, hors ligne, sauvegardes
python3 test_anglais.py                # version anglaise, chacun dans sa langue
python3 test_api.py                    # API des applications mobiles
python3 test_achats.py                 # achat direct des matériaux : commande, livraison prouvée, paiement
python3 test_controle.py               # calculateur, stock, contrôles obligatoires, circuit de paiement, indice de confiance
python3 test_avance.py                 # fiche et parcelle, profils, maquette IFC, capteurs, images THR, export comptable, Académie
python3 test_ia.py                     # entrepreneurs vérifiés et avis, assistant IA, lecture des plans
python3 test_terrain.py                # zones, visites 360°, quantités installées, rapport, clés d'API, webhooks
python3 test_equipe.py                 # accès équipe : rôles, sections visibles, 2FA obligatoire, journal
python3 test_paiements.py              # paiement suivi sans toucher l'argent, interrupteur du séquestre
python3 test_abonnements.py            # essai, offres, factures, renouvellement, relances, suspension
python3 test_demarrage.py              # liste « Bien démarrer », invitation WhatsApp, fonctions avancées
python3 test_recours.py                # validation automatique, litiges et recours, portail citoyen, inspections, conditions fournisseur
python3 test_aide.py                   # guide d'utilisation : profils, anglais, guide de l'équipe réservé
python3 test_qualite.py                # contrôle qualité : photos guidées, règles, IA simulée, avis, contre-visite, quota
python3 test_whatsapp.py               # WhatsApp du chef : position partagée, photos, commandes, notes vocales, webhook signé
python3 test_financement.py            # plan de financement, trésorerie, endettement, dossier de crédit, alertes
python3 test_terrain_comptage.py       # foncier, comptage des livraisons, plan et réalité
python3 test_utilite.py                # test d'utilité : ce que voit chaque acteur (menus, alertes, vignettes, indice)
python3 recette/navigateur.py          # dans un vrai navigateur (Playwright) : mots expliqués, hors ligne, autorisations, photo par réseau faible
python3 test_production.py             # mise en production : signature S3, copie distante, restauration, santé, tâches, alertes
python3 test_pilotage.py               # tableau de pilotage : accès, calculs, rendu
python3 test_securite.py               # attaques jouées : fichier piégé, image « bombe », CSRF, redirection, force brute, IP falsifiée
python3 test_mode_simple.py            # mode simple du particulier : l'essentiel d'abord, « Autres fonctions », bascule
python3 test_double_auth.py            # double authentification : QR code relu, nouvelle clé, session expirée, connexion
DATABASE_URL=postgresql://… python3 test_complet.py   # les mêmes tests sur PostgreSQL (base de test vidée !)
cd mobile && npm test                  # application mobile : logique et parcours contre le serveur
```

## Structure

```
app.py                 serveur Flask : routes, base de données, contrôles
services/payments.py   séquestre : simulation et CinetPay
services/notify.py     WhatsApp, SMS (Twilio), e-mail
services/vision.py     empreinte visuelle, changements satellite, IA de vision, lecture de factures
services/media.py      vidéos : date, position, durée, vignette
services/satellite.py  images Sentinel-2 et Sentinel-1 (Copernicus)
services/predict.py    prédiction des retards
services/materials.py  contrôle des matériaux
services/security.py   double authentification, mots de passe
services/db.py         SQLite ou PostgreSQL
services/i18n.py       traductions (français, anglais)
services/attestation.py attestation de l'appareil (applications natives)
translations/en.json   textes anglais
mobile/                applications Android et iPhone (Expo)
tests_support/         petit pilote PostgreSQL pour les tests (sans psycopg)
templates/             pages HTML (Jinja)
static/                styles, capture photo et vidéo, application installable
static/produit.css     page produit ; static/produit/ ses images ; static/fonts/ police Inter (licence OFL)
services/demo.py       données et photos de démonstration
instance/              base de données et fichiers (créé au démarrage)
```
