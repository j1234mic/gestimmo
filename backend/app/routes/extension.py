"""Routes des modules complémentaires de gestion immobilière (18 à 31)."""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.database import get_db
from app.models.extension import *
from app.schemas.extension import *
from app.services.extension_service import (
    compute_booking_amount,
    compute_utility_consumption,
    create_loan_payments,
    generate_reference,
    generate_tracking_token,
    unique_reference,
)

router = APIRouter(prefix="/api/extension", tags=["Extension immobilière"])


def _page(query, page: int, limit: int):
    total = query.count()
    rows = query.order_by(getattr(query.column_descriptions[0]["entity"], "id", "id"))
    rows = rows.offset((page - 1) * limit).limit(limit).all()
    return rows, total


def _serialize_payload(rows, serializer=None):
    if serializer:
        return [serializer.model_validate(r).model_dump() for r in rows]
    return [r for r in rows]


@router.get("/overview")
def extension_overview(db: Session = Depends(get_db), user=Depends(require_read)):
    counts = {
        "short_term_listings": db.query(ShortTermListing).count(),
        "bookings": db.query(ShortTermBooking).count(),
        "legal_cases": db.query(LegalCaseFile).count(),
        "fiscal_records": db.query(FiscalYearRecord).count(),
        "loans": db.query(PropertyLoan).count(),
        "service_agreements": db.query(ServiceAgreement).count(),
        "access_keys": db.query(AccessKey).count(),
        "utility_meters": db.query(UtilityMeter).count(),
        "development_programs": db.query(DevelopmentProgram).count(),
        "development_units": db.query(DevelopmentUnit).count(),
        "investment_funds": db.query(InvestmentFund).count(),
        "energy_audits": db.query(EnergyAudit).count(),
        "satisfaction_surveys": db.query(SatisfactionSurvey).count(),
        "tasks": db.query(Task).count(),
        "acquisition_opportunities": db.query(AcquisitionOpportunity).count(),
        "public_pages": db.query(PublicPage).count(),
        "public_agents": db.query(PublicAgent).count(),
        "public_testimonials": db.query(PublicTestimonial).count(),
        "public_news": db.query(PublicNewsPost).count(),
        "public_leads": db.query(PublicLead).count(),
    }
    return {"data": counts, "total": sum(counts.values())}


# ============================================================
# MODULE 18 — COURTE DURÉE
# ============================================================
@router.post("/short-term-listings", response_model=ShortTermListingResponse, status_code=201)
def create_short_term_listing(data: ShortTermListingCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = ShortTermListing(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/short-term-listings")
def list_short_term_listings(
    property_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(ShortTermListing)
    if property_id:
        q = q.filter(ShortTermListing.property_id == property_id)
    total = q.count()
    rows = q.order_by(ShortTermListing.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [ShortTermListingResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.get("/short-term-listings/{listing_id}", response_model=ShortTermListingResponse)
def get_short_term_listing(listing_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    row = db.query(ShortTermListing).filter(ShortTermListing.id == listing_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Annonce courte durée non trouvée")
    return row


@router.put("/short-term-listings/{listing_id}", response_model=ShortTermListingResponse)
def update_short_term_listing(listing_id: int, data: ShortTermListingUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(ShortTermListing).filter(ShortTermListing.id == listing_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Annonce courte durée non trouvée")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/short-term-listings/{listing_id}")
def delete_short_term_listing(listing_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(ShortTermListing).filter(ShortTermListing.id == listing_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Annonce courte durée non trouvée")
    db.delete(row)
    db.commit()
    return {"message": "Annonce supprimée", "listing_id": listing_id}


@router.get("/short-term-listings/{listing_id}/quote")
def short_term_quote(listing_id: int, nights: int = Query(..., ge=1), db: Session = Depends(get_db), user=Depends(require_read)):
    listing = db.query(ShortTermListing).filter(ShortTermListing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce courte durée non trouvée")
    return {"listing_id": listing_id, "nights": nights, "amount": compute_booking_amount(listing, nights)}


@router.get("/short-term-listings/{listing_id}/availability")
def short_term_availability(
    listing_id: int,
    date_from: date = Query(..., description="Début de la période"),
    date_to: date = Query(..., description="Fin de la période"),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    listing = db.query(ShortTermListing).filter(ShortTermListing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce courte durée non trouvée")
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to doit être après date_from")
    bookings = db.query(ShortTermBooking).filter(
        ShortTermBooking.listing_id == listing_id,
        ShortTermBooking.status.in_([
            BookingStatus.PENDING,
            BookingStatus.CONFIRMED,
            BookingStatus.CHECKED_IN,
            BookingStatus.CHECKED_OUT,
        ]),
        ShortTermBooking.check_out > date_from,
        ShortTermBooking.check_in < date_to,
    ).all()
    blocked = {}
    for booking in bookings:
        current = booking.check_in
        while current < booking.check_out and current < date_to:
            if current >= date_from:
                blocked[current.isoformat()] = booking.status.value
            current = date.fromordinal(current.toordinal() + 1)
    days = []
    current = date_from
    while current <= date_to:
        days.append({"date": current.isoformat(), "available": not blocked.get(current.isoformat()), "booking_status": blocked.get(current.isoformat())})
        current = date.fromordinal(current.toordinal() + 1)
    return {"listing_id": listing_id, "days": days, "available_nights": sum(1 for d in days if d["available"])}


@router.get("/short-term-listings/{listing_id}/report")
def short_term_listing_report(
    listing_id: int,
    date_from: date,
    date_to: date,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    listing = db.query(ShortTermListing).filter(ShortTermListing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce courte durée non trouvée")
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to doit être après date_from")
    bookings = db.query(ShortTermBooking).filter(
        ShortTermBooking.listing_id == listing_id,
        ShortTermBooking.check_out > date_from,
        ShortTermBooking.check_in < date_to,
    ).all()
    nb_nights = (date_to - date_from).days
    sold_nights = sum(max(0, (min(b.check_out, date_to) - max(b.check_in, date_from)).days) for b in bookings)
    revenue = sum(b.amount + b.cleaning_fee + b.tax_amount for b in bookings)
    revpar = round(revenue / nb_nights, 2) if nb_nights else 0
    return {
        "listing_id": listing_id,
        "property_id": listing.property_id,
        "period": {"from": date_from, "to": date_to},
        "nights": nb_nights,
        "sold_nights": sold_nights,
        "occupancy_rate": round(sold_nights / nb_nights, 4) if nb_nights else 0,
        "revenue": round(revenue, 2),
        "trevpar": revpar,
        "revpar": revpar,
        "bookings": len(bookings),
    }


@router.get("/short-term-reporting")
def short_term_reporting(
    property_id: Optional[int] = None,
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    if date_to < date_from:
        raise HTTPException(status_code=422, detail="date_to doit être après date_from")
    q = db.query(ShortTermBooking)
    if property_id:
        q = q.join(ShortTermListing).filter(ShortTermListing.property_id == property_id)
    q = q.filter(ShortTermBooking.check_out > date_from, ShortTermBooking.check_in < date_to)
    bookings = q.all()
    nb_nights = (date_to - date_from).days
    sold_nights = sum(max(0, (min(b.check_out, date_to) - max(b.check_in, date_from)).days) for b in bookings)
    revenue = sum(b.amount + b.cleaning_fee + b.tax_amount for b in bookings)
    return {
        "property_id": property_id,
        "period": {"from": date_from, "to": date_to},
        "nights": nb_nights,
        "sold_nights": sold_nights,
        "occupancy_rate": round(sold_nights / nb_nights, 4) if nb_nights else 0,
        "revenue": round(revenue, 2),
        "revpar": round(revenue / nb_nights, 2) if nb_nights else 0,
        "bookings": len(bookings),
    }


@router.post("/short-term-bookings", response_model=ShortTermBookingResponse, status_code=201)
def create_short_term_booking(data: ShortTermBookingCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = ShortTermBooking(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/short-term-bookings")
def list_short_term_bookings(
    property_id: Optional[int] = None,
    listing_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(ShortTermBooking)
    if listing_id:
        q = q.filter(ShortTermBooking.listing_id == listing_id)
    if property_id:
        q = q.join(ShortTermListing).filter(ShortTermListing.property_id == property_id)
    if status:
        q = q.filter(ShortTermBooking.status == status)
    total = q.count()
    rows = q.order_by(ShortTermBooking.check_in.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [ShortTermBookingResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.put("/short-term-bookings/{booking_id}", response_model=ShortTermBookingResponse)
def update_short_term_booking(booking_id: int, data: ShortTermBookingUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(ShortTermBooking).filter(ShortTermBooking.id == booking_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Réservation non trouvée")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/short-term-bookings/{booking_id}")
def delete_short_term_booking(booking_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(ShortTermBooking).filter(ShortTermBooking.id == booking_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Réservation non trouvée")
    db.delete(row)
    db.commit()
    return {"message": "Réservation supprimée", "booking_id": booking_id}


@router.post("/short-term-price-rules", response_model=ShortTermPriceRuleResponse, status_code=201)
def create_short_term_price_rule(data: ShortTermPriceRuleCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = ShortTermPriceRule(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/short-term-price-rules")
def list_short_term_price_rules(listing_id: Optional[int] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(ShortTermPriceRule)
    if listing_id:
        q = q.filter(ShortTermPriceRule.listing_id == listing_id)
    rows = q.order_by(ShortTermPriceRule.date_from.desc()).all()
    return {"data": [ShortTermPriceRuleResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


# ============================================================
# MODULE 19 — CONTENTIEUX
# ============================================================
@router.post("/legal-cases", response_model=LegalCaseResponse, status_code=201)
def create_legal_case(data: LegalCaseCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    payload = data.model_dump()
    payload["reference"] = unique_reference(db, LegalCaseFile, "LGL")
    if payload.get("opened_at") is None:
        payload["opened_at"] = date.today()
    row = LegalCaseFile(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/legal-cases")
def list_legal_cases(
    status: Optional[str] = None,
    case_type: Optional[str] = None,
    property_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(LegalCaseFile)
    if status:
        q = q.filter(LegalCaseFile.status == status)
    if case_type:
        q = q.filter(LegalCaseFile.case_type == case_type)
    if property_id:
        q = q.filter(LegalCaseFile.property_id == property_id)
    total = q.count()
    rows = q.order_by(LegalCaseFile.opened_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [LegalCaseResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.get("/legal-cases/{case_id}", response_model=LegalCaseResponse)
def get_legal_case(case_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    row = db.query(LegalCaseFile).filter(LegalCaseFile.id == case_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Dossier contentieux non trouvé")
    return row


@router.put("/legal-cases/{case_id}", response_model=LegalCaseResponse)
def update_legal_case(case_id: int, data: LegalCaseUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(LegalCaseFile).filter(LegalCaseFile.id == case_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Dossier contentieux non trouvé")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/legal-cases/{case_id}")
def delete_legal_case(case_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(LegalCaseFile).filter(LegalCaseFile.id == case_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Dossier contentieux non trouvé")
    db.delete(row)
    db.commit()
    return {"message": "Dossier supprimé", "case_id": case_id}


@router.post("/legal-actions", response_model=LegalActionResponse, status_code=201)
def create_legal_action(data: LegalActionCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    case = db.query(LegalCaseFile).filter(LegalCaseFile.id == data.case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Dossier contentieux non trouvé")
    row = LegalAction(**{**data.model_dump(), "created_by": getattr(user, "email", None)})
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/legal-cases/{case_id}/actions")
def list_legal_actions(case_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    case = db.query(LegalCaseFile).filter(LegalCaseFile.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Dossier contentieux non trouvé")
    rows = db.query(LegalAction).filter(LegalAction.case_id == case_id).order_by(LegalAction.action_date.desc()).all()
    return {"data": [LegalActionResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


# ============================================================
# MODULE 20 — FISCALITÉ
# ============================================================
@router.post("/fiscal-records", response_model=FiscalYearRecordResponse, status_code=201)
def create_fiscal_record(data: FiscalYearRecordCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    payload = data.model_dump()
    payload["result"] = round(payload.get("rental_income", 0) - payload.get("deductible_charges", 0) - payload.get("amortization", 0), 2)
    payload["tax_amount"] = round(max(0, payload["result"]) * 0.30, 2)
    row = FiscalYearRecord(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/fiscal-records")
def list_fiscal_records(
    owner_id: Optional[int] = None,
    property_id: Optional[int] = None,
    fiscal_year: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(FiscalYearRecord)
    if owner_id:
        q = q.filter(FiscalYearRecord.owner_id == owner_id)
    if property_id:
        q = q.filter(FiscalYearRecord.property_id == property_id)
    if fiscal_year:
        q = q.filter(FiscalYearRecord.fiscal_year == fiscal_year)
    total = q.count()
    rows = q.order_by(FiscalYearRecord.fiscal_year.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [FiscalYearRecordResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.put("/fiscal-records/{record_id}", response_model=FiscalYearRecordResponse)
def update_fiscal_record(record_id: int, data: FiscalYearRecordUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(FiscalYearRecord).filter(FiscalYearRecord.id == record_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Enregistrement fiscal non trouvé")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    row.result = round(row.rental_income - row.deductible_charges - row.amortization, 2)
    row.tax_amount = round(max(0, row.result) * 0.30, 2)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/fiscal-records/{record_id}")
def delete_fiscal_record(record_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(FiscalYearRecord).filter(FiscalYearRecord.id == record_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Enregistrement fiscal non trouvé")
    db.delete(row)
    db.commit()
    return {"message": "Enregistrement fiscal supprimé", "record_id": record_id}


# ============================================================
# MODULE 21 — FINANCEMENT
# ============================================================
@router.post("/loans", response_model=PropertyLoanResponse, status_code=201)
def create_loan(data: PropertyLoanCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    payload = data.model_dump()
    monthly_payment = 0.0
    rate = payload["interest_rate"] / 100 / 12
    if rate:
        monthly_payment = round(
            payload["principal"] * rate / (1 - (1 + rate) ** -payload["duration_months"]), 2
        )
    else:
        monthly_payment = round(payload["principal"] / payload["duration_months"], 2)
    payload["monthly_payment"] = monthly_payment
    row = PropertyLoan(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    create_loan_payments(db, row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/loans")
def list_loans(
    owner_id: Optional[int] = None,
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(PropertyLoan)
    if owner_id:
        q = q.filter(PropertyLoan.owner_id == owner_id)
    if property_id:
        q = q.filter(PropertyLoan.property_id == property_id)
    if status:
        q = q.filter(PropertyLoan.status == status)
    total = q.count()
    rows = q.order_by(PropertyLoan.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [PropertyLoanResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.get("/loans/{loan_id}/schedule")
def loan_schedule(loan_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    loan = db.query(PropertyLoan).filter(PropertyLoan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Prêt non trouvé")
    rows = db.query(LoanPayment).filter(LoanPayment.loan_id == loan_id).order_by(LoanPayment.payment_number).all()
    return {"data": [LoanPaymentResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.put("/loans/{loan_id}", response_model=PropertyLoanResponse)
def update_loan(loan_id: int, data: PropertyLoanUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PropertyLoan).filter(PropertyLoan.id == loan_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Prêt non trouvé")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.put("/loans/{loan_id}/payments/{payment_id}", response_model=LoanPaymentResponse)
def update_loan_payment(loan_id: int, payment_id: int, data: LoanPaymentUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(LoanPayment).filter(LoanPayment.id == payment_id, LoanPayment.loan_id == loan_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Échéance non trouvée")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/loans/{loan_id}")
def delete_loan(loan_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PropertyLoan).filter(PropertyLoan.id == loan_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Prêt non trouvé")
    db.delete(row)
    db.commit()
    return {"message": "Prêt supprimé", "loan_id": loan_id}


# ============================================================
# SERVICES RÉSIDENTIELS
# ============================================================
@router.post("/service-agreements", response_model=ServiceAgreementResponse, status_code=201)
def create_service_agreement(data: ServiceAgreementCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = ServiceAgreement(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/service-agreements")
def list_service_agreements(
    property_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(ServiceAgreement)
    if property_id:
        q = q.filter(ServiceAgreement.property_id == property_id)
    if tenant_id:
        q = q.filter(ServiceAgreement.tenant_id == tenant_id)
    if status:
        q = q.filter(ServiceAgreement.status == status)
    rows = q.order_by(ServiceAgreement.id.desc()).all()
    return {"data": [ServiceAgreementResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.put("/service-agreements/{agreement_id}", response_model=ServiceAgreementResponse)
def update_service_agreement(agreement_id: int, data: ServiceAgreementUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(ServiceAgreement).filter(ServiceAgreement.id == agreement_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Contrat de service non trouvé")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.post("/service-invoices", response_model=ServiceInvoiceResponse, status_code=201)
def create_service_invoice(data: ServiceInvoiceCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    payload = data.model_dump()
    payload["total"] = round(payload.get("amount", 0) + payload.get("vat_amount", 0), 2)
    row = ServiceInvoice(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/service-invoices")
def list_service_invoices(agreement_id: Optional[int] = None, status: Optional[str] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(ServiceInvoice)
    if agreement_id:
        q = q.filter(ServiceInvoice.agreement_id == agreement_id)
    if status:
        q = q.filter(ServiceInvoice.status == status)
    rows = q.order_by(ServiceInvoice.period.desc()).all()
    return {"data": [ServiceInvoiceResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.put("/service-invoices/{invoice_id}", response_model=ServiceInvoiceResponse)
def update_service_invoice(invoice_id: int, data: ServiceInvoiceUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(ServiceInvoice).filter(ServiceInvoice.id == invoice_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Facture de service non trouvée")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    row.total = round(row.amount + row.vat_amount, 2)
    db.commit()
    db.refresh(row)
    return row


# ============================================================
# ACCÈS, CLÉS & SÛRETÉ
# ============================================================
@router.post("/access-keys", response_model=AccessKeyResponse, status_code=201)
def create_access_key(data: AccessKeyCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = AccessKey(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/access-keys")
def list_access_keys(property_id: Optional[int] = None, status: Optional[str] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(AccessKey)
    if property_id:
        q = q.filter(AccessKey.property_id == property_id)
    if status:
        q = q.filter(AccessKey.status == status)
    rows = q.order_by(AccessKey.id.desc()).all()
    return {"data": [AccessKeyResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.put("/access-keys/{key_id}", response_model=AccessKeyResponse)
def update_access_key(key_id: int, data: AccessKeyUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(AccessKey).filter(AccessKey.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Clé/vaccès non trouvé")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.post("/key-operations", response_model=KeyOperationResponse, status_code=201)
def create_key_operation(data: KeyOperationCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    key = db.query(AccessKey).filter(AccessKey.id == data.key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Clé/vaccès non trouvé")
    operation = KeyOperation(**data.model_dump())
    if data.action == "issue":
        key.status = "prete"
    elif data.action == "return":
        key.status = "disponible"
        operation.returned_at = datetime.now(timezone.utc)
    elif data.action == "lost":
        key.status = "perdu"
    db.add(operation)
    db.commit()
    db.refresh(operation)
    return operation


@router.get("/access-keys/{key_id}/operations")
def list_key_operations(key_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    key = db.query(AccessKey).filter(AccessKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="Clé/vaccès non trouvé")
    rows = db.query(KeyOperation).filter(KeyOperation.key_id == key_id).order_by(KeyOperation.occurred_at.desc()).all()
    return {"data": [KeyOperationResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


# ============================================================
# COMPTEURS & ÉNERGIE
# ============================================================
@router.post("/utility-meters", response_model=UtilityMeterResponse, status_code=201)
def create_utility_meter(data: UtilityMeterCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = UtilityMeter(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/utility-meters")
def list_utility_meters(property_id: Optional[int] = None, meter_type: Optional[str] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(UtilityMeter)
    if property_id:
        q = q.filter(UtilityMeter.property_id == property_id)
    if meter_type:
        q = q.filter(UtilityMeter.meter_type == meter_type)
    rows = q.order_by(UtilityMeter.id.desc()).all()
    return {"data": [UtilityMeterResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.post("/utility-readings", response_model=UtilityReadingResponse, status_code=201)
def create_utility_reading(data: UtilityReadingCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    meter = db.query(UtilityMeter).filter(UtilityMeter.id == data.meter_id).first()
    if not meter:
        raise HTTPException(status_code=404, detail="Compteur non trouvé")
    row = UtilityReading(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    if not meter.initial_reading:
        meter.initial_reading = row.value
        db.commit()
    return row


@router.get("/utility-meters/{meter_id}/readings")
def list_utility_readings(meter_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    meter = db.query(UtilityMeter).filter(UtilityMeter.id == meter_id).first()
    if not meter:
        raise HTTPException(status_code=404, detail="Compteur non trouvé")
    rows = db.query(UtilityReading).filter(UtilityReading.meter_id == meter_id).order_by(UtilityReading.reading_date.desc()).all()
    return {"data": [UtilityReadingResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.post("/utility-bills", response_model=UtilityBillResponse, status_code=201)
def create_utility_bill(data: UtilityBillCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = UtilityBill(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/utility-bills")
def list_utility_bills(property_id: Optional[int] = None, period: Optional[str] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(UtilityBill)
    if property_id:
        q = q.filter(UtilityBill.property_id == property_id)
    if period:
        q = q.filter(UtilityBill.period == period)
    rows = q.order_by(UtilityBill.period.desc()).all()
    return {"data": [UtilityBillResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.put("/utility-bills/{bill_id}", response_model=UtilityBillResponse)
def update_utility_bill(bill_id: int, data: UtilityBillUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(UtilityBill).filter(UtilityBill.id == bill_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Facture énergie non trouvée")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


# ============================================================
# DÉVELOPPEMENT / VEFA
# ============================================================
@router.post("/development-programs", response_model=DevelopmentProgramResponse, status_code=201)
def create_development_program(data: DevelopmentProgramCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    payload = data.model_dump()
    payload["reference"] = unique_reference(db, DevelopmentProgram, "DEV")
    row = DevelopmentProgram(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/development-programs")
def list_development_programs(status: Optional[str] = None, city: Optional[str] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(DevelopmentProgram)
    if status:
        q = q.filter(DevelopmentProgram.status == status)
    if city:
        q = q.filter(DevelopmentProgram.city.ilike(f"%{city}%"))
    rows = q.order_by(DevelopmentProgram.id.desc()).all()
    return {"data": [DevelopmentProgramResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.put("/development-programs/{program_id}", response_model=DevelopmentProgramResponse)
def update_development_program(program_id: int, data: DevelopmentProgramUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(DevelopmentProgram).filter(DevelopmentProgram.id == program_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Programme de développement non trouvé")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.post("/development-units", response_model=DevelopmentUnitResponse, status_code=201)
def create_development_unit(data: DevelopmentUnitCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    payload = data.model_dump()
    payload["price_ttc"] = round((payload.get("price_ht") or 0) * (1 + (payload.get("tva_rate") or 0) / 100), 2)
    row = DevelopmentUnit(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    try:
        program = db.query(DevelopmentProgram).filter(DevelopmentProgram.id == row.program_id).first()
        if program and program.total_units in (0, None):
            program.total_units = db.query(DevelopmentUnit).filter(DevelopmentUnit.program_id == program.id).count()
            db.commit()
    except Exception:
        pass
    return row


@router.get("/development-programs/{program_id}/units")
def list_development_units(program_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    rows = db.query(DevelopmentUnit).filter(DevelopmentUnit.program_id == program_id).order_by(DevelopmentUnit.label).all()
    return {"data": [DevelopmentUnitResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.post("/vefa-reservations", response_model=VefaReservationResponse, status_code=201)
def create_vefa_reservation(data: VefaReservationCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    unit = db.query(DevelopmentUnit).filter(DevelopmentUnit.id == data.unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Lot VEFA non trouvé")
    row = VefaReservation(**data.model_dump())
    unit.status = "reserved"
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/vefa-reservations/{reservation_id}", response_model=VefaReservationResponse)
def update_vefa_reservation(reservation_id: int, data: VefaReservationUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(VefaReservation).filter(VefaReservation.id == reservation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Réservation VEFA non trouvée")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


# ============================================================
# INVESTISSEURS / FONDS
# ============================================================
@router.post("/investment-funds", response_model=InvestmentFundResponse, status_code=201)
def create_investment_fund(data: InvestmentFundCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = InvestmentFund(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/investment-funds")
def list_investment_funds(fund_type: Optional[str] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(InvestmentFund)
    if fund_type:
        q = q.filter(InvestmentFund.fund_type == fund_type)
    rows = q.order_by(InvestmentFund.name).all()
    return {"data": [InvestmentFundResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.post("/fund-subscriptions", response_model=FundSubscriptionResponse, status_code=201)
def create_fund_subscription(data: FundSubscriptionCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    fund = db.query(InvestmentFund).filter(InvestmentFund.id == data.fund_id).first()
    if not fund:
        raise HTTPException(status_code=404, detail="Fonds non trouvé")
    row = FundSubscription(**data.model_dump())
    db.add(row)
    fund.total_capital = (fund.total_capital or 0) + row.amount
    db.commit()
    db.refresh(row)
    return row


@router.get("/investment-funds/{fund_id}/subscriptions")
def list_fund_subscriptions(fund_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    rows = db.query(FundSubscription).filter(FundSubscription.fund_id == fund_id).order_by(FundSubscription.subscription_date.desc()).all()
    return {"data": [FundSubscriptionResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.post("/fund-distributions", response_model=FundDistributionResponse, status_code=201)
def create_fund_distribution(data: FundDistributionCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    fund = db.query(InvestmentFund).filter(InvestmentFund.id == data.fund_id).first()
    if not fund:
        raise HTTPException(status_code=404, detail="Fonds non trouvé")
    row = FundDistribution(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/investment-funds/{fund_id}/distributions")
def list_fund_distributions(fund_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    rows = db.query(FundDistribution).filter(FundDistribution.fund_id == fund_id).order_by(FundDistribution.period.desc()).all()
    return {"data": [FundDistributionResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


# ============================================================
# PERFORMANCE ÉNERGÉTIQUE & RÉNOVATION
# ============================================================
@router.post("/energy-audits", response_model=EnergyAuditResponse, status_code=201)
def create_energy_audit(data: EnergyAuditCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = EnergyAudit(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/energy-audits")
def list_energy_audits(property_id: Optional[int] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(EnergyAudit)
    if property_id:
        q = q.filter(EnergyAudit.property_id == property_id)
    rows = q.order_by(EnergyAudit.audit_date.desc()).all()
    return {"data": [EnergyAuditResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.post("/energy-projects", response_model=EnergyRenovationProjectResponse, status_code=201)
def create_energy_project(data: EnergyRenovationProjectCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = EnergyRenovationProject(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/energy-projects")
def list_energy_projects(property_id: Optional[int] = None, status: Optional[str] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(EnergyRenovationProject)
    if property_id:
        q = q.filter(EnergyRenovationProject.property_id == property_id)
    if status:
        q = q.filter(EnergyRenovationProject.status == status)
    rows = q.order_by(EnergyRenovationProject.id.desc()).all()
    return {"data": [EnergyRenovationProjectResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.post("/energy-grants", response_model=EnergyGrantResponse, status_code=201)
def create_energy_grant(data: EnergyGrantCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = EnergyGrant(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/energy-projects/{project_id}/grants")
def list_energy_grants(project_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    rows = db.query(EnergyGrant).filter(EnergyGrant.project_id == project_id).all()
    return {"data": [EnergyGrantResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


# ============================================================
# QUALITÉ DE SERVICE
# ============================================================
@router.post("/satisfaction-surveys", response_model=SatisfactionSurveyResponse, status_code=201)
def create_satisfaction_survey(data: SatisfactionSurveyCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = SatisfactionSurvey(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/satisfaction-surveys")
def list_satisfaction_surveys(
    respondent_type: Optional[str] = None,
    property_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(SatisfactionSurvey)
    if respondent_type:
        q = q.filter(SatisfactionSurvey.respondent_type == respondent_type)
    if property_id:
        q = q.filter(SatisfactionSurvey.property_id == property_id)
    rows = q.order_by(SatisfactionSurvey.created_at.desc()).all()
    return {"data": [SatisfactionSurveyResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


# ============================================================
# TÂCHES INTERNES
# ============================================================
@router.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(data: TaskCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = Task(**{**data.model_dump(), "created_by": getattr(user, "email", None)})
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/tasks")
def list_tasks(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    status: Optional[str] = None,
    assignee_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(Task)
    if entity_type:
        q = q.filter(Task.entity_type == entity_type)
    if entity_id:
        q = q.filter(Task.entity_id == entity_id)
    if status:
        q = q.filter(Task.status == status)
    if assignee_id:
        q = q.filter(Task.assignee_id == assignee_id)
    rows = q.order_by(Task.due_date.desc().nulls_last()).all()
    return {"data": [TaskResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.put("/tasks/{task_id}", response_model=TaskResponse)
def update_task(task_id: int, data: TaskUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(Task).filter(Task.id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")
    prior = row.status
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    if row.status != prior and row.status == "terminee":
        row.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


@router.post("/tasks/{task_id}/comments", response_model=TaskCommentResponse, status_code=201)
def create_task_comment(task_id: int, data: TaskCommentCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(Task).filter(Task.id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")
    comment = TaskComment(**{**data.model_dump(), "task_id": task_id, "author": data.author or getattr(user, "email", None)})
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/tasks/{task_id}/comments")
def list_task_comments(task_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    row = db.query(Task).filter(Task.id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")
    rows = db.query(TaskComment).filter(TaskComment.task_id == task_id).order_by(TaskComment.created_at).all()
    return {"data": [TaskCommentResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(Task).filter(Task.id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tâche non trouvée")
    db.delete(row)
    db.commit()
    return {"message": "Tâche supprimée", "task_id": task_id}


# ============================================================
# SOURCING & ACQUISITIONS
# ============================================================
@router.post("/acquisition-opportunities", response_model=AcquisitionOpportunityResponse, status_code=201)
def create_acquisition_opportunity(data: AcquisitionOpportunityCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    payload = data.model_dump()
    payload["reference"] = unique_reference(db, AcquisitionOpportunity, "GAME")
    row = AcquisitionOpportunity(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/acquisition-opportunities")
def list_acquisition_opportunities(
    status: Optional[str] = None,
    city: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(AcquisitionOpportunity)
    if status:
        q = q.filter(AcquisitionOpportunity.status == status)
    if city:
        q = q.filter(AcquisitionOpportunity.city.ilike(f"%{city}%"))
    total = q.count()
    rows = q.order_by(AcquisitionOpportunity.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [AcquisitionOpportunityResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.put("/acquisition-opportunities/{opportunity_id}", response_model=AcquisitionOpportunityResponse)
def update_acquisition_opportunity(opportunity_id: int, data: AcquisitionOpportunityUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(AcquisitionOpportunity).filter(AcquisitionOpportunity.id == opportunity_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Opportunité non trouvée")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.post("/due-diligence-items", response_model=DueDiligenceItemResponse, status_code=201)
def create_due_diligence_item(data: DueDiligenceItemCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    opp = db.query(AcquisitionOpportunity).filter(AcquisitionOpportunity.id == data.opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunité non trouvée")
    row = DueDiligenceItem(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/acquisition-opportunities/{opportunity_id}/due-diligence")
def list_due_diligence_items(opportunity_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    opp = db.query(AcquisitionOpportunity).filter(AcquisitionOpportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunité non trouvée")
    rows = db.query(DueDiligenceItem).filter(DueDiligenceItem.opportunity_id == opportunity_id).order_by(DueDiligenceItem.due_date).all()
    return {"data": [DueDiligenceItemResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


# ============================================================
# MODULE 22 — PORTAIL PUBLIC / SITE VITRINE (administration)
# ============================================================
@router.post("/public-pages", response_model=PublicPageResponse, status_code=201)
def create_public_page(data: PublicPageCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    payload = data.model_dump()
    if payload.get("status") == "published" and not payload.get("published_at"):
        payload["published_at"] = datetime.now(timezone.utc)
    row = PublicPage(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/public-pages")
def list_public_pages(status: Optional[str] = None, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(PublicPage)
    if status:
        q = q.filter(PublicPage.status == status)
    total = q.count()
    rows = q.order_by(PublicPage.title).offset((page - 1) * limit).limit(limit).all()
    return {"data": [PublicPageResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.put("/public-pages/{page_id}", response_model=PublicPageResponse)
def update_public_page(page_id: int, data: PublicPageUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PublicPage).filter(PublicPage.id == page_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Page publique non trouvée")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    if row.status == "published" and not row.published_at:
        row.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/public-pages/{page_id}")
def delete_public_page(page_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PublicPage).filter(PublicPage.id == page_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Page publique non trouvée")
    db.delete(row)
    db.commit()
    return {"message": "Page publique supprimée", "page_id": page_id}


@router.post("/public-agents", response_model=PublicAgentResponse, status_code=201)
def create_public_agent(data: PublicAgentCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = PublicAgent(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/public-agents")
def list_public_agents(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(PublicAgent)
    total = q.count()
    rows = q.order_by(PublicAgent.order, PublicAgent.id).offset((page - 1) * limit).limit(limit).all()
    return {"data": [PublicAgentResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.put("/public-agents/{agent_id}", response_model=PublicAgentResponse)
def update_public_agent(agent_id: int, data: PublicAgentUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PublicAgent).filter(PublicAgent.id == agent_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Agent public non trouvé")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/public-agents/{agent_id}")
def delete_public_agent(agent_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PublicAgent).filter(PublicAgent.id == agent_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Agent public non trouvé")
    db.delete(row)
    db.commit()
    return {"message": "Agent public supprimé", "agent_id": agent_id}


@router.post("/public-testimonials", response_model=PublicTestimonialResponse, status_code=201)
def create_public_testimonial(data: PublicTestimonialCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = PublicTestimonial(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/public-testimonials")
def list_public_testimonials(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(PublicTestimonial)
    total = q.count()
    rows = q.order_by(PublicTestimonial.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [PublicTestimonialResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.put("/public-testimonials/{testimonial_id}", response_model=PublicTestimonialResponse)
def update_public_testimonial(testimonial_id: int, data: PublicTestimonialUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PublicTestimonial).filter(PublicTestimonial.id == testimonial_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Témoignage non trouvé")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/public-testimonials/{testimonial_id}")
def delete_public_testimonial(testimonial_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PublicTestimonial).filter(PublicTestimonial.id == testimonial_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Témoignage non trouvé")
    db.delete(row)
    db.commit()
    return {"message": "Témoignage supprimé", "testimonial_id": testimonial_id}


@router.post("/public-news", response_model=PublicNewsPostResponse, status_code=201)
def create_public_news(data: PublicNewsPostCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    payload = data.model_dump()
    if payload.get("status") == "published" and not payload.get("published_at"):
        payload["published_at"] = datetime.now(timezone.utc)
    row = PublicNewsPost(**payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/public-news")
def list_public_news(status: Optional[str] = None, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(PublicNewsPost)
    if status:
        q = q.filter(PublicNewsPost.status == status)
    total = q.count()
    rows = q.order_by(PublicNewsPost.published_at.desc().nulls_last()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [PublicNewsPostResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.put("/public-news/{news_id}", response_model=PublicNewsPostResponse)
def update_public_news(news_id: int, data: PublicNewsPostUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PublicNewsPost).filter(PublicNewsPost.id == news_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Actualité publique non trouvée")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    if row.status == "published" and not row.published_at:
        row.published_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/public-news/{news_id}")
def delete_public_news(news_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PublicNewsPost).filter(PublicNewsPost.id == news_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Actualité publique non trouvée")
    db.delete(row)
    db.commit()
    return {"message": "Actualité supprimée", "news_id": news_id}


@router.get("/public-leads")
def list_public_leads(
    request_type: Optional[str] = None,
    status: Optional[str] = None,
    property_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(PublicLead)
    if request_type:
        q = q.filter(PublicLead.request_type == request_type)
    if status:
        q = q.filter(PublicLead.status == status)
    if property_id:
        q = q.filter(PublicLead.property_id == property_id)
    total = q.count()
    rows = q.order_by(PublicLead.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [PublicLeadResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.put("/public-leads/{lead_id}", response_model=PublicLeadResponse)
def update_public_lead(lead_id: int, data: PublicLeadUpdate, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PublicLead).filter(PublicLead.id == lead_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Demande publique non trouvée")
    for f, v in data.model_dump(exclude_unset=True).items():
        setattr(row, f, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/public-leads/{lead_id}")
def delete_public_lead(lead_id: int, db: Session = Depends(get_db), user=Depends(require_write)):
    row = db.query(PublicLead).filter(PublicLead.id == lead_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Demande publique non trouvée")
    db.delete(row)
    db.commit()
    return {"message": "Demande publique supprimée", "lead_id": lead_id}


# ============================================================
# INDICATEURS CROISÉS
# ============================================================
@router.get("/fiscal-summary")
def fiscal_summary(owner_id: int, fiscal_year: Optional[int] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(FiscalYearRecord).filter(FiscalYearRecord.owner_id == owner_id)
    if fiscal_year:
        q = q.filter(FiscalYearRecord.fiscal_year == fiscal_year)
    rows = q.all()
    return {
        "owner_id": owner_id,
        "fiscal_year": fiscal_year,
        "records": len(rows),
        "rental_income": round(sum(r.rental_income for r in rows), 2),
        "deductible_charges": round(sum(r.deductible_charges for r in rows), 2),
        "amortization": round(sum(r.amortization for r in rows), 2),
        "result": round(sum(r.result for r in rows), 2),
        "tax_amount": round(sum(r.tax_amount for r in rows), 2),
    }


@router.get("/utility-meters/{meter_id}/consumption")
def utility_consumption(
    meter_id: int,
    reading_from: int,
    reading_to: int,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    meter = db.query(UtilityMeter).filter(UtilityMeter.id == meter_id).first()
    if not meter:
        raise HTTPException(status_code=404, detail="Compteur non trouvé")
    if reading_from == reading_to:
        raise HTTPException(status_code=422, detail="Les relevés doivent être différents")
    consumption = compute_utility_consumption(db, meter, reading_from, reading_to)
    return {"meter_id": meter_id, "from_id": reading_from, "to_id": reading_to, "consumption": round(consumption, 2), "unit": meter.unit}


@router.get("/energy-projects/{project_id}/roi")
def energy_project_roi(project_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    project = db.query(EnergyRenovationProject).filter(EnergyRenovationProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet de rénovation énergétique non trouvé")
    grants = db.query(EnergyGrant).filter(EnergyGrant.project_id == project_id).all()
    grants_total = sum(g.amount or 0 for g in grants if g.status == "accepted")
    net_cost = max(0, (project.budget or 0) - grants_total)
    savings = project.estimated_savings or 0
    payback_years = round(net_cost / savings, 2) if savings else None
    return {
        "project_id": project_id,
        "budget": project.budget or 0,
        "grants_total": round(grants_total, 2),
        "net_cost": round(net_cost, 2),
        "estimated_savings": savings,
        "payback_years": payback_years,
        "grants": len(grants),
    }


@router.get("/satisfaction-summary")
def satisfaction_summary(
    respondent_type: Optional[str] = None,
    property_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(SatisfactionSurvey)
    if respondent_type:
        q = q.filter(SatisfactionSurvey.respondent_type == respondent_type)
    if property_id:
        q = q.filter(SatisfactionSurvey.property_id == property_id)
    rows = q.all()
    nps_values = [r.nps_score for r in rows if r.nps_score is not None]
    csat_values = [r.csat for r in rows if r.csat is not None]
    promoters = sum(1 for n in nps_values if n >= 9)
    detractors = sum(1 for n in nps_values if n <= 6)
    nps = round((promoters - detractors) / len(nps_values) * 100, 2) if nps_values else None
    return {
        "respondent_type": respondent_type,
        "property_id": property_id,
        "surveys": len(rows),
        "nps_score": nps,
        "promoters": promoters,
        "detractors": detractors,
        "csat_average": round(sum(csat_values) / len(csat_values), 2) if csat_values else None,
        "low_scores": len([r for r in rows if (r.csat or 0) <= 2]),
    }


@router.get("/tasks/board")
def task_board(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    assignee_id: Optional[int] = None,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(Task)
    if entity_type:
        q = q.filter(Task.entity_type == entity_type)
    if entity_id:
        q = q.filter(Task.entity_id == entity_id)
    if assignee_id:
        q = q.filter(Task.assignee_id == assignee_id)
    rows = q.all()
    buckets = {"a_faire": [], "en_cours": [], "en_attente": [], "terminee": [], "annulee": []}
    for row in rows:
        status = row.status.value if hasattr(row.status, "value") else row.status
        buckets.setdefault(status, []).append(TaskResponse.model_validate(row).model_dump())
    return {"data": buckets, "total": len(rows)}


@router.get("/acquisition-opportunities/{opportunity_id}/analysis")
def acquisition_analysis(opportunity_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    opp = db.query(AcquisitionOpportunity).filter(AcquisitionOpportunity.id == opportunity_id).first()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunité non trouvée")
    price_per_sqm = round(opp.expected_price / opp.total_area, 2) if opp.expected_price and opp.total_area else None
    gross_yield = round(opp.potential_rent * 12 / opp.expected_price, 4) if opp.potential_rent and opp.expected_price else None
    discount = round((opp.market_price - opp.expected_price) / opp.market_price, 4) if opp.market_price and opp.expected_price else None
    diligence_done = db.query(DueDiligenceItem).filter(
        DueDiligenceItem.opportunity_id == opportunity_id,
        DueDiligenceItem.status == "done",
    ).count()
    diligence_total = db.query(DueDiligenceItem).filter(DueDiligenceItem.opportunity_id == opportunity_id).count()
    score = 50
    if gross_yield is not None:
        score += min(20, max(0, int(gross_yield * 100)))
    if discount is not None:
        score += min(20, max(0, int(discount * 100)))
    if diligence_total:
        score += min(10, round(diligence_done / diligence_total * 10))
    return {
        "opportunity_id": opportunity_id,
        "price_per_sqm": price_per_sqm,
        "gross_rental_yield": gross_yield,
        "market_discount": discount,
        "diligence": {"done": diligence_done, "total": diligence_total},
        "score": min(100, score),
    }
