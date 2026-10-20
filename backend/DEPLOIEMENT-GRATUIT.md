# Déploiement gratuit — hébergement + base MySQL

Ce guide propose des combinaisons **gratuites en 2026** pour mettre en ligne
cette API FastAPI avec une base **MySQL**, et documente la compatibilité MySQL
ajoutée au backend.

> Les offres gratuites évoluent vite (Fly.io et Koyeb ont supprimé la leur,
> PlanetScale n'a plus de plan gratuit, Render a réduit sa bande passante en
> avril 2026). Les chiffres ci-dessous ont été vérifiés en octobre 2026 ;
> revérifiez les pages officielles avant de vous engager.

---

## 1. En bref : trois combinaisons

| # | Hébergement | Base MySQL | Coût | Durée | Mise en place | Limite principale |
|---|---|---|---|---|---|---|
| **A** | **Oracle Cloud Always Free** — VM ARM 2 OCPU / 12 Go, 200 Go de disque | **MySQL HeatWave Always Free** (50 Go) ou MySQL 8.4 en Docker sur la VM | 0 € | **sans limite** | 1 à 2 h (ou ~10 min avec `deploy/cloud-init.yaml`) | Carte bancaire pour vérifier l'identité ; capacité ARM parfois indisponible |
| **B** | **Render Free** (Docker) — 512 Mo, 0,1 CPU | **Aiven MySQL Free** — 1 Go | 0 € | **sans limite** (le service web n'expire pas) | 20 à 30 min | Mise en veille après 15 min ; disque éphémère ; 5 Go de trafic/mois |
| **C** | **Google Cloud Run** — 2 M requêtes/mois | **Aiven MySQL** ou **TiDB Cloud Starter** | 0 € | **sans limite** (quota mensuel) | 1 h | Carte bancaire obligatoire ; disque éphémère ; 1 Go d'egress gratuit |

> ⚠️ **La seule offre « 30 jours » du lot est le PostgreSQL gratuit de
> Render** : il expire 30 jours après sa création, puis il est supprimé après
> 14 jours de grâce. Aucune des combinaisons ci-dessus ne l'utilise (base
> MySQL externe ou MySQL local). Voir
> [`../deploy/README.md`](../deploy/README.md) pour le tableau des durées.

**Recommandation**

- **Pour un service qui doit rester allumé et conserver les fichiers**
  (documents, photos, sauvegardes) → **option A**. C'est la seule combinaison
  gratuite qui offre un vrai disque persistant et assez de RAM pour l'OCR.
- **Pour une démonstration rapide, sans carte bancaire** → **option B**.
  Acceptez la mise en veille et la perte des uploads à chaque redéploiement.
- **Option C** si vous êtes déjà à l'aise avec Google Cloud et que le trafic
  est faible.

**Latence depuis Antananarivo** : Oracle Johannesburg est la région la plus
proche ; Render (Francfort), Aiven (région non choisie) et Cloud Run
(europe-west1) ajoutent une centaine de millisecondes par aller-retour. Pour
une démonstration c'est sans conséquence, pour une saisie interactive
intensive, l'option A est nettement plus confortable.

Et si MySQL n'est pas une contrainte absolue : **gardez PostgreSQL**. Le code
est écrit pour PostgreSQL depuis l'origine ; Neon, Supabase ou Aiven
PostgreSQL offrent un plan gratuit et **aucune modification de code n'est
nécessaire** (voir § 8).

---

## 2. Ce que ce backend exige réellement

| Contrainte | Détail | Conséquence pour l'hébergement |
|---|---|---|
| Image Docker | `backend/Dockerfile` (Python 3.11 + tesseract + clients PostgreSQL/MySQL) | Choisir une plateforme qui accepte un `Dockerfile` |
| Dépendances lourdes | PyMuPDF, reportlab, Pillow, openpyxl, python-docx, tesseract | 512 Mo de RAM sont justes ; les gros PDF/OCR peuvent dépasser et tuer le conteneur |
| Base | 248 tables, 778 index, `create_all` au démarrage | Le premier démarrage est lent (plusieurs dizaines de secondes), surtout à 0,1 CPU ; prévoir un healthcheck tolérant |
| Fichiers | `uploads/`, `private_uploads/`, `backups/` sur le disque local | Sans volume persistant, **les documents sont perdus** à chaque redéploiement ou réveil |
| Sauvegardes | `pg_dump` / `mysqldump` / copie SQLite appelés depuis l'API | Le client correspondant doit être présent dans l'image (c'est le cas) |
| Migrations | Pas d'Alembic : `AUTO_CREATE_TABLES=true` crée les tables manquantes | Acceptable sur une base neuve ; pour faire évoluer un schéma existant, prévoir une migration SQL manuelle |
| Port | Uvicorn sur `8000` | Le `Dockerfile` lit désormais `$PORT` (Render/Cloud Run) et retombe sur `8000` |

### Poids mémoire estimé

L'import de FastAPI + SQLAlchemy + PyMuPDF + reportlab + Pillow représente
déjà **150 à 250 Mo de RSS** au repos (estimation, pas un benchmark), avant
tout traitement OCR ou génération de PDF. C'est pour cela que 512 Mo sur
Render Free sont un plafond, pas une marge.

---

## 3. Compatibilité MySQL — ce qui a été ajouté

Le backend était **PostgreSQL uniquement**. Il tourne maintenant sur MySQL 8.x
sans changer le code métier. Modifications apportées :

| Fichier | Changement |
|---|---|
| `backend/requirements.txt` | Ajout de `PyMySQL==1.2.3` (pilote pur Python, compatible ARM) |
| `backend/app/config.py` | `mysql://` et `mariadb://` réécrits vers `mysql+pymysql://` ; hôtes compose `mysql`/`mariadb` remappés vers `localhost` hors Docker |
| `backend/app/database.py` | Conversion de `ssl-mode` / `ssl-ca` / `ssl-cert` / `ssl-key` en options PyMySQL ; `pool_recycle=280` ; création d'index portable (MySQL ne connaît pas `CREATE INDEX IF NOT EXISTS`) |
| `backend/app/models/ai_automation.py` | Index préfixe de 191 caractères sur `VARCHAR(1000)` (limite MySQL de 3 072 octets en utf8mb4) |
| `backend/app/services/admin_security_service.py` | Sauvegarde MySQL via `mysqldump` (fichier `.sql`), message de restauration hors ligne explicite |
| `backend/Dockerfile` | Ajout de `default-mysql-client` (mysqldump) ; port piloté par `$PORT` |
| `backend/docker-compose.mysql.yml` | Stack complète API + MySQL 8.4, healthcheck et volumes persistants |
| `backend/tests/test_mysql_support.py` | Tests de préparation d'URL et de compilation du schéma pour le dialecte MySQL |
| `render.yaml` | Blueprint Render (Docker, plan gratuit, base MySQL externe) |

**Validation** : les 136 tests passent (SQLite) et le schéma complet (248
tables, 778 index) compile pour le dialecte MySQL. Aucun serveur MySQL n'était
disponible dans l'environnement de développement : le premier `create_all`
réel est donc à surveiller dans les logs de démarrage (`docker compose logs -f
api`). Les erreurs de type `Specified key was too long` ou de syntaxe DDL
seraient visibles immédiatement.

### URL de connexion

```bash
# MySQL local (docker-compose.mysql.yml)
DATABASE_URL=mysql+pymysql://immo_user:immo_password_2024@localhost:3306/immo_db?charset=utf8mb4

# Base managée avec TLS obligatoire (Aiven, HeatWave…)
DATABASE_URL=mysql+pymysql://avnadmin:motdepasse@mysql-xxxx.aivencloud.com:12345/defaultdb?ssl-mode=REQUIRED
```

`ssl-mode` accepte `REQUIRED` (chiffré, certificat non validé),
`VERIFY_CA` (certificat validé) et `VERIFY_IDENTITY` (certificat + nom
d'hôte). Ajoutez `&ssl-ca=/chemin/ca.pem` si l'autorité n'est pas dans le
magasin système.

> ⚠️ **`SECURE_ID_KEY` doit rester stable.** Sans elle, une clé éphémère est
> générée à chaque démarrage et les `secure_id` déjà stockés deviennent
> illisibles. Générez-la une fois :
> `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

### Vérifier localement

```bash
cd backend

# 1) Tests (SQLite + compilation du schéma MySQL)
python -m unittest discover -s tests -v

# 2) Stack MySQL complète
docker compose -f docker-compose.mysql.yml up -d --build
curl http://localhost:8000/health

# 3) État de la base
docker compose -f docker-compose.mysql.yml exec mysql \
  mysql -u immo_user -pimmo_password_2024 -e "USE immo_db; SHOW TABLES;" | head
```

Les tests `test_mysql_support.py` compilent **toutes** les tables et tous les
index avec le dialecte MySQL de SQLAlchemy et vérifient qu'aucune clé d'index
ne dépasse 3 072 octets : une future colonne `String(1000)` indexée sera
détectée avant le déploiement.

---

## 4. Option A — Oracle Cloud Always Free (recommandé)

### Ce que le plan gratuit couvre (2026)

| Ressource | Quota Always Free |
|---|---|
| Compute ARM Ampere A1 | **2 OCPU + 12 Go de RAM** (réduit depuis 4 OCPU/24 Go en juin 2026) |
| Compute AMD | 2 micro-VM (1/8 OCPU, 1 Go chacune) |
| Stockage bloc | 200 Go au total |
| Trafic sortant | 10 To/mois |
| MySQL HeatWave | **1 système, 1 ECPU, 50 Go de stockage + 50 Go de sauvegardes**, dans la région d'accueil |
| Carte bancaire | Obligatoire pour vérifier l'identité (pas de carte virtuelle/prépayée), débit 0 € sur les ressources Always Free |
| Région d'accueil | Définitive, choisie à l'inscription parmi celles proposées ; Always Free uniquement dans cette région |
| Compte inactif | Un compte laissé inactif 30 jours peut être suspendu : une sonde `/health` toutes les 30 min l'évite |

Sources : [Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm),
[MySQL HeatWave Always Free](https://blogs.oracle.com/mysql/introducing-heatwave-always-free),
[limites 2026](https://fullmetalbrackets.com/blog/oci-free-tier-breakdown).

### A.1 Créer le compte et la VM

1. Créez un compte sur [cloud.oracle.com/free](https://cloud.oracle.com/free).
   La **région d'accueil** proposée dépend du pays/territoire saisi et de la
   disponibilité : Johannesburg n'apparaît pas toujours. Prenez alors la plus
   proche parmi celles offertes — Dubai, Jeddah, Casablanca, puis Paris,
   Marseille, Francfort ou Milan. Oracle le documente : « si votre région ne
   est pas disponible, choisissez une région adjacente ». Ce choix est
   **définitif** pour les ressources Always Free, mais il n'influence que la
   latence et la capacité ARM. Détail et tableau des latences :
   [`../deploy/README.md`](../deploy/README.md#quelle-région-daccueil-choisir-si-johannesburg-napparaît-pas).
2. **Compute → Instances → Create instance** :
   - image **Ubuntu 24.04** (ou 22.04), architecture **aarch64** ;
   - shape **VM.Standard.A1.Flex**, 2 OCPU et 12 Go (tout le quota) ;
   - disque de démarrage 100–200 Go (dans les 200 Go gratuits) ;
   - réseau : VCN par défaut, **IP publique** activée ;
   - ajoutez votre clé SSH publique.
3. Ouvrez les ports dans la **Security List** du subnet : `22`, `80`, `443`
   (n'ouvrez `8000` que temporairement, pour tester).
4. Connectez-vous :

```bash
ssh -i ~/.ssh/ma-cle ubuntu@<IP_PUBLIQUE>
```

Si Oracle répond « Out of host capacity » (fréquent sur A1, y compris à
Johannesburg) : réessayez plus tard, changez de domaine de disponibilité, ou
utilisez les **2 micro-VM AMD de 1 Go** incluses dans l'offre gratuite avec la
variante SQLite :

```bash
sudo /opt/gestimmo/deploy/install.sh --sqlite --domain api.example.com --email moi@example.com
```

MySQL 8.4 + l'API ne tiennent pas dans 1 Go de RAM ; SQLite, si
(`backend/docker-compose.sqlite.yml`).

### A.2 Déploiement automatique (recommandé)

Copiez [`../deploy/cloud-init.yaml`](../deploy/cloud-init.yaml) dans le champ
**Cloud-init script** de la création d'instance (après avoir remplacé `main`
par la branche à déployer) : la VM installe Docker, Caddy, génère les clés,
démarre la stack et programme la sauvegarde. Suivi :

```bash
ssh ubuntu@<IP_PUBLIQUE> 'sudo tail -f /var/log/gestimmo-install.log'
```

Pour tout autre serveur Ubuntu/Debian, une seule commande :

```bash
sudo ./deploy/install.sh --domain api.example.com --email moi@example.com
```

La suite de cette section décrit la procédure manuelle, équivalente.

### A.2bis Installer Docker et lancer la stack manuellement

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER
newgrp docker   # ou déconnexion/reconnexion

git clone https://github.com/j1234mic/gestimmo.git
cd gestimmo/backend
cp .env.example .env
```

Éditez `.env` :

```bash
SECRET_KEY=<sortie de: python3 -c "import secrets; print(secrets.token_urlsafe(48))">
SECURE_ID_KEY=<sortie de: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
ALLOWED_ORIGINS=https://votre-frontend.example.com
PUBLIC_BASE_URL=https://api.example.com
ENVIRONMENT=production
DEBUG=false
PAYMENT_SIMULATION_ENABLED=false
```

Puis :

```bash
docker compose -f docker-compose.mysql.yml up -d --build
docker compose -f docker-compose.mysql.yml ps
curl http://localhost:8000/health
```

Les données MySQL, les uploads publics, les dossiers locataires et les
sauvegardes vivent dans quatre volumes nommés : un `down` ne les supprime pas
(seul `down -v` le fait). Pensez tout de même à sauvegarder le volume ou à
utiliser l'endpoint `POST /api/admin/backups` avec un jeton administrateur
(mysqldump est dans l'image).

### A.3 Utiliser MySQL HeatWave Always Free à la place du conteneur

1. Console Oracle → **Databases → MySQL HeatWave → Create DB system**.
2. Choisissez **Always Free**, un nom, les identifiants administrateur, le VCN.
3. Attendez la fin du provisionnement, puis récupérez le **endpoint** public.
   Autorisez l'adresse IP publique de la VM dans les règles d'accès du DB
   system (ou placez les deux ressources dans le même VCN).
4. Créez la base et l'utilisateur applicatif :

```sql
CREATE DATABASE immo_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'immo_user'@'%' IDENTIFIED BY 'mot-de-passe-fort';
GRANT ALL PRIVILEGES ON immo_db.* TO 'immo_user'@'%';
FLUSH PRIVILEGES;
```

5. Démarrez l'API en pointant vers HeatWave (le conteneur MySQL local démarre
   aussi mais n'est pas utilisé ; vous pouvez l'arrêter ensuite) :

```bash
export DATABASE_URL_MYSQL='mysql+pymysql://immo_user:mot-de-passe-fort@<endpoint>:3306/immo_db?ssl-mode=REQUIRED'
docker compose -f docker-compose.mysql.yml up -d --build api
```

> Le plan gratuit HeatWave est limité à **1 ECPU** et vit dans la région
> d'accueil. Pour une application de démonstration, c'est largement suffisant ;
> pour de la production, préférez une base payante ou le MySQL de la VM.

### A.4 Nom de domaine et HTTPS (Caddy)

Caddy obtient et renouvelle automatiquement un certificat Let's Encrypt. Faites
pointer un enregistrement `A` de `api.example.com` vers l'IP publique, ouvrez
80/443, puis :

```bash
sudo apt-get install -y caddy
sudo tee /etc/caddy/Caddyfile >/dev/null <<'EOF'
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl reload caddy
```

L'API est alors disponible sur `https://api.example.com/docs`.

### A.5 Points de vigilance

- **Récupération des instances inactives** : Oracle peut récupérer une VM
  Always Free restée très inactive. Un service qui répond tous les jours limite
  le risque ; sinon, ajoutez une sonde externe (UptimeRobot gratuit) sur
  `/health`.
- **Sauvegardes** : le disque bloc Oracle n'est pas une sauvegarde. Programmez
  `POST /api/admin/backups/run-daily` avec un jeton administrateur (Bearer JWT),
  ou une tâche cron qui exécute `mysqldump` via `docker compose exec`, puis
  copiez les `.sql` hors de la VM.
- **Mises à jour** : `git pull && docker compose -f docker-compose.mysql.yml up -d --build`.
- **Coût** : restez dans les quotas (2 OCPU/12 Go, 200 Go de bloc). Au-delà,
  Oracle facture.
- **Si le gratuit devient pénible** : un VPS Hetzner CX22 (2 vCPU, 4 Go,
  40 Go NVMe) coûte environ 4–5 €/mois et héberge la même stack Docker sans
  mise en veille ni quota de trafic surprenant.

---

## 5. Option B — Render Free + Aiven MySQL Free

C'est la combinaison la plus rapide : **aucune carte bancaire**, un dépôt
GitHub, et deux services à créer.

> 📖 Procédure détaillée, commande par commande :
> [`DEPLOIEMENT-RENDER-AIVEN.md`](DEPLOIEMENT-RENDER-AIVEN.md).

### B.1 Créer la base Aiven MySQL

1. Créez un compte sur [aiven.io](https://aiven.io/free-mysql-database) — sans
   carte bancaire.
2. **Create service → MySQL → plan Free**.
   - 1 Go de stockage, 1 Go de RAM, 1 CPU, un seul nœud, **76 connexions max**.
   - Un seul service gratuit par type et par organisation.
   - Le service peut être **mis hors tension après une période d'inactivité**
     (vous êtes prévenu par e-mail et pouvez le rallumer).
3. Dans l'onglet **Overview**, copiez l'**URI de connexion**, qui ressemble à :

```
mysql://avnadmin:motdepasse@mysql-xxxx.aivencloud.com:12345/defaultdb?ssl-mode=REQUIRED
```

4. Transformez-la en URL SQLAlchemy : remplacez `mysql://` par
   `mysql+pymysql://` (le backend le fait aussi tout seul) et gardez le port
   indiqué (souvent `12345`, pas `3306`).

> Astuce : créez une base dédiée `immo_db` et un utilisateur applicatif plutôt
> que d'utiliser `defaultdb`/`avnadmin` :
> `mysql --ssl-mode=REQUIRED -h <host> -P <port> -u avnadmin -p -e "CREATE DATABASE immo_db;"`

### B.2 Déployer l'API sur Render

1. Poussez le dépôt sur GitHub.
2. [dashboard.render.com](https://dashboard.render.com) → **New → Blueprint** →
   sélectionnez le dépôt. Render lit `render.yaml` à la racine.
3. Renseignez les variables demandées :
   - `DATABASE_URL` : l'URL Aiven ci-dessus ;
   - `SECURE_ID_KEY` : clé Fernet générée localement et conservée ;
   - `ALLOWED_ORIGINS` : vos domaines frontend ;
   - `PUBLIC_BASE_URL` : `https://gestimmo-api.onrender.com`.
4. Render construit `backend/Dockerfile` et expose `/health`.

### B.3 Limites à connaître

| Limite Render Free | Impact sur ce backend |
|---|---|
| 512 Mo RAM, 0,1 CPU | OCR et gros PDF peuvent échouer (OOM) ; premier démarrage lent |
| Mise en veille après 15 min sans trafic, réveil ~1 min | Le premier appel de la journée est lent |
| 750 h d'instance/mois par workspace | Un seul service qui tourne 24/7 en consomme 720 : pas de marge pour un second service |
| **5 Go de trafic/mois** (réduit en avril 2026) | Insuffisant pour servir beaucoup de photos/documents |
| Disque éphémère, pas de disque persistant sur le plan gratuit | **Les uploads sont perdus** à chaque redéploiement, redémarrage ou réveil |
| Pas de sauvegarde de la base gratuite | Utilisez Aiven, pas le PostgreSQL Render (qui expire en 30 jours) |

Sources : [render.com/docs/free](https://render.com/docs/free),
[limites 2026](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026).

### B.4 Alternative à Aiven : TiDB Cloud Starter

TiDB parle le protocole MySQL et offre **5 Gio de lignes + 5 Gio colonnaires +
50 M de Request Units par instance** (jusqu'à 5 instances gratuites), sans
carte bancaire. C'est plus généreux qu'Aiven, mais TiDB **n'est pas MySQL à
100 %** : pas de procédures stockées, de triggers ni d'événements, et certaines
fonctions se comportent différemment. Cette application n'en utilise pas, mais
testez votre schéma avant d'y déplacer des données existantes.
Voir [docs.pingcap.com/tidbcloud/select-cluster-tier](https://docs.pingcap.com/tidbcloud/select-cluster-tier/).

---

## 6. Option C — Google Cloud Run + Aiven/TiDB

Cloud Run facture à la requête et **descend à zéro** quand il n'y a pas de
trafic. Le plan Always Free couvre environ **2 M de requêtes, 180 000
vCPU-secondes et 360 000 Gio-secondes par mois** (1 Go d'egress Amérique du
Nord). Une carte bancaire est obligatoire, même si le quota reste gratuit.

```bash
# Prérequis : gcloud CLI authentifié, facturation activée
gcloud run deploy gestimmo-api \
  --source backend \
  --region europe-west1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 300 \
  --set-env-vars ENVIRONMENT=production,DEBUG=false,AUTO_CREATE_TABLES=true \
  --set-env-vars DATABASE_URL='mysql+pymysql://…@…?ssl-mode=REQUIRED' \
  --set-env-vars SECRET_KEY='…' \
  --set-env-vars SECURE_ID_KEY='…'
```

Points d'attention :

- **Système de fichiers éphémère** : les uploads disparaissent à chaque
  instance froide. Il faudrait ajouter un stockage objet (S3/GCS) au code —
  ce n'est pas prévu aujourd'hui.
- **Cold start** : ~1 à 3 s pour cette image, mais le premier appel qui suit
  une longue veille peut être plus lent (imports + connexion MySQL).
- **Egress** : 1 Go/mois gratuit seulement ; au-delà, facturation.
- Cloud Run ne sait pas exécuter `docker compose` : il ne déploie qu'un
  conteneur. Utilisez une base MySQL externe (Aiven, TiDB, HeatWave).

---

## 7. Comparatif des bases MySQL gratuites (octobre 2026)

| Offre | Moteur | Gratuit | Carte | Points forts | Points faibles |
|---|---|---|---|---|---|
| **Oracle MySQL HeatWave** | MySQL 8.x managé | 50 Go, 1 ECPU | Oui (vérification) | Le plus gros quota, sauvegardes incluses | Région d'accueil unique, création via console Oracle |
| **Aiven MySQL** | MySQL managé | 1 Go, 1 Go RAM, 1 CPU | Non | Simple, TLS, sauvegardes | 76 connexions, service mis hors tension si inactif, région non choisie |
| **TiDB Cloud Starter** | Compatible MySQL | 5 Gio + 50 M RU / instance | Non | Généreux, 5 instances | Pas 100 % MySQL (ni triggers ni procédures) |
| **Railway MySQL** | MySQL non managé | 1 $ de crédit/mois après l'essai | Non | Intégré au déploiement | Le crédit ne couvre pas une base + une API 24/7 |
| **PlanetScale** | MySQL (Vitess) | — | — | — | Plus de plan gratuit |

Hors MySQL : **PostgreSQL** gratuit chez Neon (0,5 Go), Supabase (500 Mo) et
Aiven (1 Go). Le backend fonctionne dessus **sans modification**.

---

## 8. Et si vous pouviez garder PostgreSQL ?

Le dépôt utilise PostgreSQL par défaut (`psycopg2-binary`, `JSONB` évité,
SQL standard). Passer à MySQL a nécessité les correctifs listés au § 3 ; rester
sur PostgreSQL évite cette couche et conserve les types/limites d'origine.

| Offre PostgreSQL gratuite | Quota | Remarque |
|---|---|---|
| Neon | 0,5 Go par projet, 100 CU-h/mois | Mise à l'échelle à zéro, branches |
| Supabase | 500 Mo, 60 connexions | Pause du projet après inactivité |
| Aiven PostgreSQL | 1 Go, 1 Go RAM | Même limites que MySQL |

Avec Render, utilisez **Aiven ou Neon** plutôt que le PostgreSQL gratuit de
Render : celui-ci **expire 30 jours après sa création**.

---

## 9. Checklist avant d'exposer l'API

- [ ] `SECRET_KEY` généré (≥ 32 caractères aléatoires), différent du exemple.
- [ ] `SECURE_ID_KEY` générée **une fois** et conservée (sinon les `secure_id`
      existants deviennent illisibles).
- [ ] `DEBUG=false` et `ENVIRONMENT=production`.
- [ ] `ALLOWED_ORIGINS` limité à vos domaines (pas `*`).
- [ ] `PUBLIC_BASE_URL` correct (URL de retour des paiements).
- [ ] `PAYMENT_SIMULATION_ENABLED=false` si des clés de paiement sont fournies.
- [ ] TLS activé (Caddy, Render, Cloud Run) ; le port 8000 non exposé au monde.
- [ ] Volumes persistants pour `uploads/`, `private_uploads/`, `backups/`.
- [ ] Sauvegarde quotidienne testée (`POST /api/admin/backups`, jeton admin) et
      copiée hors du serveur.
- [ ] `tesseract-ocr-fra` présent dans l'image (c'est le cas du Dockerfile).
- [ ] `AUTO_CREATE_TABLES=true` uniquement sur une base neuve ; ensuite,
      prévoyez une migration SQL avant de le désactiver.
- [ ] Le fichier `backend/.env` est **versionné** dans ce dépôt : retirez-le du
      suivi Git (`git rm --cached backend/.env`) et ajoutez `.env` au
      `.gitignore` avant de mettre des secrets réels dedans.

---

## 10. Dépannage MySQL

| Symptôme | Cause | Correctif |
|---|---|---|
| `ModuleNotFoundError: MySQLdb` | URL `mysql://` sans pilote | Utilisez `mysql+pymysql://` (le backend le réécrit, mais vérifiez que le code déployé est à jour) |
| `Access denied for user` | Mot de passe, hôte `%` ou base inexistante | Vérifiez l'utilisateur, `CREATE USER …@'%'`, et le nom de base |
| `cryptography package is required` | MySQL 8 utilise `caching_sha2_password` | `cryptography` est déjà tiré par `python-jose[cryptography]` ; sinon installez-le |
| `Specified key was too long` | Index sur une longue `VARCHAR` en utf8mb4 | Le correctif du § 3 est en place ; sinon, ajoutez `mysql_length` à l'index |
| `CREATE INDEX IF NOT EXISTS` → erreur de syntaxe | Syntaxe PostgreSQL/SQLite | Le backend utilise désormais l'inspecteur SQLAlchemy |
| `mysqldump: command not found` | Image sans client MySQL | Reconstruisez avec le `Dockerfile` mis à jour (`default-mysql-client`) |
| Connexions coupées après quelques minutes | `wait_timeout` MySQL | `pool_pre_ping=True` + `pool_recycle=280` sont configurés |
| Restauration de sauvegarde refusée | MySQL ne remplace pas son fichier à chaud | Restaurez hors ligne : `mysql -h … -u … base < sauvegarde.sql` |

---

## 11. Liens utiles

- Render — plan gratuit et limites : <https://render.com/docs/free>
- Aiven — MySQL gratuit : <https://aiven.io/docs/products/mysql/concepts/mysql-free-tier>
- Oracle — ressources Always Free : <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm>
- Oracle — MySQL HeatWave Always Free : <https://blogs.oracle.com/mysql/introducing-heatwave-always-free>
- TiDB Cloud — plan Starter : <https://docs.pingcap.com/tidbcloud/select-cluster-tier/>
- Google Cloud Run — tarification et quotas gratuits : <https://cloud.google.com/run/pricing>
