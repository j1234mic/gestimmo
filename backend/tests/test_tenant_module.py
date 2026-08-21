"""Tests d'intégration du module 3 (SQLite, sans service externe)."""

import base64
import os
import tempfile
import unittest
from io import BytesIO

from PIL import Image

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-module3-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class TenantModuleTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        login = self.client.post(
            "/api/auth/login",
            json={"email": "admin@immogest.com", "password": "Admin@2024!"},
        )
        self.assertEqual(login.status_code, 200)
        self.manager_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    @staticmethod
    def pdf(text: str) -> bytes:
        output = BytesIO()
        document = canvas.Canvas(output)
        document.drawString(40, 800, text)
        document.save()
        return output.getvalue()

    def create_property(self) -> int:
        response = self.client.post(
            "/api/properties/",
            headers=self.manager_headers,
            json={
                "type": "apartment",
                "title": "Appartement test",
                "address": "1 rue du Test",
                "postal_code": "75001",
                "city": "Paris",
                "rent_price": 900,
                "charges": 100,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_complete_application_ocr_workflow_and_portal_activation(self):
        property_id = self.create_property()
        response = self.client.post(
            "/api/applications/",
            json={
                "property_id": property_id,
                "first_name": "Alice",
                "last_name": "Martin",
                "email": "alice@example.com",
                "phone": "0612345678",
                "employment_status": "employee",
                "contract_type": "cdi",
                "employer_name": "Acme",
                "monthly_net_income": 3500,
                "privacy_consent": True,
                "guarantors": [{
                    "first_name": "Jean",
                    "last_name": "Martin",
                    "monthly_net_income": 4000,
                    "surety_type": "solidary",
                }],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        application = response.json()
        candidate_headers = {"X-Application-Token": application["tracking_token"]}

        documents = [
            ("identity", "Carte nationale Republique francaise Alice Martin", None),
            ("pay_slip", "Bulletin de paie net a payer Alice Martin", "2026-05"),
            ("pay_slip", "Bulletin de salaire net a payer Alice Martin", "2026-06"),
            ("pay_slip", "Bulletin de paie net a payer Alice Martin", "2026-07"),
            ("tax_notice", "Avis d'impot revenu fiscal Alice Martin", None),
            ("proof_of_address", "Facture electricite domicile Alice Martin", None),
            ("employment_contract", "Contrat de travail employeur salarie Alice Martin", None),
            ("employer_certificate", "Attestation de l'employeur Alice Martin", None),
        ]
        for index, (document_type, text, period) in enumerate(documents):
            form = {"document_type": document_type}
            if period:
                form["pay_slip_period"] = period
            upload = self.client.post(
                f"/api/applications/public/{application['reference']}/documents",
                headers=candidate_headers,
                data=form,
                files={"file": (f"document-{index}.pdf", self.pdf(text), "application/pdf")},
            )
            self.assertEqual(upload.status_code, 201, upload.text)
            self.assertEqual(upload.json()["verification_status"], "verified")

        tracking = self.client.get(
            f"/api/applications/public/{application['reference']}", headers=candidate_headers
        )
        self.assertEqual(tracking.status_code, 200)
        self.assertTrue(tracking.json()["document_completeness"]["complete"])
        self.assertGreaterEqual(tracking.json()["solvency_score"], 75)

        accepted = self.client.put(
            f"/api/applications/{application['id']}/status",
            headers=self.manager_headers,
            json={"status": "accepted"},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        tenant_id = accepted.json()["tenant_id"]

        activation = self.client.post(
            "/tenant-portal/activate",
            json={
                "application_reference": application["reference"],
                "tracking_token": application["tracking_token"],
                "password": "Password1",
            },
        )
        self.assertEqual(activation.status_code, 200, activation.text)
        tenant_headers = {"Authorization": f"Bearer {activation.json()['access_token']}"}
        dashboard = self.client.get("/tenant-portal/dashboard", headers=tenant_headers)
        self.assertEqual(dashboard.status_code, 200)
        self.assertEqual(dashboard.json()["tenant"]["id"], tenant_id)

    def test_late_payment_alert_receipt_and_incident_tracking(self):
        property_id = self.create_property()
        tenant_response = self.client.post(
            "/api/tenants/",
            headers=self.manager_headers,
            json={
                "first_name": "Lina",
                "last_name": "Bernard",
                "email": "lina@example.com",
                "employment_status": "employee",
                "monthly_net_income": 2800,
                "emergency_contacts": [{
                    "first_name": "Marc",
                    "last_name": "Bernard",
                    "phone": "0600000000",
                    "is_primary": True,
                }],
            },
        )
        self.assertEqual(tenant_response.status_code, 201, tenant_response.text)
        tenant_id = tenant_response.json()["id"]
        lease = self.client.post(
            f"/api/tenants/{tenant_id}/leases",
            headers=self.manager_headers,
            json={
                "property_id": property_id,
                "status": "active",
                "start_date": "2026-01-01",
                "monthly_rent": 900,
                "monthly_charges": 100,
            },
        )
        self.assertEqual(lease.status_code, 201, lease.text)
        payment = self.client.post(
            f"/api/tenants/{tenant_id}/payments",
            headers=self.manager_headers,
            json={
                "lease_id": lease.json()["id"],
                "period": "2026-01",
                "due_date": "2026-01-05",
                "amount_due": 1000,
            },
        )
        self.assertEqual(payment.status_code, 201, payment.text)

        alerts = self.client.get("/api/tenants/alerts/late-payments", headers=self.manager_headers)
        self.assertEqual(alerts.status_code, 200)
        self.assertEqual(alerts.json()["total"], 1)

        incident = self.client.post(
            f"/api/tenants/{tenant_id}/incidents",
            headers=self.manager_headers,
            json={"category": "plumbing", "title": "Fuite", "description": "Fuite sous évier", "priority": "high"},
        )
        self.assertEqual(incident.status_code, 201, incident.text)

        paid = self.client.put(
            f"/api/tenants/{tenant_id}/payments/{payment.json()['id']}",
            headers=self.manager_headers,
            json={"amount_paid": 1000, "payment_method": "bank_transfer"},
        )
        self.assertEqual(paid.status_code, 200, paid.text)
        self.assertEqual(paid.json()["status"], "paid")
        self.assertIsNotNone(paid.json()["receipt"])

        receipt = self.client.get(
            paid.json()["receipt"]["download_url"], headers=self.manager_headers
        )
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.headers["content-type"], "application/pdf")

    def create_direct_tenant(self, email: str = "contract@example.com") -> int:
        response = self.client.post(
            "/api/tenants/",
            headers=self.manager_headers,
            json={
                "first_name": "Marie",
                "last_name": "Durand",
                "email": email,
                "phone": "0611223344",
                "monthly_net_income": 3500,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_contract_pdf_revision_and_electronic_signature(self):
        property_id = self.create_property()
        tenant_id = self.create_direct_tenant()
        clause = self.client.post(
            "/api/leases/clauses",
            headers=self.manager_headers,
            json={
                "code": "ENTRETIEN_TEST",
                "title": "Entretien courant",
                "content_template": "Le locataire entretient ${property_address}.",
                "compatible_lease_types": ["residential_unfurnished"],
            },
        )
        self.assertEqual(clause.status_code, 201, clause.text)
        template = self.client.post(
            "/api/leases/templates",
            headers=self.manager_headers,
            json={
                "name": "Bail habitation test",
                "lease_type": "residential_unfurnished",
                "is_default": True,
                "clause_ids": [clause.json()["id"]],
            },
        )
        self.assertEqual(template.status_code, 201, template.text)
        lease = self.client.post(
            "/api/leases/",
            headers=self.manager_headers,
            json={
                "tenant_id": tenant_id,
                "property_id": property_id,
                "lease_type": "residential_unfurnished",
                "start_date": "2026-09-01",
                "rent_excluding_charges": 1000,
                "charges": 100,
                "deposit": 1000,
                "rent_index_type": "irl",
                "base_index_value": 145.2,
                "base_index_date": "2026-01-01",
            },
        )
        self.assertEqual(lease.status_code, 201, lease.text)
        lease_id = lease.json()["id"]
        self.assertEqual(lease.json()["end_date"], "2029-08-31")
        generated = self.client.post(
            f"/api/leases/{lease_id}/generate-pdf", headers=self.manager_headers
        )
        self.assertEqual(generated.status_code, 201, generated.text)
        self.assertEqual(len(generated.json()["checksum_sha256"]), 64)

        index = self.client.post(
            "/api/leases/indices",
            headers=self.manager_headers,
            json={
                "index_type": "irl",
                "period": "T2 2027",
                "publication_date": "2027-07-15",
                "value": 149.5,
                "source": "Source de test",
            },
        )
        cap = self.client.post(
            "/api/leases/cap-rules",
            headers=self.manager_headers,
            json={
                "name": "Plafond de test",
                "lease_type": "residential_unfurnished",
                "valid_from": "2027-01-01",
                "valid_to": "2027-12-31",
                "maximum_increase_percent": 2,
                "legal_reference": "Référence de test",
            },
        )
        self.assertEqual(index.status_code, 201, index.text)
        self.assertEqual(cap.status_code, 201, cap.text)
        revision = self.client.post(
            f"/api/leases/{lease_id}/revisions",
            headers=self.manager_headers,
            json={
                "effective_date": "2027-09-01",
                "index_value_id": index.json()["id"],
                "cap_rule_id": cap.json()["id"],
            },
        )
        self.assertEqual(revision.status_code, 201, revision.text)
        self.assertEqual(revision.json()["capped_rent"], 1020)
        applied = self.client.put(
            f"/api/leases/{lease_id}/revisions/{revision.json()['id']}/apply",
            headers=self.manager_headers,
        )
        self.assertEqual(applied.status_code, 200, applied.text)

        envelope = self.client.post(
            f"/api/leases/{lease_id}/signature-envelopes",
            headers=self.manager_headers,
            json={
                "document_id": generated.json()["id"],
                "subject": "Signature du bail",
                "parties": [
                    {"party_type": "tenant", "party_id": tenant_id, "full_name": "Marie Durand", "email": "contract@example.com"},
                    {"party_type": "owner", "full_name": "Agence Test", "email": "owner@example.com", "signing_order": 2},
                ],
            },
        )
        self.assertEqual(envelope.status_code, 201, envelope.text)
        for invitation in envelope.json()["invitations"]:
            token = invitation["signing_url"].rsplit("/", 1)[-1]
            signed = self.client.post(
                f"/api/lease-signatures/{token}/sign",
                json={"typed_signature": "Signature Test", "consent": True},
            )
            self.assertEqual(signed.status_code, 200, signed.text)
        records = self.client.get(
            f"/api/leases/{lease_id}/signature-envelopes", headers=self.manager_headers
        )
        self.assertEqual(records.json()[0]["status"], "completed")
        self.assertIsNotNone(records.json()[0]["evidence_document_id"])

        amendment = self.client.post(
            f"/api/leases/{lease_id}/amendments",
            headers=self.manager_headers,
            json={
                "title": "Modification du loyer",
                "effective_date": "2028-01-01",
                "reason": "Accord des parties",
                "changes": {"rent_excluding_charges": 1030},
            },
        )
        self.assertEqual(amendment.status_code, 201, amendment.text)
        amendment_envelope = self.client.post(
            f"/api/leases/{lease_id}/signature-envelopes",
            headers=self.manager_headers,
            json={
                "document_id": amendment.json()["document_id"],
                "subject": "Signature de l'avenant",
                "parties": [
                    {"party_type": "tenant", "party_id": tenant_id, "full_name": "Marie Durand", "email": "contract@example.com"},
                    {"party_type": "owner", "full_name": "Agence Test", "email": "owner@example.com", "signing_order": 2},
                ],
            },
        )
        self.assertEqual(amendment_envelope.status_code, 201, amendment_envelope.text)
        for invitation in amendment_envelope.json()["invitations"]:
            token = invitation["signing_url"].rsplit("/", 1)[-1]
            signed = self.client.post(
                f"/api/lease-signatures/{token}/sign",
                json={"typed_signature": "Signature Avenant", "consent": True},
            )
            self.assertEqual(signed.status_code, 200, signed.text)
        applied_amendment = self.client.put(
            f"/api/leases/{lease_id}/amendments/{amendment.json()['id']}/apply",
            headers=self.manager_headers,
        )
        self.assertEqual(applied_amendment.status_code, 200, applied_amendment.text)
        self.assertEqual(applied_amendment.json()["status"], "applied")
        updated_lease = self.client.get(f"/api/leases/{lease_id}", headers=self.manager_headers)
        self.assertEqual(updated_lease.json()["rent_excluding_charges"], 1030)

    def test_inspection_comparison_deductions_and_pdf(self):
        property_id = self.create_property()
        tenant_id = self.create_direct_tenant("inspection@example.com")
        lease = self.client.post(
            "/api/leases/",
            headers=self.manager_headers,
            json={
                "tenant_id": tenant_id,
                "property_id": property_id,
                "lease_type": "residential_furnished",
                "start_date": "2026-09-01",
                "rent_excluding_charges": 900,
                "charges": 100,
            },
        )
        self.assertEqual(lease.status_code, 201, lease.text)
        lease_id = lease.json()["id"]
        entry = self.client.post(
            f"/api/leases/{lease_id}/inspections/",
            headers=self.manager_headers,
            json={"inspection_type": "entry", "inspection_date": "2026-09-01T10:00:00Z"},
        )
        self.assertEqual(entry.status_code, 201, entry.text)
        entry_room = self.client.post(
            f"/api/leases/{lease_id}/inspections/{entry.json()['id']}/rooms",
            headers=self.manager_headers,
            json={
                "name": "Salon",
                "items": [{"category": "floor", "name": "Parquet", "condition": "good"}],
            },
        )
        self.assertEqual(entry_room.status_code, 201, entry_room.text)
        exit_inspection = self.client.post(
            f"/api/leases/{lease_id}/inspections/",
            headers=self.manager_headers,
            json={
                "inspection_type": "exit",
                "inspection_date": "2027-09-01T10:00:00Z",
                "comparison_inspection_id": entry.json()["id"],
            },
        )
        self.assertEqual(exit_inspection.status_code, 201, exit_inspection.text)
        exit_id = exit_inspection.json()["id"]
        exit_room = self.client.post(
            f"/api/leases/{lease_id}/inspections/{exit_id}/rooms",
            headers=self.manager_headers,
            json={
                "name": "Salon",
                "items": [{
                    "category": "floor",
                    "name": "Parquet",
                    "condition": "damaged",
                    "estimated_repair_cost": 500,
                    "depreciation_percent": 20,
                    "tenant_responsibility_percent": 100,
                }],
            },
        )
        self.assertEqual(exit_room.status_code, 201, exit_room.text)
        comparison = self.client.post(
            f"/api/leases/{lease_id}/inspections/{exit_id}/compare",
            headers=self.manager_headers,
        )
        self.assertEqual(comparison.status_code, 200, comparison.text)
        self.assertEqual(comparison.json()["total_suggested_deductions"], 400)

        image = Image.new("RGB", (20, 10), "white")
        output = BytesIO()
        image.save(output, "PNG")
        encoded_signature = base64.b64encode(output.getvalue()).decode()
        for signer_type, signer_name in (("tenant", "Marie Durand"), ("agent", "Agent Test")):
            signature = self.client.post(
                f"/api/leases/{lease_id}/inspections/{exit_id}/signatures",
                headers=self.manager_headers,
                json={
                    "signer_type": signer_type,
                    "signer_name": signer_name,
                    "signature_image_base64": encoded_signature,
                    "consent": True,
                },
            )
            self.assertEqual(signature.status_code, 201, signature.text)
        generated = self.client.post(
            f"/api/leases/{lease_id}/inspections/{exit_id}/generate-pdf",
            headers=self.manager_headers,
        )
        self.assertEqual(generated.status_code, 201, generated.text)
        document = self.client.get(generated.json()["download_url"], headers=self.manager_headers)
        self.assertEqual(document.status_code, 200)
        self.assertEqual(document.headers["content-type"], "application/pdf")


if __name__ == "__main__":
    unittest.main()
