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


def _add_column_if_missing(connection, table: str, column_name: str,
                           column_type: str, nullable: bool = True,
                           index: bool = False, default: str | None = None):
    """Ajoute une colonne à une table existante si elle est absente."""
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table)}
    if column_name not in existing:
        ddl = f"ALTER TABLE {table} ADD COLUMN {column_name} {column_type}"
        if not nullable:
            ddl += " NOT NULL"
        if default is not None:
            ddl += f" DEFAULT {default}"
        connection.execute(text(ddl))
    if index:
        connection.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{table}_{column_name} ON {table} ({column_name})"))


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


def _ensure_property_completion_columns():
    """Colonnes du module 1 : gestionnaire, disponibilité et visite 360°."""
    with engine.begin() as connection:
        _add_column_if_missing(connection, "properties", "manager_id", "INTEGER", index=True)
        _add_column_if_missing(connection, "properties", "available_from", "DATE", index=True)
        _add_column_if_missing(connection, "properties", "virtual_tour_url", "VARCHAR(500)")
        _add_column_if_missing(connection, "properties", "is_360_available", "BOOLEAN", index=False, default="0")
        _add_column_if_missing(connection, "property_photos", "media_type", "VARCHAR(20)", default="'image'")


def _ensure_mandate_signature_columns():
    """Colonnes du dossier de preuve de signature électronique des mandats."""
    with engine.begin() as connection:
        for name in ("signature_hash", "signature_document_hash", "signature_ip"):
            _add_column_if_missing(connection, "mandates", name, "VARCHAR(64)")
        _add_column_if_missing(connection, "mandates", "signature_evidence_path", "VARCHAR(700)")
        _add_column_if_missing(connection, "mandates", "signature_image_path", "VARCHAR(700)")
        _add_column_if_missing(connection, "mandates", "signature_consent_at", "DATETIME")
        _add_column_if_missing(connection, "mandates", "signature_user_agent", "VARCHAR(1000)")
        _add_column_if_missing(connection, "mandates", "signature_provider", "VARCHAR(50)", default="'internal_simple_signature'")
        _add_column_if_missing(connection, "mandates", "signature_requested_at", "DATETIME")


def _ensure_insurance_scope_columns():
    """Colonnes de cloisonnement société/agence pour les assurances."""
    for table in ("insurance_contracts", "insurance_attestations", "insurance_claims"):
        with engine.begin() as connection:
            _add_column_if_missing(connection, table, "entity_id", "INTEGER", index=True)
            _add_column_if_missing(connection, table, "agency_id", "INTEGER", index=True)
    with engine.begin() as connection:
        _add_column_if_missing(connection, "insurance_attestations", "last_reminded_at", "DATETIME")


def _backfill_secure_ids():
    """Chiffre les identifiants entiers existants dans ``secure_id``.

    Idempotent : seules les lignes dont ``secure_id`` est NULL sont traitées.
    Garantit qu'aucune entité persistée n'expose son id entier sans
    équivalent chiffré.
    """
    from app.hexagon.infrastructure.security.id_cipher import encrypt_id
    from app.models.owner import Owner
    from app.models.property import Property

    orm_model = {"properties": Property, "owners": Owner}
    for table in ("properties", "owners"):
        inspector = inspect(engine)
        if table not in inspector.get_table_names():
            continue
        cols = {c["name"] for c in inspector.get_columns(table)}
        if "secure_id" not in cols:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN secure_id VARCHAR(255)"))
                connection.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table}_secure_id ON {table} (secure_id)"))
        with SessionLocal() as db:
            rows = db.query(orm_model[table]).filter(orm_model[table].secure_id.is_(None)).all()
            for row in rows:
                row.secure_id = encrypt_id(row.id)
            if rows:
                db.commit()


def init_db():
    """Charge tous les modèles puis crée uniquement les tables absentes.

    Le projet ne disposant pas encore d'Alembic, ``create_all`` assure le
    démarrage d'une installation neuve. Une base existante n'est jamais
    supprimée ni recréée.
    """
    from app.models import accounting, lease_contract, message, notification, owner, property, report, tenant  # noqa: F401
    from app.models import finance, maintenance, condo, crm, reporting, communication, ged  # noqa: F401
    from app.models import admin_security, geolocation, insurance  # noqa: F401
    from app.models import ai_automation, integration  # noqa: F401
    from app.models import extension  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_module_12_13_columns()
    _ensure_property_completion_columns()
    _ensure_mandate_signature_columns()
    _ensure_insurance_scope_columns()
    _backfill_secure_ids()

    # Amorçage idempotent des profils prédéfinis et des comptes historiques.
    from app.services.admin_security_service import bootstrap_security

    bootstrap_security()
