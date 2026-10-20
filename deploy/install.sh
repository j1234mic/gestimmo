#!/usr/bin/env bash
# Déploiement automatisé de GestImmo sur un serveur Ubuntu/Debian.
#
# Cible principale : une VM Oracle Cloud « Always Free » (aucune limite de
# durée), mais le script fonctionne sur n'importe quel VPS Ubuntu 22.04/24.04
# ou Debian 12, ainsi que sur une machine locale.
#
# Ce qu'il fait, de façon idempotente (relançable sans tout casser) :
#   1. installe Docker, le plugin Compose et Caddy ;
#   2. clone (ou met à jour) le dépôt dans /opt/gestimmo ;
#   3. génère backend/.env avec SECRET_KEY et SECURE_ID_KEY stables ;
#   4. limite MySQL et l'API à 127.0.0.1 (seul Caddy est exposé) ;
#   5. démarre API + MySQL 8.4 via docker compose ;
#   6. configure HTTPS automatique (Let's Encrypt) si un domaine est fourni ;
#   7. attend que /health réponde ;
#   8. programme une sauvegarde mysqldump quotidienne.
#
# Exemples :
#   sudo ./deploy/install.sh --domain api.example.com --email moi@example.com
#   sudo ./deploy/install.sh                      # sans domaine : http://<IP>/
#   sudo ./deploy/install.sh --dry-run            # affiche les actions
#
# Variables d'environnement équivalentes : GESTIMMO_DOMAIN, GESTIMMO_EMAIL,
# GESTIMMO_REPO, GESTIMMO_REF, GESTIMMO_DIR.
set -euo pipefail

REPO_URL="${GESTIMMO_REPO:-https://github.com/j1234mic/gestimmo.git}"
REF="${GESTIMMO_REF:-main}"
APP_DIR="${GESTIMMO_DIR:-/opt/gestimmo}"
DOMAIN="${GESTIMMO_DOMAIN:-}"
EMAIL="${GESTIMMO_EMAIL:-}"
DRY_RUN=0

if [[ -t 1 ]]; then
  C_BLUE=$'\033[1;34m'; C_YELLOW=$'\033[1;33m'; C_RED=$'\033[1;31m'; C_OFF=$'\033[0m'
else
  C_BLUE=""; C_YELLOW=""; C_RED=""; C_OFF=""
fi

log()  { printf '%s==>%s %s\n' "$C_BLUE" "$C_OFF" "$*"; }
warn() { printf '%s!!%s %s\n' "$C_YELLOW" "$C_OFF" "$*" >&2; }
die()  { printf '%sxx%s %s\n' "$C_RED" "$C_OFF" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Déploie l'API GestImmo (Docker + MySQL 8.4) sur Ubuntu/Debian.

Options :
  --domain DOMAINE   nom de domaine servant l'API (HTTPS automatique via Caddy)
  --email EMAIL      e-mail ACME pour Let's Encrypt (recommandé avec --domain)
  --repo URL         dépôt Git à déployer (défaut : j1234mic/gestimmo)
  --ref REF          branche ou tag à déployer (défaut : main)
  --dir CHEMIN       répertoire d'installation (défaut : /opt/gestimmo)
  --dry-run          affiche les commandes sans rien modifier
  -h, --help         affiche cette aide

Sans --domain, l'API est servie en HTTP sur le port 80 de la machine.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="${2:?--domain attend une valeur}"; shift 2 ;;
    --email)  EMAIL="${2:?--email attend une valeur}"; shift 2 ;;
    --repo)   REPO_URL="${2:?--repo attend une valeur}"; shift 2 ;;
    --ref)    REF="${2:?--ref attend une valeur}"; shift 2 ;;
    --dir)    APP_DIR="${2:?--dir attend une valeur}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Option inconnue : $1 (voir --help)" ;;
  esac
done

# ------------------------------------------------------------------ utilitaires
run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '   [dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

as_root() {
  if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi
}

require_root() {
  [[ $EUID -eq 0 ]] && return 0
  command -v sudo >/dev/null 2>&1 || die "Ce script doit être lancé en root (ou installer sudo)."
  log "Élévation des privilèges via sudo…"
  exec sudo -E bash "$0" "$@"
}

# set_env CLÉ VALEUR FICHIER — remplace la ligne CLÉ=… ou l'ajoute.
set_env() {
  local key="$1" value="$2" file="$3" tmp
  [[ -f "$file" ]] || : > "$file"
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { done = 0 }
    index($0, k "=") == 1 { print k "=" v; done = 1; next }
    { print }
    END { if (!done) print k "=" v }
  ' "$file" > "$tmp"
  mv "$tmp" "$file"
  chmod 600 "$file"
}

env_value() {
  local key="$1" file="$2"
  grep -E "^${key}=" "$file" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

gen_secret() {
  # 64 caractères urlsafe, sans dépendance à python.
  openssl rand -base64 48 | tr -d '\n=+/' | cut -c1-64
}

gen_fernet_key() {
  # Clé Fernet : 32 octets aléatoires encodés en base64 url-safe (44 caractères).
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import base64,secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())'
  else
    openssl rand -base64 32 | tr '+/' '-_'
  fi
}

# ------------------------------------------------------------------- pré-requis
log "Vérification du système"
[[ -r /etc/os-release ]] || die "/etc/os-release introuvable : système non pris en charge."
# shellcheck disable=SC1091
. /etc/os-release
case "${ID:-}" in
  ubuntu|debian) ;;
  *) warn "Distribution « ${ID:-inconnue} » non testée ; le script suppose apt-get." ;;
esac
command -v apt-get >/dev/null 2>&1 || die "apt-get est requis (Ubuntu/Debian)."

if [[ $DRY_RUN -eq 0 && $EUID -ne 0 ]]; then
  require_root "$@"
fi

log "Installation des paquets de base (git, curl, python3, openssl)"
run as_root apt-get update -qq
run as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  ca-certificates curl git python3 openssl gnupg lsb-release

if ! command -v docker >/dev/null 2>&1; then
  log "Installation de Docker"
  run as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io
fi

if ! docker compose version >/dev/null 2>&1; then
  log "Installation du plugin Docker Compose"
  run as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-compose-v2 \
    || run as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker-compose-plugin
fi

if [[ $DRY_RUN -eq 0 ]] && ! docker compose version >/dev/null 2>&1; then
  die "Docker Compose v2 est introuvable. Installez le plugin : https://docs.docker.com/compose/install/linux/"
fi

# ----------------------------------------------------------------- pare-feu local
open_http_ports() {
  # Oracle Cloud (Ubuntu) filtre 80/443 dans iptables en plus de la Security
  # List du subnet : sans cette règle, Caddy est injoignable depuis Internet.
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow 80/tcp >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
    log "ufw : ports 80/443 autorisés"
  fi
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
    firewall-cmd --permanent --add-service=http >/dev/null 2>&1 || true
    firewall-cmd --permanent --add-service=https >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
    log "firewalld : services http/https autorisés"
  fi
  if command -v iptables >/dev/null 2>&1 && iptables -S INPUT 2>/dev/null | grep -q -- "-j REJECT"; then
    for port in 80 443; do
      iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
        || iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
    done
    command -v netfilter-persistent >/dev/null 2>&1 && netfilter-persistent save >/dev/null 2>&1 || true
    log "iptables : ports 80/443 autorisés (règles Oracle Cloud)"
  fi
}

if [[ $DRY_RUN -eq 0 ]]; then
  open_http_ports
else
  log "[dry-run] ouverture des ports 80/443 (ufw / firewalld / iptables)"
fi

if ! command -v caddy >/dev/null 2>&1; then
  log "Installation de Caddy (HTTPS automatique)"
  run bash -c 'curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg'
  run bash -c 'curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list'
  run as_root apt-get update -qq
  run as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy
fi

run as_root systemctl enable --now docker

# ------------------------------------------------------------------------ code
log "Récupération du code ($REF) dans $APP_DIR"
if [[ -d "$APP_DIR/.git" ]]; then
  run as_root git -C "$APP_DIR" fetch --depth 1 origin "$REF"
  run as_root git -C "$APP_DIR" checkout -q --detach FETCH_HEAD
else
  run as_root mkdir -p "$(dirname "$APP_DIR")"
  run as_root git clone --depth 1 --branch "$REF" "$REPO_URL" "$APP_DIR"
fi
run as_root chmod +x "$APP_DIR/deploy/install.sh" "$APP_DIR/deploy/smoke-test.sh"

BACKEND_DIR="$APP_DIR/backend"
ENV_FILE="$BACKEND_DIR/.env"
if [[ $DRY_RUN -eq 0 ]]; then
  [[ -d "$BACKEND_DIR" ]] || die "backend/ introuvable dans $APP_DIR"
fi

# ------------------------------------------------------------------ secrets .env
log "Configuration de backend/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  # Le dépôt contient un .env de développement : on repart de l'exemple.
  run as_root cp "$BACKEND_DIR/.env.example" "$ENV_FILE"
fi

if [[ $DRY_RUN -eq 0 ]]; then
  current_secret="$(env_value SECRET_KEY "$ENV_FILE")"
  if [[ -z "$current_secret" || ${#current_secret} -lt 32 || "$current_secret" == change* ]]; then
    set_env SECRET_KEY "$(gen_secret)" "$ENV_FILE"
    log "SECRET_KEY générée"
  fi
  if [[ -z "$(env_value SECURE_ID_KEY "$ENV_FILE")" ]]; then
    set_env SECURE_ID_KEY "$(gen_fernet_key)" "$ENV_FILE"
    log "SECURE_ID_KEY générée (à conserver : elle chiffre les secure_id)"
  fi
  set_env ENVIRONMENT production "$ENV_FILE"
  set_env DEBUG false "$ENV_FILE"
  set_env AUTO_CREATE_TABLES true "$ENV_FILE"
  set_env LOG_LEVEL INFO "$ENV_FILE"
  # Seul Caddy doit être joignable depuis Internet.
  set_env API_BIND 127.0.0.1 "$ENV_FILE"
  set_env MYSQL_BIND 127.0.0.1 "$ENV_FILE"
  if [[ -n "$DOMAIN" ]]; then
    set_env PUBLIC_BASE_URL "https://$DOMAIN" "$ENV_FILE"
    set_env ALLOWED_ORIGINS "https://$DOMAIN" "$ENV_FILE"
  fi
else
  log "[dry-run] génération de SECRET_KEY / SECURE_ID_KEY dans $ENV_FILE"
fi

# ------------------------------------------------------------------------ Caddy
log "Configuration du reverse proxy Caddy"
if [[ -n "$DOMAIN" ]]; then
  CADDY_SITE="$DOMAIN"
  PUBLIC_URL="https://$DOMAIN"
else
  CADDY_SITE=":80"
  PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
  PUBLIC_IP="${PUBLIC_IP:-<IP_PUBLIQUE>}"
  PUBLIC_URL="http://$PUBLIC_IP"
  warn "Aucun domaine fourni : l'API sera servie en HTTP sur $PUBLIC_URL (pas de HTTPS)."
fi

if [[ $DRY_RUN -eq 0 ]]; then
  if [[ -n "$DOMAIN" && -n "$EMAIL" ]]; then
    cat > /etc/caddy/Caddyfile <<EOF
{
	email $EMAIL
}

$CADDY_SITE {
	encode zstd gzip
	reverse_proxy 127.0.0.1:8000
}
EOF
  else
    cat > /etc/caddy/Caddyfile <<EOF
$CADDY_SITE {
	encode zstd gzip
	reverse_proxy 127.0.0.1:8000
}
EOF
  fi
  systemctl enable --now caddy >/dev/null 2>&1 || true
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
else
  log "[dry-run] écriture de /etc/caddy/Caddyfile pour $CADDY_SITE"
fi

# ---------------------------------------------------------------------- compose
log "Construction et démarrage de la stack (API + MySQL 8.4)"
run as_root docker compose --project-directory "$BACKEND_DIR" \
  -f "$BACKEND_DIR/docker-compose.mysql.yml" up -d --build

if [[ $DRY_RUN -eq 0 ]]; then
  log "Attente de /health (création des 248 tables au premier démarrage)…"
  healthy=0
  for _ in $(seq 1 120); do
    if curl -fsS --max-time 3 http://127.0.0.1:8000/health >/dev/null 2>&1; then
      healthy=1
      break
    fi
    sleep 5
  done
  if [[ $healthy -eq 1 ]]; then
    log "API en ligne : $PUBLIC_URL (docs : $PUBLIC_URL/docs)"
  else
    warn "L'API ne répond pas encore après 10 minutes."
    warn "Journal : docker compose -f $BACKEND_DIR/docker-compose.mysql.yml logs --tail=80 api"
  fi
fi

# ------------------------------------------------------------------- sauvegardes
log "Programmation de la sauvegarde quotidienne (03:15)"
if [[ $DRY_RUN -eq 0 ]]; then
  BACKUP_CMD="cd $BACKEND_DIR && docker compose -f docker-compose.mysql.yml exec -T api python -c \"from app.database import SessionLocal; from app.services.admin_security_service import create_backup; db=SessionLocal(); create_backup(db, 'cron', 'daily'); db.close()\" >> /var/log/gestimmo-backup.log 2>&1"
  cat > /etc/cron.d/gestimmo-backup <<EOF
# Sauvegarde quotidienne GestImmo (mysqldump dans le volume « backups »).
SHELL=/bin/sh
15 3 * * * root $BACKUP_CMD
EOF
  chmod 644 /etc/cron.d/gestimmo-backup
  touch /var/log/gestimmo-backup.log
else
  log "[dry-run] écriture de /etc/cron.d/gestimmo-backup"
fi

# ------------------------------------------------------------------------- bilan
cat <<EOF

────────────────────────────────────────────────────────────────
 GestImmo est déployé.

   URL de l'API    : $PUBLIC_URL
   Documentation   : $PUBLIC_URL/docs
   Santé           : $PUBLIC_URL/health
   Code            : $APP_DIR (réf. $REF)
   Base de données : MySQL 8.4, volume Docker « mysql_data »
   Données         : volumes public_uploads, private_uploads, backups

 Comptes créés au premier démarrage (À CHANGER IMMÉDIATEMENT) :
   admin@immogest.com / Admin@2024!
   gestionnaire@immogest.com / Manager@2024!
   lecteur@immogest.com / Viewer@2024!

 Vérification rapide :
   $APP_DIR/deploy/smoke-test.sh --url $PUBLIC_URL

 Mises à jour : relancer ce script (git + rebuild + redémarrage).
   sudo $APP_DIR/deploy/install.sh${DOMAIN:+ --domain $DOMAIN}${EMAIL:+ --email $EMAIL}

 Sauvegardes : /var/log/gestimmo-backup.log (tous les jours à 03:15).
────────────────────────────────────────────────────────────────

EOF
