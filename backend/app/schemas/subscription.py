"""Schémas du module « Abonnements & revenus récurrents »."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.subscription import (
    BillingInterval,
    PaymentAccountStatus,
    PaymentProvider,
    SubscriptionPaymentStatus,
    SubscriptionPlan,
    SubscriptionStatus,
)

_CONFIG = {"from_attributes": True}


class _Base(BaseModel):
    model_config = _CONFIG


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class ClientCreate(BaseModel):
    name: str
    legal_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "Madagascar"
    billing_email: Optional[str] = None
    tax_reference: Optional[str] = None
    notes: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    legal_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    billing_email: Optional[str] = None
    tax_reference: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class ClientResponse(_Base):
    id: int
    reference: str
    name: str
    legal_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    billing_email: Optional[str] = None
    tax_reference: Optional[str] = None
    notes: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Compte de paiement
# ---------------------------------------------------------------------------
class PaymentAccountCreate(BaseModel):
    client_id: int
    provider: PaymentProvider
    label: Optional[str] = None
    provider_account_id: Optional[str] = None
    currency: str = "EUR"
    is_default: bool = False
    external_metadata: Optional[dict] = None
    notes: Optional[str] = None


class PaymentAccountUpdate(BaseModel):
    label: Optional[str] = None
    provider_account_id: Optional[str] = None
    currency: Optional[str] = None
    is_default: Optional[bool] = None
    status: Optional[PaymentAccountStatus] = None
    external_metadata: Optional[dict] = None
    notes: Optional[str] = None


class PaymentAccountResponse(_Base):
    id: int
    client_id: int
    provider: PaymentProvider
    label: Optional[str] = None
    provider_account_id: Optional[str] = None
    currency: Optional[str] = None
    is_default: bool
    status: PaymentAccountStatus
    external_metadata: Optional[dict] = None
    last_verified_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Abonnement premium
# ---------------------------------------------------------------------------
class SubscriptionCreate(BaseModel):
    client_id: int
    payment_account_id: Optional[int] = None
    plan: SubscriptionPlan = SubscriptionPlan.PREMIUM
    currency: str = "EUR"
    amount: float = Field(gt=0)
    billing_interval: BillingInterval = BillingInterval.MONTHLY
    trial_days: int = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None


class SubscriptionUpdate(BaseModel):
    payment_account_id: Optional[int] = None
    plan: Optional[SubscriptionPlan] = None
    status: Optional[SubscriptionStatus] = None
    currency: Optional[str] = None
    amount: Optional[float] = None
    billing_interval: Optional[BillingInterval] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    cancel_at_period_end: Optional[bool] = None
    notes: Optional[str] = None


class SubscriptionResponse(_Base):
    id: int
    reference: str
    client_id: int
    payment_account_id: Optional[int] = None
    plan: SubscriptionPlan
    status: SubscriptionStatus
    currency: Optional[str] = None
    amount: float
    billing_interval: BillingInterval
    trial_days: int
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    next_billing_date: Optional[date] = None
    current_period_start: Optional[date] = None
    current_period_end: Optional[date] = None
    external_subscription_id: Optional[str] = None
    provider: Optional[PaymentProvider] = None
    cancel_at_period_end: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Encaissement / revenu
# ---------------------------------------------------------------------------
class CheckoutCreate(BaseModel):
    # Le prestataire est déduit du compte de paiement de l'abonnement ; on
    # autorise toutefois à le surcharger (s'il est présent).
    provider: Optional[PaymentProvider] = None
    amount: Optional[float] = Field(default=None, gt=0)


class CheckoutResponse(_Base):
    payment_id: int
    payment_reference: str
    subscription_id: int
    client_id: int
    provider: PaymentProvider
    session_id: Optional[str] = None
    checkout_url: Optional[str] = None
    amount: float
    currency: str
    status: SubscriptionPaymentStatus
    simulated: bool


class PaymentResponse(_Base):
    id: int
    reference: str
    subscription_id: int
    client_id: int
    provider: PaymentProvider
    provider_session_id: Optional[str] = None
    amount: float
    currency: Optional[str] = None
    status: SubscriptionPaymentStatus
    payment_date: Optional[date] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    payment_method: Optional[str] = None
    external_reference: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConfirmResponse(_Base):
    payment_id: int
    reference: str
    status: SubscriptionPaymentStatus
    subscription_id: int
    subscription_status: SubscriptionStatus
    paid_amount: float
    currency: str
