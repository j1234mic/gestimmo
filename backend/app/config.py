mport os
from dotenv import load_dotenv
from pathlib import Path

# Charger .env si existe
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

class Settings:
    # Base de données
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://immo_user:immo_password_2024@localhost:5432/immo_db"
    )
    
    # Application
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    
    # Uploads
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")
    
    @property
    def upload_dir_path(self):
        return Path(__file__).parent.parent / self.UPLOAD_DIR

settings = Settings()
