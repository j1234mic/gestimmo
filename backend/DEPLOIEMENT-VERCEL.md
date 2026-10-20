# Déployer l'API GestImmo sur Vercel — pas à pas

Objectif : l'API FastAPI en ligne sur Vercel, avec ses fichiers rendus durables
par **Vercel Blob** et sa sauvegarde quotidienne déclenchée par un **Cron Job**.

> **Ce que vous obtenez** : `https://<projet>.vercel.app/docs`, une mise à
> l'échelle automatique, 0 € sur le plan Hobby.
>
> **Ce que vous acceptez en contrepartie** : le conteneur s'arrête après
> **5 minutes sans trafic** (cold start au réveil), le système de fichiers est
> **en lecture seule hors `/tmp`**, et tout corps de requête supérieur à
> **4,5 Mo** est refusé par la plateforme avant d'atteindre FastAPI.
>
> **Si vous voulez un service toujours allumé avec un vrai disque**, restez sur
> [`DEPLOIEMENT-GRATUIT.md`](DEPLOIEMENT-GRATUIT.md) (Oracle Always Free) ou
> [`DEPLOIEMENT-RENDER-AIVEN.md`](DEPLOIEMENT-RENDER-AIVEN.md) : ce dépôt est
> déjà câblé pour ces cibles (`render.yaml`, `railway.json`, `deploy/install.sh`).

---

## 0. Pourquoi le chemin « conteneur » et non le runtime Python natif

Vercel sait déployer FastAPI sans configuration. Mais ce dépôt a deux besoins que
le runtime Python natif ne peut pas satisfaire :

| Besoin du dépôt | Runtime Python natif | Conteneur (`Dockerfile.vercel`) |
|---|---|---|
| `tesseract-ocr` + français (module 16, OCR des justificatifs) | ❌ pas d'`apt-get` | ✅ |
| `pg_dump` / `mysqldump` (module 12, sauvegardes) | ❌ | ✅ |
| Python 3.11 (celui du `Dockerfile` existant) | ❌ 3.12/3.13/3.14 seulement | ✅ |
| Roues binaires épinglées | ⚠️ `pydantic-core 2.14.5`, `psycopg2-binary 2.9.9`, `uvloop 0.19.0`, `httptools 0.6.1` n'ont **aucune roue cp313** | ✅ |

Le fichier [`../Dockerfile.vercel`](../Dockerfile.vercel) reprend donc le
`Dockerfile` existant et y ajoute les adaptations serverless. Vercel le détecte à
la racine du projet, construit l'image, la pousse dans son registre (VCR) et la
sert depuis une Function sur Fluid compute.

---

## 1. Prérequis

- un compte **GitHub** et le dépôt `j1234mic/gestimmo` ;
- un compte **Vercel** (inscription avec GitHub, sans carte pour le plan Hobby) ;
- une **base de données managée** joignable en TLS depuis Internet : Neon ou
  Aiven (PostgreSQL), TiDB ou Aiven (MySQL). Vercel n'héberge pas de base ;
- Python 3 en local, uniquement pour générer deux clés.

---

## 2. Créer le store Vercel Blob

1. Tableau de bord Vercel → **Storage** → **Create** → **Blob**.
2. Nom : `gestimmo-fichiers`. **Access : Public** (recommandé ici).
3. Connectez le store à votre projet : Vercel ajoute `BLOB_READ_WRITE_TOKEN`
   automatiquement aux variables d'environnement du projet.

> **Public ou privé ?** Les médias de galerie (`/uploads/...`) sont publics par
> nature : le store public les fait servir par le CDN Vercel, sans bande
> passante Function. Les documents locataires sont stockés sous le préfixe
> `private/` mais restent accessibles à quiconque possède l'URL (longue et non
> devinable, générée avec un UUID). Si cette garantie ne suffit pas — RGPD,
> justificatifs d'identité — créez un store **privé** et posez
> `BLOB_ACCESS=private` : l'API relaiera alors chaque lecture après
> authentification (voir `app/services/file_storage.py:response`).

---

## 3. Générer les deux clés

```bash
# SECRET_KEY — signe les jetons JWT (32 octets, encodage URL-safe)
python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

# SECURE_ID_KEY — chiffre les secure_id exposés dans l'API
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> ⚠️ **`SECURE_ID_KEY` doit rester stable entre les déploiements.** Tous les
> `secure_id` déjà stockés en base sont chiffrés avec elle : la changer rend ces
> identifiants illisibles.
>
> ⚠️ **`backend/.env` est actuellement suivi par Git** et contient une clé
> `SECURE_ID_KEY` et un mot de passe de base réels. Avant de connecter le dépôt à
> Vercel : générez de nouvelles clés, retirez le fichier du suivi
> (`git rm --cached backend/.env`) et ajoutez `.env` au `.gitignore`. Le fichier
> est de toute façon exclu de l'image par [`.dockerignore`](../.dockerignore) —
> mais il reste lisible dans l'historique public.

---

## 4. Importer le projet sur Vercel

1. **Add New… → Project** → sélectionnez `j1234mic/gestimmo`.
2. Framework : Vercel détecte `Dockerfile.vercel` et bascule sur le
   **Container Runtime**. Rien à régler : ne définissez **ni** Build Command,
   **ni** Output Directory, **ni** Install Command.
3. Le fichier [`../vercel.json`](../vercel.json) déclare déjà le Cron Job.

---

## 5. Variables d'environnement

À poser dans **Settings → Environment Variables** (Production + Preview) :

| Variable | Exemple | Rôle |
|---|---|---|
| `DATABASE_URL` | `mysql+pymysql://avnadmin:***@mysql-xxx.aivencloud.com:12345/defaultdb?ssl-mode=REQUIRED` | Base managée. Les URL `mysql://` sont réécrites vers PyMySQL automatiquement |
| `SECRET_KEY` | *(générée à l'étape 3)* | Signature des JWT |
| `SECURE_ID_KEY` | *(générée à l'étape 3)* | Chiffrement Fernet des `secure_id` — **stable à vie** |
| `ALLOWED_ORIGINS` | `https://mon-front.vercel.app` | CORS. Pas de `*` en production |
| `PUBLIC_BASE_URL` | `https://<projet>.vercel.app` | Base des URL de retour de paiement |
| `BLOB_READ_WRITE_TOKEN` | *(posé par Vercel à l'étape 2)* | Écriture dans le store Blob |
| `CRON_SECRET` | *(générée : `openssl rand -hex 32`)* | Jeton signé par les Cron Jobs |
| `AUTO_CREATE_TABLES` | `false` | Voir l'encadré ci-dessous |

Les valeurs suivantes sont **déjà fixées dans `Dockerfile.vercel`** et n'ont pas
besoin d'être répétées, sauf si vous voulez les surcharger :

| Variable | Valeur dans l'image | Pourquoi |
|---|---|---|
| `UPLOAD_DIR` | `/tmp/uploads` | Seul `/tmp` est inscriptible |
| `PRIVATE_UPLOAD_DIR` | `/tmp/private_uploads` | idem |
| `BACKUP_DIR` | `/tmp/backups` | idem |
| `LOG_FILE` | *(vide)* | `/app` n'est pas inscriptible ; Vercel collecte stdout |
| `STORAGE_BACKEND` | `blob` | Rend les fichiers durables |
| `BLOB_ACCESS` | `public` | Mode du store créé à l'étape 2 |
| `BACKUP_SCHEDULER_ENABLED` | `false` | La boucle asyncio ne survit pas au scale-to-zero |
| `TRUST_PROXY_HEADERS` | `true` | L'IP réelle est dans `X-Forwarded-For` |
| `ENVIRONMENT` / `DEBUG` | `production` / `false` | — |
| `PAYMENT_SIMULATION_ENABLED` | `false` | — |

> **`AUTO_CREATE_TABLES` : `true` au premier déploiement, puis `false`.**
> Le projet n'a pas d'Alembic : `init_db()` crée les tables absentes et applique
> quelques ALTER additifs. Sur Vercel, ce travail se répète à **chaque cold
> start** (les ~248 tables, l'inspecteur, le backfill `secure_id`, l'amorçage des
> comptes) et deux instances qui démarrent ensemble peuvent se concurrencer sur
> les DDL. Procédure recommandée :
>
> ```bash
> cd backend
> # une fois, depuis votre machine, avec la DATABASE_URL de production
> python scripts/init_schema.py --list-tables
> ```
>
> puis posez `AUTO_CREATE_TABLES=false` dans Vercel et redéployez.

> ⚠️ `init_db()` amorcé par `bootstrap_security()` crée trois comptes de
> démonstration aux mots de passe connus (`admin@immogest.com` / `Admin@2024!`,
> plus un gestionnaire et un lecteur). **Changez-les ou supprimez-les** avant
> d'exposer l'API publiquement.

---

## 6. Premier déploiement et vérification

```bash
# Depuis la racine du dépôt (nécessite le CLI Vercel et Docker en local)
npx vercel link
npx vercel dev          # exécute l'image localement, comme en production
npx vercel deploy --prod
```

Ou poussez simplement la branche : Vercel construit et déploie.

Contrôles à effectuer :

```bash
BASE=https://<projet>.vercel.app

# 1. L'API répond et annonce son moteur de stockage.
curl -s $BASE/health
#    attendu : {"status":"healthy","storage":{"backend":"blob","durable":true,...},
#               "internal_backup_scheduler":false,"writable_storage_dirs":true}

# 2. La documentation OpenAPI est servie.
curl -s -o /dev/null -w "%{http_code}\n" $BASE/docs      # 200

# 3. Le cron refuse un appel non signé.
curl -s -o /dev/null -w "%{http_code}\n" $BASE/api/cron/daily   # 401

# 4. Le cron accepte le jeton signé (mêmes entêtes que Vercel).
curl -s -H "Authorization: Bearer $CRON_SECRET" $BASE/api/cron/status
```

Si `/health` renvoie `"writable_storage_dirs": false`, une racine de stockage
pointe encore hors de `/tmp` : vérifiez qu'aucune variable du projet Vercel
n'écrase `UPLOAD_DIR`, `PRIVATE_UPLOAD_DIR` ou `BACKUP_DIR` avec un chemin
relatif.

---

## 7. La sauvegarde quotidienne par Cron Job

Sur Vercel, aucune tâche de fond ne survit : l'instance est gelée entre deux
requêtes et détruite après ~5 min d'inactivité. La boucle `asyncio` historique
de `app/main.py` y est donc désactivée (`BACKUP_SCHEDULER_ENABLED=false`) et
remplacée par [`../vercel.json`](../vercel.json) :

```json
{ "crons": [ { "path": "/api/cron/daily", "schedule": "0 3 * * *" } ] }
```

Vercel appelle cette route une fois par jour avec
`Authorization: Bearer $CRON_SECRET`. La route
(`app/routes/cron.py`) exécute quatre tâches, chacune isolée — une panne n'arrête
pas les suivantes :

| Tâche | Effet |
|---|---|
| `daily_backup` | Sauvegarde de la base (`pg_dump` / `mysqldump` / copie SQLite), répliquée dans Blob sous `backups/` |
| `report_schedules` | Envoi des rapports planifiés échus (module 9) |
| `rent_revisions` | Application des révisions de loyer arrivées à leur date d'effet (module 4) |
| `automatic_renewals` | Création des renouvellements tacites échus (module 4) |

> **Plan Hobby : une exécution par jour maximum**, avec une précision horaire
> (±59 min). Toute expression plus fréquente (`0 * * * *`) **fait échouer le
> déploiement**. L'horaire `0 3 * * *` est choisi pour respecter
> `daily_hour_utc` (2 h par défaut) : la politique de sauvegarde ignore un
> déclenchement antérieur à cette heure.
>
> Le plan Pro permet une expression par minute si vous voulez avancer la
> précision.

---

## 8. Ce que le serveur ne peut pas faire sur Vercel

Trois limites de la plateforme s'imposent au code, pas à la configuration. Une
quatrième contrainte, elle, découle du stockage facturé :

**1. Les fichiers de plus de 4,5 Mo ne peuvent pas traverser l'API.**
Vercel répond `413 FUNCTION_PAYLOAD_TOO_LARGE` avant même d'atteindre FastAPI.
Sont concernés : les vidéos de galerie (`mp4`, `mov`, `webm`, `m4v`) et toute
pièce jointe volumineuse. `settings.effective_upload_limit` ramène la limite
annoncée à 4,5 Mo sur Vercel. La seule issue est un **téléversement direct du
navigateur vers le store Blob** (« client uploads », SDK `@vercel/blob/client`) :
le fichier ne passe plus par la Function. Cela suppose un frontend — le dépôt
n'en contient aucun — et une route de génération de jeton, qui doit être écrite
en JavaScript.

**2. Les réponses sont limitées à 4,5 Mo, sauf en streaming.**
Les exports PDF/Excel du dépôt utilisent `StreamingResponse` et ne sont donc pas
concernés.

**3. `/tmp` est effacé à l'arrêt de l'instance.**
Tout ce qui n'est pas répliqué dans Blob est perdu. C'est précisément le rôle de
la façade `app/services/file_storage.py` : chaque écriture est suivie d'un
`mirror()` vers le store, et la référence persistée en base devient l'URL Blob.

**4. Les objets Blob orphelins restent facturés.**
Quand un bail est modifié, qu'une clause est ajoutée ou retirée,
`app/routes/leases.py` incrémente `contract_version` et remet
`lease.document_storage_path` à `None` : le contrat PDF est invalidé en base,
mais le fichier n'est pas supprimé. C'est un comportement **antérieur à cette
adaptation** (le fichier restait déjà sur le disque local) et il a été conservé
tel quel : il s'agit de contrats, et une piste d'audit matérielle peut être
préférable à une suppression. La différence sur Vercel est que l'objet continue
d'occuper du stockage Blob facturé, sans plus être référencé nulle part.

Pour récupérer cet espace, listez le store et comparez aux références en base
(au-delà de 1 000 objets, recommencez en passant le `cursor` renvoyé) :

```bash
curl -s "https://vercel.com/api/blob?limit=1000" \
  -H "authorization: Bearer $BLOB_READ_WRITE_TOKEN" \
  -H "x-vercel-blob-store-id: $BLOB_STORE_ID" \
  -H "x-api-version: 13"
```

Si vous préférez supprimer le document dès son invalidation, appelez
`file_storage.delete(reference)` juste avant la remise à `None` dans les trois
sites concernés — la façade gère les deux moteurs et ignore silencieusement une
référence déjà absente.

Par ailleurs, la limitation de débit reste **par instance** (compteur en
mémoire) : elle ne remplace pas un compteur partagé. Pour une protection réelle,
branchez Upstash Redis ou le WAF Vercel.

---

## 9. Ce qui a été adapté dans le code

| Fichier | Adaptation |
|---|---|
| `app/config.py` | `STORAGE_BACKEND`, `BLOB_*`, `CRON_SECRET`, `TRUST_PROXY_HEADERS`, `BACKUP_SCHEDULER_ENABLED`, détection `is_vercel_environment()`, `effective_upload_limit` |
| `app/services/blob_storage.py` | Client REST Vercel Blob (httpx, sans dépendance nouvelle), contrat reproduit du SDK officiel `@vercel/blob` 2.8.2 |
| `app/services/file_storage.py` | Façade local/Blob : `mirror`, `reference_for`, `response`, `read_bytes`, `exists`, `delete`, `materialize` |
| `app/middleware/rate_limit.py` | `client_ip()` lit `X-Forwarded-For` quand le proxy est de confiance |
| `app/routes/cron.py` | `GET /api/cron/daily` et `/api/cron/status`, authentifiés par `CRON_SECRET` |
| `app/main.py` | Création des racines tolérante aux échecs, montage `/uploads` conditionnel, `/health` enrichi, planificateur interne gardé |
| 12 routeurs + 6 services | Écritures répliquées vers Blob, lectures via la façade |
| `scripts/init_schema.py` | Initialisation unique du schéma, hors cold start |
| `../Dockerfile.vercel`, `../.dockerignore`, `../vercel.json` | Cible Vercel |

Le SDK Python officiel `vercel-blob` n'est **pas** utilisé : il exige
`pydantic>=2.7` et `httpx2`, incompatibles avec les versions épinglées du projet
(`pydantic==2.5.2`, `httpx==0.25.2`). Le client maison n'ajoute donc aucune
dépendance.

---

## 10. Latence depuis Madagascar

Les Functions Vercel s'exécutent par défaut en `iad1` (Virginie, États-Unis) :
comptez ~250 à 300 ms aller-retour depuis Antananarivo, plus le cold start après
une période d'inactivité. Le choix de la région est un réglage Pro
(multi-régions) ; `fra1` (Francfort) est le plus proche de l'océan Indien parmi
les régions européennes. Pour un usage quotidien à Madagascar, un VPS Oracle
Always Free à Johannesburg ou Mumbai
([`../deploy/install.sh`](../deploy/install.sh)) reste plus réactif — et sans
cold start.

---

## 11. Tests

```bash
cd backend
python -m unittest discover -s tests              # suite complète
python -m unittest tests.test_vercel_deployment   # adaptations Vercel seules
```

Les tests Vercel n'appellent jamais le vrai service : la couche HTTP est
remplacée par un client factice qui enregistre les requêtes. Ils vérifient le
contrat REST (URL, méthode, entêtes `x-api-version`, `x-vercel-blob-access`), les
deux moteurs de la façade, la lecture de `X-Forwarded-For` et l'authentification
du cron — sans réseau ni jeton.
