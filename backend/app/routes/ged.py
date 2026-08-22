"""API du module 11 : gestion documentaire (GED)."""

from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import require_admin, require_delete, require_read, require_write
from app.database import get_db
from app.schemas.ged import (
    DocumentMetaUpdate,
    EnvelopeCreate,
    EraseRequest,
    FolderCreate,
    FolderUpdate,
    GenerateDocumentRequest,
    SettingsUpdate,
    SignRequest,
    TemplateCreate,
    TemplateUpdate,
)
from app.services import ged_service

router = APIRouter(prefix="/api/ged", tags=["Gestion documentaire"])


def _role(user) -> str:
    return getattr(user, "role", None) or "viewer"


# ---------------------------------------------------------------------------
# Paramètres
# ---------------------------------------------------------------------------
@router.get("/settings")
def get_settings(db: Session = Depends(get_db), current_user=Depends(require_read)):
    return ged_service.settings_view(ged_service.get_settings(db))


@router.put("/settings")
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db), current_user=Depends(require_admin)):
    return ged_service.settings_view(ged_service.update_settings(db, data))


@router.get("/types")
def document_types(current_user=Depends(require_read)):
    return {"data": ged_service.DOCUMENT_TYPES}


# ---------------------------------------------------------------------------
# Arborescence
# ---------------------------------------------------------------------------
@router.post("/folders", status_code=201)
def create_folder(data: FolderCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        folder = ged_service.create_folder(db, data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ged_service.folder_view(folder)


@router.get("/folders")
def list_folders(
    parent_id: Optional[int] = None,
    scope: Optional[str] = None,
    property_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    folders = ged_service.list_folders(
        db,
        parent_id=parent_id,
        scope=scope,
        property_id=property_id,
        owner_id=owner_id,
        tenant_id=tenant_id,
        lease_id=lease_id,
    )
    return {"data": [ged_service.folder_view(f) for f in folders], "count": len(folders)}


@router.get("/folders/tree")
def folder_tree(root_id: Optional[int] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return {"data": ged_service.folder_tree(db, root_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/folders/{folder_id}")
def update_folder(folder_id: int, data: FolderUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        folder = ged_service.update_folder(db, folder_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ged_service.folder_view(folder)


# ---------------------------------------------------------------------------
# Documents : upload, versioning, métadonnées
# ---------------------------------------------------------------------------
@router.post("/documents", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    document_type: str = Form("other"),
    folder_id: Optional[int] = Form(None),
    tags: Optional[str] = Form(None),
    property_id: Optional[int] = Form(None),
    owner_id: Optional[int] = Form(None),
    tenant_id: Optional[int] = Form(None),
    lease_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    content = await file.read()
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    try:
        document = ged_service.create_document(
            db,
            title=title or file.filename,
            filename=file.filename or "document",
            content=content,
            mime_type=file.content_type,
            document_type=document_type,
            actor=current_user.email,
            actor_role=_role(current_user),
            folder_id=folder_id,
            tags=tag_list,
            property_id=property_id,
            owner_id=owner_id,
            tenant_id=tenant_id,
            lease_id=lease_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ged_service.document_view(document)


@router.post("/documents/batch", status_code=201)
async def upload_multiple(
    files: List[UploadFile] = File(...),
    document_type: str = Form("other"),
    folder_id: Optional[int] = Form(None),
    property_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    created = []
    errors = []
    for file in files:
        content = await file.read()
        try:
            document = ged_service.create_document(
                db,
                title=file.filename,
                filename=file.filename or "document",
                content=content,
                mime_type=file.content_type,
                document_type=document_type,
                actor=current_user.email,
                actor_role=_role(current_user),
                folder_id=folder_id,
                property_id=property_id,
            )
            created.append(ged_service.document_view(document))
        except ValueError as exc:
            errors.append({"filename": file.filename, "error": str(exc)})
    return {"data": created, "count": len(created), "errors": errors}


@router.get("/documents")
def search_documents(
    q: Optional[str] = None,
    document_type: Optional[str] = None,
    tag: Optional[str] = None,
    property_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    folder_id: Optional[int] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    documents = ged_service.search_documents(
        db,
        q=q,
        document_type=document_type,
        tag=tag,
        property_id=property_id,
        owner_id=owner_id,
        tenant_id=tenant_id,
        lease_id=lease_id,
        folder_id=folder_id,
        date_from=date_from,
        date_to=date_to,
    )
    return {"data": [ged_service.document_view(d) for d in documents], "count": len(documents)}


@router.get("/documents/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        document = ged_service.get_document(db, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    ged_service.log_audit(db, document.id, "view", current_user.email, _role(current_user))
    db.commit()
    return ged_service.document_view(document, include_ocr=True)


@router.put("/documents/{document_id}")
def update_document(
    document_id: int,
    data: DocumentMetaUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    try:
        document = ged_service.update_document(db, document_id, data, current_user.email, _role(current_user))
    except ValueError as exc:
        status = 404 if "non trouvé" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc))
    return ged_service.document_view(document)


@router.post("/documents/{document_id}/versions", status_code=201)
async def add_version(
    document_id: int,
    file: UploadFile = File(...),
    comment: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    content = await file.read()
    try:
        document = ged_service.add_version(
            db,
            document_id,
            file.filename or "document",
            content,
            file.content_type,
            current_user.email,
            _role(current_user),
            comment,
        )
    except ValueError as exc:
        status = 404 if "non trouvé" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc))
    return ged_service.document_view(document)


@router.get("/documents/{document_id}/download")
def download_document(document_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        document = ged_service.get_document(db, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not document.storage_path or not Path(document.storage_path).is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    ged_service.log_audit(db, document.id, "download", current_user.email, _role(current_user))
    db.commit()
    return Response(
        content=Path(document.storage_path).read_bytes(),
        media_type=document.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{document.original_filename or "document"}"'},
    )


@router.delete("/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db), current_user=Depends(require_delete)):
    try:
        document = ged_service.delete_document(db, document_id, current_user.email, _role(current_user))
    except ValueError as exc:
        status = 404 if "non trouvé" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc))
    return {"deleted": True, "id": document.id}


@router.post("/documents/{document_id}/erase")
def erase_document(
    document_id: int, data: EraseRequest, db: Session = Depends(get_db), current_user=Depends(require_admin)
):
    try:
        document = ged_service.erase_document(db, document_id, data.reason, current_user.email, _role(current_user))
    except ValueError as exc:
        status = 404 if "non trouvé" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc))
    return {"erased": True, "id": document.id, "reason": document.deleted_reason}


@router.get("/documents/{document_id}/audit")
def document_audit(document_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        ged_service.get_document(db, document_id, include_deleted=True)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": ged_service.list_audit(db, document_id)}


@router.post("/documents/{document_id}/ocr")
def rerun_ocr(document_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        document = ged_service.get_document(db, document_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if not document.storage_path:
        raise HTTPException(status_code=400, detail="Aucun fichier à analyser")
    ged_service.apply_ocr(document, Path(document.storage_path))
    ged_service.log_audit(db, document.id, "classify", current_user.email, _role(current_user))
    db.commit()
    return ged_service.document_view(document, include_ocr=True)


# ---------------------------------------------------------------------------
# Génération
# ---------------------------------------------------------------------------
@router.get("/templates")
def list_templates(db: Session = Depends(get_db), current_user=Depends(require_read)):
    templates = ged_service.list_templates(db)
    return {"data": [ged_service.template_view(t) for t in templates], "count": len(templates)}


@router.post("/templates", status_code=201)
def create_template(data: TemplateCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        template = ged_service.create_template(db, data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ged_service.template_view(template)


@router.put("/templates/{template_id}")
def update_template(
    template_id: int, data: TemplateUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)
):
    try:
        template = ged_service.update_template(db, template_id, data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ged_service.template_view(template)


@router.post("/generate")
def generate_document(
    data: GenerateDocumentRequest, db: Session = Depends(get_db), current_user=Depends(require_write)
):
    try:
        return ged_service.generate_document(db, data, current_user.email, _role(current_user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Signature
# ---------------------------------------------------------------------------
@router.post("/signatures", status_code=201)
def create_envelope(data: EnvelopeCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        envelope = ged_service.create_envelope(db, data, current_user.email)
    except ValueError as exc:
        status = 404 if "non trouvé" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc))
    return ged_service.envelope_view(envelope)


@router.post("/signatures/{envelope_id}/send")
def send_envelope(envelope_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        envelope = ged_service.send_envelope(db, envelope_id, current_user.email)
    except ValueError as exc:
        status = 404 if "non trouvée" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc))
    return ged_service.envelope_view(envelope)


@router.get("/signatures/{envelope_id}")
def get_envelope(envelope_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    from app.models.ged import GedSignatureEnvelope

    envelope = db.query(GedSignatureEnvelope).filter(GedSignatureEnvelope.id == envelope_id).first()
    if not envelope:
        raise HTTPException(status_code=404, detail="Enveloppe non trouvée")
    return ged_service.envelope_view(envelope)


@router.post("/signatures/{envelope_id}/signers/{signer_id}/sign")
def sign_document(
    envelope_id: int,
    signer_id: int,
    data: SignRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    ip = request.client.host if request.client else "0.0.0.0"
    try:
        envelope = ged_service.sign_as(
            db, envelope_id, signer_id, data.typed_signature, data.consent, ip, request.headers.get("user-agent")
        )
    except ValueError as exc:
        status = 404 if "introuvable" in str(exc) or "non trouvée" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc))
    return ged_service.envelope_view(envelope)


@router.post("/signatures/{envelope_id}/signers/{signer_id}/decline")
def decline_signature(
    envelope_id: int,
    signer_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    try:
        envelope = ged_service.decline_signature(db, envelope_id, signer_id, None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ged_service.envelope_view(envelope)


@router.get("/signatures/{envelope_id}/evidence")
def download_evidence(envelope_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    from app.models.ged import GedSignatureEnvelope

    envelope = db.query(GedSignatureEnvelope).filter(GedSignatureEnvelope.id == envelope_id).first()
    if not envelope or not envelope.evidence_path or not Path(envelope.evidence_path).is_file():
        raise HTTPException(status_code=404, detail="Dossier de preuve indisponible")
    return Response(
        content=Path(envelope.evidence_path).read_bytes(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="preuve-{envelope.reference}.pdf"'},
    )
