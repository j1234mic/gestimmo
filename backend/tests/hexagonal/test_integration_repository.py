"""Tests d'intégration — adaptateurs SQLAlchemy (repository + mappers).

Exécute le vrai ``SqlAlchemyPropertyRepository`` / ``SqlAlchemyOwnerRepository``
sur SQLite, en passant par les mappers et le chiffrement des ids. Aucun
protocole HTTP n'est impliqué.
"""

import os
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-hex-int-")
os.environ["SECURE_ID_KEY"] = "QKv_PYSNfbjeDsnZjKuISHB-uSnplMhWIjjn-JOfJwo="
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"

from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.hexagon.domain.owner import Owner, OwnerType  # noqa: E402
from app.hexagon.domain.property import Property, PropertyStatus, PropertyType  # noqa: E402
from app.hexagon.infrastructure.persistence.repositories import (  # noqa: E402
    SqlAlchemyOwnerRepository,
    SqlAlchemyPropertyRepository,
)
from app.hexagon.infrastructure.security.id_cipher import decrypt_id  # noqa: E402


class RepositoryIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        # Backfill des secure_id (comportement de production).
        from app.database import _backfill_secure_ids
        _backfill_secure_ids()

    def setUp(self):
        self.db: Session = SessionLocal()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def test_property_repository_persists_and_resolves_secure_id(self):
        repo = SqlAlchemyPropertyRepository(self.db)
        entity = repo.save(Property(
            id=None, reference="PROP-TEST1", type=PropertyType.APARTMENT, status=PropertyStatus.AVAILABLE,
            title="Appart test", address="1 rue", postal_code="75001", city="Paris", rent_price=900))
        self.assertIsNotNone(entity.id)
        self.assertIsNotNone(entity.secure_id)
        # Le secure_id chiffre bien l'id entier.
        self.assertEqual(decrypt_id(entity.secure_id), entity.id)

        # Résolution par secure_id (chaîne) comme en production.
        resolved = repo.find_by_id(entity.secure_id)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, entity.id)

        # Résolution par id entier (rétro-compatibilité).
        resolved_int = repo.find_by_id(entity.id)
        self.assertEqual(resolved_int.secure_id, entity.secure_id)

    def test_property_repository_update_keeps_secure_id(self):
        repo = SqlAlchemyPropertyRepository(self.db)
        entity = repo.save(Property(
            id=None, reference="PROP-TEST2", type=PropertyType.HOUSE, status=PropertyStatus.AVAILABLE,
            title="Maison", address="2 rue", postal_code="69001", city="Lyon"))
        sid = entity.secure_id
        entity.title = "Maison rénovée"
        updated = repo.save(entity)
        self.assertEqual(updated.secure_id, sid)
        self.assertEqual(updated.title, "Maison rénovée")

    def test_property_repository_soft_delete(self):
        repo = SqlAlchemyPropertyRepository(self.db)
        entity = repo.save(Property(
            id=None, reference="PROP-TEST3", type=PropertyType.STUDIO, status=PropertyStatus.AVAILABLE,
            title="Studio", address="3 rue", postal_code="13001", city="Marseille"))
        deleted = repo.delete(entity.id)
        self.assertIsNotNone(deleted)
        self.assertIsNone(repo.find_by_id(entity.id))

    def test_property_statistics(self):
        repo = SqlAlchemyPropertyRepository(self.db)
        stats = repo.statistics()
        self.assertGreaterEqual(stats.total_properties, 0)
        self.assertIsInstance(stats.by_type, dict)

    def test_owner_repository_persists_and_resolves_secure_id(self):
        repo = SqlAlchemyOwnerRepository(self.db)
        entity = repo.save(Owner(
            id=None, reference="OWN-TEST1", owner_type=OwnerType.INDIVIDUAL,
            first_name="Jean", last_name="Dupont", city="Lyon"))
        self.assertIsNotNone(entity.secure_id)
        self.assertEqual(decrypt_id(entity.secure_id), entity.id)
        resolved = repo.find_by_id(entity.secure_id)
        self.assertEqual(resolved.id, entity.id)


if __name__ == "__main__":
    unittest.main()
