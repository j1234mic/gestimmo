# Déploiement — sans limite de 30 jours

Ce dossier contient le déploiement **automatisé** de GestImmo sur un serveur
qui reste gratuit sans échéance.

## Quelle offre n'a PAS de limite de 30 jours ?

| Offre | Durée réelle | Ce qui expire |
|---|---|---|
| **Oracle Cloud Always Free** (VM + MySQL HeatWave) | Illimitée | Rien. Oracle peut récupérer une VM très inactive ; une sonde `/health` suffit à l'éviter. |
| **Aiven MySQL Free** | Illimitée | Rien. Le service est mis **hors tension** après inactivité, puis rallumé d'un clic. |
| **Render — service web Free** | Illimitée | Rien pour le service. Il s'endort après 15 min et se réveille en ~1 min. |
| **Render — PostgreSQL Free** | **30 jours** | ⚠️ La base expire puis est supprimée après 14 jours de grâce. **Nous ne l'utilisons pas** : la base est sur Aiven. |
| Railway Free | 30 jours d'essai (5 $) puis 1 $/mois de crédit | Le crédit ne couvre pas une API 24/7. |
| Fly.io | 7 jours d'essai | Plus de plan gratuit depuis octobre 2024. |

Autrement dit : **le « 30 jours » que vous avez vu concerne uniquement le
PostgreSQL gratuit de Render**. Le déploiement décrit ici utilise MySQL sur
Aiven (ou MySQL local sur une VM Oracle) : aucune expiration.

## Option 1 — Oracle Cloud Always Free (recommandée, sans échéance)

Une VM ARM **2 OCPU / 12 Go**, 200 Go de disque, trafic 10 To/mois, MySQL
HeatWave 50 Go : tout est Always Free, sans date de fin.

### 1. Créer la VM

1. <https://cloud.oracle.com/free> → compte (carte bancaire pour vérifier
   l'identité, 0 € débité sur l'Always Free). Région d'accueil :
   **Johannesburg** (la plus proche de Madagascar).
2. **Compute → Instances → Create instance** :
   - image **Ubuntu 24.04**, architecture **aarch64** ;
   - shape **VM.Standard.A1.Flex**, 2 OCPU / 12 Go ;
   - disque 100–200 Go ; IP publique activée ; clé SSH.
3. **Show advanced options → Management → Cloud-init script** : collez
   [`cloud-init.yaml`](cloud-init.yaml) après avoir remplacé `main` par la
   branche à déployer (le fichier contient la variable `REF`).
4. Ouvrez les ports **22, 80, 443** dans la Security List du subnet.

### 2. Attendre l'installation

Le cloud-init installe Docker, Caddy et la stack, puis démarre l'API. Suivez
l'avancement :

```bash
ssh ubuntu@<IP_PUBLIQUE>
sudo tail -f /var/log/gestimmo-install.log
curl -s http://127.0.0.1/health
```

### 3. Activer HTTPS avec un domaine

```bash
sudo /opt/gestimmo/deploy/install.sh --domain api.example.com --email moi@example.com
```

Caddy obtient et renouvelle le certificat Let's Encrypt automatiquement.

## Option 2 — n'importe quel serveur Ubuntu/Debian

```bash
git clone https://github.com/j1234mic/gestimmo.git
cd gestimmo
sudo ./deploy/install.sh                 # HTTP sur http://<IP>/
# ou
sudo ./deploy/install.sh --domain api.example.com --email moi@example.com
```

Le script est idempotent : relancez-le pour mettre à jour (git pull + rebuild).

## Ce que le script installe

| Élément | Détail |
|---|---|
| Docker + Compose v2 | `docker compose -f backend/docker-compose.mysql.yml` |
| MySQL 8.4 | Volume `mysql_data`, écoute uniquement sur `127.0.0.1:3306` |
| API FastAPI | Écoute `127.0.0.1:8000`, jamais exposée directement |
| Caddy | Reverse proxy + HTTPS automatique sur 80/443 |
| `backend/.env` | `SECRET_KEY` et `SECURE_ID_KEY` générées une fois, stables |
| Sauvegarde cron | `mysqldump` chaque jour à 03:15 → volume `backups` |

Les fichiers utilisateurs (`uploads/`, `private_uploads/`) et les sauvegardes
sont dans des volumes Docker : ils survivent aux redémarrages et aux mises à
jour. Seul `docker compose down -v` les supprime.

## Intégration continue et déploiement automatique (optionnel)

Les workflows GitHub Actions sont fournis **hors** de `.github/workflows/` :

- `github-actions/ci.yml` — exécute les 136 tests à chaque push et pull request ;
- `github-actions/deploy.yml` — met à jour le serveur par SSH (cible `vps`) ou
  déclenche un Deploy Hook Render (cible `render`).

Raison : les outils de cet environnement n'ont pas la permission GitHub
`workflows`, qui est nécessaire pour créer un fichier dans `.github/workflows/`.
Pour les activer, ajoutez-les depuis l'interface GitHub (onglet **Actions →
New workflow**, ou **Add file → Create new file** avec le chemin
`.github/workflows/ci.yml` et le contenu du fichier), ou en local avec un jeton
possédant la portée `workflow` :

```bash
mkdir -p .github/workflows
cp deploy/github-actions/*.yml .github/workflows/
git add .github && git commit -m "Active la CI et le déploiement GitHub Actions" && git push
```

Secrets à créer dans **Settings → Secrets and variables → Actions** :

| Secret | Cible | Valeur |
|---|---|---|
| `DEPLOY_HOST` | vps | IP publique ou domaine du serveur |
| `DEPLOY_USER` | vps | `ubuntu` (Oracle) ou votre utilisateur |
| `DEPLOY_SSH_KEY` | vps | clé privée SSH (contenu complet) |
| `DEPLOY_DOMAIN` | vps | optionnel, `api.example.com` |
| `DEPLOY_EMAIL` | vps | optionnel, e-mail Let's Encrypt |
| `RENDER_DEPLOY_HOOK` | render | URL du Deploy Hook Render |

Le workflow de déploiement ne se lance que manuellement
(**Actions → Déploiement → Run workflow**), pour éviter de redémarrer la
production à chaque commit.

## Mises à jour

```bash
sudo /opt/gestimmo/deploy/install.sh --domain api.example.com --email moi@example.com
```

ou, sans SSH, via GitHub Actions : **Actions → Déploiement → Run workflow**
(cible `vps`). Secrets requis : `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`
et, en option, `DEPLOY_DOMAIN`, `DEPLOY_EMAIL`.

## Sauvegarde et restauration

```bash
# Déclencher une sauvegarde immédiate
cd /opt/gestimmo/backend
docker compose -f docker-compose.mysql.yml exec -T api python -c \
  "from app.database import SessionLocal; from app.services.admin_security_service import create_backup; \
   db=SessionLocal(); print(create_backup(db, 'admin', 'manual').filename); db.close()"

# Copier le dump hors du serveur
docker run --rm -v gestimmo_backups:/b -v "$PWD":/out alpine \
  cp /b/$(docker run --rm -v gestimmo_backups:/b alpine ls -t /b | head -1) /out/

# Restaurer (hors ligne, API arrêtée)
docker compose -f docker-compose.mysql.yml stop api
docker compose -f docker-compose.mysql.yml exec -T mysql \
  mysql -u immo_user -pimmo_password_2024 immo_db < sauvegarde.sql
docker compose -f docker-compose.mysql.yml start api
```

> Le nom des volumes dépend du répertoire du projet : `gestimmo_backups`,
> `gestimmo_mysql_data`, etc. Vérifiez avec `docker volume ls`.

## Désinstaller

```bash
cd /opt/gestimmo/backend
docker compose -f docker-compose.mysql.yml down          # garde les données
docker compose -f docker-compose.mysql.yml down -v       # supprime les volumes
```

## Dépannage

| Symptôme | Vérifier |
|---|---|
| `install.sh` s'arrête sur Docker Compose | `docker compose version` ; sinon `apt-get install docker-compose-v2` |
| `/health` ne répond pas | `docker compose -f backend/docker-compose.mysql.yml logs --tail=100 api` |
| Le certificat HTTPS échoue | DNS du domaine pointe-t-il bien vers l'IP ? ports 80/443 ouverts ? |
| `Out of capacity` chez Oracle | Changer de domaine de disponibilité, ou créer 1 OCPU puis redimensionner |
| Sauvegarde en échec | `cat /var/log/gestimmo-backup.log` ; `mysqldump` est dans l'image |
