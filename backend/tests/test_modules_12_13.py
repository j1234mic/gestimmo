"""Tests d'intégration des modules 12 (administration) et 13 (cartographie)."""

import os
import tempfile
import unittest
from datetime import datetime, timedelta

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-mod12-13-")
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


class AdministrationGeolocationTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.context = TestClient(app)
        self.client = self.context.__enter__()
        login = self.client.post(
            "/api/auth/login", json={"email": "admin@immogest.com", "password": "Admin@2024!"}
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def _organization(self):
        org = self.client.post(
            "/api/admin/organizations",
            headers=self.headers,
            json={"name": "GestImmo France", "city": "Paris", "fiscal_settings": {"vat": 20}},
        )
        self.assertEqual(org.status_code, 201, org.text)
        agency = self.client.post(
            "/api/admin/agencies",
            headers=self.headers,
            json={"organization_id": org.json()["id"], "code": "PAR", "name": "Agence Paris"},
        )
        self.assertEqual(agency.status_code, 201, agency.text)
        return org.json()["id"], agency.json()["id"]

    def _property(self, organization_id, agency_id, title="Bien Paris", latitude=48.8566, longitude=2.3522):
        response = self.client.post(
            "/api/properties/",
            headers=self.headers,
            json={
                "type": "apartment", "title": title, "address": "1 rue de Rivoli",
                "postal_code": "75001", "city": "Paris", "latitude": latitude,
                "longitude": longitude, "entity_id": organization_id, "agency_id": agency_id,
                "rent_price": 1200,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_users_custom_roles_scopes_and_isolation(self):
        organization_id, agency_id = self._organization()
        role = self.client.post(
            "/api/admin/roles",
            headers=self.headers,
            json={
                "name": "Cartographe lecture",
                "organization_id": organization_id,
                "permissions": [{"module": "geolocation", "actions": ["read"], "scope_type": "assigned"}],
            },
        )
        self.assertEqual(role.status_code, 201, role.text)
        user = self.client.post(
            "/api/admin/users",
            headers=self.headers,
            json={
                "email": "carte@example.fr", "full_name": "Camille Carte", "password": "CarteTest@2026",
                "roles": [{"role_id": role.json()["id"], "organization_id": organization_id, "agency_id": agency_id}],
                "scopes": [{"organization_id": organization_id, "agency_id": agency_id, "is_default": True}],
            },
        )
        self.assertEqual(user.status_code, 201, user.text)
        login = self.client.post("/api/auth/login", json={"email": "carte@example.fr", "password": "CarteTest@2026"})
        self.assertEqual(login.status_code, 200, login.text)
        scoped = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # Lecture cartographique permise, écriture POI refusée et module biens refusé.
        self.assertEqual(self.client.get("/api/geolocation/map/properties", headers=scoped).status_code, 200)
        denied = self.client.post(
            "/api/geolocation/points-of-interest", headers=scoped,
            json={"name": "Métro", "category": "transport", "latitude": 48.85, "longitude": 2.35},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.get("/api/properties/", headers=scoped).status_code, 403)

        history = self.client.get(f"/api/admin/users/{user.json()['id']}/login-history", headers=self.headers)
        self.assertEqual(history.status_code, 200)
        self.assertGreaterEqual(history.json()["count"], 1)
        deactivated = self.client.post(
            f"/api/admin/users/{user.json()['id']}/deactivate", headers=self.headers,
            json={"reason": "Départ de la société"},
        )
        self.assertEqual(deactivated.status_code, 200)
        self.assertEqual(
            self.client.post("/api/auth/login", json={"email": "carte@example.fr", "password": "CarteTest@2026"}).status_code,
            403,
        )

    def test_security_policy_lockout_and_email_2fa(self):
        policy = self.client.put(
            "/api/admin/security-policy", headers=self.headers,
            json={"max_login_attempts": 2, "lockout_minutes": 10},
        )
        self.assertEqual(policy.status_code, 200)
        for _ in range(2):
            bad = self.client.post(
                "/api/auth/login", json={"email": "lecteur@immogest.com", "password": "incorrect"}
            )
            self.assertEqual(bad.status_code, 401)
        locked = self.client.post(
            "/api/auth/login", json={"email": "lecteur@immogest.com", "password": "Viewer@2024!"}
        )
        self.assertEqual(locked.status_code, 423)

        setup = self.client.post("/api/auth/2fa/setup", headers=self.headers, json={"method": "email"})
        self.assertEqual(setup.status_code, 200, setup.text)
        self.assertIn("debug_code", setup.json())
        confirm = self.client.post(
            "/api/auth/2fa/confirm", headers=self.headers,
            json={"challenge_token": setup.json()["challenge_token"], "code": setup.json()["debug_code"]},
        )
        self.assertEqual(confirm.status_code, 200, confirm.text)
        login = self.client.post(
            "/api/auth/login", json={"email": "admin@immogest.com", "password": "Admin@2024!"}
        )
        self.assertTrue(login.json()["two_factor_required"])
        verified = self.client.post(
            "/api/auth/2fa/verify",
            json={"challenge_token": login.json()["challenge_token"], "code": login.json()["debug_code"]},
        )
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertIn("access_token", verified.json())

    def test_entities_settings_audit_backup_and_gdpr(self):
        organization_id, _ = self._organization()
        settings = self.client.put(
            "/api/admin/settings/general", headers=self.headers,
            json={
                "organization_id": organization_id, "currency": "eur", "language": "fr",
                "date_format": "DD/MM/YYYY", "timezone": "Europe/Paris",
                "numbering": {"invoice": "FAC-{YYYY}-{SEQ:5}"},
            },
        )
        self.assertEqual(settings.status_code, 200)
        self.assertEqual(settings.json()["currency"], "EUR")
        numbering = self.client.put(
            "/api/admin/settings/numbering", headers=self.headers,
            json={
                "organization_id": organization_id, "document_type": "invoice",
                "period": "2026", "prefix": "FAC-{YYYY}-", "next_value": 1, "padding": 4,
            },
        )
        self.assertEqual(numbering.status_code, 200, numbering.text)
        first_number = self.client.post(
            "/api/admin/settings/numbering/next", headers=self.headers,
            params={"organization_id": organization_id, "document_type": "invoice", "period": "2026"},
        )
        self.assertEqual(first_number.json()["number"], "FAC-2026-0001")
        index = self.client.post(
            "/api/admin/settings/reference-indices", headers=self.headers,
            json={"organization_id": organization_id, "code": "IRL", "period": "2026-Q1", "value": "145.47"},
        )
        self.assertEqual(index.status_code, 201)

        consent = self.client.post(
            "/api/admin/gdpr/consents", headers=self.headers,
            json={
                "subject_type": "user", "subject_id": "1", "purpose": "prospection",
                "granted": True, "legal_text_version": "2026-01",
            },
        )
        self.assertEqual(consent.status_code, 201)
        policy = self.client.post(
            "/api/admin/gdpr/privacy-policies", headers=self.headers,
            json={
                "organization_id": organization_id, "version": "1.0", "title": "Vie privée",
                "content": "Politique de confidentialité complète de GestImmo.", "publish": True,
            },
        )
        self.assertEqual(policy.status_code, 201)
        self.assertEqual(
            self.client.get("/api/privacy/current", params={"organization_id": organization_id}).status_code, 200
        )
        portable = self.client.get("/api/admin/gdpr/portability/user/1", headers=self.headers)
        self.assertEqual(portable.status_code, 200)
        self.assertIn("attachment", portable.headers["content-disposition"])

        backup = self.client.post("/api/admin/backups", headers=self.headers)
        self.assertEqual(backup.status_code, 201, backup.text)
        self.assertEqual(backup.json()["status"], "completed")
        self.assertGreater(backup.json()["size_bytes"], 0)
        audit = self.client.get("/api/admin/audit-logs", headers=self.headers)
        self.assertEqual(audit.status_code, 200)
        self.assertGreater(audit.json()["total"], 0)
        export = self.client.get("/api/admin/audit-logs/export", headers=self.headers)
        self.assertEqual(export.status_code, 200)
        self.assertIn("text/csv", export.headers["content-type"])

    def test_map_pois_score_zones_and_statistics(self):
        organization_id, agency_id = self._organization()
        property_id = self._property(organization_id, agency_id)
        pois = [
            ("Métro Louvre", "transport", 48.8570, 2.3510),
            ("École du Centre", "school", 48.8580, 2.3540),
            ("Commerce Rivoli", "shop", 48.8568, 2.3530),
            ("Hôpital", "hospital", 48.86, 2.35),
            ("Jardin", "park", 48.855, 2.349),
        ]
        batch = self.client.post(
            "/api/geolocation/points-of-interest/batch", headers=self.headers,
            json=[
                {"name": name, "category": category, "latitude": lat, "longitude": lon, "entity_id": organization_id}
                for name, category, lat, lon in pois
            ],
        )
        self.assertEqual(batch.status_code, 201, batch.text)
        map_response = self.client.get(
            "/api/geolocation/map/properties", headers=self.headers,
            params={"city": "Paris", "zoom": 10, "cluster": True},
        )
        self.assertEqual(map_response.status_code, 200)
        self.assertEqual(map_response.json()["count"], 1)
        self.assertEqual(map_response.json()["type"], "FeatureCollection")
        nearby = self.client.get(
            f"/api/geolocation/properties/{property_id}/location", headers=self.headers,
            params={"radius_m": 3000},
        )
        self.assertEqual(len(nearby.json()["points_of_interest"]), 5)
        score = self.client.post(
            f"/api/geolocation/properties/{property_id}/location-score", headers=self.headers
        )
        self.assertEqual(score.status_code, 200)
        self.assertGreater(score.json()["score"], 70)

        zone = self.client.post(
            "/api/geolocation/zones", headers=self.headers,
            json={
                "name": "Paris Centre", "entity_id": organization_id, "agency_id": agency_id,
                "polygon": {"type": "Polygon", "coordinates": [[[2.30, 48.80], [2.40, 48.80], [2.40, 48.90], [2.30, 48.90], [2.30, 48.80]]]},
            },
        )
        self.assertEqual(zone.status_code, 201, zone.text)
        assigned = self.client.post(
            "/api/geolocation/zones/assign-properties", headers=self.headers,
            params={"entity_id": organization_id},
        )
        self.assertEqual(assigned.json()["assigned"], 1)
        statistics = self.client.get(
            f"/api/geolocation/zones/{zone.json()['id']}/statistics", headers=self.headers
        )
        self.assertEqual(statistics.json()["property_count"], 1)
        self.assertEqual(statistics.json()["total_monthly_rent"], 1200)

    def test_visits_travel_times_and_optimized_route(self):
        organization_id, agency_id = self._organization()
        first_id = self._property(organization_id, agency_id, "Bien 1", 48.8566, 2.3522)
        second_id = self._property(organization_id, agency_id, "Bien 2", 48.8666, 2.3622)
        start = datetime.utcnow() + timedelta(hours=2)
        visit_ids = []
        for index, property_id in enumerate([first_id, second_id]):
            response = self.client.post(
                "/api/geolocation/visits", headers=self.headers,
                json={"property_id": property_id, "starts_at": (start + timedelta(hours=index)).isoformat(), "duration_minutes": 30},
            )
            self.assertEqual(response.status_code, 201, response.text)
            visit_ids.append(response.json()["id"])
        travel = self.client.post(
            f"/api/geolocation/properties/{first_id}/travel-time", headers=self.headers,
            json={"destination": {"latitude": 48.8666, "longitude": 2.3622}, "travel_mode": "driving"},
        )
        self.assertEqual(travel.status_code, 200)
        self.assertGreater(travel.json()["estimated_minutes"], 0)
        route = self.client.post(
            "/api/geolocation/routes/optimize", headers=self.headers,
            json={
                "name": "Tournée du matin", "visit_ids": visit_ids,
                "start": {"latitude": 48.85, "longitude": 2.35}, "travel_mode": "driving",
                "return_to_start": True,
            },
        )
        self.assertEqual(route.status_code, 201, route.text)
        self.assertEqual(len(route.json()["ordered_stops"]), 2)
        self.assertGreater(route.json()["total_distance_km"], 0)
        self.assertEqual(route.json()["provider"], "internal_estimate")


if __name__ == "__main__":
    unittest.main()
