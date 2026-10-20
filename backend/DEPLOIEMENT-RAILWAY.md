# Déployer GestImmo sur Railway

## Coût et accès

Railway n'est pas une garantie d'hébergement gratuit permanent. Vérifiez les
conditions actuelles sur https://railway.com/pricing et les crédits disponibles
dans votre compte. API, base de données, stockage et trafic peuvent consommer
ces crédits. Configurez les contrôles de dépenses disponibles avant de lancer
les services ; une alerte seule ne constitue pas un plafond bloquant.

Ce guide prépare le déploiement, il ne signifie pas qu'un service a été créé.
Ne partagez aucun jeton Railway, mot de passe de base ou clé dans Git/chat.

## 1. Service API depuis GitHub

1. Rendez la branche qui contient les changements disponible sur GitHub,
   puis créez un projet Railway avec **Deploy from GitHub repo**, dépôt
   `j1234mic/gestimmo`.
2. Choisissez cette branche (ou `main` après intégration des changements).
3. Dans les paramètres du service, définissez **Root Directory** à `/backend`.
   Le contexte Docker doit être `backend`, et non la racine du dépôt.
4. Si Railway demande explicitement le chemin du fichier de configuration,
   indiquez `/backend/railway.json` (chemin depuis la racine du dépôt).
   Vérifiez que le plan détecté utilise `Dockerfile` et `/health`.

Le Dockerfile démarre Uvicorn sur `0.0.0.0` et utilise le `PORT` injecté par
Railway. Ne remplacez pas sa commande de démarrage.

## 2. Base et variables

Ajoutez un service PostgreSQL au projet (il consomme lui aussi des ressources).
Dans les variables du service **API**, ajoutez une référence à son
`DATABASE_URL` interne via le sélecteur de références Railway, sous le nom
`DATABASE_URL` (par exemple `${{Postgres.DATABASE_URL}}`, en remplaçant
`Postgres` par le nom exact du service). Ne recopiez pas une URL publique
inutilement.

N'utilisez pas `localhost` ni `postgres` comme hôte dans Railway : `localhost`
renvoie vers le conteneur API lui-même, et `postgres` est uniquement l'alias du
service dans le réseau Docker Compose local. Utilisez la référence Railway
fournie par la base. Une base PostgreSQL/MySQL externe est aussi possible si
elle est accessible et si ses paramètres TLS sont respectés.

Configurez également :

| Variable | Valeur |
|---|---|
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `LOG_LEVEL` | `INFO` |
| `AUTO_CREATE_TABLES` | `true` pour une base neuve |
| `SECRET_KEY` | secret aléatoire stable, généré ci-dessous |
| `SECURE_ID_KEY` | clé Fernet stable, générée ci-dessous |
| `ALLOWED_ORIGINS` | URL HTTPS réelle du frontend, sans `/` final ; pas `*` |
| `PAYMENT_SIMULATION_ENABLED` | `false` |
| `PUBLIC_BASE_URL` | URL HTTPS publique de l'API après génération du domaine |

Générez localement les secrets avec Python et les dépendances installées :

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Collez les sorties uniquement dans les variables privées Railway. Conservez
ces clés entre redéploiements : changer `SECURE_ID_KEY` rend les identifiants
chiffrés existants illisibles. Aucune clé n'est générée dans le dépôt.

## 3. Fichiers persistants

Sans volume, les uploads et sauvegardes disparaissent lors du remplacement du
conteneur. Pour les conserver, montez un volume Railway sur `/data` et ajoutez :

```text
UPLOAD_DIR=/data/uploads
PRIVATE_UPLOAD_DIR=/data/private_uploads
BACKUP_DIR=/data/backups
```

Le volume peut entraîner un coût. Gardez une sauvegarde externe de la base et
des fichiers ; un volume n'est pas une sauvegarde. Ne stockez pas de documents
réels si vous choisissez volontairement le disque éphémère pour une démo.

## 4. Déployer et vérifier

Lancez le déploiement après configuration. Le premier démarrage crée les tables
manquantes ; le healthcheck attend jusqu'à 300 secondes. Ce mécanisme n'est pas
un outil de migration pour modifier des tables existantes.

Dans **Networking**, générez un domaine public pour le service API. Vérifiez :

```bash
curl --fail https://VOTRE-DOMAINE/health
# attendu : {"status":"healthy"}
```

Ouvrez `https://VOTRE-DOMAINE/docs` pour Swagger. Le dépôt contient une API,
pas une interface web de gestion. `/health` confirme que le processus répond,
mais ne teste pas la base : vérifiez aussi un parcours métier depuis Swagger.
Consultez les logs si le déploiement échoue, et la consommation après démarrage.

### Dépannage : `localhost:5432` refusé ou hôte `postgres` remappé

Ce message signifie que l'API n'utilise pas l'adresse de la base Railway. Dans
les variables du service API, créez ou corrigez `DATABASE_URL` avec une
référence au service PostgreSQL du même projet, puis redéployez l'API. N'utilisez
pas l'URL locale de `docker-compose` (`...@postgres:5432/...`) ni
`...@localhost:5432/...`. Si le message de remappage apparaît encore après le
redéploiement, vérifiez que Railway déploie bien le commit contenant la
correction et que la référence `DATABASE_URL` est définie sur le service API.

Si le budget doit impérativement rester à zéro, n'activez aucun service sans
avoir confirmé les conditions de votre compte. Les autres pistes du dépôt
sont décrites dans `DEPLOIEMENT-GRATUIT.md` ; leurs offres sont également à
revérifier auprès des fournisseurs.
