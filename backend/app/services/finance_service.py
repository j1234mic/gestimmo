"""Services métier du module 5 : gestion financière et comptabilité.

Le service centralise : la génération des appels de loyer, l'encaissement,
la détection et le recouvrement des impayés (workflow de relance), le calcul
des pénalités, les plans d'apurement, la gestion des charges, la comptabilité
générale (plan comptable, journal, grand livre, balance), le rapprochement
bancaire, la facturation, les dépôts de garantie et les exports comptables.
"""

import csv
import io
import uuid
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from typing import Dict, List, Optional

from sqlalchemy import func as sqlfunc
from sqlalchemy.orm import Session

from app.models.finance import (
    AccountingAccount,
    AccountingExport,
    BankAccount,
    BankReconciliation,
    BankStatement,
    BankStatementLine,
    Charge,
    ChargeAllocation,
    ChargeAllocationRule,
    ChargeAllocationKey,
    ChargeRegularization,
    ChargeRecoverability,
    DepositDeduction,
    DepositGuarantee,
    DepositStatus,
    ExportFormat,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    InvoiceType,
    JournalEntry,
    JournalEntryStatus,
    JournalLine,
    LatePayment,
    PaymentPlan,
    PaymentPlanInstallment,
    PaymentStage,
    ReconciliationMatch,
    ReconciliationStatus,
    ReminderAction,
    ReminderChannel,
    UnpaidCase,
    CaseAction,
)
from app.models.tenant import (
    Lease,
    LeaseStatus,
    PaymentStatus,
    RentPayment,
    RentReceipt,
    Tenant,
)
from app.models.owner import Owner
from app.models.property import Property

# Taux d'intérêt légal par défaut (paramétrable au niveau de l'appel).
DEFAULT_LEGAL_RATE = 5.0


def generate_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def parse_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


# ---------------------------------------------------------------------------
# Appels de loyer automatiques
# ---------------------------------------------------------------------------
def generate_rent_calls(db: Session, month: Optional[str] = None, as_of: Optional[date] = None) -> Dict:
    """Génère les appels de loyer mensuels pour tous les baux actifs.

    Idempotent : un appel existant pour (bail, période) n'est pas recréé.
    ``month`` au format ``YYYY-MM`` ; par défaut le mois courant (ou celui de
    ``as_of``).
    """
    reference_date = as_of or date.today()
    period = month or reference_date.strftime("%Y-%m")
    payment_day_source = reference_date

    leases = db.query(Lease).filter(
        Lease.status == LeaseStatus.ACTIVE,
        Lease.start_date <= payment_day_source,
    ).all()

    created = []
    skipped = []
    for lease in leases:
        result = generate_rent_call_for_lease(db, lease, period)
        if result:
            created.append(result)
        else:
            skipped.append(lease.id)

    db.commit()
    return {"period": period, "created": created, "skipped_leases": skipped, "count": len(created)}


def generate_rent_call_for_lease(db: Session, lease: Lease, period: str) -> Optional[int]:
    """Crée l'appel de loyer d'un bail pour une période donnée."""
    existing = db.query(RentPayment).filter(
        RentPayment.lease_id == lease.id,
        RentPayment.period == period,
    ).first()
    if existing:
        return None

    due_day = lease.payment_day if lease.payment_day else 5
    month, _ = int(period.split("-")[0]), int(period.split("-")[1])
    due_date = _period_due_date(period, due_day)

    amount = float(lease.monthly_rent or 0) + float(lease.monthly_charges or 0)
    payment = RentPayment(
        reference=generate_reference("APP"),
        tenant_id=lease.tenant_id,
        lease_id=lease.id,
        period=period,
        due_date=due_date,
        amount_due=amount,
        amount_paid=0,
        status=PaymentStatus.DUE,
        notes="Appel de loyer généré automatiquement",
    )
    db.add(payment)
    db.flush()
    return payment.id


def _period_due_date(period: str, day: int) -> date:
    year, month = int(period[:4]), int(period[5:7])
    last_day = 28
    if month == 12:
        last_day = 31
    elif month in (1, 3, 5, 7, 8, 10):
        last_day = 31
    elif month in (4, 6, 9, 11):
        last_day = 30
    return date(year, month, min(day, last_day))


# ---------------------------------------------------------------------------
# Encaissement multi-canal
# ---------------------------------------------------------------------------
def record_rent_payment(
    db: Session,
    payment_id: int,
    amount: float,
    method: str,
    paid_at: Optional[date] = None,
    external_reference: Optional[str] = None,
    notes: Optional[str] = None,
) -> RentPayment:
    """Enregistre un encaissement (CB, prélèvement, virement, chèque, espèces)."""
    payment = db.query(RentPayment).filter(RentPayment.id == payment_id).first()
    if not payment:
        raise ValueError("Paiement non trouvé")

    closing = round(float(payment.amount_due) - float(payment.amount_paid or 0), 2)
    if amount <= 0:
        raise ValueError("Le montant encaissé doit être positif")
    applied = min(round(amount, 2), closing)
    payment.amount_paid = round(float(payment.amount_paid or 0) + applied, 2)
    payment.payment_method = method
    payment.external_reference = external_reference or payment.external_reference
    if notes:
        payment.notes = notes

    now = _now()
    when = datetime.combine(paid_at, datetime.min.time(), tzinfo=timezone.utc) if paid_at else now
    payment.paid_at = when
    if payment.amount_paid >= payment.amount_due:
        payment.status = PaymentStatus.PAID
    elif payment.amount_paid > 0:
        payment.status = PaymentStatus.PARTIAL if payment.due_date >= date.today() else PaymentStatus.OVERDUE
    else:
        payment.status = PaymentStatus.DUE if payment.due_date >= date.today() else PaymentStatus.OVERDUE

    _ensure_receipt(db, payment)
    _post_rent_journal_entry(db, payment, applied, method)
    _resolve_matching_late_payment(db, payment)
    db.commit()
    db.refresh(payment)
    return payment


def _ensure_receipt(db: Session, payment: RentPayment) -> None:
    if payment.receipt:
        return
    receipt = RentReceipt(
        reference=generate_reference("QUIT"),
        payment_id=payment.id,
        tenant_id=payment.tenant_id,
        lease_id=payment.lease_id,
        period=payment.period,
    )
    db.add(receipt)
    db.flush()


# ---------------------------------------------------------------------------
# Détection des impayés et workflow de relance
# ---------------------------------------------------------------------------
def detect_late_payments(db: Session, as_of: Optional[date] = None) -> Dict:
    """Détecte les appels de loyer non soldés après leur date d'échéance."""
    reference_date = as_of or date.today()
    payments = db.query(RentPayment).filter(
        RentPayment.status.in_([PaymentStatus.DUE, PaymentStatus.PARTIAL, PaymentStatus.OVERDUE]),
        RentPayment.due_date < reference_date,
    ).all()

    detected = []
    for payment in payments:
        outstanding = round(float(payment.amount_due) - float(payment.amount_paid or 0), 2)
        if outstanding <= 0:
            continue
        existing = db.query(LatePayment).filter(
            LatePayment.rent_payment_id == payment.id,
            LatePayment.status != "resolved",
        ).first()
        if existing:
            existing.amount_outstanding = outstanding
            existing.overdue_days = (reference_date - payment.due_date).days
            _update_stage(db, existing)
            continue
        late = LatePayment(
            reference=generate_reference("IMP"),
            tenant_id=payment.tenant_id,
            lease_id=payment.lease_id,
            property_id=payment.lease.property_id,
            rent_payment_id=payment.id,
            period=payment.period,
            amount_due=payment.amount_due,
            amount_outstanding=outstanding,
            due_date=payment.due_date,
            overdue_days=(reference_date - payment.due_date).days,
            stage=PaymentStage.DETECTED,
            status="open",
        )
        db.add(late)
        db.flush()
        _update_stage(db, late)
        detected.append(late.id)

    db.commit()
    return {"as_of": reference_date, "detected": detected, "count": len(detected)}


def _update_stage(db: Session, late: LatePayment) -> None:
    stage = stage_due_to_overdue_days(late.overdue_days)
    if stage != late.stage:
        late.stage = stage
        late.stage_reached_at = _now()


def stage_due_to_overdue_days(days: int) -> PaymentStage:
    if days >= 90:
        return PaymentStage.CONTENTIEUX
    if days >= 60:
        return PaymentStage.COMMANDEMENT
    if days >= 30:
        return PaymentStage.DEMANDE
    if days >= 15:
        return PaymentStage.FIRM
    if days >= 5:
        return PaymentStage.AMIABLE
    return PaymentStage.DETECTED


def advance_reminder_workflow(db: Session, late_payment_id: int) -> Dict:
    """Avance le workflow de relance selon le nombre de jours de retard.

    J+5 relance amiable (email), J+15 relance ferme (email + SMS),
    J+30 mise en demeure (courrier AR), J+60 commandement de payer,
    J+90 procédure contentieuse.
    """
    late = db.query(LatePayment).filter(LatePayment.id == late_payment_id).first()
    if not late:
        raise ValueError("Impayé non trouvé")

    stage = late.stage
    actions = []
    if stage == PaymentStage.AMIABLE:
        actions.append(_trigger_reminder(db, late, PaymentStage.AMIABLE, ReminderChannel.EMAIL))
    elif stage == PaymentStage.FIRM:
        actions.append(_trigger_reminder(db, late, PaymentStage.FIRM, ReminderChannel.EMAIL))
        actions.append(_trigger_reminder(db, late, PaymentStage.FIRM, ReminderChannel.SMS))
    elif stage == PaymentStage.DEMANDE:
        actions.append(_trigger_reminder(db, late, PaymentStage.DEMANDE, ReminderChannel.AR_LETTER))
    elif stage == PaymentStage.COMMANDEMENT:
        actions.append(_trigger_reminder(db, late, PaymentStage.COMMANDEMENT, ReminderChannel.HUISSIER))
    elif stage == PaymentStage.CONTENTIEUX:
        actions.append(_trigger_reminder(db, late, PaymentStage.CONTENTIEUX, ReminderChannel.TRIBUNAL))
        if not late.case:
            _open_case(db, late)
    else:
        # Retard détecté mais pas encore de relance : message d'information.
        return {"late_payment_id": late.id, "stage": stage.value, "actions": []}

    db.commit()
    return {
        "late_payment_id": late.id,
        "stage": stage.value,
        "overdue_days": late.overdue_days,
        "actions": actions,
    }


def _trigger_reminder(db, late, stage, channel, subject=None, body=None) -> Dict:
    reminder = ReminderAction(
        late_payment_id=late.id,
        stage=stage,
        channel=channel,
        template=f"relance_{stage.value}_{channel.value}",
        subject=subject or f"Relance de votre loyer {late.period}",
        body=body,
        status="sent",
        sent_at=_now(),
    )
    db.add(reminder)
    db.flush()
    return {
        "id": reminder.id,
        "stage": stage.value,
        "channel": channel.value,
        "sent_at": reminder.sent_at,
    }


def _open_case(db, late) -> UnpaidCase:
    case = UnpaidCase(
        reference=generate_reference("CASE"),
        late_payment_id=late.id,
        outstanding_amount=late.amount_outstanding,
        opened_at=date.today(),
        description=f"Procédure contentieuse pour la période {late.period}",
    )
    db.add(case)
    db.flush()
    late.status = "in_progress"
    return case


def calculate_penalty(principal: float, days: int, annual_rate_percent: float = DEFAULT_LEGAL_RATE) -> float:
    """Calcule les pénalités de retard (intérêts légaux) sur un impayé."""
    if principal <= 0 or days <= 0:
        return 0.0
    rate = Decimal(str(annual_rate_percent)) / Decimal(100)
    penalty = Decimal(str(principal)) * rate * Decimal(str(days)) / Decimal(365)
    return float(penalty.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _resolve_matching_late_payment(db: Session, payment: RentPayment) -> None:
    late = db.query(LatePayment).filter(
        LatePayment.rent_payment_id == payment.id,
        LatePayment.status != "resolved",
    ).first()
    if not late:
        return
    outstanding = round(float(payment.amount_due) - float(payment.amount_paid or 0), 2)
    late.amount_outstanding = max(outstanding, 0)
    if outstanding <= 0:
        late.status = "resolved"
        late.stage = PaymentStage.RESOLVED
        late.resolved_at = _now()
        if late.case and late.case.status not in ("closed", "won", "lost"):
            late.case.status = "closed"
            late.case.closed_at = date.today()


# ---------------------------------------------------------------------------
# Plans d'apurement (échelonnement)
# ---------------------------------------------------------------------------
def create_payment_plan(db: Session, data) -> PaymentPlan:
    plan = PaymentPlan(
        reference=generate_reference("PLAN"),
        tenant_id=data.tenant_id,
        lease_id=data.lease_id,
        total_amount=data.total_amount,
        installments_count=data.installments_count,
        installments_amount=round(data.total_amount / data.installments_count, 2),
        first_due_date=data.first_due_date,
        agreed_at=data.agreed_at,
        notes=data.notes,
        status="active",
    )
    db.add(plan)
    db.flush()
    due = data.first_due_date
    for position in range(1, data.installments_count + 1):
        db.add(PaymentPlanInstallment(
            plan_id=plan.id,
            position=position,
            due_date=due,
            amount=plan.installments_amount if position < data.installments_count
            else round(data.total_amount - plan.installments_amount * (data.installments_count - 1), 2),
            status="pending",
        ))
        due = _add_months(due, 1)
    db.commit()
    db.refresh(plan)
    return plan


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    last_day = 28
    if month == 12:
        last_day = 31
    elif month in (1, 3, 5, 7, 8, 10):
        last_day = 31
    elif month in (4, 6, 9, 11):
        last_day = 30
    return date(year, month, min(value.day, last_day))


def record_installment_payment(db: Session, installment_id: int, paid_at: Optional[datetime] = None) -> Dict:
    installment = db.query(PaymentPlanInstallment).filter(PaymentPlanInstallment.id == installment_id).first()
    if not installment:
        raise ValueError("Échéance non trouvée")
    installment.paid_at = paid_at or _now()
    installment.status = "paid"
    plan = installment.plan
    if all(i.status == "paid" for i in plan.installments):
        plan.status = "completed"
        plan.completed_at = _now()
    else:
        plan.status = "in_progress"
    db.commit()
    return {"installment_id": installment.id, "plan_id": plan.id, "plan_status": plan.status}


# ---------------------------------------------------------------------------
# Charges, répartition et régularisation
# ---------------------------------------------------------------------------
def create_charge(db: Session, data) -> Charge:
    charge = Charge(
        reference=generate_reference("CHG"),
        property_id=data.property_id,
        lease_id=data.lease_id,
        charge_type=data.charge_type,
        category=data.category,
        amount=data.amount,
        vat_rate=data.vat_rate,
        recoverability=data.recoverability,
        period_start=data.period_start,
        period_end=data.period_end,
        allocation_key=data.allocation_key,
        provider_name=data.provider_name,
        invoice_reference=data.invoice_reference,
        is_coproperty=data.is_coproperty,
        notes=data.notes,
        status="pending",
    )
    db.add(charge)
    db.flush()
    if data.lease_id:
        share = _compute_share(db, charge)
        db.add(ChargeAllocation(
            charge_id=charge.id,
            lease_id=charge.lease_id,
            tenant_id=charge.lease.tenant_id,
            share=share,
            share_label=f"{data.allocation_key.value} = {share}",
            amount=round(charge.amount * share, 2),
        ))
        charge.status = "allocated"
    db.commit()
    db.refresh(charge)
    return charge


def _compute_share(db: Session, charge: Charge) -> float:
    """Détermine la part d'une charge pour un bail donné (par défaut 1.0)."""
    # Avec une seule unité (loyers/habitation), la charge se rapporte à ce bail.
    rule = db.query(ChargeAllocationRule).filter(
        ChargeAllocationRule.property_id == charge.property_id,
        ChargeAllocationRule.is_default.is_(True),
    ).first()
    if charge.allocation_key == ChargeAllocationKey.OCCUPANTS:
        return float(charge.lease.tenant.occupants_count if hasattr(charge.lease.tenant, "occupants_count") else 1) or 1.0
    return 1.0


def allocate_charge_by_key(db: Session, charge_id: int) -> Dict:
    """Répartit une charge selon la clé (tantièmes, surface, occupants, custom)."""
    charge = db.query(Charge).filter(Charge.id == charge_id).first()
    if not charge:
        raise ValueError("Charge non trouvée")

    leases = db.query(Lease).filter(Lease.property_id == charge.property_id, Lease.status == LeaseStatus.ACTIVE).all()
    if not leases:
        return {"charge_id": charge.id, "allocations": []}

    weights = []
    for lease in leases:
        if charge.allocation_key == ChargeAllocationKey.SURFACE:
            weight = float(getattr(lease.property, "living_area", 0) or 1)
        elif charge.allocation_key == ChargeAllocationKey.OCCUPANTS:
            weight = float(getattr(lease.tenant, "occupants_count", 1) or 1)
        elif charge.allocation_key == ChargeAllocationKey.CUSTOM:
            weight = float(charge.custom_weight if hasattr(charge, "custom_weight") else 1)
        else:  # TANTIEMES par défaut : part par bail (1 unité chacun)
            weight = 1.0
        weights.append((lease, weight))

    total_weight = sum(w for _, w in weights) or 1.0
    db.query(ChargeAllocation).filter(ChargeAllocation.charge_id == charge.id).delete()
    allocations = []
    for lease, weight in weights:
        share = round(weight / total_weight, 6)
        amount = round(charge.amount * share, 2)
        allocation = ChargeAllocation(
            charge_id=charge.id,
            lease_id=lease.id,
            tenant_id=lease.tenant_id,
            share=share,
            share_label=f"{charge.allocation_key.value} {share}",
            amount=amount,
        )
        db.add(allocation)
        allocations.append({"lease_id": lease.id, "share": share, "amount": amount})
    charge.status = "allocated"
    db.commit()
    return {"charge_id": charge.id, "allocation_key": charge.allocation_key.value, "allocations": allocations}


def calculate_charge_regularization(db: Session, lease_id: int, year: int) -> ChargeRegularization:
    """Calcule la régularisation annuelle des charges (provision vs réel).

    La provision = part de charges incluse dans les loyers versés sur
    l'exercice ; le réel = charges réellement récupérables imputées au bail.
    """
    lease = db.query(Lease).filter(Lease.id == lease_id).first()
    if not lease:
        raise ValueError("Bail non trouvé")

    period_start = date(year, 1, 1)
    period_end = date(year, 12, 31)
    monthly_charges = float(lease.monthly_charges or 0)

    # Provision de charges = part « charges » incluse dans les appels réglés.
    provision_total = 0.0
    payments_count = 0
    for payment in db.query(RentPayment).filter(
        RentPayment.lease_id == lease.id,
        RentPayment.period.like(f"{year}-%"),
    ).all():
        paid = min(float(payment.amount_due), float(payment.amount_paid or 0))
        if paid > 0:
            provision_total += min(paid, monthly_charges) if monthly_charges else 0
            payments_count += 1

    real_total = round(sum(float(c.amount) for c in db.query(Charge).filter(
        Charge.lease_id == lease.id,
        Charge.period_start >= period_start,
        Charge.period_start <= period_end,
    ).all() if c.recoverability.value == "recoverable"), 2)

    difference = round(real_total - provision_total, 2)
    regularization = ChargeRegularization(
        reference=generate_reference("REG"),
        lease_id=lease.id,
        property_id=lease.property_id,
        tenant_id=lease.tenant_id,
        year=year,
        provision_total=round(provision_total, 2),
        real_total=real_total,
        difference=difference,
        status="calculated",
        detail={"monthly_charges": monthly_charges, "payments_count": payments_count},
    )
    db.add(regularization)
    db.commit()
    db.refresh(regularization)
    return regularization


def build_budget_previsionnel(db: Session, property_id: int, year: int) -> Dict:
    """Budget prévisionnel des charges pour un bien et une année."""
    period_start = date(year, 1, 1)
    period_end = date(year, 12, 31)
    charges = db.query(Charge).filter(
        Charge.property_id == property_id,
        Charge.period_start >= period_start,
        Charge.period_start <= period_end,
    ).all()
    budget = sum(float(c.amount) for c in charges)
    by_type = {}
    for c in charges:
        by_type[c.charge_type] = by_type.get(c.charge_type, 0) + float(c.amount)
    return {
        "property_id": property_id,
        "year": year,
        "budget": round(budget, 2),
        "actual": round(budget, 2),
        "by_type": by_type,
    }


# ---------------------------------------------------------------------------
# Comptabilité générale
# ---------------------------------------------------------------------------
class _JournalContext:
    """Ouverture d'une écriture avec contrôle d'équilibre au commit."""

    def __init__(self, db, entry_date, label, reference=None, source_type=None, source_id=None, property_id=None, created_by=None):
        self.db = db
        self.entry = JournalEntry(
            code=generate_reference("ECR"),
            entry_date=entry_date,
            label=label,
            reference=reference,
            source_type=source_type,
            source_id=source_id,
            property_id=property_id,
            created_by=created_by,
            status=JournalEntryStatus.DRAFT,
        )
        self.db.add(self.entry)
        self.db.flush()
        self._lines = []

    def debit(self, account_code: str, amount: float, tenant_id=None, label=None):
        self._lines.append((account_code, "debit", amount, tenant_id, label))
        return self

    def credit(self, account_code: str, amount: float, tenant_id=None, label=None):
        self._lines.append((account_code, "credit", amount, tenant_id, label))
        return self

    def commit(self):
        total_debit = round(sum(a for _, side, a, *_ in self._lines if side == "debit"), 2)
        total_credit = round(sum(a for _, side, a, *_ in self._lines if side == "credit"), 2)
        if total_debit != total_credit:
            self.db.rollback()
            raise ValueError(f"Écriture déséquilibrée : débit {total_debit} vs crédit {total_credit}")
        for code, side, amount, tenant_id, label in self._lines:
            account = _get_or_create_standard_account(self.db, code)
            if side == "debit":
                line = JournalLine(entry_id=self.entry.id, account_id=account.id, debit=amount, credit=0, label=label, tenant_id=tenant_id)
            else:
                line = JournalLine(entry_id=self.entry.id, account_id=account.id, debit=0, credit=amount, label=label, tenant_id=tenant_id)
            self.db.add(line)
        self.db.flush()
        return self.entry


def _get_or_create_standard_account(db: Session, code: str) -> AccountingAccount:
    account = db.query(AccountingAccount).filter(AccountingAccount.code == code).first()
    if account:
        return account
    bundle = _STANDARD_ACCOUNTS.get(code, {})
    account = AccountingAccount(
        code=code,
        label=bundle.get("label", code),
        account_type=bundle.get("type", "other"),
        is_system=True,
    )
    db.add(account)
    db.flush()
    return account


_STANDARD_ACCOUNTS = {
    "512": {"label": "Banque", "type": "asset"},
    "411": {"label": "Clients locataires", "type": "asset"},
    "70": {"label": "Produits (loyers & revenus)", "type": "income"},
    "708": {"label": "Produits accessoires", "type": "income"},
    "706": {"label": "Honoraires de gestion", "type": "income"},
    "645": {"label": "Charges de personnel", "type": "expense"},
    "606": {"label": "Fournitures", "type": "expense"},
    "401": {"label": "Fournisseurs", "type": "liability"},
    "801": {"label": "Obligations locataires (impayés)", "type": "asset"},
    "4011": {"label": "Fournisseurs prestataires", "type": "liability"},
    "420": {"label": "Dépôts de garantie reçus", "type": "liability"},
    "467": {"label": "Comptes de gérance propriétaires", "type": "liability"},
    "4671": {"label": "Remboursements propriétaires", "type": "liability"},
}


def create_journal_entry(db: Session, data) -> JournalEntry:
    account_cache = {}
    lines_debit = 0.0
    lines_credit = 0.0
    entry = JournalEntry(
        code=generate_reference("ECR"),
        entry_date=data.entry_date,
        label=data.label,
        description=data.description,
        reference=data.reference,
        source_type=data.source_type,
        source_id=data.source_id,
        property_id=data.property_id,
        created_by=data.created_by if hasattr(data, "created_by") else None,
        status=JournalEntryStatus.DRAFT,
    )
    db.add(entry)
    db.flush()
    for line in data.lines:
        if round(line.debit, 2) + round(line.credit, 2) != round(line.debit + line.credit, 2):
            raise ValueError("Une ligne ne peut avoir que débit OU crédit")
        account = db.query(AccountingAccount).filter(AccountingAccount.id == line.account_id).first()
        if not account:
            raise ValueError("Compte comptable non trouvé")
        db.add(JournalLine(
            entry_id=entry.id,
            account_id=account.id,
            debit=line.debit,
            credit=line.credit,
            label=line.label,
            tenant_id=line.tenant_id,
        ))
        lines_debit += line.debit
        lines_credit += line.credit
    if round(lines_debit, 2) != round(lines_credit, 2):
        db.rollback()
        raise ValueError(f"Écriture déséquilibrée : débit {lines_debit} vs crédit {lines_credit}")
    db.commit()
    db.refresh(entry)
    return entry


def _post_rent_journal_entry(db: Session, payment: RentPayment, amount: float, method: str) -> None:
    """Écriture automatique d'un encaissement de loyer."""
    if amount <= 0:
        return
    ctx = _JournalContext(
        db,
        payment.paid_at.date() if payment.paid_at else date.today(),
        f"Encaissement loyer {payment.period}",
        reference=payment.reference,
        source_type="rent_payment",
        source_id=payment.id,
        property_id=payment.lease.property_id,
    )
    acc = "512" if method in ("card", "direct_debit", "bank_transfer", "online_stripe", "virement") else "411"
    ctx.debit(acc, amount, tenant_id=payment.tenant_id)
    ctx.credit("70", amount, tenant_id=payment.tenant_id)
    ctx.commit()


def calculate_rent_due_parts(amount: float, monthly_rent: float, monthly_charges: float) -> Dict:
    """Décompose un loyer versé en loyer HC et part de charges."""
    charges_part = min(monthly_charges, amount)
    rent_part = max(0, amount - charges_part)
    return {"rent": round(rent_part, 2), "charges": round(charges_part, 2)}


def list_journal_entries(db: Session, start_date=None, end_date=None, account_id=None, page=1, limit=100):
    query = db.query(JournalEntry)
    if start_date:
        query = query.filter(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.filter(JournalEntry.entry_date <= end_date)
    if account_id:
        query = query.join(JournalLine).filter(JournalLine.account_id == account_id)
    total = query.count()
    entries = query.order_by(JournalEntry.entry_date.desc()).offset((page - 1) * limit).limit(limit).all()
    return entries, total


def trial_balance(db: Session, as_of: Optional[date] = None) -> Dict:
    """Balance générale (débit/crédit/solde par compte)."""
    query = db.query(
        AccountingAccount,
        sqlfunc.coalesce(sqlfunc.sum(JournalLine.debit), 0).label("debit"),
        sqlfunc.coalesce(sqlfunc.sum(JournalLine.credit), 0).label("credit"),
    ).join(JournalLine, JournalLine.account_id == AccountingAccount.id)
    if as_of:
        query = query.filter(JournalEntry.entry_date <= as_of).join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
    rows = query.group_by(AccountingAccount.id).all()

    accounts = []
    for account, debit, credit in rows:
        accounts.append({
            "code": account.code,
            "label": account.label,
            "account_type": account.account_type,
            "debit": float(debit),
            "credit": float(credit),
            "balance": float(debit) - float(credit),
        })
    return {"as_of": as_of, "accounts": accounts}


def general_ledger(db: Session, account_id: int, start_date=None, end_date=None) -> Dict:
    """Grand livre d'un compte comptable."""
    account = db.query(AccountingAccount).filter(AccountingAccount.id == account_id).first()
    if not account:
        raise ValueError("Compte non trouvé")
    query = db.query(JournalLine).filter(JournalLine.account_id == account_id)
    if start_date:
        query = query.join(JournalEntry).filter(JournalEntry.entry_date >= start_date)
    if end_date:
        query = query.join(JournalEntry).filter(JournalEntry.entry_date <= end_date)
    lines = query.order_by(JournalEntry.entry_date).all()
    balance = 0.0
    ledger = []
    for line in lines:
        balance += line.debit - line.credit
        ledger.append({
            "entry_id": line.entry_id,
            "entry_date": line.entry.entry_date,
            "label": line.entry.label,
            "reference": line.entry.reference,
            "debit": line.debit,
            "credit": line.credit,
            "balance": round(balance, 2),
        })
    return {
        "account": {"id": account.id, "code": account.code, "label": account.label},
        "lines": ledger,
        "closing_balance": round(balance, 2),
    }


# ---------------------------------------------------------------------------
# Rapprochement bancaire
# ---------------------------------------------------------------------------
def create_bank_account(db: Session, data) -> BankAccount:
    account = BankAccount(reference=generate_reference("BAN"), current_balance=data.opening_balance, **data.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def import_bank_statement(db: Session, bank_account_id: int, data) -> BankStatement:
    account = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
    if not account:
        raise ValueError("Compte bancaire non trouvé")
    statement = BankStatement(
        bank_account_id=account.id,
        reference=generate_reference("RELE"),
        import_source="manual",
        period_start=data.period_start,
        period_end=data.period_end,
        currency=data.currency,
        raw_filename=data.raw_filename,
        line_count=len(data.lines),
        total_debit=round(sum(-l.amount for l in data.lines if l.amount < 0), 2),
        total_credit=round(sum(l.amount for l in data.lines if l.amount > 0), 2),
    )
    db.add(statement)
    db.flush()
    for line in data.lines:
        db.add(BankStatementLine(
            statement_id=statement.id,
            transaction_date=line.transaction_date,
            amount=line.amount,
            label=line.label,
            counterparty=line.counterparty,
            reference=line.reference,
            internal_reference=line.internal_reference,
        ))
    db.commit()
    db.refresh(statement)
    return statement


def create_reconciliation(db: Session, data) -> BankReconciliation:
    reconciliation = BankReconciliation(
        reference=None,
        bank_account_id=data.bank_account_id,
        period_start=data.period_start,
        period_end=data.period_end,
        opening_balance=data.opening_balance,
        closing_balance=data.closing_balance,
        status=ReconciliationStatus.DRAFT,
    )
    db.add(reconciliation)
    db.commit()
    db.refresh(reconciliation)
    return reconciliation


def auto_match_reconciliation(db: Session, reconciliation_id: int) -> Dict:
    """Rapprochement automatique des lignes bancaires avec les écritures connues."""
    reconciliation = db.query(BankReconciliation).filter(BankReconciliation.id == reconciliation_id).first()
    if not reconciliation:
        raise ValueError("Rapprochement non trouvé")

    lines = db.query(BankStatementLine).join(BankStatement).filter(
        BankStatement.bank_account_id == reconciliation.bank_account_id,
        BankStatementLine.is_reconciled.is_(False),
        BankStatementLine.transaction_date >= reconciliation.period_start,
        BankStatementLine.transaction_date <= reconciliation.period_end,
    ).all()

    auto_matched = 0
    manual_matched = 0
    for line in lines:
        target = _match_single_line(db, line)
        if target:
            matched_type, matched_id, amount, confidence = target
            db.add(ReconciliationMatch(
                reconciliation_id=reconciliation.id,
                line_id=line.id,
                matched_type=matched_type,
                matched_id=matched_id,
                amount=amount,
                confidence=confidence,
            ))
            line.matched_type = "auto" if confidence >= 0.8 else "manual"
            line.matched_transaction_id = matched_id
            line.is_reconciled = True
            if confidence >= 0.8:
                auto_matched += 1
            else:
                manual_matched += 1

    reconciliation.auto_matched_count = auto_matched
    reconciliation.manual_matched_count = manual_matched
    reconciliation.unmatched_count = db.query(BankStatementLine).join(BankStatement).filter(
        BankStatement.bank_account_id == reconciliation.bank_account_id,
        BankStatementLine.is_reconciled.is_(False),
    ).count()
    reconciliation.status = ReconciliationStatus.IN_PROGRESS
    db.commit()
    return {
        "reconciliation_id": reconciliation.id,
        "auto_matched": auto_matched,
        "manual_matched": manual_matched,
        "unmatched": reconciliation.unmatched_count,
    }


def _match_single_line(db: Session, line: BankStatementLine):
    """Cherche une contrepartie au montant absolu d'une ligne bancaire.

    Retourne (matched_type, matched_id, amount, confidence) ou None.
    """
    amount = abs(line.amount)
    # 1. Correspondance sur un appel de loyer non encore soldé.
    payments = db.query(RentPayment).filter(
        RentPayment.amount_due == amount,
    ).all()
    payments = [p for p in payments if abs(float(p.amount_due) - float(p.amount_paid or 0)) < 0.01]
    if payments:
        payment = payments[0]
        return ("rent_payment", payment.id, float(payment.amount_due), 0.9)

    # 2. Correspondance sur une transaction propriétaire (même signe / montant).
    from app.models.accounting import OwnerTransaction
    transactions = db.query(OwnerTransaction).filter(
        OwnerTransaction.amount == line.amount,
    ).all()
    if transactions:
        tx = transactions[0]
        return ("owner_transaction", tx.id, float(tx.amount), 0.85)

    # 3. Correspondance sur une facture.
    invoices = db.query(Invoice).filter(Invoice.amount_ttc == amount).all()
    if invoices:
        inv = invoices[0]
        return ("invoice", inv.id, float(inv.amount_ttc), 0.85)

    return None


def record_manual_match(db: Session, reconciliation_id: int, data) -> Dict:
    reconciliation = db.query(BankReconciliation).filter(BankReconciliation.id == reconciliation_id).first()
    if not reconciliation:
        raise ValueError("Rapprochement non trouvé")
    line = db.query(BankStatementLine).filter(BankStatementLine.id == data.line_id).first()
    if not line:
        raise ValueError("Ligne bancaire non trouvée")
    db.add(ReconciliationMatch(
        reconciliation_id=reconciliation.id,
        line_id=line.id,
        matched_type=data.matched_type,
        matched_id=data.matched_id,
        amount=data.amount,
        confidence=1.0,
    ))
    line.matched_type = "manual"
    line.matched_transaction_id = data.matched_id
    line.is_reconciled = True
    reconciliation.manual_matched_count += 1
    db.commit()
    return {"message": "Rapprochement manuel enregistré", "line_id": line.id}


def reconcile_account(db: Session, bank_account_id: int, period_start: date, period_end: date) -> Dict:
    """Clôture un rapprochement : recalcul du solde du compte bancaire."""
    account = db.query(BankAccount).filter(BankAccount.id == bank_account_id).first()
    if not account:
        raise ValueError("Compte bancaire non trouvé")
    statement = db.query(BankStatement).filter(
        BankStatement.bank_account_id == account.id,
        BankStatement.period_start == period_start,
        BankStatement.period_end == period_end,
    ).first()
    if not statement:
        raise ValueError("Aucun relevé pour cette période")
    matched_total = db.query(sqlfunc.coalesce(sqlfunc.sum(ReconciliationMatch.amount), 0)).join(
        ReconciliationMatch, ReconciliationMatch.line_id == BankStatementLine.id
    ).filter(BankStatementLine.statement_id == statement.id).scalar() or 0
    account.current_balance = round(account.opening_balance + float(matched_total), 2)
    db.commit()
    return {"bank_account_id": account.id, "current_balance": account.current_balance}


# ---------------------------------------------------------------------------
# Facturation
# ---------------------------------------------------------------------------
def next_invoice_number(db: Session, invoice_type: InvoiceType) -> str:
    prefix = {"honoraire": "FAC", "prestation": "FPR", "devis": "DEV", "avoir": "AVR", "other": "FCT"}.get(invoice_type.value, "FCT")
    year = date.today().year
    pattern = f"{prefix}-{year}-%"
    count = db.query(Invoice).filter(Invoice.number.like(pattern)).count()
    return f"{prefix}-{year}-{count + 1:05d}"


def create_invoice(db: Session, data) -> Invoice:
    number = next_invoice_number(db, data.invoice_type)
    amount_ht = 0.0
    for line in data.lines:
        amount_ht += round(line.quantity * line.unit_price, 2)
    vat_rate = data.lines[0].vat_rate if data.lines else 0
    vat_amount = round(amount_ht * vat_rate / 100, 2)
    amount_ttc = round(amount_ht + vat_amount, 2)

    invoice = Invoice(
        reference=generate_reference("INV"),
        number=number,
        invoice_type=data.invoice_type,
        status=data.status,
        invoice_date=data.invoice_date,
        due_date=data.due_date,
        issuer_type=data.issuer_type,
        issuer_id=data.issuer_id,
        issuer_name=data.issuer_name,
        recipient_type=data.recipient_type,
        recipient_id=data.recipient_id,
        recipient_name=data.recipient_name,
        property_id=data.property_id,
        lease_id=data.lease_id,
        amount_ht=amount_ht,
        vat_rate=vat_rate,
        vat_amount=vat_amount,
        amount_ttc=amount_ttc,
        tax_exempt=data.tax_exempt,
        notes=data.notes,
        generated_from=data.generated_from,
        created_by=data.created_by if hasattr(data, "created_by") else None,
    )
    db.add(invoice)
    db.flush()
    for position, line in enumerate(data.lines, 1):
        db.add(InvoiceLine(
            invoice_id=invoice.id,
            position=position,
            description=line.description,
            quantity=line.quantity,
            unit_price=line.unit_price,
            amount_ht=round(line.quantity * line.unit_price, 2),
            vat_rate=line.vat_rate,
            account_code=line.account_code,
        ))
    db.commit()
    db.refresh(invoice)
    return invoice


def generate_management_fee_invoice(db: Session, owner_id: int, period_start: date, period_end: date, rate_percent: float = 5.0) -> Invoice:
    """Facture d'honoraires de gestion pour un propriétaire et une période."""
    from app.models.accounting import OwnerTransaction, TransactionType
    transactions = db.query(OwnerTransaction).filter(
        OwnerTransaction.owner_id == owner_id,
        OwnerTransaction.status == "completed",
        OwnerTransaction.transaction_date >= period_start,
        OwnerTransaction.transaction_date <= period_end,
        OwnerTransaction.amount > 0,
        OwnerTransaction.transaction_type == TransactionType.RENTAL_INCOME,
    ).all()
    total_income = sum(float(t.amount) for t in transactions)
    fees = round(total_income * rate_percent / 100, 2)
    owner = db.query(Owner).filter(Owner.id == owner_id).first()
    if not owner:
        raise ValueError("Propriétaire non trouvé")

    invoice = Invoice(
        reference=generate_reference("HON"),
        number=next_invoice_number(db, InvoiceType.HONORAIRE),
        invoice_type=InvoiceType.HONORAIRE,
        status=InvoiceStatus.DRAFT,
        invoice_date=period_end,
        issuer_type="company",
        issuer_name="GestImmo",
        recipient_type="owner",
        recipient_id=owner_id,
        recipient_name=owner.company_name or f"{owner.first_name or ''} {owner.last_name or ''}".strip(),
        amount_ht=fees,
        vat_rate=0,
        vat_amount=0,
        amount_ttc=fees,
        generated_from="management_fee",
        notes=f"Honoraires de gestion du {period_start} au {period_end}",
    )
    db.add(invoice)
    db.flush()
    db.add(InvoiceLine(
        invoice_id=invoice.id,
        position=1,
        description=f"Honoraires de gestion ({rate_percent}% des loyers encaissés)",
        quantity=1,
        unit_price=fees,
        amount_ht=fees,
        vat_rate=0,
        account_code="706",
    ))
    db.commit()
    db.refresh(invoice)
    return invoice


def update_invoice_status(db: Session, invoice_id: int, status: InvoiceStatus, due_date=None, notes=None) -> Invoice:
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise ValueError("Facture non trouvée")
    invoice.status = status
    if due_date:
        invoice.due_date = due_date
    if notes:
        invoice.notes = notes
    db.commit()
    db.refresh(invoice)
    return invoice


# ---------------------------------------------------------------------------
# Dépôts de garantie
# ---------------------------------------------------------------------------
def create_deposit(db: Session, data) -> DepositGuarantee:
    deposit = DepositGuarantee(
        reference=generate_reference("DEP"),
        **data.model_dump(),
        status=DepositStatus.HELD,
    )
    lease = db.query(Lease).filter(Lease.id == data.lease_id).first()
    if lease:
        deposit.start_date = data.start_date or lease.start_date
        deposit.end_date = data.end_date or lease.end_date
    db.add(deposit)
    db.flush()
    _post_deposit_journal_entry(db, deposit)
    db.commit()
    db.refresh(deposit)
    return deposit


def _post_deposit_journal_entry(db: Session, deposit: DepositGuarantee) -> None:
    ctx = _JournalContext(
        db,
        deposit.received_at,
        f"Encaissement dépôt de garantie {deposit.reference}",
        reference=deposit.reference,
        source_type="deposit",
        source_id=deposit.id,
        property_id=deposit.property_id,
    )
    ctx.debit("512", deposit.amount, tenant_id=deposit.tenant_id)
    ctx.credit("420", deposit.amount, tenant_id=deposit.tenant_id)
    ctx.commit()


def calculate_deposit_restitution(db: Session, deposit_id: int) -> Dict:
    """Calcule la restitution d'un dépôt (montant retourné et retenues)."""
    deposit = db.query(DepositGuarantee).filter(DepositGuarantee.id == deposit_id).first()
    if not deposit:
        raise ValueError("Dépôt non trouvé")

    deductions = sum(float(d.amount) for d in deposit.deductions)
    interest = round(float(deposit.amount) * float(deposit.interest_rate or 0) / 100, 2)
    amount_returned = round(float(deposit.amount) - deductions + interest, 2)
    amount_returned = max(amount_returned, 0)
    # Montant non restitué = ce qui reste dans le dépôt après restitution.
    amount_withheld = round(max(float(deposit.amount) - amount_returned, 0), 2)

    legal_months = deposit.restitution_legal_delay_months or 1
    deadline = None
    if deposit.end_date:
        deadline = _add_months(deposit.end_date, legal_months)

    return {
        "deposit_id": deposit.id,
        "reference": deposit.reference,
        "amount": deposit.amount,
        "deductions": round(deductions, 2),
        "interest": interest,
        "amount_returned": amount_returned,
        "amount_withheld": amount_withheld,
        "restitution_deadline": deadline,
        "legal_delay_months": legal_months,
    }


def return_deposit(db: Session, deposit_id: int, data) -> Dict:
    deposit = db.query(DepositGuarantee).filter(DepositGuarantee.id == deposit_id).first()
    if not deposit:
        raise ValueError("Dépôt non trouvé")
    deposit.amount_returned = data.amount_returned
    deposit.returned_at = datetime.combine(data.returned_at, datetime.min.time(), tzinfo=timezone.utc)
    deductions = sum(float(d.amount) for d in deposit.deductions)
    deposit.amount_withheld = round(float(deposit.amount) - float(data.amount_returned), 2)
    if deductions > 0 or float(data.amount_returned) < float(deposit.amount):
        deposit.status = DepositStatus.PARTIALLY_RETURNED if float(data.amount_returned) > 0 else DepositStatus.WITHHELD
    else:
        deposit.status = DepositStatus.RETURNED

    # Écriture de restitution.
    if float(data.amount_returned) > 0:
        ctx = _JournalContext(
            db,
            data.returned_at,
            f"Restitution dépôt de garantie {deposit.reference}",
            reference=deposit.reference,
            source_type="deposit_restoration",
            source_id=deposit.id,
            property_id=deposit.property_id,
        )
        ctx.debit("420", float(data.amount_returned), tenant_id=deposit.tenant_id)
        ctx.credit("512", float(data.amount_returned), tenant_id=deposit.tenant_id)
        ctx.commit()
    db.commit()
    db.refresh(deposit)
    return {
        "deposit_id": deposit.id,
        "status": deposit.status.value,
        "amount_returned": deposit.amount_returned,
        "amount_withheld": deposit.amount_withheld,
    }


def add_deposit_deduction(db: Session, deposit_id: int, data) -> DepositDeduction:
    deposit = db.query(DepositGuarantee).filter(DepositGuarantee.id == deposit_id).first()
    if not deposit:
        raise ValueError("Dépôt non trouvé")
    deduction = DepositDeduction(deposit_id=deposit.id, **data.model_dump())
    db.add(deduction)
    db.commit()
    db.refresh(deduction)
    return deduction


# ---------------------------------------------------------------------------
# Exports comptables
# ---------------------------------------------------------------------------
def export_accounting(db: Session, data) -> Dict:
    """Génère un export comptable (FEC, CSV, Sage, QuickBooks, Ciel)."""
    entries = db.query(JournalEntry).filter(
        JournalEntry.entry_date >= data.period_start,
        JournalEntry.entry_date <= data.period_end,
        JournalEntry.status != JournalEntryStatus.REVERSED,
    ).order_by(JournalEntry.entry_date).all()

    if data.entity_type == "owner" and data.entity_id:
        owner_tx = db.query(JournalEntry).filter(
            JournalEntry.entry_date >= data.period_start,
            JournalEntry.entry_date <= data.period_end,
            JournalEntry.source_type == "owner",
        )

    total_debit = 0.0
    total_credit = 0.0
    rows = []
    for entry in entries:
        for line in entry.lines:
            total_debit += line.debit
            total_credit += line.credit
            account = line.account
            rows.append({
                "date": entry.entry_date.isoformat(),
                "journal_code": entry.code,
                "piece": entry.reference or entry.code,
                "account_code": account.code if account else "",
                "account_label": account.label if account else "",
                "debit": line.debit,
                "credit": line.credit,
                "label": f"{entry.label} — {line.label or ''}".strip("— "),
                "source_type": entry.source_type,
                "source_id": entry.source_id,
            })

    content = _build_export_content(db, data.export_format, rows, data.period_start, data.period_end)
    export = AccountingExport(
        reference=generate_reference("EXPT"),
        export_format=data.export_format,
        period_start=data.period_start,
        period_end=data.period_end,
        entity_type=data.entity_type,
        entity_id=data.entity_id,
        entry_count=len(rows),
        total_debit=round(total_debit, 2),
        total_credit=round(total_credit, 2),
        status="generated",
        notes=data.notes,
    )
    db.add(export)
    db.commit()
    db.refresh(export)
    return {
        "export_id": export.id,
        "reference": export.reference,
        "format": data.export_format.value,
        "entry_count": len(rows),
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "content": content,
        "filename": _export_filename(data.export_format, data.period_start, data.period_end),
    }


def _build_export_content(db, export_format: ExportFormat, rows, start, end) -> str:
    buffer = io.StringIO()
    if export_format == ExportFormat.FEC:
        writer = csv.writer(buffer, delimiter="\t")
        writer.writerow(["JournalCode", "JournalLabel", "Date", "Compte", "CompteLibelle", "Debit", "Credit", "EcritureLib"])
        for row in rows:
            writer.writerow([
                row["journal_code"], "GestImmo", row["date"], row["account_code"],
                row["account_label"], f"{row['debit']:.2f}", f"{row['credit']:.2f}", row["label"],
            ])
    elif export_format == ExportFormat.SAGE:
        writer = csv.writer(buffer, delimiter=";")
        writer.writerow(["Journal", "Date", "Compte", "Débit", "Crédit", "Libellé"])
        for row in rows:
            writer.writerow([row["journal_code"], row["date"], row["account_code"], f"{row['debit']:.2f}", f"{row['credit']:.2f}", row["label"]])
    elif export_format == ExportFormat.QUICKBOOKS:
        writer = csv.writer(buffer)
        writer.writerow(["Date", "Account", "Description", "Amount"])
        for row in rows:
            amount = row["debit"] - row["credit"]
            writer.writerow([row["date"], row["account_code"], row["label"], f"{amount:.2f}"])
    elif export_format == ExportFormat.CIEL:
        writer = csv.writer(buffer, delimiter=",")
        writer.writerow(["date", "compte", "debit", "credit", "libelle"])
        for row in rows:
            writer.writerow([row["date"], row["account_code"], f"{row['debit']:.2f}", f"{row['credit']:.2f}", row["label"]])
    else:
        writer = csv.writer(buffer, delimiter=",")
        writer.writerow(["Date", "Journal", "Compte", "Libellé compte", "Débit", "Crédit", "Libellé écriture", "Type", "Source id"])
        for row in rows:
            writer.writerow([row["date"], row["journal_code"], row["account_code"], row["account_label"], f"{row['debit']:.2f}", f"{row['credit']:.2f}", row["label"], row["source_type"], row["source_id"]])
    return buffer.getvalue()


def _export_filename(export_format: ExportFormat, start: date, end: date) -> str:
    return f"export_{export_format.value}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.csv"
