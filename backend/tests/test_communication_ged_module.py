"""Tests d'intégration des modules 10 et 11 : communication et GED.

Lancés sur SQLite, sans prestataire externe : messagerie interne,
notifications multicanal journalisées, automatisations, préférences,
arborescence documentaire, génération, signature et conformité.
"""

import io
import os
import tempfile
import unittest
from datetime import date, timedelta

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-mod10-11-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402


def _pdf_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.drawString(72, 750, text)
    pdf.save()
    return buffer.getvalue()


def _png_bytes() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (80, 80), color=(200, 10, 10))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class CommunicationGedModuleTest(unittest.TestCase):
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
        self.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        viewer = self.client.post(
            "/api/auth/login",
            json={"email": "lecteur@immogest.com", "password": "Viewer@2024!"},
        )
        self.viewer_headers = {"Authorization": f"Bearer {viewer.json()['access_token']}"}
        self.property_id = self._create_property()
        self.tenant = self._create_tenant()
        self.owner = self._create_owner()
        self.lease = self._create_lease()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    def _create_property(self) -> int:
        response = self.client.post(
            "/api/properties/",
            headers=self.headers,
            json={
                "type": "apartment",
                "title": "T3 République",
                "address": "12 rue de la Paix",
                "postal_code": "69003",
                "city": "Lyon",
                "rent_price": 900,
                "charges": 90,
                "living_area": 62,
                "rooms": 3,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _create_tenant(self) -> dict:
        response = self.client.post(
            "/api/tenants/",
            headers=self.headers,
            json={
                "first_name": "Léa",
                "last_name": "Martin",
                "email": "lea.martin@example.fr",
                "phone": "0611223344",
                "mobile": "0611223344",
                "city": "Lyon",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _create_owner(self) -> dict:
        response = self.client.post(
            "/api/owners/",
            headers=self.headers,
            json={
                "first_name": "Paul",
                "last_name": "Durand",
                "email": "paul.durand@example.fr",
                "phone": "0478123456",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _create_lease(self) -> dict:
        response = self.client.post(
            f"/api/tenants/{self.tenant['id']}/leases",
            headers=self.headers,
            json={
                "property_id": self.property_id,
                "status": "active",
                "start_date": (date.today().replace(year=date.today().year - 1)).isoformat()
                if date.today().month != 2 or date.today().day != 29
                else (date.today() - timedelta(days=365)).isoformat(),
                "end_date": (date.today() + timedelta(days=45)).isoformat(),
                "monthly_rent": 900,
                "monthly_charges": 90,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    # ------------------------------------------------------------------
    # Module 10 — messagerie interne
    # ------------------------------------------------------------------
    def test_conversation_thread_attachment_search_archive(self):
        created = self.client.post(
            "/api/comms/conversations",
            headers=self.headers,
            json={
                "subject": "Travaux cuisine T3 République",
                "conversation_type": "property",
                "property_id": self.property_id,
                "participants": [
                    {
                        "participant_type": "tenant",
                        "participant_id": self.tenant["id"],
                        "name": "Léa Martin",
                        "email": "lea.martin@example.fr",
                    }
                ],
                "first_message": "Bonjour, le robinet fuit.",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        conversation = created.json()
        self.assertEqual(conversation["conversation_type"], "property")
        self.assertEqual(conversation["message_count"], 1)

        dossier = self.client.post(
            "/api/comms/conversations",
            headers=self.headers,
            json={
                "subject": "Dossier location Léa",
                "conversation_type": "dossier",
                "deal_id": 42,
                "tenant_id": self.tenant["id"],
                "first_message": "Pièces du dossier à relire.",
            },
        )
        self.assertEqual(dossier.status_code, 201)

        listed = self.client.get(
            "/api/comms/conversations",
            headers=self.headers,
            params={"property_id": self.property_id},
        )
        self.assertEqual(listed.json()["count"], 1)

        by_deal = self.client.get(
            "/api/comms/conversations",
            headers=self.headers,
            params={"deal_id": 42, "conversation_type": "dossier"},
        )
        self.assertEqual(by_deal.json()["count"], 1)

        posted = self.client.post(
            f"/api/comms/conversations/{conversation['id']}/messages",
            headers=self.headers,
            json={"body": "Un plombier passe demain matin."},
        )
        self.assertEqual(posted.status_code, 201)
        message_id = posted.json()["id"]

        attached = self.client.post(
            f"/api/comms/conversations/{conversation['id']}/messages/{message_id}/attachments",
            headers=self.headers,
            files={"file": ("devis.txt", b"Devis plomberie 180 EUR", "text/plain")},
        )
        self.assertEqual(attached.status_code, 201, attached.text)
        download = self.client.get(
            attached.json()["download_url"], headers=self.headers
        )
        self.assertEqual(download.status_code, 200)
        self.assertIn(b"180", download.content)

        search = self.client.get(
            "/api/comms/messages/search", headers=self.headers, params={"q": "plombier"}
        )
        self.assertEqual(search.status_code, 200)
        self.assertGreaterEqual(search.json()["data"][0]["id"], 1)

        archived = self.client.put(
            f"/api/comms/conversations/{conversation['id']}/archive",
            headers=self.headers,
            json={"archived": True},
        )
        self.assertTrue(archived.json()["is_archived"])
        blocked = self.client.post(
            f"/api/comms/conversations/{conversation['id']}/messages",
            headers=self.headers,
            json={"body": "trop tard"},
        )
        self.assertEqual(blocked.status_code, 400)

        active = self.client.get(
            "/api/comms/conversations", headers=self.headers, params={"archived": False}
        )
        self.assertEqual(active.json()["count"], 1)

    # ------------------------------------------------------------------
    # Module 10 — templates, dispatch, suivi, préférences
    # ------------------------------------------------------------------
    def test_templates_dispatch_tracking_and_preferences(self):
        templates = self.client.get("/api/comms/templates", headers=self.headers)
        self.assertEqual(templates.status_code, 200)
        keys = {t["key"] for t in templates.json()["data"]}
        self.assertIn("welcome_tenant", keys)
        self.assertIn("payment_reminder", keys)

        customized = self.client.put(
            f"/api/comms/templates/{templates.json()['data'][0]['id']}",
            headers=self.headers,
            json={"subject": "Bienvenue {{prenom}} chez GestImmo"},
        )
        self.assertEqual(customized.status_code, 200)

        sent = self.client.post(
            "/api/comms/dispatch",
            headers=self.headers,
            json={
                "notification_type": "welcome_tenant",
                "channels": ["email", "in_app", "push"],
                "recipient_type": "tenant",
                "recipient_id": self.tenant["id"],
                "recipient_email": "lea.martin@example.fr",
                "recipient_name": "Léa Martin",
                "template_key": "welcome_tenant",
                "tenant_id": self.tenant["id"],
                "property_id": self.property_id,
                "lease_id": self.lease["id"],
                "related_entity_type": "tenant",
                "related_entity_id": self.tenant["id"],
            },
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(sent.json()["count"], 3)
        email = next(item for item in sent.json()["sent"] if item["channel"] == "email")
        self.assertIn("Léa", email["body"])
        self.assertIn("T3 République", email["body"])
        self.assertIsNotNone(email["tracking_token"])

        pixel = self.client.get(f"/api/comms/track/{email['tracking_token']}")
        self.assertEqual(pixel.status_code, 200)
        self.assertEqual(pixel.headers["content-type"], "image/gif")
        history = self.client.get(
            "/api/comms/history",
            headers=self.headers,
            params={"channel": "email", "tenant_id": self.tenant["id"]},
        )
        self.assertEqual(history.json()["count"], 1)
        self.assertEqual(history.json()["data"][0]["status"], "opened")
        self.assertEqual(history.json()["data"][0]["open_count"], 1)

        sms = self.client.post(
            "/api/comms/dispatch",
            headers=self.headers,
            json={
                "notification_type": "visit_reminder",
                "channels": ["sms"],
                "recipient_type": "tenant",
                "recipient_id": self.tenant["id"],
                "recipient_phone": "0611223344",
                "recipient_name": "Léa Martin",
                "subject": "Rappel visite",
                "body": "Visite demain 10h",
            },
        )
        self.assertEqual(sms.json()["count"], 1)
        self.assertEqual(sms.json()["sent"][0]["provider"], "sms_gateway")

        postal = self.client.post(
            "/api/comms/dispatch",
            headers=self.headers,
            json={
                "notification_type": "unpaid_followup",
                "channels": ["postal"],
                "recipient_type": "tenant",
                "recipient_id": self.tenant["id"],
                "recipient_name": "Léa Martin",
                "subject": "Relance AR",
                "body": "Mise en demeure",
                "postal_address": {
                    "address": "12 rue de la Paix",
                    "postal_code": "69003",
                    "city": "Lyon",
                },
            },
        )
        self.assertEqual(postal.json()["count"], 1)
        self.assertEqual(postal.json()["sent"][0]["provider"], "service_courrier")

        pref = self.client.put(
            "/api/comms/preferences",
            headers=self.headers,
            json={
                "contact_type": "tenant",
                "contact_id": self.tenant["id"],
                "email": "lea.martin@example.fr",
                "notification_type": "owner_monthly_report",
                "channels": ["email"],
                "frequency": "never",
                "unsubscribed": True,
            },
        )
        self.assertEqual(pref.status_code, 200)
        blocked = self.client.post(
            "/api/comms/dispatch",
            headers=self.headers,
            json={
                "notification_type": "owner_monthly_report",
                "channels": ["email"],
                "recipient_type": "tenant",
                "recipient_email": "lea.martin@example.fr",
                "subject": "Bilan",
                "body": "Ne doit pas partir",
            },
        )
        self.assertEqual(blocked.json()["count"], 0)

        unsub = self.client.get(f"/api/comms/unsubscribe/{email['unsubscribe_token']}")
        self.assertTrue(unsub.json()["unsubscribed"])

    def test_automation_scenarios(self):
        scenarios = self.client.get("/api/comms/scenarios", headers=self.headers)
        self.assertEqual(scenarios.status_code, 200)
        self.assertEqual(scenarios.json()["count"], 8)
        keys = {s["key"] for s in scenarios.json()["data"]}
        self.assertEqual(
            keys,
            {
                "welcome_tenant",
                "payment_reminder_j3",
                "unpaid_followup",
                "lease_anniversary",
                "renewal_reminder",
                "payment_confirmation",
                "visit_confirmation",
                "owner_monthly_report",
            },
        )

        reminder = next(s for s in scenarios.json()["data"] if s["key"] == "payment_reminder_j3")
        updated = self.client.put(
            f"/api/comms/scenarios/{reminder['id']}",
            headers=self.headers,
            json={"offset_days": -3, "channels": ["email", "sms", "in_app"]},
        )
        self.assertEqual(updated.json()["offset_days"], -3)

        due = date.today() + timedelta(days=3)
        overdue = date.today() - timedelta(days=10)
        used_periods = {due.strftime("%Y-%m")}
        overdue_period = overdue.strftime("%Y-%m")
        if overdue_period in used_periods:
            overdue_period = (overdue.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        used_periods.add(overdue_period)
        paid_period = "2020-01"
        self.client.post(
            f"/api/tenants/{self.tenant['id']}/payments",
            headers=self.headers,
            json={
                "lease_id": self.lease["id"],
                "period": due.strftime("%Y-%m"),
                "due_date": due.isoformat(),
                "amount_due": 990,
            },
        )
        overdue_pay = self.client.post(
            f"/api/tenants/{self.tenant['id']}/payments",
            headers=self.headers,
            json={
                "lease_id": self.lease["id"],
                "period": overdue_period,
                "due_date": overdue.isoformat(),
                "amount_due": 990,
            },
        )
        self.assertEqual(overdue_pay.status_code, 201, overdue_pay.text)
        confirm = self.client.post(
            f"/api/tenants/{self.tenant['id']}/payments",
            headers=self.headers,
            json={
                "lease_id": self.lease["id"],
                "period": paid_period,
                "due_date": date.today().isoformat(),
                "amount_due": 990,
            },
        )
        self.assertEqual(confirm.status_code, 201, confirm.text)
        self.client.put(
            f"/api/tenants/{self.tenant['id']}/payments/{confirm.json()['id']}",
            headers=self.headers,
            json={"amount_paid": 990, "payment_method": "virement"},
        )

        # Forcer le bilan propriétaire (jour du mois)
        report = next(s for s in scenarios.json()["data"] if s["key"] == "owner_monthly_report")
        self.client.put(
            f"/api/comms/scenarios/{report['id']}",
            headers=self.headers,
            json={"rules": {"day_of_month": date.today().day, "force": True}},
        )

        run = self.client.post("/api/comms/scenarios/run", headers=self.headers)
        self.assertEqual(run.status_code, 200, run.text)
        by_key = {item["key"]: item for item in run.json()["scenarios"]}
        self.assertGreaterEqual(by_key["welcome_tenant"]["sent"], 1)
        self.assertGreaterEqual(by_key["payment_reminder_j3"]["sent"], 1)
        self.assertGreaterEqual(by_key["unpaid_followup"]["sent"], 1)
        self.assertGreaterEqual(by_key["renewal_reminder"]["sent"], 1)
        self.assertGreaterEqual(by_key["payment_confirmation"]["sent"], 1)
        self.assertGreaterEqual(by_key["owner_monthly_report"]["sent"], 1)
        # Anniversaire : le bail a été créé avec start_date = aujourd'hui - 1 an
        self.assertGreaterEqual(by_key["lease_anniversary"]["sent"], 1)

        # Idempotence : un second passage n'envoie pas deux fois
        again = self.client.post("/api/comms/scenarios/run", headers=self.headers).json()
        again_map = {item["key"]: item for item in again["scenarios"]}
        self.assertEqual(again_map["payment_reminder_j3"]["sent"], 0)

        history = self.client.get(
            "/api/comms/history",
            headers=self.headers,
            params={"q": "loyer", "property_id": self.property_id},
        )
        self.assertGreaterEqual(history.json()["count"], 1)

    # ------------------------------------------------------------------
    # Module 11 — GED
    # ------------------------------------------------------------------
    def test_folder_tree_upload_versioning_search(self):
        root = self.client.post(
            "/api/ged/folders",
            headers=self.headers,
            json={"name": "Bien T3", "scope": "property", "property_id": self.property_id},
        )
        self.assertEqual(root.status_code, 201, root.text)
        child = self.client.post(
            "/api/ged/folders",
            headers=self.headers,
            json={
                "name": "Contrats",
                "parent_id": root.json()["id"],
                "scope": "contract",
                "lease_id": self.lease["id"],
                "property_id": self.property_id,
            },
        )
        self.assertEqual(child.status_code, 201)
        tree = self.client.get("/api/ged/folders/tree", headers=self.headers)
        self.assertEqual(tree.status_code, 200)
        self.assertEqual(tree.json()["data"][0]["children"][0]["name"], "Contrats")

        pdf = _pdf_bytes("Contrat de location bail locataire bailleur T3 République")
        upload = self.client.post(
            "/api/ged/documents",
            headers=self.headers,
            data={
                "title": "Bail Léa Martin",
                "document_type": "other",
                "folder_id": child.json()["id"],
                "tags": "urgent,bail",
                "property_id": self.property_id,
                "tenant_id": self.tenant["id"],
                "lease_id": self.lease["id"],
            },
            files={"file": ("bail.pdf", pdf, "application/pdf")},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        document = upload.json()
        self.assertEqual(document["current_version"], 1)
        self.assertIn("bail", (document["classification"] or document["document_type"]))
        self.assertGreater(document["ocr_confidence"], 0)

        v2 = self.client.post(
            f"/api/ged/documents/{document['id']}/versions",
            headers=self.headers,
            data={"comment": "Version signée"},
            files={"file": ("bail-v2.pdf", _pdf_bytes("Contrat de location version 2"), "application/pdf")},
        )
        self.assertEqual(v2.status_code, 201, v2.text)
        self.assertEqual(v2.json()["current_version"], 2)

        png = self.client.post(
            "/api/ged/documents",
            headers=self.headers,
            data={"title": "Photo cuisine", "document_type": "other", "property_id": self.property_id},
            files={"file": ("cuisine.png", _png_bytes(), "image/png")},
        )
        self.assertEqual(png.status_code, 201, png.text)
        self.assertTrue((png.json()["original_filename"] or "").endswith(".jpg"))
        self.assertEqual(png.json()["mime_type"], "image/jpeg")
        self.assertGreater(png.json()["file_size"], 0)

        batch = self.client.post(
            "/api/ged/documents/batch",
            headers=self.headers,
            data={"document_type": "other", "property_id": self.property_id},
            files=[
                ("files", ("a.pdf", _pdf_bytes("Attestation d'assurance multirisque"), "application/pdf")),
                ("files", ("b.pdf", _pdf_bytes("Avis d'échéance montant du loyer"), "application/pdf")),
            ],
        )
        self.assertEqual(batch.status_code, 201, batch.text)
        self.assertEqual(batch.json()["count"], 2)

        search = self.client.get(
            "/api/ged/documents",
            headers=self.headers,
            params={"q": "location", "property_id": self.property_id, "tag": "urgent"},
        )
        self.assertEqual(search.status_code, 200)
        self.assertGreaterEqual(search.json()["count"], 1)

        detail = self.client.get(f"/api/ged/documents/{document['id']}", headers=self.headers)
        self.assertIn("contrat de location", (detail.json().get("ocr_text") or "").lower())
        audit = self.client.get(f"/api/ged/documents/{document['id']}/audit", headers=self.headers)
        actions = {row["action"] for row in audit.json()["data"]}
        self.assertIn("upload", actions)
        self.assertIn("view", actions)

        download = self.client.get(f"/api/ged/documents/{document['id']}/download", headers=self.headers)
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download.content.startswith(b"%PDF"))

        rejected = self.client.post(
            "/api/ged/documents",
            headers=self.headers,
            files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
        )
        self.assertEqual(rejected.status_code, 400)

    def test_generation_preview_and_all_templates(self):
        listing = self.client.get("/api/ged/templates", headers=self.headers)
        self.assertEqual(listing.status_code, 200)
        categories = {t["category"] for t in listing.json()["data"]}
        expected = {
            "bail",
            "quittance",
            "appel_loyer",
            "etat_des_lieux",
            "lettre_relance",
            "attestation_loyer",
            "lettre_conge",
            "mise_en_demeure",
            "mandat_gestion",
            "avis_echeance",
            "regularisation_charges",
        }
        self.assertTrue(expected.issubset(categories))

        preview = self.client.post(
            "/api/ged/generate",
            headers=self.headers,
            json={
                "template_key": "quittance",
                "preview_only": True,
                "tenant_id": self.tenant["id"],
                "property_id": self.property_id,
                "lease_id": self.lease["id"],
                "variables": {"montant": 990, "periode": "2026-08"},
            },
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertTrue(preview.json()["preview"])
        self.assertIn("Léa", preview.json()["text"])
        self.assertIn("990", preview.json()["text"])

        generated = self.client.post(
            "/api/ged/generate",
            headers=self.headers,
            json={
                "template_key": "attestation_loyer",
                "tenant_id": self.tenant["id"],
                "property_id": self.property_id,
                "lease_id": self.lease["id"],
            },
        )
        self.assertEqual(generated.status_code, 200, generated.text)
        self.assertFalse(generated.json()["preview"])
        self.assertEqual(generated.json()["document"]["document_type"], "attestation_loyer")
        pdf = self.client.get(
            generated.json()["document"]["download_url"], headers=self.headers
        )
        reader = PdfReader(io.BytesIO(pdf.content))
        self.assertGreaterEqual(len(reader.pages), 1)

    def test_signature_circuit_and_evidence(self):
        generated = self.client.post(
            "/api/ged/generate",
            headers=self.headers,
            json={
                "template_key": "bail",
                "tenant_id": self.tenant["id"],
                "property_id": self.property_id,
                "lease_id": self.lease["id"],
            },
        )
        document_id = generated.json()["document"]["id"]
        envelope = self.client.post(
            "/api/ged/signatures",
            headers=self.headers,
            json={
                "document_id": document_id,
                "provider": "yousign",
                "signature_level": "simple",
                "signers": [
                    {"name": "Léa Martin", "email": "lea.martin@example.fr", "role": "locataire", "signing_order": 1},
                    {"name": "Paul Durand", "email": "paul.durand@example.fr", "role": "bailleur", "signing_order": 2},
                ],
            },
        )
        self.assertEqual(envelope.status_code, 201, envelope.text)
        env_id = envelope.json()["id"]
        first, second = envelope.json()["signers"]

        too_soon = self.client.post(
            f"/api/ged/signatures/{env_id}/signers/{first['id']}/sign",
            headers=self.headers,
            json={"typed_signature": "Léa Martin", "consent": True},
        )
        self.assertEqual(too_soon.status_code, 400)

        sent = self.client.post(f"/api/ged/signatures/{env_id}/send", headers=self.headers)
        self.assertEqual(sent.json()["status"], "sent")
        self.assertTrue(sent.json()["provider_envelope_id"].startswith("yousign-"))

        wrong_order = self.client.post(
            f"/api/ged/signatures/{env_id}/signers/{second['id']}/sign",
            headers=self.headers,
            json={"typed_signature": "Paul Durand", "consent": True},
        )
        self.assertEqual(wrong_order.status_code, 400)

        sign1 = self.client.post(
            f"/api/ged/signatures/{env_id}/signers/{first['id']}/sign",
            headers=self.headers,
            json={"typed_signature": "Léa Martin", "consent": True},
        )
        self.assertEqual(sign1.status_code, 200, sign1.text)
        self.assertEqual(sign1.json()["status"], "in_progress")

        sign2 = self.client.post(
            f"/api/ged/signatures/{env_id}/signers/{second['id']}/sign",
            headers=self.headers,
            json={"typed_signature": "Paul Durand", "consent": True},
        )
        self.assertEqual(sign2.json()["status"], "completed")
        self.assertTrue(sign2.json()["has_evidence"])
        self.assertIsNotNone(sign2.json()["evidence_hash"])

        evidence = self.client.get(f"/api/ged/signatures/{env_id}/evidence", headers=self.headers)
        self.assertEqual(evidence.status_code, 200)
        self.assertTrue(evidence.content.startswith(b"%PDF"))

    def test_security_retention_legal_hold_gdpr_and_roles(self):
        upload = self.client.post(
            "/api/ged/documents",
            headers=self.headers,
            data={"title": "Pièce identité", "document_type": "identity", "tenant_id": self.tenant["id"]},
            files={"file": ("cni.pdf", _pdf_bytes("Carte nationale d identite"), "application/pdf")},
        )
        doc_id = upload.json()["id"]

        # Lecteur : pas d'upload
        denied = self.client.post(
            "/api/ged/documents",
            headers=self.viewer_headers,
            files={"file": ("x.pdf", _pdf_bytes("x"), "application/pdf")},
        )
        self.assertEqual(denied.status_code, 403)

        hold = self.client.put(
            f"/api/ged/documents/{doc_id}",
            headers=self.headers,
            json={"legal_hold": True},
        )
        self.assertTrue(hold.json()["legal_hold"])
        blocked = self.client.delete(f"/api/ged/documents/{doc_id}", headers=self.headers)
        self.assertEqual(blocked.status_code, 400)

        self.client.put(
            f"/api/ged/documents/{doc_id}",
            headers=self.headers,
            json={"legal_hold": False, "retention_years": 10},
        )
        too_soon = self.client.post(
            f"/api/ged/documents/{doc_id}/erase",
            headers=self.headers,
            json={"reason": "demande RGPD locataire"},
        )
        self.assertEqual(too_soon.status_code, 400)

        # Rétention échue → effacement possible
        from app.models.ged import GedDocument

        db = SessionLocal()
        try:
            db.query(GedDocument).filter(GedDocument.id == doc_id).update(
                {"retain_until": date.today() - timedelta(days=1), "legal_hold": False}
            )
            db.commit()
        finally:
            db.close()
        erased = self.client.post(
            f"/api/ged/documents/{doc_id}/erase",
            headers=self.headers,
            json={"reason": "demande RGPD locataire"},
        )
        self.assertEqual(erased.status_code, 200, erased.text)
        self.assertTrue(erased.json()["erased"])

        settings = self.client.put(
            "/api/ged/settings",
            headers=self.headers,
            json={"max_upload_mb": 5, "default_retention_years": 8},
        )
        self.assertEqual(settings.status_code, 200)
        self.assertEqual(settings.json()["max_upload_mb"], 5)
        viewer_settings = self.client.put(
            "/api/ged/settings",
            headers=self.viewer_headers,
            json={"max_upload_mb": 50},
        )
        self.assertEqual(viewer_settings.status_code, 403)


if __name__ == "__main__":
    unittest.main()
