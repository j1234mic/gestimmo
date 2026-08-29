#!/usr/bin/env bash
set -e

# GestImmo — Démarrage dev full-stack
# API base: (proxy relatif → /api)
# Proxy target: http://localhost:8000
# Astuce: laissez VITE_API_URL vide en dev pour utiliser le proxy Vite (évite CORS).
# Backend attendu sur :8000 — vérifiez `docker compose up -d postgres` puis `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`

ROOT=$(cd "$(dirname "$0")" && pwd)
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

echo "== GestImmo Dev Stack =="
echo "API base: /api (proxy relatif) → http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo "Backend:  http://localhost:8000/docs"
echo ""

# 1) Postgres
if command -v docker >/dev/null 2>&1; then
  echo "[1/3] Démarrage postgres via docker compose..."
  cd "$BACKEND"
  docker compose up -d postgres || echo "⚠️  docker compose postgres échoué, fallback SQLite"
  cd "$ROOT"
else
  echo "[1/3] Docker non trouvé → utilisation SQLite (test.db) pour le sandbox"
fi

# 2) Backend env
echo "[2/3] Préparation backend/.env..."
cd "$BACKEND"
if [ ! -f .env ]; then
  python3 scripts/init_env.py --db-host localhost || python scripts/init_env.py --db-host localhost
fi
echo "DATABASE_URL=$(grep DATABASE_URL .env || echo 'non défini')"

# 3) Backend
echo "[3/3] Lancement backend :8000..."
if [ -f "$BACKEND/.env" ]; then
  echo "Utilisation de $BACKEND/.env"
fi
# Vérifie si le backend tourne déjà
if curl -s http://localhost:8000/health | grep -q healthy; then
  echo "✅ Backend déjà en cours sur :8000"
else
  echo "Démarrage uvicorn..."
  # En arrière-plan si tmux/screen non dispo, on lance via nohup
  if command -v uvicorn >/dev/null 2>&1; then
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
  elif [ -f "$HOME/.local/bin/uvicorn" ]; then
    $HOME/.local/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
  else
    python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload &
  fi
  echo "Attente backend..."
  for i in {1..15}; do
    if curl -s http://localhost:8000/health | grep -q healthy; then
      echo "✅ Backend OK"
      break
    fi
    sleep 1
  done
fi

# 4) Frontend
echo ""
echo "== Frontend =="
cd "$FRONTEND"
if [ ! -d node_modules ]; then
  echo "Installation dépendances..."
  npm install
fi
echo "VITE_API_URL vide → proxy /api → http://localhost:8000 (évite CORS)"
echo "Lancement Vite dev server..."
npm run dev
