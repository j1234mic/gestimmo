#!/usr/bin/env bash
# Vérifie qu'un déploiement GestImmo répond correctement.
#
# Exemples :
#   ./deploy/smoke-test.sh                                  # http://127.0.0.1
#   ./deploy/smoke-test.sh --url https://api.example.com
#   ./deploy/smoke-test.sh --url https://api.example.com \
#       --email admin@immogest.com --password 'MotDePasseFort!2026'
#
# Codes de sortie : 0 si tout est vert, 1 sinon.
set -euo pipefail

URL="${GESTIMMO_URL:-http://127.0.0.1}"
EMAIL=""
PASSWORD=""
TIMEOUT=120

if [[ -t 1 ]]; then
  C_GREEN=$'\033[1;32m'; C_RED=$'\033[1;31m'; C_OFF=$'\033[0m'
else
  C_GREEN=""; C_RED=""; C_OFF=""
fi

ok()   { printf '%s✓%s %s\n' "$C_GREEN" "$C_OFF" "$*"; }
fail() { printf '%s✗%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; FAILED=1; }
FAILED=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url) URL="${2:?--url attend une valeur}"; shift 2 ;;
    --email) EMAIL="${2:?}"; shift 2 ;;
    --password) PASSWORD="${2:?}"; shift 2 ;;
    --timeout) TIMEOUT="${2:?}"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "Option inconnue : $1" >&2; exit 2 ;;
  esac
done

URL="${URL%/}"
command -v curl >/dev/null 2>&1 || { echo "curl est requis." >&2; exit 2; }

# 1. Le conteneur vient peut-être de démarrer (réveil Render, création des tables).
printf 'Attente de %s/health (max %ss)…\n' "$URL" "$TIMEOUT"
deadline=$((SECONDS + TIMEOUT))
health=""
while [[ $SECONDS -lt $deadline ]]; do
  if health="$(curl -fsS --max-time 5 "$URL/health" 2>/dev/null)"; then
    break
  fi
  sleep 3
  health=""
done

if [[ -n "$health" ]] && grep -q '"healthy"' <<<"$health"; then
  ok "GET /health → $health"
else
  fail "GET /health ne répond pas (dernier essai : ${health:-aucune réponse})"
fi

# 2. Documentation OpenAPI
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$URL/docs" || true)"
if [[ "$code" == "200" ]]; then
  ok "GET /docs → 200"
else
  fail "GET /docs → $code"
fi

schema="$(curl -s --max-time 30 "$URL/openapi.json" || true)"
count="$(grep -o '"/api/[^"]*"' <<<"$schema" | sort -u | wc -l | tr -d ' ')"
if [[ "${count:-0}" -gt 50 ]]; then
  ok "OpenAPI : $count chemins /api exposés"
else
  fail "OpenAPI : seulement ${count:-0} chemins /api (attendu > 50)"
fi

# 3. Authentification (optionnelle : nécessite un compte valide)
if [[ -n "$EMAIL" && -n "$PASSWORD" ]]; then
  login="$(curl -s --max-time 20 -X POST "$URL/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" || true)"
  if grep -q '"access_token"' <<<"$login"; then
    ok "POST /api/auth/login → jeton obtenu pour $EMAIL"
  else
    fail "POST /api/auth/login a échoué : $(head -c 200 <<<"$login")"
  fi
else
  printf '… Authentification non testée (ajoutez --email et --password)\n'
fi

if [[ $FAILED -eq 0 ]]; then
  printf '\n%sDéploiement opérationnel :%s %s\n' "$C_GREEN" "$C_OFF" "$URL"
  exit 0
fi
printf '\n%sAu moins une vérification a échoué.%s\n' "$C_RED" "$C_OFF" >&2
exit 1
