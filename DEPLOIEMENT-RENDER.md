# Déployer GestImmo sur Render

Le fichier [`render.yaml`](render.yaml) décrit une API Docker, une base PostgreSQL et un disque persistant pour les uploads privés/publics et les sauvegardes. **Ces ressources sont payantes** (le disque persistant n'est pas disponible sur l'offre gratuite).

1. Poussez la branche contenant `render.yaml` sur GitHub.
2. Dans [Render Dashboard](https://dashboard.render.com/), choisissez **New → Blueprint**, connectez le dépôt `j1234mic/gestimmo` et sélectionnez la branche contenant ce fichier. Vérifiez les coûts avant confirmation.
3. Saisissez `SECURE_ID_KEY` : générez-la avec `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Conservez-la : la modifier rend les identifiants chiffrés existants illisibles.
4. Saisissez `ALLOWED_ORIGINS` : origine(s) exacte(s) des interfaces clientes, séparées par des virgules. S'il n'y a pas encore d'interface web, utilisez l'URL de l'API Render (`https://gestimmo-api.onrender.com`, à adapter selon l'URL attribuée). Ne configurez pas `*` pour des requêtes avec credentials.
5. Après déploiement, vérifiez `https://<votre-service>.onrender.com/health` et `/docs`. La base est créée au premier démarrage (`AUTO_CREATE_TABLES=true`). Ajoutez les variables facultatives (Stripe, SMTP, etc.) dans le dashboard selon les fonctionnalités utilisées ; ne les commitez pas.

**Attention :** `backend/.env` est actuellement suivi par Git. Vérifiez son contenu, révoquez toute clé réelle qui aurait été publiée et ne réutilisez aucune de ses valeurs en production. Les disques Render ne sont pas partagés entre plusieurs instances ; maintenez une seule instance de l'API ou migrez les fichiers vers un stockage objet. Prévoyez également des sauvegardes externes de PostgreSQL et du disque.
