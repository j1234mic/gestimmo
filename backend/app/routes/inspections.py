"""États des lieux : saisie mobile, photos, comparaison, retenues et PDF."""

import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.config import settings
from app.database import get_db
from app.models.lease_contract import (
    ArchiveStatus,
    ContractDocumentType,
    InspectionItem,
    InspectionKey,
    InspectionMeter,
    InspectionPhoto,
    InspectionRoom,
    InspectionSignature,
    InspectionStatus,
    InspectionType,
    PropertyInspection,
)
from app.models.tenant import Lease
from app.schemas.lease_contract import (
    InspectionBulkSync,
    InspectionCreate,
    InspectionDeductionsApproval,
    InspectionItemInput,
    InspectionKeyCreate,
    InspectionMeterCreate,
    InspectionRoomCreate,
    InspectionSignatureCreate,
    InspectionUpdate,
)
from app.services.lease_service import (
    compare_inspections,
    decode_signature_image,
    generate_inspection_pdf_bytes,
    generate_reference,
    log_event,
    store_contract_document,
)

router = APIRouter(prefix="/api/leases/{lease_id}/inspections", tags=["États des lieux"])


def _lease_or_404(db: Session, lease_id: int) -> Lease:
    lease = db.query(Lease).filter(Lease.id == lease_id).first()
    if not lease:
        raise HTTPException(status_code=404, detail="Bail non trouvé")
    return lease


def _inspection_or_404(db: Session, lease_id: int, inspection_id: int) -> PropertyInspection:
    inspection = db.query(PropertyInspection).filter(
        PropertyInspection.id == inspection_id,
        PropertyInspection.lease_id == lease_id,
    ).first()
    if not inspection:
        raise HTTPException(status_code=404, detail="État des lieux non trouvé")
    return inspection


def _item_view(item: InspectionItem) -> dict:
    return {
        "id": item.id,
        "client_uuid": item.client_uuid,
        "category": item.category,
        "name": item.name,
        "condition": item.condition.value,
        "cleanliness": item.cleanliness,
        "description": item.description,
        "estimated_repair_cost": item.estimated_repair_cost,
        "depreciation_percent": item.depreciation_percent,
        "tenant_responsibility_percent": item.tenant_responsibility_percent,
        "photos": [
            {
                "id": photo.id,
                "caption": photo.caption,
                "captured_at": photo.captured_at,
                "checksum_sha256": photo.checksum_sha256,
                "download_url": f"/api/leases/{item.room.inspection.lease_id}/inspections/{item.room.inspection_id}/photos/{photo.id}/download",
            }
            for photo in item.photos
        ],
    }


def _inspection_view(inspection: PropertyInspection, detail: bool = False) -> dict:
    result = {
        "id": inspection.id,
        "reference": inspection.reference,
        "client_uuid": inspection.client_uuid,
        "lease_id": inspection.lease_id,
        "inspection_type": inspection.inspection_type.value,
        "status": inspection.status.value,
        "inspection_date": inspection.inspection_date,
        "conducted_by": inspection.conducted_by,
        "general_comments": inspection.general_comments,
        "comparison_inspection_id": inspection.comparison_inspection_id,
        "document_id": inspection.document_id,
        "total_suggested_deductions": inspection.total_suggested_deductions,
        "total_approved_deductions": inspection.total_approved_deductions,
        "sync_version": inspection.sync_version,
        "photos_count": len(inspection.photos),
        "signatures_count": len(inspection.signatures),
        "created_at": inspection.created_at,
        "updated_at": inspection.updated_at,
    }
    if detail:
        result.update({
            "rooms": [
                {
                    "id": room.id,
                    "client_uuid": room.client_uuid,
                    "name": room.name,
                    "room_type": room.room_type,
                    "display_order": room.display_order,
                    "comments": room.comments,
                    "items": [_item_view(item) for item in room.items],
                }
                for room in sorted(inspection.rooms, key=lambda item: item.display_order)
            ],
            "meters": [
                {
                    "id": meter.id,
                    "meter_type": meter.meter_type,
                    "serial_number": meter.serial_number,
                    "reading": meter.reading,
                    "unit": meter.unit,
                    "location": meter.location,
                    "photo_id": meter.photo_id,
                }
                for meter in inspection.meters
            ],
            "keys": [
                {"id": key.id, "key_type": key.key_type, "quantity": key.quantity, "comments": key.comments}
                for key in inspection.keys
            ],
            "photos": [
                {
                    "id": photo.id,
                    "room_id": photo.room_id,
                    "item_id": photo.item_id,
                    "caption": photo.caption,
                    "captured_at": photo.captured_at,
                    "latitude": photo.latitude,
                    "longitude": photo.longitude,
                    "checksum_sha256": photo.checksum_sha256,
                    "download_url": f"/api/leases/{inspection.lease_id}/inspections/{inspection.id}/photos/{photo.id}/download",
                }
                for photo in inspection.photos
            ],
            "signatures": [
                {
                    "id": signature.id,
                    "signer_type": signature.signer_type,
                    "signer_name": signature.signer_name,
                    "signer_email": signature.signer_email,
                    "signed_at": signature.signed_at,
                    "document_checksum": signature.document_checksum,
                }
                for signature in inspection.signatures
            ],
            "deductions": [
                {
                    "id": deduction.id,
                    "item_id": deduction.item_id,
                    "label": deduction.label,
                    "deterioration": deduction.deterioration,
                    "estimated_cost": deduction.estimated_cost,
                    "depreciation_percent": deduction.depreciation_percent,
                    "responsibility_percent": deduction.responsibility_percent,
                    "suggested_amount": deduction.suggested_amount,
                    "approved_amount": deduction.approved_amount,
                    "approval_notes": deduction.approval_notes,
                }
                for deduction in inspection.deductions
            ],
        })
    return result


def _ensure_editable(inspection: PropertyInspection):
    if inspection.status in {InspectionStatus.READY_FOR_SIGNATURE, InspectionStatus.SIGNED, InspectionStatus.ARCHIVED}:
        raise HTTPException(status_code=409, detail="Un état des lieux en signature, signé ou archivé est immuable")


def _add_room(db: Session, inspection: PropertyInspection, data: InspectionRoomCreate) -> InspectionRoom:
    room = InspectionRoom(
        inspection_id=inspection.id,
        **data.model_dump(exclude={"items"}),
    )
    db.add(room)
    db.flush()
    for item_data in data.items:
        db.add(InspectionItem(room_id=room.id, **item_data.model_dump()))
    return room


@router.get("/")
def list_inspections(lease_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _lease_or_404(db, lease_id)
    records = db.query(PropertyInspection).filter(PropertyInspection.lease_id == lease_id).order_by(PropertyInspection.inspection_date.desc()).all()
    return [_inspection_view(item) for item in records]


@router.post("/", status_code=201)
def create_inspection(lease_id: int, data: InspectionCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _lease_or_404(db, lease_id)
    if data.comparison_inspection_id:
        comparison = db.query(PropertyInspection).filter(
            PropertyInspection.id == data.comparison_inspection_id,
            PropertyInspection.lease_id == lease_id,
        ).first()
        if not comparison:
            raise HTTPException(status_code=400, detail="État des lieux de comparaison invalide")
    if data.client_uuid:
        existing = db.query(PropertyInspection).filter(PropertyInspection.client_uuid == data.client_uuid).first()
        if existing:
            return _inspection_view(existing, detail=True)
    inspection = PropertyInspection(
        reference=generate_reference("EDL"),
        lease_id=lease_id,
        status=InspectionStatus.IN_PROGRESS,
        **data.model_dump(),
    )
    db.add(inspection)
    db.flush()
    log_event(db, lease_id, "inspection_created", "État des lieux créé", current_user.email, details={"inspection_id": inspection.id, "type": data.inspection_type.value})
    db.commit()
    db.refresh(inspection)
    return _inspection_view(inspection, detail=True)


@router.get("/{inspection_id}")
def get_inspection(lease_id: int, inspection_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    return _inspection_view(_inspection_or_404(db, lease_id, inspection_id), detail=True)


@router.put("/{inspection_id}")
def update_inspection(lease_id: int, inspection_id: int, data: InspectionUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    _ensure_editable(inspection)
    if data.status in {InspectionStatus.SIGNED, InspectionStatus.ARCHIVED}:
        raise HTTPException(status_code=409, detail="Utilisez le workflow de signature et d'archivage")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(inspection, field, value)
    inspection.sync_version += 1
    db.commit()
    db.refresh(inspection)
    return _inspection_view(inspection, detail=True)


@router.post("/{inspection_id}/rooms", status_code=201)
def add_room(lease_id: int, inspection_id: int, data: InspectionRoomCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    _ensure_editable(inspection)
    room = _add_room(db, inspection, data)
    inspection.sync_version += 1
    db.commit()
    db.refresh(room)
    return {
        "id": room.id,
        "client_uuid": room.client_uuid,
        "name": room.name,
        "room_type": room.room_type,
        "display_order": room.display_order,
        "items": [_item_view(item) for item in room.items],
    }


@router.post("/{inspection_id}/rooms/{room_id}/items", status_code=201)
def add_item(lease_id: int, inspection_id: int, room_id: int, data: InspectionItemInput, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    _ensure_editable(inspection)
    room = db.query(InspectionRoom).filter(InspectionRoom.id == room_id, InspectionRoom.inspection_id == inspection.id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Pièce non trouvée")
    item = InspectionItem(room_id=room.id, **data.model_dump())
    db.add(item)
    inspection.sync_version += 1
    db.commit()
    db.refresh(item)
    return _item_view(item)


@router.put("/{inspection_id}/rooms/{room_id}/items/{item_id}")
def update_item(lease_id: int, inspection_id: int, room_id: int, item_id: int, data: InspectionItemInput, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    _ensure_editable(inspection)
    item = db.query(InspectionItem).join(InspectionRoom).filter(
        InspectionItem.id == item_id,
        InspectionItem.room_id == room_id,
        InspectionRoom.inspection_id == inspection.id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Élément non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    inspection.sync_version += 1
    db.commit()
    db.refresh(item)
    return _item_view(item)


@router.post("/{inspection_id}/meters", status_code=201)
def add_meter(lease_id: int, inspection_id: int, data: InspectionMeterCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    _ensure_editable(inspection)
    meter = InspectionMeter(inspection_id=inspection.id, **data.model_dump())
    db.add(meter)
    inspection.sync_version += 1
    db.commit()
    db.refresh(meter)
    return meter


@router.post("/{inspection_id}/keys", status_code=201)
def add_key(lease_id: int, inspection_id: int, data: InspectionKeyCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    _ensure_editable(inspection)
    key = InspectionKey(inspection_id=inspection.id, **data.model_dump())
    db.add(key)
    inspection.sync_version += 1
    db.commit()
    db.refresh(key)
    return key


@router.put("/{inspection_id}/mobile-sync")
def mobile_sync(lease_id: int, inspection_id: int, data: InspectionBulkSync, db: Session = Depends(get_db), current_user=Depends(require_write)):
    """Synchronisation transactionnelle d'une saisie mobile éventuellement hors ligne."""
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    _ensure_editable(inspection)
    if inspection.client_uuid and inspection.client_uuid != data.client_uuid:
        raise HTTPException(status_code=409, detail="client_uuid ne correspond pas à cet état des lieux")
    if data.sync_version < inspection.sync_version:
        raise HTTPException(status_code=409, detail={
            "message": "Conflit de synchronisation",
            "server_version": inspection.sync_version,
            "client_version": data.sync_version,
        })
    inspection.client_uuid = data.client_uuid
    inspection.inspection_date = data.inspection_date
    inspection.general_comments = data.general_comments
    db.query(InspectionPhoto).filter(InspectionPhoto.inspection_id == inspection.id).update({"room_id": None, "item_id": None})
    for room in list(inspection.rooms):
        db.delete(room)
    for meter in list(inspection.meters):
        db.delete(meter)
    for key in list(inspection.keys):
        db.delete(key)
    db.flush()
    for room_data in data.rooms:
        _add_room(db, inspection, room_data)
    for meter_data in data.meters:
        db.add(InspectionMeter(inspection_id=inspection.id, **meter_data.model_dump()))
    for key_data in data.keys:
        db.add(InspectionKey(inspection_id=inspection.id, **key_data.model_dump()))
    inspection.sync_version = max(inspection.sync_version, data.sync_version) + 1
    db.commit()
    db.refresh(inspection)
    return _inspection_view(inspection, detail=True)


@router.post("/{inspection_id}/photos", status_code=201)
async def upload_photo(
    lease_id: int,
    inspection_id: int,
    file: UploadFile = File(...),
    captured_at: datetime = Form(...),
    room_id: Optional[int] = Form(None),
    item_id: Optional[int] = Form(None),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    caption: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    _ensure_editable(inspection)
    if room_id and not db.query(InspectionRoom).filter(InspectionRoom.id == room_id, InspectionRoom.inspection_id == inspection.id).first():
        raise HTTPException(status_code=400, detail="Pièce invalide")
    if item_id:
        item = db.query(InspectionItem).join(InspectionRoom).filter(InspectionItem.id == item_id, InspectionRoom.inspection_id == inspection.id).first()
        if not item:
            raise HTTPException(status_code=400, detail="Élément invalide")
        room_id = item.room_id
    extension = Path(file.filename or "").suffix.lower().lstrip(".")
    if extension not in {"jpg", "jpeg", "png", "webp"}:
        raise HTTPException(status_code=400, detail="Formats photo autorisés : JPG, PNG, WEBP")
    content = await file.read()
    if not content or len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Photo vide ou supérieure à 15 Mo")
    try:
        import io
        from PIL import Image
        image = Image.open(io.BytesIO(content))
        image.verify()
    except Exception:
        raise HTTPException(status_code=400, detail="Image invalide")
    directory = Path(settings.private_upload_dir_path) / "contracts" / str(lease_id) / "inspections" / str(inspection.id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.{extension}"
    async with aiofiles.open(path, "wb") as output:
        await output.write(content)
    photo = InspectionPhoto(
        inspection_id=inspection.id,
        room_id=room_id,
        item_id=item_id,
        original_filename=Path(file.filename or "photo").name,
        storage_path=str(path),
        mime_type=file.content_type,
        checksum_sha256=hashlib.sha256(content).hexdigest(),
        captured_at=captured_at,
        latitude=latitude,
        longitude=longitude,
        caption=caption,
    )
    db.add(photo)
    inspection.sync_version += 1
    db.commit()
    db.refresh(photo)
    return {
        "id": photo.id,
        "captured_at": photo.captured_at,
        "checksum_sha256": photo.checksum_sha256,
        "download_url": f"/api/leases/{lease_id}/inspections/{inspection.id}/photos/{photo.id}/download",
    }


@router.get("/{inspection_id}/photos/{photo_id}/download")
def download_photo(lease_id: int, inspection_id: int, photo_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    photo = db.query(InspectionPhoto).filter(InspectionPhoto.id == photo_id, InspectionPhoto.inspection_id == inspection_id).first()
    if not photo or not os.path.isfile(photo.storage_path):
        raise HTTPException(status_code=404, detail="Photo non trouvée")
    return FileResponse(photo.storage_path, media_type=photo.mime_type, filename=photo.original_filename)


@router.post("/{inspection_id}/compare")
def compare(lease_id: int, inspection_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    try:
        return compare_inspections(db, inspection)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/{inspection_id}/deductions")
def approve_deductions(lease_id: int, inspection_id: int, data: InspectionDeductionsApproval, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    _ensure_editable(inspection)
    records = {item.id: item for item in inspection.deductions}
    for approval in data.deductions:
        deduction = records.get(approval.deduction_id)
        if not deduction:
            raise HTTPException(status_code=404, detail=f"Retenue {approval.deduction_id} non trouvée")
        if approval.approved_amount > deduction.estimated_cost:
            raise HTTPException(status_code=400, detail="Une retenue approuvée ne peut pas dépasser le coût estimé")
        deduction.approved_amount = approval.approved_amount
        deduction.approval_notes = approval.approval_notes
    inspection.total_approved_deductions = round(sum(item.approved_amount or 0 for item in inspection.deductions), 2)
    log_event(db, lease_id, "deductions_approved", "Retenues d'état des lieux approuvées", current_user.email, details={"inspection_id": inspection.id, "total": inspection.total_approved_deductions})
    db.commit()
    return _inspection_view(inspection, detail=True)


@router.post("/{inspection_id}/signatures", status_code=201)
def sign_inspection(lease_id: int, inspection_id: int, data: InspectionSignatureCreate, request: Request, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    if inspection.status in {InspectionStatus.SIGNED, InspectionStatus.ARCHIVED}:
        raise HTTPException(status_code=409, detail="État des lieux déjà finalisé")
    if any(item.signer_type == data.signer_type and item.signer_name == data.signer_name for item in inspection.signatures):
        raise HTTPException(status_code=409, detail="Ce signataire a déjà signé")
    try:
        path, _ = decode_signature_image(
            data.signature_image_base64,
            Path(settings.private_upload_dir_path) / "contracts" / str(lease_id) / "inspections" / str(inspection.id) / "signatures",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    signature = InspectionSignature(
        inspection_id=inspection.id,
        signer_type=data.signer_type,
        signer_name=data.signer_name,
        signer_email=str(data.signer_email) if data.signer_email else None,
        signature_image_path=path,
        consent_text="Je reconnais l'exactitude de cet état des lieux et consens à le signer électroniquement.",
        ip_address=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("User-Agent", "")[:1000],
    )
    db.add(signature)
    db.flush()
    signer_types = {item.signer_type for item in inspection.signatures} | {data.signer_type}
    if "tenant" in signer_types and signer_types.intersection({"owner", "manager", "agent"}):
        inspection.status = InspectionStatus.SIGNED
    else:
        inspection.status = InspectionStatus.READY_FOR_SIGNATURE
    log_event(db, lease_id, "inspection_signed", "État des lieux signé", current_user.email, details={"inspection_id": inspection.id, "signer_type": data.signer_type})
    db.commit()
    db.refresh(signature)
    return {"id": signature.id, "signed_at": signature.signed_at, "inspection_status": inspection.status.value}


@router.put("/{inspection_id}/archive")
def archive_inspection(lease_id: int, inspection_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    if inspection.status != InspectionStatus.SIGNED or not inspection.document:
        raise HTTPException(status_code=409, detail="L'état des lieux doit être signé et son PDF généré avant archivage")
    inspection.status = InspectionStatus.ARCHIVED
    inspection.document.archive_status = ArchiveStatus.ARCHIVED
    inspection.document.archived_at = datetime.now(timezone.utc)
    log_event(db, lease_id, "inspection_archived", "État des lieux archivé", current_user.email, details={"inspection_id": inspection.id, "document_id": inspection.document_id})
    db.commit()
    return _inspection_view(inspection, detail=True)


@router.post("/{inspection_id}/generate-pdf", status_code=201)
def generate_inspection_pdf(lease_id: int, inspection_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    inspection = _inspection_or_404(db, lease_id, inspection_id)
    document_type = ContractDocumentType.ENTRY_INSPECTION if inspection.inspection_type == InspectionType.ENTRY else ContractDocumentType.EXIT_INSPECTION
    content = generate_inspection_pdf_bytes(inspection)
    document = store_contract_document(
        db,
        lease_id,
        document_type,
        f"État des lieux {inspection.reference}",
        content,
        current_user.email,
        is_required=True,
    )
    inspection.document_id = document.id
    checksum = document.checksum_sha256
    for signature in inspection.signatures:
        signature.document_checksum = checksum
    db.commit()
    db.refresh(document)
    return {
        "id": document.id,
        "reference": document.reference,
        "checksum_sha256": document.checksum_sha256,
        "download_url": f"/api/leases/{lease_id}/documents/{document.id}/download",
    }
