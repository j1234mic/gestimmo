"""Tests d'intégration du module 8 : CRM et gestion commerciale.

Lancés sur SQLite, sans service externe, à travers l'API FastAPI : prospects
et score de qualité, pipeline/Kanban, visites (disponibilités, confirmation,
rappels, compte-rendu, agenda), matching automatique, diffusion multi-portails
avec statistiques, transactions de vente (offre, compromis, conditions
suspensives, acte, commission) et performance des agents.
"""

import os
import tempfile
import unittest
from datetime import date, timedelta

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-mod8-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class CrmModuleTest(unittest.TestCase):
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
        self.property_id = self._create_property()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    def _create_property(self, **overrides) -> int:
        payload = {
            "type": "apartment",
            "title": "Appartement CRM",
            "address": "10 rue du Commerce",
            "postal_code": "75015",
            "city": "Paris",
            "rent_price": 950,
            "charges": 90,
            "living_area": 55,
            "rooms": 3,
            "bedrooms": 2,
        }
        payload.update(overrides)
        response = self.client.post("/api/properties/", headers=self.headers, json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _create_prospect(self, **overrides) -> dict:
        payload = {
            "first_name": "Camille",
            "last_name": "Durand",
            "email": "camille.durand@example.fr",
            "phone": "0601020304",
            "prospect_type": "locataire",
            "source": "site_web",
            "budget_min": 800,
            "budget_max": 1000,
            "search_criteria": {
                "property_types": ["apartment"],
                "cities": ["Paris"],
                "postal_codes": ["75015"],
                "min_surface": 40,
                "min_rooms": 2,
            },
            "assigned_agent": "gestionnaire@immogest.com",
        }
        payload.update(overrides)
        response = self.client.post("/api/crm/prospects", headers=self.headers, json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    # ------------------------------------------------------------------
    # Prospects : fiche, source, critères, budget, score de qualité
    # ------------------------------------------------------------------
    def test_prospect_creation_with_explainable_score(self):
        prospect = self._create_prospect()
        self.assertTrue(prospect["reference"].startswith("PRO-"))
        self.assertEqual(prospect["status"], "actif")
        self.assertGreater(prospect["quality_score"], 0)
        parts = {p["label"]: p for p in prospect["score_detail"]["parts"]}
        self.assertIn("Complétude de la fiche", parts)
        self.assertIn("Qualité de la source", parts)
        self.assertIn("Engagement", parts)
        self.assertEqual(prospect["quality_score"], prospect["score_detail"]["total"])
        # Complétude maximale : email, téléphone, budget, critères et agent
        self.assertEqual(parts["Complétude de la fiche"]["points"], 40)

    def test_prospect_filters_and_rescoring(self):
        prospect = self._create_prospect()
        # Mise à jour : perte du téléphone et de l'email → score complétude réduit
        response = self.client.put(
            f"/api/crm/prospects/{prospect['id']}",
            headers=self.headers,
            json={"email": None, "phone": None},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertLess(body["quality_score"], prospect["quality_score"])

        listing = self.client.get(
            "/api/crm/prospects", headers=self.headers, params={"min_score": 90}
        )
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["count"], 0)

        search = self.client.get(
            "/api/crm/prospects", headers=self.headers, params={"search": "Durand"}
        )
        self.assertEqual(search.json()["count"], 1)

        response = self.client.post(
            f"/api/crm/prospects/{prospect['id']}/score", headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("detail", response.json())

    def test_prospect_status_workflow(self):
        prospect = self._create_prospect()
        response = self.client.put(
            f"/api/crm/prospects/{prospect['id']}/status",
            headers=self.headers,
            json={"status": "perdu", "lost_reason": "budget trop faible"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "perdu")
        self.assertEqual(response.json()["lost_reason"], "budget trop faible")

    # ------------------------------------------------------------------
    # Pipeline : étapes configurables, Kanban, probabilité, valeur
    # ------------------------------------------------------------------
    def test_default_pipeline_stages_seeded_and_configurable(self):
        response = self.client.get("/api/crm/pipeline/stages", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        stages = response.json()["data"]
        self.assertEqual(len(stages), 8)
        self.assertEqual(stages[0]["name"], "Premier contact")
        self.assertEqual(stages[6]["name"], "Bail signé / Vente conclue")
        self.assertTrue(stages[6]["is_won"])
        self.assertEqual(stages[6]["probability"], 1.0)
        self.assertTrue(stages[7]["is_lost"])

        # Ajout d'une étape personnalisée
        response = self.client.post(
            "/api/crm/pipeline/stages",
            headers=self.headers,
            json={"name": "Négociation", "display_order": 5, "probability": 0.6},
        )
        self.assertEqual(response.status_code, 201)
        custom_id = response.json()["id"]
        response = self.client.put(
            f"/api/crm/pipeline/stages/{custom_id}",
            headers=self.headers,
            json={"probability": 0.65, "color": "#f59e0b"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["probability"], 0.65)

    def test_deal_lifecycle_and_kanban(self):
        prospect = self._create_prospect()
        response = self.client.post(
            "/api/crm/deals",
            headers=self.headers,
            json={
                "title": "Location T3 Paris 15e",
                "prospect_id": prospect["id"],
                "property_id": self.property_id,
                "estimated_value": 950,
                "expected_commission": 85,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        deal = response.json()
        self.assertEqual(deal["status"], "open")
        self.assertEqual(deal["stage_name"], "Premier contact")
        self.assertEqual(deal["probability"], 0.1)  # Probabilité de l'étape initiale

        stages = self.client.get("/api/crm/pipeline/stages", headers=self.headers).json()["data"]
        qualified = next(s for s in stages if s["name"] == "Qualification")

        # Déplacement d'étape avec historique
        response = self.client.post(
            f"/api/crm/deals/{deal['id']}/stage",
            headers=self.headers,
            json={"stage_id": qualified["id"], "comment": "Dossier qualifié"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["probability"], 0.25)
        history = self.client.get(f"/api/crm/deals/{deal['id']}", headers=self.headers).json()
        self.assertEqual(len(history["stage_history"]), 2)

        # Kanban : colonnes avec valeur totale et pondérée
        kanban = self.client.get("/api/crm/pipeline/kanban", headers=self.headers).json()
        self.assertEqual(len(kanban["columns"]), 8)
        self.assertEqual(kanban["totals"]["open_deals"], 1)
        self.assertEqual(kanban["totals"]["total_value"], 950)
        self.assertAlmostEqual(kanban["totals"]["weighted_value"], 950 * 0.25)

        # Conclusion : étape gagnée → prospect converti
        won_stage = next(s for s in stages if s["is_won"])
        response = self.client.post(
            f"/api/crm/deals/{deal['id']}/stage", headers=self.headers, json={"stage_id": won_stage["id"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "won")
        prospect_after = self.client.get(
            f"/api/crm/prospects/{prospect['id']}", headers=self.headers
        ).json()
        self.assertEqual(prospect_after["status"], "converti")
        self.assertIsNotNone(prospect_after["converted_at"])

        # Le Kanban n'affiche plus le dossier gagné (colonne gagnée exclue des ouverts)
        kanban_after = self.client.get("/api/crm/pipeline/kanban", headers=self.headers).json()
        self.assertEqual(kanban_after["totals"]["open_deals"], 0)

    # ------------------------------------------------------------------
    # Visites : disponibilités, planification, confirmation, rappels,
    # compte-rendu, retour visiteur, agenda
    # ------------------------------------------------------------------
    def test_visit_full_workflow(self):
        prospect = self._create_prospect()
        visit_day = date.today() + timedelta(days=7)

        # Disponibilités du bien
        response = self.client.post(
            f"/api/crm/properties/{self.property_id}/availabilities",
            headers=self.headers,
            json={
                "available_date": visit_day.isoformat(),
                "slots": [{"start": "10:00", "end": "11:00"}, {"start": "14:00", "end": "15:00"}],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        slots = response.json()["data"]
        self.assertEqual(len(slots), 2)

        free = self.client.get(
            f"/api/crm/properties/{self.property_id}/availabilities",
            headers=self.headers,
            params={"only_free": True},
        ).json()
        self.assertEqual(free["count"], 2)

        # Planification sur un créneau (confirmation automatique)
        response = self.client.post(
            "/api/crm/visits",
            headers=self.headers,
            json={
                "property_id": self.property_id,
                "prospect_id": prospect["id"],
                "scheduled_date": visit_day.isoformat(),
                "start_time": "10:00",
                "end_time": "11:00",
                "availability_id": slots[0]["id"],
                "auto_confirm": True,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        visit = response.json()
        self.assertEqual(visit["status"], "confirmee")
        self.assertIsNotNone(visit.get("confirmed_at"))

        # Le créneau est réservé
        free = self.client.get(
            f"/api/crm/properties/{self.property_id}/availabilities",
            headers=self.headers,
            params={"only_free": True},
        ).json()
        self.assertEqual(free["count"], 1)

        # Conflit de créneau refusé
        conflict = self.client.post(
            "/api/crm/visits",
            headers=self.headers,
            json={
                "property_id": self.property_id,
                "prospect_id": prospect["id"],
                "scheduled_date": visit_day.isoformat(),
                "start_time": "10:30",
                "end_time": "11:30",
            },
        )
        self.assertEqual(conflict.status_code, 400)

        # Rappels email + SMS journalisés
        reminders = self.client.post(
            f"/api/crm/visits/{visit['id']}/reminders", headers=self.headers, json={"channels": ["email", "sms"]}
        )
        self.assertEqual(reminders.status_code, 200)
        self.assertEqual(reminders.json()["count"], 2)

        # Compte-rendu de visite + retour du visiteur
        report = self.client.post(
            f"/api/crm/visits/{visit['id']}/report",
            headers=self.headers,
            json={
                "overall_rating": 4,
                "interest_level": "fort",
                "strengths": "Lumineux, bien situé",
                "weaknesses": "cuisine à rafraîchir",
                "next_step": "Envoi du dossier",
            },
        )
        self.assertEqual(report.status_code, 201)
        self.assertEqual(report.json()["status"], "effectuee")
        self.assertEqual(report.json()["report"]["interest_level"], "fort")

        feedback = self.client.post(
            f"/api/crm/visits/{visit['id']}/feedback",
            headers=self.headers,
            json={"visitor_rating": 5, "visitor_comments": "Très bon accueil", "visitor_would_apply": True},
        )
        self.assertEqual(feedback.status_code, 201)
        self.assertEqual(feedback.json()["report"]["visitor_rating"], 5)

        # Agenda jour / semaine / mois
        for view, expected_min in (("day", 1), ("week", 1), ("month", 1)):
            agenda = self.client.get(
                "/api/crm/visits/agenda",
                headers=self.headers,
                params={"view": view, "date": visit_day.isoformat()},
            )
            self.assertEqual(agenda.status_code, 200)
            self.assertGreaterEqual(agenda.json()["count"], expected_min)
            self.assertIn(visit_day.isoformat(), agenda.json()["days"])

    def test_visit_cancellation_frees_slot(self):
        prospect = self._create_prospect()
        visit_day = date.today() + timedelta(days=5)
        slots = self.client.post(
            f"/api/crm/properties/{self.property_id}/availabilities",
            headers=self.headers,
            json={"available_date": visit_day.isoformat(), "slots": [{"start": "09:00", "end": "10:00"}]},
        ).json()["data"]

        visit = self.client.post(
            "/api/crm/visits",
            headers=self.headers,
            json={
                "property_id": self.property_id,
                "prospect_id": prospect["id"],
                "scheduled_date": visit_day.isoformat(),
                "start_time": "09:00",
                "end_time": "10:00",
                "availability_id": slots[0]["id"],
            },
        ).json()

        response = self.client.post(
            f"/api/crm/visits/{visit['id']}/cancel",
            headers=self.headers,
            json={"reason": "Indisponibilité du prospect"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "annulee")
        free = self.client.get(
            f"/api/crm/properties/{self.property_id}/availabilities",
            headers=self.headers,
            params={"only_free": True},
        ).json()
        self.assertEqual(free["count"], 1)

    # ------------------------------------------------------------------
    # Matching automatique
    # ------------------------------------------------------------------
    def test_matching_scan_suggestions_and_alerts(self):
        prospect = self._create_prospect()
        # Bien hors critères (Lyon, hors budget)
        other_id = self._create_property(city="Lyon", postal_code="69001", rent_price=1500)

        response = self.client.post(
            "/api/crm/matching/scan", headers=self.headers, json={"min_score": 60, "notify": True}
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertGreaterEqual(body["alerts_created"], 1)

        matches = self.client.get(
            "/api/crm/matching/matches", headers=self.headers, params={"prospect_id": prospect["id"]}
        ).json()
        property_ids = [m["property_id"] for m in matches["data"]]
        self.assertIn(self.property_id, property_ids)
        self.assertNotIn(other_id, property_ids)
        best = matches["data"][0]
        self.assertIn("detail", best)
        self.assertGreaterEqual(best["score"], 60)

        # Suggestions classées
        suggestions = self.client.get(
            f"/api/crm/matching/suggestions/{prospect['id']}", headers=self.headers
        ).json()
        self.assertGreaterEqual(suggestions["count"], 1)
        scores = [s["score"] for s in suggestions["data"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

        # Notification automatique à l'agent
        notifications = self.client.get(
            "/api/crm/notifications", headers=self.headers, params={"unread_only": True}
        ).json()
        self.assertTrue(any(n["type"] == "matching" for n in notifications["data"]))

        # Suggestion envoyée puis écartée
        notify = self.client.post(
            f"/api/crm/matching/matches/{best['id']}/notify",
            headers=self.headers,
            json={"also_email_prospect": True},
        )
        self.assertEqual(notify.status_code, 200)
        self.assertEqual(notify.json()["status"], "notifiee")
        dismissed = self.client.post(
            f"/api/crm/matching/matches/{best['id']}/dismiss",
            headers=self.headers,
            json={"reason": "déjà loué"},
        )
        self.assertEqual(dismissed.json()["status"], "ecartee")

    # ------------------------------------------------------------------
    # Diffusion multi-portails et statistiques
    # ------------------------------------------------------------------
    def test_listing_publication_and_stats(self):
        # Modèle d'annonce
        template = self.client.post(
            "/api/crm/listing-templates",
            headers=self.headers,
            json={
                "name": "Location standard",
                "property_type": "apartment",
                "title_template": "{titre} — {ville} ({code_postal})",
                "description_template": "{type} de {surface} m², {pieces} pièces, {prix}/mois.",
            },
        )
        self.assertEqual(template.status_code, 201)

        listing = self.client.post(
            "/api/crm/listings",
            headers=self.headers,
            json={
                "property_id": self.property_id,
                "title": "Appartement CRM",
                "listing_type": "location",
                "template_id": template.json()["id"],
            },
        )
        self.assertEqual(listing.status_code, 201, listing.text)
        self.assertTrue(listing.json()["description"].startswith("apartment de 55 m²"))

        portals = self.client.get("/api/crm/portals", headers=self.headers).json()["data"]
        self.assertEqual(
            sorted(portals),
            sorted(["seloger", "leboncoin", "logic_immo", "bienici", "pap", "site_agence"]),
        )

        # Publication multi-portails
        publish = self.client.post(
            f"/api/crm/listings/{listing.json()['id']}/publish",
            headers=self.headers,
            json={"portals": ["seloger", "leboncoin", "site_agence"]},
        )
        self.assertEqual(publish.status_code, 200)
        self.assertEqual(publish.json()["published_count"], 3)

        sync = self.client.get(
            f"/api/crm/listings/{listing.json()['id']}/sync", headers=self.headers
        ).json()["data"]
        self.assertEqual(len(sync), 3)
        self.assertTrue(all(s["status"] == "publiee" for s in sync))

        # Statistiques remontées par les portails (vues / contacts / conversion)
        stats = self.client.post(
            f"/api/crm/listings/{listing.json()['id']}/stats",
            headers=self.headers,
            json={
                "entries": [
                    {"stat_date": date.today().isoformat(), "views": 150, "contacts": 6, "portal": "seloger"},
                    {"stat_date": date.today().isoformat(), "views": 100, "contacts": 2, "portal": "leboncoin"},
                    {"stat_date": date.today().isoformat(), "views": 50, "contacts": 2, "portal": None},
                ]
            },
        )
        self.assertEqual(stats.status_code, 200, stats.text)
        body = stats.json()
        self.assertEqual(body["totals"]["views"], 300)
        self.assertEqual(body["totals"]["contacts"], 10)
        self.assertAlmostEqual(body["totals"]["conversion_rate_pct"], round(10 / 300 * 100, 2))

        # Vue centralisée
        overview = self.client.get("/api/crm/listings", headers=self.headers).json()
        self.assertEqual(overview["count"], 1)
        self.assertEqual(overview["listings"][0]["views"], 300)

        # Retrait d'un portail puis de tous
        unpublish = self.client.post(
            f"/api/crm/listings/{listing.json()['id']}/unpublish",
            headers=self.headers,
            params={"portal": "seloger"},
        )
        self.assertEqual(unpublish.status_code, 200)
        self.assertEqual(unpublish.json()["status"], "en_pause")
        unpublish_all = self.client.post(
            f"/api/crm/listings/{listing.json()['id']}/unpublish", headers=self.headers
        )
        self.assertEqual(unpublish_all.json()["status"], "retiree")

    # ------------------------------------------------------------------
    # Transactions : offre, compromis, conditions, acte, commission
    # ------------------------------------------------------------------
    def test_sale_transaction_full_lifecycle(self):
        prospect = self._create_prospect(prospect_type="acheteur")
        sale_property = self._create_property(
            title="Maison Bordeaux", city="Bordeaux", postal_code="33000",
            rent_price=None, sale_price=320000,
        )
        deal = self.client.post(
            "/api/crm/deals",
            headers=self.headers,
            json={
                "title": "Achat maison Bordeaux",
                "prospect_id": prospect["id"],
                "property_id": sale_property,
                "deal_type": "vente",
                "estimated_value": 320000,
                "expected_commission": 19200,
            },
        ).json()

        # Offre d'achat
        offer = self.client.post(
            "/api/crm/offers",
            headers=self.headers,
            json={
                "property_id": sale_property,
                "prospect_id": prospect["id"],
                "deal_id": deal["id"],
                "amount": 310000,
                "offer_date": date.today().isoformat(),
                "validity_date": (date.today() + timedelta(days=10)).isoformat(),
            },
        )
        self.assertEqual(offer.status_code, 201)
        offer_id = offer.json()["id"]
        self.assertEqual(offer.json()["status"], "en_attente")

        # Acceptation avec création automatique du dossier de vente
        accepted = self.client.post(
            f"/api/crm/offers/{offer_id}/accept",
            headers=self.headers,
            json={"note": "Offre acceptée", "create_transaction": True},
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        transaction = accepted.json()["transaction"]
        self.assertEqual(transaction["stage"], "offre")
        self.assertEqual(transaction["buyer_name"], "Camille Durand")

        # Compromis + suivi notaire
        compromis = self.client.post(
            f"/api/crm/transactions/{transaction['id']}/compromis",
            headers=self.headers,
            json={
                "compromis_date": date.today().isoformat(),
                "notary_name": "Maître Martin",
                "notary_email": "cabinet@martin-notaire.fr",
            },
        )
        self.assertEqual(compromis.status_code, 200)
        self.assertEqual(compromis.json()["stage"], "compromis")
        self.assertEqual(compromis.json()["notary"]["name"], "Maître Martin")

        # Conditions suspensives
        financing = self.client.post(
            f"/api/crm/transactions/{transaction['id']}/conditions",
            headers=self.headers,
            json={"label": "Obtention du prêt", "condition_type": "financement",
                  "deadline": (date.today() + timedelta(days=45)).isoformat()},
        ).json()
        inspection = self.client.post(
            f"/api/crm/transactions/{transaction['id']}/conditions",
            headers=self.headers,
            json={"label": "Diagnostics conformes", "condition_type": "diagnostic"},
        ).json()

        # L'acte est refusé tant qu'une condition est en attente
        blocked = self.client.post(
            f"/api/crm/transactions/{transaction['id']}/acte",
            headers=self.headers,
            json={"acte_signed_at": date.today().isoformat()},
        )
        self.assertEqual(blocked.status_code, 400)

        decision = self.client.post(
            f"/api/crm/transactions/conditions/{financing['id']}/decision",
            headers=self.headers,
            json={"decision": "satisfaite"},
        )
        self.assertEqual(decision.status_code, 200)
        waived = self.client.post(
            f"/api/crm/transactions/conditions/{inspection['id']}/decision",
            headers=self.headers,
            json={"decision": "levee"},
        )
        self.assertEqual(waived.status_code, 200)

        # Événement de suivi notaire
        event = self.client.post(
            f"/api/crm/transactions/{transaction['id']}/events",
            headers=self.headers,
            json={"event_type": "notaire", "label": "Reconduction RDV notaire"},
        )
        self.assertEqual(event.status_code, 201)

        # Acte authentique : commission agence calculée (5 % + 1000 €, TVA 20 %)
        acte = self.client.post(
            f"/api/crm/transactions/{transaction['id']}/acte",
            headers=self.headers,
            json={
                "acte_signed_at": date.today().isoformat(),
                "commission_rate": 5,
                "commission_fixed": 1000,
            },
        )
        self.assertEqual(acte.status_code, 200, acte.text)
        body = acte.json()
        self.assertEqual(body["stage"], "signee")
        calc = body["commission_calculation"]
        self.assertEqual(calc["commission_ht"], round(310000 * 5 / 100 + 1000, 2))
        self.assertEqual(calc["commission_ttc"], round((310000 * 5 / 100 + 1000) * 1.2, 2))

        # Le dossier commercial lié est gagné
        deal_after = self.client.get(f"/api/crm/deals/{deal['id']}", headers=self.headers).json()
        self.assertEqual(deal_after["status"], "won")

    def test_offer_refusal(self):
        sale_property = self._create_property(sale_price=200000, rent_price=None)
        offer = self.client.post(
            "/api/crm/offers",
            headers=self.headers,
            json={"property_id": sale_property, "amount": 150000, "offer_date": date.today().isoformat()},
        ).json()
        refused = self.client.post(
            f"/api/crm/offers/{offer['id']}/refuse", headers=self.headers, json={"note": "Trop basse"}
        )
        self.assertEqual(refused.status_code, 200)
        self.assertEqual(refused.json()["status"], "refusee")
        # Une offre traitée ne peut pas être re-décidée
        again = self.client.post(
            f"/api/crm/offers/{offer['id']}/accept", headers=self.headers, json={}
        )
        self.assertEqual(again.status_code, 400)

    # ------------------------------------------------------------------
    # Performance des agents
    # ------------------------------------------------------------------
    def test_agent_performance(self):
        prospect = self._create_prospect()
        deal = self.client.post(
            "/api/crm/deals",
            headers=self.headers,
            json={
                "title": "Location T3",
                "prospect_id": prospect["id"],
                "estimated_value": 950,
                "assigned_agent": "gestionnaire@immogest.com",
            },
        ).json()
        visit = self.client.post(
            "/api/crm/visits",
            headers=self.headers,
            json={
                "property_id": self.property_id,
                "prospect_id": prospect["id"],
                "scheduled_date": date.today().isoformat(),
                "start_time": "10:00",
                "end_time": "11:00",
                "assigned_agent": "gestionnaire@immogest.com",
            },
        ).json()
        self.client.post(f"/api/crm/visits/{visit['id']}/report", headers=self.headers, json={"overall_rating": 4})

        stages = self.client.get("/api/crm/pipeline/stages", headers=self.headers).json()["data"]
        won_stage = next(s for s in stages if s["is_won"])
        self.client.post(
            f"/api/crm/deals/{deal['id']}/stage", headers=self.headers, json={"stage_id": won_stage["id"]}
        )

        response = self.client.get("/api/crm/performance", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        agent = next(
            a for a in body["agents"] if a["agent"] == "gestionnaire@immogest.com"
        )
        self.assertEqual(agent["deals_won"], 1)
        self.assertEqual(agent["visits_completed"], 1)
        self.assertEqual(agent["visits_per_signature"], 1.0)
        self.assertIn("occupancy_rate_pct", body["global"])
        self.assertGreaterEqual(body["global"]["deals_created"], 1)


if __name__ == "__main__":
    unittest.main()
