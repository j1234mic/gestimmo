import os
from pathlib import Path

from dotenv import load_dotenv

# Charge un éventuel fichier .env (développement local). Sans effet en Docker,
# où les variables sont injectées par l'environnement. override=False pour ne
# jamais écraser une variable déjà positionnée par l'hôte.
load_dotenv()


class Settings:
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    APP_NAME = "API Gestion Immobilière"
    APP_VERSION = "1.2.0"
    SECRET_KEY = os.getenv("SECRET_KEY", "ma-cle-secrete-2024")
    ALLOWED_ORIGINS = ["*"]
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
    PRIVATE_UPLOAD_DIR = os.getenv("PRIVATE_UPLOAD_DIR", "private_uploads")
    BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://immo_user:immo_password_2024@localhost:5432/immo_db")
    DEBUG = os.getenv("DEBUG", "true").lower() == "true"
    AUTO_CREATE_TABLES = os.getenv("AUTO_CREATE_TABLES", "true").lower() == "true"
    SMS_WEBHOOK_URL = os.getenv("SMS_WEBHOOK_URL", "")
    SMS_WEBHOOK_TOKEN = os.getenv("SMS_WEBHOOK_TOKEN", "")
    # Chat libre : endpoint compatible OpenAI (OpenAI, Azure proxy, Ollama,
    # etc.). Sans ces variables, le chatbot métier reste local et le chat
    # général explique clairement qu'aucun fournisseur n'est configuré.
    AI_CHAT_BASE_URL = os.getenv("AI_CHAT_BASE_URL", "").rstrip("/")
    AI_CHAT_API_KEY = os.getenv("AI_CHAT_API_KEY", "")
    AI_CHAT_MODEL = os.getenv("AI_CHAT_MODEL", "")
    AI_CHAT_TIMEOUT_SECONDS = float(os.getenv("AI_CHAT_TIMEOUT_SECONDS", "25"))


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

settings = Settings()
ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "gif"]
