"""Modèles du module « Abonnements & revenus récurrents ».

Ce module ajoute un concept générique de **client** (au-delà des propriétaires /
locataires existants), des **comptes de paiement** rattachés aux prestataires
(Stripe, PayPal, Wise, MVola, Orange Money) et des **abonnements premium**
générant un revenu récurrent, encaissé réellement via le prestataire choisi
(paiement en ligne avec webhook idempotent, sur le modèle du paiement Stripe
locataire déjà en place).

L'API s'adresse à l'équipe d'administration (les endpoints sont protégés par
``require_read`` / ``require_write``) et le webhook de notification du
prestataire reste public (comme ``/tenant-portal/payments/webhook/stripe``).
"""

import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# ---------------------------------------------------------------------------
# Enums métier
# ---------------------------------------------------------------------------
class PaymentProvider(str, enum.Enum):
    STRIPE = "stripe"
    PAYPAL = "paypal"
    WISE = "wise"
    MVOLA = "mvola"
    ORANGE_MONEY = "orange_money"


class PaymentAccountStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    VERIFICATION_PENDING = "verification_pending"
    REVOKED = "revoked"


class SubscriptionPlan(str, enum.Enum):
    BASIC = "basic"
    PREMIUM = "premium"          # Abonnement premium
    BUSINESS = "business"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, enum.Enum):
    DRAFT = "draft"
    TRIAL = "trial"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BillingInterval(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMI_ANNUAL = "semi_annual"
    ANNUAL = "annual"


class SubscriptionPaymentStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"


# ---------------------------------------------------------------------------
# Client (concept générique de contrepartie d'un abonnement)
# ---------------------------------------------------------------------------
class SubscriptionClient(Base):
    __tablename__ = "subscription_clients"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    legal_name = Column(String(255))
    email = Column(String(255), index=True)
    phone = Column(String(50))
    address = Column(String(255))
    city = Column(String(120))
    postal_code = Column(String(20))
    country = Column(String(80), default="Madagascar")
    billing_email = Column(String(255))
    tax_reference = Column(String(120))
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    payment_accounts = relationship(
        "ClientPaymentAccount",
        back_populates="client",
        cascade="all, delete-orphan",
    )
    subscriptions = relationship(
        "PremiumSubscription",
        back_populates="client",
        cascade="all, delete-orphan",
    )
    payments = relationship("SubscriptionPayment", back_populates="client")


# ---------------------------------------------------------------------------
# Compte de paiement chez un prestataire
# ---------------------------------------------------------------------------
class ClientPaymentAccount(Base):
    __tablename__ = "client_payment_accounts"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(
        Integer,
        ForeignKey("subscription_clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(Enum(PaymentProvider), nullable=False, index=True)
    label = Column(String(150))
    # Identifiant du compte chez le prestataire (ex : acct_xxx Stripe, email
    # PayPal/Wise, numéro MVola/Orange Money). Fait office de clé externe.
    provider_account_id = Column(String(255), index=True)
    currency = Column(String(10), default="EUR")
    is_default = Column(Boolean, default=False)
    status = Column(
        Enum(PaymentAccountStatus), default=PaymentAccountStatus.ACTIVE, nullable=False, index=True
    )
    # Métadonnées propres au prestataire (mode de test, pays, banque, etc.)
    external_metadata = Column(JSON, default=dict)
    last_verified_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("client_id", "provider", name="uq_client_payment_account_provider"),
    )

    client = relationship("SubscriptionClient", back_populates="payment_accounts")
    subscriptions = relationship("PremiumSubscription", back_populates="payment_account")


# ---------------------------------------------------------------------------
# Abonnement premium (revenu récurrent)
# ---------------------------------------------------------------------------
class PremiumSubscription(Base):
    __tablename__ = "premium_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    client_id = Column(
        Integer,
        ForeignKey("subscription_clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_account_id = Column(
        Integer,
        ForeignKey("client_payment_accounts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    plan = Column(Enum(SubscriptionPlan), default=SubscriptionPlan.PREMIUM, nullable=False, index=True)
    status = Column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.DRAFT, nullable=False, index=True
    )
    currency = Column(String(10), default="EUR")
    amount = Column(Float, nullable=False)
    billing_interval = Column(
        Enum(BillingInterval), default=BillingInterval.MONTHLY, nullable=False
    )
    trial_days = Column(Integer, default=0)
    start_date = Column(Date)
    end_date = Column(Date)
    next_billing_date = Column(Date, index=True)
    current_period_start = Column(Date)
    current_period_end = Column(Date)
    # Identifiant d'abonnement chez le prestataire (sub_xxx Stripe, etc.)
    external_subscription_id = Column(String(255), index=True)
    provider = Column(Enum(PaymentProvider), nullable=True, index=True)
    cancel_at_period_end = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    client = relationship("SubscriptionClient", back_populates="subscriptions")
    payment_account = relationship("ClientPaymentAccount", back_populates="subscriptions")
    payments = relationship(
        "SubscriptionPayment",
        back_populates="subscription",
        cascade="all, delete-orphan",
    )


# ---------------------------------------------------------------------------
# Encaissement / revenu généré
# ---------------------------------------------------------------------------
class SubscriptionPayment(Base):
    __tablename__ = "subscription_payments"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    subscription_id = Column(
        Integer,
        ForeignKey("premium_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id = Column(
        Integer,
        ForeignKey("subscription_clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(Enum(PaymentProvider), nullable=False, index=True)
    provider_session_id = Column(String(255), index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="EUR")
    status = Column(
        Enum(SubscriptionPaymentStatus), default=SubscriptionPaymentStatus.PENDING, nullable=False, index=True
    )
    payment_date = Column(Date)
    period_start = Column(Date)
    period_end = Column(Date)
    payment_method = Column(String(100))
    external_reference = Column(String(255), index=True)
    error_message = Column(Text)
    # Jeton utilisé en mode simulation (aucun prestataire live) pour confirmer
    # l'encaissement sans exposer de donnée sensible.
    confirm_token = Column(String(64), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    subscription = relationship("PremiumSubscription", back_populates="payments")
    client = relationship("SubscriptionClient", back_populates="payments")
