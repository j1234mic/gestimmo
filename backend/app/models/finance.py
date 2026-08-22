"""Modèles du module 5 : gestion financière et comptabilité.

Ce module complète le suivi locatif existant (RentPayment / RentReceipt) par le
volet comptable et financier : appels de loyer, encaissements multi-canal,
impayés et relances, charges et régularisation, comptabilité générale,
facturation, dépôt de garantie et exports comptables.
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
class BankAccountType(str, enum.Enum):
    OPERATING = "operating"          # Compte d'exploitation / gérance
    OWNER = "owner"                  # Compte bancaire du propriétaire
    COLLECTION = "collection"        # Compte de collection des loyers
    OTHER = "other"


class ReconciliationStatus(str, enum.Enum):
    DRAFT = "draft"                  # Import réalisé, en attente de pointage
    IN_PROGRESS = "in_progress"      # Matching en cours
    RECONCILED = "reconciled"        # Solde vérifié
    CLOSED = "closed"


class PaymentStage(str, enum.Enum):
    """Étapes du workflow de relance d'un impayé."""
    DETECTED = "detected"            # Retard détecté
    AMIABLE = "amiable"              # J+5 relance amiable
    FIRM = "firm"                    # J+15 relance ferme
    DEMANDE = "demande"              # J+30 mise en demeure
    COMMANDEMENT = "commandement"    # J+60 commandement de payer
    CONTENTIEUX = "contentieux"      # J+90 procédure contentieuse
    RESOLVED = "resolved"


class ReminderChannel(str, enum.Enum):
    EMAIL = "email"
    SMS = "sms"
    LETTER = "letter"                # Courrier
    AR_LETTER = "ar_letter"          # Courrier recommandé avec AR
    HUISSIER = "huissier"
    TRIBUNAL = "tribunal"
    OTHER = "other"


class ChargeAllocationKey(str, enum.Enum):
    TANTIEMES = "tantièmes"
    SURFACE = "surface"
    OCCUPANTS = "occupants"
    CUSTOM = "custom"


class ChargeRecoverability(str, enum.Enum):
    RECOVERABLE = "recoverable"      # Récupérable (répercutable au locataire)
    NON_RECOVERABLE = "non_recoverable"



class JournalEntryStatus(str, enum.Enum):
    DRAFT = "draft"
    VALIDATED = "validated"
    REVERSED = "reversed"


class InvoiceType(str, enum.Enum):
    HONORAIRE = "honoraire"          # Facture d'honoraires
    PRESTATION = "prestation"        # Facture de prestations
    DEVIS = "devis"
    AVOIR = "avoir"
    OTHER = "other"


class InvoiceStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


class DepositStatus(str, enum.Enum):
    HELD = "held"                    # Encaissé, retenu en garantie
    PARTIALLY_RETURNED = "partially_returned"
    RETURNED = "returned"
    WITHHELD = "withheld"            # Aucune restitution (retenues)
    DISPUTED = "disputed"


class ExportFormat(str, enum.Enum):
    FEC = "fec"
    CSV = "csv"
    SAGE = "sage"
    QUICKBOOKS = "quickbooks"
    CIEL = "ciel"
    CUSTOM = "custom"
    ANNUAL_TAX = "annual_tax"


# ---------------------------------------------------------------------------
# Comptes bancaires et rapprochement
# ---------------------------------------------------------------------------
class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(150), nullable=False)
    bank_name = Column(String(200))
    account_type = Column(Enum(BankAccountType), default=BankAccountType.OPERATING, nullable=False)
    iban = Column(String(34))
    bic = Column(String(11))
    account_number = Column(String(50))
    currency = Column(String(10), default="EUR")
    opening_balance = Column(Float, default=0)
    current_balance = Column(Float, default=0)
    is_active = Column(Boolean, default=True)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    statements = relationship("BankStatement", back_populates="account", cascade="all, delete-orphan")
    reconciliations = relationship("BankReconciliation", back_populates="account", cascade="all, delete-orphan")


class BankStatement(Base):
    __tablename__ = "bank_statements"

    id = Column(Integer, primary_key=True, index=True)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    reference = Column(String(50), unique=True)
    import_source = Column(String(30), default="manual")  # ofx, csv, mt940, manual
    period_start = Column(Date)
    period_end = Column(Date)
    currency = Column(String(10), default="EUR")
    line_count = Column(Integer, default=0)
    total_debit = Column(Float, default=0)
    total_credit = Column(Float, default=0)
    raw_filename = Column(String(255))
    imported_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("BankAccount", back_populates="statements")
    lines = relationship("BankStatementLine", back_populates="statement", cascade="all, delete-orphan")


class BankStatementLine(Base):
    __tablename__ = "bank_statement_lines"

    id = Column(Integer, primary_key=True, index=True)
    statement_id = Column(Integer, ForeignKey("bank_statements.id", ondelete="CASCADE"), nullable=False, index=True)
    transaction_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)          # > 0 crédit, < 0 débit
    label = Column(String(500))
    counterparty = Column(String(255))
    reference = Column(String(100))
    internal_reference = Column(String(50), index=True)
    matched_transaction_id = Column(Integer, nullable=True, index=True)  # FK soft vers OwnerTransaction / RentPayment
    match_type = Column(String(30), default="unmatched")  # auto, manual, unmatched
    match_confidence = Column(Float, default=0)
    is_reconciled = Column(Boolean, default=False)

    statement = relationship("BankStatement", back_populates="lines")


class BankReconciliation(Base):
    __tablename__ = "bank_reconciliations"

    id = Column(Integer, primary_key=True, index=True)
    bank_account_id = Column(Integer, ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    status = Column(Enum(ReconciliationStatus), default=ReconciliationStatus.DRAFT, nullable=False)
    opening_balance = Column(Float, default=0)
    closing_balance = Column(Float, default=0)
    auto_matched_count = Column(Integer, default=0)
    manual_matched_count = Column(Integer, default=0)
    unmatched_count = Column(Integer, default=0)
    matched_total = Column(Float, default=0)
    notes = Column(Text)
    reconciled_by = Column(String(255))
    reconciled_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("BankAccount", back_populates="reconciliations")
    matches = relationship("ReconciliationMatch", back_populates="reconciliation", cascade="all, delete-orphan")


class ReconciliationMatch(Base):
    __tablename__ = "reconciliation_matches"

    id = Column(Integer, primary_key=True, index=True)
    reconciliation_id = Column(Integer, ForeignKey("bank_reconciliations.id", ondelete="CASCADE"), nullable=False, index=True)
    line_id = Column(Integer, ForeignKey("bank_statement_lines.id", ondelete="CASCADE"), nullable=False)
    matched_type = Column(String(30), nullable=False)  # rent_payment, owner_transaction, invoice
    matched_id = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    confidence = Column(Float, default=1.0)
    matched_at = Column(DateTime(timezone=True), server_default=func.now())

    reconciliation = relationship("BankReconciliation", back_populates="matches")
    line = relationship("BankStatementLine")


# ---------------------------------------------------------------------------
# Impayés, relances et plans d'apurement
# ---------------------------------------------------------------------------
class LatePayment(Base):
    __tablename__ = "late_payments"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    rent_payment_id = Column(Integer, ForeignKey("rent_payments.id", ondelete="SET NULL"), nullable=True, index=True)
    period = Column(String(7), nullable=False)  # YYYY-MM
    amount_due = Column(Float, nullable=False)
    amount_outstanding = Column(Float, nullable=False)
    penalty_amount = Column(Float, default=0)
    due_date = Column(Date, nullable=False)
    overdue_days = Column(Integer, default=0)
    stage = Column(Enum(PaymentStage), default=PaymentStage.DETECTED, nullable=False, index=True)
    stage_reached_at = Column(DateTime(timezone=True))
    status = Column(String(30), default="open", index=True)  # open, in_progress, resolved
    plan_id = Column(Integer, ForeignKey("payment_plans.id", ondelete="SET NULL"), nullable=True)
    resolved_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = relationship("Tenant")
    lease = relationship("Lease")
    property = relationship("Property")
    rent_payment = relationship("RentPayment")
    reminders = relationship("ReminderAction", back_populates="late_payment", cascade="all, delete-orphan")
    case = relationship("UnpaidCase", back_populates="late_payment", uselist=False, cascade="all, delete-orphan")


class ReminderAction(Base):
    __tablename__ = "reminder_actions"

    id = Column(Integer, primary_key=True, index=True)
    late_payment_id = Column(Integer, ForeignKey("late_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(Enum(PaymentStage), nullable=False)
    channel = Column(Enum(ReminderChannel), nullable=False)
    template = Column(String(255))
    subject = Column(String(255))
    body = Column(Text)
    status = Column(String(30), default="sent")  # draft, sent, failed, scheduled
    scheduled_for = Column(DateTime(timezone=True))
    sent_at = Column(DateTime(timezone=True))
    cost = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    late_payment = relationship("LatePayment", back_populates="reminders")


class PaymentPlan(Base):
    __tablename__ = "payment_plans"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    total_amount = Column(Float, nullable=False)
    installments_count = Column(Integer, nullable=False)
    installments_amount = Column(Float, nullable=False)
    first_due_date = Column(Date, nullable=False)
    status = Column(String(30), default="active", index=True)  # active, in_progress, completed, defaulted, cancelled
    agreed_at = Column(Date)
    completed_at = Column(DateTime(timezone=True))
    defaulted_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    installments = relationship("PaymentPlanInstallment", back_populates="plan", cascade="all, delete-orphan")


class PaymentPlanInstallment(Base):
    __tablename__ = "payment_plan_installments"
    __table_args__ = (UniqueConstraint("plan_id", "position", name="uq_plan_installment_position"),)

    id = Column(Integer, primary_key=True)
    plan_id = Column(Integer, ForeignKey("payment_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False)
    due_date = Column(Date, nullable=False)
    amount = Column(Float, nullable=False)
    paid_at = Column(DateTime(timezone=True))
    status = Column(String(30), default="pending")  # pending, paid, overdue
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan = relationship("PaymentPlan", back_populates="installments")


class UnpaidCase(Base):
    """Dossier contentieux associé à un impayé (huissier, tribunal, historique)."""
    __tablename__ = "unpaid_cases"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    late_payment_id = Column(Integer, ForeignKey("late_payments.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    status = Column(String(30), default="open")  # open, huissier, tribunal, closed, won, lost
    outstanding_amount = Column(Float, default=0)
    huissier_name = Column(String(255))
    court_reference = Column(String(100))
    tribunal = Column(String(255))
    next_action_date = Column(Date)
    opened_at = Column(Date, nullable=False)
    closed_at = Column(Date)
    description = Column(Text)
    resolution = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    late_payment = relationship("LatePayment", back_populates="case")
    actions = relationship("CaseAction", back_populates="case", cascade="all, delete-orphan")


class CaseAction(Base):
    __tablename__ = "case_actions"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("unpaid_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type = Column(String(50), nullable=False)  # huissier, tribunal, audience, jugement, etc.
    action_date = Column(Date, nullable=False)
    description = Column(Text)
    actor = Column(String(255))
    cost = Column(Float, default=0)
    result = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    case = relationship("UnpaidCase", back_populates="actions")


# ---------------------------------------------------------------------------
# Charges et répartition
# ---------------------------------------------------------------------------
class Charge(Base):
    __tablename__ = "charges"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="SET NULL"), nullable=True, index=True)
    charge_type = Column(String(100), nullable=False)  # copropriété, chauffage, eau, etc.
    category = Column(String(100))
    amount = Column(Float, nullable=False)
    vat_rate = Column(Float, default=0)
    recoverability = Column(Enum(ChargeRecoverability), default=ChargeRecoverability.RECOVERABLE, nullable=False)
    period_start = Column(Date)
    period_end = Column(Date)
    allocation_key = Column(Enum(ChargeAllocationKey), default=ChargeAllocationKey.TANTIEMES, nullable=False)
    status = Column(String(30), default="pending")  # pending, allocated, regularized, paid
    provider_name = Column(String(255))
    invoice_reference = Column(String(100))
    notes = Column(Text)
    is_coproperty = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    property = relationship("Property")
    lease = relationship("Lease")
    allocations = relationship("ChargeAllocation", back_populates="charge", cascade="all, delete-orphan")


class ChargeAllocationRule(Base):
    __tablename__ = "charge_allocation_rules"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    key = Column(Enum(ChargeAllocationKey), default=ChargeAllocationKey.TANTIEMES, nullable=False)
    custom_expr = Column(Text)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ChargeAllocation(Base):
    __tablename__ = "charge_allocations"

    id = Column(Integer, primary_key=True, index=True)
    charge_id = Column(Integer, ForeignKey("charges.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    share = Column(Float, nullable=False)            # Coefficient (tantième / surface / occupants)
    share_label = Column(String(255))
    amount = Column(Float, nullable=False)
    allocated_at = Column(DateTime(timezone=True), server_default=func.now())

    charge = relationship("Charge", back_populates="allocations")


class ChargeRegularization(Base):
    __tablename__ = "charge_regularizations"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    provision_total = Column(Float, nullable=False)
    real_total = Column(Float, nullable=False)
    difference = Column(Float, nullable=False)
    status = Column(String(30), default="calculated")  # calculated, notified, accepted, disputed, settled
    calculated_at = Column(DateTime(timezone=True), server_default=func.now())
    notified_at = Column(DateTime(timezone=True))
    settled_at = Column(DateTime(timezone=True))
    detail = Column(JSON, default=dict)
    notes = Column(Text)


# ---------------------------------------------------------------------------
# Comptabilité générale
# ---------------------------------------------------------------------------
class AccountingAccount(Base):
    __tablename__ = "accounting_accounts"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    label = Column(String(255), nullable=False)
    account_type = Column(String(30), nullable=False)  # asset, liability, equity, income, expense
    is_system = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    parent_code = Column(String(20))
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(30), unique=True, nullable=False, index=True)
    entry_date = Column(Date, nullable=False, index=True)
    label = Column(String(255), nullable=False)
    description = Column(Text)
    reference = Column(String(100))
    source_type = Column(String(50))  # rent, invoice, charge, owner_payment, deposit, etc.
    source_id = Column(Integer, index=True)
    status = Column(Enum(JournalEntryStatus), default=JournalEntryStatus.DRAFT, nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(String(255))
    validated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lines = relationship("JournalLine", back_populates="entry", cascade="all, delete-orphan")


class JournalLine(Base):
    __tablename__ = "journal_lines"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounting_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    debit = Column(Float, default=0)
    credit = Column(Float, default=0)
    label = Column(Text)
    tenant_id = Column(Integer, nullable=True)

    entry = relationship("JournalEntry", back_populates="lines")
    account = relationship("AccountingAccount")


# ---------------------------------------------------------------------------
# Facturation
# ---------------------------------------------------------------------------
class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    number = Column(String(30), unique=True, nullable=False, index=True)
    invoice_type = Column(Enum(InvoiceType), nullable=False)
    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.DRAFT, nullable=False)
    invoice_date = Column(Date, nullable=False)
    due_date = Column(Date)
    issuer_type = Column(String(30), nullable=False)  # company / owner / provider
    issuer_id = Column(Integer)
    issuer_name = Column(String(255))
    recipient_type = Column(String(30), nullable=False)  # owner / tenant / company
    recipient_id = Column(Integer)
    recipient_name = Column(String(255))
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="SET NULL"), nullable=True)
    amount_ht = Column(Float, nullable=False)
    vat_rate = Column(Float, default=0)
    vat_amount = Column(Float, default=0)
    amount_ttc = Column(Float, nullable=False)
    tax_exempt = Column(Boolean, default=False)
    notes = Column(Text)
    generated_from = Column(String(50))  # management_fee, prestation, devis, avoir
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    lines = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, default=1)
    description = Column(String(500), nullable=False)
    quantity = Column(Float, default=1)
    unit_price = Column(Float, nullable=False)
    amount_ht = Column(Float, nullable=False)
    vat_rate = Column(Float, default=0)
    account_code = Column(String(20))

    invoice = relationship("Invoice", back_populates="lines")


# ---------------------------------------------------------------------------
# Dépôts de garantie
# ---------------------------------------------------------------------------
class DepositGuarantee(Base):
    __tablename__ = "deposit_guarantees"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    received_at = Column(Date, nullable=False)
    payment_method = Column(String(50))
    status = Column(Enum(DepositStatus), default=DepositStatus.HELD, nullable=False, index=True)
    start_date = Column(Date)
    end_date = Column(Date)
    restitution_legal_delay_months = Column(Integer, default=1)  # 1 mois (vide) ou 2 mois (meublé)
    restitution_deadline = Column(Date)
    amount_returned = Column(Float, default=0)
    amount_withheld = Column(Float, default=0)
    interest_rate = Column(Float, default=0)
    interest_amount = Column(Float, default=0)
    restitution_requested_at = Column(DateTime(timezone=True))
    returned_at = Column(DateTime(timezone=True))
    letter_document_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    lease = relationship("Lease")
    tenant = relationship("Tenant")
    property = relationship("Property")
    deductions = relationship("DepositDeduction", back_populates="deposit", cascade="all, delete-orphan")


class DepositDeduction(Base):
    __tablename__ = "deposit_deductions"

    id = Column(Integer, primary_key=True, index=True)
    deposit_id = Column(Integer, ForeignKey("deposit_guarantees.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(500), nullable=False)
    amount = Column(Float, nullable=False)
    justification = Column(Text)
    supporting_document_url = Column(String(700))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    deposit = relationship("DepositGuarantee", back_populates="deductions")


# ---------------------------------------------------------------------------
# Exports comptables
# ---------------------------------------------------------------------------
class AccountingExport(Base):
    __tablename__ = "accounting_exports"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    export_format = Column(Enum(ExportFormat), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    entity_type = Column(String(30))  # global, owner, property
    entity_id = Column(Integer, nullable=True)
    entry_count = Column(Integer, default=0)
    total_debit = Column(Float, default=0)
    total_credit = Column(Float, default=0)
    status = Column(String(30), default="generated")
    storage_path = Column(String(700))
    generated_by = Column(String(255))
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    notes = Column(Text)
