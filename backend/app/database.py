from sqlalchemy import create_engine
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


def init_db():
    """Charge tous les modèles puis crée uniquement les tables absentes.

    Le projet ne disposant pas encore d'Alembic, ``create_all`` assure le
    démarrage d'une installation neuve. Une base existante n'est jamais
    supprimée ni recréée.
    """
    from app.models import accounting, lease_contract, message, notification, owner, property, report, tenant  # noqa: F401
    from app.models import finance, maintenance, condo, crm, reporting  # noqa: F401

    Base.metadata.create_all(bind=engine)
