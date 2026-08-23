from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings


engine_kwargs = {
    "pool_pre_ping": True,
    "echo": settings.DEBUG,
}
if settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_module_12_13_columns():
    """Migration additive minimale pour la table historique ``properties``.

    ``create_all`` crée toutes les nouvelles tables mais n'ajoute pas de
    colonnes à une table existante. Ces trois colonnes nullable sont sûres sur
    PostgreSQL comme sur SQLite et rendent le déploiement des modules 12/13
    compatible avec une installation existante.
    """
    inspector = inspect(engine)
    if "properties" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("properties")}
    with engine.begin() as connection:
        for name in ("entity_id", "agency_id", "portfolio_id"):
            if name not in existing:
                connection.execute(text(f"ALTER TABLE properties ADD COLUMN {name} INTEGER"))
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_properties_{name} ON properties ({name})"))


def init_db():
    """Charge tous les modèles puis crée uniquement les tables absentes.

    Le projet ne disposant pas encore d'Alembic, ``create_all`` assure le
    démarrage d'une installation neuve. Une base existante n'est jamais
    supprimée ni recréée.
    """
    from app.models import accounting, lease_contract, message, notification, owner, property, report, tenant  # noqa: F401
    from app.models import finance, maintenance, condo, crm, reporting, communication, ged  # noqa: F401
    from app.models import admin_security, geolocation  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_module_12_13_columns()

    # Amorçage idempotent des profils prédéfinis et des comptes historiques.
    from app.services.admin_security_service import bootstrap_security

    bootstrap_security()
