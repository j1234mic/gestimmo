# backend/app/main.py

from fastapi import FastAPI
import asyncio
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging
import os

# Imports des routeurs
from app.routes.documents import router as documents_router
from app.routes.properties import router as properties_router
from app.routes.auth import router as auth_router
from app.routes.history import router as history_router
from app.routes.export import router as export_router
from app.routes.owners import router as owners_router
from app.routes.accounting import router as accounting_router
from app.routes.notifications import router as notifications_router
from app.routes.messages import router as messages_router
from app.routes.applications import router as applications_router
from app.routes.tenants import router as tenants_router
from app.routes.tenant_portal import router as tenant_portal_router
from app.routes.leases import router as leases_router, signature_router as lease_signature_router
from app.routes.inspections import router as inspections_router
from app.routes.finance import router as finance_router
from app.routes.maintenance import router as maintenance_router
from app.routes.condo import router as condo_router
from app.routes.crm import router as crm_router
from app.routes.reporting import router as reporting_router
from app.routes.comms import router as comms_router
from app.routes.ged import router as ged_router
from app.routes.admin_security import router as admin_security_router, public_router as privacy_router
from app.routes.geolocation import router as geolocation_router
from app.routes import owner_portal, communication
from app.config import settings
from app.database import init_db, SessionLocal

# Import des middlewares personnalisés depuis core/security.py
from app.core.security import SecurityHeadersMiddleware, RequestSanitizer
from app.middleware.audit import AuditTrailMiddleware

# Configuration du logging
app_logger = logging.getLogger("app")
logging.basicConfig(level=logging.INFO)

# Création de l'application FastAPI
app = FastAPI(
    title="API Gestion Immobilière",
    version="1.0.0",
    docs_url="/docs",
)

# 1. Middleware CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En production, remplacez par les domaines autorisés
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Middleware de sécurité (headers HTTP)
app.add_middleware(SecurityHeadersMiddleware)

# 3. Middleware de nettoyage des requêtes
app.add_middleware(RequestSanitizer)

# 4. Journal minimal de toutes les mutations HTTP (les services ajoutent le
# détail avant/après lorsqu'il est disponible).
app.add_middleware(AuditTrailMiddleware)

# Inclusion des routeurs
app.include_router(properties_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(history_router)
app.include_router(export_router)
app.include_router(owners_router)
app.include_router(accounting_router)
app.include_router(notifications_router)
app.include_router(messages_router)
app.include_router(applications_router)
app.include_router(tenants_router)
app.include_router(tenant_portal_router)
app.include_router(leases_router)
app.include_router(lease_signature_router)
app.include_router(inspections_router)
app.include_router(finance_router)
app.include_router(maintenance_router)
app.include_router(condo_router)

# Modules 8 à 11 : CRM, reporting, communication, GED
app.include_router(crm_router)
app.include_router(reporting_router)
app.include_router(comms_router)
app.include_router(ged_router)

# Modules 12 et 13 : administration/sécurité et cartographie
app.include_router(admin_security_router)
app.include_router(privacy_router)
app.include_router(geolocation_router)

# Routeurs du portail propriétaire et de la communication
app.include_router(owner_portal.router)
app.include_router(communication.router)

# Seuls les médias publics historiques sont servis statiquement. Les dossiers
# locataires sont conservés dans PRIVATE_UPLOAD_DIR et passent par des routes
# authentifiées de téléchargement.
os.makedirs(settings.upload_dir_path, exist_ok=True)
os.makedirs(settings.private_upload_dir_path, exist_ok=True)
os.makedirs(settings.backup_dir_path, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir_path)), name="uploads")

# Endpoints de base
@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/")
async def root():
    return {"message": "API OK", "docs": "/docs"}

async def _backup_scheduler():
    """Déclencheur horaire léger du backup quotidien configuré.

    Le premier passage est différé : le démarrage HTTP n'est jamais bloqué par
    une copie de base. ``run_daily_backup_if_due`` garantit un seul backup par
    jour même avec plusieurs réveils.
    """
    from app.services.admin_security_service import run_daily_backup_if_due

    while True:
        await asyncio.sleep(3600)

        def process():
            db = SessionLocal()
            try:
                run_daily_backup_if_due(db)
            except Exception:
                app_logger.exception("Échec du planificateur de sauvegarde")
            finally:
                db.close()

        await asyncio.to_thread(process)


# Événement de démarrage
@app.on_event("startup")
async def startup():
    if settings.AUTO_CREATE_TABLES:
        init_db()
    app.state.backup_task = asyncio.create_task(_backup_scheduler())
    app_logger.info("🚀 API démarrée !")


@app.on_event("shutdown")
async def shutdown():
    task = getattr(app.state, "backup_task", None)
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
