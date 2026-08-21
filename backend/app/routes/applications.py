"""Candidature locative en ligne, pièces justificatives, OCR et workflow."""

import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.auth import require_read, require_write
from app.config import settings
from app.database import get_db
from app.models.tenant import (
    ApplicationStatus,
    DocumentType,
    Guarantor,
    RentalApplication,
    TenantDocument,
)
from app.schemas.tenant import (
    ApplicationCreate,
    ApplicationStatusUpdate,
    DocumentReview,
    GuarantorCreate,
)
from app.services.ocr_service import analyse_document
from app.services.tenant_service import (
    calculate_application_score,
    create_application,
    document_completeness,
    transition_application,
    verify_tracking_token,
)

router = APIRouter(prefix="/api/applications", tags=["Candidatures locataires"])

ALLOWED_DOCUMENT_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
MAX_DOCUMENT_SIZE = 15 * 1024 * 1024


def _get_application(db: Session, application_id: int) -> RentalApplication:
    application = db.query(RentalApplication).options(
        joinedload(RentalApplication.documents),
        joinedload(RentalApplication.guarantors),
    ).filter(RentalApplication.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Candidature non trouvée")
    return application


def _get_public_application(db: Session, reference: str, token: str) -> RentalApplication:
    application = db.query(RentalApplication).options(
        joinedload(RentalApplication.documents),
        joinedload(RentalApplication.guarantors),
    ).filter(RentalApplication.reference == reference).first()
    if not application or not verify_tracking_token(application, token):
        raise HTTPException(status_code=404, detail="Candidature ou jeton de suivi invalide")
    return application


def _document_view(document: TenantDocument, public_reference: Optional[str] = None) -> dict:
    if public_reference:
        download_url = f"/api/applications/public/{public_reference}/documents/{document.id}/download"
    else:
        download_url = f"/api/applications/{document.application_id}/documents/{document.id}/download"
    return {
        "id": document.id,
        "document_type": document.document_type.value,
        "pay_slip_period": document.pay_slip_period,
        "original_filename": document.original_filename,
        "file_size": document.file_size,
        "mime_type": document.mime_type,
        "verification_status": document.verification_status.value,
        "ocr_confidence": document.ocr_confidence,
        "verification_checks": document.verification_checks or {},
        "rejection_reason": document.rejection_reason,
        "download_url": download_url,
        "uploaded_at": document.uploaded_at,
        "guarantor_id": document.guarantor_id,
    }


def _application_detail(application: RentalApplication, public: bool = False) -> dict:
    result = {
        "id": application.id,
        "reference": application.reference,
        "property_id": application.property_id,
        "tenant_id": application.tenant_id,
        "status": application.status.value,
        "first_name": application.first_name,
        "last_name": application.last_name,
        "email": application.email,
        "phone": application.phone,
        "employment_status": application.employment_status.value,
        "occupation": application.occupation,
        "employer_name": application.employer_name,
        "contract_type": application.contract_type.value if application.contract_type else None,
        "monthly_net_income": application.monthly_net_income,
        "other_monthly_income": application.other_monthly_income,
        "desired_move_in_date": application.desired_move_in_date,
        "solvency_score": application.solvency_score,
        "risk_level": application.risk_level,
        "score_breakdown": application.score_breakdown or {},
        "document_completeness": document_completeness(application),
        "documents": [_document_view(document, application.reference if public else None) for document in application.documents],
        "guarantors": [
            {
                "id": guarantor.id,
                "guarantor_type": guarantor.guarantor_type.value,
                "name": guarantor.company_name or f"{guarantor.first_name or ''} {guarantor.last_name or ''}".strip(),
                "guarantee_scheme": guarantor.guarantee_scheme.value,
                "surety_type": guarantor.surety_type.value,
                "is_verified": guarantor.is_verified,
            }
            for guarantor in application.guarantors
        ],
        "submitted_at": application.submitted_at,
        "reviewed_at": application.reviewed_at,
        "rejection_reason": application.rejection_reason,
    }
    if not public:
        result.update({
            "birth_date": application.birth_date,
            "birth_place": application.birth_place,
            "nationality": application.nationality,
            "address": application.address,
            "postal_code": application.postal_code,
            "city": application.city,
            "country": application.country,
            "employer_address": application.employer_address,
            "employment_start_date": application.employment_start_date,
            "trial_period_end": application.trial_period_end,
            "current_monthly_rent": application.current_monthly_rent,
            "occupants_count": application.occupants_count,
            "notes": application.notes,
            "reviewed_by": application.reviewed_by,
            "status_history": [
                {
                    "previous_status": item.previous_status.value if item.previous_status else None,
                    "new_status": item.new_status.value,
                    "reason": item.reason,
                    "changed_by": item.changed_by,
                    "created_at": item.created_at,
                }
                for item in application.status_history
            ],
        })
    return result


def _validate_file_content(content: bytes, extension: str):
    if extension == "pdf" and not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Le contenu ne correspond pas à un fichier PDF")
    if extension in {"jpg", "jpeg", "png"}:
        try:
            from PIL import Image
            import io

            image = Image.open(io.BytesIO(content))
            image.verify()
            actual = (image.format or "").lower()
            if extension == "png" and actual != "png":
                raise ValueError
            if extension in {"jpg", "jpeg"} and actual != "jpeg":
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400, detail="Le contenu ne correspond pas à une image valide")


async def _save_document(
    db: Session,
    application: RentalApplication,
    file: UploadFile,
    document_type: DocumentType,
    pay_slip_period: Optional[str],
    guarantor_id: Optional[int],
) -> TenantDocument:
    extension = Path(file.filename or "").suffix.lower().lstrip(".")
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Format non autorisé (PDF, JPG, JPEG, PNG)")
    if document_type == DocumentType.PAY_SLIP and pay_slip_period and not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", pay_slip_period):
        raise HTTPException(status_code=400, detail="pay_slip_period doit respecter le format YYYY-MM")
    if guarantor_id and not any(g.id == guarantor_id for g in application.guarantors):
        raise HTTPException(status_code=400, detail="Ce garant n'appartient pas à la candidature")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Le fichier est vide")
    if len(content) > MAX_DOCUMENT_SIZE:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (15 Mo maximum)")
    _validate_file_content(content, extension)

    directory = Path(settings.private_upload_dir_path) / "applications" / str(application.id)
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{extension}"
    file_path = directory / stored_name
    async with aiofiles.open(file_path, "wb") as output:
        await output.write(content)

    analysis = await run_in_threadpool(
        analyse_document,
        str(file_path),
        document_type,
        application.first_name,
        application.last_name,
    )
    document = TenantDocument(
        application_id=application.id,
        guarantor_id=guarantor_id,
        document_type=document_type,
        pay_slip_period=pay_slip_period,
        original_filename=Path(file.filename or "document").name[:255],
        storage_path=str(file_path),
        url=f"/api/applications/{application.id}/documents/pending/download",
        mime_type=file.content_type,
        file_size=len(content),
        file_hash=hashlib.sha256(content).hexdigest(),
        verification_status=analysis["status"],
        ocr_text=analysis["text"],
        ocr_confidence=analysis["confidence"],
        verification_checks={**analysis["checks"], "engine": analysis["engine"]},
        rejection_reason=analysis["reason"],
    )
    db.add(document)
    db.flush()
    document.url = f"/api/applications/{application.id}/documents/{document.id}/download"
    calculate_application_score(db, application, commit=False)
    db.commit()
    db.refresh(document)
    return document


# ---------------------------------------------------------------------------
# Formulaire public et suivi candidat
# ---------------------------------------------------------------------------
@router.post("/", status_code=status.HTTP_201_CREATED)
def submit_application(data: ApplicationCreate, db: Session = Depends(get_db)):
    """Formulaire public de candidature. Le jeton n'est retourné qu'une fois."""
    try:
        application, tracking_token = create_application(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": application.id,
        "reference": application.reference,
        "status": application.status.value,
        "tracking_token": tracking_token,
        "solvency_score": application.solvency_score,
        "message": "Candidature enregistrée. Conservez le jeton de suivi en lieu sûr.",
    }


@router.get("/public/{reference}")
def track_application(
    reference: str,
    x_application_token: str = Header(..., alias="X-Application-Token"),
    db: Session = Depends(get_db),
):
    application = _get_public_application(db, reference, x_application_token)
    result = _application_detail(application, public=True)
    result["notifications"] = [
        {
            "id": item.id,
            "type": item.notification_type,
            "title": item.title,
            "content": item.content,
            "is_read": item.is_read,
            "sent_at": item.sent_at,
        }
        for item in application.notifications
    ]
    return result


@router.post("/public/{reference}/guarantors", status_code=201)
def add_public_guarantor(
    reference: str,
    data: GuarantorCreate,
    x_application_token: str = Header(..., alias="X-Application-Token"),
    db: Session = Depends(get_db),
):
    application = _get_public_application(db, reference, x_application_token)
    if application.status not in (ApplicationStatus.DRAFT, ApplicationStatus.PENDING):
        raise HTTPException(status_code=409, detail="Cette candidature n'est plus modifiable")
    guarantor = Guarantor(application_id=application.id, **data.model_dump())
    db.add(guarantor)
    db.flush()
    calculate_application_score(db, application, commit=False)
    db.commit()
    db.refresh(guarantor)
    return {"id": guarantor.id, "message": "Garant ajouté"}


@router.post("/public/{reference}/documents", status_code=201)
async def upload_public_document(
    reference: str,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    pay_slip_period: Optional[str] = Form(None),
    guarantor_id: Optional[int] = Form(None),
    x_application_token: str = Header(..., alias="X-Application-Token"),
    db: Session = Depends(get_db),
):
    application = _get_public_application(db, reference, x_application_token)
    if application.status not in (ApplicationStatus.DRAFT, ApplicationStatus.PENDING):
        raise HTTPException(status_code=409, detail="Cette candidature n'est plus modifiable")
    document = await _save_document(db, application, file, document_type, pay_slip_period, guarantor_id)
    return _document_view(document, application.reference)


@router.get("/public/{reference}/documents/{document_id}/download")
def download_public_document(
    reference: str,
    document_id: int,
    x_application_token: str = Header(..., alias="X-Application-Token"),
    db: Session = Depends(get_db),
):
    application = _get_public_application(db, reference, x_application_token)
    document = next((item for item in application.documents if item.id == document_id), None)
    if not document or not os.path.isfile(document.storage_path):
        raise HTTPException(status_code=404, detail="Document non trouvé")
    return FileResponse(document.storage_path, media_type=document.mime_type, filename=document.original_filename)


# ---------------------------------------------------------------------------
# Espace gestionnaire
# ---------------------------------------------------------------------------
@router.get("/")
def list_applications(
    search: Optional[str] = Query(None),
    application_status: Optional[ApplicationStatus] = Query(None, alias="status"),
    property_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    query = db.query(RentalApplication)
    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            RentalApplication.reference.ilike(term),
            RentalApplication.first_name.ilike(term),
            RentalApplication.last_name.ilike(term),
            RentalApplication.email.ilike(term),
        ))
    if application_status:
        query = query.filter(RentalApplication.status == application_status)
    if property_id:
        query = query.filter(RentalApplication.property_id == property_id)
    total = query.count()
    applications = query.order_by(RentalApplication.submitted_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {
        "data": [
            {
                "id": item.id,
                "reference": item.reference,
                "property_id": item.property_id,
                "status": item.status.value,
                "candidate_name": f"{item.first_name} {item.last_name}",
                "email": item.email,
                "solvency_score": item.solvency_score,
                "risk_level": item.risk_level,
                "submitted_at": item.submitted_at,
            }
            for item in applications
        ],
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
    }


@router.get("/statistics")
def application_statistics(db: Session = Depends(get_db), current_user=Depends(require_read)):
    counts = {
        status.value: db.query(RentalApplication).filter(RentalApplication.status == status).count()
        for status in ApplicationStatus
    }
    total = sum(counts.values())
    scored = db.query(RentalApplication).filter(RentalApplication.scored_at.isnot(None)).all()
    return {
        "total": total,
        "by_status": counts,
        "average_score": round(sum(item.solvency_score for item in scored) / len(scored), 2) if scored else 0,
        "acceptance_rate": round(counts["accepted"] / total * 100, 2) if total else 0,
    }


@router.get("/{application_id}")
def get_application(application_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    return _application_detail(_get_application(db, application_id))


@router.post("/{application_id}/score")
def rescore_application(application_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    application = _get_application(db, application_id)
    return calculate_application_score(db, application)


@router.put("/{application_id}/status")
def update_application_status(
    application_id: int,
    data: ApplicationStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    application = _get_application(db, application_id)
    try:
        transition_application(
            db,
            application,
            data.status,
            reason=data.reason,
            changed_by=current_user.email,
            force=data.force,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _application_detail(application)


@router.post("/{application_id}/documents", status_code=201)
async def upload_manager_document(
    application_id: int,
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    pay_slip_period: Optional[str] = Form(None),
    guarantor_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    application = _get_application(db, application_id)
    document = await _save_document(db, application, file, document_type, pay_slip_period, guarantor_id)
    return _document_view(document)


@router.put("/{application_id}/documents/{document_id}/review")
def review_document(
    application_id: int,
    document_id: int,
    review: DocumentReview,
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    application = _get_application(db, application_id)
    document = next((item for item in application.documents if item.id == document_id), None)
    if not document:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    document.verification_status = review.verification_status
    document.rejection_reason = review.reason
    document.verified_by = current_user.email
    from datetime import datetime, timezone
    document.verified_at = datetime.now(timezone.utc)
    calculate_application_score(db, application, commit=False)
    db.commit()
    db.refresh(document)
    return _document_view(document)


@router.get("/{application_id}/documents/{document_id}/download")
def download_manager_document(
    application_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    application = _get_application(db, application_id)
    document = next((item for item in application.documents if item.id == document_id), None)
    if not document or not os.path.isfile(document.storage_path):
        raise HTTPException(status_code=404, detail="Document non trouvé")
    return FileResponse(document.storage_path, media_type=document.mime_type, filename=document.original_filename)


@router.delete("/{application_id}/documents/{document_id}")
def delete_document(
    application_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    application = _get_application(db, application_id)
    document = next((item for item in application.documents if item.id == document_id), None)
    if not document:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    if os.path.isfile(document.storage_path):
        os.remove(document.storage_path)
    db.delete(document)
    db.flush()
    calculate_application_score(db, application, commit=False)
    db.commit()
    return {"message": "Document supprimé", "document_id": document_id}
