# Déployer GestImmo gratuitement — Render + Aiven MySQL, pas à pas

Objectif : une API publique en ligne en **20 à 30 minutes**, avec une base
MySQL, **sans carte bancaire**. C'est la procédure la plus simple ; pour un
service toujours allumé avec disque persistant, voir l'option Oracle dans
[`DEPLOIEMENT-GRATUIT.md`](DEPLOIEMENT-GRATUIT.md#4-option-a--oracle-cloud-always-free-recommandé).

> Ce que vous obtenez : `https://<service>.onrender.com/docs`, une base MySQL
> Aiven de 1 Go, et 0 € de facture. En contrepartie : l'API s'endort après
> 15 minutes sans trafic, redémarre en ~1 minute, et **les fichiers uploadés
> sont perdus** à chaque redéploiement (disque éphémère).
>
> **Aucune limite de 30 jours** : le service web Render gratuit n'expire pas,
> et Aiven MySQL Free est gratuit sans échéance. Seul le **PostgreSQL** gratuit
> de Render expire à 30 jours — il n'est pas utilisé ici. Tableau complet des
> durées : [`../deploy/README.md`](../deploy/README.md).

### Le résumé en 5 étapes

1. **Aiven** → créer un MySQL plan **Free** → copier l'URI (`…:12345/defaultdb?ssl-mode=REQUIRED`).
2. Générer une clé : `python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"`.
3. **Render** → *New → Blueprint* → dépôt `j1234mic/gestimmo` → branche
   `arena/76e8e2ba-gestimmo` (ou `main` après fusion de la PR).
4. Renseigner `DATABASE_URL`, `SECURE_ID_KEY`, `ALLOWED_ORIGINS`, `PUBLIC_BASE_URL`.
5. Attendre le build (~10 min) puis ouvrir `https://<service>.onrender.com/health`.

---

## 0. Avant de commencer

Il faut :

- un compte **GitHub** (le dépôt `j1234mic/gestimmo`) ;
- un compte **Render** (inscription avec GitHub, sans carte) ;
- un compte **Aiven** (inscription e-mail/GitHub/Google, sans carte) ;
- Python 3 en local **uniquement** pour générer une clé (ou utilisez le
  `python` de votre choix).

Le code compatible MySQL est sur la branche
`arena/76e8e2ba-gestimmo`, déjà poussée sur GitHub, et une pull request vers
`main` est ouverte. Deux choix :

- **le plus simple** : fusionner la pull request, puis déployer `main` ;
- ou, dans Render, sélectionner directement la branche
  `arena/76e8e2ba-gestimmo` lors de la création du Blueprint.

> ⚠️ Render ne lit `render.yaml` que sur la branche sélectionnée. Si le
> Blueprint répond « render.yaml not found », c'est que la branche choisie ne
> contient pas encore ce fichier.

---

## 1. Créer la base MySQL sur Aiven (5 min)

1. Allez sur <https://aiven.io> → **Sign up** → **MySQL** → **Create service**.
2. Choisissez le plan **Free** (1 Go de stockage, 1 Go de RAM, 1 CPU).
   - Aucune carte bancaire n'est demandée.
   - Le plan gratuit ne permet pas de choisir la région ; Aiven l'attribue.
3. Cliquez **Create service** et attendez le statut **Running** (2 à 5 min).
4. Onglet **Overview** → copiez la **Service URI**. Elle ressemble à :

```
mysql://avnadmin:MOTDEPASSE@mysql-xxxx.aivencloud.com:12345/defaultdb?ssl-mode=REQUIRED
```

5. Vous pouvez garder la base `defaultdb` (le plus rapide) ou créer une base
   dédiée dans l'onglet **Databases** → **Create database** (`immo_db`).
6. Transformez l'URI pour SQLAlchemy : remplacez seulement `mysql://` par
   `mysql+pymysql://`, en conservant le port et `ssl-mode=REQUIRED` :

```
mysql+pymysql://avnadmin:MOTDEPASSE@mysql-xxxx.aivencloud.com:12345/defaultdb?ssl-mode=REQUIRED
```

C'est la valeur de `DATABASE_URL` pour Render. Gardez-la de côté.

> Le service Aiven gratuit peut être **mis hors tension après une période
> d'inactivité**. Dans ce cas, l'API ne peut plus se connecter : rallumez-le
> depuis la console Aiven (bouton **Power on**).

---

## 2. Générer `SECURE_ID_KEY` (30 s)

Cette clé chiffre les identifiants publics (`secure_id`). Elle doit rester
**stable** : si elle change, les `secure_id` déjà en base deviennent illisibles.

```bash
python3 -c "import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Copiez la chaîne de 44 caractères affichée. Conservez-la (gestionnaire de
mots de passe) : vous en aurez besoin pour toute recréation du service.

---

## 3. Déployer sur Render (5 min + build)

1. Connectez-vous à <https://dashboard.render.com> avec GitHub.
2. **New → Blueprint**.
3. Sélectionnez le dépôt `j1234mic/gestimmo`, puis la branche
   **`arena/76e8e2ba-gestimmo`**.
   Render lit automatiquement `render.yaml` à la racine.
4. Render affiche le service `gestimmo-api` et demande les variables marquées
   `sync: false` :

| Variable | Valeur à saisir |
|---|---|
| `DATABASE_URL` | l'URL Aiven de l'étape 1 (`mysql+pymysql://…?ssl-mode=REQUIRED`) |
| `SECURE_ID_KEY` | la clé de 44 caractères de l'étape 2 |
| `ALLOWED_ORIGINS` | `*` pour un test, ou l'URL de votre frontend (`https://mon-front.vercel.app`) |
| `PUBLIC_BASE_URL` | `https://<nom-du-service>.onrender.com` (l'URL exacte affichée par Render) |

`SECRET_KEY` est généré automatiquement par Render, `DEBUG=false` et
`ENVIRONMENT=production` sont déjà positionnés.

5. Cliquez **Apply** / **Create**. Le build Docker prend 5 à 10 minutes
   (tesseract + PyMuPDF + reportlab).
6. Suivez les **Logs**. Au premier démarrage, l'API crée les **248 tables**
   et **778 index** : sur une base Aiven distante et 0,1 CPU, comptez
   plusieurs minutes. Attendez la ligne `🚀 API démarrée !`.
   - Si le déploiement échoue avant (health check trop impatient), créez les
     tables **depuis votre machine** (commande au § 6), positionnez
     `AUTO_CREATE_TABLES=false` dans Render, puis redéployez. C'est la
     méthode la plus fiable pour une base distante.
7. Ouvrez :

```
https://<nom-du-service>.onrender.com/health   → {"status":"healthy"}
https://<nom-du-service>.onrender.com/docs     → documentation interactive
```

> Le premier appel après 15 minutes d'inactivité prend ~1 minute : le temps
> que Render réveille le conteneur. C'est normal.

---

## 4. Se connecter et sécuriser immédiatement

Le démarrage crée des comptes historiques de démonstration :

| E-mail | Mot de passe |
|---|---|
| `admin@immogest.com` | `Admin@2024!` |
| `gestionnaire@immogest.com` | `Manager@2024!` |
| `lecteur@immogest.com` | `Viewer@2024!` |

**Changez le mot de passe administrateur tout de suite** — l'URL est publique.

```bash
export API="https://<nom-du-service>.onrender.com"

# 1) Jeton d'administration
TOKEN=$(curl -s -X POST "$API/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@immogest.com","password":"Admin@2024!"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

# 2) Identifiant du compte admin (1 sur une base neuve)
ADMIN_ID=$(curl -s "$API/api/admin/users?q=admin@immogest.com" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['data'][0]['id'])")

# 3) Nouveau mot de passe (10 caractères min., majuscule, minuscule, chiffre, spécial)
curl -s -X PUT "$API/api/admin/users/$ADMIN_ID/password" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"current_password":"Admin@2024!","new_password":"MotDePasseFort!2026"}'
```

Réponse attendue : `{"changed":true}`. Créez ensuite vos propres comptes via
`POST /api/admin/users`, puis **désactivez** les comptes de démonstration
(`POST /api/admin/users/{id}/deactivate`, avec `{"reason":"compte de démo"}`).

---

## 5. Vérifier que la base est bien créée

```bash
mysql --ssl-mode=REQUIRED \
  -h mysql-xxxx.aivencloud.com -P 12345 -u avnadmin -p \
  -e "USE defaultdb; SHOW TABLES;" | head -20
```

Vous devez voir `admin_users`, `properties`, `owners`, `tenants`, etc.
Si l'API répond mais que la base est vide, c'est que `DATABASE_URL` pointe vers
une autre base (vérifiez le nom après le `/`).

---

## 6. Dépannage

| Symptôme | Cause probable | Solution |
|---|---|---|
| Build OK, puis `Connexion impossible à la base` | Aiven hors tension, mauvais port, `ssl-mode` absent | Rallumez Aiven ; vérifiez l'URI complète et gardez `?ssl-mode=REQUIRED` |
| `Access denied for user` | Mot de passe ou base incorrects | Recopiez l'URI depuis Aiven ; gardez `defaultdb` ou créez `immo_db` |
| Déploiement bloqué / health check en échec | Création des 248 tables trop lente sur 0,1 CPU | Passez `AUTO_CREATE_TABLES=false` dans Render, créez les tables depuis votre machine (ci-dessous), puis redéployez |
| 502/503 au premier appel | Conteneur en veille | Attendez 60 s et rechargez |
| Les photos/documents disparaissent | Disque éphémère Render | Comportement normal du plan gratuit ; passez à Oracle pour un disque persistant |
| `Out of memory` / 502 sur un gros PDF | 512 Mo de RAM | Limitez la taille des fichiers ou passez à Oracle (12 Go) |
| Le service Aiven affiche « Powered off » | Inactivité | **Power on** dans la console Aiven |

Créer les tables depuis votre machine (méthode recommandée pour une base
distante : évite un health check Render trop long) :

```bash
cd backend
export DATABASE_URL='mysql+pymysql://avnadmin:…@…:12345/defaultdb?ssl-mode=REQUIRED'
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -c "from app.database import init_db; init_db()"
```

Puis, dans Render → **Environment** : `AUTO_CREATE_TABLES=false`, et
redéployez.

---

## 7. Quand quitter ce plan gratuit

Render + Aiven convient pour une démo, un prototype ou un test client. Dès
qu'il faut :

- un service **toujours allumé** (pas de réveil de 1 min) ;
- **conserver les uploads** et les sauvegardes ;
- traiter des PDF/OCR sans risque d'OOM ;
- plus de 5 Go de trafic par mois ;

passez à **Oracle Cloud Always Free** (VM ARM 2 OCPU/12 Go, 200 Go de disque,
MySQL HeatWave 50 Go). La procédure complète est dans
[`DEPLOIEMENT-GRATUIT.md`](DEPLOIEMENT-GRATUIT.md#4-option-a--oracle-cloud-always-free-recommandé).
