# backend/app/routes/documents.py - CODE COMPLET CORRIGÉ

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
import os
import uuid
import aiofiles

from app.database import get_db
from app.auth import require_write, require_read
from app.models.property import Property, PropertyDocument
from app.config import settings

router = APIRouter(prefix="/api/properties/{property_id}/documents", tags=["Documents"])

ALLOWED_DOC_TYPES = [
    "title_deed",
    "blueprint",
    "technical_diagnosis",
    "compliance_cert",
    "hoa_rules",
    "insurance",
    "tax_document",
    "lease_agreement",
    "inventory",
    "other"
]

ALLOWED_EXTENSIONS = ["pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png", "dwg", "dxf"]


@router.get("/")
def list_documents(
    property_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Lister les documents d'un bien."""
    property_obj = db.query(Property).filter(Property.id == property_id).first()
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")

    documents = db.query(PropertyDocument).filter(
        PropertyDocument.property_id == property_id
    ).order_by(PropertyDocument.uploaded_at.desc()).all()

    return {
        "data": [
            {
                "id": doc.id,
                "type": doc.type,
                "title": doc.title,
                "filename": doc.filename,
                "url": doc.url,
                "file_size": doc.file_size,
                "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            }
            for doc in documents
        ],
        "total": len(documents)
    }


@router.post("/")
async def upload_document(
    property_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form("other"),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Uploader un document pour un bien."""
    property_obj = db.query(Property).filter(Property.id == property_id).first()
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")

    # Valider l'extension
    ext = file.filename.split('.')[-1].lower() if '.' in file.filename else 'pdf'
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Extension non autorisée: {ext}")

    # Valider le type
    if doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"Type de document invalide: {doc_type}")

    # Lire le contenu
    content = await file.read()

    if len(content) > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Fichier trop volumineux (max {settings.MAX_UPLOAD_SIZE} octets)",
        )

    # ✅ Chemin de sauvegarde : uploads/{property_id}/documents/
    upload_dir = os.path.join(settings.UPLOAD_DIR, str(property_id), "documents")
    os.makedirs(upload_dir, exist_ok=True)

    # Nom unique avec UUID
    unique_name = f"{uuid.uuid4()}.{ext}"
    file_path = os.path.join(upload_dir, unique_name)

    # Sauvegarder le fichier
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)

    # ✅ URL stockée en base : relative au dossier uploads
    stored_url = f"/uploads/{property_id}/documents/{unique_name}"

    # Créer l'entrée en base
    document = PropertyDocument(
        property_id=property_id,
        type=doc_type,
        title=title or file.filename,
        url=stored_url,
        filename=file.filename,
        file_size=len(content)
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    return {
        "id": document.id,
        "type": document.type,
        "title": document.title,
        "filename": document.filename,
        "url": document.url,
        "file_size": document.file_size,
        "uploaded_at": document.uploaded_at.isoformat() if document.uploaded_at else None,
    }


@router.delete("/{document_id}")
def delete_document(
    property_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Supprimer un document."""
    document = db.query(PropertyDocument).filter(
        PropertyDocument.id == document_id,
        PropertyDocument.property_id == property_id
    ).first()

    if not document:
        raise HTTPException(status_code=404, detail="Document non trouvé")

    # ✅ Retrouver le fichier à partir de l'URL stockée
    # URL = /uploads/{property_id}/documents/{unique_name}.pdf
    url_parts = document.url.split('/')
    real_filename = url_parts[-1]
    
    real_path = os.path.join(
        settings.UPLOAD_DIR, str(property_id), "documents", real_filename
    )

    if os.path.exists(real_path):
        os.remove(real_path)

    db.delete(document)
    db.commit()

    return {"message": "Document supprimé", "document_id": document_id}


@router.get("/types")
def get_document_types():
    """Retourne les types de documents disponibles."""
    return {
        "types": [
            {"value": "title_deed", "label": "Titre de propriété", "icon": "📜"},
            {"value": "blueprint", "label": "Plan architectural", "icon": "📐"},
            {"value": "technical_diagnosis", "label": "Diagnostic technique", "icon": "🔍"},
            {"value": "compliance_cert", "label": "Certificat de conformité", "icon": "✅"},
            {"value": "hoa_rules", "label": "Règlement de copropriété", "icon": "📋"},
            {"value": "insurance", "label": "Attestation d'assurance", "icon": "🛡️"},
            {"value": "tax_document", "label": "Document fiscal", "icon": "💰"},
            {"value": "lease_agreement", "label": "Bail / Contrat de location", "icon": "📝"},
            {"value": "inventory", "label": "État des lieux", "icon": "📦"},
            {"value": "other", "label": "Autre document", "icon": "📄"},
        ]
    }