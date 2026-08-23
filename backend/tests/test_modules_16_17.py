"""Tests d'intégration des modules 16 (IA/RPA) et 17 (intégrations/API)."""

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-mod16-17-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["BACKUP_DIR"] = f"{TEST_DIR}/backups"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["ENVIRONMENT"] = "development"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.tenant_security import hash_portal_password  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402


class IntelligenceIntegrationTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.context = TestClient(app)
        self.client = self.context.__enter__()
        login = self.client.post(
            "/api/auth/login",
            json={"email": "admin@immogest.com", "password": "Admin@2024!"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def _property(self, index, area, rent, sale):
        response = self.client.post(
            "/api/properties/",
            headers=self.headers,
            json={
                "type": "apartment", "title": f"Bien comparable {index}",
                "address": f"{index} rue des Tests", "postal_code": "75001", "city": "Paris",
                "living_area": area, "rooms": 2 + index % 2, "rent_price": rent, "sale_price": sale,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_explainable_predictions_and_market_analysis(self):
        ids = [
            self._property(index, area, rent, sale)
            for index, (area, rent, sale) in enumerate(
                [(30, 700, 200_000), (35, 760, 220_000), (40, 850, 250_000),
                 (45, 920, 280_000), (50, 1_000, 310_000), (55, 1_100, 340_000)],
                start=1,
            )
        ]
        observation = self.client.post(
            "/api/ai/market/observations", headers=self.headers,
            json={
                "source": "veille", "competitor": "Agence témoin", "listing_type": "rent",
                "property_type": "apartment", "city": "Paris", "postal_code": "75001",
                "area": 52, "rooms": 3, "price": 1080, "observed_on": "2026-08-01",
            },
        )
        self.assertEqual(observation.status_code, 201, observation.text)
        estimate = self.client.post(
            "/api/ai/predictions/rent", headers=self.headers, json={"property_id": ids[-1]}
        )
        self.assertEqual(estimate.status_code, 201, estimate.text)
        self.assertGreaterEqual(estimate.json()["result"]["comparable_count"], 5)
        self.assertIn(estimate.json()["explanation"]["method"], {"ridge_regression", "weighted_comparables"})
        self.assertIn("validation humaine", estimate.json()["disclaimer"])

        sale = self.client.post(
            "/api/ai/predictions/sale-price", headers=self.headers, json={"property_id": ids[-1]}
        )
        self.assertEqual(sale.status_code, 201, sale.text)
        self.assertGreater(sale.json()["result"]["recommended_sale_price"], 0)
        trends = self.client.get(
            "/api/ai/market/trends", headers=self.headers,
            params={"city": "Paris", "listing_type": "rent"},
        )
        self.assertEqual(trends.status_code, 200)
        self.assertEqual(trends.json()["competitive_watch"][0]["competitor"], "Agence témoin")

    def test_tenant_chatbot_ticket_tracking_and_appointment(self):
        property_id = self._property(1, 35, 780, 225_000)
        tenant_response = self.client.post(
            "/api/tenants/", headers=self.headers,
            json={
                "first_name": "Alice", "last_name": "Martin",
                "email": "alice.chatbot@example.fr", "phone": "0600000000",
            },
        )
        self.assertEqual(tenant_response.status_code, 201, tenant_response.text)
        tenant_id = tenant_response.json()["id"]
        lease = self.client.post(
            f"/api/tenants/{tenant_id}/leases", headers=self.headers,
            json={
                "property_id": property_id, "status": "active",
                "start_date": date.today().isoformat(), "monthly_rent": 780,
            },
        )
        self.assertEqual(lease.status_code, 201, lease.text)
        db = SessionLocal()
        try:
            tenant = db.get(Tenant, tenant_id)
            tenant.portal_enabled = True
            tenant.portal_password_hash = hash_portal_password("Assistant@2026")
            db.commit()
        finally:
            db.close()
        login = self.client.post(
            "/tenant-portal/login",
            json={"email": "alice.chatbot@example.fr", "password": "Assistant@2026"},
        )
        tenant_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        session = self.client.post(
            "/tenant-portal/assistant/sessions", headers=tenant_headers, json={}
        )
        self.assertEqual(session.status_code, 201, session.text)
        session_payload = session.json()
        # ``session_id`` is the stable URL identifier.  The numeric ``id`` is
        # retained for compatibility with clients that used the generic model
        # serializer before the chat contract was made explicit.
        self.assertEqual(session_payload["session_id"], session_payload["public_id"])
        message = self.client.post(
            f"/tenant-portal/assistant/sessions/{session_payload['id']}/messages",
            headers=tenant_headers, json={"message": "Je veux créer un ticket pour une fuite"},
        )
        self.assertEqual(message.json()["intent"], "maintenance_ticket")
        self.assertTrue(message.json()["available_24_7"])
        self.assertTrue(message.json()["proposed_action"]["requires_confirmation"])
        ticket = self.client.post(
            "/tenant-portal/assistant/tickets", headers=tenant_headers,
            json={
                "property_id": property_id, "category": "plomberie", "urgency": "eleve",
                "title": "Fuite sous évier", "description": "Une fuite est visible sous l'évier.",
                "confirm": True,
            },
        )
        self.assertEqual(ticket.status_code, 201, ticket.text)
        tracking = self.client.post(
            f"/tenant-portal/assistant/sessions/{session_payload['session_id']}/messages",
            headers=tenant_headers, json={"message": "Quel est le statut de mon ticket ?"},
        )
        self.assertIn(ticket.json()["reference"], tracking.json()["answer"])
        appointment = self.client.post(
            "/tenant-portal/assistant/appointments", headers=tenant_headers,
            json={
                "property_id": property_id,
                "starts_at": (datetime.now() + timedelta(days=2)).isoformat(),
                "purpose": "Diagnostic de la fuite",
            },
        )
        self.assertEqual(appointment.status_code, 201, appointment.text)
        self.assertEqual(appointment.json()["status"], "requested")

    def test_manager_assistant_answers_each_intent_from_real_data(self):
        """L'assistant gestionnaire ne doit jamais répondre la même phrase générique.

        Le moteur d'intentions doit distinguer une recherche, une demande
        d'aide, une question sur les impayés, les tickets, les échéances de bail
        et un déclenchement de workflow, en s'appuyant sur les données réelles.
        """
        property_id = self._property(9, 62, 1_150, 340_000)
        tenant_response = self.client.post(
            "/api/tenants/", headers=self.headers,
            json={
                "first_name": "Bruno", "last_name": "Lefevre",
                "email": "bruno.lefevre@example.fr", "phone": "0600000042",
            },
        )
        self.assertEqual(tenant_response.status_code, 201, tenant_response.text)
        tenant_id = tenant_response.json()["id"]
        lease = self.client.post(
            f"/api/tenants/{tenant_id}/leases", headers=self.headers,
            json={
                "property_id": property_id, "status": "active",
                "start_date": date.today().isoformat(),
                "end_date": (date.today() + timedelta(days=45)).isoformat(),
                "monthly_rent": 1_150,
            },
        )
        self.assertEqual(lease.status_code, 201, lease.text)
        lease_reference = lease.json()["reference"]
        ticket = self.client.post(
            "/api/maintenance/tickets", headers=self.headers,
            json={
                "property_id": property_id, "source": "manager",
                "category": "plomberie", "urgency": "eleve",
                "title": "Fuite au plafond", "description": "Infiltration visible dans le séjour.",
            },
        )
        self.assertEqual(ticket.status_code, 201, ticket.text)
        ticket_reference = ticket.json()["reference"]
        workflow = self.client.post(
            "/api/ai/automation/workflows", headers=self.headers,
            json={
                "name": "Relance des impayés", "event_type": "payment.late",
                "actions": [{"type": "create_task", "parameters": {"title": "Relancer le locataire"}}],
            },
        )
        self.assertEqual(workflow.status_code, 201, workflow.text)

        session = self.client.post("/api/ai/assistant/sessions", headers=self.headers, json={})
        self.assertEqual(session.status_code, 201, session.text)
        session_id = session.json()["session_id"]

        def ask(message):
            response = self.client.post(
                f"/api/ai/assistant/sessions/{session_id}/messages",
                headers=self.headers, json={"message": message},
            )
            self.assertEqual(response.status_code, 201, response.text)
            return response.json()

        greeting = ask("Bonjour")
        self.assertEqual(greeting["intent"], "manager_help")

        prompt = ask("je recherche un bail")
        self.assertEqual(prompt["intent"], "search_prompt")
        self.assertIn(lease_reference, prompt["answer"])

        # Recherche par nom de locataire : le bail doit remonter.
        by_name = ask("bail de Lefevre")
        self.assertEqual(by_name["intent"], "search_results")
        self.assertIn(lease_reference, by_name["answer"])
        self.assertEqual(by_name["results"][0]["type"], "lease")

        # Les accents et la casse ne doivent pas changer le résultat.
        unaccented = ask("Quels sont les impayes en cours ?")
        self.assertEqual(unaccented["intent"], "manager_unpaid")
        self.assertEqual(ask("Quels sont les impayés en cours ?")["intent"], "manager_unpaid")

        tickets = ask("tickets en cours")
        self.assertEqual(tickets["intent"], "manager_tickets")
        self.assertIn(ticket_reference, tickets["answer"])

        deadlines = ask("quels baux arrivent à échéance ?")
        self.assertEqual(deadlines["intent"], "manager_lease_deadlines")
        self.assertIn(lease_reference, deadlines["answer"])

        portfolio = ask("quel est le taux d'occupation du portefeuille ?")
        self.assertEqual(portfolio["intent"], "manager_portfolio")
        self.assertIn("100.0 %", portfolio["answer"])

        automation = ask("Déclencher un workflow")
        self.assertEqual(automation["intent"], "manager_workflow")
        self.assertIn("payment.late", automation["answer"])
        self.assertTrue(automation["proposed_action"]["requires_confirmation"])

        creation = ask("créer un ticket")
        self.assertEqual(creation["intent"], "manager_create_ticket")
        self.assertEqual(creation["proposed_action"]["type"], "create_ticket")

        # Aucune de ces réponses n'est identique : le bug d'origine renvoyait
        # toujours la même phrase de présentation.
        answers = [
            greeting["answer"], prompt["answer"], by_name["answer"], unaccented["answer"],
            tickets["answer"], deadlines["answer"], portfolio["answer"],
            automation["answer"], creation["answer"],
        ]
        self.assertEqual(len(set(answers)), len(answers))

    def test_workflow_rules_actions_and_idempotency(self):
        workflow = self.client.post(
            "/api/ai/automation/workflows", headers=self.headers,
            json={
                "name": "Contrôle des grosses factures", "event_type": "invoice.created",
                "conditions": [{"field": "amount", "operator": "gte", "value": 1000}],
                "actions": [{"type": "create_task", "parameters": {"title": "Vérifier ${event.reference}"}}],
            },
        )
        self.assertEqual(workflow.status_code, 201, workflow.text)
        event = {
            "event_type": "invoice.created",
            "payload": {"amount": 1500, "reference": "FAC-2026-001"},
            "idempotency_key": "invoice-FAC-2026-001",
        }
        first = self.client.post("/api/ai/automation/events", headers=self.headers, json=event)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["runs"][0]["matched"])
        self.assertEqual(
            first.json()["runs"][0]["action_results"][0]["task"]["title"],
            "Vérifier FAC-2026-001",
        )
        duplicate = self.client.post("/api/ai/automation/events", headers=self.headers, json=event)
        self.assertTrue(duplicate.json()["runs"][0]["duplicate"])
        dry_run = self.client.post(
            "/api/ai/automation/events", headers=self.headers,
            json={**event, "idempotency_key": "other", "payload": {"amount": 50}, "dry_run": True},
        )
        self.assertFalse(dry_run.json()["runs"][0]["matched"])

    def test_api_key_oauth_rate_limit_and_webhooks(self):
        credential = self.client.post(
            "/api/integrations/api-keys", headers=self.headers,
            json={"name": "Partenaire test", "scopes": ["properties:read"], "rate_limit_per_minute": 2},
        )
        self.assertEqual(credential.status_code, 201, credential.text)
        api_key = credential.json()["api_key"]
        unauthenticated = self.client.get("/api/v1/properties")
        self.assertEqual(unauthenticated.status_code, 401)
        first = self.client.get("/api/v1/properties", headers={"X-API-Key": api_key})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.headers["X-RateLimit-Limit"], "2")
        self.assertEqual(
            self.client.get("/api/v1/properties", headers={"X-API-Key": api_key}).status_code, 200
        )
        limited = self.client.get("/api/v1/properties", headers={"X-API-Key": api_key})
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Retry-After", limited.headers)

        oauth = self.client.post(
            "/api/integrations/oauth/clients", headers=self.headers,
            json={"name": "Client BI", "scopes": ["properties:read"]},
        )
        token = self.client.post(
            "/api/integrations/oauth/token",
            data={
                "grant_type": "client_credentials", "client_id": oauth.json()["client_id"],
                "client_secret": oauth.json()["client_secret"], "scope": "properties:read",
            },
        )
        self.assertEqual(token.status_code, 200, token.text)
        self.assertEqual(
            self.client.get(
                "/api/v1/properties",
                headers={"Authorization": f"Bearer {token.json()['access_token']}"},
            ).status_code,
            200,
        )
        schema = self.client.get("/openapi.json").json()
        self.assertIn("ApiKeyAuth", schema["components"]["securitySchemes"])
        self.assertIn("OAuth2ClientCredentials", schema["components"]["securitySchemes"])

        hook = self.client.post(
            "/api/integrations/webhooks", headers=self.headers,
            json={"name": "Zapier test", "target_url": "http://localhost:9999/hooks", "events": ["property.created"]},
        )
        self.assertEqual(hook.status_code, 201, hook.text)
        self.assertIn("signing_secret", hook.json())
        emitted = self.client.post(
            "/api/integrations/webhook-events", headers=self.headers,
            json={"event_type": "property.created", "data": {"id": 42}, "idempotency_key": "property-42"},
        )
        self.assertEqual(emitted.status_code, 201, emitted.text)
        self.assertEqual(emitted.json()["delivery_count"], 1)

    def test_native_catalog_csv_import_duplicates_and_xlsx_export(self):
        catalog = self.client.get("/api/integrations/catalog", headers=self.headers)
        self.assertEqual(catalog.status_code, 200)
        providers = {item["provider"] for item in catalog.json()["providers"]}
        self.assertTrue({"sage", "quickbooks", "xero", "stripe", "docusign", "twilio", "aws_s3", "seloger", "salesforce", "power_bi"}.issubset(providers))

        connection = self.client.post(
            "/api/integrations/connections", headers=self.headers,
            json={"name": "Stripe sans secret", "provider": "stripe", "credentials": {}},
        )
        self.assertEqual(connection.status_code, 201, connection.text)
        tested = self.client.post(
            f"/api/integrations/connections/{connection.json()['id']}/test", headers=self.headers
        )
        self.assertEqual(tested.json()["status"], "not_configured")
        self.assertFalse(tested.json()["configuration_valid"])

        csv_content = (
            "Titre;Type de bien;Adresse;Code postal;Ville;Surface;Loyer\n"
            "Studio A;studio;1 rue A;69001;Lyon;25;650\n"
            "Studio B;studio;2 rue A;69001;Lyon;30;700\n"
        ).encode()
        analysed = self.client.post(
            "/api/integrations/imports/analyse", headers=self.headers,
            data={"entity_type": "properties", "source_system": "ancien-logiciel"},
            files={"file": ("biens.csv", csv_content, "text/csv")},
        )
        self.assertEqual(analysed.status_code, 201, analysed.text)
        imported = self.client.post(
            f"/api/integrations/imports/{analysed.json()['id']}/execute", headers=self.headers,
            json={"mapping": analysed.json()["mapping"], "duplicate_strategy": "skip"},
        )
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertEqual(imported.json()["created"], 2)
        repeated = self.client.post(
            f"/api/integrations/imports/{analysed.json()['id']}/execute", headers=self.headers,
            json={"mapping": analysed.json()["mapping"], "duplicate_strategy": "skip"},
        )
        self.assertEqual(repeated.json()["skipped"], 2)
        exported = self.client.post(
            "/api/integrations/exports", headers=self.headers,
            json={"entity_type": "properties", "output_format": "xlsx"},
        )
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("spreadsheetml", exported.headers["content-type"])
        self.assertIn("X-Export-Reference", exported.headers)


if __name__ == "__main__":
    unittest.main()
