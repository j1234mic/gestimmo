import urllib.parse
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import parse_bool, settings

# Paramètres d'URL compris par MySQL mais pas par PyMySQL/SQLAlchemy.
_MYSQL_TLS_QUERY_KEYS = {
    "ssl-mode",
    "ssl_mode",
    "ssl-ca",
    "ssl_ca",
    "ssl-cert",
    "ssl_cert",
    "ssl-key",
    "ssl_key",
    "ssl-check-hostname",
    "ssl_check_hostname",
}


def _mysql_ssl_options(
    mode: str | None,
    ca: str | None,
    cert: str | None,
    key: str | None,
    check_hostname: bool | None,
) -> tuple[dict[str, Any], bool]:
    """Traduit ``ssl-mode``/``ssl-ca`` (syntaxe MySQL) vers PyMySQL.

    Les hébergeurs MySQL fournissent des URL du type
    ``mysql://user:pass@host:3306/db?ssl-mode=REQUIRED``. PyMySQL ne connaît
    pas ``ssl-mode`` : il attend un dictionnaire ``ssl``. On reproduit donc la
    sémantique MySQL : ``REQUIRED`` chiffre sans valider le certificat,
    ``VERIFY_CA``/``VERIFY_IDENTITY`` activent la validation (identité de
    l'hôte incluse pour le second). Retourne ``(options_ssl, désactivé)``.
    """
    normalized_mode = (mode or "").strip().upper()
    if normalized_mode in {"DISABLED", "DISABLE"}:
        return {}, True
    if not normalized_mode and not (ca or cert or key):
        return {}, False

    options: dict[str, Any] = {}
    if ca:
        options["ca"] = ca
    if cert:
        options["cert"] = cert
    if key:
        options["key"] = key

    if normalized_mode in {"VERIFY_CA", "VERIFY_IDENTITY"}:
        if not ca:
            # Sans fichier de CA explicite, valider avec le magasin système.
            options["verify_mode"] = "required"
        options["check_hostname"] = (
            normalized_mode == "VERIFY_IDENTITY" if check_hostname is None else check_hostname
        )
    else:
        # REQUIRED / PREFERRED : connexion chiffrée, certificat non validé
        # (les certificats auto-signés des conteneurs MySQL restent utilisables).
        options.setdefault("check_hostname", False)
    return options, False


def prepare_database_url(url: str) -> tuple[str | URL, dict[str, Any]]:
    """Prépare une URL MySQL pour SQLAlchemy + PyMySQL.

    - force le pilote ``mysql+pymysql`` (MySQLdb n'est pas installé) ;
    - extrait les options TLS ``ssl-mode``/``ssl-ca`` de la chaîne de requête,
      que PyMySQL ne comprend pas, et les convertit en ``connect_args`` ;
    - applique des délais raisonnables et un ``charset`` utf8mb4.

    Les autres moteurs (PostgreSQL, SQLite) sont retournés inchangés avec des
    ``connect_args`` vides. Pour MySQL, la valeur retournée est un objet
    ``sqlalchemy.engine.URL`` : il conserve le mot de passe décodé sans le
    ré-exposer dans une chaîne (un mot de passe contenant ``@`` casserait la
    réécriture textuelle de l'URL).
    """
    if not url:
        return url, {}
    try:
        parsed = make_url(url)
    except Exception:
        return url, {}

    if parsed.get_backend_name() not in {"mysql", "mariadb"}:
        return url, {}

    if not parsed.drivername.endswith("+pymysql"):
        parsed = parsed.set(drivername="mysql+pymysql")

    values = {key.lower(): value for key, value in parsed.query.items()}
    hostname_raw = values.get("ssl-check-hostname") or values.get("ssl_check_hostname")
    ssl_options, ssl_disabled = _mysql_ssl_options(
        mode=values.get("ssl-mode") or values.get("ssl_mode"),
        ca=values.get("ssl-ca") or values.get("ssl_ca"),
        cert=values.get("ssl-cert") or values.get("ssl_cert"),
        key=values.get("ssl-key") or values.get("ssl_key"),
        check_hostname=None if hostname_raw is None else parse_bool(hostname_raw, True),
    )

    connect_args: dict[str, Any] = {
        "charset": values.get("charset") or "utf8mb4",
        "program_name": "gestimmo-api",
    }
    for option, default in (("connect_timeout", 10), ("read_timeout", 60), ("write_timeout", 60)):
        try:
            connect_args[option] = int(values.get(option) or default)
        except ValueError:
            connect_args[option] = default
    if ssl_options:
        connect_args["ssl"] = ssl_options
    if ssl_disabled:
        connect_args["ssl_disabled"] = True

    remaining_keys = [key for key in parsed.query if key.lower() in _MYSQL_TLS_QUERY_KEYS]
    if remaining_keys:
        parsed = parsed.difference_update_query(remaining_keys)
    return parsed, connect_args


database_url, database_connect_args = prepare_database_url(settings.DATABASE_URL)
database_backend = (
    database_url.get_backend_name()
    if hasattr(database_url, "get_backend_name")
    else urllib.parse.urlsplit(str(database_url)).scheme
)

engine_kwargs: dict[str, Any] = {
    "pool_pre_ping": True,
    "echo": settings.DEBUG,
}
if database_backend == "sqlite":
    engine_kwargs["connect_args"] = {"check_same_thread": False}
elif database_connect_args:
    engine_kwargs["connect_args"] = database_connect_args
if database_backend in {"mysql", "mariadb"}:
    # MySQL ferme les connexions inactives (wait_timeout, souvent 300 s) :
    # renouveler le pool avant que le serveur ne les coupe.
    engine_kwargs["pool_recycle"] = 280

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _create_index_if_missing(connection, table: str, index_name: str,
                             columns: str, *, unique: bool = False) -> None:
    """Crée un index si son nom n'existe pas déjà.

    ``CREATE INDEX IF NOT EXISTS`` n'existe qu'en PostgreSQL et SQLite :
    MySQL/MariaDB rejettent la syntaxe. On interroge donc l'inspecteur, ce qui
    fonctionne sur les trois moteurs.
    """
    inspector = inspect(connection)
    if table not in inspector.get_table_names():
        return
    existing = {index.get("name") for index in inspector.get_indexes(table)}
    if index_name in existing:
        return
    prefix = "CREATE UNIQUE INDEX" if unique else "CREATE INDEX"
    connection.execute(text(f"{prefix} {index_name} ON {table} ({columns})"))


def _add_column_if_missing(connection, table: str, column_name: str,
                           column_type: str, nullable: bool = True,
                           index: bool = False, default: str | None = None):
    """Ajoute une colonne à une table existante si elle est absente."""
    inspector = inspect(connection)
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
        _create_index_if_missing(connection, table, f"ix_{table}_{column_name}", column_name)


def _ensure_module_12_13_columns():
    """Migration additive minimale pour la table historique ``properties``.

    ``create_all`` crée toutes les nouvelles tables mais n'ajoute pas de
    colonnes à une table existante. Ces trois colonnes nullable sont sûres sur
    PostgreSQL, MySQL et SQLite et rendent le déploiement des modules 12/13
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
            _create_index_if_missing(connection, "properties", f"ix_properties_{name}", name)


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
                _create_index_if_missing(
                    connection, table, f"ix_{table}_secure_id", "secure_id", unique=True
                )
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
    from app.models import subscription  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_module_12_13_columns()
    _ensure_property_completion_columns()
    _ensure_mandate_signature_columns()
    _ensure_insurance_scope_columns()
    _backfill_secure_ids()

    # Amorçage idempotent des profils prédéfinis et des comptes historiques.
    from app.services.admin_security_service import bootstrap_security

    bootstrap_security()
