"""Tests du module « Abonnements & revenus récurrents ».

Couvre le client générique, les comptes de paiement (Stripe, PayPal, Wise,
MVola, Orange Money), l'abonnement premium, l'encaissement via checkout en
mode simulation, la confirmation idempotente et le webhook.
"""
import json
import os
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

TEST_DIR = tempfile.mkdtemp(prefix="gestimmo-subscriptions-")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DIR}/tests.db"
os.environ["UPLOAD_DIR"] = f"{TEST_DIR}/public"
os.environ["PRIVATE_UPLOAD_DIR"] = f"{TEST_DIR}/private"
os.environ["DEBUG"] = "false"
os.environ["AUTO_CREATE_TABLES"] = "true"
# Le module abonnements est testé en mode simulation (aucun prestataire live).
os.environ["PAYMENT_SIMULATION_ENABLED"] = "true"
os.environ["PUBLIC_BASE_URL"] = "http://localhost:3000"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


class SubscriptionsModuleTest(unittest.TestCase):
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

    def create_client(self, name="Agence Faly", email="contact@faly.mg") -> dict:
        response = self.client.post(
            "/api/subscriptions/clients",
            headers=self.headers,
            json={"name": name, "email": email, "city": "Antananarivo", "country": "Madagascar"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_account(self, client_id, provider):
        response = self.client.post(
            "/api/subscriptions/payment-accounts",
            headers=self.headers,
            json={
                "client_id": client_id,
                "provider": provider,
                "provider_account_id": f"acc_{provider}_{client_id}",
                "currency": "EUR",
                "is_default": True,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_subscription(self, client_id, account_id, amount=49.9):
        response = self.client.post(
            "/api/subscriptions",
            headers=self.headers,
            json={
                "client_id": client_id,
                "payment_account_id": account_id,
                "plan": "premium",
                "amount": amount,
                "billing_interval": "monthly",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_subscriptions_overview(self):
        resp = self.client.get("/api/subscriptions/overview", headers=self.headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("total_revenue", resp.json()["data"])

    def test_client_crud(self):
        client = self.create_client()
        self.assertTrue(client["reference"].startswith("CLI-"))

        listing = self.client.get("/api/subscriptions/clients", headers=self.headers)
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertGreaterEqual(listing.json()["total"], 1)

        detail = self.client.get(
            f"/api/subscriptions/clients/{client['id']}", headers=self.headers
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["name"], "Agence Faly")

        patch = self.client.patch(
            f"/api/subscriptions/clients/{client['id']}",
            headers=self.headers,
            json={"phone": "+261 34 00 000 00"},
        )
        self.assertEqual(patch.status_code, 200, patch.text)
        self.assertEqual(patch.json()["phone"], "+261 34 00 000 00")

    def test_payment_accounts_all_providers(self):
        client = self.create_client()
        providers = ["stripe", "paypal", "wise", "mvola", "orange_money"]
        for provider in providers:
            account = self.create_account(client["id"], provider)
            self.assertEqual(account["provider"], provider)
            self.assertEqual(account["status"], "active")

        provider_counts = {}
        for row in [
            a["provider"] for a in self.client.get(
                "/api/subscriptions/payment-accounts", headers=self.headers
            ).json()["data"]
        ]:
            provider_counts[row] = provider_counts.get(row, 0) + 1
        for provider in providers:
            self.assertEqual(provider_counts[provider], 1)

    def test_premium_subscription_checkout_and_confirm(self):
        client = self.create_client()
        account = self.create_account(client["id"], "mvola")

        sub = self.create_subscription(client["id"], account["id"], amount=49.9)
        self.assertEqual(sub["plan"], "premium")
        self.assertEqual(sub["status"], "draft")
        self.assertIsNotNone(sub["next_billing_date"])

        checkout = self.client.post(
            f"/api/subscriptions/{sub['id']}/checkout",
            headers=self.headers,
            json={},
        )
        self.assertEqual(checkout.status_code, 201, checkout.text)
        payload = checkout.json()
        self.assertEqual(payload["provider"], "mvola")
        self.assertTrue(payload["simulated"])
        self.assertIsNotNone(payload["checkout_url"])
        self.assertIn("/confirm", payload["checkout_url"])

        # Confirmation simulée via le jeton présent dans l'URL de checkout.
        parsed = urlparse(payload["checkout_url"])
        token = parse_qs(parsed.query).get("token", [None])[0]
        reference = parsed.path.split("/")[-2]
        confirm = self.client.post(
            f"/api/subscriptions/payments/{reference}/confirm",
            headers=self.headers,
            params={"token": token},
        )
        self.assertEqual(confirm.status_code, 200, confirm.text)
        self.assertEqual(confirm.json()["status"], "succeeded")
        self.assertEqual(confirm.json()["subscription_status"], "active")

        # Idempotence : une seconde confirmation ne crée pas de défaut.
        confirm2 = self.client.post(
            f"/api/subscriptions/payments/{reference}/confirm",
            headers=self.headers,
            params={"token": token},
        )
        self.assertEqual(confirm2.status_code, 200, confirm2.text)

        # Le revenu est disponible dans le listing des paiements.
        payments = self.client.get(
            "/api/subscriptions/payments",
            headers=self.headers,
            params={"subscription_id": sub["id"]},
        ).json()
        self.assertEqual(payments["total"], 1)
        self.assertEqual(payments["data"][0]["status"], "succeeded")

    def test_checkout_rejects_invalid_token(self):
        client = self.create_client()
        account = self.create_account(client["id"], "stripe")
        sub = self.create_subscription(client["id"], account["id"])

        checkout = self.client.post(
            f"/api/subscriptions/{sub['id']}/checkout", headers=self.headers, json={}
        ).json()
        parsed = urlparse(checkout["checkout_url"])
        reference = parsed.path.split("/")[-2]
        confirm = self.client.post(
            f"/api/subscriptions/payments/{reference}/confirm",
            headers=self.headers,
            params={"token": "wrong-token"},
        )
        self.assertEqual(confirm.status_code, 400, confirm.text)

    def test_cancel_subscription(self):
        client = self.create_client()
        account = self.create_account(client["id"], "paypal")
        sub = self.create_subscription(client["id"], account["id"])
        cancel = self.client.post(
            f"/api/subscriptions/{sub['id']}/cancel", headers=self.headers
        )
        self.assertEqual(cancel.status_code, 200, cancel.text)
        self.assertTrue(cancel.json()["cancel_at_period_end"])

    def test_webhook_confirm_payment(self):
        client = self.create_client()
        account = self.create_account(client["id"], "paypal")
        sub = self.create_subscription(client["id"], account["id"])

        checkout = self.client.post(
            f"/api/subscriptions/{sub['id']}/checkout", headers=self.headers, json={}
        ).json()
        parsed = urlparse(checkout["checkout_url"])
        reference = parsed.path.split("/")[-2]

        # Callback générique du prestataire : il référence le paiement.
        event = {
            "type": "payment.completed",
            "data": {"object": {"payment_reference": reference, "amount": 49.9}},
        }
        resp = self.client.post(
            "/api/subscriptions/webhooks/paypal",
            content=json.dumps(event).encode(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        result = resp.json()
        self.assertEqual(result["received"], True)
        self.assertEqual(result["processed"], True)

        payments = self.client.get(
            "/api/subscriptions/payments",
            headers=self.headers,
            params={"subscription_id": sub["id"]},
        ).json()
        self.assertEqual(payments["data"][0]["status"], "succeeded")

    def test_webhook_stripe_unknown_graceful(self):
        client = self.create_client()
        account = self.create_account(client["id"], "stripe")
        sub = self.create_subscription(client["id"], account["id"])
        self.client.post(
            f"/api/subscriptions/{sub['id']}/checkout", headers=self.headers, json={}
        )

        # Sans signature ni provider_session_id connu, le webhook reste en
        # douceur (pas de crash, aucune double imputation).
        event = {
            "type": "checkout.session.completed",
            "data": {"object": {"id": "cs_none", "amount_total": 4990, "payment_intent": "pi_x"}},
        }
        resp = self.client.post(
            "/api/subscriptions/webhooks/stripe",
            content=json.dumps(event).encode(),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["received"], True)


if __name__ == "__main__":
    unittest.main()
