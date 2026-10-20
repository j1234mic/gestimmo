# backend/app/main.py

from fastapi import FastAPI
import asyncio
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging
import os
import urllib.parse

import sqlalchemy.exc

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
from app.routes.mobile_insurance import router as mobile_insurance_router
from app.routes.extension import router as extension_router
from app.routes.public_portal import router as public_portal_router
from app.routes.ai_automation import router as ai_router, tenant_router as tenant_ai_router
from app.routes.integrations import router as integrations_router, external_router as external_api_router
from app.routes.subscriptions import router as subscriptions_router
from app.routes.cron import router as cron_router
from app.routes import owner_portal, communication
# Architecture hexagonale : routeurs v2 (Properties / Owners).
from app.hexagon.web.property_router import router as properties_v2_router
from app.hexagon.web.owner_router import router as owners_v2_router
from app.config import configure_logging, is_railway_environment, settings
from app.database import init_db, SessionLocal

# Import des middlewares personnalisés depuis core/security.py
from app.core.security import SecurityHeadersMiddleware, RequestSanitizer
from app.middleware.audit import AuditTrailMiddleware
from app.middleware.rate_limit import RateLimitMiddleware

# Configuration du logging
configure_logging(settings)
app_logger = logging.getLogger("app")

# Création de l'application FastAPI
app = FastAPI(
    title="API Gestion Immobilière",
    version=settings.APP_VERSION,
    description=(
        "API GestImmo : gestion immobilière, prédictions explicables, automatisation, "
        "connecteurs natifs et API publique versionnée."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

# 1. Middleware CORS — origines lues depuis ALLOWED_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=settings.cors_allow_credentials,
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

# 5. Rate limiting global (RATE_LIMIT_REQUESTS / RATE_LIMIT_WINDOW)
app.add_middleware(RateLimitMiddleware)

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
app.include_router(mobile_insurance_router)

# Modules 16 et 17 : IA/RPA, OCR, marché, intégrations et API publique v1
app.include_router(ai_router)
app.include_router(tenant_ai_router)
app.include_router(integrations_router)
app.include_router(external_api_router)
app.include_router(extension_router)
app.include_router(public_portal_router)

# Routeurs du portail propriétaire et de la communication
app.include_router(owner_portal.router)
app.include_router(communication.router)

# Module « Abonnements & revenus récurrents »
app.include_router(subscriptions_router)

# Tâches périodiques appelées par le planificateur de la plateforme
# (Vercel Cron Jobs, cron externe, GitHub Actions schedule).
app.include_router(cron_router)

# Routeurs hexagonaux (v2) — pilotés par les cas d'usage, sans logique ORM
# dans les routes. Ils coexistent avec les routeurs historiques.
app.include_router(properties_v2_router)
app.include_router(owners_v2_router)

# Seuls les médias publics historiques sont servis statiquement. Les dossiers
# locataires sont conservés dans PRIVATE_UPLOAD_DIR et passent par des routes
# authentifiées de téléchargement.
#
# Sur Vercel le système de fichiers est en lecture seule hors /tmp : ces
# variables doivent pointer vers /tmp (voir Dockerfile.vercel). La création est
# tolérante aux échecs pour qu'un volume non inscriptible dégrade le stockage au
# lieu d'empêcher l'application de démarrer — un 500 sur /health masquerait la
# cause réelle.
def _prepare_storage_dirs() -> list[str]:
    """Crée les racines de stockage et renvoie la liste des échecs."""
    failures: list[str] = []
    for label, directory in (
        ("UPLOAD_DIR", settings.upload_dir_path),
        ("PRIVATE_UPLOAD_DIR", settings.private_upload_dir_path),
        ("BACKUP_DIR", settings.backup_dir_path),
    ):
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError as exc:
            failures.append(label)
            app_logger.error(
                "❌ Racine de stockage %s=%s non créable (%s).\n"
                "   Sur Vercel le système de fichiers est en lecture seule : seul /tmp "
                "est inscriptible. Définissez %s=/tmp/... ou activez STORAGE_BACKEND=blob.",
                label, directory, exc, label,
            )
    return failures


_storage_dir_failures = _prepare_storage_dirs()

# En stockage Blob, les médias sont servis par le CDN Vercel via leur URL :
# monter un dossier local vide ne ferait que renvoyer des 404 trompeurs.
if not settings.blob_enabled and "UPLOAD_DIR" not in _storage_dir_failures:
    app.mount("/uploads", StaticFiles(directory=str(settings.upload_dir_path)), name="uploads")
elif settings.blob_enabled:
    app_logger.info("📦 Stockage Vercel Blob actif : /uploads n'est pas monté (médias servis par le store).")


# Endpoints de base
@app.get("/health")
async def health():
    from app.services import file_storage

    return {
        "status": "healthy",
        "storage": file_storage.describe_backend(),
        "internal_backup_scheduler": settings.BACKUP_SCHEDULER_ENABLED,
        "writable_storage_dirs": not _storage_dir_failures,
    }

@app.get("/")
async def root():
    return {"message": "API OK", "docs": "/docs", "public_api": "/api/v1", "version": app.version}


def custom_openapi():
    """Documente les deux méthodes d'authentification de l'API publique.

    L'interface d'administration continue d'utiliser le Bearer JWT historique ;
    les opérations ``/api/v1`` acceptent, au choix, une API key ou un jeton
    OAuth2 client_credentials.
    """
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    security_schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    security_schemes["ApiKeyAuth"] = {
        "type": "apiKey", "in": "header", "name": "X-API-Key",
        "description": "Clé créée depuis POST /api/integrations/api-keys.",
    }
    security_schemes["OAuth2ClientCredentials"] = {
        "type": "oauth2",
        "flows": {
            "clientCredentials": {
                "tokenUrl": "/api/integrations/oauth/token",
                "scopes": {
                    "properties:read": "Lire les biens",
                    "properties:write": "Créer ou modifier des biens",
                    "tenants:read": "Lire l'annuaire locataire limité",
                    "webhooks:write": "Émettre des événements webhook",
                },
            }
        },
    }
    for path, operations in schema.get("paths", {}).items():
        if path.startswith("/api/v1"):
            for operation in operations.values():
                if isinstance(operation, dict):
                    operation["security"] = [{"ApiKeyAuth": []}, {"OAuth2ClientCredentials": []}]
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi


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
        try:
            init_db()
        except sqlalchemy.exc.OperationalError as exc:
            # Message court et actionnable plutôt qu'une pile d'appels de 60 trames.
            db_host = "localhost"
            try:
                db_host = urllib.parse.urlsplit(settings.DATABASE_URL).hostname or db_host
            except ValueError:
                pass
            is_mysql = settings.DATABASE_URL.startswith(("mysql", "mariadb"))
            if is_railway_environment():
                service_hint = (
                    "   Vérifiez que le service de base de données est démarré et accessible dans le projet Railway.\n"
                    "   Dans les variables du service API, définissez DATABASE_URL comme référence à la base,\n"
                    "   par exemple ${{Postgres.DATABASE_URL}} (remplacez Postgres par le nom exact du service).\n"
                    "   N'utilisez ni « localhost » ni l'alias Docker Compose « postgres » : ce n'est pas\n"
                    "   l'adresse du service Railway. Pour une base externe, vérifiez l'URL, le port et TLS."
                )
            elif is_mysql:
                service_hint = (
                    "   1) Le conteneur mysql est-il démarré ?\n"
                    "      -> docker compose -f docker-compose.mysql.yml up -d mysql\n"
                    "   2) Base managée (Aiven, HeatWave…) : vérifiez l'hôte, le port\n"
                    "      (souvent 12345 chez Aiven) et le paramètre ssl-mode dans\n"
                    "      DATABASE_URL (backend/.env).\n"
                    "   3) Ou lancez toute la stack MySQL : docker compose -f docker-compose.mysql.yml up --build"
                )
            else:
                service_hint = (
                    "   1) Le conteneur postgres est-il démarré ? -> docker compose up -d postgres\n"
                    "   2) L'API tourne hors Docker : l'hôte « postgres » a été remappé vers\n"
                    "      « localhost » ; vérifiez DATABASE_URL dans backend/.env\n"
                    "      (postgresql://immo_user:immo_password_2024@localhost:5432/immo_db)\n"
                    "   3) Ou lancez toute la stack dans Docker : docker compose up --build"
                )
            app_logger.error(
                "❌ Impossible de joindre la base de données (%s).\n"
                "   Cause racine : %s\n%s",
                db_host,
                exc.orig,
                service_hint,
            )
            raise RuntimeError(f"Connexion impossible à la base de données ({db_host}) : {exc.orig}") from exc

    # La boucle asyncio suppose un processus permanent. Sur Vercel l'instance est
    # gelée entre les requêtes puis détruite après ~5 min d'inactivité : la tâche
    # ne se réveille jamais. On la remplace par un Cron Job qui appelle
    # GET /api/cron/daily avec Authorization: Bearer $CRON_SECRET.
    if settings.BACKUP_SCHEDULER_ENABLED:
        app.state.backup_task = asyncio.create_task(_backup_scheduler())
    else:
        app.state.backup_task = None
        app_logger.info(
            "⏱️  Planificateur interne désactivé (BACKUP_SCHEDULER_ENABLED=false) : "
            "les sauvegardes quotidiennes doivent être déclenchées par GET /api/cron/daily."
        )
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
