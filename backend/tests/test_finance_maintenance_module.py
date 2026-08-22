"""Tests d'intégration des modules 5 (finance/compta) et 6 (maintenance/travaux).

Lancés sur SQLite, sans service externe, à travers l'API FastAPI.
"""

import os
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-mod56-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class FinanceMaintenanceTest(unittest.TestCase):
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

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    def create_property(self) -> int:
        response = self.client.post(
            "/api/properties/",
            headers=self.headers,
            json={
                "type": "apartment",
                "title": "Appartement test",
                "address": "1 rue du Test",
                "postal_code": "75001",
                "city": "Paris",
                "rent_price": 900,
                "charges": 100,
                "living_area": 60,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def create_tenant_and_lease(self, property_id: int):
        tenant = self.client.post(
            "/api/tenants/",
            headers=self.headers,
            json={
                "first_name": "Alice",
                "last_name": "Martin",
                "email": "alice@example.com",
                "employment_status": "employee",
                "monthly_net_income": 3500,
                "status": "active",
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
                "start_date": "2024-01-01",
                "monthly_rent": 900,
                "monthly_charges": 100,
                "payment_day": 5,
                "lease_type": "unfurnished",
            },
        )
        self.assertEqual(lease.status_code, 201, lease.text)
        return tenant_id, lease.json()["id"]

    def test_module5_rent_calls_payment_late_plan(self):
        property_id = self.create_property()
        tenant_id, lease_id = self.create_tenant_and_lease(property_id)

        # Génération d'appels de loyer pour une période passée.
        calls = self.client.post(
            "/api/finance/rent-calls/generate?month=2024-05",
            headers=self.headers,
        )
        self.assertEqual(calls.status_code, 200, calls.text)
        body = calls.json()
        self.assertEqual(body["count"], 1)

        # L'idempotence empêche de recréer l'appel.
        calls2 = self.client.post(
            "/api/finance/rent-calls/generate?month=2024-05",
            headers=self.headers,
        )
        self.assertEqual(calls2.json()["count"], 0)

        # Encaissement multi-canal (virement).
        payments = self.client.get(f"/api/tenants/{tenant_id}/payments", headers=self.headers)
        payment = payments.json()[0]
        record = self.client.post(
            f"/api/finance/payments/{payment['id']}/record?amount=1000&method=bank_transfer&paid_at=2024-05-10",
            headers=self.headers,
        )
        self.assertEqual(record.status_code, 200, record.text)
        self.assertEqual(record.json()["status"], "paid")

        # Détection des impayés sur un appel non soldé d'une période antérieure.
        calls_old = self.client.post("/api/finance/rent-calls/generate?month=2024-04", headers=self.headers)
        self.assertEqual(calls_old.json()["count"], 1)
        detected = self.client.post("/api/finance/late-payments/detect?as_of=2024-07-01", headers=self.headers)
        self.assertEqual(detected.status_code, 200, detected.text)
        self.assertGreater(detected.json()["count"], 0)

        lates = self.client.get("/api/finance/late-payments", headers=self.headers)
        self.assertGreater(lates.json()["count"], 0)
        late = lates.json()["data"][0]

        # Pénalités de retard.
        penalty = self.client.post(
            f"/api/finance/late-payments/{late['id']}/penalty",
            headers=self.headers,
            json={"principal": late["amount_outstanding"], "days": 30, "annual_rate_percent": 5},
        )
        self.assertEqual(penalty.status_code, 200, penalty.text)
        self.assertEqual(penalty.json()["days"], 30)

        # Workflow de relance (J+30 → mise en demeure).
        advance = self.client.post(f"/api/finance/late-payments/{late['id']}/advance", headers=self.headers)
        self.assertEqual(advance.status_code, 200, advance.text)

        # Plan d'apurement.
        plan = self.client.post(
            "/api/finance/payment-plans",
            headers=self.headers,
            json={
                "tenant_id": tenant_id,
                "lease_id": lease_id,
                "total_amount": late["amount_outstanding"],
                "installments_count": 3,
                "first_due_date": "2024-08-01",
            },
        )
        self.assertEqual(plan.status_code, 201, plan.text)
        installments = plan.json()["installments"]
        self.assertEqual(len(installments), 3)
        pay = self.client.post(
            f"/api/finance/payment-plans/installments/{installments[0]['id']}/pay",
            headers=self.headers,
            json={},
        )
        self.assertEqual(pay.status_code, 200, pay.text)
        self.assertEqual(pay.json()["plan_status"], "in_progress")

    def test_module5_charges_accounting_invoice_deposit_export(self):
        property_id = self.create_property()
        tenant_id, lease_id = self.create_tenant_and_lease(property_id)

        # Charge récupérable répartie.
        charge = self.client.post(
            "/api/finance/charges",
            headers=self.headers,
            json={
                "property_id": property_id,
                "lease_id": lease_id,
                "charge_type": "chauffage",
                "amount": 600,
                "recoverability": "recoverable",
                "allocation_key": "tantièmes",
                "period_start": "2024-01-01",
                "period_end": "2024-12-31",
            },
        )
        self.assertEqual(charge.status_code, 201, charge.text)
        allocated = self.client.post(f"/api/finance/charges/{charge.json()['id']}/allocate", headers=self.headers)
        self.assertEqual(allocated.status_code, 200, allocated.text)

        # Régularisation annuelle.
        reg = self.client.post(f"/api/finance/charges/regularize?lease_id={lease_id}&year=2024", headers=self.headers)
        self.assertEqual(reg.status_code, 201, reg.text)
        self.assertIn("difference", reg.json())

        # Plan comptable standard + écriture équilibrée.
        accounts = self.client.post("/api/finance/accounts/standard", headers=self.headers)
        self.assertEqual(accounts.status_code, 200, accounts.text)
        all_accounts = self.client.get("/api/finance/accounts", headers=self.headers).json()["data"]
        bank = next(a for a in all_accounts if a["code"] == "512")
        income = next(a for a in all_accounts if a["code"] == "70")
        entry = self.client.post(
            "/api/finance/journal-entries",
            headers=self.headers,
            json={
                "entry_date": "2024-05-01",
                "label": "Écriture de test",
                "lines": [
                    {"account_id": bank["id"], "debit": 100, "credit": 0},
                    {"account_id": income["id"], "debit": 0, "credit": 100},
                ],
            },
        )
        self.assertEqual(entry.status_code, 201, entry.text)
        entry_id = entry.json()["id"]
        validate = self.client.post(f"/api/finance/journal-entries/{entry_id}/validate", headers=self.headers)
        self.assertEqual(validate.status_code, 200, validate.text)
        self.assertEqual(validate.json()["status"], "validated")

        # Balance générale.
        balance = self.client.get("/api/finance/trial-balance", headers=self.headers)
        self.assertEqual(balance.status_code, 200, balance.text)

        # Facturation.
        invoice = self.client.post(
            "/api/finance/invoices",
            headers=self.headers,
            json={
                "invoice_type": "prestation",
                "invoice_date": "2024-05-01",
                "issuer_type": "company",
                "recipient_type": "tenant",
                "recipient_name": "Alice",
                "lines": [{"description": "Prestation", "unit_price": 50, "quantity": 2}],
            },
        )
        self.assertEqual(invoice.status_code, 201, invoice.text)
        self.assertEqual(invoice.json()["amount_ttc"], 100)

        # Dépôt de garantie : encaissement, retenue, restitution.
        deposit = self.client.post(
            "/api/finance/deposits",
            headers=self.headers,
            json={
                "lease_id": lease_id,
                "tenant_id": tenant_id,
                "property_id": property_id,
                "amount": 900,
                "received_at": "2024-01-01",
                "end_date": "2024-12-31",
                "restitution_legal_delay_months": 1,
            },
        )
        self.assertEqual(deposit.status_code, 201, deposit.text)
        deposit_id = deposit.json()["id"]
        deduction = self.client.post(
            f"/api/finance/deposits/{deposit_id}/deductions",
            headers=self.headers,
            json={"label": "Réparation", "amount": 100, "justification": "Dégât"},
        )
        self.assertEqual(deduction.status_code, 201, deduction.text)
        restitution = self.client.post(f"/api/finance/deposits/{deposit_id}/restitution", headers=self.headers)
        self.assertEqual(restitution.status_code, 200, restitution.text)
        self.assertEqual(restitution.json()["amount_returned"], 800)
        retour = self.client.post(
            f"/api/finance/deposits/{deposit_id}/return",
            headers=self.headers,
            json={"amount_returned": 800, "returned_at": "2025-01-15"},
        )
        self.assertEqual(retour.status_code, 200, retour.text)

        # Export FEC.
        export = self.client.post(
            "/api/finance/exports",
            headers=self.headers,
            json={
                "export_format": "fec",
                "period_start": "2024-01-01",
                "period_end": "2024-12-31",
            },
        )
        self.assertEqual(export.status_code, 200, export.text)
        self.assertEqual(export.json()["format"], "fec")
        self.assertIn("JournalCode", export.json()["content"])

    def test_module6_ticket_workflow_preventive_project_equipment(self):
        property_id = self.create_property()
        tenant_id, lease_id = self.create_tenant_and_lease(property_id)

        # Prestataire.
        provider = self.client.post(
            "/api/maintenance/providers",
            headers=self.headers,
            json={"company_name": "PlombierPro", "specialties": ["plomberie"], "tariff_hourly": 60},
        )
        self.assertEqual(provider.status_code, 201, provider.text)
        provider_id = provider.json()["id"]

        # Ticket de demande d'intervention.
        ticket = self.client.post(
            "/api/maintenance/tickets",
            headers=self.headers,
            json={
                "source": "tenant",
                "tenant_id": tenant_id,
                "property_id": property_id,
                "lease_id": lease_id,
                "category": "plomberie",
                "urgency": "eleve",
                "title": "Fuite d'eau",
                "description": "Fuite sous lavabo",
                "location": "Salle de bain",
            },
        )
        self.assertEqual(ticket.status_code, 201, ticket.text)
        ticket_id = ticket.json()["id"]
        self.assertEqual(ticket.json()["status"], "nouveau")
        self.assertIsNotNone(ticket.json()["sla_deadline"])

        # Avancement du workflow.
        for status in ["valide", "prestataire_assigne", "devis_en_attente"]:
            update = self.client.post(
                f"/api/maintenance/tickets/{ticket_id}/status",
                headers=self.headers,
                json={"status": status, "note": "Avancement"},
            )
            self.assertEqual(update.status_code, 200, update.text)
            self.assertEqual(update.json()["status"], status)

        # Devis, comparaison et acceptation.
        q1 = self.client.post(
            f"/api/maintenance/tickets/{ticket_id}/quotes",
            headers=self.headers,
            json={"provider_id": provider_id, "amount": 350},
        )
        self.assertEqual(q1.status_code, 201, q1.text)
        q2 = self.client.post(
            f"/api/maintenance/tickets/{ticket_id}/quotes",
            headers=self.headers,
            json={"provider_id": provider_id, "amount": 420},
        )
        self.assertEqual(q2.status_code, 201, q2.text)
        compare = self.client.get(f"/api/maintenance/tickets/{ticket_id}/quotes/compare", headers=self.headers)
        self.assertEqual(compare.status_code, 200, compare.text)
        self.assertEqual(compare.json()["cheapest_quote_id"], q1.json()["id"])
        accept = self.client.post(
            f"/api/maintenance/tickets/{ticket_id}/quotes/{q1.json()['id']}/accept",
            headers=self.headers,
        )
        self.assertEqual(accept.status_code, 200, accept.text)
        detail = self.client.get(f"/api/maintenance/tickets/{ticket_id}", headers=self.headers)
        self.assertEqual(detail.json()["status"], "devis_valide")

        # Maintenance préventive.
        plan = self.client.post(
            "/api/maintenance/preventive/plans",
            headers=self.headers,
            json={
                "property_id": property_id,
                "maintenance_type": "chaudiere",
                "next_due_date": "2020-06-01",
                "interval_months": 12,
            },
        )
        self.assertEqual(plan.status_code, 201, plan.text)
        materialized = self.client.post("/api/maintenance/preventive/materialize?as_of=2024-06-01", headers=self.headers)
        self.assertEqual(materialized.status_code, 200, materialized.text)
        self.assertGreaterEqual(materialized.json()["count"], 1)

        # Travaux lourds : projet, phases, documents, réception.
        project = self.client.post(
            "/api/maintenance/projects",
            headers=self.headers,
            json={"property_id": property_id, "title": "Rénovation cuisine", "budget": 10000},
        )
        self.assertEqual(project.status_code, 201, project.text)
        project_id = project.json()["id"]
        phase = self.client.post(
            f"/api/maintenance/projects/{project_id}/phases",
            headers=self.headers,
            json={"name": "Dépose", "start_date": "2024-06-01", "end_date": "2024-06-15", "progress": 30},
        )
        self.assertEqual(phase.status_code, 201, phase.text)
        receive = self.client.post(f"/api/maintenance/projects/{project_id}/receive", headers=self.headers)
        self.assertEqual(receive.status_code, 200, receive.text)
        self.assertEqual(receive.json()["status"], "recu")

        # Inventaire équipements + historique pannes.
        equipment = self.client.post(
            "/api/maintenance/equipment",
            headers=self.headers,
            json={
                "property_id": property_id,
                "name": "Chaudière",
                "category": "chauffage",
                "installation_date": "2019-01-01",
                "replacement_date": "2030-01-01",
            },
        )
        self.assertEqual(equipment.status_code, 201, equipment.text)
        equip_id = equipment.json()["id"]
        log = self.client.post(
            f"/api/maintenance/equipment/{equip_id}/logs",
            headers=self.headers,
            json={"log_type": "panne", "description": "Bruit anormal", "cost": 120},
        )
        self.assertEqual(log.status_code, 201, log.text)
        history = self.client.get(f"/api/maintenance/equipment/{equip_id}/history", headers=self.headers)
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual(len(history.json()["logs"]), 1)

        # Suivi financier.
        expense = self.client.post(
            "/api/maintenance/expenses",
            headers=self.headers,
            json={
                "property_id": property_id,
                "amount": 350,
                "expense_date": "2024-06-01",
                "imputation": "proprietaire",
                "description": "Réparation",
            },
        )
        self.assertEqual(expense.status_code, 201, expense.text)
        budget = self.client.get(f"/api/maintenance/budget?property_id={property_id}&year=2024", headers=self.headers)
        self.assertEqual(budget.status_code, 200, budget.text)
        self.assertEqual(budget.json()["actual"], 350)

    def test_module6_sla_escalation(self):
        property_id = self.create_property()
        tenant_id, lease_id = self.create_tenant_and_lease(property_id)
        # Un ticket critique expire son SLA immédiatement en remontant l'échéance.
        ticket = self.client.post(
            "/api/maintenance/tickets",
            headers=self.headers,
            json={
                "source": "manager",
                "property_id": property_id,
                "lease_id": lease_id,
                "category": "electricite",
                "urgency": "critique",
                "title": "Surchauffe tableau électrique",
            },
        )
        self.assertEqual(ticket.status_code, 201, ticket.text)
        ticket_id = ticket.json()["id"]
        # Passage de l'échéance SLA dans le passé puis escalade.
        from datetime import datetime, timezone

        from app.database import SessionLocal
        from app.models.maintenance import MaintenanceTicket
        session = SessionLocal()
        t = session.query(MaintenanceTicket).filter(MaintenanceTicket.id == ticket_id).first()
        t.sla_deadline = datetime(2020, 1, 1, tzinfo=timezone.utc)
        session.commit()
        session.close()

        escalate = self.client.post("/api/maintenance/tickets/escalate", headers=self.headers)
        self.assertEqual(escalate.status_code, 200, escalate.text)
        self.assertGreaterEqual(escalate.json()["escalated"], 1)

        detail = self.client.get(f"/api/maintenance/tickets/{ticket_id}", headers=self.headers)
        self.assertTrue(detail.json()["sla_breached"])
        self.assertTrue(detail.json()["escalated"])


if __name__ == "__main__":
    unittest.main()
