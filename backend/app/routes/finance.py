"""API du module 5 : gestion financière et comptabilité."""

from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.database import get_db
from app.models.finance import (
    BankAccount,
    BankStatement,
    Charge,
    DepositGuarantee,
    ExportFormat,
    Invoice,
    InvoiceStatus,
    JournalEntry,
    JournalEntryStatus,
    LatePayment,
    PaymentPlan,
    UnpaidCase,
)
from app.models.tenant import Lease, RentPayment, Tenant
from app.schemas.finance import (
    BankAccountCreate,
    BankAccountUpdate,
    BankReconciliationCreate,
    BankStatementImport,
    BudgetPrevisionnel,
    CaseActionCreate,
    ChargeAllocationRuleCreate,
    ChargeCreate,
    ChargeRegularizationInput,
    DepositCreate,
    DepositDeductionCreate,
    DepositRestitution,
    ExportInput,
    InstallmentPayment,
    InvoiceCreate,
    InvoiceUpdate,
    JournalEntryCreate,
    JournalEntryValidate,
    LatePaymentDetectInput,
    MatchInput,
    PaymentPlanCreate,
    PenaltyCalculation,
    ReminderTrigger,
    UnpaidCaseCreate,
)
from app.services.finance_service import (
    add_deposit_deduction,
    advance_reminder_workflow,
    allocate_charge_by_key,
    auto_match_reconciliation,
    build_budget_previsionnel,
    calculate_charge_regularization,
    calculate_deposit_restitution,
    calculate_penalty,
    create_bank_account,
    create_charge,
    create_deposit,
    create_invoice,
    create_journal_entry,
    create_payment_plan,
    create_reconciliation,
    detect_late_payments,
    export_accounting,
    generate_management_fee_invoice,
    generate_rent_calls,
    import_bank_statement,
    list_journal_entries,
    record_installment_payment,
    record_manual_match,
    record_rent_payment,
    reconcile_account,
    return_deposit,
    trial_balance,
    update_invoice_status,
    general_ledger,
)

router = APIRouter(prefix="/api/finance", tags=["Gestion financière et comptabilité"])


# ---------------------------------------------------------------------------
# Comptes bancaires et rapprochement
# ---------------------------------------------------------------------------
@router.post("/bank-accounts", status_code=201)
def create_bank_account_endpoint(data: BankAccountCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    account = create_bank_account(db, data)
    return _bank_account_view(account)


@router.get("/bank-accounts")
def list_bank_accounts(db: Session = Depends(get_db), current_user=Depends(require_read)):
    accounts = db.query(BankAccount).filter(BankAccount.is_active.is_(True)).order_by(BankAccount.name).all()
    return {"data": [_bank_account_view(a) for a in accounts], "count": len(accounts)}


@router.get("/bank-accounts/{bank_account_id}")
def get_bank_account(bank_account_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    account = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Compte bancaire non trouvé")
    return _bank_account_view(account)


@router.put("/bank-accounts/{bank_account_id}")
def update_bank_account(bank_account_id: int, data: BankAccountUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    account = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Compte bancaire non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return _bank_account_view(account)


@router.post("/bank-accounts/{bank_account_id}/statements", status_code=201)
def upload_bank_statement(bank_account_id: int, data: BankStatementImport, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        statement = import_bank_statement(db, bank_account_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": statement.id,
        "reference": statement.reference,
        "account_id": statement.bank_account_id,
        "period_start": statement.period_start,
        "period_end": statement.period_end,
        "line_count": statement.line_count,
        "total_debit": statement.total_debit,
        "total_credit": statement.total_credit,
    }


@router.get("/bank-accounts/{bank_account_id}/statements")
def list_bank_statements(bank_account_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    statements = db.query(BankStatement).filter(BankStatement.bank_account_id == bank_account_id).order_by(BankStatement.period_start.desc()).all()
    return {"data": [
        {
            "id": s.id,
            "reference": s.reference,
            "import_source": s.import_source,
            "period_start": s.period_start,
            "period_end": s.period_end,
            "line_count": s.line_count,
            "total_debit": s.total_debit,
            "total_credit": s.total_credit,
            "imported_at": s.imported_at,
        }
        for s in statements
    ]}


@router.post("/reconciliations", status_code=201)
def create_reconciliation_endpoint(data: BankReconciliationCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    reconciliation = create_reconciliation(db, data)
    return _reconciliation_view(reconciliation)


@router.post("/reconciliations/{reconciliation_id}/auto-match")
def run_auto_match(reconciliation_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return auto_match_reconciliation(db, reconciliation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/reconciliations/{reconciliation_id}/matches")
def manual_match(reconciliation_id: int, data: MatchInput, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return record_manual_match(db, reconciliation_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/reconciliations/{reconciliation_id}/reconcile")
def close_reconciliation(reconciliation_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    from app.models.finance import BankReconciliation
    reconciliation = db.query(BankReconciliation).filter(BankReconciliation.id == reconciliation_id).first()
    if not reconciliation:
        raise HTTPException(status_code=404, detail="Rapprochement non trouvé")
    try:
        return reconcile_account(db, reconciliation.bank_account_id, reconciliation.period_start, reconciliation.period_end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Appels de loyer et encaissement
# ---------------------------------------------------------------------------
@router.post("/rent-calls/generate")
def generate_rent_calls_endpoint(month: Optional[str] = None, as_of: Optional[date] = None, db: Session = Depends(get_db), current_user=Depends(require_write)):
    return generate_rent_calls(db, month, as_of)


@router.post("/payments/{payment_id}/record")
def record_payment(payment_id: int, amount: float = Query(..., gt=0), method: str = Query(...), paid_at: Optional[date] = Query(None), external_reference: Optional[str] = Query(None), notes: Optional[str] = Query(None), db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        payment = record_rent_payment(db, payment_id, amount, method, paid_at, external_reference, notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _payment_view(payment)


# ---------------------------------------------------------------------------
# Impayés, relances, pénalités, plans d'apurement
# ---------------------------------------------------------------------------
@router.post("/late-payments/detect")
def detect_late_payments_endpoint(as_of: Optional[date] = Query(None), db: Session = Depends(get_db), current_user=Depends(require_write)):
    return detect_late_payments(db, as_of)


@router.get("/late-payments")
def list_late_payments(
    stage: Optional[str] = None,
    status: Optional[str] = None,
    tenant_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    query = db.query(LatePayment)
    if stage:
        query = query.filter(LatePayment.stage == stage)
    if status:
        query = query.filter(LatePayment.status == status)
    if tenant_id:
        query = query.filter(LatePayment.tenant_id == tenant_id)
    rows = query.order_by(LatePayment.overdue_days.desc()).all()
    return {"data": [_late_payment_view(r) for r in rows], "count": len(rows)}


@router.get("/late-payments/{late_payment_id}")
def get_late_payment(late_payment_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    late = db.query(LatePayment).filter(LatePayment.id == late_payment_id).first()
    if not late:
        raise HTTPException(status_code=404, detail="Impayé non trouvé")
    view = _late_payment_view(late)
    view["reminders"] = [
        {"id": r.id, "stage": r.stage.value, "channel": r.channel.value, "subject": r.subject, "status": r.status, "sent_at": r.sent_at}
        for r in late.reminders
    ]
    view["case"] = _case_view(late.case) if late.case else None
    return view


@router.post("/late-payments/{late_payment_id}/advance")
def advance_workflow(late_payment_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return advance_reminder_workflow(db, late_payment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/late-payments/{late_payment_id}/penalty")
def compute_penalty(late_payment_id: int, data: PenaltyCalculation, db: Session = Depends(get_db), current_user=Depends(require_read)):
    late = db.query(LatePayment).filter(LatePayment.id == late_payment_id).first()
    if not late:
        raise HTTPException(status_code=404, detail="Impayé non trouvé")
    principal = data.principal or late.amount_outstanding
    days = data.days or late.overdue_days
    return {
        "late_payment_id": late.id,
        "principal": principal,
        "days": days,
        "annual_rate_percent": data.annual_rate_percent,
        "penalty": calculate_penalty(principal, days, data.annual_rate_percent),
    }


@router.post("/payment-plans", status_code=201)
def create_payment_plan_endpoint(data: PaymentPlanCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    plan = create_payment_plan(db, data)
    return _payment_plan_view(plan)


@router.get("/payment-plans/{plan_id}")
def get_payment_plan(plan_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    plan = db.query(PaymentPlan).filter(PaymentPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan d'apurement non trouvé")
    return _payment_plan_view(plan)


@router.post("/payment-plans/installments/{installment_id}/pay")
def pay_installment(installment_id: int, data: InstallmentPayment, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return record_installment_payment(db, installment_id, data.paid_at)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/late-payments/{late_payment_id}/case", status_code=201)
def open_case(late_payment_id: int, data: UnpaidCaseCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    late = db.query(LatePayment).filter(LatePayment.id == late_payment_id).first()
    if not late:
        raise HTTPException(status_code=404, detail="Impayé non trouvé")
    if late.case:
        raise HTTPException(status_code=409, detail="Un dossier contentieux existe déjà pour cet impayé")
    case = UnpaidCase(
        reference=_generate_case_reference(),
        late_payment_id=late.id,
        outstanding_amount=data.outstanding_amount,
        huissier_name=data.huissier_name,
        court_reference=data.court_reference,
        tribunal=data.tribunal,
        next_action_date=data.next_action_date,
        opened_at=date.today(),
        description=data.description,
    )
    late.status = "in_progress"
    db.add(case)
    db.commit()
    db.refresh(case)
    return _case_view(case)


@router.post("/cases/{case_id}/actions", status_code=201)
def add_case_action(case_id: int, data: CaseActionCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    from app.models.finance import CaseAction
    case = db.query(UnpaidCase).filter(UnpaidCase.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Dossier contentieux non trouvé")
    action = CaseAction(case_id=case.id, **data.model_dump())
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


# ---------------------------------------------------------------------------
# Charges et répartition
# ---------------------------------------------------------------------------
@router.post("/charges", status_code=201)
def create_charge_endpoint(data: ChargeCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        charge = create_charge(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _charge_view(charge)


@router.get("/charges")
def list_charges(
    property_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    charge_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    query = db.query(Charge)
    if property_id:
        query = query.filter(Charge.property_id == property_id)
    if lease_id:
        query = query.filter(Charge.lease_id == lease_id)
    if charge_type:
        query = query.filter(Charge.charge_type == charge_type)
    rows = query.order_by(Charge.period_start.desc(), Charge.id.desc()).all()
    return {"data": [_charge_view(r) for r in rows], "count": len(rows)}


@router.post("/charges/{charge_id}/allocate")
def allocate_charge(charge_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return allocate_charge_by_key(db, charge_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/allocation-rules", status_code=201)
def create_allocation_rule(data: ChargeAllocationRuleCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    from app.models.finance import ChargeAllocationRule
    if data.is_default:
        db.query(ChargeAllocationRule).filter(ChargeAllocationRule.property_id == data.property_id).update({"is_default": False})
    rule = ChargeAllocationRule(**data.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": rule.id, "name": rule.name, "key": rule.key.value, "is_default": rule.is_default}


@router.post("/charges/regularize", status_code=201)
def regularize_charges(lease_id: int = Query(...), year: int = Query(...), db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        regularization = calculate_charge_regularization(db, lease_id, year)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": regularization.id,
        "reference": regularization.reference,
        "lease_id": regularization.lease_id,
        "year": regularization.year,
        "provision_total": regularization.provision_total,
        "real_total": regularization.real_total,
        "difference": regularization.difference,
        "status": regularization.status,
    }


@router.post("/charges/budget")
def charge_budget(data: BudgetPrevisionnel, db: Session = Depends(get_db), current_user=Depends(require_read)):
    return build_budget_previsionnel(db, data.property_id, data.year)


# ---------------------------------------------------------------------------
# Comptabilité générale
# ---------------------------------------------------------------------------
@router.post("/accounts", status_code=201)
def create_account(data: dict, db: Session = Depends(get_db), current_user=Depends(require_write)):
    from app.models.finance import AccountingAccount
    account = AccountingAccount(**data)
    db.add(account)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Compte déjà existant ou invalide : {exc}")
    db.refresh(account)
    return {"id": account.id, "code": account.code, "label": account.label, "account_type": account.account_type}


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db), current_user=Depends(require_read)):
    from app.models.finance import AccountingAccount
    accounts = db.query(AccountingAccount).filter(AccountingAccount.is_active.is_(True)).order_by(AccountingAccount.code).all()
    return {"data": [{"id": a.id, "code": a.code, "label": a.label, "account_type": a.account_type, "is_system": a.is_system} for a in accounts], "count": len(accounts)}


@router.post("/accounts/standard")
def ensure_standard_accounts(db: Session = Depends(get_db), current_user=Depends(require_write)):
    from app.services.finance_service import _STANDARD_ACCOUNTS, _get_or_create_standard_account
    created = []
    for code in list(_STANDARD_ACCOUNTS.keys()):
        account = _get_or_create_standard_account(db, code)
        created.append({"code": account.code, "label": account.label})
    db.commit()
    return {"standard_accounts": created}


@router.post("/journal-entries", status_code=201)
def create_journal_entry_endpoint(data: JournalEntryCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        entry = create_journal_entry(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _journal_entry_view(entry)


@router.get("/journal-entries")
def list_entries(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    account_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    entries, total = list_journal_entries(db, start_date, end_date, account_id, page, limit)
    return {"data": [_journal_entry_view(e) for e in entries], "total": total, "page": page}


@router.post("/journal-entries/{entry_id}/validate")
def validate_entry(entry_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    entry = db.query(JournalEntry).filter(JournalEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Écriture non trouvée")
    entry.status = JournalEntryStatus.VALIDATED
    entry.validated_at = datetime.now()
    db.commit()
    db.refresh(entry)
    return _journal_entry_view(entry)


@router.get("/trial-balance")
def get_trial_balance(as_of: Optional[date] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    return trial_balance(db, as_of)


@router.get("/general-ledger/{account_id}")
def get_general_ledger(account_id: int, start_date: Optional[date] = None, end_date: Optional[date] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return general_ledger(db, account_id, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Facturation
# ---------------------------------------------------------------------------
@router.post("/invoices", status_code=201)
def create_invoice_endpoint(data: InvoiceCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    data.created_by = current_user.email
    try:
        invoice = create_invoice(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _invoice_view(invoice)


@router.get("/invoices")
def list_invoices(
    status: Optional[InvoiceStatus] = None,
    invoice_type: Optional[str] = None,
    recipient_type: Optional[str] = None,
    recipient_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    query = db.query(Invoice)
    if status:
        query = query.filter(Invoice.status == status)
    if invoice_type:
        query = query.filter(Invoice.invoice_type == invoice_type)
    if recipient_type:
        query = query.filter(Invoice.recipient_type == recipient_type)
    if recipient_id:
        query = query.filter(Invoice.recipient_id == recipient_id)
    rows = query.order_by(Invoice.invoice_date.desc()).all()
    return {"data": [_invoice_view(i) for i in rows], "count": len(rows)}


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture non trouvée")
    return _invoice_view(invoice)


@router.put("/invoices/{invoice_id}/status")
def update_invoice(invoice_id: int, data: InvoiceUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        invoice = update_invoice_status(db, invoice_id, data.status, data.due_date, data.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _invoice_view(invoice)


@router.post("/invoices/management-fee", status_code=201)
def generate_management_fee(
    owner_id: int = Query(...),
    period_start: date = Query(...),
    period_end: date = Query(...),
    rate_percent: float = Query(5.0, ge=0, le=100),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    try:
        invoice = generate_management_fee_invoice(db, owner_id, period_start, period_end, rate_percent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _invoice_view(invoice)


# ---------------------------------------------------------------------------
# Dépôts de garantie
# ---------------------------------------------------------------------------
@router.post("/deposits", status_code=201)
def create_deposit_endpoint(data: DepositCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        deposit = create_deposit(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _deposit_view(deposit)


@router.get("/deposits/{deposit_id}")
def get_deposit(deposit_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    deposit = db.query(DepositGuarantee).filter(DepositGuarantee.id == deposit_id).first()
    if not deposit:
        raise HTTPException(status_code=404, detail="Dépôt de garantie non trouvé")
    return _deposit_view(deposit)


@router.post("/deposits/{deposit_id}/deductions", status_code=201)
def add_deposit_deduction_endpoint(deposit_id: int, data: DepositDeductionCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        deduction = add_deposit_deduction(db, deposit_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": deduction.id, "label": deduction.label, "amount": deduction.amount}


@router.post("/deposits/{deposit_id}/restitution")
def compute_deposit_restitution(deposit_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return calculate_deposit_restitution(db, deposit_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/deposits/{deposit_id}/return")
def return_deposit_endpoint(deposit_id: int, data: DepositRestitution, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return return_deposit(db, deposit_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Exports comptables
# ---------------------------------------------------------------------------
@router.post("/exports")
def create_export(data: ExportInput, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return export_accounting(db, data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/exports")
def list_exports(db: Session = Depends(get_db), current_user=Depends(require_read)):
    from app.models.finance import AccountingExport
    exports = db.query(AccountingExport).order_by(AccountingExport.generated_at.desc()).limit(100).all()
    return {"data": [
        {
            "id": e.id,
            "reference": e.reference,
            "export_format": e.export_format.value,
            "period_start": e.period_start,
            "period_end": e.period_end,
            "entity_type": e.entity_type,
            "entry_count": e.entry_count,
            "total_debit": e.total_debit,
            "total_credit": e.total_credit,
            "generated_at": e.generated_at,
        }
        for e in exports
    ]}


# ---------------------------------------------------------------------------
# Helpers de sérialisation
# ---------------------------------------------------------------------------
def _bank_account_view(a: BankAccount) -> dict:
    return {
        "id": a.id,
        "reference": a.reference,
        "name": a.name,
        "bank_name": a.bank_name,
        "account_type": a.account_type.value,
        "iban": a.iban,
        "bic": a.bic,
        "currency": a.currency,
        "opening_balance": a.opening_balance,
        "current_balance": a.current_balance,
        "is_active": a.is_active,
    }


def _reconciliation_view(r) -> dict:
    return {
        "id": r.id,
        "bank_account_id": r.bank_account_id,
        "period_start": r.period_start,
        "period_end": r.period_end,
        "status": r.status.value,
        "opening_balance": r.opening_balance,
        "closing_balance": r.closing_balance,
        "auto_matched_count": r.auto_matched_count,
        "manual_matched_count": r.manual_matched_count,
        "unmatched_count": r.unmatched_count,
    }


def _payment_view(p: RentPayment) -> dict:
    return {
        "id": p.id,
        "reference": p.reference,
        "tenant_id": p.tenant_id,
        "lease_id": p.lease_id,
        "period": p.period,
        "due_date": p.due_date,
        "amount_due": p.amount_due,
        "amount_paid": p.amount_paid,
        "status": p.status.value,
        "paid_at": p.paid_at,
        "payment_method": p.payment_method,
        "receipt_id": p.receipt.id if p.receipt else None,
    }


def _late_payment_view(l: LatePayment) -> dict:
    return {
        "id": l.id,
        "reference": l.reference,
        "tenant_id": l.tenant_id,
        "lease_id": l.lease_id,
        "property_id": l.property_id,
        "period": l.period,
        "amount_due": l.amount_due,
        "amount_outstanding": l.amount_outstanding,
        "penalty_amount": l.penalty_amount,
        "due_date": l.due_date,
        "overdue_days": l.overdue_days,
        "stage": l.stage.value,
        "status": l.status,
        "plan_id": l.plan_id,
        "resolved_at": l.resolved_at,
    }


def _case_view(c: UnpaidCase) -> dict:
    return {
        "id": c.id,
        "reference": c.reference,
        "status": c.status,
        "outstanding_amount": c.outstanding_amount,
        "huissier_name": c.huissier_name,
        "court_reference": c.court_reference,
        "tribunal": c.tribunal,
        "next_action_date": c.next_action_date,
        "opened_at": c.opened_at,
        "closed_at": c.closed_at,
        "actions": [
            {"id": a.id, "action_type": a.action_type, "action_date": a.action_date, "description": a.description, "cost": a.cost}
            for a in c.actions
        ],
    }


def _payment_plan_view(plan: PaymentPlan) -> dict:
    return {
        "id": plan.id,
        "reference": plan.reference,
        "tenant_id": plan.tenant_id,
        "lease_id": plan.lease_id,
        "total_amount": plan.total_amount,
        "installments_count": plan.installments_count,
        "installments_amount": plan.installments_amount,
        "first_due_date": plan.first_due_date,
        "status": plan.status,
        "installments": [
            {"id": i.id, "position": i.position, "due_date": i.due_date, "amount": i.amount, "status": i.status, "paid_at": i.paid_at}
            for i in sorted(plan.installments, key=lambda x: x.position)
        ],
    }


def _charge_view(c: Charge) -> dict:
    return {
        "id": c.id,
        "reference": c.reference,
        "property_id": c.property_id,
        "lease_id": c.lease_id,
        "charge_type": c.charge_type,
        "category": c.category,
        "amount": c.amount,
        "vat_rate": c.vat_rate,
        "recoverability": c.recoverability.value,
        "period_start": c.period_start,
        "period_end": c.period_end,
        "allocation_key": c.allocation_key.value,
        "status": c.status,
        "is_coproperty": c.is_coproperty,
    }


def _journal_entry_view(e: JournalEntry) -> dict:
    return {
        "id": e.id,
        "code": e.code,
        "entry_date": e.entry_date,
        "label": e.label,
        "status": e.status.value,
        "created_at": e.created_at,
        "lines": [
            {
                "id": l.id,
                "account_id": l.account_id,
                "account_code": l.account.code if l.account else None,
                "debit": l.debit,
                "credit": l.credit,
                "label": l.label,
            }
            for l in e.lines
        ],
    }


def _invoice_view(i: Invoice) -> dict:
    return {
        "id": i.id,
        "reference": i.reference,
        "number": i.number,
        "invoice_type": i.invoice_type.value,
        "status": i.status.value,
        "invoice_date": i.invoice_date,
        "due_date": i.due_date,
        "issuer_type": i.issuer_type,
        "issuer_name": i.issuer_name,
        "recipient_type": i.recipient_type,
        "recipient_name": i.recipient_name,
        "property_id": i.property_id,
        "lease_id": i.lease_id,
        "amount_ht": i.amount_ht,
        "vat_rate": i.vat_rate,
        "vat_amount": i.vat_amount,
        "amount_ttc": i.amount_ttc,
        "tax_exempt": i.tax_exempt,
        "generated_from": i.generated_from,
        "lines": [
            {"id": l.id, "description": l.description, "quantity": l.quantity, "unit_price": l.unit_price, "amount_ht": l.amount_ht, "vat_rate": l.vat_rate}
            for l in i.lines
        ],
    }


def _deposit_view(d: DepositGuarantee) -> dict:
    return {
        "id": d.id,
        "reference": d.reference,
        "lease_id": d.lease_id,
        "tenant_id": d.tenant_id,
        "property_id": d.property_id,
        "amount": d.amount,
        "received_at": d.received_at,
        "payment_method": d.payment_method,
        "status": d.status.value,
        "start_date": d.start_date,
        "end_date": d.end_date,
        "restitution_legal_delay_months": d.restitution_legal_delay_months,
        "restitution_deadline": d.restitution_deadline,
        "amount_returned": d.amount_returned,
        "amount_withheld": d.amount_withheld,
        "interest_rate": d.interest_rate,
        "interest_amount": d.interest_amount,
        "deductions": [
            {"id": dd.id, "label": dd.label, "amount": dd.amount, "justification": dd.justification}
            for dd in d.deductions
        ],
    }


def _generate_case_reference() -> str:
    import uuid
    return f"CASE-{uuid.uuid4().hex[:10].upper()}"
