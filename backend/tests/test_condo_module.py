"""Tests d'intégration du module 7 (copropriété) et des compléments du
module 6 (bon de commande, contrôle qualité, planning Gantt).

Lancés sur SQLite, sans service externe, à travers l'API FastAPI.
"""

import os
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-mod7-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class CondoModuleTest(unittest.TestCase):
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

    # ------------------------------------------------------------------
    # Module 6 : compléments (bon de commande, contrôle qualité, Gantt)
    # ------------------------------------------------------------------
    def test_module6_purchase_order_quality_control_and_gantt(self):
        property_id = self.create_property()

        provider = self.client.post(
            "/api/maintenance/providers",
            headers=self.headers,
            json={"company_name": "ElecPro", "specialties": ["electricite"], "tariff_hourly": 55},
        )
        self.assertEqual(provider.status_code, 201, provider.text)
        provider_id = provider.json()["id"]

        ticket = self.client.post(
            "/api/maintenance/tickets",
            headers=self.headers,
            json={
                "source": "manager",
                "property_id": property_id,
                "category": "electricite",
                "urgency": "moyen",
                "title": "Panne tableau électrique",
            },
        )
        self.assertEqual(ticket.status_code, 201, ticket.text)
        ticket_id = ticket.json()["id"]

        for status in ["valide"]:
            update = self.client.post(
                f"/api/maintenance/tickets/{ticket_id}/status",
                headers=self.headers,
                json={"status": status},
            )
            self.assertEqual(update.status_code, 200, update.text)

        # Bon de commande.
        order = self.client.post(
            f"/api/maintenance/tickets/{ticket_id}/purchase-orders",
            headers=self.headers,
            json={"provider_id": provider_id, "amount": 280, "description": "Remplacement disjoncteur"},
        )
        self.assertEqual(order.status_code, 201, order.text)
        order_id = order.json()["id"]
        self.assertEqual(order.json()["status"], "draft")

        # Le ticket passe automatiquement à prestataire_assigne.
        detail = self.client.get(f"/api/maintenance/tickets/{ticket_id}", headers=self.headers)
        self.assertEqual(detail.json()["status"], "prestataire_assigne")

        confirm = self.client.put(
            f"/api/maintenance/purchase-orders/{order_id}/status",
            headers=self.headers,
            json={"status": "confirme"},
        )
        self.assertEqual(confirm.status_code, 200, confirm.text)
        self.assertEqual(confirm.json()["status"], "confirme")

        orders_list = self.client.get(f"/api/maintenance/tickets/{ticket_id}/purchase-orders", headers=self.headers)
        self.assertEqual(orders_list.status_code, 200)
        self.assertEqual(orders_list.json()["count"], 1)

        # Avancement jusqu'à contrôle qualité.
        for status in ["planned".replace("planned", "intervention_planifiee"), "en_cours", "termine", "controle_qualite"]:
            update = self.client.post(
                f"/api/maintenance/tickets/{ticket_id}/status",
                headers=self.headers,
                json={"status": status},
            )
            self.assertEqual(update.status_code, 200, update.text)

        # Contrôle qualité refusé -> retour en cours.
        qc_fail = self.client.post(
            f"/api/maintenance/tickets/{ticket_id}/quality-control",
            headers=self.headers,
            json={"passed": False, "comment": "Reprise nécessaire"},
        )
        self.assertEqual(qc_fail.status_code, 200, qc_fail.text)
        self.assertEqual(qc_fail.json()["status"], "en_cours")

        # Nouvelle boucle jusqu'à contrôle qualité puis validation -> clôturé.
        for status in ["termine", "controle_qualite"]:
            update = self.client.post(
                f"/api/maintenance/tickets/{ticket_id}/status",
                headers=self.headers,
                json={"status": status},
            )
            self.assertEqual(update.status_code, 200, update.text)
        qc_ok = self.client.post(
            f"/api/maintenance/tickets/{ticket_id}/quality-control",
            headers=self.headers,
            json={"passed": True, "comment": "Conforme"},
        )
        self.assertEqual(qc_ok.status_code, 200, qc_ok.text)
        self.assertEqual(qc_ok.json()["status"], "cloture")

        # Planning Gantt d'un projet de travaux.
        project = self.client.post(
            "/api/maintenance/projects",
            headers=self.headers,
            json={"property_id": property_id, "title": "Ravalement façade", "budget": 20000,
                  "start_date": "2024-01-01", "end_date": "2024-06-01"},
        )
        self.assertEqual(project.status_code, 201, project.text)
        project_id = project.json()["id"]
        self.client.post(
            f"/api/maintenance/projects/{project_id}/phases",
            headers=self.headers,
            json={"name": "Échafaudage", "start_date": "2024-01-01", "end_date": "2024-01-15", "progress": 100, "display_order": 1},
        )
        self.client.post(
            f"/api/maintenance/projects/{project_id}/phases",
            headers=self.headers,
            json={"name": "Ravalement", "start_date": "2024-01-16", "end_date": "2024-05-01", "progress": 40, "display_order": 2},
        )
        gantt = self.client.get(f"/api/maintenance/projects/{project_id}/gantt", headers=self.headers)
        self.assertEqual(gantt.status_code, 200, gantt.text)
        self.assertEqual(len(gantt.json()["phases"]), 2)
        self.assertEqual(gantt.json()["phases"][0]["name"], "Échafaudage")
        self.assertEqual(gantt.json()["phases"][1]["duration_days"], (
            __import__("datetime").date(2024, 5, 1) - __import__("datetime").date(2024, 1, 16)
        ).days)

    # ------------------------------------------------------------------
    # Module 7 : copropriété
    # ------------------------------------------------------------------
    def create_building(self):
        response = self.client.post(
            "/api/condo/buildings",
            headers=self.headers,
            json={
                "name": "Résidence Les Tilleuls",
                "address": "12 avenue des Tilleuls",
                "postal_code": "75012",
                "city": "Paris",
                "total_tantiemes": 1000,
                "syndic_name": "Syndic Pro",
                "syndic_email": "contact@syndicpro.fr",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _build_building_with_lots(self):
        building_id = self.create_building()
        detail = self.client.get(f"/api/condo/buildings/{building_id}", headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["lots"], [])

        lot1 = self.client.post(
            f"/api/condo/buildings/{building_id}/lots",
            headers=self.headers,
            json={"lot_number": "A101", "lot_type": "appartement", "tantiemes": 600, "floor": 1},
        )
        self.assertEqual(lot1.status_code, 201, lot1.text)
        lot2 = self.client.post(
            f"/api/condo/buildings/{building_id}/lots",
            headers=self.headers,
            json={"lot_number": "P01", "lot_type": "parking", "tantiemes": 400},
        )
        self.assertEqual(lot2.status_code, 201, lot2.text)

        balance = self.client.get(f"/api/condo/buildings/{building_id}/tantiemes-balance", headers=self.headers)
        self.assertEqual(balance.status_code, 200, balance.text)
        self.assertTrue(balance.json()["balanced"])
        self.assertEqual(balance.json()["allocated_tantiemes"], 1000)

        common_area = self.client.post(
            f"/api/condo/buildings/{building_id}/common-areas",
            headers=self.headers,
            json={"name": "Hall d'entrée", "area_m2": 30},
        )
        self.assertEqual(common_area.status_code, 201, common_area.text)

        lots = self.client.get(f"/api/condo/buildings/{building_id}/lots", headers=self.headers)
        self.assertEqual(lots.json()["count"], 2)
        return building_id, lot1.json()["id"], lot2.json()["id"]

    def test_module7_building_lots_and_common_areas(self):
        self._build_building_with_lots()

    def test_module7_charges_fund_calls_and_works_fund(self):
        building_id, lot1_id, lot2_id = self._build_building_with_lots()

        budget = self.client.post(
            f"/api/condo/buildings/{building_id}/budgets",
            headers=self.headers,
            json={
                "fiscal_year": 2026,
                "courante_amount": 8000,
                "exceptionnelle_amount": 2000,
                "travaux_amount": 0,
                "lines": [
                    {"category": "Entretien ascenseur", "charge_nature": "courante", "amount": 3000},
                    {"category": "Assurance immeuble", "charge_nature": "courante", "amount": 5000},
                ],
            },
        )
        self.assertEqual(budget.status_code, 201, budget.text)
        budget_id = budget.json()["id"]
        self.assertEqual(budget.json()["total_amount"], 10000)

        vote = self.client.post(f"/api/condo/budgets/{budget_id}/vote", headers=self.headers, json={})
        self.assertEqual(vote.status_code, 200, vote.text)
        self.assertEqual(vote.json()["status"], "vote")

        fund_call = self.client.post(
            f"/api/condo/buildings/{building_id}/fund-calls",
            headers=self.headers,
            json={"budget_id": budget_id, "period_label": "T1 2026", "call_date": "2026-01-05", "due_date": "2026-02-05"},
        )
        self.assertEqual(fund_call.status_code, 201, fund_call.text)
        fund_call_id = fund_call.json()["id"]
        self.assertEqual(fund_call.json()["total_amount"], 2500)  # 10000/4

        detail = self.client.get(f"/api/condo/fund-calls/{fund_call_id}", headers=self.headers)
        self.assertEqual(detail.status_code, 200, detail.text)
        lines = detail.json()["lines"]
        self.assertEqual(len(lines), 2)
        total_lines = round(sum(l["amount"] for l in lines), 2)
        self.assertEqual(total_lines, 2500)
        lot1_line = next(l for l in lines if l["lot_id"] == lot1_id)
        self.assertAlmostEqual(lot1_line["amount"], 1500, places=2)  # 60% de 2500

        send = self.client.post(f"/api/condo/fund-calls/{fund_call_id}/send", headers=self.headers)
        self.assertEqual(send.status_code, 200)
        self.assertEqual(send.json()["status"], "envoye")

        pay = self.client.post(
            f"/api/condo/fund-calls/lines/{lot1_line['id']}/pay",
            headers=self.headers,
            json={"amount": 1500},
        )
        self.assertEqual(pay.status_code, 200, pay.text)
        self.assertEqual(pay.json()["status"], "paye")

        fund_call_after = self.client.get(f"/api/condo/fund-calls/{fund_call_id}", headers=self.headers)
        self.assertEqual(fund_call_after.json()["status"], "partiellement_paye")

        repartition = self.client.get(
            f"/api/condo/buildings/{building_id}/charges-repartition?fiscal_year=2026", headers=self.headers
        )
        self.assertEqual(repartition.status_code, 200, repartition.text)
        self.assertEqual(repartition.json()["total_paid"], 1500)

        # Fonds travaux.
        works_fund = self.client.get(f"/api/condo/buildings/{building_id}/works-fund", headers=self.headers)
        self.assertEqual(works_fund.status_code, 200)
        self.assertEqual(works_fund.json()["balance"], 0)

        contribute = self.client.post(
            f"/api/condo/buildings/{building_id}/works-fund/movements",
            headers=self.headers,
            json={"movement_type": "cotisation", "amount": 500, "movement_date": "2026-01-10"},
        )
        self.assertEqual(contribute.status_code, 201, contribute.text)
        self.assertEqual(contribute.json()["balance"], 500)

        withdraw = self.client.post(
            f"/api/condo/buildings/{building_id}/works-fund/movements",
            headers=self.headers,
            json={"movement_type": "prelevement", "amount": 200, "movement_date": "2026-02-01", "description": "Ravalement"},
        )
        self.assertEqual(withdraw.status_code, 201, withdraw.text)
        self.assertEqual(withdraw.json()["balance"], 300)

        return building_id, lot1_id, lot2_id

    def test_module7_general_assembly_workflow(self):
        building_id, lot1_id, lot2_id = self._build_building_with_lots()

        assembly = self.client.post(
            f"/api/condo/buildings/{building_id}/assemblies",
            headers=self.headers,
            json={
                "assembly_type": "ordinaire",
                "meeting_date": "2026-03-15T18:00:00",
                "location": "Salle commune",
                "agenda_items": [
                    {"title": "Approbation des comptes", "position": 1},
                    {"title": "Vote du budget prévisionnel", "position": 2},
                ],
            },
        )
        self.assertEqual(assembly.status_code, 201, assembly.text)
        assembly_id = assembly.json()["id"]
        self.assertEqual(assembly.json()["status"], "draft")

        convene = self.client.post(f"/api/condo/assemblies/{assembly_id}/convene", headers=self.headers, json={})
        self.assertEqual(convene.status_code, 200, convene.text)
        self.assertEqual(convene.json()["status"], "convoquee")

        attendance = self.client.post(
            f"/api/condo/assemblies/{assembly_id}/attendance",
            headers=self.headers,
            json={"records": [
                {"lot_id": lot1_id, "status": "present"},
                {"lot_id": lot2_id, "status": "absent"},
            ]},
        )
        self.assertEqual(attendance.status_code, 200, attendance.text)
        self.assertTrue(attendance.json()["quorum_met"])  # 600/1000 > 500
        self.assertEqual(attendance.json()["tantiemes_present"], 600)

        resolution = self.client.post(
            f"/api/condo/assemblies/{assembly_id}/resolutions",
            headers=self.headers,
            json={"title": "Approbation des comptes 2025", "majority_required": "article_24"},
        )
        self.assertEqual(resolution.status_code, 201, resolution.text)
        resolution_id = resolution.json()["id"]

        vote = self.client.post(
            f"/api/condo/resolutions/{resolution_id}/vote",
            headers=self.headers,
            json={"votes": [
                {"lot_id": lot1_id, "choice": "pour"},
                {"lot_id": lot2_id, "choice": "contre"},
            ]},
        )
        self.assertEqual(vote.status_code, 200, vote.text)
        self.assertEqual(vote.json()["status"], "adoptee")  # 600 pour > 400 contre

        resolution2 = self.client.post(
            f"/api/condo/assemblies/{assembly_id}/resolutions",
            headers=self.headers,
            json={"title": "Ravalement de façade", "majority_required": "article_25"},
        )
        resolution2_id = resolution2.json()["id"]
        vote2 = self.client.post(
            f"/api/condo/resolutions/{resolution2_id}/vote",
            headers=self.headers,
            json={"votes": [
                {"lot_id": lot1_id, "choice": "pour"},
                {"lot_id": lot2_id, "choice": "contre"},
            ]},
        )
        self.assertEqual(vote2.status_code, 200, vote2.text)
        # Article 25 exige > 500/1000 : 600 pour un total du syndicat de 1000 -> adoptée.
        self.assertEqual(vote2.json()["status"], "adoptee")

        close = self.client.post(
            f"/api/condo/assemblies/{assembly_id}/close",
            headers=self.headers,
            json={"minutes": "Séance levée à 20h."},
        )
        self.assertEqual(close.status_code, 200, close.text)
        self.assertEqual(close.json()["status"], "cloturee")

        minutes = self.client.get(f"/api/condo/assemblies/{assembly_id}/minutes", headers=self.headers)
        self.assertEqual(minutes.status_code, 200, minutes.text)
        self.assertEqual(len(minutes.json()["resolutions"]), 2)
        self.assertEqual(len(minutes.json()["attendance"]), 2)

    def test_module7_council_and_maintenance_book(self):
        building_id, lot1_id, _ = self._build_building_with_lots()

        member = self.client.post(
            f"/api/condo/buildings/{building_id}/council-members",
            headers=self.headers,
            json={"full_name": "Jean Dupont", "role": "president"},
        )
        self.assertEqual(member.status_code, 201, member.text)

        meeting = self.client.post(
            f"/api/condo/buildings/{building_id}/council-meetings",
            headers=self.headers,
            json={"meeting_date": "2026-02-01T10:00:00", "title": "Réunion préparatoire AG", "agenda": "Préparer l'ordre du jour"},
        )
        self.assertEqual(meeting.status_code, 201, meeting.text)
        meeting_id = meeting.json()["id"]

        minutes = self.client.put(
            f"/api/condo/council-meetings/{meeting_id}/minutes",
            headers=self.headers,
            json={"minutes": "Ordre du jour validé à l'unanimité."},
        )
        self.assertEqual(minutes.status_code, 200, minutes.text)
        self.assertIn("validé", minutes.json()["minutes"])

        book_entry = self.client.post(
            f"/api/condo/buildings/{building_id}/book-entries",
            headers=self.headers,
            json={
                "entry_type": "contrat",
                "title": "Contrat entretien ascenseur",
                "entry_date": "2026-01-01",
                "provider_name": "AscenseurPlus",
                "cost": 1200,
                "contract_status": "en_cours",
            },
        )
        self.assertEqual(book_entry.status_code, 201, book_entry.text)

        entries = self.client.get(f"/api/condo/buildings/{building_id}/book-entries", headers=self.headers)
        self.assertEqual(entries.status_code, 200)
        self.assertEqual(entries.json()["count"], 1)

    def test_module7_accounting(self):
        building_id, lot1_id, _ = self._build_building_with_lots()

        standard = self.client.post("/api/condo/accounts/standard", headers=self.headers)
        self.assertEqual(standard.status_code, 200, standard.text)
        self.assertGreater(standard.json()["created"], 0)

        entry = self.client.post(
            f"/api/condo/buildings/{building_id}/journal-entries",
            headers=self.headers,
            json={
                "entry_date": "2026-01-15",
                "label": "Appel de fonds T1 2026",
                "lines": [
                    {"account_code": "45", "debit": 2500, "lot_id": lot1_id, "label": "Quote-part lot A101"},
                    {"account_code": "70", "credit": 2500, "label": "Produits appel de fonds"},
                ],
            },
        )
        self.assertEqual(entry.status_code, 201, entry.text)
        entry_id = entry.json()["id"]

        validate = self.client.post(f"/api/condo/journal-entries/{entry_id}/validate", headers=self.headers)
        self.assertEqual(validate.status_code, 200, validate.text)
        self.assertEqual(validate.json()["status"], "validated")

        ledger = self.client.get(f"/api/condo/buildings/{building_id}/general-ledger", headers=self.headers)
        self.assertEqual(ledger.status_code, 200, ledger.text)
        self.assertEqual(len(ledger.json()["lines"]), 2)

        balance_sheet = self.client.get(f"/api/condo/buildings/{building_id}/balance-sheet", headers=self.headers)
        self.assertEqual(balance_sheet.status_code, 200, balance_sheet.text)
        self.assertEqual(balance_sheet.json()["assets"], 2500)
        self.assertEqual(balance_sheet.json()["income"], 2500)

        # Écriture déséquilibrée rejetée.
        bad_entry = self.client.post(
            f"/api/condo/buildings/{building_id}/journal-entries",
            headers=self.headers,
            json={
                "entry_date": "2026-01-16",
                "label": "Écriture invalide",
                "lines": [
                    {"account_code": "45", "debit": 100},
                    {"account_code": "70", "credit": 50},
                ],
            },
        )
        self.assertEqual(bad_entry.status_code, 400)


if __name__ == "__main__":
    unittest.main()
