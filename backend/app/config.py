import logging
import os
import urllib.parse
from pathlib import Path

from dotenv import load_dotenv

# Charge backend/.env pour le développement local, quel que soit le CWD.
# override=False : une variable déjà positionnée par l'hôte ou Docker l'emporte.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)

# Hôtes qui n'existent que dans le réseau docker-compose (noms de services).
# Ils ne sont résolubles qu'à l'intérieur des conteneurs, jamais sur la machine hôte.
COMPOSE_ONLY_HOSTS = {"postgres", "db", "mysql", "mariadb"}

# Railway n'expose pas toujours /.dockerenv dans ses conteneurs. Ces variables
# sont injectées à l'exécution et indiquent que l'application est sur Railway.
RAILWAY_RUNTIME_MARKERS = (
    "RAILWAY_SERVICE_ID",
    "RAILWAY_DEPLOYMENT_ID",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_ENVIRONMENT_NAME",
)

# SQLAlchemy ne fournit aucun connecteur MySQL : le schéma d'URL écrit par les
# hébergeurs (`mysql://…`, `mariadb://…`, `mysql+mysqldb://…`) est réécrit vers
# PyMySQL, le pilote pur Python déclaré dans requirements.txt. Sans cela,
# SQLAlchemy tenterait de charger MySQLdb, absent de l'image Docker.
MYSQL_SCHEME_PREFIXES = {"mysql", "mariadb"}


def normalize_mysql_scheme(scheme: str) -> str:
    """Force PyMySQL pour tout schéma MySQL/MariaDB."""
    lowered = scheme.lower()
    if lowered.split("+", 1)[0] in MYSQL_SCHEME_PREFIXES and not lowered.endswith("+pymysql"):
        return "mysql+pymysql"
    return scheme


def is_railway_environment() -> bool:
    """Vrai quand Railway a injecté ses marqueurs d'environnement d'exécution."""
    return any(os.getenv(marker) for marker in RAILWAY_RUNTIME_MARKERS)


# Vercel injecte ces variables dans chaque Function/conteneur. Elles signalent
# un environnement serverless : système de fichiers en lecture seule hors /tmp,
# mise à l'échelle à zéro après ~5 min d'inactivité et aucune tâche de fond
# durable.
VERCEL_RUNTIME_MARKERS = (
    "VERCEL",
    "VERCEL_ENV",
    "VERCEL_DEPLOYMENT_ID",
    "VERCEL_URL",
)


def is_vercel_environment() -> bool:
    """Vrai quand l'API tourne sur Vercel (Function Python ou conteneur)."""
    return any(os.getenv(marker) for marker in VERCEL_RUNTIME_MARKERS)


def is_serverless_environment() -> bool:
    """Vrai sur les plateformes sans disque persistant ni processus long."""
    return is_vercel_environment()


def running_inside_docker() -> bool:
    """Vrai dans Docker/Kubernetes ou sur Railway, même sans ``/.dockerenv``.

    Cette détection évite de transformer un nom de service en ``localhost``
    sur les plateformes conteneurisées qui ne créent pas le fichier marker.
    """
    return (
        Path("/.dockerenv").exists()
        or bool(os.getenv("KUBERNETES_SERVICE_HOST"))
        or is_railway_environment()
    )


def normalize_database_url(url: str, *, in_docker: bool | None = None) -> str:
    """Normalise ``DATABASE_URL`` avant sa transmission à SQLAlchemy.

    Deux corrections sont appliquées :

    1. **Hôte compose-only** — ``postgres``/``mysql`` sont des alias du réseau
       docker-compose. Lancer ``uvicorn`` sur la machine hôte avec une telle URL
       échoue (« could not translate host name … ») ; hors conteneur, l'hôte est
       remappé vers ``localhost`` et le port publié par compose est conservé.
       Les marqueurs Railway/Kubernetes empêchent ce remappage dans les services
       déployés, même si la plateforme ne fournit pas ``/.dockerenv``.
    2. **Pilote MySQL** — ``mysql://`` et ``mariadb://`` sont réécrits vers
       ``mysql+pymysql://`` : PyMySQL est le pilote pur Python embarqué dans
       l'image, MySQLdb n'y est pas installé.
    """
    if not url:
        return url
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url

    netloc = parts.netloc
    try:
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return url
    changed = False
    if in_docker is None:
        in_docker = running_inside_docker()

    if not in_docker and host in COMPOSE_ONLY_HOSTS:
        userinfo, sep, hostport = netloc.rpartition("@")
        if not sep:
            userinfo, hostport = "", netloc
        # Remplace uniquement l'hôte, en conservant identifiants et port.
        if hostport.lower().startswith(host):
            hostport = "localhost" + hostport[len(host):]
        netloc = f"{userinfo}@{hostport}" if userinfo else hostport
        changed = True

        shown = f"{parts.scheme}://localhost" + (f":{port}" if port else "") + parts.path
        logging.getLogger(__name__).warning(
            "DATABASE_URL cible l'hôte Docker « %s » mais l'API tourne hors Docker ; "
            "l'hôte a été remappé vers localhost (%s). Vérifiez que le service de "
            "base de données est démarré : docker compose up -d postgres, ou "
            "docker compose -f docker-compose.mysql.yml up -d mysql",
            host,
            shown,
        )

    scheme = parts.scheme.lower()
    normalized_scheme = normalize_mysql_scheme(scheme)
    if normalized_scheme != parts.scheme:
        changed = True
    if not changed:
        # Ne pas resérialiser une URL inchangée : urlunsplit() casse les URL
        # SQLite absolues (sqlite:////tmp/x.db → sqlite://tmp/x.db).
        return url
    return urllib.parse.urlunsplit(
        (normalized_scheme or scheme, netloc, parts.path, parts.query, parts.fragment)
    )


def parse_bool(raw: str | None, default: bool = False) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_int(raw: str | None, default: int) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def parse_float(raw: str | None, default: float) -> float:
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def parse_csv_list(raw: str | None, default: list[str] | None = None) -> list[str]:
    if raw is None or raw.strip() == "":
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings:
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    APP_NAME = "API Gestion Immobilière"
    APP_VERSION = "1.2.0"
    SECRET_KEY = os.getenv("SECRET_KEY", "ma-cle-secrete-2024")
    # Clé de chiffrement des identifiants publics (secure_id). Si absente, une
    # clé de session éphémère est générée (voir app/hexagon/infrastructure/security/id_cipher.py).
    SECURE_ID_KEY = os.getenv("SECURE_ID_KEY", "")
    ACCESS_TOKEN_EXPIRE_MINUTES = parse_int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"), 30)
    REFRESH_TOKEN_EXPIRE_DAYS = parse_int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS"), 7)
    RATE_LIMIT_REQUESTS = parse_int(os.getenv("RATE_LIMIT_REQUESTS"), 100)
    RATE_LIMIT_WINDOW = parse_int(os.getenv("RATE_LIMIT_WINDOW"), 60)
    RATE_LIMIT_ENABLED = parse_bool(os.getenv("RATE_LIMIT_ENABLED"), True)
    ALLOWED_ORIGINS = parse_csv_list(os.getenv("ALLOWED_ORIGINS"), ["*"])
    ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "gif"]
    ALLOWED_VIDEO_EXTENSIONS = ["mp4", "mov", "webm", "m4v"]
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
    PRIVATE_UPLOAD_DIR = os.getenv("PRIVATE_UPLOAD_DIR", "private_uploads")
    BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
    MAX_UPLOAD_SIZE = parse_int(os.getenv("MAX_UPLOAD_SIZE"), 5_242_880)
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE = os.getenv("LOG_FILE", "logs/app.log")
    DATABASE_URL = normalize_database_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql://immo_user:immo_password_2024@localhost:5432/immo_db",
        )
    )
    DEBUG = parse_bool(os.getenv("DEBUG"), True)
    AUTO_CREATE_TABLES = parse_bool(os.getenv("AUTO_CREATE_TABLES"), True)
    SMS_WEBHOOK_URL = os.getenv("SMS_WEBHOOK_URL", "")
    SMS_WEBHOOK_TOKEN = os.getenv("SMS_WEBHOOK_TOKEN", "")
    # Chat libre : endpoint compatible OpenAI (OpenAI, Azure proxy, Ollama,
    # etc.). Sans ces variables, le chatbot métier reste local et le chat
    # général explique clairement qu'aucun fournisseur n'est configuré.
    AI_CHAT_BASE_URL = os.getenv("AI_CHAT_BASE_URL", "").rstrip("/")
    AI_CHAT_API_KEY = os.getenv("AI_CHAT_API_KEY", "")
    AI_CHAT_MODEL = os.getenv("AI_CHAT_MODEL", "")
    AI_CHAT_TIMEOUT_SECONDS = parse_float(os.getenv("AI_CHAT_TIMEOUT_SECONDS"), 25)

    # Paiement en ligne. Sans clé, l'endpoint de checkout répond explicitement 503.
    STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
    PAYMENT_CURRENCY = os.getenv("PAYMENT_CURRENCY", "EUR")
    PAYMENT_SUCCESS_URL = os.getenv(
        "PAYMENT_SUCCESS_URL", "http://localhost:3000/tenant/payments/{payment_id}?status=success"
    )
    PAYMENT_CANCEL_URL = os.getenv(
        "PAYMENT_CANCEL_URL", "http://localhost:3000/tenant/payments/{payment_id}?status=cancelled"
    )

    # Mode simulation d'encaissement des abonnements (par défaut activé en
    # développement). Quand un prestataire n'est pas configuré, le module
    # « Abonnements » génère une URL de confirmation locale au lieu d'appeler
    # l'API du prestataire ; le webhook reste fonctionnel pour la production.
    PAYMENT_SIMULATION_ENABLED = parse_bool(os.getenv("PAYMENT_SIMULATION_ENABLED"), True)
    # Base publique utilisée pour construire les URL de retour de la page de
    # paiement (redirection du client après encaissement).
    PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:3000")
    # Clés des prestataires de paiement (optionnelles). Renseignez-les en
    # production pour désactiver la simulation et appeler l'API réelle.
    PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID", "")
    PAYPAL_CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET", "")
    PAYPAL_MODE = os.getenv("PAYPAL_MODE", "sandbox")  # sandbox | live

    # ------------------------------------------------------------------
    # Stockage des fichiers (module transverse : médias, GED, preuves,
    # sauvegardes). Deux moteurs :
    #   local — disque de l'instance (comportement historique, Render/VPS) ;
    #   blob  — Vercel Blob, objet durable + URL publique/privée, indispensable
    #           sur Vercel où le système de fichiers est éphémère.
    # ------------------------------------------------------------------
    STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
    BLOB_READ_WRITE_TOKEN = os.getenv(
        "BLOB_READ_WRITE_TOKEN", os.getenv("VERCEL_BLOB_READ_WRITE_TOKEN", "")
    )
    BLOB_STORE_ID = os.getenv("BLOB_STORE_ID", "")
    # `public` : URL servies par le CDN Vercel (médias de galerie).
    # `private` : lecture authentifiée, relayée par l'API (documents locataires).
    BLOB_ACCESS = os.getenv("BLOB_ACCESS", "public").strip().lower()
    BLOB_API_URL = os.getenv("BLOB_API_URL", "https://vercel.com/api/blob").rstrip("/")
    BLOB_API_VERSION = os.getenv("BLOB_API_VERSION", "13")
    BLOB_CACHE_CONTROL_MAX_AGE = parse_int(os.getenv("BLOB_CACHE_CONTROL_MAX_AGE"), 31_536_000)
    BLOB_ADD_RANDOM_SUFFIX = parse_bool(os.getenv("BLOB_ADD_RANDOM_SUFFIX"), True)
    BLOB_TIMEOUT_SECONDS = parse_float(os.getenv("BLOB_TIMEOUT_SECONDS"), 60)
    # Au-delà, un objet passe par l'upload multipart de Vercel Blob.
    BLOB_MULTIPART_THRESHOLD = parse_int(os.getenv("BLOB_MULTIPART_THRESHOLD"), 100 * 1024 * 1024)
    # En cas d'échec du miroir Blob, on garde la copie locale et on journalise :
    # une pièce jointe ne doit jamais faire échouer tout un appel métier.
    BLOB_FAIL_OPEN = parse_bool(os.getenv("BLOB_FAIL_OPEN"), True)

    # ------------------------------------------------------------------
    # Exécution serverless (Vercel)
    # ------------------------------------------------------------------
    # Vercel signe ses appels de Cron Jobs avec `Authorization: Bearer $CRON_SECRET`.
    CRON_SECRET = os.getenv("CRON_SECRET", "")
    # Derrière un proxy (Vercel, Caddy, Render), l'IP cliente réelle est dans
    # X-Forwarded-For. Auto-détecté sur les plateformes managées.
    TRUST_PROXY_HEADERS = parse_bool(
        os.getenv("TRUST_PROXY_HEADERS"),
        is_vercel_environment() or is_railway_environment()
        or bool(os.getenv("RENDER_SERVICE_ID")) or bool(os.getenv("FLY_APP_NAME")),
    )
    # Le planificateur interne de sauvegarde suppose un processus permanent.
    # Sur Vercel l'instance est gelée entre les requêtes : on le désactive et on
    # laisse un Cron Job appeler /api/cron/daily-backup.
    BACKUP_SCHEDULER_ENABLED = parse_bool(
        os.getenv("BACKUP_SCHEDULER_ENABLED"), not is_vercel_environment()
    )
    # Limite de corps de requête imposée par Vercel Functions (4,5 Mo). Au-delà,
    # la plateforme répond 413 avant même d'atteindre FastAPI ; l'API renvoie
    # donc un message actionnable plutôt qu'une erreur opaque.
    VERCEL_BODY_LIMIT = parse_int(os.getenv("VERCEL_BODY_LIMIT"), 4_500_000)
    WISE_API_TOKEN = os.getenv("WISE_API_TOKEN", "")
    MVOLA_API_KEY = os.getenv("MVOLA_API_KEY", "")
    ORANGE_MONEY_CLIENT_ID = os.getenv("ORANGE_MONEY_CLIENT_ID", "")
    ORANGE_MONEY_CLIENT_SECRET = os.getenv("ORANGE_MONEY_CLIENT_SECRET", "")

    @property
    def upload_dir_path(self):
        return Path(__file__).parent.parent / self.UPLOAD_DIR

    @property
    def private_upload_dir_path(self):
        return Path(__file__).parent.parent / self.PRIVATE_UPLOAD_DIR

    @property
    def backup_dir_path(self):
        return Path(__file__).parent.parent / self.BACKUP_DIR

    @property
    def log_file_path(self) -> Path | None:
        if not self.LOG_FILE:
            return None
        path = Path(self.LOG_FILE)
        if path.is_absolute():
            return path
        return Path(__file__).resolve().parent.parent / path

    @property
    def cors_allow_credentials(self) -> bool:
        return self.ALLOWED_ORIGINS != ["*"]

    @property
    def blob_enabled(self) -> bool:
        """Vrai quand le stockage objet Vercel Blob est actif et crédenté.

        Sans jeton, on retombe sur le disque local plutôt que de faire échouer
        chaque écriture : un déploiement Vercel mal configuré reste démarable et
        le journal explique la dégradation.
        """
        return self.STORAGE_BACKEND == "blob" and bool(self.BLOB_READ_WRITE_TOKEN)

    @property
    def effective_upload_limit(self) -> int:
        """Plus petit plafond entre MAX_UPLOAD_SIZE et la limite Vercel.

        Vercel Functions refusent tout corps de requête supérieur à 4,5 Mo avant
        même d'atteindre FastAPI. Annoncer la limite réelle évite de promettre un
        upload de 5 Mo qui échouera côté plateforme.
        """
        if is_vercel_environment():
            return min(self.MAX_UPLOAD_SIZE, self.VERCEL_BODY_LIMIT)
        return self.MAX_UPLOAD_SIZE

    def upload_ceiling(self, requested: int) -> int:
        """Ramène un plafond d'upload métier à la limite imposée par la plateforme.

        Chaque garde conserve son plafond métier — 15 Mo pour une pièce de
        candidature, 50 Mo pour une vidéo d'intervention — mais sur Vercel ce
        plafond est inatteignable : la plateforme répond 413 avant FastAPI.
        L'annoncer tel quel ferait promettre un dépôt accepté qui échoue en
        réalité côté plateforme, avec un corps d'erreur que l'application n'a pas
        écrit. Hors Vercel la valeur est rendue inchangée, ce qui laisse le
        comportement des autres hébergements strictement identique.
        """
        if is_vercel_environment():
            return min(requested, self.VERCEL_BODY_LIMIT)
        return requested


def configure_logging(settings_obj: "Settings | None" = None) -> None:
    """Configure la journalisation stdout + fichier à partir de LOG_LEVEL / LOG_FILE."""
    current = settings_obj or settings
    level = getattr(logging, current.LOG_LEVEL, logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_path = current.log_file_path
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        handlers=handlers,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        force=True,
    )


settings = Settings()
ALLOWED_EXTENSIONS = settings.ALLOWED_EXTENSIONS
