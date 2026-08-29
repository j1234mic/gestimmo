"""Tests end-to-end — API HTTP (routeurs hexagonaux v2).

Scénario complet navigué via FastAPI ``TestClient`` : authentification,
création d'un bien et d'un propriétaire, consultation par id entier ET par
secure_id, mise à jour, liste filtrée, puis suppression. Aucune logique
métier n'est dupliquée : on valide uniquement le câblage hexagonal de bout
en bout.
"""

import os
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-hex-e2e-")
os.environ["SECURE_ID_KEY"] = "QKv_PYSNfbjeDsnZjKuISHB-uSnplMhWIjjn-JOfJwo="
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["BACKUP_DIR"] = f"{TEST_DIR}/backups"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["ENVIRONMENT"] = "development"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class HexagonalE2ETest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        from app.database import _backfill_secure_ids, init_db
        init_db()

    def setUp(self):
        self.context = TestClient(app)
        self.client = self.context.__enter__()
        login = self.client.post(
            "/api/auth/login", json={"email": "admin@immogest.com", "password": "Admin@2024!"}
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def _create_property(self) -> dict:
        resp = self.client.post(
            "/api/v2/properties/",
            headers=self.headers,
            json={
                "type": "apartment", "title": "E2E Appartement",
                "address": "12 rue de la Paix", "postal_code": "75002",
                "city": "Paris", "rent_price": 1100,
            },
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def _create_owner(self) -> dict:
        resp = self.client.post(
            "/api/v2/owners/",
            headers=self.headers,
            json={"owner_type": "individual", "first_name": "E2E", "last_name": "Proprio", "city": "Nantes"},
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def test_property_full_lifecycle(self):
        prop = self._create_property()
        # La réponse expose bien l'id entier ET le secure_id chiffré.
        self.assertIn("id", prop)
        self.assertIn("secure_id", prop)
        self.assertIsNotNone(prop["secure_id"])

        pid = prop["id"]
        sid = prop["secure_id"]

        # Consultation par id entier
        by_int = self.client.get(f"/api/v2/properties/{pid}", headers=self.headers)
        self.assertEqual(by_int.status_code, 200, by_int.text)
        self.assertEqual(by_int.json()["id"], pid)

        # Consultation par secure_id (chaîne) — sécurisation de l'URL
        by_secure = self.client.get(f"/api/v2/properties/{sid}", headers=self.headers)
        self.assertEqual(by_secure.status_code, 200, by_secure.text)
        self.assertEqual(by_secure.json()["secure_id"], sid)
        self.assertEqual(by_secure.json()["id"], pid)

        # Mise à jour
        upd = self.client.put(
            f"/api/v2/properties/{pid}", headers=self.headers,
            json={"title": "E2E Appartement rénové", "rent_price": 1200},
        )
        self.assertEqual(upd.status_code, 200, upd.text)
        self.assertEqual(upd.json()["title"], "E2E Appartement rénové")
        self.assertEqual(upd.json()["rent_price"], 1200)

        # Liste filtrée (recherche textuelle)
        listing = self.client.get("/api/v2/properties/?search=E2E", headers=self.headers)
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertGreaterEqual(listing.json()["total"], 1)

        # Suppression (soft delete)
        dele = self.client.delete(f"/api/v2/properties/{pid}", headers=self.headers)
        self.assertEqual(dele.status_code, 200, dele.text)
        gone = self.client.get(f"/api/v2/properties/{pid}", headers=self.headers)
        self.assertEqual(gone.status_code, 404)

    def test_owner_full_lifecycle(self):
        owner = self._create_owner()
        self.assertIn("secure_id", owner)
        self.assertIsNotNone(owner["secure_id"])

        oid = owner["id"]
        sid = owner["secure_id"]

        by_int = self.client.get(f"/api/v2/owners/{oid}", headers=self.headers)
        self.assertEqual(by_int.status_code, 200, by_int.text)
        by_secure = self.client.get(f"/api/v2/owners/{sid}", headers=self.headers)
        self.assertEqual(by_secure.status_code, 200, by_secure.text)
        self.assertEqual(by_secure.json()["id"], oid)

        upd = self.client.put(
            f"/api/v2/owners/{oid}", headers=self.headers, json={"city": "Bordeaux"})
        self.assertEqual(upd.status_code, 200, upd.text)
        self.assertEqual(upd.json()["city"], "Bordeaux")

        listing = self.client.get("/api/v2/owners/", headers=self.headers)
        self.assertEqual(listing.status_code, 200, listing.text)

    def test_legacy_endpoints_still_work(self):
        # Non-régression : l'ancienne route fonctionne toujours.
        resp = self.client.post(
            "/api/properties/",
            headers=self.headers,
            json={"type": "apartment", "title": "Legacy", "address": "1 rue",
                  "postal_code": "75001", "city": "Paris", "rent_price": 800},
        )
        self.assertEqual(resp.status_code, 201, resp.text)


if __name__ == "__main__":
    unittest.main()
