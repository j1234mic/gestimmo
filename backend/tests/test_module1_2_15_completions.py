"""Tests des compléments modules 1, 2 et 15 (SQLite, sans service externe)."""
import os
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-125-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class Module125CompletionTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        login = self.client.post(
            "/api/auth/login",
            json={"email": "admin@immogest.com", "password": "Admin@2024!"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    def create_property(self, **extra) -> int:
        payload = {
            "type": "apartment",
            "title": "Appartement complétion",
            "address": "1 rue du Test",
            "postal_code": "75001",
            "city": "Paris",
            "rent_price": 900,
            "tags": ["neuf", "test"],
            "available_from": "2026-09-01",
        }
        payload.update(extra)
        response = self.client.post("/api/properties/", headers=self.headers, json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def create_owner(self) -> int:
        response = self.client.post(
            "/api/owners/",
            headers=self.headers,
            json={
                "first_name": "Jean",
                "last_name": "Dupont",
                "email": "jean.dupont@example.com",
                "tax_regime": "reel",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_module1_filters_videos_saved_searches_exports_and_tour(self):
        property_id = self.create_property()
        property_id_without = self.create_property(title="Autre bien", tags=["autre"])

        # Filtres tags / available_from / manager_id / owner_id
        response = self.client.get(
            "/api/properties/",
            headers=self.headers,
            params={"tags": ["neuf"], "available_from": "2026-09-01", "manager_id": 42},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 0)

        response = self.client.get(
            "/api/properties/",
            headers=self.headers,
            params={"tags": ["neuf"], "available_from": "2026-09-01"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["data"][0]["id"], property_id)
        self.assertEqual(response.json()["data"][0]["tags"], ["neuf", "test"])

        # Upload vidéo
        video = self.client.post(
            f"/api/properties/{property_id}/photos",
            headers=self.headers,
            files=[("files", ("visite.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4"))],
        )
        self.assertEqual(video.status_code, 200, video.text)
        self.assertEqual(video.json()["uploaded"][0]["media_type"], "video")

        # Visite virtuelle 360°
        tour = self.client.put(
            f"/api/properties/{property_id}/virtual-tour",
            headers=self.headers,
            json={"virtual_tour_url": "https://360.example/tour", "is_360_available": True},
        )
        self.assertEqual(tour.status_code, 200, tour.text)
        detail = self.client.get(f"/api/properties/{property_id}", headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["virtual_tour_url"], "https://360.example/tour")
        self.assertTrue(detail.json()["is_360_available"])

        # Recherches favorites
        saved = self.client.post(
            "/api/properties/saved-searches",
            headers=self.headers,
            json={"name": "mes paris", "criteria": {"city": "Paris", "tags": ["neuf"]}},
        )
        self.assertEqual(saved.status_code, 201, saved.text)
        saved_id = saved.json()["id"]
        listing = self.client.get("/api/properties/saved-searches", headers=self.headers)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["total"], 1)
        update = self.client.put(
            f"/api/properties/saved-searches/{saved_id}",
            headers=self.headers,
            json={"name": "mes paris étendus"},
        )
        self.assertEqual(update.status_code, 200, update.text)

        # Exports CSV et rapport d'évaluation PDF
        csv_export = self.client.get("/api/export/properties/csv", headers=self.headers)
        self.assertEqual(csv_export.status_code, 200)
        self.assertIn("text/csv", csv_export.headers["content-type"])
        self.assertRegex(csv_export.content.decode("utf-8-sig"), "PROP-")

        evaluation = self.client.post(
            f"/api/properties/{property_id}/evaluations",
            headers=self.headers,
            params={"value": 250000, "source": "ai", "notes": "Estimation test"},
        )
        self.assertEqual(evaluation.status_code, 200, evaluation.text)
        report = self.client.get(
            f"/api/export/properties/{property_id}/evaluation-report",
            headers=self.headers,
        )
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.headers["content-type"], "application/pdf")
        self.assertGreater(len(report.content), 500)

    def test_module1_history_consolidates_tenants_rents_and_tickets(self):
        property_id = self.create_property()

        tenant = self.client.post(
            "/api/tenants/",
            headers=self.headers,
            json={
                "first_name": "Lucie",
                "last_name": "Moreau",
                "email": "lucie@example.com",
                "monthly_net_income": 2800,
            },
        )
        self.assertEqual(tenant.status_code, 201, tenant.text)
        tenant_id = tenant.json()["id"]

        lease = self.client.post(
            f"/api/tenants/{tenant_id}/leases",
            headers=self.headers,
            json={
                "property_id": property_id,
                "status": "active",
                "start_date": "2026-01-10",
                "monthly_rent": 900,
                "monthly_charges": 100,
            },
        )
        self.assertEqual(lease.status_code, 201, lease.text)
        lease_id = lease.json()["id"]

        payment = self.client.post(
            f"/api/tenants/{tenant_id}/payments",
            headers=self.headers,
            json={
                "lease_id": lease_id,
                "period": "2026-01",
                "amount_due": 1000,
                "amount_paid": 1000,
                "status": "paid",
                "due_date": "2026-01-05",
            },
        )
        self.assertEqual(payment.status_code, 201, payment.text)

        ticket = self.client.post(
            "/api/maintenance/tickets",
            headers=self.headers,
            json={
                "property_id": property_id,
                "category": "plomberie",
                "urgency": "eleve",
                "title": "Fuite cuisine",
                "description": "Fuite sous l'évier",
                "estimated_cost": 120,
            },
        )
        self.assertEqual(ticket.status_code, 201, ticket.text)

        history = self.client.get(f"/api/properties/{property_id}/history", headers=self.headers)
        self.assertEqual(history.status_code, 200)
        sources = {row["source"] for row in history.json()["data"]}
        self.assertIn("property", sources)
        self.assertIn("lease", sources)
        self.assertIn("rent", sources)
        self.assertIn("maintenance", sources)

    def test_module2_mandate_signature_evidence_and_per_property_summary(self):
        property_id = self.create_property()
        owner_id = self.create_owner()

        # Lier le bien et ajouter des transactions financières
        link = self.client.post(
            f"/api/owners/{owner_id}/properties",
            headers=self.headers,
            json={"property_id": property_id, "is_main_owner": True},
        )
        self.assertEqual(link.status_code, 200, link.text)

        income = self.client.post(
            "/api/accounting/transactions",
            headers=self.headers,
            json={
                "owner_id": owner_id,
                "property_id": property_id,
                "transaction_type": "rental_income",
                "amount": 900,
                "transaction_date": "2026-01-05",
                "description": "Janvier",
            },
        )
        self.assertEqual(income.status_code, 201, income.text)

        summary = self.client.get(
            f"/api/accounting/owners/{owner_id}/property-summary", headers=self.headers
        )
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertEqual(summary.json()["total_income"], 900)
        self.assertEqual(len(summary.json()["properties"]), 1)
        self.assertEqual(summary.json()["properties"][0]["property_id"], property_id)

        # Mandat + signature réelle
        mandate = self.client.post(
            f"/api/owners/{owner_id}/mandates",
            headers=self.headers,
            json={
                "mandate_type": "rental_management",
                "property_id": property_id,
                "start_date": "2026-01-01",
                "end_date": "2027-01-01",
                "renewal_automatic": True,
                "fees_percentage": 5,
            },
        )
        self.assertEqual(mandate.status_code, 201, mandate.text)
        mandate_id = mandate.json()["id"]

        signature = self.client.put(
            f"/api/owners/{owner_id}/mandates/{mandate_id}/sign",
            headers=self.headers,
            json={"typed_signature": "Jean Dupont", "consent": "Je signe ce mandat."},
        )
        self.assertEqual(signature.status_code, 200, signature.text)
        body = signature.json()
        self.assertTrue(body["signature_hash"])
        self.assertTrue(body["signature_document_hash"])

        evidence = self.client.get(
            f"/api/owners/{owner_id}/mandates/{mandate_id}/evidence",
            headers=self.headers,
        )
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(evidence.headers["content-type"], "application/pdf")
        self.assertGreater(len(evidence.content), 500)

    def test_module15_contracts_claims_and_attestations(self):
        property_id = self.create_property()

        contract = self.client.post(
            "/api/insurance/contracts",
            headers=self.headers,
            json={
                "property_id": property_id,
                "insurance_type": "pno",
                "policy_number": "POL-125",
                "company": "AXA",
                "expiry_date": "2027-01-01",
                "premium": 250,
            },
        )
        self.assertEqual(contract.status_code, 201, contract.text)
        contract_id = contract.json()["id"]

        contract_update = self.client.put(
            f"/api/insurance/contracts/{contract_id}",
            headers=self.headers,
            json={"premium": 300, "broker": "Courtier A"},
        )
        self.assertEqual(contract_update.status_code, 200, contract_update.text)
        self.assertEqual(contract_update.json()["premium"], 300)

        contract_list = self.client.get(
            "/api/insurance/contracts", headers=self.headers, params={"property_id": property_id}
        )
        self.assertEqual(contract_list.status_code, 200)
        self.assertEqual(contract_list.json()["total"], 1)

        claim = self.client.post(
            "/api/insurance/claims",
            headers=self.headers,
            json={
                "property_id": property_id,
                "claim_type": "degat_des_eaux",
                "incident_date": "2026-07-01",
                "circumstances": "Fuite salle de bain",
            },
        )
        self.assertEqual(claim.status_code, 201, claim.text)
        claim_id = claim.json()["id"]

        claim_update = self.client.put(
            f"/api/insurance/claims/{claim_id}",
            headers=self.headers,
            json={
                "status": "indemnisation_proposee",
                "expert": "M. Expert",
                "insurance_case_number": "DG-901",
                "proposed_indemnity": 1500,
                "key_dates": {"expertise": "2026-08-01"},
            },
        )
        self.assertEqual(claim_update.status_code, 200, claim_update.text)
        self.assertEqual(claim_update.json()["expert"], "M. Expert")
        self.assertEqual(claim_update.json()["proposed_indemnity"], 1500)

        attestation = self.client.post(
            "/api/insurance/attestations",
            headers=self.headers,
            json={"property_id": property_id},
        )
        self.assertEqual(attestation.status_code, 201, attestation.text)
        attestation_id = attestation.json()["id"]

        reminder = self.client.post(
            f"/api/insurance/attestations/{attestation_id}/remind",
            headers=self.headers,
        )
        self.assertEqual(reminder.status_code, 200, reminder.text)
        self.assertEqual(reminder.json()["reminder_count"], 1)

        attestation_update = self.client.put(
            f"/api/insurance/attestations/{attestation_id}",
            headers=self.headers,
            json={"status": "received", "document_url": "/uploads/att.pdf", "valid_until": "2027-01-01"},
        )
        self.assertEqual(attestation_update.status_code, 200, attestation_update.text)
        self.assertEqual(attestation_update.json()["status"], "received")


if __name__ == "__main__":
    unittest.main()
