import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# Charge backend/.env pour le développement local, quel que soit le CWD.
# override=False : une variable déjà positionnée par l'hôte ou Docker l'emporte.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)


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
    ACCESS_TOKEN_EXPIRE_MINUTES = parse_int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES"), 30)
    REFRESH_TOKEN_EXPIRE_DAYS = parse_int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS"), 7)
    RATE_LIMIT_REQUESTS = parse_int(os.getenv("RATE_LIMIT_REQUESTS"), 100)
    RATE_LIMIT_WINDOW = parse_int(os.getenv("RATE_LIMIT_WINDOW"), 60)
    RATE_LIMIT_ENABLED = parse_bool(os.getenv("RATE_LIMIT_ENABLED"), True)
    ALLOWED_ORIGINS = parse_csv_list(os.getenv("ALLOWED_ORIGINS"), ["*"])
    ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "gif"]
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
    PRIVATE_UPLOAD_DIR = os.getenv("PRIVATE_UPLOAD_DIR", "private_uploads")
    BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
    MAX_UPLOAD_SIZE = parse_int(os.getenv("MAX_UPLOAD_SIZE"), 5_242_880)
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE = os.getenv("LOG_FILE", "logs/app.log")
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://immo_user:immo_password_2024@localhost:5432/immo_db",
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
