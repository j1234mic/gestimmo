# Configuration Proxy API — GestImmo

## Résumé (demandé)

```
API base: (proxy relatif → /api)
Proxy target: http://localhost:8000
Astuce: laissez VITE_API_URL vide en dev pour utiliser le proxy Vite (évite CORS).
Backend attendu sur :8000 — vérifiez `docker compose up -d postgres` puis `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
```

## Implémentation

### vite.config.js

```js
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      allowedHosts: true, // nécessaire pour le preview e2b https://{port}-{id}.e2b.app
      proxy: {
        '/api': {
          target: proxyTarget, // → http://localhost:8000
          changeOrigin: true,
          secure: false,
        },
        '/uploads': {
          target: proxyTarget,
          changeOrigin: true,
          secure: false,
        }
      }
    }
  }
})
```

### .env (dev)

```
# Laissez vide pour utiliser le proxy relatif /api → :8000 (évite CORS)
VITE_API_URL=
VITE_PROXY_TARGET=http://localhost:8000
```

### .env (prod)

```
VITE_API_URL=https://api.gestimmo.example.com
```

### Client API (src/api/client.ts)

```ts
function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_URL?.trim()
  if (!envUrl) return '/api' // proxy relatif en dev
  return envUrl.replace(/\/+$/, '')
}

export const API_BASE_URL = getApiBaseUrl()

export const apiClient = axios.create({
  baseURL: API_BASE_URL, // /api en dev → Vite proxy → :8000
})
```

## Pourquoi proxy relatif ?

- Évite CORS en développement : le navigateur appelle `/api/auth/login` sur le même origin (5173), Vite proxyfie vers 8000 côté serveur Node, pas de preflight CORS.
- En prod, `VITE_API_URL` absolue pointe directement vers l'API (ou via reverse proxy Nginx).
- `/uploads` aussi proxyfié pour les images/documents.

## Vérification backend

```bash
cd backend

# 1) Postgres via Docker (recommandé)
docker compose up -d postgres
# → publie localhost:5432, DB immo_db, user immo_user / immo_password_2024

# 2) Env
python scripts/init_env.py --db-host localhost
# Si vous lancez tout dans Docker: --db-host postgres

# 3) API
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# ou
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Health
curl http://localhost:8000/health
# Docs
open http://localhost:8000/docs
```

Fallback sans Docker (sandbox) :

```bash
# backend/.env
DATABASE_URL=sqlite:///./test.db
```

## Vérification frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
# Test proxy:
curl http://localhost:5173/api/auth/login -X POST -H "Content-Type: application/json" -d '{"email":"admin@immogest.com","password":"Admin@2024!"}'
# Doit retourner access_token (même chose que http://localhost:8000/api/auth/login)
```

## Comptes de test (bootstrap)

- admin@immogest.com / Admin@2024! (super_admin)
- gestionnaire@immogest.com / Manager@2024! (manager)
- lecteur@immogest.com / Viewer@2024! (viewer)
