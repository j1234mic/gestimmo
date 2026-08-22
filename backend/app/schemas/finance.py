"""Schémas Pydantic du module 5 : gestion financière et comptabilité."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.finance import (
    BankAccountType,
    ChargeAllocationKey,
    ChargeRecoverability,
    DepositStatus,
    ExportFormat,
    InvoiceStatus,
    InvoiceType,
    JournalEntryStatus,
    PaymentStage,
    ReminderChannel,
    ReconciliationStatus,
)


# ---------------------------------------------------------------------------
# Comptes bancaires et rapprochement
# ---------------------------------------------------------------------------
class BankAccountCreate(BaseModel):
    name: str
    bank_name: Optional[str] = None
    account_type: BankAccountType = BankAccountType.OPERATING
    iban: Optional[str] = None
    bic: Optional[str] = None
    account_number: Optional[str] = None
    currency: str = "EUR"
    opening_balance: float = 0
    notes: Optional[str] = None


class BankAccountUpdate(BaseModel):
    name: Optional[str] = None
    bank_name: Optional[str] = None
    account_type: Optional[BankAccountType] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    account_number: Optional[str] = None
    currency: Optional[str] = None
    opening_balance: Optional[float] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class BankStatementLineCreate(BaseModel):
    transaction_date: date
    amount: float
    label: Optional[str] = None
    counterparty: Optional[str] = None
    reference: Optional[str] = None
    internal_reference: Optional[str] = None


class BankStatementImport(BaseModel):
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    currency: str = "EUR"
    lines: List[BankStatementLineCreate] = Field(default_factory=list)
    raw_filename: Optional[str] = None


class BankReconciliationCreate(BaseModel):
    bank_account_id: int
    period_start: date
    period_end: date
    opening_balance: float = 0
    closing_balance: float = 0


class MatchInput(BaseModel):
    line_id: int
    matched_type: str  # rent_payment, owner_transaction, invoice
    matched_id: int
    amount: float


# ---------------------------------------------------------------------------
# Impayés, relances et plans d'apurement
# ---------------------------------------------------------------------------
class LatePaymentDetectInput(BaseModel):
    tenant_id: int
    lease_id: int
    rent_payment_id: Optional[int] = None
    period: str
    amount_due: float
    due_date: date


class ReminderTrigger(BaseModel):
    stage: PaymentStage
    channel: ReminderChannel
    template: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    cost: float = 0


class PenaltyCalculation(BaseModel):
    principal: float
    days: int
    annual_rate_percent: float = 5.0  # taux d'intérêt légal paramétrable


class PaymentPlanCreate(BaseModel):
    tenant_id: int
    lease_id: int
    total_amount: float
    installments_count: int = Field(..., ge=1, le=120)
    first_due_date: date
    agreed_at: Optional[date] = None
    notes: Optional[str] = None


class InstallmentPayment(BaseModel):
    paid_at: Optional[datetime] = None


class UnpaidCaseCreate(BaseModel):
    late_payment_id: int
    outstanding_amount: float
    huissier_name: Optional[str] = None
    court_reference: Optional[str] = None
    tribunal: Optional[str] = None
    next_action_date: Optional[date] = None
    description: Optional[str] = None


class CaseActionCreate(BaseModel):
    action_type: str
    action_date: date
    description: Optional[str] = None
    actor: Optional[str] = None
    cost: float = 0
    result: Optional[str] = None


# ---------------------------------------------------------------------------
# Charges et répartition
# ---------------------------------------------------------------------------
class ChargeCreate(BaseModel):
    property_id: int
    lease_id: Optional[int] = None
    charge_type: str
    category: Optional[str] = None
    amount: float
    vat_rate: float = 0
    recoverability: ChargeRecoverability = ChargeRecoverability.RECOVERABLE
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    allocation_key: ChargeAllocationKey = ChargeAllocationKey.TANTIEMES
    provider_name: Optional[str] = None
    invoice_reference: Optional[str] = None
    is_coproperty: bool = False
    notes: Optional[str] = None


class ChargeAllocationRuleCreate(BaseModel):
    property_id: int
    name: str
    key: ChargeAllocationKey = ChargeAllocationKey.TANTIEMES
    custom_expr: Optional[str] = None
    is_default: bool = False


class ChargeRegularizationInput(BaseModel):
    year: int


class BudgetPrevisionnel(BaseModel):
    property_id: int
    year: int


# ---------------------------------------------------------------------------
# Comptabilité générale
# ---------------------------------------------------------------------------
class AccountingAccountCreate(BaseModel):
    code: str
    label: str
    account_type: str
    parent_code: Optional[str] = None
    is_system: bool = False
    description: Optional[str] = None


class JournalLineCreate(BaseModel):
    account_id: int
    debit: float = 0
    credit: float = 0
    label: Optional[str] = None
    tenant_id: Optional[int] = None


class JournalEntryCreate(BaseModel):
    entry_date: date
    label: str
    description: Optional[str] = None
    reference: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    property_id: Optional[int] = None
    lines: List[JournalLineCreate] = Field(..., min_length=1)


class JournalEntryValidate(BaseModel):
    do_validate: bool = True
    created_by: Optional[str] = None


# ---------------------------------------------------------------------------
# Facturation
# ---------------------------------------------------------------------------
class InvoiceLineCreate(BaseModel):
    description: str
    quantity: float = 1
    unit_price: float
    vat_rate: float = 0
    account_code: Optional[str] = None


class InvoiceCreate(BaseModel):
    invoice_type: InvoiceType
    status: InvoiceStatus = InvoiceStatus.DRAFT
    invoice_date: date
    due_date: Optional[date] = None
    issuer_type: str
    issuer_id: Optional[int] = None
    issuer_name: Optional[str] = None
    recipient_type: str
    recipient_id: Optional[int] = None
    recipient_name: Optional[str] = None
    property_id: Optional[int] = None
    lease_id: Optional[int] = None
    tax_exempt: bool = False
    notes: Optional[str] = None
    generated_from: Optional[str] = None
    created_by: Optional[str] = None
    lines: List[InvoiceLineCreate] = Field(..., min_length=1)


class InvoiceUpdate(BaseModel):
    status: Optional[InvoiceStatus] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Dépôts de garantie
# ---------------------------------------------------------------------------
class DepositCreate(BaseModel):
    lease_id: int
    tenant_id: int
    property_id: int
    amount: float
    received_at: date
    payment_method: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    restitution_legal_delay_months: int = 1
    interest_rate: float = 0
    notes: Optional[str] = None


class DepositDeductionCreate(BaseModel):
    label: str
    amount: float
    justification: Optional[str] = None
    supporting_document_url: Optional[str] = None


class DepositRestitution(BaseModel):
    amount_returned: float
    returned_at: date


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------
class ExportInput(BaseModel):
    export_format: ExportFormat
    period_start: date
    period_end: date
    entity_type: str = "global"
    entity_id: Optional[int] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Rapports (réponse générique)
# ---------------------------------------------------------------------------
class ChargeBudgetReport(BaseModel):
    property_id: int
    year: int
    budget: float
    actual: float
    difference: float
    progress_percent: float


class UnpaidReport(BaseModel):
    total_unpaid: float
    count: int
    by_stage: Dict[str, Any] = Field(default_factory=dict)
    by_tenant: List[Dict[str, Any]] = Field(default_factory=list)
