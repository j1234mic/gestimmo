"""Compatibilité MySQL : préparation d'URL, options TLS et schéma SQL.

Ces tests ne nécessitent aucun serveur MySQL : ils vérifient la traduction des
URL fournies par les hébergeurs (Aiven, HeatWave…) et compilent le schéma
SQLAlchemy avec le dialecte MySQL, qui rejette les constructions acceptées par
PostgreSQL/SQLite (index trop longs, ``CREATE INDEX IF NOT EXISTS``…).
"""

import os
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-mysql-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DIR}/tests.db")
os.environ.setdefault("DEBUG", "false")

from sqlalchemy import String, Text, UniqueConstraint, create_engine, inspect, text  # noqa: E402
from sqlalchemy.dialects import mysql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from app.database import Base, _create_index_if_missing, prepare_database_url  # noqa: E402

MYSQL_MAX_KEY_BYTES = 3072  # utf8mb4 : 4 octets par caractère


def _load_all_models():
    """Importe tous les modules de modèles, comme ``init_db``."""
    from app.models import (  # noqa: F401
        accounting,
        admin_security,
        ai_automation,
        communication,
        condo,
        crm,
        extension,
        finance,
        ged,
        geolocation,
        insurance,
        integration,
        lease_contract,
        maintenance,
        message,
        notification,
        owner,
        property,
        report,
        reporting,
        subscription,
        tenant,
    )


def _rendered(url):
    """Chaîne d'URL lisible pour les assertions (sans masquer le mot de passe)."""
    if hasattr(url, "render_as_string"):
        return url.render_as_string(hide_password=False)
    return url


def _key_bytes(column, index=None):
    """Taille maximale en octets d'une colonne dans une clé d'index MySQL.

    Retourne ``None`` pour un type sans longueur bornée (TEXT/BLOB), qui exige
    un index préfixe.
    """
    column_type = column.type
    if isinstance(column_type, Text):
        return None
    if isinstance(column_type, String):
        length = column_type.length or 255
        if index is not None:
            prefix = index.dialect_options["mysql"].get("length")
            if isinstance(prefix, int):
                length = min(length, prefix)
            elif isinstance(prefix, dict) and column.name in prefix:
                length = min(length, int(prefix[column.name]))
        return length * 4
    return 4


class PrepareDatabaseUrlTest(unittest.TestCase):
    def test_mysql_scheme_uses_pymysql(self):
        url, connect_args = prepare_database_url("mysql://u:p@localhost:3306/immo_db")
        self.assertEqual(_rendered(url), "mysql+pymysql://u:p@localhost:3306/immo_db")
        self.assertEqual(connect_args["charset"], "utf8mb4")
        self.assertEqual(connect_args["connect_timeout"], 10)
        self.assertNotIn("ssl", connect_args)

    def test_mariadb_scheme_uses_pymysql(self):
        url, _ = prepare_database_url("mariadb://u:p@db:3306/immo")
        self.assertEqual(_rendered(url), "mysql+pymysql://u:p@db:3306/immo")

    def test_mysqldb_driver_is_replaced(self):
        url, _ = prepare_database_url("mysql+mysqldb://u:p@db:3306/immo")
        self.assertEqual(url.drivername, "mysql+pymysql")

    def test_ssl_mode_required_becomes_pymysql_ssl(self):
        url, connect_args = prepare_database_url(
            "mysql://avnadmin:secret@mysql-1.aivencloud.com:12345/defaultdb"
            "?ssl-mode=REQUIRED&charset=utf8mb4"
        )
        rendered = _rendered(url)
        self.assertNotIn("ssl-mode", rendered)
        self.assertNotIn("ssl_mode", rendered)
        self.assertIn("charset=utf8mb4", rendered)
        self.assertEqual(connect_args["ssl"], {"check_hostname": False})

    def test_ssl_mode_verify_ca_uses_ca(self):
        _, connect_args = prepare_database_url(
            "mysql://u:p@host:3306/db?ssl-mode=VERIFY_CA&ssl-ca=/etc/ssl/aiven-ca.pem"
        )
        self.assertEqual(connect_args["ssl"]["ca"], "/etc/ssl/aiven-ca.pem")
        self.assertFalse(connect_args["ssl"]["check_hostname"])

    def test_ssl_mode_verify_identity_checks_hostname(self):
        _, connect_args = prepare_database_url(
            "mysql://u:p@host:3306/db?ssl-mode=VERIFY_IDENTITY&ssl-ca=/tmp/ca.pem"
        )
        self.assertTrue(connect_args["ssl"]["check_hostname"])

    def test_ssl_mode_verify_ca_without_ca_uses_system_store(self):
        _, connect_args = prepare_database_url("mysql://u:p@host:3306/db?ssl-mode=VERIFY_CA")
        self.assertEqual(connect_args["ssl"]["verify_mode"], "required")

    def test_ssl_mode_disabled(self):
        _, connect_args = prepare_database_url("mysql://u:p@host:3306/db?ssl-mode=DISABLED")
        self.assertTrue(connect_args["ssl_disabled"])
        self.assertNotIn("ssl", connect_args)

    def test_encoded_password_is_preserved(self):
        url, _ = prepare_database_url("mysql://u:p%40ss%3Aword@host:3306/db")
        self.assertEqual(url.password, "p@ss:word")

    def test_password_with_at_sign_survives_ssl_cleanup(self):
        # Le mot de passe encodé doit rester intact : la valeur retournée est
        # un objet URL, jamais resérialisé puis réanalysé.
        url, connect_args = prepare_database_url(
            "mysql://avnadmin:p%40ss@host:12345/defaultdb?ssl-mode=REQUIRED"
        )
        self.assertEqual(url.password, "p@ss")
        self.assertEqual(url.host, "host")
        self.assertEqual(connect_args["ssl"], {"check_hostname": False})

        engine = create_engine(url)
        try:
            self.assertEqual(engine.url.password, "p@ss")
            self.assertEqual(engine.url.drivername, "mysql+pymysql")
        finally:
            engine.dispose()

    def test_non_mysql_urls_are_untouched(self):
        for url in (
            "postgresql://u:p@localhost:5432/immo_db",
            f"sqlite:///{TEST_DIR}/tests.db",
            "",
        ):
            prepared, connect_args = prepare_database_url(url)
            self.assertEqual(_rendered(prepared), url)
            self.assertEqual(connect_args, {})

    def test_query_options_are_honoured(self):
        _, connect_args = prepare_database_url(
            "mysql://u:p@host/db?charset=latin1&connect_timeout=3"
        )
        self.assertEqual(connect_args["charset"], "latin1")
        self.assertEqual(connect_args["connect_timeout"], 3)


class MySQLSchemaCompilationTest(unittest.TestCase):
    """Le schéma complet doit être créable sur MySQL 8."""

    @classmethod
    def setUpClass(cls):
        _load_all_models()
        cls.dialect = mysql.dialect()

    def test_every_table_compiles_for_mysql(self):
        self.assertGreaterEqual(len(Base.metadata.sorted_tables), 200)
        for table in Base.metadata.sorted_tables:
            with self.subTest(table=table.name):
                CreateTable(table).compile(dialect=self.dialect)

    def test_every_index_compiles_and_fits_mysql_key_limit(self):
        for table in Base.metadata.tables.values():
            for index in table.indexes:
                with self.subTest(table=table.name, index=index.name):
                    CreateIndex(index).compile(dialect=self.dialect)
                    total = 0
                    for column in index.columns:
                        size = _key_bytes(column, index)
                        self.assertIsNotNone(
                            size,
                            f"{table.name}.{index.name} indexe un TEXT : "
                            "ajoutez un index préfixe (mysql_length)",
                        )
                        total += size
                    self.assertLessEqual(
                        total,
                        MYSQL_MAX_KEY_BYTES,
                        f"{table.name}.{index.name} dépasse la limite MySQL utf8mb4",
                    )

    def test_unique_constraints_fit_mysql_key_limit(self):
        for table in Base.metadata.tables.values():
            for constraint in table.constraints:
                if not isinstance(constraint, UniqueConstraint):
                    continue
                total = 0
                for column in constraint.columns:
                    size = _key_bytes(column)
                    self.assertIsNotNone(size, f"{table.name}: UNIQUE sur TEXT")
                    total += size
                self.assertLessEqual(total, MYSQL_MAX_KEY_BYTES, f"{table.name}: UNIQUE trop long")

    def test_long_question_index_uses_prefix_on_mysql(self):
        table = Base.metadata.tables["ai_chat_knowledge"]
        index = next(ix for ix in table.indexes if ix.name == "ix_ai_chat_knowledge_normalized_question")
        self.assertEqual(index.dialect_options["mysql"]["length"], 191)


class PortableIndexCreationTest(unittest.TestCase):
    """``_create_index_if_missing`` doit être idempotent et portable."""

    def setUp(self):
        self.engine = create_engine(f"sqlite:///{TEST_DIR}/indexes.db")
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE IF NOT EXISTS demo (id INTEGER PRIMARY KEY, name VARCHAR(20))"))

    def tearDown(self):
        self.engine.dispose()

    def test_index_is_created_once(self):
        with self.engine.begin() as connection:
            _create_index_if_missing(connection, "demo", "ix_demo_name", "name")
            _create_index_if_missing(connection, "demo", "ix_demo_name", "name")
        names = {ix["name"] for ix in inspect(self.engine).get_indexes("demo")}
        self.assertIn("ix_demo_name", names)

    def test_unique_index_creation(self):
        with self.engine.begin() as connection:
            _create_index_if_missing(
                connection, "demo", "uq_demo_name", "name", unique=True
            )
        indexes = {ix["name"]: ix for ix in inspect(self.engine).get_indexes("demo")}
        self.assertTrue(indexes["uq_demo_name"]["unique"])

    def test_missing_table_is_ignored(self):
        with self.engine.begin() as connection:
            _create_index_if_missing(connection, "absent", "ix_absent_id", "id")

    def test_generated_statement_has_no_if_not_exists(self):
        # MySQL n'accepte pas CREATE INDEX IF NOT EXISTS : on vérifie que le
        # dialecte MySQL compile bien un index simple (l'inspecteur évite la
        # syntaxe non portable).
        table = Base.metadata.tables["ai_chat_knowledge"]
        index = next(ix for ix in table.indexes if ix.name.startswith("ix_ai_chat_knowledge_actor"))
        statement = str(CreateIndex(index).compile(dialect=mysql.dialect()))
        self.assertNotIn("IF NOT EXISTS", statement.upper())


if __name__ == "__main__":
    unittest.main()
