import os
from pathlib import Path

class Settings:
    ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
    APP_NAME = "API Gestion Immobilière"
    APP_VERSION = "1.0.0"
    SECRET_KEY = os.getenv("SECRET_KEY", "ma-cle-secrete-2024")
    ALLOWED_ORIGINS = ["*"]
    UPLOAD_DIR = "uploads"
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://immo_user:immo_password_2024@localhost:5432/immo_db")
    DEBUG = os.getenv("DEBUG", "true").lower() == "true"

    @property
    def upload_dir_path(self):
        return Path(__file__).parent.parent / self.UPLOAD_DIR

settings = Settings()
ALLOWED_EXTENSIONS = ["jpg", "jpeg", "png", "webp", "gif"]
