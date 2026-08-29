# GestImmo Frontend — Vite + React + TypeScript

Frontend pour l'API GestImmo (31 modules).

## API base: (proxy relatif → /api)

- **En développement**: `VITE_API_URL` vide → le frontend utilise `/api` relatif
- **Proxy Vite**: `/api` → `http://localhost:8000` (évite CORS)
- **Uploads**: `/uploads` → `http://localhost:8000/uploads`

```ts
// vite.config.ts
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
    '/uploads': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    }
  }
}
```

```ts
// src/api/client.ts
function getApiBaseUrl() {
  const envUrl = import.meta.env.VITE_API_URL?.trim()
  if (!envUrl) return '/api' // proxy relatif en dev
  return envUrl.replace(/\/+$/, '')
}
export const API_BASE_URL = getApiBaseUrl()
```

### Astuce: laissez VITE_API_URL vide en dev pour utiliser le proxy Vite (évite CORS)

Dans `.env`:
```
VITE_API_URL=
```

En production:
```
VITE_API_URL=https://api.gestimmo.example.com
```

## Backend attendu sur :8000

Vérifiez:

```bash
cd backend
# 1) Base de données
docker compose up -d postgres
# ou si Docker indisponible, fallback SQLite:
# DATABASE_URL=sqlite:///./test.db dans backend/.env

# 2) Env
python scripts/init_env.py --db-host localhost
# ou --db-host postgres si vous lancez via docker compose

# 3) API
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# Docs: http://localhost:8000/docs
```

## Frontend dev

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
# Les appels /api sont proxifiés vers :8000
```

## Build

```bash
npm run build
npm run preview
```

## Stack

- Vite 5 + React 18 + TypeScript
- React Router 6
- Zustand (auth)
- Axios (client avec refresh token)
- Tailwind CSS 3
- Recharts (dashboard)
- Lucide (icons)

## Modules couverts

- Dashboard (KPIs temps réel)
- Biens (Module 1) — 12 types, 6 statuts, galerie, 360°
- Propriétaires (Module 2)
- Locataires (Module 3)
- Baux (Module 4)
- Finance (Module 5)
- Maintenance (Module 6)
- Copro (Module 7)
- CRM (Module 8)
- Reporting (Module 9)
- Communication (Module 10)
- GED (Module 11)
- Admin & Sécurité (Module 12)
- Géoloc / Carte (Module 13)
- Extension 18-31 (courte durée, fiscalité, VEFA, SCPI, etc.)
