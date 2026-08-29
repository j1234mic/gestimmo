"""Tests des modules complémentaires extension (18 à 31)."""
import os
import tempfile
import unittest

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-extension-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class ExtensionModulesTest(unittest.TestCase):
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

    def create_property(self) -> int:
        response = self.client.post(
            "/api/properties/",
            headers=self.headers,
            json={
                "type": "apartment",
                "title": "Appartement extension",
                "address": "5 rue du Test",
                "postal_code": "75005",
                "city": "Paris",
                "rent_price": 800,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def create_owner(self) -> int:
        response = self.client.post(
            "/api/owners/",
            headers=self.headers,
            json={"first_name": "Marc", "last_name": "Laurent", "email": "marc.laurent@example.com"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def test_extension_indicators(self):
        property_id = self.create_property()
        owner_id = self.create_owner()

        listing = self.client.post(
            "/api/extension/short-term-listings",
            headers=self.headers,
            json={"property_id": property_id, "platform": "airbnb", "nightly_rate": 100, "cleaning_fee": 20},
        )
        self.assertEqual(listing.status_code, 201, listing.text)
        listing_id = listing.json()["id"]

        booking = self.client.post(
            "/api/extension/short-term-bookings",
            headers=self.headers,
            json={
                "listing_id": listing_id,
                "check_in": "2026-07-01",
                "check_out": "2026-07-05",
                "guest_name": "Indicateur",
                "amount": 400,
                "cleaning_fee": 20,
                "tax_amount": 20,
                "status": "confirme",
            },
        )
        self.assertEqual(booking.status_code, 201, booking.text)

        avail = self.client.get(
            f"/api/extension/short-term-listings/{listing_id}/availability",
            headers=self.headers,
            params={"date_from": "2026-07-01", "date_to": "2026-07-06"},
        )
        self.assertEqual(avail.status_code, 200)
        self.assertEqual(avail.json()["available_nights"], 2)

        report = self.client.get(
            f"/api/extension/short-term-listings/{listing_id}/report",
            headers=self.headers,
            params={"date_from": "2026-07-01", "date_to": "2026-07-06"},
        )
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()["sold_nights"], 4)
        self.assertEqual(report.json()["occupancy_rate"], 0.8)

        meter = self.client.post(
            "/api/extension/utility-meters",
            headers=self.headers,
            json={"property_id": property_id, "meter_type": "electricite", "unit": "kWh"},
        )
        self.assertEqual(meter.status_code, 201, meter.text)
        r1 = self.client.post(
            "/api/extension/utility-readings",
            headers=self.headers,
            json={"meter_id": meter.json()["id"], "reading_date": "2026-01-01", "value": 100},
        )
        r2 = self.client.post(
            "/api/extension/utility-readings",
            headers=self.headers,
            json={"meter_id": meter.json()["id"], "reading_date": "2026-02-01", "value": 250},
        )
        consumption = self.client.get(
            f"/api/extension/utility-meters/{meter.json()['id']}/consumption",
            headers=self.headers,
            params={"reading_from": r1.json()["id"], "reading_to": r2.json()["id"]},
        )
        self.assertEqual(consumption.status_code, 200)
        self.assertEqual(consumption.json()["consumption"], 150)

        audit = self.client.post(
            "/api/extension/energy-audits",
            headers=self.headers,
            json={"property_id": property_id, "audit_date": "2026-01-01", "energy_class_before": "E", "energy_class_after": "C"},
        )
        project = self.client.post(
            "/api/extension/energy-projects",
            headers=self.headers,
            json={"audit_id": audit.json()["id"], "property_id": property_id, "title": "Isolation", "budget": 10000, "estimated_savings": 2000},
        )
        self.client.post(
            "/api/extension/energy-grants",
            headers=self.headers,
            json={"project_id": project.json()["id"], "program_name": "Aide", "amount": 2000, "status": "accepted"},
        )
        roi = self.client.get(f"/api/extension/energy-projects/{project.json()['id']}/roi", headers=self.headers)
        self.assertEqual(roi.status_code, 200)
        self.assertEqual(roi.json()["net_cost"], 8000)
        self.assertEqual(roi.json()["payback_years"], 4)

        self.client.post(
            "/api/extension/satisfaction-surveys",
            headers=self.headers,
            json={"respondent_type": "tenant", "respondent_id": 1, "property_id": property_id, "nps_score": 10, "csat": 5},
        )
        summary = self.client.get("/api/extension/satisfaction-summary", headers=self.headers)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["nps_score"], 100.0)

        task = self.client.post(
            "/api/extension/tasks",
            headers=self.headers,
            json={"entity_type": "property", "entity_id": property_id, "title": "Suivi", "status": "a_faire"},
        )
        self.assertEqual(task.status_code, 201, task.text)
        board = self.client.get("/api/extension/tasks/board", headers=self.headers)
        self.assertEqual(board.status_code, 200)
        self.assertEqual(len(board.json()["data"]["a_faire"]), 1)

        opp = self.client.post(
            "/api/extension/acquisition-opportunities",
            headers=self.headers,
            json={"address": "2 rue", "city": "Lyon", "expected_price": 200000, "market_price": 240000, "potential_rent": 1000, "total_area": 80},
        )
        self.assertEqual(opp.status_code, 201, opp.text)
        analysis = self.client.get(f"/api/extension/acquisition-opportunities/{opp.json()['id']}/analysis", headers=self.headers)
        self.assertEqual(analysis.status_code, 200)
        self.assertEqual(analysis.json()["price_per_sqm"], 2500.0)
        self.assertLessEqual(analysis.json()["score"], 100)

    def test_short_term_and_legal_contentieux(self):
        property_id = self.create_property()

        listing = self.client.post(
            "/api/extension/short-term-listings",
            headers=self.headers,
            json={
                "property_id": property_id,
                "platform": "airbnb",
                "nightly_rate": 100,
                "min_nights": 2,
                "max_guests": 3,
                "cleaning_fee": 20,
            },
        )
        self.assertEqual(listing.status_code, 201, listing.text)
        listing_id = listing.json()["id"]

        quote = self.client.get(
            f"/api/extension/short-term-listings/{listing_id}/quote",
            headers=self.headers,
            params={"nights": 5},
        )
        self.assertEqual(quote.status_code, 200, quote.text)
        self.assertEqual(quote.json()["amount"], 500)

        booking = self.client.post(
            "/api/extension/short-term-bookings",
            headers=self.headers,
            json={
                "listing_id": listing_id,
                "check_in": "2026-07-10",
                "check_out": "2026-07-15",
                "guest_name": "Alice",
                "guests": 2,
                "amount": 500,
                "cleaning_fee": 20,
                "tax_amount": 20,
                "status": "confirme",
            },
        )
        self.assertEqual(booking.status_code, 201, booking.text)
        self.assertEqual(booking.json()["status"], "confirme")

        price_rule = self.client.post(
            "/api/extension/short-term-price-rules",
            headers=self.headers,
            json={
                "listing_id": listing_id,
                "label": "Haute saison",
                "date_from": "2026-07-01",
                "date_to": "2026-08-31",
                "rate_multiplier": 1.4,
            },
        )
        self.assertEqual(price_rule.status_code, 201, price_rule.text)

        legal = self.client.post(
            "/api/extension/legal-cases",
            headers=self.headers,
            json={
                "case_type": "impaye",
                "subject": "Retard de paiement",
                "property_id": property_id,
                "amount_in_dispute": 1200,
                "court": "TJ Paris",
            },
        )
        self.assertEqual(legal.status_code, 201, legal.text)
        case_id = legal.json()["id"]
        self.assertTrue(legal.json()["reference"].startswith("LGL-"))

        action = self.client.post(
            "/api/extension/legal-actions",
            headers=self.headers,
            json={"case_id": case_id, "action_type": "mise_en_demeure", "action_date": "2026-06-01"},
        )
        self.assertEqual(action.status_code, 201, action.text)

        actions = self.client.get(f"/api/extension/legal-cases/{case_id}/actions", headers=self.headers)
        self.assertEqual(actions.status_code, 200)
        self.assertEqual(actions.json()["total"], 1)

    def test_fiscal_loan_services_access_and_utility(self):
        property_id = self.create_property()
        owner_id = self.create_owner()

        fiscal = self.client.post(
            "/api/extension/fiscal-records",
            headers=self.headers,
            json={
                "owner_id": owner_id,
                "property_id": property_id,
                "fiscal_year": 2025,
                "regime": "reel",
                "rental_income": 12000,
                "deductible_charges": 3000,
                "amortization": 1000,
            },
        )
        self.assertEqual(fiscal.status_code, 201, fiscal.text)
        self.assertEqual(fiscal.json()["result"], 8000)
        self.assertEqual(fiscal.json()["tax_amount"], 2400)

        loan = self.client.post(
            "/api/extension/loans",
            headers=self.headers,
            json={
                "owner_id": owner_id,
                "property_id": property_id,
                "lender": "Banque Test",
                "loan_type": "classique",
                "principal": 100000,
                "interest_rate": 3,
                "duration_months": 24,
                "start_date": "2026-01-01",
            },
        )
        self.assertEqual(loan.status_code, 201, loan.text)
        self.assertGreater(loan.json()["monthly_payment"], 0)
        schedule = self.client.get(f"/api/extension/loans/{loan.json()['id']}/schedule", headers=self.headers)
        self.assertEqual(schedule.status_code, 200)
        self.assertEqual(schedule.json()["total"], 24)

        agreement = self.client.post(
            "/api/extension/service-agreements",
            headers=self.headers,
            json={"property_id": property_id, "service_type": "menage", "monthly_amount": 80, "status": "actif"},
        )
        self.assertEqual(agreement.status_code, 201, agreement.text)
        invoice = self.client.post(
            "/api/extension/service-invoices",
            headers=self.headers,
            json={"agreement_id": agreement.json()["id"], "period": "2026-08", "amount": 80, "vat_amount": 8},
        )
        self.assertEqual(invoice.status_code, 201, invoice.text)
        self.assertEqual(invoice.json()["total"], 88)

        key = self.client.post(
            "/api/extension/access-keys",
            headers=self.headers,
            json={"property_id": property_id, "label": "Clé A", "key_type": "cle", "location": "Boîte 1"},
        )
        self.assertEqual(key.status_code, 201, key.text)
        key_id = key.json()["id"]
        op = self.client.post(
            "/api/extension/key-operations",
            headers=self.headers,
            json={"key_id": key_id, "action": "issue", "borrowed_by": "Locataire"},
        )
        self.assertEqual(op.status_code, 201, op.text)
        self.assertEqual(self.client.get(
            f"/api/extension/access-keys/{key_id}/operations", headers=self.headers
        ).json()["total"], 1)

        meter = self.client.post(
            "/api/extension/utility-meters",
            headers=self.headers,
            json={"property_id": property_id, "meter_type": "electricite", "initial_reading": 1000},
        )
        self.assertEqual(meter.status_code, 201, meter.text)
        meter_id = meter.json()["id"]
        reading = self.client.post(
            "/api/extension/utility-readings",
            headers=self.headers,
            json={"meter_id": meter_id, "reading_date": "2026-08-01", "value": 1250, "source": "app"},
        )
        self.assertEqual(reading.status_code, 201, reading.text)

        bill = self.client.post(
            "/api/extension/utility-bills",
            headers=self.headers,
            json={"property_id": property_id, "period": "2026-08", "utility_type": "electricite", "amount": 120, "consumption": 250, "unit_price": 0.48},
        )
        self.assertEqual(bill.status_code, 201, bill.text)

    def test_development_funds_energy_and_satisfaction(self):
        property_id = self.create_property()

        program = self.client.post(
            "/api/extension/development-programs",
            headers=self.headers,
            json={"name": "Les Lilas", "program_type": "residential", "city": "Lille", "total_units": 2, "developer": "PromoTest"},
        )
        self.assertEqual(program.status_code, 201, program.text)
        program_id = program.json()["id"]

        unit = self.client.post(
            "/api/extension/development-units",
            headers=self.headers,
            json={"program_id": program_id, "label": "A01", "unit_type": "apartment", "surface": 55, "price_ht": 200000, "tva_rate": 20},
        )
        self.assertEqual(unit.status_code, 201, unit.text)
        self.assertEqual(unit.json()["price_ttc"], 240000)
        unit_id = unit.json()["id"]

        reservation = self.client.post(
            "/api/extension/vefa-reservations",
            headers=self.headers,
            json={"unit_id": unit_id, "buyer_name": "Client VEFA", "deposit": 5000, "reservation_date": "2026-09-01"},
        )
        self.assertEqual(reservation.status_code, 201, reservation.text)

        fund = self.client.post(
            "/api/extension/investment-funds",
            headers=self.headers,
            json={"name": "Fonds Pierres", "fund_type": "scpi", "nav": 750, "total_capital": 500000},
        )
        self.assertEqual(fund.status_code, 201, fund.text)
        fund_id = fund.json()["id"]
        sub = self.client.post(
            "/api/extension/fund-subscriptions",
            headers=self.headers,
            json={"fund_id": fund_id, "investor_name": "Investisseur A", "amount": 15000, "units": 20, "subscription_date": "2026-08-01"},
        )
        self.assertEqual(sub.status_code, 201, sub.text)
        dist = self.client.post(
            "/api/extension/fund-distributions",
            headers=self.headers,
            json={"fund_id": fund_id, "period": "2026-T3", "amount_per_unit": 12, "total_amount": 5000},
        )
        self.assertEqual(dist.status_code, 201, dist.text)

        audit = self.client.post(
            "/api/extension/energy-audits",
            headers=self.headers,
            json={"property_id": property_id, "audit_date": "2026-06-01", "energy_class_before": "E", "energy_class_after": "C"},
        )
        self.assertEqual(audit.status_code, 201, audit.text)
        audit_id = audit.json()["id"]
        project = self.client.post(
            "/api/extension/energy-projects",
            headers=self.headers,
            json={"audit_id": audit_id, "property_id": property_id, "title": "Isolation", "budget": 12000, "estimated_savings": 1500, "status": "proposed"},
        )
        self.assertEqual(project.status_code, 201, project.text)
        grant = self.client.post(
            "/api/extension/energy-grants",
            headers=self.headers,
            json={"project_id": project.json()["id"], "program_name": "MaPrimeRénov", "amount": 4000, "status": "accepted"},
        )
        self.assertEqual(grant.status_code, 201, grant.text)

        survey = self.client.post(
            "/api/extension/satisfaction-surveys",
            headers=self.headers,
            json={"respondent_type": "tenant", "respondent_id": 1, "property_id": property_id, "nps_score": 9, "csat": 5, "comment": "Très bien"},
        )
        self.assertEqual(survey.status_code, 201, survey.text)

    def test_public_portal(self):
        property_id = self.create_property()

        page = self.client.post(
            "/api/extension/public-pages",
            headers=self.headers,
            json={"title": "À propos", "slug": "a-propos", "content": "Texte", "status": "published"},
        )
        self.assertEqual(page.status_code, 201, page.text)

        agent = self.client.post(
            "/api/extension/public-agents",
            headers=self.headers,
            json={"name": "Aline Admin", "role": "Gestionnaire", "active": True},
        )
        self.assertEqual(agent.status_code, 201, agent.text)

        testimonial = self.client.post(
            "/api/extension/public-testimonials",
            headers=self.headers,
            json={"client_name": "Client A", "content": "Très satisfait", "rating": 5, "published": True},
        )
        self.assertEqual(testimonial.status_code, 201, testimonial.text)

        news = self.client.post(
            "/api/extension/public-news",
            headers=self.headers,
            json={"title": "Actualité", "slug": "actualite-1", "content": "Contenu", "status": "published"},
        )
        self.assertEqual(news.status_code, 201, news.text)

        lead = self.client.post(
            "/api/public-portal/leads",
            json={
                "request_type": "visit",
                "name": "Visiteur B",
                "email": "visitor@example.com",
                "property_id": property_id,
                "preferred_date": "2026-09-12",
            },
        )
        self.assertEqual(lead.status_code, 200, lead.text)
        reference = lead.json()["reference"]
        token = lead.json()["tracking_token"]
        self.assertTrue(reference.startswith("PUB-"))

        tracked = self.client.get(f"/api/public-portal/leads/{reference}", params={"token": token})
        self.assertEqual(tracked.status_code, 200, tracked.text)
        self.assertEqual(tracked.json()["data"]["status"], "nouveau")

        cancel = self.client.post(f"/api/public-portal/leads/{reference}/cancel", params={"token": token})
        self.assertEqual(cancel.status_code, 200, cancel.text)
        self.assertEqual(cancel.json()["status"], "archive")

        admin_leads = self.client.get("/api/extension/public-leads", headers=self.headers)
        self.assertEqual(admin_leads.status_code, 200)
        self.assertEqual(admin_leads.json()["total"], 1)

        props = self.client.get("/api/public-portal/properties", params={"city": "Paris"})
        self.assertEqual(props.status_code, 200)
        self.assertEqual(props.json()["total"], 1)

        detail = self.client.get(f"/api/public-portal/properties/{property_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["title"], "Appartement extension")

        agent_map = self.client.get("/api/public-portal/map")
        self.assertEqual(agent_map.status_code, 200)
        self.assertEqual(agent_map.json()["total"], 0)

        agents = self.client.get("/api/public-portal/agents")
        self.assertEqual(agents.json()["total"], 1)
        testimonials = self.client.get("/api/public-portal/testimonials")
        self.assertEqual(testimonials.json()["total"], 1)
        pages = self.client.get("/api/public-portal/pages")
        self.assertEqual(pages.json()["total"], 1)
        news_list = self.client.get("/api/public-portal/news")
        self.assertEqual(news_list.json()["total"], 1)

    def test_tasks_and_acquisition_sourcing(self):
        task = self.client.post(
            "/api/extension/tasks",
            headers=self.headers,
            json={"entity_type": "property", "entity_id": 1, "title": "Relancer propriétaire", "priority": "haute", "due_date": "2026-09-10T10:00:00Z"},
        )
        self.assertEqual(task.status_code, 201, task.text)
        task_id = task.json()["id"]

        comment = self.client.post(
            f"/api/extension/tasks/{task_id}/comments",
            headers=self.headers,
            json={"author": "Gestionnaire", "body": "Fait"},
        )
        self.assertEqual(comment.status_code, 201, comment.text)

        update = self.client.put(
            f"/api/extension/tasks/{task_id}",
            headers=self.headers,
            json={"status": "terminee"},
        )
        self.assertEqual(update.status_code, 200, update.text)
        self.assertEqual(update.json()["status"], "terminee")
        self.assertIsNotNone(update.json()["completed_at"])

        opportunity = self.client.post(
            "/api/extension/acquisition-opportunities",
            headers=self.headers,
            json={
                "source": "grille",
                "address": "8 rue Test",
                "postal_code": "31000",
                "city": "Toulouse",
                "expected_price": 150000,
                "market_price": 180000,
                "potential_rent": 900,
                "total_area": 60,
                "status": "prospection",
                "notes": "Oppo test",
            },
        )
        self.assertEqual(opportunity.status_code, 201, opportunity.text)
        opp_id = opportunity.json()["id"]
        self.assertTrue(opportunity.json()["reference"].startswith("GAME-"))

        diligence = self.client.post(
            "/api/extension/due-diligence-items",
            headers=self.headers,
            json={"opportunity_id": opp_id, "label": "Cadastre", "category": "juridique", "due_date": "2026-09-15"},
        )
        self.assertEqual(diligence.status_code, 201, diligence.text)

        listing = self.client.get(
            f"/api/extension/acquisition-opportunities/{opp_id}/due-diligence",
            headers=self.headers,
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["total"], 1)


if __name__ == "__main__":
    unittest.main()
