"""Tests d'intégration du module 9 : tableau de bord et reporting.

Lancés sur SQLite, sans service externe, à travers l'API FastAPI : KPIs
temps réel, graphiques dynamiques, widgets drag & drop, rapports prédéfinis,
rapports personnalisés (filtres, groupements, planification, partage),
exports PDF/Excel/CSV/Word et alertes paramétrables.
"""

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-mod9-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models.finance import Charge, LatePayment  # noqa: E402
from app.models.tenant import (  # noqa: E402
    Lease,
    LeaseStatus,
    PaymentStatus,
    RentPayment,
    Tenant,
)
from app.services.crm_service import generate_reference


class ReportingModuleTest(unittest.TestCase):
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
        self._seed_financials()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    def _create_property(self) -> int:
        response = self.client.post(
            "/api/properties/",
            headers=self.headers,
            json={
                "type": "apartment",
                "title": "Appartement reporting",
                "address": "5 avenue des Tests",
                "postal_code": "69003",
                "city": "Lyon",
                "rent_price": 800,
                "charges": 80,
                "living_area": 50,
                "rooms": 2,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def _seed_financials(self):
        """Alimente directement la base (modèles internes) : locataire, bail,
        loyers encaissés, impayé et charge."""
        db = SessionLocal()
        try:
            tenant = Tenant(
                reference=generate_reference("LOC")[:24],
                first_name="Léa",
                last_name="Moreau",
                email="lea.moreau@example.fr",
            )
            db.add(tenant)
            db.flush()
            lease = Lease(
                reference=generate_reference("BAIL")[:30],
                tenant_id=tenant.id,
                property_id=self.property_id,
                status=LeaseStatus.ACTIVE,
                start_date=date.today().replace(day=1) - timedelta(days=90),
                end_date=date.today() + timedelta(days=60),
                monthly_rent=800,
                monthly_charges=80,
            )
            db.add(lease)
            db.flush()
            now = datetime.now(timezone.utc)

            def month_first(months_back: int) -> date:
                total = date.today().year * 12 + (date.today().month - 1) - months_back
                return date(total // 12, total % 12 + 1, 1)

            for i in range(3):
                period_date = month_first(i + 1)  # mois précédents, jamais le mois courant
                db.add(
                    RentPayment(
                        reference=generate_reference("PAY")[:30],
                        tenant_id=tenant.id,
                        lease_id=lease.id,
                        period=period_date.strftime("%Y-%m"),
                        due_date=period_date,
                        amount_due=880,
                        amount_paid=880,
                        status=PaymentStatus.PAID,
                        paid_at=now - timedelta(days=30 * i),
                    )
                )
            db.add(
                RentPayment(
                    reference=generate_reference("PAY")[:30],
                    tenant_id=tenant.id,
                    lease_id=lease.id,
                    period=date.today().strftime("%Y-%m"),
                    due_date=date.today(),
                    amount_due=880,
                    amount_paid=0,
                    status=PaymentStatus.OVERDUE,
                )
            )
            db.flush()
            db.add(
                LatePayment(
                    reference=generate_reference("IMP")[:30],
                    tenant_id=tenant.id,
                    lease_id=lease.id,
                    property_id=self.property_id,
                    period=date.today().strftime("%Y-%m"),
                    amount_due=880,
                    amount_outstanding=880,
                    due_date=date.today() - timedelta(days=20),
                    overdue_days=20,
                )
            )
            db.add(
                Charge(
                    reference=generate_reference("CHG")[:30],
                    property_id=self.property_id,
                    charge_type="copropriété",
                    category="charges_courantes",
                    amount=1200,
                )
            )
            db.commit()
            self.lease_id = lease.id
        finally:
            db.close()

    # ------------------------------------------------------------------
    # Dashboard principal : KPIs temps réel et graphiques
    # ------------------------------------------------------------------
    def test_dashboard_kpis(self):
        response = self.client.get("/api/reporting/dashboard", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        kpis = body["kpis"]
        self.assertEqual(kpis["properties"]["total"], 1)
        self.assertEqual(kpis["properties"]["occupied"], 1)
        self.assertEqual(kpis["occupancy_rate_pct"], 100.0)
        self.assertGreater(kpis["revenue"]["month_to_date"], 0)
        self.assertEqual(kpis["unpaid"]["count"], 1)
        self.assertEqual(kpis["unpaid"]["outstanding"], 880)
        self.assertEqual(kpis["leases_expiring"]["90"], 1)
        self.assertIn("maintenance", kpis)
        self.assertIn("mandates_expiring_90d", kpis)
        self.assertIn("crm", kpis)

    def test_dashboard_charts(self):
        response = self.client.get(
            "/api/reporting/dashboard/charts", headers=self.headers, params={"months": 6}
        )
        self.assertEqual(response.status_code, 200)
        charts = response.json()
        self.assertEqual(len(charts["revenue_evolution"]), 6)
        self.assertGreater(sum(m["amount"] for m in charts["revenue_evolution"]), 0)
        self.assertEqual(charts["property_type_distribution"][0]["type"], "apartment")
        self.assertEqual(len(charts["occupancy_monthly"]), 6)
        self.assertEqual(charts["charge_distribution"][0]["type"], "copropriété")
        self.assertIn("commercial_performance", charts)

    # ------------------------------------------------------------------
    # Widgets personnalisables (drag & drop)
    # ------------------------------------------------------------------
    def test_widget_lifecycle_and_reorder(self):
        catalog = self.client.get("/api/reporting/dashboard/widgets/catalog", headers=self.headers)
        self.assertEqual(catalog.status_code, 200)
        self.assertGreaterEqual(len(catalog.json()["data"]), 10)

        first = self.client.post(
            "/api/reporting/dashboard/widgets",
            headers=self.headers,
            json={"widget_type": "kpi_occupancy", "column_index": 0, "position": 0},
        ).json()
        second = self.client.post(
            "/api/reporting/dashboard/widgets",
            headers=self.headers,
            json={"widget_type": "chart_revenue", "column_index": 1, "position": 0, "size": "large"},
        ).json()

        # Données temps réel du widget
        data = self.client.get(
            "/api/reporting/dashboard/widgets/kpi_occupancy/data", headers=self.headers
        ).json()
        self.assertEqual(data["data"]["value"], 100.0)

        # Drag & drop : permutation
        reorder = self.client.put(
            "/api/reporting/dashboard/widgets/reorder",
            headers=self.headers,
            json={
                "positions": [
                    {"widget_id": first["id"], "column_index": 1, "position": 1},
                    {"widget_id": second["id"], "column_index": 0, "position": 0},
                ]
            },
        )
        self.assertEqual(reorder.status_code, 200)
        self.assertEqual(reorder.json()["reordered"], 2)

        widgets = self.client.get("/api/reporting/dashboard/widgets", headers=self.headers).json()
        positions = {w["id"]: (w["column_index"], w["position"]) for w in widgets["data"]}
        self.assertEqual(positions[second["id"]], (0, 0))

        # Suppression
        deleted = self.client.delete(
            f"/api/reporting/dashboard/widgets/{first['id']}", headers=self.headers
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(
            self.client.get("/api/reporting/dashboard/widgets", headers=self.headers).json()["count"], 1
        )

    # ------------------------------------------------------------------
    # Rapports prédéfinis
    # ------------------------------------------------------------------
    def test_all_predefined_reports_run(self):
        listing = self.client.get("/api/reporting/reports/predefined", headers=self.headers).json()
        self.assertEqual(len(listing["data"]), 9)

        for entry in listing["data"]:
            response = self.client.get(
                f"/api/reporting/reports/predefined/{entry['key']}",
                headers=self.headers,
                params={"year": date.today().year},
            )
            self.assertEqual(response.status_code, 200, entry["key"])

        etat = self.client.get(
            "/api/reporting/reports/predefined/etat_loyers",
            headers=self.headers,
            params={"year": date.today().year},
        ).json()
        self.assertGreaterEqual(etat["row_count"], 3)
        self.assertGreater(etat["totals"]["paye"], 0)

        impayes = self.client.get(
            "/api/reporting/reports/predefined/synthese_impayes", headers=self.headers
        ).json()
        self.assertEqual(impayes["totals"]["dossiers"], 1)
        self.assertEqual(impayes["totals"]["restant_dû"], 880)

        vacance = self.client.get(
            "/api/reporting/reports/predefined/rapport_vacance_locative", headers=self.headers
        ).json()
        # Le bien est loué : aucun bien vacant
        self.assertEqual(vacance["totals"]["biens_vacants"], 0)

    def test_predefined_report_exports(self):
        cases = {
            "pdf": "application/pdf",
            "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "csv": "text/csv; charset=utf-8",
            "word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        for fmt, mime in cases.items():
            response = self.client.get(
                "/api/reporting/reports/predefined/etat_loyers",
                headers=self.headers,
                params={"year": date.today().year, "format": fmt},
            )
            self.assertEqual(response.status_code, 200, fmt)
            self.assertEqual(response.headers["content-type"].split(";")[0], mime.split(";")[0])
            # Un CSV compact reste léger ; les autres formats sont plus lourts
            self.assertGreater(len(response.content), 150 if fmt == "csv" else 1000)
            self.assertIn("attachment", response.headers["content-disposition"])

        # Le PDF est lisible
        import io

        from pypdf import PdfReader

        pdf_response = self.client.get(
            "/api/reporting/reports/predefined/etat_loyers",
            headers=self.headers,
            params={"year": date.today().year, "format": "pdf"},
        )
        pdf = PdfReader(io.BytesIO(pdf_response.content))
        self.assertGreaterEqual(len(pdf.pages), 1)

    # ------------------------------------------------------------------
    # Rapports personnalisés : générateur, filtres, groupement, partage
    # ------------------------------------------------------------------
    def test_custom_report_builder(self):
        datasets = self.client.get("/api/reporting/custom-reports/datasets", headers=self.headers).json()
        names = {d["dataset"] for d in datasets["data"]}
        self.assertIn("biens", names)
        self.assertIn("loyers", names)

        created = self.client.post(
            "/api/reporting/custom-reports",
            headers=self.headers,
            json={
                "name": "Loyers impayés de l'année",
                "dataset": "loyers",
                "fields": ["periode", "du", "paye", "statut"],
                "filters": [
                    {"field": "statut", "operator": "eq", "value": "overdue"},
                    {"field": "echeance", "operator": "gte", "value": f"{date.today().year}-01-01"},
                ],
                "sort_by": [{"field": "echeance", "dir": "asc"}],
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        report = created.json()

        run = self.client.post(
            f"/api/reporting/custom-reports/{report['id']}/run",
            headers=self.headers,
            json={"format": "json"},
        )
        self.assertEqual(run.status_code, 200, run.text)
        result = run.json()
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["rows"][0]["statut"], "overdue")

        # Champ inconnu → 400
        bad = self.client.post(
            "/api/reporting/custom-reports",
            headers=self.headers,
            json={"name": "Invalide", "dataset": "loyers", "fields": ["inconnu"]},
        )
        self.assertEqual(bad.status_code, 400)

    def test_custom_report_grouping_and_export(self):
        # Création d'un second bien pour le groupement
        self.client.post(
            "/api/properties/",
            headers=self.headers,
            json={
                "type": "house",
                "title": "Maison Lyon",
                "address": "1 rue B",
                "postal_code": "69003",
                "city": "Lyon",
                "rent_price": 1200,
                "charges": 100,
                "living_area": 100,
                "rooms": 5,
            },
        )
        created = self.client.post(
            "/api/reporting/custom-reports",
            headers=self.headers,
            json={
                "name": "Parc par ville",
                "dataset": "biens",
                "fields": ["ville", "loyer"],
                "group_by": ["ville"],
            },
        )
        self.assertEqual(created.status_code, 201)
        report_id = created.json()["id"]

        run = self.client.post(
            f"/api/reporting/custom-reports/{report_id}/run", headers=self.headers, json={"format": "json"}
        ).json()
        self.assertEqual(run["row_count"], 1)
        row = run["rows"][0]
        self.assertEqual(row["ville"], "Lyon")
        self.assertEqual(row["loyer"]["count"], 2)
        self.assertAlmostEqual(row["loyer"]["sum"], 2000)
        self.assertEqual(row["count"], 2)

        excel = self.client.post(
            f"/api/reporting/custom-reports/{report_id}/run",
            headers=self.headers,
            json={"format": "excel"},
        )
        self.assertEqual(excel.status_code, 200)
        self.assertIn("spreadsheetml", excel.headers["content-type"])

    def test_custom_report_share_and_schedule(self):
        report = self.client.post(
            "/api/reporting/custom-reports",
            headers=self.headers,
            json={"name": "Rapport partagé", "dataset": "biens", "fields": ["reference", "titre", "ville"]},
        ).json()

        # Partage sans authentification via le jeton
        shared = self.client.get(f"/api/reporting/reports/shared/{report['share_token']}")
        self.assertEqual(shared.status_code, 200)
        self.assertTrue(shared.json()["shared"])
        self.assertEqual(shared.json()["row_count"], 1)

        missing = self.client.get("/api/reporting/reports/shared/token-inconnu")
        self.assertEqual(missing.status_code, 404)

        # Planification d'envoi automatique
        schedule = self.client.post(
            f"/api/reporting/custom-reports/{report['id']}/schedule",
            headers=self.headers,
            json={"frequency": "quotidien", "recipients": ["direction@immogest.com"], "format": "pdf"},
        )
        self.assertEqual(schedule.status_code, 200)
        body = schedule.json()["schedule"]
        self.assertEqual(body["frequency"], "quotidien")
        self.assertIsNotNone(body["next_run_at"])

        # Échéance forcée : next_run passé → exécution immédiate
        from app.models.reporting import CustomReport

        db = SessionLocal()
        try:
            db.query(CustomReport).filter(CustomReport.id == report["id"]).update(
                {"next_run_at": datetime.now(timezone.utc) - timedelta(hours=1)}
            )
            db.commit()
        finally:
            db.close()

        run = self.client.post("/api/reporting/reports/schedules/run", headers=self.headers)
        self.assertEqual(run.status_code, 200)
        self.assertEqual(run.json()["count"], 1)
        processed = run.json()["processed"][0]
        self.assertEqual(processed["recipients"], ["direction@immogest.com"])

        # Historique des exécutions
        executions = self.client.get("/api/reporting/executions", headers=self.headers).json()
        self.assertGreaterEqual(executions["count"], 1)

    # ------------------------------------------------------------------
    # Exports génériques / API BI
    # ------------------------------------------------------------------
    def test_generic_export_api(self):
        json_export = self.client.get(
            "/api/reporting/exports", headers=self.headers, params={"dataset": "biens", "format": "json"}
        )
        self.assertEqual(json_export.status_code, 200)
        self.assertEqual(json_export.json()["row_count"], 1)
        self.assertIn("reference", json_export.json()["rows"][0])

        csv_export = self.client.get(
            "/api/reporting/exports", headers=self.headers, params={"dataset": "loyers", "format": "csv"}
        )
        self.assertEqual(csv_export.status_code, 200)
        self.assertIn("text/csv", csv_export.headers["content-type"])

        invalid = self.client.get(
            "/api/reporting/exports", headers=self.headers, params={"dataset": "inconnu"}
        )
        self.assertEqual(invalid.status_code, 400)

    # ------------------------------------------------------------------
    # Alertes paramétrables et notifications
    # ------------------------------------------------------------------
    def test_alert_rules_and_realtime_events(self):
        # Métrique inconnue → 400
        bad = self.client.post(
            "/api/reporting/alert-rules",
            headers=self.headers,
            json={"name": "Invalide", "metric": "metrique_inconnue", "threshold": 1},
        )
        self.assertEqual(bad.status_code, 400)

        # Seuil franchi : taux d'occupation < 100 % est faux (100 %) → non déclenché ;
        # impayés > 500 € est vrai → déclenché
        self.client.post(
            "/api/reporting/alert-rules",
            headers=self.headers,
            json={
                "name": "Occupation saine",
                "metric": "occupancy_rate",
                "operator": "<",
                "threshold": 90,
                "severity": "critical",
                "channels": ["dashboard", "email"],
            },
        )
        self.client.post(
            "/api/reporting/alert-rules",
            headers=self.headers,
            json={"name": "Impayés élevés", "metric": "unpaid_outstanding", "operator": ">", "threshold": 500},
        )

        evaluation = self.client.post("/api/reporting/alerts/evaluate", headers=self.headers)
        self.assertEqual(evaluation.status_code, 200)
        body = evaluation.json()
        self.assertEqual(body["rules_checked"], 2)
        self.assertEqual(body["triggered_count"], 1)
        self.assertEqual(body["triggered"][0]["rule"], "Impayés élevés")
        self.assertEqual(body["triggered"][0]["value"], 880)

        events = self.client.get(
            "/api/reporting/alert-events", headers=self.headers, params={"acknowledged": False}
        ).json()
        self.assertEqual(events["count"], 1)

        # Prise de connaissance
        ack = self.client.post(
            f"/api/reporting/alert-events/{events['data'][0]['id']}/ack", headers=self.headers, json={}
        )
        self.assertEqual(ack.status_code, 200)
        self.assertTrue(ack.json()["acknowledged"])

        # Anti-spam : une nouvelle évaluation ne re-déclenche pas (cooldown 24 h)
        again = self.client.post("/api/reporting/alerts/evaluate", headers=self.headers).json()
        self.assertEqual(again["triggered_count"], 0)

    def test_alert_rule_update_and_delete(self):
        rule = self.client.post(
            "/api/reporting/alert-rules",
            headers=self.headers,
            json={"name": "Tickets", "metric": "open_tickets", "operator": ">", "threshold": 10},
        ).json()
        updated = self.client.put(
            f"/api/reporting/alert-rules/{rule['id']}",
            headers=self.headers,
            json={"threshold": 5, "severity": "critical"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["threshold"], 5)
        deleted = self.client.delete(f"/api/reporting/alert-rules/{rule['id']}", headers=self.headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get("/api/reporting/alert-rules", headers=self.headers).json()["count"], 0)


if __name__ == "__main__":
    unittest.main()
