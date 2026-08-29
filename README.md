# GestImmo — API de gestion immobilière

API FastAPI couvrant la gestion des biens, des propriétaires et des locataires.

## État d'avancement des 17 modules

Le détail complet, module par module et avec les preuves d'exécution, est dans
[`AUDIT-MODULES.md`](AUDIT-MODULES.md). En synthèse :

- **complets et couverts par des tests d'intégration** : modules 1 (biens), 2
  (propriétaires), 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16 et 17 ;
- **socle API uniquement** : module 14 (mobile). Le dépôt ne contient
  **aucun frontend ni code mobile** : les portails, la carte, les widgets et
  les quatre applications du cahier des charges existent côté endpoints, pas
  côté écrans.

Le module 1 couvre désormais aussi les vidéos de galerie, la visite 360°,
les filtres propriétaire/gestionnaire/disponibilité/tags, les recherches
favorites, l'export CSV, le rapport d'évaluation PDF et l'historique
consolidé. Le module 2 couvre la signature électronique du mandat avec dossier
de preuve et la synthèse financière par bien. Le module 15 couvre le cycle de
vie complet des contrats, sinistres et attestations.

Suite de tests : 89 tests d'intégration, tous verts.

```bash
cd backend
python -m unittest discover -s tests
```

## Module 1 — Biens immobiliers

Le module biens ajoute :

- CRUD complet, 12 types de biens, 6 statuts, référence auto-générée,
  géolocalisation, surfaces, pièces, étages, année, chauffage, DPE/GES,
  équipements, description, tags et catégories ;
- galerie photos/vidéos avec upload multiple, compression des images,
  photo principale, gestion des métadonnées média et visite virtuelle 360° ;
- recherche multicritère avec filtres type, statut, localisation, prix,
  surface, pièces, propriétaire, gestionnaire, date de disponibilité et tags ;
- recherches favorites (`/api/properties/saved-searches`) et exports
  PDF / Excel / CSV ;
- évaluation, rapport d'évaluation PDF et historique consolidé (baux,
  loyers, tickets de maintenance).

## Module 2 — Propriétaires

Le module propriétaires ajoute :

- fiche personne physique / morale, coordonnées, IBAN, fiscalité, SIRET,
  documents numérisés ;
- portefeuille de biens, mandats (gestion / vente / recherche) avec
  renouvellement, préavis et alertes d'expiration ;
- **signature électronique réelle** du mandat avec consentement, empreinte
  SHA-256, horodatage, IP, user-agent et dossier de preuve PDF téléchargeable ;
- comptabilité propriétaire (solde, relevé mensuel/trimestriel/annuel PDF) et
  **synthèse financière par bien** ;
- portail propriétaire JWT (dashboard, revenus/charges, documents, messagerie,
  déclaration fiscale).

## Module 3 — Gestion des locataires

Le module locataire comprend :

- **fiche locataire complète** : état civil, coordonnées, situation professionnelle, revenus, contacts d'urgence, anciens logements, garants, scores de solvabilité et de fiabilité ;
- **candidature en ligne** : formulaire public, jeton de suivi privé, justificatifs, OCR PDF/image, contrôles automatiques, score explicable et workflow `pending → accepted/refused` ;
- **gestion des garanties** : personne physique ou morale, caution simple/solidaire, Visale/GLI, acte de cautionnement et vérification des pièces ;
- **portail locataire JWT** : tableau de bord, bail, échéances et paiements, quittances PDF, demandes d'intervention, messagerie et notifications ;
- **suivi** : détection des retards, score de fiabilité dynamique, historique des interactions, alertes et dossiers contentieux ;
- **paiement en ligne** : création de sessions Stripe et webhook signé/idempotent lorsque Stripe est configuré.

Les justificatifs locataires sont enregistrés dans un espace privé distinct des médias publics. Leur téléchargement passe toujours par une route authentifiée ou par le jeton de suivi de la candidature.

## Module 4 — Baux et contrats

Le module contractuel ajoute :

- huit types de bail : habitation vide/meublée, commercial 3/6/9, professionnel, dérogatoire, saisonnier, occupation précaire et mixte ;
- modèles versionnés, bibliothèque de clauses et clauses propres à chaque contrat ;
- paramètres complets : durée, reconduction, loyer HC, charges, dépôt, indice IRL/ICC/ILAT/ILC, périodicité, paiement, échéance et clause résolutoire ;
- génération PDF et signature électronique simple intégrée avec consentement, empreinte SHA-256, horodatage, adresse IP et dossier de preuve ;
- révisions de loyer calculées selon l'indice, plafonds réglementaires configurables, notification et historique ;
- alertes d'échéance, renouvellement automatique, avenant ou création d'un nouveau bail ;
- congés locataire/propriétaire, motifs vente/reprise/légitime, préavis calculé, lettre PDF et suivi ;
- états des lieux d'entrée/sortie, saisie pièce par pièce, compteurs, clés, photos horodatées, synchronisation mobile hors ligne, signatures sur tablette, comparaison et retenues proposées ;
- annexes obligatoires, contrôle de complétude, avenants et archivage avec durée de conservation et gel juridique.

Les règles de plafonnement sont datées, sourcées et administrables. Aucune valeur réglementaire susceptible d'évoluer n'est simulée : sans règle applicable, le calcul restitue la hausse indiciaire non plafonnée et l'indique dans son détail.

## Module 5 — Gestion financière et comptabilité

Le module financier et comptable ajoute :

- **appels de loyer automatiques** : génération mensuelle idempotente, échéance selon la journée de paiement du bail, complément des méthodes déjà gérées par le module locataire ;
- **encaissement multi-canal** : CB, prélèvement, virement, chèque, espèces (avec reçu), quittance générée automatiquement et écriture comptable automatique ;
- **impayés** : détection automatique des retards, calcul des pénalités d'intérêt légal, workflow de relance J+5 (amiable/email), J+15 (ferme/email+SMS), J+30 (mise en demeure/AR), J+60 (commandement), J+90 (contentieux), plans d'apurement avec échéancier et dossiers contentieux (huissier, tribunal, historique d'actions) ;
- **charges** : charges récupérables / non récupérables, répartition par tantièmes, surface, occupants ou clé personnalisée, budget prévisionnel et régularisation annuelle (provision vs réel) ;
- **comptabilité générale** : plan comptable immobilier, écritures automatiques équilibrées, journal, grand livre, balance générale, rapprochement bancaire (import OFX/CSV/MT940, matching automatique et manuel), gestion multi-comptes bancaires, TVA et clôture ;
- **compte de gérance** : relevé de gestion, honoraires, versements (déjà couvert par le module de transactions propriétaire) ;
- **facturation** : factures d'honoraires et de prestations, devis, avoirs, numérotation automatique, TVA / exonération ;
- **dépôt de garantie** : encaissement, suivi, retenues justifiées, délai légal de restitution (1 ou 2 mois) et lettre de restitution ;
- **exports comptables** : FEC (`JournalCode|Date|Compte|Débit|Crédit|Libellé`), CSV, Sage, QuickBooks, Ciel et format personnalisable.

## Module 6 — Maintenance et travaux

Le module maintenance ajoute :

- **ticketing / demandes d'intervention** : création par le locataire (portail), le gestionnaire, le propriétaire ou automatique (préventif), catégorisation (plomberie, électricité, chauffage, serrurerie, peinture, toiture, parties communes, autre), niveau d'urgence (faible, moyen, élevé, critique), pièces jointes photo/vidéo et localisation ;
- **workflow d'intervention** : statuts `nouveau → validation propriétaire → validé → prestataire assigné → devis → planifié → en cours → terminé → contrôle qualité → clôturé`, notifications à chaque étape, SLA par niveau d'urgence et escalade automatique ;
- **prestataires** : annuaire (coordonnées, spécialités, zones, tarifs, assurances, certifications, note), comparaison de devis, bon de commande et évaluation post-intervention ;
- **maintenance préventive** : planification récurrente (ramonage, chaudière, détecteurs de fumée, espaces verts, nettoyage, personnalisable), calendrier, alertes automatiques et matérialisation des tâches ;
- **travaux lourds** : projet, budget prévisionnel, suivi d'avancement, planning de phases (Gantt), documents (permis, devis, factures), réception des travaux ;
- **suivi financier** : budget maintenance par bien, coûts réels vs prévisionnel, imputation propriétaire / locataire / copropriété et reporting ;
- **inventaire des équipements** : liste par bien, date d'installation, garantie, contrat d'entretien, historique des pannes et date de remplacement prévisionnelle ;
- **bon de commande** : émission auprès du prestataire à partir d'un devis, suivi de statut (brouillon, envoyé, confirmé, annulé) et rattachement automatique au ticket ;
- **contrôle qualité** : validation ou refus post-intervention avant clôture, avec retour en cours si non conforme ;
- **planning de phases (Gantt)** : vue consolidée des dates et de l'avancement de chaque phase d'un projet de travaux.

## Module 7 — Gestion de copropriété

Le module copropriété ajoute :

- **fiche copropriété / immeuble** : informations générales, règlement de copropriété, liste des lots (numéro, type, tantièmes, propriétaire, occupant), parties communes et coordonnées du syndic ;
- **contrôle des tantièmes** : vérification de la répartition totale des lots par rapport au total déclaré de la copropriété ;
- **charges de copropriété** : budget prévisionnel par poste (courant / exceptionnel / travaux), vote en assemblée, appels de fonds répartis automatiquement par tantièmes (avec ajustement d'arrondi), suivi des paiements par lot, fonds de travaux (loi ALUR) avec cotisations/prélèvements, et répartition annuelle des charges par lot ;
- **assemblée générale** : convocation (verrouille l'ordre du jour et prépare la feuille de présence), feuille de présence avec calcul du quorum, résolutions avec majorités légales (article 24/25/26, unanimité), vote par lot au tantième, procès-verbal structuré et clôture ;
- **conseil syndical** : membres (président, membres, suppléants), réunions et comptes-rendus ;
- **carnet d'entretien** : historique des travaux, contrats en cours, diagnostics et sinistres ;
- **comptabilité copropriété** : plan comptable dédié (créable en un clic avec la nomenclature standard), écritures équilibrées, grand livre par compte et bilan simplifié (actif / passif / résultat / solde du fonds travaux).

## Module 8 — CRM et gestion commerciale

Le module CRM et gestion commerciale ajoute :

- **gestion des prospects** : fiche acheteur / locataire complète (coordonnées, source d'acquisition : site web, portail, agence, parrainage…, critères de recherche structurés en JSON, budget min/max) avec un score de qualité 0-100 explicable (complétude de la fiche, qualité de la source, engagement, actualité du contact) recalculé à chaque évolution ;
- **pipeline commercial** : huit étapes par défaut (premier contact → qualification → visite programmée → visite effectuée → dossier déposé → dossier validé → bail signé / vente conclue → perdu), configurables (nom, ordre, probabilité, couleur), vue Kanban avec valeurs totales et pondérées par probabilité de conversion, historique des changements d'étape et conversion automatique du prospect en cas de signature ;
- **gestion des visites** : créneaux de disponibilité par bien, planification avec réservation de créneau, détection des conflits, confirmation automatique, rappels email + SMS journalisés, compte-rendu structuré (note, niveau d'intérêt, forces/faiblesses, prochaine étape), retour du visiteur et vues agenda jour / semaine / mois ;
- **matching automatique** : scoring explicable prospect ↔ bien (type, localisation, budget avec tolérance 10 %, surface, pièces), alertes à seuil configurable, suggestions de biens classées, notification automatique à l'agent référent et envoi de la suggestion au prospect ;
- **diffusion multi-portails** : annonces générées à partir de modèles (variables `{titre}`, `{ville}`, `{surface}`…) et publiées sur SeLoger, LeBonCoin, Logic-Immo, Bien'ici, PAP et le site de l'agence, gestion centralisée avec statut de synchronisation par portail, statistiques par annonce et par portail (vues, contacts, favoris, taux de conversion) et retrait total ou partiel ;
- **transactions de vente** : offre d'achat (acceptation avec création automatique du dossier), compromis de vente, conditions suspensives typées (financement, diagnostic, préemption…) avec deadline et décision (satisfaite / levée / échouée — l'échec annule le dossier), suivi notaire via journal d'événements, acte authentique verrouillé tant qu'une condition est en attente et commission agence calculée HT/TTC (taux + fixe + TVA) ;
- **suivi de la performance** : KPIs par agent (dossiers créés/gagnés/perdus, taux de conversion, valeur et commissions, visites effectuées, ratio visites par signature, délai moyen de conclusion) et indicateurs globaux (délai moyen de location, taux d'occupation, commissions encaissées).

Aucun envoi réel vers les portails ni les canaux email/SMS n'est simulé : chaque publication et chaque rappel sont journalisés avec leur destinataire, prêts à être branchés sur un prestataire.

## Module 9 — Tableau de bord et reporting

Le module tableau de bord et reporting ajoute :

- **dashboard principal** : KPIs temps réel (biens gérés, taux d'occupation global, revenus mensuels/annuels, impayés en cours, tickets maintenance ouverts, baux et mandats arrivant à échéance à 30/60/90 jours, prospects actifs) et graphiques dynamiques (évolution des revenus sur 12 mois, répartition par type de bien, taux d'occupation mensuel, répartition des charges, performance commerciale) ;
- **widgets personnalisables** : catalogue de widgets (cartes KPI, graphiques, listes), positionnement persistant en colonnes/ordre pour supporter le drag & drop, réorganisation en masse et données temps réel par type de widget ;
- **rapports prédéfinis** : rapport de gestion locative, état des loyers, synthèse des impayés, état des travaux, rapport de vacance locative (avec perte de loyer estimée), bilan financier par propriétaire, bilan financier par bien, rapport d'activité de l'agence et rapport fiscal annuel ;
- **rapports personnalisés** : générateur sur dix datasets (biens, baux, loyers, impayés, tickets, charges, prospects, dossiers, visites, annonces) avec sélection de champs, filtres avancés (eq, ne, gt, gte, lt, lte, like, in, between — valeurs coercées vers les enums et dates), groupements avec agrégats (count/sum/avg/min/max), tri et limite ; planification d'envoi (quotidien, hebdomadaire, mensuel, trimestriel) avec exécution des échéances, partage par jeton sans authentification et historique des exécutions ;
- **exports** : PDF, Excel, CSV, Word pour tous les rapports prédéfinis et personnalisés, et export API JSON par dataset pour un BI externe ;
- **alertes dashboard** : règles paramétrables (11 métriques surveillées, comparateur, seuil, sévérité, canaux dashboard/email/SMS, délai de repos anti-spam), évaluation à la demande, journal des déclenchements et prise de connaissance.

## Module 10 — Communication et notifications

Le module communication ajoute :

- **messagerie interne** : conversations par bien, par dossier commercial, par locataire / propriétaire / bail, fil de discussion, pièces jointes privées, recherche plein texte et archivage (une conversation archivée n'accepte plus de messages) ;
- **notifications multicanal** : email (modèles personnalisables, variables dynamiques `{{prenom}}`, `{{bien}}`…, pixel de suivi d'ouverture), SMS (alertes urgentes, rappels de visite et de paiement), push, in-app et courrier postal. Aucun envoi réel n'est simulé : chaque émission est journalisée avec destinataire, prestataire prévu et statut, prête à être branchée ;
- **automatisation** : huit scénarios système (bienvenue locataire, rappel loyer J-3, relance impayé, anniversaire de bail, rappel renouvellement, confirmation de paiement, confirmation de visite, bilan mensuel propriétaire), règles et canaux personnalisables, exécution idempotente (un même événement n'est pas renvoyé) ;
- **centre de préférences** : choix des canaux par type de notification, fréquence (`immediate`, `daily_digest`, `weekly`, `never`) et désabonnement par jeton public ;
- **historique complet** : recherche avancée par canal, type, contact, bien, dossier, locataire, propriétaire et texte.

## Module 11 — Gestion documentaire (GED)

Le module documentaire ajoute :

- **arborescence** : dossiers et sous-dossiers organisés par bien, propriétaire, locataire, contrat ou type de document ;
- **upload et stockage** : fichier unique ou lot, formats PDF / images / Word / Excel, taille max configurable, compression automatique des images, versioning ;
- **génération automatique** : onze modèles (bail, quittance, appel de loyer, état des lieux, lettre de relance, attestation de loyer, lettre de congé, mise en demeure, mandat de gestion, avis d'échéance, régularisation de charges), fusion de variables et prévisualisation avant génération PDF ;
- **signature électronique** : enveloppes DocuSign / Yousign / HelloSign journalisées (sans appel prestataire), niveaux simple / avancé / qualifié, circuit multi-signataires ordonné, suivi de statut et dossier de preuve SHA-256 à valeur d'archivage ;
- **OCR et classification** : lecture automatique (pypdf / Tesseract), extraction de montants, dates, emails et références, classification par mots-clés — une extraction insuffisante ne classe jamais un document avec certitude ;
- **recherche** : plein texte sur titre, nom de fichier, OCR et tags, filtres type / date / bien / contact ;
- **sécurité et conformité** : droits par rôle (lecture / écriture / suppression / administration), journal d'audit (consultation, téléchargement, modification), gel juridique, durée de rétention paramétrable et effacement RGPD refusé tant que la rétention ou le gel s'applique.

## Module 12 — Administration et sécurité

Le module d'administration ajoute :

- **utilisateurs persistants** : création, modification, activation/désactivation, historique de connexion, révocation des sessions et changement de mot de passe ;
- **RBAC granulaire** : profils prédéfinis, rôles personnalisables, droits par module et action (`create`, `read`, `update`, `delete`, `export`, `admin`) et périmètres société, agence ou portefeuille ; les dépendances historiques `require_*` appliquent désormais ces droits au module déduit de la route ;
- **authentification renforcée** : politique de mot de passe, historique anti-réutilisation, expiration, blocage après échecs, session inactive, rotation du refresh token, 2FA TOTP/email/SMS et connexion mobile par challenge signé RSA/ECDSA (la validation biométrique reste effectuée dans l'enclave sécurisée du téléphone) ;
- **SSO** : OAuth2 Authorization Code avec état signé, échange serveur et profil distant ; SAML 2.0 avec synchronisation des métadonnées, vérification XMLDSig/X.509, émetteur, audience, dates et anti-rejeu ;
- **multi-sociétés / multi-agences** : identité visuelle, coordonnées, fiscalité, modèles, périmètres utilisateurs, rattachement société/agence/portefeuille des biens et reporting consolidé ou par agence ;
- **paramétrage** : devise, langue, date, fuseau IANA, séquences transactionnelles de numérotation, indices IRL/ICC/ILAT/ILC et SMTP (secrets chiffrés au repos) ;
- **audit** : journal transversal de toutes les mutations, détails avant/après pour l'administration, acteur, date, IP, historique par ressource et export CSV ;
- **sauvegarde** : backup SQLite cohérent ou `pg_dump`, vérification SHA-256, déclencheur horaire du backup quotidien, backup manuel, rétention et restauration SQLite avec point de retour obligatoire ; PostgreSQL expose volontairement une procédure de restauration hors ligne `pg_restore` ;
- **RGPD** : consentements et retraits, export JSON portable, demandes d'accès/portabilité/oubli, anonymisation, blocage par rétention ou gel juridique GED, registre des traitements et versions publiées de la politique de confidentialité.

Les codes 2FA email/SMS ne sont retournés dans la réponse qu'en environnement non productif. En production, un SMTP actif ou `SMS_WEBHOOK_URL` est obligatoire : l'API échoue explicitement plutôt que de simuler un envoi.

## Module 13 — Géolocalisation et cartographie

Le module cartographique ajoute :

- **carte GeoJSON** de tous les biens géolocalisés, filtres dynamiques (statut, type, ville, prix, société, agence, portefeuille et emprise), clusters selon le zoom et configuration plan OpenStreetMap / satellite Esri ;
- **fiche de localisation** : points d'intérêt locaux (transports, écoles, commerces, hôpitaux, parcs), recherche par rayon, regroupement par catégorie et score pondéré explicable sur 100 ;
- **temps de trajet** : distance Haversine, géométrie de liaison et durée estimée par mode voiture, marche, vélo ou transports ; les résultats internes sont identifiés comme estimations sans trafic et ne sont jamais présentés comme un guidage routier réel ;
- **secteurs GeoJSON** : polygones validés, affectation d'agents, calcul point-dans-polygone, rattachement des biens et statistiques par zone ;
- **tournées** : planification des visites, optimisation par plus proche voisin, ordre des arrêts, heures d'arrivée/départ, attente/retard estimés, distance et temps total, avec conservation du plan calculé.

## Module 14 — Application mobile

L'API expose un socle mobile pour les applications gestionnaire, locataire, propriétaire et prestataire : `GET /api/mobile/dashboard`, synchronisation offline idempotente via `POST/GET /api/mobile/sync`, photos géolocalisées via `/api/mobile/media`. Les écrans métier réutilisent les tickets, baux, états des lieux, messages, notifications et carte existants.

## Module 15 — Assurances et sinistres

Contrats PNO, MRH, GLI, responsabilité civile et copropriété avec CRUD complet
(`/api/insurance/contracts`), cycle de vie des sinistres
(`/api/insurance/claims` — expert, n° dossier, dates clés, indemnisation
proposée/reçue, travaux de remise en état), suivi des attestations
(demande, mise à jour, relance, nombre de relances, validité) et reporting
(mesures, échéances 30 jours, sinistres ouverts, indemnités, attestations
en attente/expirant). Les listes sont paginées et cloisonnées par société /
agence. Les opérations sont protégées par les droits RBAC existants.

## Module 16 — Intelligence artificielle et automatisation

Le module IA (`/api/ai`) fournit des résultats explicables et historisés, toujours présentés comme des aides à la décision :

- **estimations et risques** : estimation du loyer et recommandation du prix de vente par régression ridge/comparables locaux, risque de vacance, scoring dynamique d'impayé sans attribut protégé, et détection d'anomalies financières par écart absolu médian et contrôle des doublons ; chaque résultat conserve entrées, méthode, confiance, facteurs, limites et revue humaine ;
- **assistant 24/7** : FAQ, échéances et suivi de tickets depuis `/tenant-portal/assistant`, création confirmée de ticket et demande de rendez-vous ; l'assistant gestionnaire recherche biens, locataires, baux et tickets, propose des actions rapides avec confirmation et affiche une aide contextuelle ; les conversations locataires sont isolées par leur JWT portail ;
- **RPA** : workflows versionnés avec conditions configurables, opérateurs contrôlés, variables `${event.champ}`, déclencheurs événementiels, clés d'idempotence, dry-run et journal complet. Les actions sont limitées à une liste sûre (notification, ticket, changement de statut, événement webhook et tâche) ; aucun code arbitraire n'est exécuté ;
- **OCR intelligent** : réutilisation du stockage privé et de l'OCR GED, classification, extraction de montants/références de facture et données de bail, contrôles de cohérence et file de revue manuelle quand le texte ou la confiance sont insuffisants ;
- **marché** : observations de veille, concurrents, comparables, séries locales au prix/m² et indices sourcés. Les données externes doivent être importées ou fournies par un connecteur : l'API ne fabrique pas de tendance.

Les profils RBAC possèdent un module granulaire `artificial_intelligence`. Les scores d'impayé ne prennent aucune décision d'acceptation/refus et leur réponse indique explicitement `protected_attributes_used: []`.


### Chat libre sans questions prédéfinies

L'assistant n'utilise plus de catalogue FAQ. Les demandes métier continuent à
interroger les données autorisées de GestImmo ; toute autre question est envoyée
à un fournisseur **compatible OpenAI** configuré par l'administrateur. Chaque
tour est mémorisé automatiquement dans une mémoire privée, limitée au locataire
ou gestionnaire qui l'a posé, puis réutilisé comme contexte pour ses prochaines
questions. C'est un apprentissage par mémoire (RAG léger), **pas** un
entraînement opaque des poids du modèle.

| Variable | Utilité |
|---|---|
| `AI_CHAT_BASE_URL` | URL racine de l'API compatible OpenAI (l'API appelle `/chat/completions`) |
| `AI_CHAT_MODEL` | Nom du modèle conversationnel |
| `AI_CHAT_API_KEY` | Clé API, si le fournisseur l'exige |
| `AI_CHAT_TIMEOUT_SECONDS` | Délai maximal de l'appel, 25 secondes par défaut |

Exemple : `AI_CHAT_BASE_URL=https://api.openai.com/v1`,
`AI_CHAT_MODEL=gpt-4.1-mini`. Si ces variables ne sont pas définies, le système
n'invente pas de réponse libre et indique explicitement que le fournisseur doit
être configuré. Les opérations de gestion restent soumises à confirmation.

## Module 17 — Intégrations et API

Le module d'intégration (`/api/integrations`) ajoute :

- **API REST publique versionnée** sous `/api/v1`, documentée dans Swagger (`/docs`), ReDoc (`/redoc`) et OpenAPI (`/openapi.json`) ; authentification au choix par `X-API-Key` ou OAuth2 `client_credentials`, scopes, expiration/révocation et rate limiting par client avec en-têtes `X-RateLimit-*` ; les secrets et clés brutes ne sont affichés qu'une fois, puis seul leur hash est conservé ;
- **webhooks HMAC-SHA256** : abonnements par événement, secret chiffré au repos, file de livraison, signature horodatée `X-Gestimmo-Signature`, tentatives, backoff, replay et désactivation après échecs répétés. Les destinations privées/réservées sont refusées en production pour prévenir le SSRF ;
- **connecteurs natifs déclarés** pour Sage, QuickBooks, Xero, synchronisation bancaire, Stripe, GoCardless, PayPal, DocuSign, Yousign, SendGrid, Mailgun, SMTP, Twilio, OVH, S3, Google Cloud Storage, Google Maps, Mapbox, SeLoger, LeBonCoin, Google Calendar, Outlook, Salesforce, HubSpot, Power BI et Tableau. Les credentials sont chiffrés ; un test local ne prétend jamais avoir joint un fournisseur et une synchronisation indique clairement lorsqu'un worker/adaptateur distant reste à déployer ;
- **import, migration et export massifs** : analyse CSV/XLSX, suggestion et correction du mapping, aperçu, validation, détection des doublons (`skip`, `update`, `error`), dry-run, rapport ligne par ligne, export CSV/XLSX/JSON et conservation des fichiers en stockage privé ;
- **Zapier et Make** : catalogue préconfiguré de triggers, actions et recherches reposant sur les webhooks et l'API v1.

Les droits du module sont regroupés sous `integrations`. Une clé limitée à `properties:read` ne peut par exemple ni créer un bien ni lire l'annuaire locataire.

## Démarrage avec Docker

```bash
cd backend
docker compose up --build
```

L'API est ensuite disponible sur `http://localhost:8000` et sa documentation OpenAPI sur `http://localhost:8000/docs`.

Les tables absentes sont créées au démarrage (`AUTO_CREATE_TABLES=true`). Pour une base déjà exploitée en production, prévoir une migration SQL/Alembic avant de désactiver cette option.

## Démarrage local

```bash
cd backend
cp .env.example .env   # puis adapter SECRET_KEY et DATABASE_URL
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
# Hors Docker, pointez vers localhost plutôt que l'hôte `postgres` :
export DATABASE_URL='postgresql://immo_user:immo_password_2024@localhost:5432/immo_db'
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Les variables de `backend/.env` sont chargées automatiquement (`python-dotenv`). Docker Compose lit le même fichier via `env_file`.

| Variable | Utilité | Valeur par défaut |
|---|---|---|
| `ENVIRONMENT` | Masque les codes 2FA dès que la valeur est `production` | `development` |
| `DEBUG` | Active l'écho SQLAlchemy | `true` |
| `DATABASE_URL` | URL SQLAlchemy | PostgreSQL local |
| `SECRET_KEY` | Signature JWT et dérivation des secrets | valeur de développement |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Durée par défaut d'un access token | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Durée par défaut d'un refresh token | `7` |
| `RATE_LIMIT_REQUESTS` | Requêtes max par IP sur la fenêtre | `100` |
| `RATE_LIMIT_WINDOW` | Fenêtre de rate limiting, en secondes | `60` |
| `ALLOWED_ORIGINS` | Origines CORS, séparées par des virgules | `*` |
| `UPLOAD_DIR` | Médias publics | `uploads` |
| `MAX_UPLOAD_SIZE` | Taille max d'un fichier uploadé, en octets | `5242880` |
| `LOG_LEVEL` | Niveau de journalisation | `INFO` |
| `LOG_FILE` | Fichier de logs (relatif à `backend/`) | `logs/app.log` |

## Configuration du module locataire

| Variable | Utilité | Valeur par défaut |
|---|---|---|
| `PRIVATE_UPLOAD_DIR` | Répertoire non exposé des dossiers locataires | `private_uploads` |
| `AUTO_CREATE_TABLES` | Crée les tables absentes au démarrage | `true` |
| `STRIPE_SECRET_KEY` | Clé serveur Stripe | vide (checkout désactivé) |
| `STRIPE_WEBHOOK_SECRET` | Secret de signature du webhook Stripe | vide |
| `PAYMENT_CURRENCY` | Devise des loyers | `EUR` |
| `PAYMENT_SUCCESS_URL` | Retour après paiement, accepte `{payment_id}` | URL locale |
| `PAYMENT_CANCEL_URL` | Retour après annulation, accepte `{payment_id}` | URL locale |

Sans `STRIPE_SECRET_KEY`, l'endpoint de paiement répond `503` au lieu de simuler un encaissement.

### Configuration administration et sécurité

| Variable | Utilité | Valeur par défaut |
|---|---|---|
| `SECRET_KEY` | Signature JWT et dérivation de la clé de chiffrement des secrets SMTP/SSO | valeur de développement à remplacer |
| `BACKUP_DIR` | Stockage privé des sauvegardes | `backups` |
| `ENVIRONMENT` | Masque les codes 2FA dès que la valeur est `production` | `development` |
| `SMS_WEBHOOK_URL` | Passerelle HTTP `POST {to, message}` pour le 2FA SMS | vide |
| `SMS_WEBHOOK_TOKEN` | Bearer token de la passerelle SMS | vide |

En production, `SECRET_KEY` doit être une valeur aléatoire stable et sauvegardée : sa rotation invalide les JWT et empêche de relire les secrets SMTP/SSO déjà chiffrés.

## Principaux endpoints

### Candidatures

- `POST /api/applications/` — déposer une candidature publique ;
- `GET /api/applications/public/{reference}` — suivre son dossier avec `X-Application-Token` ;
- `POST /api/applications/public/{reference}/documents` — déposer un justificatif et lancer l'OCR ;
- `GET /api/applications/` — file des candidatures (gestionnaire) ;
- `PUT /api/applications/{id}/status` — accepter, refuser ou rouvrir un dossier ;
- `POST /api/applications/{id}/score` — recalculer le score.

### Gestion locataire

- `GET|POST /api/tenants/` — rechercher/créer des locataires ;
- `GET|PUT|DELETE /api/tenants/{id}` — fiche complète ;
- sous-routes `incomes`, `emergency-contacts`, `rental-history`, `guarantors`, `leases`, `payments`, `incidents`, `messages`, `interactions`, `legal-cases` ;
- `GET /api/tenants/alerts/late-payments` — détecter et lister les loyers en retard ;
- `POST /api/tenants/{id}/score/recalculate` — actualiser le score de fiabilité.

### Portail locataire

- `POST /tenant-portal/activate`, `/login`, `/refresh` ;
- `GET /tenant-portal/dashboard`, `/leases`, `/payments`, `/receipts`, `/contract-signatures` ;
- `POST /tenant-portal/incidents`, `/messages` ;
- `POST /tenant-portal/payments/{id}/checkout` ;
- `POST /tenant-portal/payments/webhook/stripe`.

### Baux et contrats

- `GET /api/leases/types` — types de contrats disponibles ;
- `POST /api/leases/`, `GET|PUT /api/leases/{id}` — création et paramétrage complet ;
- `POST /api/leases/templates`, `/clauses` — modèles et bibliothèque de clauses ;
- `POST /api/leases/{id}/generate-pdf` — génération du bail PDF ;
- `POST /api/leases/{id}/signature-envelopes` — invitations de signature ;
- `GET|POST /api/lease-signatures/{token}` — parcours public sécurisé du signataire ;
- `POST /api/leases/indices`, `/cap-rules` — valeurs d'indice et plafonds légaux datés ;
- `POST /api/leases/scheduled-revisions/process` — application idempotente des révisions arrivées à échéance ;
- sous-routes `revisions`, `renewals`, `amendments`, `notices`, `documents`, `events` ;
- `GET /api/leases/renewal-alerts` — échéances à 3, 6 mois ou horizon personnalisé ;
- `POST /api/leases/automatic-renewals/process` — tâche idempotente de reconduction tacite ;
- sous-routes `/api/leases/{id}/inspections` — pièces, équipements, compteurs, clés, photos, comparaison, retenues, signatures et PDF ;
- `PUT /api/leases/{id}/inspections/{inspection_id}/mobile-sync` — synchronisation transactionnelle d'une application mobile/hors ligne.

### Gestion financière et comptabilité (`/api/finance`)

- `POST /bank-accounts`, `GET|PUT /bank-accounts/{id}` — multi-comptes bancaires ;
- `POST /bank-accounts/{id}/statements` — import d'un relevé (lignes) ; `GET /bank-accounts/{id}/statements` ;
- `POST /reconciliations` → `/reconciliations/{id}/auto-match`, `/matches` (manuel), `/reconcile` — rapprochement bancaire ;
- `POST /rent-calls/generate?month=YYYY-MM` — génération mensuelle idempotente ;
- `POST /payments/{payment_id}/record?amount=&method=` — encaissement (CB, virement, chèque, espèces…) ;
- `POST /late-payments/detect` — détection automatique ; `GET /late-payments` ; `GET /late-payments/{id}` ;
- `POST /late-payments/{id}/advance` — relance J+5/J+15/J+30/J+60/J+90 ; `POST /late-payments/{id}/penalty` — pénalités ;
- `POST /late-payments/{id}/case`, `POST /cases/{id}/actions` — dossier contentieux ;
- `POST /payment-plans`, `GET /payment-plans/{id}`, `POST /payment-plans/installments/{id}/pay` — plan d'apurement ;
- `POST /charges`, `GET /charges`, `POST /charges/{id}/allocate` — charges et répartition ;
- `POST /allocation-rules`, `POST /charges/regularize?lease_id=&year=`, `POST /charges/budget` — clés, régularisation, budget ;
- `POST /accounts/standard`, `GET /accounts`, `POST /accounts` — plan comptable ;
- `POST /journal-entries`, `GET /journal-entries`, `POST /journal-entries/{id}/validate` — journal ;
- `GET /trial-balance`, `GET /general-ledger/{account_id}` — balance et grand livre ;
- `POST /invoices`, `GET /invoices`, `PUT /invoices/{id}/status`, `POST /invoices/management-fee` — facturation ;
- `POST /deposits`, `GET /deposits/{id}`, `POST /deposits/{id}/deductions`, `POST /deposits/{id}/restitution`, `POST /deposits/{id}/return` — dépôt de garantie ;
- `POST /exports`, `GET /exports` — exports FEC/CSV/Sage/QuickBooks/Ciel.

### Maintenance et travaux (`/api/maintenance`)

- `POST /providers`, `GET /providers`, `GET|PUT /providers/{id}` — annuaire des prestataires ;
- `POST /tickets`, `GET /tickets`, `GET|PUT /tickets/{id}`, `POST /tickets/{id}/status` — ticketing workflow ;
- `POST /tickets/{id}/quotes`, `/quotes/{quote_id}/accept`, `GET /tickets/{id}/quotes/compare` — devis ;
- `POST /tickets/{id}/evaluations`, `POST /tickets/{id}/attachments` — évaluation et pièces jointes ;
- `POST /tickets/escalate` — escalade SLA automatique ;
- `POST /preventive/plans`, `GET /preventive/plans`, `POST /preventive/materialize`, `POST /preventive/tasks/{id}/complete` — maintenance préventive ;
- `GET /calendar?start_date=&end_date=` — calendrier de maintenance ;
- `POST /projects`, `GET /projects`, `GET|PUT /projects/{id}`, `POST /projects/{id}/phases`, `POST /projects/{id}/documents`, `POST /projects/{id}/receive` — travaux lourds ;
- `POST /equipment`, `GET /equipment`, `GET|PUT /equipment/{id}`, `POST /equipment/{id}/logs`, `GET /equipment/{id}/history` — inventaire ;
- `POST /expenses`, `GET /expenses`, `GET /budget?property_id=&year=`, `GET /reporting?year=` — suivi financier ;
- `POST /tickets/{id}/purchase-orders`, `GET /tickets/{id}/purchase-orders`, `PUT /purchase-orders/{id}/status` — bon de commande ;
- `POST /tickets/{id}/quality-control` — contrôle qualité post-intervention ;
- `GET /projects/{id}/gantt` — planning Gantt du projet de travaux.

### Gestion de copropriété (`/api/condo`)

- `POST /buildings`, `GET /buildings`, `GET|PUT /buildings/{id}` — fiche copropriété / immeuble ;
- `POST /buildings/{id}/lots`, `GET /buildings/{id}/lots`, `PUT /lots/{id}` — lots (numéro, type, tantièmes, propriétaire, occupant) ;
- `GET /buildings/{id}/tantiemes-balance` — contrôle de la répartition des tantièmes ;
- `POST /buildings/{id}/common-areas` — parties communes ;
- `POST /buildings/{id}/budgets`, `GET /buildings/{id}/budgets`, `POST /budgets/{id}/vote` — budget prévisionnel et vote ;
- `POST /buildings/{id}/fund-calls`, `GET /buildings/{id}/fund-calls`, `GET /fund-calls/{id}`, `POST /fund-calls/{id}/send`, `POST /fund-calls/lines/{id}/pay` — appels de fonds répartis par tantièmes et suivi des règlements ;
- `GET /buildings/{id}/charges-repartition?fiscal_year=` — répartition annuelle des charges par lot ;
- `GET|PUT /buildings/{id}/works-fund`, `POST /buildings/{id}/works-fund/movements` — fonds de travaux (loi ALUR) ;
- `POST /buildings/{id}/assemblies`, `GET /buildings/{id}/assemblies`, `GET /assemblies/{id}` — assemblées générales ;
- `POST /assemblies/{id}/convene`, `POST /assemblies/{id}/attendance` — convocation et feuille de présence (quorum) ;
- `POST /assemblies/{id}/resolutions`, `POST /resolutions/{id}/vote` — résolutions et votes par tantième (majorités article 24/25/26, unanimité) ;
- `POST /assemblies/{id}/close`, `GET /assemblies/{id}/minutes` — clôture et procès-verbal structuré ;
- `POST /buildings/{id}/council-members`, `GET /buildings/{id}/council-members`, `PUT /council-members/{id}` — conseil syndical ;
- `POST /buildings/{id}/council-meetings`, `GET /buildings/{id}/council-meetings`, `PUT /council-meetings/{id}/minutes` — réunions et comptes-rendus ;
- `POST /buildings/{id}/book-entries`, `GET /buildings/{id}/book-entries` — carnet d'entretien (travaux, contrats, diagnostics, sinistres) ;
- `POST /accounts/standard`, `POST /accounts`, `GET /accounts` — plan comptable copropriété ;
- `POST /buildings/{id}/journal-entries`, `GET /buildings/{id}/journal-entries`, `POST /journal-entries/{id}/validate` — écritures comptables équilibrées ;
- `GET /buildings/{id}/general-ledger?account_code=`, `GET /buildings/{id}/balance-sheet?as_of=` — grand livre et bilan simplifié.

### CRM et gestion commerciale (`/api/crm`)

- `POST /prospects`, `GET /prospects` (filtres type/source/statut/agent/score/recherche), `GET|PUT /prospects/{id}`, `PUT /prospects/{id}/status`, `POST /prospects/{id}/score` — fiche prospect, critères, budget et score de qualité explicable ;
- `GET /pipeline/stages` (8 étapes par défaut), `POST /pipeline/stages`, `PUT /pipeline/stages/{id}` — étapes configurables ; `GET /pipeline/kanban?agent=` — vue Kanban avec valeurs pondérées ;
- `POST /deals`, `GET /deals`, `GET|PUT /deals/{id}`, `POST /deals/{id}/stage` — dossiers, probabilité de conversion, valeur estimée et historique d'étapes ;
- `POST /properties/{id}/availabilities`, `GET /properties/{id}/availabilities?only_free=` — créneaux de disponibilité du bien ;
- `POST /visits`, `GET /visits`, `GET|PUT /visits/{id}`, `POST /visits/{id}/confirm|cancel|complete|reminders|report|feedback` — planification, confirmation, rappels email+SMS, compte-rendu et retour du visiteur ;
- `GET /visits/agenda?view=jour|semaine|mois&date=` — vues agenda ;
- `POST /matching/scan` (seuil et notification automatique), `GET /matching/matches`, `GET /matching/suggestions/{prospect_id}`, `POST /matching/matches/{id}/notify|dismiss` — matching automatique prospect ↔ bien ;
- `POST /listing-templates`, `GET /listing-templates`, `POST /listings`, `GET|PUT /listings/{id}`, `POST /listings/{id}/publish|unpublish`, `GET /listings/{id}/sync|stats`, `POST /listings/{id}/stats`, `GET /listings`, `GET /portals` — modèles d'annonces et diffusion multi-portails centralisée avec statistiques (vues, contacts, conversion) ;
- `POST /offers`, `POST /offers/{id}/accept|refuse|withdraw`, `POST /transactions`, `POST /transactions/{id}/compromis`, `POST /transactions/{id}/conditions`, `POST /transactions/conditions/{id}/decision`, `PUT /transactions/{id}/notary`, `POST /transactions/{id}/acte`, `POST /transactions/{id}/events` — offre d'achat, compromis, conditions suspensives, suivi notaire, acte authentique et commission agence ;
- `GET /notifications`, `PUT /notifications/{id}/read` — notifications commerciales temps réel ;
- `GET /performance?date_from=&date_to=` — KPIs par agent (visites/signature, délai moyen, taux d'occupation, chiffre d'affaires).

### Tableau de bord et reporting (`/api/reporting`)

- `GET /dashboard`, `GET /dashboard/kpis`, `GET /dashboard/charts?months=` — KPIs temps réel et graphiques dynamiques ;
- `GET /dashboard/widgets/catalog`, `GET|POST /dashboard/widgets`, `PUT /dashboard/widgets/reorder`, `PUT|DELETE /dashboard/widgets/{id}`, `GET /dashboard/widgets/{type}/data` — widgets personnalisables (drag & drop) et données associées ;
- `GET /reports/predefined` — liste des 9 rapports ; `GET /reports/predefined/{clé}?year=&month=&format=json|pdf|excel|csv|word` — exécution et export ;
- `GET /custom-reports/datasets` — catalogue des datasets ; `POST|GET /custom-reports`, `GET|PUT|DELETE /custom-reports/{id}`, `POST /custom-reports/{id}/run` — générateur de rapports avec filtres avancés et groupements ;
- `POST /custom-reports/{id}/schedule`, `POST /reports/schedules/run` — planification d'envoi automatique ; `GET /reports/shared/{token}` — partage sans authentification ; `GET /executions` — historique ;
- `GET /exports?dataset=&format=` — exports API pour BI externe (json, pdf, excel, csv, word) ;
- `POST|GET /alert-rules`, `PUT|DELETE /alert-rules/{id}`, `POST /alerts/evaluate`, `GET /alert-events`, `POST /alert-events/{id}/ack` — alertes paramétrables à seuils personnalisables et notifications temps réel.

### Communication et notifications (`/api/comms`)

- `POST|GET /conversations`, `GET /conversations/{id}`, `POST /conversations/{id}/messages`, `POST /conversations/{id}/messages/{id}/attachments`, `PUT /conversations/{id}/archive`, `GET /messages/search` — messagerie interne ;
- `GET|POST /templates`, `PUT /templates/{id}` — modèles d'email personnalisables ;
- `POST /dispatch` — envoi multicanal journalisé (email, SMS, push, in-app, postal) ;
- `GET /in-app`, `PUT /in-app/{id}/read` — notifications in-app ;
- `GET /track/{token}` — pixel de suivi d'ouverture (public) ; `GET /unsubscribe/{token}` — désabonnement ;
- `GET|PUT /preferences` — centre de préférences ;
- `GET|POST /scenarios`, `PUT /scenarios/{id}`, `POST /scenarios/run` — scénarios automatisés et exécution cron ;
- `GET /history` — historique avancé (canal, type, contact, bien, dossier, recherche texte).

### Gestion documentaire (`/api/ged`)

- `GET|PUT /settings`, `GET /types` — paramètres (taille max, compression, rétention) et catalogue de types ;
- `POST|GET /folders`, `GET /folders/tree`, `PUT /folders/{id}` — arborescence ;
- `POST /documents`, `POST /documents/batch`, `GET /documents`, `GET|PUT|DELETE /documents/{id}`, `POST /documents/{id}/versions`, `GET /documents/{id}/download`, `GET /documents/{id}/audit`, `POST /documents/{id}/ocr`, `POST /documents/{id}/erase` — cycle de vie documentaire ;
- `GET|POST /templates`, `PUT /templates/{id}`, `POST /generate` — modèles et génération / prévisualisation ;
- `POST /signatures`, `POST /signatures/{id}/send`, `GET /signatures/{id}`, `POST /signatures/{id}/signers/{id}/sign|decline`, `GET /signatures/{id}/evidence` — circuit de signature et dossier de preuve.

### Administration et sécurité (`/api/admin`, `/api/auth`)

- `POST|GET /api/admin/organizations`, `GET|PUT /api/admin/organizations/{id}`, `GET /api/admin/organizations/{id}/reporting`, `POST|GET /api/admin/agencies`, `PUT /api/admin/agencies/{id}` — sociétés, agences et reporting ;
- `GET /api/admin/roles/profiles`, `POST|GET /api/admin/roles`, `GET|PUT|DELETE /api/admin/roles/{id}` — profils, rôles et matrice de permissions ;
- `POST|GET /api/admin/users`, `GET|PUT /api/admin/users/{id}`, `POST /api/admin/users/{id}/activate|deactivate`, `PUT /api/admin/users/{id}/password`, `GET /api/admin/users/{id}/login-history` — comptes ;
- `GET|PUT /api/admin/security-policy`, `POST /api/auth/login|refresh|logout`, `GET /api/auth/sessions`, `POST /api/auth/2fa/setup|confirm|verify` — politique, verrouillage, sessions et 2FA ;
- `/api/auth/biometric/*`, `/api/auth/sso/{slug}/login|callback|acs`, `/api/admin/sso-providers` — appareils biométriques et SSO ;
- `GET|PUT /api/admin/settings/general|smtp`, `/api/admin/settings/numbering`, `/api/admin/settings/reference-indices` — paramètres généraux ;
- `GET /api/admin/audit-logs`, `GET /api/admin/audit-logs/export`, `/api/admin/backups`, `/api/admin/gdpr/*` — audit, sauvegarde et conformité.

### Géolocalisation (`/api/geolocation`)

- `GET /map/config`, `GET /map/properties`, `PUT /properties/{id}/coordinates` — carte, filtres, clusters et coordonnées ;
- `POST|GET /points-of-interest`, `POST /points-of-interest/batch`, `GET /properties/{id}/location`, `POST /properties/{id}/location-score|travel-time` — proximité, score et trajets ;
- `POST|GET /zones`, `GET|PUT|DELETE /zones/{id}`, `/zones/{id}/agents`, `/zones/{id}/statistics`, `POST /zones/assign-properties` — secteurs et agents ;
- `POST|GET /visits`, `PUT /visits/{id}`, `POST /routes/optimize`, `GET /routes`, `GET /routes/{id}` — visites et tournées.

## Scoring

Le score de candidature (0–100) est explicable et versionné. Il porte uniquement sur :

1. le ratio revenus/loyer ;
2. la stabilité professionnelle ;
3. la complétude des pièces ;
4. leur vérification ;
5. la garantie disponible.

La nationalité, l'âge et le lieu de naissance ne participent pas au score. La décision reste sous le contrôle du gestionnaire. Une acceptation dérogatoire d'un dossier incomplet est possible avec `force=true` et est inscrite dans l'historique.

Le score de fiabilité est recalculé selon les retards de paiement, incidents ouverts et contentieux actifs.

## Tests

```bash
cd backend
python -m unittest discover -s tests -v
```

Les tests utilisent SQLite et couvrent le dépôt d'une candidature, l'OCR, le scoring, la validation, l'activation du portail, les alertes de retard, les quittances, les modèles de bail, les révisions plafonnées, la signature avec dossier de preuve, la comparaison des états des lieux, ainsi que les modules 5 et 6 : appels de loyer, encaissement, impayés et plans d'apurement, charges et régularisation, écritures et balance, facturation, dépôt de garantie, exports, workflow de tickets avec SLA/escalade, devis, maintenance préventive, travaux et équipements.

Le module 7 (copropriété) et les compléments du module 6 (bon de commande, contrôle qualité, planning Gantt) sont couverts par `tests/test_condo_module.py` : lots et tantièmes, budget et vote, appels de fonds répartis automatiquement, paiements, fonds travaux, assemblée générale complète (convocation, présence, résolutions/votes, PV, clôture), conseil syndical, carnet d'entretien et comptabilité dédiée (plan comptable, écritures, grand livre, bilan).

Le module 8 (CRM et gestion commerciale) est couvert par `tests/test_crm_module.py` : score de qualité explicable du prospect, cycle de vie d'un dossier dans le pipeline jusqu'au Kanban, workflow complet des visites (disponibilités réservées/libérées, confirmation, rappels, compte-rendu, retour visiteur, agenda jour/semaine/mois), matching automatique avec détail du score, publication multi-portails avec statistiques et taux de conversion, transaction de vente de l'offre d'achat à l'acte authentique (conditions suspensives bloquantes, commission HT/TTC) et performance des agents.

Le module 9 (tableau de bord et reporting) est couvert par `tests/test_reporting_module.py` : KPIs temps réel et graphiques, widgets avec réorganisation drag & drop, les neuf rapports prédéfinis, les quatre formats d'export (PDF vérifié avec pypdf, Excel, CSV, Word), générateur de rapports personnalisés (filtres coercés vers les enums/dates, groupements avec agrégats), partage par jeton, planification d'exécution et alertes à seuils avec anti-spam et prise de connaissance.

Les modules 12 et 13 sont couverts par `tests/test_modules_12_13.py` : rôles personnalisés et cloisonnement, désactivation et historique, verrouillage et 2FA, sociétés/agences, paramètres, indices, audit, backup SQLite et portabilité RGPD, carte GeoJSON, POI, score de localisation, zones/statistiques, temps de trajet, visites et optimisation de tournée.

Les modules 16 et 17 sont couverts par `tests/test_modules_16_17.py` : prédictions explicables et analyse de marché, chatbot locataire (ticket, suivi, rendez-vous), assistant gestionnaire (recherche, impayés, tickets, échéances, portefeuille, workflow), règles d'automatisation avec idempotence, clés API / OAuth2 / rate limiting / webhooks, catalogue de connecteurs, import CSV avec doublons et export XLSX.

La suite complète comporte **89 tests d'intégration**. Les modules 1 (biens),
2 (propriétaires) et 15 (assurances/sinistres) sont désormais couverts par
`tests/test_module1_2_15_completions.py`. Le seul module encore non couvert
est le module 14 (mobile, socle API uniquement). Voir
[`AUDIT-MODULES.md`](AUDIT-MODULES.md).
