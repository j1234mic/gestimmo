from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    echo=settings.DEBUG
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    from app.models.property import Property
    Base.metadata.create_all(bind=engine)
    print("✅ Tables créées avec succès !")
EOF

# ============================================
# 2. Corriger main.py
# ============================================
cat > app/main.py << 'EOF'
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.database import init_db
from app.routes import properties
import os

app = FastAPI(
    title="API Gestion Immobilière",
    description="API pour la gestion de biens immobiliers",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(properties.router)

# Fichiers statiques
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

@app.get("/health")
async def health_check():
    """Vérifier l'état de l'API"""
    return {
        "status": "healthy",
        "version": "1.0.0",
        "message": "API opérationnelle"
    }

@app.get("/")
async def root():
    """Page d'accueil"""
    return {
        "message": "API Gestion Immobilière",
        "docs": "/docs",
        "health": "/health"
    }

@app.on_event("startup")
async def startup():
    """Initialisation au démarrage"""
    print("🚀 Démarrage de l'API...")
    try:
        init_db()
        print("✅ Base de données initialisée")
    except Exception as e:
        print(f"⚠️  Erreur DB: {e}")
    print("📚 Documentation: http://localhost:8000/docs")