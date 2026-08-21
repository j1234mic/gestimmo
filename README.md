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

Les tests utilisent SQLite et couvrent le dépôt d'une candidature, l'OCR, le scoring, la validation, l'activation du portail, les alertes de retard, les quittances, les modèles de bail, les révisions plafonnées, la signature avec dossier de preuve et la comparaison des états des lieux.
