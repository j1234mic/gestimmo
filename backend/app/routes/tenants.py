"""API de gestion interne des fiches et du suivi locataire."""

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.config import settings
from app.core.tenant_security import hash_portal_password
from app.database import get_db
from app.models.property import Property
from app.models.tenant import (
    DocumentType,
    EmergencyContact,
    Guarantor,
    IncidentStatus,
    Lease,
    LegalCase,
    LegalCaseStatus,
    PaymentStatus,
    RentPayment,
    RentReceipt,
    RentalHistory,
    Tenant,
    TenantAlert,
    TenantDocument,
    TenantIncome,
    TenantIncident,
    TenantInteraction,
    TenantMessage,
    VerificationStatus,
)
from app.schemas.tenant import (
    EmergencyContactCreate,
    GuarantorCreate,
    GuarantorUpdate,
    IncidentCreate,
    IncidentUpdate,
    InteractionCreate,
    LeaseCreate,
    LeaseUpdate,
    LegalCaseCreate,
    LegalCaseUpdate,
    PaymentCreate,
    PaymentUpdate,
    PortalAccessUpdate,
    RentalHistoryCreate,
    TenantCreate,
    TenantIncomeCreate,
    TenantMessageCreate,
    TenantUpdate,
)
from app.services.ocr_service import analyse_document
from app.services.tenant_payment_service import generate_receipt_pdf
from app.services.tenant_service import (
    calculate_reliability_score,
    create_notification,
    create_tenant,
    ensure_receipt,
    generate_reference,
    refresh_late_payment_alerts,
    search_tenants,
)

router = APIRouter(prefix="/api/tenants", tags=["Locataires"])


def _tenant_or_404(db: Session, tenant_id: int) -> Tenant:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.is_active == True).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Locataire non trouvé")
    return tenant


def _enum(value):
    return value.value if hasattr(value, "value") else value


def _guarantor_view(item: Guarantor) -> dict:
    return {
        "id": item.id,
        "guarantor_type": _enum(item.guarantor_type),
        "company_name": item.company_name,
        "first_name": item.first_name,
        "last_name": item.last_name,
        "birth_date": item.birth_date,
        "birth_place": item.birth_place,
        "nationality": item.nationality,
        "email": item.email,
        "phone": item.phone,
        "address": item.address,
        "postal_code": item.postal_code,
        "city": item.city,
        "country": item.country,
        "employment_status": _enum(item.employment_status),
        "occupation": item.occupation,
        "employer_name": item.employer_name,
        "contract_type": _enum(item.contract_type),
        "employment_start_date": item.employment_start_date,
        "monthly_net_income": item.monthly_net_income,
        "other_monthly_income": item.other_monthly_income,
        "surety_type": _enum(item.surety_type),
        "guarantee_scheme": _enum(item.guarantee_scheme),
        "guarantee_reference": item.guarantee_reference,
        "guaranteed_amount": item.guaranteed_amount,
        "guarantee_start_date": item.guarantee_start_date,
        "guarantee_end_date": item.guarantee_end_date,
        "deed_signed_at": item.deed_signed_at,
        "is_verified": item.is_verified,
        "documents": [
            {
                "id": document.id,
                "document_type": _enum(document.document_type),
                "original_filename": document.original_filename,
                "verification_status": _enum(document.verification_status),
                "download_url": f"/api/tenants/{item.tenant_id}/guarantors/{item.id}/documents/{document.id}/download",
            }
            for document in item.documents
        ],
        "notes": item.notes,
    }


def _lease_view(item: Lease) -> dict:
    return {
        "id": item.id,
        "reference": item.reference,
        "property_id": item.property_id,
        "property": {
            "reference": item.property.reference,
            "title": item.property.title,
            "address": item.property.address,
            "postal_code": item.property.postal_code,
            "city": item.property.city,
        } if item.property else None,
        "status": _enum(item.status),
        "start_date": item.start_date,
        "end_date": item.end_date,
        "monthly_rent": item.monthly_rent,
        "monthly_charges": item.monthly_charges,
        "deposit": item.deposit,
        "payment_day": item.payment_day,
        "lease_type": item.lease_type,
        "signed_at": item.signed_at,
        "document_url": f"/api/tenants/{item.tenant_id}/leases/{item.id}/document" if item.document_storage_path else None,
        "notes": item.notes,
    }


def _payment_view(item: RentPayment) -> dict:
    return {
        "id": item.id,
        "reference": item.reference,
        "lease_id": item.lease_id,
        "period": item.period,
        "due_date": item.due_date,
        "amount_due": item.amount_due,
        "amount_paid": item.amount_paid,
        "remaining_amount": round(max(0, item.amount_due - item.amount_paid), 2),
        "status": _enum(item.status),
        "paid_at": item.paid_at,
        "payment_method": item.payment_method,
        "external_reference": item.external_reference,
        "receipt": {
            "id": item.receipt.id,
            "reference": item.receipt.reference,
            "download_url": f"/api/tenants/{item.tenant_id}/receipts/{item.receipt.id}/download",
        } if item.receipt else None,
    }


def _tenant_summary(item: Tenant) -> dict:
    active_lease = next((lease for lease in item.leases if _enum(lease.status) == "active"), None)
    return {
        "id": item.id,
        "reference": item.reference,
        "status": _enum(item.status),
        "first_name": item.first_name,
        "last_name": item.last_name,
        "email": item.email,
        "phone": item.phone,
        "city": item.city,
        "solvency_score": item.solvency_score,
        "reliability_score": item.reliability_score,
        "portal_enabled": item.portal_enabled,
        "active_lease": _lease_view(active_lease) if active_lease else None,
        "created_at": item.created_at,
    }


def _tenant_detail(item: Tenant) -> dict:
    result = _tenant_summary(item)
    result.update({
        "birth_date": item.birth_date,
        "birth_place": item.birth_place,
        "nationality": item.nationality,
        "mobile": item.mobile,
        "address": item.address,
        "postal_code": item.postal_code,
        "country": item.country,
        "employment_status": _enum(item.employment_status),
        "occupation": item.occupation,
        "employer_name": item.employer_name,
        "employer_address": item.employer_address,
        "contract_type": _enum(item.contract_type),
        "employment_start_date": item.employment_start_date,
        "trial_period_end": item.trial_period_end,
        "monthly_net_income": item.monthly_net_income,
        "other_monthly_income": item.other_monthly_income,
        "score_breakdown": item.score_breakdown or {},
        "score_updated_at": item.score_updated_at,
        "notes": item.notes,
        "tags": item.tags or [],
        "application_id": item.application.id if item.application else None,
        "incomes": [
            {
                "id": income.id,
                "income_type": _enum(income.income_type),
                "label": income.label,
                "monthly_amount": income.monthly_amount,
                "payer": income.payer,
                "start_date": income.start_date,
                "end_date": income.end_date,
                "is_verified": income.is_verified,
            }
            for income in item.incomes
        ],
        "emergency_contacts": [
            {
                "id": contact.id,
                "first_name": contact.first_name,
                "last_name": contact.last_name,
                "relationship": contact.relationship,
                "phone": contact.phone,
                "email": contact.email,
                "is_primary": contact.is_primary,
            }
            for contact in item.emergency_contacts
        ],
        "rental_history": [
            {
                "id": history.id,
                "address": history.address,
                "city": history.city,
                "landlord_name": history.landlord_name,
                "landlord_phone": history.landlord_phone,
                "start_date": history.start_date,
                "end_date": history.end_date,
                "monthly_rent": history.monthly_rent,
                "departure_reason": history.departure_reason,
                "payment_incidents": history.payment_incidents,
                "reference_checked": history.reference_checked,
            }
            for history in item.rental_history
        ],
        "guarantors": [_guarantor_view(guarantor) for guarantor in item.guarantors],
        "leases": [_lease_view(lease) for lease in item.leases],
        "documents": [
            {
                "id": document.id,
                "document_type": _enum(document.document_type),
                "original_filename": document.original_filename,
                "verification_status": _enum(document.verification_status),
                "application_id": document.application_id,
            }
            for document in item.documents
        ],
        "open_incidents": sum(incident.status in (IncidentStatus.OPEN, IncidentStatus.IN_PROGRESS) for incident in item.incidents),
        "active_alerts": sum(alert.is_active for alert in item.alerts),
        "active_legal_cases": sum(case.status != LegalCaseStatus.CLOSED for case in item.legal_cases),
    })
    return result


# Routes fixes avant /{tenant_id}
@router.get("/statistics")
def tenant_statistics(db: Session = Depends(get_db), current_user=Depends(require_read)):
    tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
    return {
        "total": len(tenants),
        "by_status": {
            status: sum(_enum(tenant.status) == status for tenant in tenants)
            for status in ("candidate", "active", "notice", "left", "suspended")
        },
        "average_solvency_score": round(sum(t.solvency_score for t in tenants) / len(tenants), 2) if tenants else 0,
        "average_reliability_score": round(sum(t.reliability_score for t in tenants) / len(tenants), 2) if tenants else 0,
        "portal_activation_rate": round(sum(t.portal_enabled for t in tenants) / len(tenants) * 100, 2) if tenants else 0,
    }


@router.get("/alerts/late-payments")
def late_payment_alerts(db: Session = Depends(get_db), current_user=Depends(require_read)):
    alerts = refresh_late_payment_alerts(db)
    return {
        "data": [
            {
                "id": alert.id,
                "tenant_id": alert.tenant_id,
                "tenant_name": f"{alert.tenant.first_name} {alert.tenant.last_name}",
                "severity": alert.severity,
                "title": alert.title,
                "content": alert.content,
                "payment_id": alert.related_entity_id,
                "created_at": alert.created_at,
            }
            for alert in alerts
        ],
        "total": len(alerts),
    }


@router.get("/")
def list_tenants(
    search: Optional[str] = Query(None),
    tenant_status: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    tenants, total = search_tenants(db, search, tenant_status, (page - 1) * limit, limit)
    return {
        "data": [_tenant_summary(tenant) for tenant in tenants],
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
    }


@router.post("/", status_code=201)
def create_new_tenant(data: TenantCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    return _tenant_detail(create_tenant(db, data))


@router.get("/{tenant_id}")
def get_tenant(tenant_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    return _tenant_detail(_tenant_or_404(db, tenant_id))


@router.put("/{tenant_id}")
def update_tenant(
    tenant_id: int,
    data: TenantUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    tenant = _tenant_or_404(db, tenant_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)
    db.commit()
    db.refresh(tenant)
    return _tenant_detail(tenant)


@router.delete("/{tenant_id}")
def delete_tenant(tenant_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    tenant.is_active = False
    tenant.portal_enabled = False
    db.commit()
    return {"message": "Locataire archivé", "tenant_id": tenant_id}


@router.post("/{tenant_id}/incomes", status_code=201)
def add_income(tenant_id: int, data: TenantIncomeCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    income = TenantIncome(tenant_id=tenant.id, **data.model_dump())
    db.add(income)
    db.commit()
    db.refresh(income)
    return {"id": income.id, **data.model_dump()}


@router.delete("/{tenant_id}/incomes/{income_id}")
def delete_income(tenant_id: int, income_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _tenant_or_404(db, tenant_id)
    income = db.query(TenantIncome).filter(TenantIncome.id == income_id, TenantIncome.tenant_id == tenant_id).first()
    if not income:
        raise HTTPException(status_code=404, detail="Revenu non trouvé")
    db.delete(income)
    db.commit()
    return {"message": "Revenu supprimé"}


@router.post("/{tenant_id}/emergency-contacts", status_code=201)
def add_emergency_contact(tenant_id: int, data: EmergencyContactCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    if data.is_primary:
        db.query(EmergencyContact).filter(EmergencyContact.tenant_id == tenant.id).update({"is_primary": False})
    contact = EmergencyContact(tenant_id=tenant.id, **data.model_dump())
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return {"id": contact.id, **data.model_dump()}


@router.delete("/{tenant_id}/emergency-contacts/{contact_id}")
def delete_emergency_contact(tenant_id: int, contact_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _tenant_or_404(db, tenant_id)
    contact = db.query(EmergencyContact).filter(EmergencyContact.id == contact_id, EmergencyContact.tenant_id == tenant_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact non trouvé")
    db.delete(contact)
    db.commit()
    return {"message": "Contact supprimé"}


@router.post("/{tenant_id}/rental-history", status_code=201)
def add_rental_history(tenant_id: int, data: RentalHistoryCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    history = RentalHistory(tenant_id=tenant.id, **data.model_dump())
    db.add(history)
    db.commit()
    db.refresh(history)
    return {"id": history.id, **data.model_dump()}


@router.delete("/{tenant_id}/rental-history/{history_id}")
def delete_rental_history(tenant_id: int, history_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _tenant_or_404(db, tenant_id)
    history = db.query(RentalHistory).filter(RentalHistory.id == history_id, RentalHistory.tenant_id == tenant_id).first()
    if not history:
        raise HTTPException(status_code=404, detail="Historique non trouvé")
    db.delete(history)
    db.commit()
    return {"message": "Historique supprimé"}


@router.post("/{tenant_id}/guarantors", status_code=201)
def add_guarantor(tenant_id: int, data: GuarantorCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    guarantor = Guarantor(tenant_id=tenant.id, **data.model_dump())
    db.add(guarantor)
    db.commit()
    db.refresh(guarantor)
    return _guarantor_view(guarantor)


@router.put("/{tenant_id}/guarantors/{guarantor_id}")
def update_guarantor(tenant_id: int, guarantor_id: int, data: GuarantorUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _tenant_or_404(db, tenant_id)
    guarantor = db.query(Guarantor).filter(Guarantor.id == guarantor_id, Guarantor.tenant_id == tenant_id).first()
    if not guarantor:
        raise HTTPException(status_code=404, detail="Garant non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(guarantor, field, value)
    db.commit()
    db.refresh(guarantor)
    return _guarantor_view(guarantor)


@router.post("/{tenant_id}/guarantors/{guarantor_id}/documents", status_code=201)
async def upload_guarantor_document(
    tenant_id: int,
    guarantor_id: int,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(DocumentType.GUARANTEE_DEED),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    tenant = _tenant_or_404(db, tenant_id)
    guarantor = db.query(Guarantor).filter(Guarantor.id == guarantor_id, Guarantor.tenant_id == tenant.id).first()
    if not guarantor:
        raise HTTPException(status_code=404, detail="Garant non trouvé")
    extension = Path(file.filename or "").suffix.lower().lstrip(".")
    if extension not in {"pdf", "jpg", "jpeg", "png"}:
        raise HTTPException(status_code=400, detail="Format non autorisé")
    content = await file.read()
    if not content or len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier vide ou supérieur à 15 Mo")
    directory = Path(settings.private_upload_dir_path) / "tenants" / str(tenant.id) / "guarantors"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.{extension}"
    async with aiofiles.open(path, "wb") as output:
        await output.write(content)
    analysis = await run_in_threadpool(analyse_document, str(path), document_type, guarantor.first_name, guarantor.last_name)
    document = TenantDocument(
        tenant_id=tenant.id,
        guarantor_id=guarantor.id,
        document_type=document_type,
        original_filename=Path(file.filename or "document").name,
        storage_path=str(path),
        url="private",
        mime_type=file.content_type,
        file_size=len(content),
        file_hash=hashlib.sha256(content).hexdigest(),
        verification_status=analysis["status"],
        ocr_text=analysis["text"],
        ocr_confidence=analysis["confidence"],
        verification_checks=analysis["checks"],
        rejection_reason=analysis["reason"],
    )
    db.add(document)
    if document_type == DocumentType.GUARANTEE_DEED and analysis["status"] == VerificationStatus.VERIFIED:
        guarantor.deed_signed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(document)
    return {
        "id": document.id,
        "document_type": document.document_type.value,
        "verification_status": document.verification_status.value,
        "ocr_confidence": document.ocr_confidence,
        "verification_checks": document.verification_checks,
        "download_url": f"/api/tenants/{tenant.id}/guarantors/{guarantor.id}/documents/{document.id}/download",
    }


@router.get("/{tenant_id}/guarantors/{guarantor_id}/documents/{document_id}/download")
def download_guarantor_document(tenant_id: int, guarantor_id: int, document_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _tenant_or_404(db, tenant_id)
    document = db.query(TenantDocument).filter(
        TenantDocument.id == document_id,
        TenantDocument.tenant_id == tenant_id,
        TenantDocument.guarantor_id == guarantor_id,
    ).first()
    if not document or not os.path.isfile(document.storage_path):
        raise HTTPException(status_code=404, detail="Document non trouvé")
    return FileResponse(document.storage_path, media_type=document.mime_type, filename=document.original_filename)


@router.post("/{tenant_id}/leases", status_code=201)
def create_lease(tenant_id: int, data: LeaseCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    if not db.query(Property).filter(Property.id == data.property_id, Property.is_active == True).first():
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    lease = Lease(tenant_id=tenant.id, reference=generate_reference("LEA"), **data.model_dump())
    db.add(lease)
    db.commit()
    db.refresh(lease)
    return _lease_view(lease)


@router.put("/{tenant_id}/leases/{lease_id}")
def update_lease(tenant_id: int, lease_id: int, data: LeaseUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _tenant_or_404(db, tenant_id)
    lease = db.query(Lease).filter(Lease.id == lease_id, Lease.tenant_id == tenant_id).first()
    if not lease:
        raise HTTPException(status_code=404, detail="Bail non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(lease, field, value)
    db.commit()
    db.refresh(lease)
    return _lease_view(lease)


@router.post("/{tenant_id}/leases/{lease_id}/document")
async def upload_lease_document(tenant_id: int, lease_id: int, file: UploadFile = File(...), db: Session = Depends(get_db), current_user=Depends(require_write)):
    _tenant_or_404(db, tenant_id)
    lease = db.query(Lease).filter(Lease.id == lease_id, Lease.tenant_id == tenant_id).first()
    if not lease:
        raise HTTPException(status_code=404, detail="Bail non trouvé")
    content = await file.read()
    if not file.filename.lower().endswith(".pdf") or not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Le bail doit être un fichier PDF valide")
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Fichier supérieur à 20 Mo")
    directory = Path(settings.private_upload_dir_path) / "tenants" / str(tenant_id) / "leases"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.pdf"
    async with aiofiles.open(path, "wb") as output:
        await output.write(content)
    if lease.document_storage_path and os.path.isfile(lease.document_storage_path):
        os.remove(lease.document_storage_path)
    lease.document_storage_path = str(path)
    lease.document_url = f"/api/tenants/{tenant_id}/leases/{lease.id}/document"
    db.commit()
    return {"message": "Bail enregistré", "document_url": lease.document_url}


@router.get("/{tenant_id}/leases/{lease_id}/document")
def download_lease_document(tenant_id: int, lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _tenant_or_404(db, tenant_id)
    lease = db.query(Lease).filter(Lease.id == lease_id, Lease.tenant_id == tenant_id).first()
    if not lease or not lease.document_storage_path or not os.path.isfile(lease.document_storage_path):
        raise HTTPException(status_code=404, detail="Document de bail non trouvé")
    return FileResponse(lease.document_storage_path, media_type="application/pdf", filename=f"bail-{lease.reference}.pdf")


@router.post("/{tenant_id}/payments", status_code=201)
def create_payment(tenant_id: int, data: PaymentCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    lease = db.query(Lease).filter(Lease.id == data.lease_id, Lease.tenant_id == tenant.id).first()
    if not lease:
        raise HTTPException(status_code=404, detail="Bail non trouvé pour ce locataire")
    payment = RentPayment(tenant_id=tenant.id, reference=generate_reference("PAY"), **data.model_dump())
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Un appel de loyer existe déjà pour ce bail et cette période")
    db.refresh(payment)
    return _payment_view(payment)


@router.get("/{tenant_id}/payments")
def list_payments(tenant_id: int, payment_status: Optional[PaymentStatus] = Query(None, alias="status"), db: Session = Depends(get_db), current_user=Depends(require_read)):
    _tenant_or_404(db, tenant_id)
    query = db.query(RentPayment).filter(RentPayment.tenant_id == tenant_id)
    if payment_status:
        query = query.filter(RentPayment.status == payment_status)
    return [_payment_view(payment) for payment in query.order_by(RentPayment.due_date.desc()).all()]


@router.put("/{tenant_id}/payments/{payment_id}")
def register_payment(tenant_id: int, payment_id: int, data: PaymentUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    payment = db.query(RentPayment).filter(RentPayment.id == payment_id, RentPayment.tenant_id == tenant.id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Paiement non trouvé")
    payment.amount_paid = min(data.amount_paid, payment.amount_due)
    payment.paid_at = data.paid_at or (datetime.now(timezone.utc) if payment.amount_paid else None)
    payment.payment_method = data.payment_method
    payment.external_reference = data.external_reference
    payment.notes = data.notes
    if payment.amount_paid >= payment.amount_due:
        payment.status = PaymentStatus.PAID
    elif payment.amount_paid > 0:
        payment.status = PaymentStatus.PARTIAL if payment.due_date >= datetime.now().date() else PaymentStatus.OVERDUE
    else:
        payment.status = PaymentStatus.DUE if payment.due_date >= datetime.now().date() else PaymentStatus.OVERDUE
    ensure_receipt(db, payment)
    alert = db.query(TenantAlert).filter(TenantAlert.alert_type == "late_payment", TenantAlert.related_entity_id == payment.id).first()
    if alert and payment.status == PaymentStatus.PAID:
        alert.is_active = False
    calculate_reliability_score(db, tenant, commit=False)
    db.commit()
    db.refresh(payment)
    return _payment_view(payment)


@router.get("/{tenant_id}/receipts/{receipt_id}/download")
def download_receipt(tenant_id: int, receipt_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _tenant_or_404(db, tenant_id)
    receipt = db.query(RentReceipt).filter(RentReceipt.id == receipt_id, RentReceipt.tenant_id == tenant_id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Quittance non trouvée")
    return StreamingResponse(
        generate_receipt_pdf(receipt),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="quittance-{receipt.period}.pdf"'},
    )


@router.get("/{tenant_id}/incidents")
def list_incidents(tenant_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _tenant_or_404(db, tenant_id)
    return db.query(TenantIncident).filter(TenantIncident.tenant_id == tenant_id).order_by(TenantIncident.reported_at.desc()).all()


@router.post("/{tenant_id}/incidents", status_code=201)
def create_incident(tenant_id: int, data: IncidentCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    if data.lease_id and not db.query(Lease).filter(Lease.id == data.lease_id, Lease.tenant_id == tenant.id).first():
        raise HTTPException(status_code=400, detail="Bail invalide")
    incident = TenantIncident(tenant_id=tenant.id, reference=generate_reference("INC"), **data.model_dump())
    db.add(incident)
    db.add(TenantInteraction(
        tenant_id=tenant.id,
        interaction_type="incident",
        direction="incoming",
        subject=data.title,
        content=data.description,
        actor=current_user.email,
    ))
    calculate_reliability_score(db, tenant, commit=False)
    db.commit()
    db.refresh(incident)
    return incident


@router.put("/{tenant_id}/incidents/{incident_id}")
def update_incident(tenant_id: int, incident_id: int, data: IncidentUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    incident = db.query(TenantIncident).filter(TenantIncident.id == incident_id, TenantIncident.tenant_id == tenant.id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(incident, field, value)
    if incident.status in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
        incident.resolved_at = datetime.now(timezone.utc)
    calculate_reliability_score(db, tenant, commit=False)
    db.commit()
    db.refresh(incident)
    return incident


@router.get("/{tenant_id}/messages")
def list_messages(tenant_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _tenant_or_404(db, tenant_id)
    return db.query(TenantMessage).filter(TenantMessage.tenant_id == tenant_id).order_by(TenantMessage.created_at.desc()).all()


@router.post("/{tenant_id}/messages", status_code=201)
def send_manager_message(tenant_id: int, data: TenantMessageCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    message = TenantMessage(tenant_id=tenant.id, sender_type="manager", sender_name=current_user.full_name, **data.model_dump())
    db.add(message)
    db.add(TenantInteraction(
        tenant_id=tenant.id,
        interaction_type="message",
        direction="outgoing",
        subject=data.subject,
        content=data.content,
        actor=current_user.email,
    ))
    create_notification(db, tenant_id=tenant.id, notification_type="message", title=data.subject or "Nouveau message", content=data.content[:500])
    db.commit()
    db.refresh(message)
    return message


@router.get("/{tenant_id}/interactions")
def list_interactions(tenant_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _tenant_or_404(db, tenant_id)
    return db.query(TenantInteraction).filter(TenantInteraction.tenant_id == tenant_id).order_by(TenantInteraction.occurred_at.desc()).all()


@router.post("/{tenant_id}/interactions", status_code=201)
def add_interaction(tenant_id: int, data: InteractionCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    interaction = TenantInteraction(tenant_id=tenant.id, actor=current_user.email, **data.model_dump())
    db.add(interaction)
    db.commit()
    db.refresh(interaction)
    return interaction


@router.get("/{tenant_id}/legal-cases")
def list_legal_cases(tenant_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _tenant_or_404(db, tenant_id)
    return db.query(LegalCase).filter(LegalCase.tenant_id == tenant_id).order_by(LegalCase.opened_at.desc()).all()


@router.post("/{tenant_id}/legal-cases", status_code=201)
def create_legal_case(tenant_id: int, data: LegalCaseCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    if data.lease_id and not db.query(Lease).filter(Lease.id == data.lease_id, Lease.tenant_id == tenant.id).first():
        raise HTTPException(status_code=400, detail="Bail invalide")
    case = LegalCase(tenant_id=tenant.id, reference=generate_reference("LIT"), **data.model_dump())
    db.add(case)
    calculate_reliability_score(db, tenant, commit=False)
    db.commit()
    db.refresh(case)
    return case


@router.put("/{tenant_id}/legal-cases/{case_id}")
def update_legal_case(tenant_id: int, case_id: int, data: LegalCaseUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    case = db.query(LegalCase).filter(LegalCase.id == case_id, LegalCase.tenant_id == tenant.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Dossier contentieux non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(case, field, value)
    calculate_reliability_score(db, tenant, commit=False)
    db.commit()
    db.refresh(case)
    return case


@router.post("/{tenant_id}/score/recalculate")
def recalculate_score(tenant_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    return calculate_reliability_score(db, _tenant_or_404(db, tenant_id))


@router.put("/{tenant_id}/portal-access")
def update_portal_access(tenant_id: int, data: PortalAccessUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    tenant = _tenant_or_404(db, tenant_id)
    if data.enabled and not tenant.portal_password_hash and not data.temporary_password:
        raise HTTPException(status_code=400, detail="Un mot de passe temporaire est requis pour la première activation")
    if data.temporary_password:
        tenant.portal_password_hash = hash_portal_password(data.temporary_password)
    tenant.portal_enabled = data.enabled
    db.commit()
    return {"tenant_id": tenant.id, "portal_enabled": tenant.portal_enabled}


@router.put("/{tenant_id}/alerts/{alert_id}/acknowledge")
def acknowledge_alert(tenant_id: int, alert_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _tenant_or_404(db, tenant_id)
    alert = db.query(TenantAlert).filter(TenantAlert.id == alert_id, TenantAlert.tenant_id == tenant_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte non trouvée")
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Alerte acquittée", "alert_id": alert.id}
