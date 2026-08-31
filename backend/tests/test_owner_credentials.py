"""Tests d'intégration de la génération de connexion propriétaire.

Crée un propriétaire existant puis génère un compte de connexion lié, vérifie
le login et l'accès au portail propriétaire.
"""

import os
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-owner-credentials-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class OwnerCredentialsTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.client = TestClient(app)

        # bootstrap des profils + comptes historiques
        from app.services.admin_security_service import bootstrap_security
        bootstrap_security()

        login = self.client.post(
            "/api/auth/login",
            json={"email": "admin@immogest.com", "password": "Admin@2024!"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.admin_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def test_generate_credentials_for_existing_owner(self):
        # 1. Créer un propriétaire existant
        resp = self.client.post(
            "/api/owners/",
            json={
                "owner_type": "individual",
                "first_name": "Jean",
                "last_name": "Dupont",
                "email": "jean.dupont@email.fr",
                "city": "Paris",
            },
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        owner_id = resp.json()["id"]

        # 2. Générer une connexion pour ce propriétaire
        resp = self.client.post(
            f"/api/owners/{owner_id}/credentials",
            json={},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        payload = resp.json()
        self.assertEqual(payload["email"], "jean.dupont@email.fr")
        self.assertTrue(payload["must_change_password"])
        self.assertIn("password", payload)
        password = payload["password"]

        # 3. L'idempotence : sans reset, la deuxième génération est refusée
        resp = self.client.post(
            f"/api/owners/{owner_id}/credentials",
            json={},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 409, resp.text)

        # 4. Le propriétaire se connecte avec ses identifiants
        resp = self.client.post(
            "/api/auth/login",
            json={"email": "jean.dupont@email.fr", "password": password},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        login_payload = resp.json()
        owner_token = login_payload["access_token"]
        database_id = login_payload["user"]["database_id"]

        # 5. Le mot de passe temporaire impose un renouvellement
        resp = self.client.get(
            "/owner-portal/dashboard",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        self.assertEqual(resp.status_code, 403, resp.text)

        # 6. Il renouvelle son mot de passe puis accède à son portail
        resp = self.client.put(
            f"/api/admin/users/{database_id}/password",
            json={"current_password": password, "new_password": "NouveauMot2Passe!"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        resp = self.client.get(
            "/owner-portal/dashboard",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["owner_id"], owner_id)

        # 7. Réinitialisation du mot de passe (reset_existing)
        resp = self.client.post(
            f"/api/owners/{owner_id}/credentials",
            json={"reset_existing": True},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        new_password = resp.json()["password"]
        self.assertNotEqual(new_password, password)

    def test_generate_credentials_requires_email(self):
        resp = self.client.post(
            "/api/owners/",
            json={"owner_type": "individual", "first_name": "Sans", "last_name": "Email"},
            headers=self.admin_headers,
        )
        owner_id = resp.json()["id"]
        resp = self.client.post(
            f"/api/owners/{owner_id}/credentials",
            json={},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 400, resp.text)

        # Avec un email fourni dans la requête, cela fonctionne
        resp = self.client.post(
            f"/api/owners/{owner_id}/credentials",
            json={"email": "sans.email@example.fr"},
            headers=self.admin_headers,
        )
        self.assertEqual(resp.status_code, 201, resp.text)


if __name__ == "__main__":
    unittest.main()
