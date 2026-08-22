# GestImmo — API de gestion immobilière

API FastAPI couvrant la gestion des biens, des propriétaires et des locataires.

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
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL='postgresql://immo_user:immo_password_2024@localhost:5432/immo_db'
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

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
