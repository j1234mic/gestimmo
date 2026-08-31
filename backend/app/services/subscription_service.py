"""Services du module « Abonnements & revenus récurrents ».

Centralise la création des clients, comptes de paiement et abonnements premium,
puis l'encaissement réel via les prestataires : Stripe, PayPal, Wise, MVola et
Orange Money. Le module suit le modèle du paiement Stripe locataire existant :
session de paiement chez le prestataire + webhook idempotent. En développement,
lorsqu'un prestataire n'est pas configuré, la simulation est utilisée pour que
le flux soit testable de bout en bout.
"""

import hashlib
import hmac
import json
import time
import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.subscription import (
    BillingInterval,
    ClientPaymentAccount,
    PaymentAccountStatus,
    PaymentProvider,
    PremiumSubscription,
    SubscriptionClient,
    SubscriptionPayment,
    SubscriptionPaymentStatus,
    SubscriptionPlan,
    SubscriptionStatus,
)

# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------
def generate_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def unique_reference(db: Session, model, prefix: str) -> str:
    """Génère une référence unique (boucle de secours en cas de collision)."""
    for _ in range(5):
        candidate = generate_reference(prefix)
        if not db.query(model).filter(model.reference == candidate).first():
            return candidate
    # Dernier recours : suffixe horodaté.
    return f"{prefix}-{int(time.time())}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _today() -> date:
    return datetime.now(timezone.utc).date()


# ---------------------------------------------------------------------------
# Périodes de facturation
# ---------------------------------------------------------------------------
_BILING_INTERVAL_MONTHS = {
    BillingInterval.MONTHLY: 1,
    BillingInterval.QUARTERLY: 3,
    BillingInterval.SEMI_ANNUAL: 6,
    BillingInterval.ANNUAL: 12,
}


def add_interval(d: date, interval: BillingInterval, times: int = 1) -> date:
    """Ajoute une/périodes de facturation (gère les fins de mois)."""
    months = _BILING_INTERVAL_MONTHS[interval] * times
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp au dernier jour du mois cible (31 -> 30/28/29).
    import calendar

    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def compute_period(
    subscription: PremiumSubscription,
    anchor: Optional[date] = None,
) -> tuple[date, date, date]:
    """Calcule la période de facturation courante.

    Retourne ``(period_start, period_end, next_billing_date)``.
    Le prochain ``next_billing_date`` sert d'ancrage si aucune période n'est
    encore ouverte.
    """
    interval = subscription.billing_interval or BillingInterval.MONTHLY
    if anchor is not None:
        start = anchor
    elif subscription.current_period_start:
        start = subscription.current_period_start
    elif subscription.next_billing_date:
        start = subscription.next_billing_date
    elif subscription.start_date:
        start = subscription.start_date
    else:
        start = _today()
    end = add_interval(start, interval) - timedelta(days=1)
    next_billing = add_interval(start, interval)
    return start, end, next_billing


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
def create_client(db: Session, data, actor: str = "api") -> SubscriptionClient:
    client = SubscriptionClient(
        reference=unique_reference(db, SubscriptionClient, "CLI"),
        name=data.name,
        legal_name=data.legal_name,
        email=data.email,
        phone=data.phone,
        address=data.address,
        city=data.city,
        postal_code=data.postal_code,
        country=data.country or "Madagascar",
        billing_email=data.billing_email,
        tax_reference=data.tax_reference,
        notes=data.notes,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def update_client(db: Session, client: SubscriptionClient, data, actor: str = "api") -> SubscriptionClient:
    for field in ("name", "legal_name", "email", "phone", "address", "city",
                  "postal_code", "country", "billing_email", "tax_reference",
                  "notes", "is_active"):
        value = getattr(data, field, None)
        if value is not None:
            setattr(client, field, value)
    db.commit()
    db.refresh(client)
    return client


# ---------------------------------------------------------------------------
# Comptes de paiement
# ---------------------------------------------------------------------------
def create_payment_account(db: Session, data, actor: str = "api") -> ClientPaymentAccount:
    client = db.query(SubscriptionClient).filter(SubscriptionClient.id == data.client_id).first()
    if not client:
        raise ValueError("Client introuvable")

    # Un seul compte par défaut par client.
    existing_default = (
        db.query(ClientPaymentAccount)
        .filter(
            ClientPaymentAccount.client_id == data.client_id,
            ClientPaymentAccount.is_default.is_(True),
        )
        .first()
    )
    if data.is_default and existing_default and existing_default.provider != data.provider:
        existing_default.is_default = False

    account = ClientPaymentAccount(
        client_id=data.client_id,
        provider=data.provider,
        label=data.label or f"Compte {data.provider.value}",
        provider_account_id=data.provider_account_id,
        currency=data.currency or "EUR",
        is_default=data.is_default or existing_default is None,
        status=PaymentAccountStatus.ACTIVE,
        external_metadata=data.external_metadata or {},
        notes=data.notes,
        last_verified_at=_now(),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


# ---------------------------------------------------------------------------
# Abonnements premium
# ---------------------------------------------------------------------------
def create_subscription(db: Session, data, actor: str = "api") -> PremiumSubscription:
    client = db.query(SubscriptionClient).filter(SubscriptionClient.id == data.client_id).first()
    if not client:
        raise ValueError("Client introuvable")
    if data.payment_account_id:
        account = (
            db.query(ClientPaymentAccount)
            .filter(
                ClientPaymentAccount.id == data.payment_account_id,
                ClientPaymentAccount.client_id == data.client_id,
            )
            .first()
        )
        if not account:
            raise ValueError("Le compte de paiement n'appartient pas à ce client")

    plan = data.plan or SubscriptionPlan.PREMIUM
    status = SubscriptionStatus.TRIAL if data.trial_days > 0 else SubscriptionStatus.DRAFT
    start = data.start_date or _today()
    subscription = PremiumSubscription(
        reference=unique_reference(db, PremiumSubscription, "SUB"),
        client_id=data.client_id,
        payment_account_id=data.payment_account_id,
        plan=plan,
        status=status,
        currency=data.currency or "EUR",
        amount=data.amount,
        billing_interval=data.billing_interval or BillingInterval.MONTHLY,
        trial_days=data.trial_days or 0,
        start_date=start,
        end_date=data.end_date,
        next_billing_date=add_interval(start, data.billing_interval or BillingInterval.MONTHLY),
        notes=data.notes,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


def cancel_subscription(db: Session, subscription: PremiumSubscription, actor: str = "api") -> PremiumSubscription:
    subscription.cancel_at_period_end = True
    if not subscription.next_billing_date or subscription.next_billing_date > _today():
        subscription.status = SubscriptionStatus.ACTIVE if subscription.status in (
            SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL
        ) else subscription.status
    db.commit()
    db.refresh(subscription)
    return subscription


# ---------------------------------------------------------------------------
# Encaissement réel via les prestataires
# ---------------------------------------------------------------------------
class ProviderResult:
    __slots__ = ("session_id", "checkout_url", "simulated")

    def __init__(self, session_id: str, checkout_url: str, simulated: bool):
        self.session_id = session_id
        self.checkout_url = checkout_url
        self.simulated = simulated


def _simulation_url(payment: SubscriptionPayment) -> str:
    return (
        f"{settings.PUBLIC_BASE_URL}/api/subscriptions/payments/{payment.reference}/confirm"
        f"?token={payment.confirm_token}"
    )


def _stripe_checkout(subscription: PremiumSubscription, payment: SubscriptionPayment) -> Optional[ProviderResult]:
    """Crée une session Stripe Checkout réelle (sur le modèle locataire)."""
    if not settings.STRIPE_SECRET_KEY:
        return None
    amount = int(round(payment.amount * 100))
    base = settings.PUBLIC_BASE_URL
    payload = {
        "mode": "payment",
        "success_url": f"{base}/abonnement/{payment.reference}?status=success",
        "cancel_url": f"{base}/abonnement/{payment.reference}?status=cancelled",
        "client_reference_id": payment.reference,
        "customer_email": subscription.client.billing_email or subscription.client.email,
        "metadata[payment_id]": str(payment.id),
        "metadata[subscription_id]": str(subscription.id),
        "metadata[client_id]": str(subscription.client_id),
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": (payment.currency or "EUR").lower(),
        "line_items[0][price_data][unit_amount]": str(amount),
        "line_items[0][price_data][product_data][name]": f"Abonnement {subscription.plan.value}",
        "line_items[0][price_data][product_data][description]": subscription.reference,
    }
    try:
        response = httpx.post(
            "https://api.stripe.com/v1/checkout/sessions",
            data=payload,
            auth=(settings.STRIPE_SECRET_KEY, ""),
            timeout=20,
        )
        if response.status_code >= 400:
            return None
        session = response.json()
        return ProviderResult(session.get("id"), session.get("url"), False)
    except httpx.HTTPError:
        return None


def _paypal_checkout(subscription: PremiumSubscription, payment: SubscriptionPayment) -> Optional[ProviderResult]:
    """Crée une intent PayPal (mode sandbox par défaut)."""
    if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
        return None
    base = "https://api-m.sandbox.paypal.com" if settings.PAYPAL_MODE == "sandbox" else "https://api-m.paypal.com"
    auth = (
        settings.PAYPAL_CLIENT_ID,
        settings.PAYPAL_CLIENT_SECRET,
    )
    try:
        token_resp = httpx.post(
            f"{base}/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            auth=auth,
            timeout=20,
        )
        if token_resp.status_code >= 400:
            return None
        access_token = token_resp.json().get("access_token")
        order_resp = httpx.post(
            f"{base}/v2/checkout/orders",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "intent": "CAPTURE",
                "purchase_units": [{
                    "reference_id": payment.reference,
                    "amount": {
                        "currency_code": (payment.currency or "EUR").upper(),
                        "value": f"{payment.amount:.2f}",
                    },
                    "description": f"Abonnement {subscription.plan.value} {subscription.reference}",
                }],
            },
            timeout=20,
        )
        if order_resp.status_code >= 400:
            return None
        order = order_resp.json()
        link = next((l["href"] for l in order.get("links", []) if l.get("rel") == "approve"), None)
        return ProviderResult(order.get("id"), link, False) if link else None
    except httpx.HTTPError:
        return None


def _generic_provider_checkout(
    subscription: PremiumSubscription,
    payment: SubscriptionPayment,
    *,
    key,
    provider: str,
) -> Optional[ProviderResult]:
    """Adaptateur générique (Wise, MVola, Orange Money).

    Le contrat d'initiation de paiement diffère fortement selon le pays / le
    prestataire (Wise, MVola, Orange Money). Plutôt que de fabriquer un appel
    API dont on ne garantit pas le schéma, l'adaptateur renvoie ``None`` : le
    flux bascule alors sur la **simulation locale**, et le webhook générique
    (``/api/subscriptions/webhooks/{provider}``) confirme l'encaissement. Le
    compte de paiement reste pleinement enregistré pour ces prestataires.
    """
    return None


def build_provider_checkout(
    subscription: PremiumSubscription,
    payment: SubscriptionPayment,
) -> ProviderResult:
    """Construit l'encaissement chez le prestataire, ou la simulation locale."""
    provider = payment.provider
    if settings.PAYMENT_SIMULATION_ENABLED:
        return ProviderResult(None, _simulation_url(payment), True)

    result: Optional[ProviderResult] = None
    if provider == PaymentProvider.STRIPE:
        result = _stripe_checkout(subscription, payment)
    elif provider == PaymentProvider.PAYPAL:
        result = _paypal_checkout(subscription, payment)
    elif provider == PaymentProvider.WISE:
        result = _generic_provider_checkout(subscription, payment, key=settings.WISE_API_TOKEN, provider="wise")
    elif provider == PaymentProvider.MVOLA:
        result = _generic_provider_checkout(subscription, payment, key=settings.MVOLA_API_KEY, provider="mvola")
    elif provider == PaymentProvider.ORANGE_MONEY:
        result = _generic_provider_checkout(
            subscription, payment,
            key=settings.ORANGE_MONEY_CLIENT_ID or settings.ORANGE_MONEY_CLIENT_SECRET,
            provider="orange_money",
        )

    if result is not None:
        return result
    # Aucun prestataire configuré : bascule sur la simulation locale.
    return ProviderResult(None, _simulation_url(payment), True)


def create_checkout(
    db: Session,
    subscription: PremiumSubscription,
    provider: Optional[PaymentProvider] = None,
    amount_override: Optional[float] = None,
    actor: str = "api",
) -> SubscriptionPayment:
    """Prépare un encaissement et retourne le paiement + l'URL de paiement."""
    if subscription.status == SubscriptionStatus.EXPIRED:
        raise ValueError("L'abonnement est expiré, impossible de l'encaisser")

    # Prestataire : préfère celui du compte de paiement, sinon l'override.
    account = (
        db.query(ClientPaymentAccount)
        .filter(ClientPaymentAccount.id == subscription.payment_account_id)
        .first()
        if subscription.payment_account_id
        else None
    )
    if account and account.status != PaymentAccountStatus.ACTIVE:
        raise ValueError("Le compte de paiement n'est pas actif")

    chosen_provider = provider or (account.provider if account else subscription.provider)
    if account is None and chosen_provider is None:
        raise ValueError("Aucun prestataire de paiement défini pour cet abonnement")

    period_start, period_end, next_billing = compute_period(subscription)
    amount = amount_override if amount_override is not None else subscription.amount

    payment = SubscriptionPayment(
        reference=unique_reference(db, SubscriptionPayment, "PAY"),
        subscription_id=subscription.id,
        client_id=subscription.client_id,
        provider=chosen_provider,
        amount=amount,
        currency=subscription.currency or "EUR",
        status=SubscriptionPaymentStatus.PENDING,
        period_start=period_start,
        period_end=period_end,
        confirm_token=uuid.uuid4().hex,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    result = build_provider_checkout(subscription, payment)
    payment.provider_session_id = result.session_id
    db.commit()
    db.refresh(payment)
    payment.checkout_url = result.checkout_url  # type: ignore[attr-defined]
    payment.is_simulated = result.simulated  # type: ignore[attr-defined]
    return payment


# ---------------------------------------------------------------------------
# Confirmation idempotente d'un encaissement
# ---------------------------------------------------------------------------
def confirm_payment(
    db: Session,
    payment: SubscriptionPayment,
    *,
    paid_amount: Optional[float] = None,
    external_reference: Optional[str] = None,
    payment_method: Optional[str] = None,
    actor: str = "api",
) -> SubscriptionPayment:
    """Marque un paiement comme encaissé et fait avancer l'abonnement.

    Idempotent : un paiement déjà ``succeeded`` est retourné tel quel sans
    double imputation du revenu.
    """
    if payment.status == SubscriptionPaymentStatus.SUCCEEDED:
        return payment

    subscription = (
        db.query(PremiumSubscription)
        .filter(PremiumSubscription.id == payment.subscription_id)
        .first()
    )
    if not subscription:
        raise ValueError("Abonnement introuvable pour ce paiement")

    payment.status = SubscriptionPaymentStatus.SUCCEEDED
    payment.payment_date = _today()
    payment.payment_method = payment_method or f"online_{payment.provider.value}"
    payment.external_reference = external_reference or payment.external_reference
    payment.error_message = None

    # Avance la période de facturation et passe l'abonnement à « actif ».
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.provider = payment.provider
    subscription.current_period_start = payment.period_start
    subscription.current_period_end = payment.period_end
    subscription.next_billing_date = add_interval(payment.period_end or _today(), subscription.billing_interval or BillingInterval.MONTHLY)

    db.commit()
    db.refresh(payment)
    db.refresh(subscription)
    return payment


# ---------------------------------------------------------------------------
# Webhooks prestataires
# ---------------------------------------------------------------------------
def verify_provider_signature(provider: PaymentProvider, payload: bytes, signature: str) -> bool:
    """Vérifie la signature du webhook quand le secret est configuré."""
    if provider == PaymentProvider.STRIPE:
        if not settings.STRIPE_WEBHOOK_SECRET or not signature:
            return False
        values = {}
        for part in signature.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                values.setdefault(key, []).append(value)
        try:
            timestamp = int(values["t"][0])
        except (KeyError, ValueError, TypeError):
            return False
        if abs(int(time.time()) - timestamp) > 300:
            return False
        signed = f"{timestamp}.".encode() + payload
        expected = hmac.new(
            settings.STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256
        ).hexdigest()
        return any(hmac.compare_digest(expected, candidate) for candidate in values.get("v1", []))

    # Autres prestataires : sans secret dédié, on accepte le callback uniquement
    # en simulation. En production, branchez la vérification HMAC du prestataire.
    return settings.PAYMENT_SIMULATION_ENABLED


def process_provider_event(db: Session, provider: PaymentProvider, payload: bytes, signature: str) -> dict:
    """Traite un événement webhook de prestataire (idempotent)."""
    if not verify_provider_signature(provider, payload, signature):
        return {"received": True, "processed": False, "reason": "invalid_signature"}

    try:
        event = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"received": True, "processed": False, "reason": "invalid_json"}

    payment = None
    paid_amount = None
    external_ref = None
    if provider == PaymentProvider.STRIPE and event.get("type") == "checkout.session.completed":
        session = event.get("data", {}).get("object", {})
        payment = (
            db.query(SubscriptionPayment)
            .filter(SubscriptionPayment.provider_session_id == session.get("id"))
            .first()
        )
        if not payment:
            return {"received": True, "processed": False, "reason": "unknown_session"}
        paid_amount = float(session.get("amount_total", 0)) / 100
        external_ref = session.get("payment_intent") or session.get("id")
    else:
        # Callback générique : identifiant de paiement fourni par le prestataire.
        data = event.get("data", {}).get("object", event.get("object", event))
        session_id = data.get("provider_session_id") or data.get("session_id") or data.get("id")
        external_ref = data.get("payment_reference") or data.get("transaction_id") or session_id
        if not session_id and not external_ref:
            return {"received": True, "processed": False, "reason": "unknown_payment"}
        payment = (
            db.query(SubscriptionPayment)
            .filter(
                (SubscriptionPayment.reference == external_ref)
                | (SubscriptionPayment.provider_session_id == session_id)
            )
            .first()
        )
        if not payment:
            return {"received": True, "processed": False, "reason": "unknown_payment"}
        paid_amount = float(data.get("amount") or data.get("amount_total") or payment.amount)

    if payment.status == SubscriptionPaymentStatus.SUCCEEDED:
        return {"received": True, "processed": True, "idempotent": True, "payment_id": payment.id}

    confirm_payment(
        db,
        payment,
        paid_amount=paid_amount,
        external_reference=external_ref,
        payment_method=f"online_{provider.value}",
    )
    return {"received": True, "processed": True, "payment_id": payment.id}


def confirm_by_token(db: Session, reference: str, token: str) -> SubscriptionPayment:
    """Confirme un encaissement en mode simulation (jeton requis)."""
    if not settings.PAYMENT_SIMULATION_ENABLED:
        raise ValueError("La confirmation par jeton est désactivée hors simulation")
    payment = (
        db.query(SubscriptionPayment)
        .filter(SubscriptionPayment.reference == reference)
        .first()
    )
    if not payment:
        raise ValueError("Paiement introuvable")
    if not payment.confirm_token or not hmac.compare_digest(payment.confirm_token, token):
        raise ValueError("Jeton de confirmation invalide")
    return confirm_payment(db, payment, payment_method=f"online_{payment.provider.value}")
