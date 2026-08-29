"""Règles métier des modules complémentaires (18 à 31)."""
import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.extension import (
    AcquisitionOpportunity,
    DevelopmentProgram,
    LegalCaseFile,
    PropertyLoan,
    ShortTermBooking,
    ShortTermListing,
    UtilityMeter,
    UtilityReading,
)


def generate_reference(prefix: str) -> str:
    return f"{prefix}-{str(uuid.uuid4())[:8].upper()}"


def compute_booking_amount(listing: ShortTermListing, nights: int) -> float:
    return round(listing.nightly_rate * nights, 2)


def compute_loan_schedule(principal: float, annual_rate: float, months: int, start_date: date):
    """Tableau d'amortissement linéaire (capital constant) simplifié."""
    if months <= 0 or principal < 0:
        return []
    monthly_rate = annual_rate / 100 / 12
    principal_part = round(principal / months, 2)
    schedule = []
    remaining = principal
    for n in range(1, months + 1):
        interest_part = round(remaining * monthly_rate, 2)
        if n == months:
            principal_part = round(remaining, 2)
        remaining = max(0, remaining - principal_part)
        due = start_date
        if n > 1:
            # Ajouter n-1 mois (logique simple, sans librairie de calendrier)
            month = start_date.month - 1 + n
            year = start_date.year + month // 12
            month = month % 12 + 1
            day = min(start_date.day, 28)
            due = date(year, month, day)
        schedule.append({
            "payment_number": n,
            "due_date": due,
            "principal_part": principal_part,
            "interest_part": interest_part,
            "total_part": round(principal_part + interest_part, 2),
        })
    return schedule


def create_loan_payments(db: Session, loan: PropertyLoan) -> None:
    for row in compute_loan_schedule(loan.principal, loan.interest_rate, loan.duration_months, loan.start_date):
        from app.models.extension import LoanPayment
        value = row.pop("payment_number")
        db.add(LoanPayment(loan_id=loan.id, payment_number=value, **row))


def compute_utility_consumption(db: Session, meter: UtilityMeter, from_id: int, to_id: int) -> float:
    """Conso entre deux relevés : lecture la plus récente - lecture précédente."""
    readings = db.query(UtilityReading).filter(
        UtilityReading.meter_id == meter.id,
        UtilityReading.id.in_([from_id, to_id]),
    ).order_by(UtilityReading.reading_date).all()
    if len(readings) < 2:
        return 0
    return max(0.0, readings[-1].value - readings[0].value)


def generate_tracking_token() -> str:
    return uuid.uuid4().hex


def compute_full_names() -> None:
    return None


def _ref_exists(db: Session, model, reference: str) -> bool:
    return db.query(model).filter(model.reference == reference).first() is not None


def unique_reference(db: Session, model, prefix: str) -> str:
    ref = generate_reference(prefix)
    while _ref_exists(db, model, ref):
        ref = generate_reference(prefix)
    return ref
