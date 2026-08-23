"""Services métier du module 11 : gestion documentaire (GED).

Les envois vers DocuSign / Yousign / HelloSign ne sont pas simulés : les
enveloppes et le circuit de signature sont journalisés, avec une signature
simple interne (consentement, horodatage, empreinte) et un dossier de
preuve. L'OCR réutilise le moteur existant ; une extraction impossible
n'entraîne jamais une classification « certaine ».
"""

from __future__ import annotations

import hashlib
import io
import re
import secrets
import unicodedata
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.ged import (
    GedAuditLog,
    GedDocument,
    GedDocumentVersion,
    GedFolder,
    GedSettings,
    GedSignatureEnvelope,
    GedSigner,
    GedTemplate,
)
from app.models.owner import Owner
from app.models.property import Property
from app.models.tenant import Lease, Tenant
from app.services.communication_service import merge_context, render_template

DEFAULT_EXTENSIONS = ["pdf", "jpg", "jpeg", "png", "doc", "docx", "xls", "xlsx"]

DOCUMENT_TYPES = [
    "bail",
    "quittance",
    "appel_loyer",
    "etat_des_lieux",
    "lettre_relance",
    "attestation_loyer",
    "lettre_conge",
    "mise_en_demeure",
    "mandat_gestion",
    "avis_echeance",
    "regularisation_charges",
    "identity",
    "diagnostic",
    "insurance",
    "facture",
    "other",
]

CLASSIFICATION_KEYWORDS = {
    "bail": ("contrat de location", "bail", "locataire", "bailleur"),
    "quittance": ("quittance", "loyer recu", "acquitte"),
    "appel_loyer": ("appel de loyer", "avis d'echeance", "montant du"),
    "etat_des_lieux": ("etat des lieux", "constat", "compteur"),
    "lettre_relance": ("relance", "impaye", "rappel amiable"),
    "attestation_loyer": ("attestation de loyer", "atteste que"),
    "lettre_conge": ("conge", "preavis", "resiliation"),
    "mise_en_demeure": ("mise en demeure", "demeure de"),
    "mandat_gestion": ("mandat de gestion", "mandataire"),
    "avis_echeance": ("avis d'echeance", "echeance"),
    "regularisation_charges": ("regularisation de charges", "provisions pour charges"),
    "identity": ("carte nationale", "passeport", "republique francaise"),
    "diagnostic": ("diagnostic", "dpe", "amiante", "plomb"),
    "insurance": ("attestation d'assurance", "multirisque", "assureur"),
    "facture": ("facture", "total ttc", "numero de facture", "date d'echeance"),
}

SYSTEM_DOC_TEMPLATES: List[Dict[str, Any]] = [
    {
        "key": "bail",
        "name": "Bail d'habitation",
        "category": "bail",
        "body": (
            "CONTRAT DE LOCATION\n\n"
            "Entre le bailleur et {{prenom}} {{nom}}, locataire.\n"
            "Bien : {{bien}} — {{adresse}}, {{ville}}.\n"
            "Prise d'effet : {{date_debut}} — Fin : {{date_fin}}.\n"
            "Loyer hors charges : {{loyer}} € — Charges : {{charges}} €.\n"
            "Référence : {{reference_bail}}\n"
        ),
        "variables": ["prenom", "nom", "bien", "adresse", "ville", "date_debut", "date_fin", "loyer", "charges", "reference_bail"],
    },
    {
        "key": "quittance",
        "name": "Quittance de loyer",
        "category": "quittance",
        "body": (
            "QUITTANCE DE LOYER\n\n"
            "Je soussigné, gestionnaire de {{agence}}, reconnais avoir reçu de "
            "{{prenom}} {{nom}} la somme de {{montant}} € au titre du loyer "
            "de la période {{periode}} pour le bien {{bien}}.\n"
        ),
        "variables": ["agence", "prenom", "nom", "montant", "periode", "bien"],
    },
    {
        "key": "appel_loyer",
        "name": "Appel de loyer",
        "category": "appel_loyer",
        "body": (
            "APPEL DE LOYER\n\n"
            "Locataire : {{prenom}} {{nom}}\n"
            "Bien : {{bien}}\n"
            "Période : {{periode}}\n"
            "Montant dû : {{montant}} € — Échéance : {{echeance}}\n"
        ),
        "variables": ["prenom", "nom", "bien", "periode", "montant", "echeance"],
    },
    {
        "key": "etat_des_lieux",
        "name": "État des lieux",
        "category": "etat_des_lieux",
        "body": (
            "ÉTAT DES LIEUX\n\n"
            "Bien : {{bien}} — {{adresse}}, {{ville}}\n"
            "Locataire : {{prenom}} {{nom}}\n"
            "Date : {{date}}\n"
            "Type : {{type_edl}}\n"
        ),
        "variables": ["bien", "adresse", "ville", "prenom", "nom", "date", "type_edl"],
    },
    {
        "key": "lettre_relance",
        "name": "Lettre de relance",
        "category": "lettre_relance",
        "body": (
            "LETTRE DE RELANCE\n\n"
            "{{prenom}} {{nom}},\n"
            "Sauf erreur, le loyer de {{periode}} ({{montant}} €) demeure impayé "
            "depuis le {{echeance}} pour le bien {{bien}}.\n"
            "Merci de régulariser sans délai.\n"
        ),
        "variables": ["prenom", "nom", "periode", "montant", "echeance", "bien"],
    },
    {
        "key": "attestation_loyer",
        "name": "Attestation de loyer",
        "category": "attestation_loyer",
        "body": (
            "ATTESTATION DE LOYER\n\n"
            "{{agence}} atteste que {{prenom}} {{nom}} est locataire du bien "
            "{{bien}} pour un loyer mensuel de {{loyer}} € hors charges.\n"
            "Bail : {{reference_bail}} — du {{date_debut}} au {{date_fin}}.\n"
        ),
        "variables": ["agence", "prenom", "nom", "bien", "loyer", "reference_bail", "date_debut", "date_fin"],
    },
    {
        "key": "lettre_conge",
        "name": "Lettre de congé",
        "category": "lettre_conge",
        "body": (
            "LETTRE DE CONGÉ\n\n"
            "{{prenom}} {{nom}} donne congé pour le bien {{bien}}.\n"
            "Date d'effet souhaitée : {{date_effet}}\n"
            "Motif : {{motif}}\n"
        ),
        "variables": ["prenom", "nom", "bien", "date_effet", "motif"],
    },
    {
        "key": "mise_en_demeure",
        "name": "Mise en demeure",
        "category": "mise_en_demeure",
        "body": (
            "MISE EN DEMEURE\n\n"
            "{{prenom}} {{nom}},\n"
            "Vous êtes mis en demeure de régler la somme de {{montant}} € "
            "au titre du loyer {{periode}} du bien {{bien}}, sous huit jours.\n"
        ),
        "variables": ["prenom", "nom", "montant", "periode", "bien"],
    },
    {
        "key": "mandat_gestion",
        "name": "Mandat de gestion",
        "category": "mandat_gestion",
        "body": (
            "MANDAT DE GESTION\n\n"
            "Le propriétaire {{proprietaire}} confie à {{agence}} la gestion du bien "
            "{{bien}} situé {{adresse}}, {{ville}}.\n"
            "Honoraires : {{honoraires}}\n"
        ),
        "variables": ["proprietaire", "agence", "bien", "adresse", "ville", "honoraires"],
    },
    {
        "key": "avis_echeance",
        "name": "Avis d'échéance",
        "category": "avis_echeance",
        "body": (
            "AVIS D'ÉCHÉANCE\n\n"
            "Locataire : {{prenom}} {{nom}}\n"
            "Bien : {{bien}}\n"
            "Échéance du {{echeance}} — Montant : {{montant}} €\n"
            "Période : {{periode}}\n"
        ),
        "variables": ["prenom", "nom", "bien", "echeance", "montant", "periode"],
    },
    {
        "key": "regularisation_charges",
        "name": "Régularisation de charges",
        "category": "regularisation_charges",
        "body": (
            "RÉGULARISATION DE CHARGES\n\n"
            "Locataire : {{prenom}} {{nom}} — Bien : {{bien}}\n"
            "Année : {{annee}}\n"
            "Provisions versées : {{provisions}} €\n"
            "Charges réelles : {{reel}} €\n"
            "Solde : {{solde}} €\n"
        ),
        "variables": ["prenom", "nom", "bien", "annee", "provisions", "reel", "solde"],
    },
]


def generate_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.lower()).strip()


def get_settings(db: Session) -> GedSettings:
    row = db.query(GedSettings).first()
    if not row:
        row = GedSettings(
            max_upload_mb=20,
            compress_images=True,
            default_retention_years=10,
            allowed_extensions=list(DEFAULT_EXTENSIONS),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update_settings(db: Session, data) -> GedSettings:
    row = get_settings(db)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


def settings_view(row: GedSettings) -> Dict[str, Any]:
    return {
        "max_upload_mb": row.max_upload_mb,
        "compress_images": row.compress_images,
        "default_retention_years": row.default_retention_years,
        "allowed_extensions": row.allowed_extensions or list(DEFAULT_EXTENSIONS),
    }


def ensure_templates(db: Session) -> None:
    if db.query(GedTemplate).count() == 0:
        for item in SYSTEM_DOC_TEMPLATES:
            db.add(
                GedTemplate(
                    key=item["key"],
                    name=item["name"],
                    category=item["category"],
                    body=item["body"],
                    variables=item["variables"],
                    is_system=True,
                )
            )
        db.commit()


def log_audit(
    db: Session,
    document_id: int,
    action: str,
    actor: str,
    actor_role: Optional[str] = None,
    details: Optional[Dict] = None,
) -> None:
    db.add(
        GedAuditLog(
            document_id=document_id,
            action=action,
            actor=actor,
            actor_role=actor_role,
            details=details or {},
        )
    )


# ---------------------------------------------------------------------------
# Arborescence
# ---------------------------------------------------------------------------
def create_folder(db: Session, data, actor: str) -> GedFolder:
    if data.parent_id:
        parent = db.query(GedFolder).filter(GedFolder.id == data.parent_id).first()
        if not parent:
            raise ValueError("Dossier parent introuvable")
    folder = GedFolder(
        name=data.name,
        parent_id=data.parent_id,
        scope=data.scope,
        property_id=data.property_id,
        owner_id=data.owner_id,
        tenant_id=data.tenant_id,
        lease_id=data.lease_id,
        document_type=data.document_type,
        created_by=actor,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


def update_folder(db: Session, folder_id: int, data) -> GedFolder:
    folder = db.query(GedFolder).filter(GedFolder.id == folder_id).first()
    if not folder:
        raise ValueError("Dossier non trouvé")
    payload = data.model_dump(exclude_unset=True)
    if "parent_id" in payload and payload["parent_id"] == folder.id:
        raise ValueError("Un dossier ne peut pas être son propre parent")
    for field, value in payload.items():
        setattr(folder, field, value)
    db.commit()
    db.refresh(folder)
    return folder


def list_folders(
    db: Session,
    *,
    parent_id: Optional[int] = None,
    scope: Optional[str] = None,
    property_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    lease_id: Optional[int] = None,
) -> List[GedFolder]:
    query = db.query(GedFolder)
    if parent_id is not None:
        query = query.filter(GedFolder.parent_id == parent_id)
    if scope:
        query = query.filter(GedFolder.scope == scope)
    if property_id:
        query = query.filter(GedFolder.property_id == property_id)
    if owner_id:
        query = query.filter(GedFolder.owner_id == owner_id)
    if tenant_id:
        query = query.filter(GedFolder.tenant_id == tenant_id)
    if lease_id:
        query = query.filter(GedFolder.lease_id == lease_id)
    return query.order_by(GedFolder.name).all()


def folder_tree(db: Session, root_id: Optional[int] = None) -> List[Dict[str, Any]]:
    folders = db.query(GedFolder).order_by(GedFolder.name).all()
    by_parent: Dict[Optional[int], List[GedFolder]] = {}
    for folder in folders:
        by_parent.setdefault(folder.parent_id, []).append(folder)

    def build(parent: Optional[int]) -> List[Dict[str, Any]]:
        return [
            {
                **folder_view(folder),
                "children": build(folder.id),
            }
            for folder in by_parent.get(parent, [])
        ]

    if root_id:
        root = db.query(GedFolder).filter(GedFolder.id == root_id).first()
        if not root:
            raise ValueError("Dossier non trouvé")
        return [{**folder_view(root), "children": build(root.id)}]
    return build(None)


def folder_view(folder: GedFolder) -> Dict[str, Any]:
    return {
        "id": folder.id,
        "name": folder.name,
        "parent_id": folder.parent_id,
        "scope": folder.scope,
        "property_id": folder.property_id,
        "owner_id": folder.owner_id,
        "tenant_id": folder.tenant_id,
        "lease_id": folder.lease_id,
        "document_type": folder.document_type,
        "created_by": folder.created_by,
    }


def ensure_scope_folder(
    db: Session,
    *,
    scope: str,
    name: str,
    actor: str,
    property_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    document_type: Optional[str] = None,
) -> GedFolder:
    query = db.query(GedFolder).filter(GedFolder.scope == scope, GedFolder.parent_id == None)  # noqa: E711
    if property_id:
        query = query.filter(GedFolder.property_id == property_id)
    if owner_id:
        query = query.filter(GedFolder.owner_id == owner_id)
    if tenant_id:
        query = query.filter(GedFolder.tenant_id == tenant_id)
    if lease_id:
        query = query.filter(GedFolder.lease_id == lease_id)
    if document_type:
        query = query.filter(GedFolder.document_type == document_type)
    folder = query.first()
    if folder:
        return folder
    folder = GedFolder(
        name=name,
        scope=scope,
        property_id=property_id,
        owner_id=owner_id,
        tenant_id=tenant_id,
        lease_id=lease_id,
        document_type=document_type,
        created_by=actor,
    )
    db.add(folder)
    db.flush()
    return folder


# ---------------------------------------------------------------------------
# Upload / versioning / compression
# ---------------------------------------------------------------------------
def _compress_if_needed(content: bytes, filename: str, enabled: bool) -> Tuple[bytes, str]:
    ext = Path(filename).suffix.lower().lstrip(".")
    if not enabled or ext not in {"jpg", "jpeg", "png"}:
        return content, ext
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(content))
        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=75, optimize=True)
        return buffer.getvalue(), "jpg"
    except Exception:
        return content, ext


def store_file(content: bytes, filename: str, document_id: int) -> Path:
    directory = Path(settings.private_upload_dir_path) / "ged" / str(document_id)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix or ".bin"
    path = directory / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(content)
    return path


def _retain_until(years: int) -> date:
    today = date.today()
    try:
        return today.replace(year=today.year + years)
    except ValueError:
        return today.replace(month=2, day=28, year=today.year + years)


def create_document(
    db: Session,
    *,
    title: str,
    filename: str,
    content: bytes,
    mime_type: Optional[str],
    document_type: str,
    actor: str,
    actor_role: Optional[str] = None,
    folder_id: Optional[int] = None,
    tags: Optional[List[str]] = None,
    property_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    run_ocr: bool = True,
) -> GedDocument:
    cfg = get_settings(db)
    ext = Path(filename).suffix.lower().lstrip(".")
    allowed = cfg.allowed_extensions or list(DEFAULT_EXTENSIONS)
    if ext not in allowed:
        raise ValueError(f"Extension non autorisée : {ext}")
    max_bytes = (cfg.max_upload_mb or 20) * 1024 * 1024
    if len(content) > max_bytes:
        raise ValueError(f"Fichier trop volumineux (max {cfg.max_upload_mb} Mo)")
    content, new_ext = _compress_if_needed(content, filename, bool(cfg.compress_images))
    if new_ext != ext and filename.lower().endswith(ext):
        filename = str(Path(filename).with_suffix(f".{new_ext}"))
        mime_type = "image/jpeg"

    if document_type not in DOCUMENT_TYPES:
        document_type = "other"

    document = GedDocument(
        reference=generate_reference("DOC"),
        folder_id=folder_id,
        title=title or filename,
        document_type=document_type,
        original_filename=filename,
        mime_type=mime_type,
        file_size=len(content),
        file_hash=hashlib.sha256(content).hexdigest(),
        current_version=1,
        tags=tags or [],
        property_id=property_id,
        owner_id=owner_id,
        tenant_id=tenant_id,
        lease_id=lease_id,
        retention_years=cfg.default_retention_years,
        retain_until=_retain_until(cfg.default_retention_years or 10),
        created_by=actor,
    )
    db.add(document)
    db.flush()
    path = store_file(content, filename, document.id)
    document.storage_path = str(path)
    db.add(
        GedDocumentVersion(
            document_id=document.id,
            version_number=1,
            storage_path=str(path),
            file_size=len(content),
            file_hash=document.file_hash,
            mime_type=document.mime_type,
            original_filename=filename,
            comment="Version initiale",
            created_by=actor,
        )
    )
    if run_ocr:
        apply_ocr(document, path)
    log_audit(db, document.id, "upload", actor, actor_role, {"filename": filename})
    db.commit()
    db.refresh(document)
    return document


def add_version(
    db: Session,
    document_id: int,
    filename: str,
    content: bytes,
    mime_type: Optional[str],
    actor: str,
    actor_role: Optional[str] = None,
    comment: Optional[str] = None,
) -> GedDocument:
    document = get_document(db, document_id)
    if document.legal_hold:
        raise ValueError("Document gelé : versioning interdit")
    cfg = get_settings(db)
    ext = Path(filename).suffix.lower().lstrip(".")
    allowed = cfg.allowed_extensions or list(DEFAULT_EXTENSIONS)
    if ext not in allowed:
        raise ValueError(f"Extension non autorisée : {ext}")
    max_bytes = (cfg.max_upload_mb or 20) * 1024 * 1024
    if len(content) > max_bytes:
        raise ValueError(f"Fichier trop volumineux (max {cfg.max_upload_mb} Mo)")
    content, _ = _compress_if_needed(content, filename, bool(cfg.compress_images))
    path = store_file(content, filename, document.id)
    document.current_version = (document.current_version or 1) + 1
    document.storage_path = str(path)
    document.original_filename = filename
    document.mime_type = mime_type
    document.file_size = len(content)
    document.file_hash = hashlib.sha256(content).hexdigest()
    db.add(
        GedDocumentVersion(
            document_id=document.id,
            version_number=document.current_version,
            storage_path=str(path),
            file_size=len(content),
            file_hash=document.file_hash,
            mime_type=mime_type,
            original_filename=filename,
            comment=comment or f"Version {document.current_version}",
            created_by=actor,
        )
    )
    apply_ocr(document, path)
    log_audit(db, document.id, "update", actor, actor_role, {"version": document.current_version})
    db.commit()
    db.refresh(document)
    return document


def get_document(db: Session, document_id: int, include_deleted: bool = False) -> GedDocument:
    query = db.query(GedDocument).filter(GedDocument.id == document_id)
    if not include_deleted:
        query = query.filter(GedDocument.is_deleted == False)  # noqa: E712
    document = query.first()
    if not document:
        raise ValueError("Document non trouvé")
    return document


def update_document(db: Session, document_id: int, data, actor: str, actor_role: Optional[str] = None) -> GedDocument:
    document = get_document(db, document_id)
    payload = data.model_dump(exclude_unset=True)
    if payload.get("legal_hold") and actor_role not in (None, "admin", "manager"):
        raise ValueError("Gel juridique réservé aux gestionnaires")
    if "retention_years" in payload and payload["retention_years"]:
        document.retain_until = _retain_until(payload["retention_years"])
    if "classification" in payload and payload["classification"]:
        document.classification_source = "manual"
    for field, value in payload.items():
        setattr(document, field, value)
    log_audit(db, document.id, "update", actor, actor_role, payload)
    db.commit()
    db.refresh(document)
    return document


def delete_document(db: Session, document_id: int, actor: str, actor_role: Optional[str] = None) -> GedDocument:
    document = get_document(db, document_id)
    if document.legal_hold:
        raise ValueError("Document sous gel juridique : suppression interdite")
    document.is_deleted = True
    document.deleted_at = _now()
    document.deleted_reason = "suppression"
    log_audit(db, document.id, "delete", actor, actor_role)
    db.commit()
    db.refresh(document)
    return document


def erase_document(db: Session, document_id: int, reason: str, actor: str, actor_role: Optional[str] = None) -> GedDocument:
    """Effacement RGPD : refuse si gel juridique ou durée de rétention légale en cours."""
    document = get_document(db, document_id, include_deleted=True)
    if document.legal_hold:
        raise ValueError("Effacement impossible : gel juridique actif")
    if document.retain_until and document.retain_until > date.today():
        raise ValueError(
            f"Effacement impossible avant la fin de rétention ({document.retain_until.isoformat()})"
        )
    if document.storage_path and Path(document.storage_path).exists():
        Path(document.storage_path).unlink()
    for version in document.versions:
        if version.storage_path and Path(version.storage_path).exists():
            Path(version.storage_path).unlink()
        version.storage_path = ""
        version.file_hash = None
    document.storage_path = None
    document.ocr_text = None
    document.extracted_data = {}
    document.title = "Document anonymisé"
    document.original_filename = None
    document.is_deleted = True
    document.deleted_at = _now()
    document.deleted_reason = reason
    log_audit(db, document.id, "erase", actor, actor_role, {"reason": reason})
    db.commit()
    db.refresh(document)
    return document


# ---------------------------------------------------------------------------
# OCR / classification
# ---------------------------------------------------------------------------
def apply_ocr(document: GedDocument, path: Path) -> None:
    text = ""
    confidence = 0.0
    engine = "none"
    try:
        from app.services.ocr_service import analyse_document
        from app.models.tenant import DocumentType

        mapping = {
            "identity": DocumentType.IDENTITY,
            "bail": DocumentType.LEASE,
        }
        analysis = analyse_document(str(path), mapping.get(document.document_type, DocumentType.OTHER))
        text = analysis.get("text") or ""
        confidence = analysis.get("confidence") or 0
        engine = analysis.get("engine") or "ocr"
    except Exception:
        if path.suffix.lower() == ".pdf":
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(path))
                text = "\n".join((page.extract_text() or "") for page in reader.pages[:10])
                confidence = 90.0 if len(text.strip()) >= 20 else 0
                engine = "pypdf"
            except Exception:
                text, confidence, engine = "", 0, "failed"

    document.ocr_text = (text or "")[:100_000]
    document.ocr_confidence = round(float(confidence or 0), 2)
    extracted = extract_key_fields(text)
    extracted["engine"] = engine
    document.extracted_data = extracted
    auto_type, score = classify_text(text)
    if auto_type and document.classification_source != "manual":
        document.classification = auto_type
        document.classification_source = "auto"
        if document.document_type in (None, "other") and score >= 2:
            document.document_type = auto_type


def extract_key_fields(text: str) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    amounts = re.findall(r"(\d[\d\s]{0,8}(?:[.,]\d{2})?)\s*€", text or "")
    if amounts:
        data["montants"] = [item.replace(" ", "").replace(",", ".") for item in amounts[:8]]
    dates = re.findall(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b", text or "")
    if dates:
        data["dates"] = dates[:8]
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text or "", flags=re.I)
    if emails:
        data["emails"] = emails[:5]
    refs = re.findall(r"\b(?:BAIL|LEA|DOC|PAY|REC)-[A-Z0-9]+\b", text or "", flags=re.I)
    if refs:
        data["references"] = refs[:5]
    return data


def classify_text(text: str) -> Tuple[Optional[str], int]:
    normalized = _normalize(text)
    if len(normalized) < 20:
        return None, 0
    best, score = None, 0
    for doc_type, keywords in CLASSIFICATION_KEYWORDS.items():
        hits = sum(1 for keyword in keywords if keyword in normalized)
        if hits > score:
            best, score = doc_type, hits
    return best, score


# ---------------------------------------------------------------------------
# Recherche
# ---------------------------------------------------------------------------
def search_documents(
    db: Session,
    *,
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
    limit: int = 100,
) -> List[GedDocument]:
    query = db.query(GedDocument).filter(GedDocument.is_deleted == False)  # noqa: E712
    if document_type:
        query = query.filter(GedDocument.document_type == document_type)
    if property_id:
        query = query.filter(GedDocument.property_id == property_id)
    if owner_id:
        query = query.filter(GedDocument.owner_id == owner_id)
    if tenant_id:
        query = query.filter(GedDocument.tenant_id == tenant_id)
    if lease_id:
        query = query.filter(GedDocument.lease_id == lease_id)
    if folder_id:
        query = query.filter(GedDocument.folder_id == folder_id)
    if date_from:
        query = query.filter(GedDocument.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(GedDocument.created_at <= datetime.combine(date_to, datetime.max.time()))
    if tag:
        documents = query.order_by(GedDocument.created_at.desc()).all()
        documents = [d for d in documents if tag in (d.tags or [])]
    else:
        documents = query.order_by(GedDocument.created_at.desc()).limit(500).all()
    if q:
        needle = q.lower()
        documents = [
            d
            for d in documents
            if needle in (d.title or "").lower()
            or needle in (d.ocr_text or "").lower()
            or needle in (d.original_filename or "").lower()
            or needle in (d.reference or "").lower()
            or any(needle in str(t).lower() for t in (d.tags or []))
        ]
    return documents[:limit]


def document_view(document: GedDocument, include_ocr: bool = False) -> Dict[str, Any]:
    payload = {
        "id": document.id,
        "reference": document.reference,
        "title": document.title,
        "document_type": document.document_type,
        "folder_id": document.folder_id,
        "original_filename": document.original_filename,
        "mime_type": document.mime_type,
        "file_size": document.file_size,
        "file_hash": document.file_hash,
        "current_version": document.current_version,
        "tags": document.tags or [],
        "classification": document.classification,
        "classification_source": document.classification_source,
        "extracted_data": document.extracted_data or {},
        "ocr_confidence": document.ocr_confidence,
        "property_id": document.property_id,
        "owner_id": document.owner_id,
        "tenant_id": document.tenant_id,
        "lease_id": document.lease_id,
        "retention_years": document.retention_years,
        "retain_until": document.retain_until.isoformat() if document.retain_until else None,
        "legal_hold": document.legal_hold,
        "created_by": document.created_by,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "download_url": f"/api/ged/documents/{document.id}/download",
        "versions": [
            {
                "id": v.id,
                "version_number": v.version_number,
                "file_size": v.file_size,
                "file_hash": v.file_hash,
                "comment": v.comment,
                "created_by": v.created_by,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in sorted(document.versions, key=lambda x: x.version_number)
        ],
    }
    if include_ocr:
        payload["ocr_text"] = document.ocr_text
    return payload


# ---------------------------------------------------------------------------
# Génération de documents
# ---------------------------------------------------------------------------
def list_templates(db: Session) -> List[GedTemplate]:
    ensure_templates(db)
    return db.query(GedTemplate).order_by(GedTemplate.category, GedTemplate.name).all()


def update_template(db: Session, template_id: int, data, actor: str) -> GedTemplate:
    template = db.query(GedTemplate).filter(GedTemplate.id == template_id).first()
    if not template:
        raise ValueError("Modèle non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    template.updated_by = actor
    db.commit()
    db.refresh(template)
    return template


def create_template(db: Session, data, actor: str) -> GedTemplate:
    if db.query(GedTemplate).filter(GedTemplate.key == data.key).first():
        raise ValueError("Une clé de modèle existe déjà")
    template = GedTemplate(
        key=data.key,
        name=data.name,
        category=data.category,
        body=data.body,
        variables=data.variables,
        is_system=False,
        updated_by=actor,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def template_view(template: GedTemplate) -> Dict[str, Any]:
    return {
        "id": template.id,
        "key": template.key,
        "name": template.name,
        "category": template.category,
        "body": template.body,
        "variables": template.variables or [],
        "is_system": template.is_system,
        "is_active": template.is_active,
    }


def render_document_text(db: Session, data) -> Tuple[GedTemplate, str, Dict[str, Any]]:
    ensure_templates(db)
    template = db.query(GedTemplate).filter(GedTemplate.key == data.template_key).first()
    if not template or not template.is_active:
        raise ValueError("Modèle introuvable ou inactif")
    ctx = merge_context(
        db,
        tenant_id=data.tenant_id,
        owner_id=data.owner_id,
        property_id=data.property_id,
        lease_id=data.lease_id,
        extra=data.variables,
    )
    return template, render_template(template.body, ctx), ctx


def build_pdf(title: str, body: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(title.replace("\n", "<br/>"), styles["Title"]), Spacer(1, 12)]
    for paragraph in body.split("\n"):
        story.append(Paragraph((paragraph or " ").replace(" ", "&nbsp;") if paragraph == "" else paragraph, styles["BodyText"]))
        story.append(Spacer(1, 6))
    doc.build(story)
    return buffer.getvalue()


def generate_document(db: Session, data, actor: str, actor_role: Optional[str] = None) -> Dict[str, Any]:
    template, text, ctx = render_document_text(db, data)
    if data.preview_only:
        return {
            "preview": True,
            "template_key": template.key,
            "title": data.title or template.name,
            "text": text,
            "variables": ctx,
        }
    pdf = build_pdf(data.title or template.name, text)
    document = create_document(
        db,
        title=data.title or template.name,
        filename=f"{template.key}.pdf",
        content=pdf,
        mime_type="application/pdf",
        document_type=template.category,
        actor=actor,
        actor_role=actor_role,
        folder_id=data.folder_id,
        property_id=data.property_id,
        owner_id=data.owner_id,
        tenant_id=data.tenant_id,
        lease_id=data.lease_id,
        run_ocr=True,
    )
    log_audit(db, document.id, "generate", actor, actor_role, {"template": template.key})
    db.commit()
    return {"preview": False, "document": document_view(document), "text": text, "variables": ctx}


# ---------------------------------------------------------------------------
# Signature électronique
# ---------------------------------------------------------------------------
PROVIDERS = ("docusign", "yousign", "hellosign")


def create_envelope(db: Session, data, actor: str) -> GedSignatureEnvelope:
    document = get_document(db, data.document_id)
    if data.provider not in PROVIDERS:
        raise ValueError("Prestataire de signature inconnu")
    envelope = GedSignatureEnvelope(
        reference=generate_reference("ENV"),
        document_id=document.id,
        provider=data.provider,
        signature_level=data.signature_level,
        status="draft",
        created_by=actor,
    )
    db.add(envelope)
    db.flush()
    for signer in data.signers:
        db.add(
            GedSigner(
                envelope_id=envelope.id,
                name=signer.name,
                email=signer.email,
                role=signer.role,
                signing_order=signer.signing_order,
                token=secrets.token_urlsafe(24),
            )
        )
    log_audit(db, document.id, "sign", actor, None, {"action": "envelope_created", "provider": data.provider})
    db.commit()
    db.refresh(envelope)
    return envelope


def send_envelope(db: Session, envelope_id: int, actor: str) -> GedSignatureEnvelope:
    envelope = _envelope_or_404(db, envelope_id)
    if envelope.status not in ("draft", "sent"):
        raise ValueError("Enveloppe déjà traitée")
    if not envelope.signers:
        raise ValueError("Aucun signataire")
    envelope.status = "sent"
    envelope.sent_at = _now()
    envelope.provider_envelope_id = f"{envelope.provider}-{envelope.reference}"
    log_audit(db, envelope.document_id, "sign", actor, None, {"action": "sent", "provider": envelope.provider})
    db.commit()
    db.refresh(envelope)
    return envelope


def current_signer(envelope: GedSignatureEnvelope) -> Optional[GedSigner]:
    pending = [s for s in envelope.signers if s.status == "pending"]
    if not pending:
        return None
    return sorted(pending, key=lambda s: s.signing_order)[0]


def sign_as(
    db: Session,
    envelope_id: int,
    signer_id: int,
    typed_signature: str,
    consent: bool,
    ip: str,
    user_agent: Optional[str],
) -> GedSignatureEnvelope:
    envelope = _envelope_or_404(db, envelope_id)
    if envelope.status == "draft":
        raise ValueError("L'enveloppe n'a pas encore été envoyée")
    if envelope.status in ("completed", "declined", "expired"):
        raise ValueError("Circuit de signature terminé")
    if not consent:
        raise ValueError("Le consentement est requis")
    signer = next((s for s in envelope.signers if s.id == signer_id), None)
    if not signer:
        raise ValueError("Signataire introuvable")
    expected = current_signer(envelope)
    if not expected or expected.id != signer.id:
        raise ValueError("Ce n'est pas le tour de ce signataire")
    document = envelope.document
    payload = f"{document.file_hash}|{signer.email}|{typed_signature}|{_now().isoformat()}|{ip}"
    signer.status = "signed"
    signer.signed_at = _now()
    signer.ip_address = ip
    signer.user_agent = user_agent
    signer.consent_text = "Je reconnais avoir lu le document et consens à le signer électroniquement."
    signer.signature_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    remaining = [s for s in envelope.signers if s.status == "pending"]
    if remaining:
        envelope.status = "in_progress"
    else:
        _complete_envelope(db, envelope)
    log_audit(
        db,
        envelope.document_id,
        "sign",
        signer.email,
        None,
        {"action": "signed", "signer_id": signer.id, "level": envelope.signature_level},
    )
    db.commit()
    db.refresh(envelope)
    return envelope


def decline_signature(db: Session, envelope_id: int, signer_id: int, reason: Optional[str]) -> GedSignatureEnvelope:
    envelope = _envelope_or_404(db, envelope_id)
    signer = next((s for s in envelope.signers if s.id == signer_id), None)
    if not signer:
        raise ValueError("Signataire introuvable")
    signer.status = "declined"
    envelope.status = "declined"
    log_audit(db, envelope.document_id, "sign", signer.email, None, {"action": "declined", "reason": reason})
    db.commit()
    db.refresh(envelope)
    return envelope


def _complete_envelope(db: Session, envelope: GedSignatureEnvelope) -> None:
    envelope.status = "completed"
    envelope.completed_at = _now()
    evidence = _evidence_pdf(envelope)
    directory = Path(settings.private_upload_dir_path) / "ged" / "evidence"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{envelope.reference}.pdf"
    path.write_bytes(evidence)
    envelope.evidence_path = str(path)
    envelope.evidence_hash = hashlib.sha256(evidence).hexdigest()


def _evidence_pdf(envelope: GedSignatureEnvelope) -> bytes:
    lines = [
        f"Dossier de preuve {envelope.reference}",
        f"Prestataire prévu : {envelope.provider} (envoi journalisé, non transmis)",
        f"Niveau : {envelope.signature_level}",
        f"Document : {envelope.document.reference if envelope.document else ''}",
        f"Empreinte document : {envelope.document.file_hash if envelope.document else ''}",
        "",
        "Signataires :",
    ]
    for signer in sorted(envelope.signers, key=lambda s: s.signing_order):
        lines.append(
            f"- {signer.name} <{signer.email}> ordre {signer.signing_order} "
            f"statut={signer.status} hash={signer.signature_hash or '-'} "
            f"ip={signer.ip_address or '-'}"
        )
    lines.append("")
    lines.append(
        "Ce dossier atteste d'une signature électronique simple avec consentement, "
        "horodatage et empreinte. Il ne constitue pas automatiquement une signature "
        "qualifiée au sens eIDAS."
    )
    return build_pdf(f"Preuve {envelope.reference}", "\n".join(lines))


def _envelope_or_404(db: Session, envelope_id: int) -> GedSignatureEnvelope:
    envelope = db.query(GedSignatureEnvelope).filter(GedSignatureEnvelope.id == envelope_id).first()
    if not envelope:
        raise ValueError("Enveloppe non trouvée")
    return envelope


def envelope_view(envelope: GedSignatureEnvelope) -> Dict[str, Any]:
    current = current_signer(envelope)
    return {
        "id": envelope.id,
        "reference": envelope.reference,
        "document_id": envelope.document_id,
        "provider": envelope.provider,
        "signature_level": envelope.signature_level,
        "status": envelope.status,
        "provider_envelope_id": envelope.provider_envelope_id,
        "evidence_hash": envelope.evidence_hash,
        "has_evidence": bool(envelope.evidence_path),
        "created_by": envelope.created_by,
        "sent_at": envelope.sent_at.isoformat() if envelope.sent_at else None,
        "completed_at": envelope.completed_at.isoformat() if envelope.completed_at else None,
        "current_signer_id": current.id if current else None,
        "signers": [
            {
                "id": s.id,
                "name": s.name,
                "email": s.email,
                "role": s.role,
                "signing_order": s.signing_order,
                "status": s.status,
                "signed_at": s.signed_at.isoformat() if s.signed_at else None,
                "signature_hash": s.signature_hash,
            }
            for s in sorted(envelope.signers, key=lambda x: x.signing_order)
        ],
    }


def list_audit(db: Session, document_id: int) -> List[Dict[str, Any]]:
    rows = (
        db.query(GedAuditLog)
        .filter(GedAuditLog.document_id == document_id)
        .order_by(GedAuditLog.occurred_at.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "action": row.action,
            "actor": row.actor,
            "actor_role": row.actor_role,
            "details": row.details or {},
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
        }
        for row in rows
    ]
