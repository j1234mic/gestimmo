"""API du module 4 : création, documents, révisions et cycle de vie des baux."""

import hashlib
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.config import settings
from app.database import get_db
from app.models.lease_contract import (
    ArchiveStatus,
    ContractDocument,
    ContractDocumentType,
    ContractEvent,
    LeaseAmendment,
    LeaseClause,
    LeaseClauseAssignment,
    LeaseContractSettings,
    LeaseNotice,
    LeaseRenewal,
    LeaseTemplate,
    LeaseTemplateClause,
    NoticeStatus,
    RenewalMode,
    RenewalStatus,
    RentCapRule,
    RentIndexValue,
    RentRevision,
    RevisionStatus,
    SignatureEnvelope,
    SignatureEnvelopeStatus,
    SignaturePartyStatus,
)
from app.models.property import PropertyStatus
from app.models.tenant import Lease, LeaseStatus, TenantStatus
from app.schemas.lease_contract import (
    AmendmentCreate,
    ClauseAssignmentCreate,
    DocumentArchiveInput,
    LeaseClauseCreate,
    LeaseContractCreate,
    LeaseContractUpdate,
    LeaseTemplateCreate,
    NoticeCreate,
    NoticeStatusUpdate,
    PublicSignatureInput,
    RenewalCreate,
    RentCapRuleCreate,
    RentIndexValueCreate,
    RentRevisionCreate,
    SignatureDeclineInput,
    SignatureEnvelopeCreate,
)
from app.services.lease_service import (
    annex_completeness,
    apply_rent_revision,
    calculate_rent_revision,
    create_amendment,
    create_contract_lease,
    create_notice,
    create_signature_envelope,
    find_signature_party,
    generate_and_store_lease,
    generate_notice_pdf_bytes,
    generate_reference,
    log_event,
    notify_tenant,
    process_renewal,
    renewal_alerts,
    store_contract_document,
    complete_signature,
)

router = APIRouter(prefix="/api/leases", tags=["Baux et contrats"])
signature_router = APIRouter(prefix="/api/lease-signatures", tags=["Signature électronique des baux"])


def _lease_or_404(db: Session, lease_id: int) -> Lease:
    lease = db.query(Lease).filter(Lease.id == lease_id).first()
    if not lease:
        raise HTTPException(status_code=404, detail="Bail non trouvé")
    return lease


def _settings_or_404(db: Session, lease_id: int) -> LeaseContractSettings:
    row = db.query(LeaseContractSettings).filter(LeaseContractSettings.lease_id == lease_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Ce bail ne dispose pas des paramètres du module contrats")
    return row


def _document_integrity_ok(document: ContractDocument) -> bool:
    if not os.path.isfile(document.storage_path):
        return False
    digest = hashlib.sha256()
    with open(document.storage_path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == document.checksum_sha256


def _document_view(document: ContractDocument) -> dict:
    return {
        "id": document.id,
        "reference": document.reference,
        "document_type": document.document_type.value,
        "title": document.title,
        "original_filename": document.original_filename,
        "mime_type": document.mime_type,
        "file_size": document.file_size,
        "checksum_sha256": document.checksum_sha256,
        "version": document.version,
        "is_required": document.is_required,
        "archive_status": document.archive_status.value,
        "archived_at": document.archived_at,
        "retention_until": document.retention_until,
        "legal_hold": document.legal_hold,
        "signed_at": document.signed_at,
        "created_at": document.created_at,
        "download_url": f"/api/leases/{document.lease_id}/documents/{document.id}/download",
    }


def _lease_view(lease: Lease, detail: bool = False) -> dict:
    contract = next((item for item in [getattr(lease, "_contract_settings", None)] if item), None)
    if not contract:
        # La relation n'est volontairement pas ajoutée au modèle historique Lease.
        from sqlalchemy.orm import object_session
        session = object_session(lease)
        contract = session.query(LeaseContractSettings).filter(LeaseContractSettings.lease_id == lease.id).first() if session else None
    result = {
        "id": lease.id,
        "reference": lease.reference,
        "tenant_id": lease.tenant_id,
        "tenant": {
            "reference": lease.tenant.reference,
            "name": f"{lease.tenant.first_name} {lease.tenant.last_name}",
            "email": lease.tenant.email,
        },
        "property_id": lease.property_id,
        "property": {
            "reference": lease.property.reference,
            "title": lease.property.title,
            "address": lease.property.address,
            "postal_code": lease.property.postal_code,
            "city": lease.property.city,
        },
        "lease_type": contract.lease_type.value if contract else lease.lease_type,
        "status": lease.status.value,
        "start_date": lease.start_date,
        "end_date": lease.end_date,
        "rent_excluding_charges": lease.monthly_rent,
        "charges": lease.monthly_charges,
        "deposit": lease.deposit,
        "payment_day": lease.payment_day,
        "signed_at": lease.signed_at,
        "document_url": lease.document_url,
    }
    if detail and contract:
        result["parameters"] = {
            "duration_months": contract.duration_months,
            "tacit_renewal": contract.tacit_renewal,
            "renewal_notice_months": contract.renewal_notice_months,
            "charge_method": contract.charge_method.value,
            "rent_frequency": contract.rent_frequency.value,
            "payment_method": contract.payment_method,
            "rent_index_type": contract.rent_index_type.value,
            "base_index_value": contract.base_index_value,
            "base_index_date": contract.base_index_date,
            "next_revision_date": contract.next_revision_date,
            "resolutory_clause": contract.resolutory_clause,
            "resolutory_clause_text": contract.resolutory_clause_text,
            "special_conditions": contract.special_conditions,
            "custom_variables": contract.custom_variables or {},
            "contract_version": contract.contract_version,
            "template_id": contract.template_id,
            "signature_status": contract.signature_status,
        }
        result["clauses"] = [
            {
                "id": item.id,
                "clause_id": item.clause_id,
                "title": item.title,
                "content": item.content,
                "display_order": item.display_order,
                "is_required": item.is_required,
                "source": item.source,
            }
            for item in sorted(contract.clause_assignments, key=lambda value: value.display_order)
        ]
    return result


# ---------------------------------------------------------------------------
# Bibliothèque de modèles, clauses, indices et règles légales
# ---------------------------------------------------------------------------
@router.get("/types")
def lease_types():
    return {
        "types": [
            {"value": "residential_unfurnished", "label": "Bail d'habitation vide"},
            {"value": "residential_furnished", "label": "Bail d'habitation meublé"},
            {"value": "commercial_369", "label": "Bail commercial 3/6/9"},
            {"value": "professional", "label": "Bail professionnel"},
            {"value": "short_term_derogatory", "label": "Bail précaire / dérogatoire"},
            {"value": "seasonal", "label": "Bail saisonnier"},
            {"value": "precarious_occupancy", "label": "Convention d'occupation précaire"},
            {"value": "mixed_use", "label": "Bail mixte"},
        ]
    }


@router.post("/clauses", status_code=201)
def create_clause(data: LeaseClauseCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    clause = LeaseClause(
        **data.model_dump(exclude={"compatible_lease_types"}),
        compatible_lease_types=[item.value for item in data.compatible_lease_types],
    )
    db.add(clause)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ce code de clause existe déjà")
    db.refresh(clause)
    return {
        "id": clause.id,
        "code": clause.code,
        "title": clause.title,
        "content_template": clause.content_template,
        "compatible_lease_types": clause.compatible_lease_types,
        "category": clause.category,
        "is_mandatory": clause.is_mandatory,
        "version": clause.version,
    }


@router.get("/clauses")
def list_clauses(lease_type: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    clauses = db.query(LeaseClause).filter(LeaseClause.is_active.is_(True)).order_by(LeaseClause.category, LeaseClause.title).all()
    if lease_type:
        clauses = [item for item in clauses if not item.compatible_lease_types or lease_type in item.compatible_lease_types]
    return [
        {
            "id": item.id,
            "code": item.code,
            "title": item.title,
            "content_template": item.content_template,
            "compatible_lease_types": item.compatible_lease_types or [],
            "category": item.category,
            "is_mandatory": item.is_mandatory,
            "version": item.version,
        }
        for item in clauses
    ]


@router.post("/templates", status_code=201)
def create_template(data: LeaseTemplateCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    clauses = []
    if data.clause_ids:
        clauses = db.query(LeaseClause).filter(LeaseClause.id.in_(data.clause_ids), LeaseClause.is_active.is_(True)).all()
        if len(clauses) != len(set(data.clause_ids)):
            raise HTTPException(status_code=400, detail="Une ou plusieurs clauses sont invalides")
    if data.is_default:
        db.query(LeaseTemplate).filter(LeaseTemplate.lease_type == data.lease_type).update({"is_default": False})
    template = LeaseTemplate(
        **data.model_dump(exclude={"clause_ids"}),
        created_by=current_user.email,
    )
    db.add(template)
    db.flush()
    for order, clause in enumerate(clauses):
        db.add(LeaseTemplateClause(
            template_id=template.id,
            clause_id=clause.id,
            display_order=order,
            is_required=clause.is_mandatory,
        ))
    db.commit()
    db.refresh(template)
    return {"id": template.id, "name": template.name, "lease_type": template.lease_type.value, "version": template.version, "is_default": template.is_default}


@router.get("/templates")
def list_templates(lease_type: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    query = db.query(LeaseTemplate).filter(LeaseTemplate.is_active.is_(True))
    if lease_type:
        query = query.filter(LeaseTemplate.lease_type == lease_type)
    return [
        {
            "id": item.id,
            "name": item.name,
            "lease_type": item.lease_type.value,
            "description": item.description,
            "version": item.version,
            "is_default": item.is_default,
            "clause_ids": [link.clause_id for link in item.clauses],
        }
        for item in query.order_by(LeaseTemplate.lease_type, LeaseTemplate.name).all()
    ]


@router.put("/templates/{template_id}", status_code=201)
def version_template(template_id: int, data: LeaseTemplateCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    previous = db.query(LeaseTemplate).filter(LeaseTemplate.id == template_id).first()
    if not previous:
        raise HTTPException(status_code=404, detail="Modèle non trouvé")
    clauses = db.query(LeaseClause).filter(LeaseClause.id.in_(data.clause_ids), LeaseClause.is_active.is_(True)).all() if data.clause_ids else []
    if len(clauses) != len(set(data.clause_ids)):
        raise HTTPException(status_code=400, detail="Une ou plusieurs clauses sont invalides")
    previous.is_active = False
    previous.is_default = False
    if data.is_default:
        db.query(LeaseTemplate).filter(LeaseTemplate.lease_type == data.lease_type).update({"is_default": False})
    template = LeaseTemplate(
        **data.model_dump(exclude={"clause_ids"}),
        version=previous.version + 1,
        created_by=current_user.email,
    )
    db.add(template)
    db.flush()
    for order, clause in enumerate(clauses):
        db.add(LeaseTemplateClause(template_id=template.id, clause_id=clause.id, display_order=order, is_required=clause.is_mandatory))
    db.commit()
    db.refresh(template)
    return {"id": template.id, "replaces_template_id": previous.id, "name": template.name, "lease_type": template.lease_type.value, "version": template.version, "is_default": template.is_default}


@router.put("/clauses/{clause_id}")
def update_clause(clause_id: int, data: LeaseClauseCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    clause = db.query(LeaseClause).filter(LeaseClause.id == clause_id).first()
    if not clause:
        raise HTTPException(status_code=404, detail="Clause non trouvée")
    duplicate = db.query(LeaseClause).filter(LeaseClause.code == data.code, LeaseClause.id != clause.id).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Ce code de clause existe déjà")
    payload = data.model_dump(exclude={"compatible_lease_types"})
    for field, value in payload.items():
        setattr(clause, field, value)
    clause.compatible_lease_types = [item.value for item in data.compatible_lease_types]
    clause.version += 1
    db.commit()
    db.refresh(clause)
    return {"id": clause.id, "code": clause.code, "title": clause.title, "version": clause.version}


@router.post("/indices", status_code=201)
def create_index(data: RentIndexValueCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    item = RentIndexValue(**data.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Cet indice existe déjà pour cette période et cette zone")
    db.refresh(item)
    return item


@router.get("/indices")
def list_indices(index_type: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    query = db.query(RentIndexValue)
    if index_type:
        query = query.filter(RentIndexValue.index_type == index_type)
    return query.order_by(RentIndexValue.publication_date.desc()).all()


@router.post("/cap-rules", status_code=201)
def create_cap_rule(data: RentCapRuleCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    rule = RentCapRule(**data.model_dump())
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/cap-rules")
def list_cap_rules(active_only: bool = True, db: Session = Depends(get_db), current_user=Depends(require_read)):
    query = db.query(RentCapRule)
    if active_only:
        query = query.filter(RentCapRule.is_active.is_(True))
    return query.order_by(RentCapRule.valid_from.desc()).all()


@router.get("/renewal-alerts")
def get_renewal_alerts(months: Optional[int] = Query(None, ge=1, le=24), db: Session = Depends(get_db), current_user=Depends(require_read)):
    return {"data": renewal_alerts(db, months)}


@router.post("/scheduled-revisions/process")
def process_scheduled_revisions(
    as_of: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    """Applique de façon idempotente les révisions arrivées à leur date d'effet."""
    processing_date = as_of or date.today()
    revisions = db.query(RentRevision).filter(
        RentRevision.status == RevisionStatus.SCHEDULED,
        RentRevision.effective_date <= processing_date,
    ).order_by(RentRevision.effective_date).all()
    processed = []
    for revision in revisions:
        apply_rent_revision(db, revision, current_user.email)
        processed.append({"revision_id": revision.id, "lease_id": revision.lease_id, "applied_rent": revision.applied_rent})
    return {"as_of": processing_date, "processed": processed, "count": len(processed)}


@router.post("/automatic-renewals/process")
def process_automatic_renewals(
    as_of: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    """Point d'entrée idempotent destiné au planificateur quotidien."""
    processing_date = as_of or date.today()
    due_leases = db.query(Lease).join(LeaseContractSettings, LeaseContractSettings.lease_id == Lease.id).filter(
        Lease.status == LeaseStatus.ACTIVE,
        LeaseContractSettings.tacit_renewal.is_(True),
        Lease.end_date < processing_date,
    ).all()
    processed = []
    for lease in due_leases:
        planned_date = lease.end_date + timedelta(days=1)
        existing = db.query(LeaseRenewal).filter(
            LeaseRenewal.lease_id == lease.id,
            LeaseRenewal.mode == RenewalMode.AUTOMATIC,
            LeaseRenewal.planned_date == planned_date,
        ).first()
        if existing:
            continue
        renewal = LeaseRenewal(
            reference=generate_reference("REN"),
            lease_id=lease.id,
            mode=RenewalMode.AUTOMATIC,
            planned_date=planned_date,
            created_by=current_user.email,
            notes="Renouvellement déclenché automatiquement",
        )
        db.add(renewal)
        db.flush()
        process_renewal(db, renewal, current_user.email)
        processed.append({"lease_id": lease.id, "renewal_id": renewal.id, "new_end_date": renewal.new_end_date})
    return {"as_of": processing_date, "processed": processed, "count": len(processed)}


# ---------------------------------------------------------------------------
# CRUD et génération du bail
# ---------------------------------------------------------------------------
@router.post("/", status_code=201)
def create_lease(data: LeaseContractCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        lease = create_contract_lease(db, data, current_user.email)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    return _lease_view(lease, detail=True)


@router.get("/")
def list_leases(
    status: Optional[LeaseStatus] = None,
    lease_type: Optional[str] = None,
    tenant_id: Optional[int] = None,
    property_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    query = db.query(Lease).join(LeaseContractSettings, LeaseContractSettings.lease_id == Lease.id)
    if status:
        query = query.filter(Lease.status == status)
    if lease_type:
        query = query.filter(LeaseContractSettings.lease_type == lease_type)
    if tenant_id:
        query = query.filter(Lease.tenant_id == tenant_id)
    if property_id:
        query = query.filter(Lease.property_id == property_id)
    total = query.count()
    rows = query.order_by(Lease.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [_lease_view(item) for item in rows], "total": total, "page": page, "total_pages": (total + limit - 1) // limit}


@router.get("/{lease_id}")
def get_lease(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    lease = _lease_or_404(db, lease_id)
    result = _lease_view(lease, detail=True)
    result["annexes"] = annex_completeness(db, lease)
    result["statistics"] = {
        "revisions": db.query(RentRevision).filter(RentRevision.lease_id == lease.id).count(),
        "amendments": db.query(LeaseAmendment).filter(LeaseAmendment.lease_id == lease.id).count(),
        "notices": db.query(LeaseNotice).filter(LeaseNotice.lease_id == lease.id).count(),
        "documents": db.query(ContractDocument).filter(ContractDocument.lease_id == lease.id).count(),
    }
    return result


@router.put("/{lease_id}")
def update_lease(lease_id: int, data: LeaseContractUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    lease = _lease_or_404(db, lease_id)
    contract = _settings_or_404(db, lease_id)
    payload = data.model_dump(exclude_unset=True)
    if contract.signature_status == "completed" and set(payload) - {"status", "notes"}:
        raise HTTPException(status_code=409, detail="Un bail signé est immuable ; créez un avenant pour modifier ses conditions")
    base_mapping = {
        "status": "status",
        "start_date": "start_date",
        "end_date": "end_date",
        "rent_excluding_charges": "monthly_rent",
        "charges": "monthly_charges",
        "deposit": "deposit",
        "payment_day": "payment_day",
        "notes": "notes",
    }
    settings_fields = {
        "duration_months", "tacit_renewal", "renewal_notice_months", "charge_method",
        "rent_index_type", "base_index_value", "base_index_date", "next_revision_date",
        "rent_frequency", "payment_method", "resolutory_clause", "resolutory_clause_text",
        "special_conditions", "custom_variables",
    }
    for field, target in base_mapping.items():
        if field in payload:
            setattr(lease, target, payload[field])
    for field in settings_fields:
        if field in payload:
            setattr(contract, field, payload[field])
    if lease.end_date and lease.end_date < lease.start_date:
        raise HTTPException(status_code=400, detail="La date de fin doit être postérieure à la date de début")
    if lease.status == LeaseStatus.ACTIVE:
        lease.property.status = PropertyStatus.RENTED
        lease.tenant.status = TenantStatus.ACTIVE
    if set(payload) - {"status", "notes"}:
        contract.contract_version += 1
        contract.pdf_document_id = None
        contract.signature_status = "not_started"
        lease.document_storage_path = None
        lease.document_url = None
    log_event(db, lease.id, "lease_updated", "Paramètres du bail modifiés", current_user.email, details={"fields": sorted(payload)})
    db.commit()
    db.refresh(lease)
    return _lease_view(lease, detail=True)


@router.post("/{lease_id}/clauses", status_code=201)
def add_lease_clause(lease_id: int, data: ClauseAssignmentCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    contract = _settings_or_404(db, lease_id)
    if contract.signature_status == "completed":
        raise HTTPException(status_code=409, detail="Un bail signé est immuable ; créez un avenant")
    clause = None
    if data.clause_id:
        clause = db.query(LeaseClause).filter(LeaseClause.id == data.clause_id, LeaseClause.is_active.is_(True)).first()
        if not clause:
            raise HTTPException(status_code=404, detail="Clause non trouvée")
    assignment = LeaseClauseAssignment(
        settings_id=contract.id,
        clause_id=clause.id if clause else None,
        title=data.title or clause.title,
        content=data.content or clause.content_template,
        display_order=data.display_order,
        is_required=data.is_required or (clause.is_mandatory if clause else False),
        source="library" if clause else "custom",
    )
    db.add(assignment)
    contract.contract_version += 1
    contract.pdf_document_id = None
    contract.signature_status = "not_started"
    contract.lease.document_storage_path = None
    contract.lease.document_url = None
    db.commit()
    db.refresh(assignment)
    return assignment


@router.delete("/{lease_id}/clauses/{assignment_id}")
def delete_lease_clause(lease_id: int, assignment_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    contract = _settings_or_404(db, lease_id)
    if contract.signature_status == "completed":
        raise HTTPException(status_code=409, detail="Un bail signé est immuable ; créez un avenant")
    assignment = db.query(LeaseClauseAssignment).filter(LeaseClauseAssignment.id == assignment_id, LeaseClauseAssignment.settings_id == contract.id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Clause non trouvée")
    if assignment.is_required:
        raise HTTPException(status_code=409, detail="Une clause obligatoire ne peut pas être retirée")
    db.delete(assignment)
    contract.contract_version += 1
    contract.pdf_document_id = None
    contract.signature_status = "not_started"
    contract.lease.document_storage_path = None
    contract.lease.document_url = None
    db.commit()
    return {"message": "Clause retirée"}


@router.post("/{lease_id}/generate-pdf", status_code=201)
def generate_pdf(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    lease = _lease_or_404(db, lease_id)
    try:
        document = generate_and_store_lease(db, lease, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _document_view(document)


# ---------------------------------------------------------------------------
# Documents et archivage
# ---------------------------------------------------------------------------
@router.get("/{lease_id}/documents")
def list_documents(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    lease = _lease_or_404(db, lease_id)
    documents = db.query(ContractDocument).filter(ContractDocument.lease_id == lease.id).order_by(ContractDocument.created_at.desc()).all()
    return {"data": [_document_view(item) for item in documents], "completeness": annex_completeness(db, lease)}


@router.post("/{lease_id}/documents", status_code=201)
async def upload_document(
    lease_id: int,
    file: UploadFile = File(...),
    document_type: ContractDocumentType = Form(...),
    title: Optional[str] = Form(None),
    is_required: bool = Form(False),
    retention_until: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    lease = _lease_or_404(db, lease_id)
    extension = Path(file.filename or "").suffix.lower().lstrip(".")
    if extension not in {"pdf", "jpg", "jpeg", "png"}:
        raise HTTPException(status_code=400, detail="Formats autorisés : PDF, JPG, JPEG, PNG")
    content = await file.read()
    if not content or len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier vide ou supérieur à 25 Mo")
    if extension == "pdf" and not content.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="PDF invalide")
    if extension in {"jpg", "jpeg", "png"}:
        try:
            import io
            from PIL import Image
            image = Image.open(io.BytesIO(content))
            image.verify()
        except Exception:
            raise HTTPException(status_code=400, detail="Image invalide")
    directory = Path(settings.private_upload_dir_path) / "contracts" / str(lease.id) / "annexes"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.{extension}"
    async with aiofiles.open(path, "wb") as output:
        await output.write(content)
    try:
        retention_date = datetime.strptime(retention_until, "%Y-%m-%d").date() if retention_until else None
    except ValueError:
        raise HTTPException(status_code=400, detail="retention_until doit respecter YYYY-MM-DD")
    version = db.query(ContractDocument).filter(ContractDocument.lease_id == lease.id, ContractDocument.document_type == document_type).count() + 1
    document = ContractDocument(
        reference=generate_reference("DOC"),
        lease_id=lease.id,
        document_type=document_type,
        title=title or Path(file.filename or "document").name,
        original_filename=Path(file.filename or "document").name,
        storage_path=str(path),
        mime_type=file.content_type,
        file_size=len(content),
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        version=version,
        is_required=is_required,
        retention_until=retention_date,
        uploaded_by=current_user.email,
    )
    db.add(document)
    db.flush()
    log_event(db, lease.id, "document_uploaded", "Document contractuel ajouté", current_user.email, details={"document_id": document.id, "document_type": document_type.value})
    db.commit()
    db.refresh(document)
    return _document_view(document)


@router.get("/{lease_id}/documents/completeness")
def document_completeness(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    return annex_completeness(db, _lease_or_404(db, lease_id))


@router.get("/{lease_id}/documents/{document_id}/download")
def download_document(lease_id: int, document_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    document = db.query(ContractDocument).filter(ContractDocument.id == document_id, ContractDocument.lease_id == lease_id).first()
    if not document or document.archive_status == ArchiveStatus.DESTROYED or not os.path.isfile(document.storage_path):
        raise HTTPException(status_code=404, detail="Document non trouvé")
    if not _document_integrity_ok(document):
        raise HTTPException(status_code=409, detail="L'intégrité du document archivé ne peut pas être vérifiée")
    return FileResponse(document.storage_path, media_type=document.mime_type, filename=document.original_filename or f"{document.reference}.pdf")


@router.put("/{lease_id}/documents/{document_id}/archive")
def archive_document(lease_id: int, document_id: int, data: DocumentArchiveInput, db: Session = Depends(get_db), current_user=Depends(require_write)):
    document = db.query(ContractDocument).filter(ContractDocument.id == document_id, ContractDocument.lease_id == lease_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    document.archive_status = ArchiveStatus.ARCHIVED
    document.archived_at = datetime.now(timezone.utc)
    document.retention_until = data.retention_until
    document.legal_hold = data.legal_hold
    log_event(db, lease_id, "document_archived", "Document archivé", current_user.email, details={"document_id": document.id, "retention_until": str(data.retention_until), "legal_hold": data.legal_hold})
    db.commit()
    return _document_view(document)


# ---------------------------------------------------------------------------
# Révision, renouvellement, avenants et congés
# ---------------------------------------------------------------------------
@router.post("/{lease_id}/revisions", status_code=201)
def create_revision(lease_id: int, data: RentRevisionCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return calculate_rent_revision(db, _lease_or_404(db, lease_id), data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{lease_id}/revisions")
def list_revisions(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _lease_or_404(db, lease_id)
    return db.query(RentRevision).filter(RentRevision.lease_id == lease_id).order_by(RentRevision.effective_date.desc()).all()


@router.put("/{lease_id}/revisions/{revision_id}/apply")
def apply_revision(lease_id: int, revision_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    revision = db.query(RentRevision).filter(RentRevision.id == revision_id, RentRevision.lease_id == lease_id).first()
    if not revision:
        raise HTTPException(status_code=404, detail="Révision non trouvée")
    try:
        return apply_rent_revision(db, revision, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{lease_id}/renewals", status_code=201)
def create_renewal(lease_id: int, data: RenewalCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    lease = _lease_or_404(db, lease_id)
    renewal = LeaseRenewal(
        reference=generate_reference("REN"),
        lease_id=lease.id,
        created_by=current_user.email,
        **data.model_dump(),
    )
    db.add(renewal)
    log_event(db, lease.id, "renewal_planned", "Renouvellement planifié", current_user.email, details={"mode": data.mode.value, "planned_date": data.planned_date.isoformat()})
    db.commit()
    db.refresh(renewal)
    return renewal


@router.get("/{lease_id}/renewals")
def list_renewals(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _lease_or_404(db, lease_id)
    return db.query(LeaseRenewal).filter(LeaseRenewal.lease_id == lease_id).order_by(LeaseRenewal.planned_date.desc()).all()


@router.put("/{lease_id}/renewals/{renewal_id}/complete")
def complete_renewal(lease_id: int, renewal_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    renewal = db.query(LeaseRenewal).filter(LeaseRenewal.id == renewal_id, LeaseRenewal.lease_id == lease_id).first()
    if not renewal:
        raise HTTPException(status_code=404, detail="Renouvellement non trouvé")
    try:
        return process_renewal(db, renewal, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/{lease_id}/amendments", status_code=201)
def add_amendment(lease_id: int, data: AmendmentCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    return create_amendment(db, _lease_or_404(db, lease_id), data, current_user.email)


@router.get("/{lease_id}/amendments")
def list_amendments(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _lease_or_404(db, lease_id)
    return db.query(LeaseAmendment).filter(LeaseAmendment.lease_id == lease_id).order_by(LeaseAmendment.amendment_number.desc()).all()


@router.put("/{lease_id}/amendments/{amendment_id}/apply")
def apply_amendment(lease_id: int, amendment_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    amendment = db.query(LeaseAmendment).filter(LeaseAmendment.id == amendment_id, LeaseAmendment.lease_id == lease_id).first()
    if not amendment:
        raise HTTPException(status_code=404, detail="Avenant non trouvé")
    if amendment.status == "applied":
        return amendment
    if amendment.signature_status != "completed":
        raise HTTPException(status_code=409, detail="L'avenant doit être signé par toutes les parties avant application")
    lease = amendment.lease
    contract = _settings_or_404(db, lease_id)
    base_fields = {
        "rent_excluding_charges": "monthly_rent",
        "monthly_rent": "monthly_rent",
        "charges": "monthly_charges",
        "monthly_charges": "monthly_charges",
        "deposit": "deposit",
        "payment_day": "payment_day",
    }
    settings_fields = {"special_conditions", "payment_method", "tacit_renewal", "renewal_notice_months"}
    unsupported = set(amendment.changes or {}) - set(base_fields) - settings_fields - {"end_date"}
    if unsupported:
        raise HTTPException(status_code=400, detail=f"Modifications non applicables automatiquement : {', '.join(sorted(unsupported))}")
    for field, target in base_fields.items():
        if field in (amendment.changes or {}):
            setattr(lease, target, amendment.changes[field])
    for field in settings_fields:
        if field in (amendment.changes or {}):
            setattr(contract, field, amendment.changes[field])
    if "end_date" in (amendment.changes or {}):
        try:
            lease.end_date = date.fromisoformat(str(amendment.changes["end_date"]))
        except ValueError:
            raise HTTPException(status_code=400, detail="end_date invalide dans l'avenant")
    amendment.status = "applied"
    amendment.applied_at = datetime.now(timezone.utc)
    contract.contract_version += 1
    renewal = db.query(LeaseRenewal).filter(LeaseRenewal.amendment_id == amendment.id).first()
    if renewal:
        renewal.status = RenewalStatus.COMPLETED
        renewal.completed_at = amendment.applied_at
    notify_tenant(db, lease.tenant_id, "lease_amendment_applied", "Avenant appliqué", f"L'avenant n° {amendment.amendment_number} est entré en vigueur.")
    log_event(db, lease_id, "amendment_applied", "Avenant appliqué", current_user.email, details={"amendment_id": amendment.id, "changes": amendment.changes})
    db.commit()
    db.refresh(amendment)
    return amendment


@router.post("/{lease_id}/notices", status_code=201)
def add_notice(lease_id: int, data: NoticeCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return create_notice(db, _lease_or_404(db, lease_id), data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{lease_id}/notices")
def list_notices(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _lease_or_404(db, lease_id)
    return db.query(LeaseNotice).filter(LeaseNotice.lease_id == lease_id).order_by(LeaseNotice.notice_date.desc()).all()


@router.post("/{lease_id}/notices/{notice_id}/generate-letter", status_code=201)
def generate_notice_letter(lease_id: int, notice_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    notice = db.query(LeaseNotice).filter(LeaseNotice.id == notice_id, LeaseNotice.lease_id == lease_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="Congé non trouvé")
    document = store_contract_document(
        db,
        lease_id,
        ContractDocumentType.NOTICE_LETTER,
        f"Lettre de congé {notice.reference}",
        generate_notice_pdf_bytes(notice),
        current_user.email,
    )
    notice.letter_document_id = document.id
    db.commit()
    db.refresh(document)
    return _document_view(document)


@router.put("/{lease_id}/notices/{notice_id}/status")
def update_notice_status(lease_id: int, notice_id: int, data: NoticeStatusUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    notice = db.query(LeaseNotice).filter(LeaseNotice.id == notice_id, LeaseNotice.lease_id == lease_id).first()
    if not notice:
        raise HTTPException(status_code=404, detail="Congé non trouvé")
    now = datetime.now(timezone.utc)
    notice.status = data.status
    if data.status == NoticeStatus.SENT:
        notice.sent_at = now
    elif data.status == NoticeStatus.ACKNOWLEDGED:
        notice.acknowledged_at = now
    elif data.status == NoticeStatus.COMPLETED:
        notice.completed_at = now
        notice.lease.status = LeaseStatus.TERMINATED
        notice.lease.end_date = notice.effective_end_date
        other_active_lease = db.query(Lease).filter(
            Lease.tenant_id == notice.lease.tenant_id,
            Lease.id != notice.lease_id,
            Lease.status == LeaseStatus.ACTIVE,
        ).first()
        if not other_active_lease:
            notice.lease.tenant.status = TenantStatus.LEFT
        other_property_lease = db.query(Lease).filter(
            Lease.property_id == notice.lease.property_id,
            Lease.id != notice.lease_id,
            Lease.status == LeaseStatus.ACTIVE,
        ).first()
        if not other_property_lease:
            notice.lease.property.status = PropertyStatus.AVAILABLE
    log_event(db, lease_id, "notice_status_changed", "Statut du congé modifié", current_user.email, details={"notice_id": notice.id, "status": data.status.value})
    db.commit()
    db.refresh(notice)
    return notice


# ---------------------------------------------------------------------------
# Signature électronique simple avec piste d'audit
# ---------------------------------------------------------------------------
@router.post("/{lease_id}/signature-envelopes", status_code=201)
def request_signature(lease_id: int, data: SignatureEnvelopeCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    lease = _lease_or_404(db, lease_id)
    document = db.query(ContractDocument).filter(ContractDocument.id == data.document_id, ContractDocument.lease_id == lease.id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document non trouvé")
    try:
        envelope, invitations = create_signature_envelope(db, lease, document, data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": envelope.id,
        "reference": envelope.reference,
        "status": envelope.status.value,
        "provider": envelope.provider,
        "expires_at": envelope.expires_at,
        "invitations": invitations,
        "warning": "Signature électronique simple avec piste d'audit ; une qualification eIDAS dépend du prestataire et du niveau requis.",
    }


@router.get("/{lease_id}/signature-envelopes")
def list_signature_envelopes(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _lease_or_404(db, lease_id)
    envelopes = db.query(SignatureEnvelope).filter(SignatureEnvelope.lease_id == lease_id).order_by(SignatureEnvelope.created_at.desc()).all()
    return [
        {
            "id": item.id,
            "reference": item.reference,
            "document_id": item.document_id,
            "status": item.status.value,
            "provider": item.provider,
            "expires_at": item.expires_at,
            "completed_at": item.completed_at,
            "evidence_document_id": item.evidence_document_id,
            "parties": [{"id": p.id, "name": p.full_name, "email": p.email, "status": p.status.value, "signed_at": p.signed_at} for p in item.parties],
        }
        for item in envelopes
    ]


@router.get("/{lease_id}/events")
def contract_history(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _lease_or_404(db, lease_id)
    return db.query(ContractEvent).filter(ContractEvent.lease_id == lease_id).order_by(ContractEvent.occurred_at.desc()).all()


# Routes publiques protégées par un jeton à forte entropie propre à chaque signataire.
@signature_router.get("/{token}")
def view_signature(token: str, db: Session = Depends(get_db)):
    try:
        party = find_signature_party(db, token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if party.status == SignaturePartyStatus.PENDING:
        party.status = SignaturePartyStatus.VIEWED
        party.viewed_at = datetime.now(timezone.utc)
        db.commit()
    document = party.envelope.document
    return {
        "envelope_reference": party.envelope.reference,
        "subject": party.envelope.subject,
        "message": party.envelope.message,
        "signer": {"name": party.full_name, "email": party.email, "status": party.status.value},
        "document": {
            "title": document.title,
            "checksum_sha256": document.checksum_sha256,
            "download_url": f"/api/lease-signatures/{token}/document",
        },
        "expires_at": party.envelope.expires_at,
        "signature_level": "simple_electronic_signature",
    }


@signature_router.get("/{token}/document")
def public_signature_document(token: str, db: Session = Depends(get_db)):
    try:
        party = find_signature_party(db, token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    document = party.envelope.document
    if not os.path.isfile(document.storage_path):
        raise HTTPException(status_code=404, detail="Document non trouvé")
    if not _document_integrity_ok(document):
        raise HTTPException(status_code=409, detail="L'intégrité du document à signer ne peut pas être vérifiée")
    return FileResponse(document.storage_path, media_type=document.mime_type, filename=document.original_filename)


@signature_router.post("/{token}/sign")
def sign_document(token: str, data: PublicSignatureInput, request: Request, db: Session = Depends(get_db)):
    try:
        party = find_signature_party(db, token)
        party = complete_signature(
            db,
            party,
            data.typed_signature,
            data.signature_image_base64,
            request.client.host if request.client else "unknown",
            request.headers.get("User-Agent", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": party.status.value, "signed_at": party.signed_at, "envelope_status": party.envelope.status.value}


@signature_router.post("/{token}/decline")
def decline_signature(token: str, data: SignatureDeclineInput, db: Session = Depends(get_db)):
    try:
        party = find_signature_party(db, token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if party.status == SignaturePartyStatus.SIGNED:
        raise HTTPException(status_code=409, detail="Un document déjà signé ne peut pas être refusé")
    party.status = SignaturePartyStatus.DECLINED
    party.declined_at = datetime.now(timezone.utc)
    party.decline_reason = data.reason
    party.envelope.status = SignatureEnvelopeStatus.DECLINED
    db.commit()
    return {"status": "declined"}
