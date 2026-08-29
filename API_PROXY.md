# GestImmo — Configuration API & Proxy

## Enoncé

```
API base: (proxy relatif → /api)
Proxy target: http://localhost:8000
Astuce: laissez VITE_API_URL vide en dev pour utiliser le proxy Vite (évite CORS).
Backend attendu sur :8000 — vérifiez `docker compose up -d postgres` puis `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
```

## Implémentation réalisée

### 1. Frontend Vite (frontend/vite.config.js)

```js
server: {
  host: '0.0.0.0',
  port: 5173,
  allowedHosts: true, // e2b preview https://5173-xxx.e2b.app
  proxy: {
    '/api': {
      target: 'http://localhost:8000', // Proxy target
      changeOrigin: true,
      secure: false,
    },
    '/uploads': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    }
  }
}
```

### 2. Client API (frontend/src/api/client.ts)

```ts
function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_URL?.trim()
  if (!envUrl) return '/api' // proxy relatif en dev → évite CORS
  return envUrl.replace(/\/+$/, '')
}
export const API_BASE_URL = getApiBaseUrl() // '/api' en dev, absolue en prod
```

### 3. Env (frontend/.env.example)

```
# Dev: vide = proxy relatif
VITE_API_URL=
# Prod: absolue
# VITE_API_URL=https://api.gestimmo.example.com
VITE_PROXY_TARGET=http://localhost:8000
```

### 4. Backend (backend/)

- `docker-compose.yml` : service `postgres` (port 5432) + `api` (8000)
- `scripts/init_env.py` : génère SECRET_KEY / SECURE_ID_KEY stables
- `app/config.py` : normalise DATABASE_URL `postgres` → `localhost` hors Docker
- Fallback SQLite `sqlite:///./test.db` pour sandbox sans Docker

### 5. Vérification

```bash
# Backend
cd backend
docker compose up -d postgres
python scripts/init_env.py --db-host localhost
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
curl http://localhost:8000/health # → {"status":"healthy"}
curl http://localhost:8000/docs   # Swagger

# Frontend
cd frontend
npm install
npm run dev
# → http://localhost:5173
# Proxy test:
curl http://localhost:5173/api/auth/login -X POST -d '{"email":"admin@immogest.com","password":"Admin@2024!"}' -H "Content-Type: application/json"
# → même réponse que :8000/api/auth/login
```

### 6. Pourquoi proxy relatif ?

- En dev, le navigateur appelle `/api/...` sur le même origin (5173) → Vite proxyfie côté serveur Node vers 8000 → pas de CORS, pas de preflight, cookies OK.
- En prod, `VITE_API_URL` absolue ou reverse proxy Nginx `/api → :8000`.
- Astuce : laisser `VITE_API_URL` vide évite de hardcoder `http://localhost:8000` dans le code frontend, ce qui casserait en prod et forcerait CORS.

### 7. Stack

- Backend: FastAPI, 670 routes, 209 modèles, 95 tests, PostgreSQL / SQLite fallback
- Frontend: Vite 8 + React 18 + TS + Tailwind + Zustand + Axios + Recharts
- Proxy: /api → :8000, /uploads → :8000
- Auth: JWT + refresh rotation + 2FA
