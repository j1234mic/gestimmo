
import base64
import binascii
import hashlib
import io
import uuid
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional
from datetime import date, datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import settings
from app.models.owner import Owner, PropertyOwner, Mandate
from app.schemas.owner import OwnerCreate, OwnerUpdate, MandateCreate, MandateSignatureRequest
from app.hexagon.infrastructure.security.id_cipher import encrypt_id


def generate_reference():
    unique_id = str(uuid.uuid4()).replace("-", "")[:8].upper()
    return f"OWN-{unique_id}"


def create_owner(db: Session, data: OwnerCreate):
    reference = generate_reference()
    while db.query(Owner).filter(Owner.reference == reference).first():
        reference = generate_reference()
    
    # Créer avec model_dump() pour Pydantic v2
    owner_dict = data.model_dump()
    owner_dict["reference"] = reference
    
    owner = Owner(**owner_dict)
    db.add(owner)
    db.commit()
    db.refresh(owner)

    # Identifiant public chiffré (secure_id) — exposé à la place de l'id entier.
    if not owner.secure_id:
        owner.secure_id = encrypt_id(owner.id)
        db.commit()
    return owner


def get_owner(db: Session, owner_id: int):
    return db.query(Owner).filter(Owner.id == owner_id, Owner.is_active == True).first()


def get_owners(db: Session, skip: int = 0, limit: int = 100, search: Optional[str] = None, owner_type: Optional[str] = None):
    query = db.query(Owner).filter(Owner.is_active == True)
    
    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            Owner.first_name.ilike(term), Owner.last_name.ilike(term),
            Owner.company_name.ilike(term), Owner.email.ilike(term),
            Owner.city.ilike(term), Owner.reference.ilike(term)
        ))
    
    if owner_type:
        query = query.filter(Owner.owner_type == owner_type)
    
    total = query.count()
    owners = query.order_by(Owner.last_name, Owner.first_name).offset(skip).limit(limit).all()
    
    result = []
    for owner in owners:
        result.append({
            "id": owner.id,
            "reference": owner.reference,
            "owner_type": owner.owner_type.value if owner.owner_type else "individual",
            "first_name": owner.first_name,
            "last_name": owner.last_name,
            "company_name": owner.company_name,
            "email": owner.email,
            "phone": owner.phone,
            "city": owner.city,
            "tax_regime": owner.tax_regime.value if owner.tax_regime else None,
            "is_active": owner.is_active,
            "properties_count": len(owner.properties) if owner.properties else 0,
            "created_at": owner.created_at
        })
    
    return result, total


def update_owner(db: Session, owner_id: int, data: OwnerUpdate):
    owner = get_owner(db, owner_id)
    if not owner:
        return None
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(owner, field, value)
    
    db.commit()
    db.refresh(owner)
    return owner


def delete_owner(db: Session, owner_id: int):
    owner = get_owner(db, owner_id)
    if owner:
        owner.is_active = False
        db.commit()
    return owner


def link_property_to_owner(db: Session, property_id: int, owner_id: int, ownership_percentage: float = 100.0,
                           is_main_owner: bool = True, acquisition_date=None, acquisition_price=None):
    existing = db.query(PropertyOwner).filter(
        PropertyOwner.property_id == property_id, PropertyOwner.owner_id == owner_id
    ).first()
    
    if existing:
        existing.ownership_percentage = ownership_percentage
        existing.is_main_owner = is_main_owner
        existing.acquisition_date = acquisition_date
        existing.acquisition_price = acquisition_price
    else:
        link = PropertyOwner(
            property_id=property_id, owner_id=owner_id,
            ownership_percentage=ownership_percentage, is_main_owner=is_main_owner,
            acquisition_date=acquisition_date, acquisition_price=acquisition_price
        )
        db.add(link)
    db.commit()
    return {"message": "Lien créé"}


def unlink_property_from_owner(db: Session, property_id: int, owner_id: int):
    link = db.query(PropertyOwner).filter(
        PropertyOwner.property_id == property_id, PropertyOwner.owner_id == owner_id
    ).first()
    if link:
        db.delete(link)
        db.commit()
    return {"message": "Lien supprimé"}


def create_mandate(db: Session, owner_id: int, data: MandateCreate):
    reference = f"MAND-{str(uuid.uuid4())[:8].upper()}"
    mandate_dict = data.model_dump()
    mandate_dict["owner_id"] = owner_id
    mandate_dict["reference"] = reference
    
    mandate = Mandate(**mandate_dict)
    db.add(mandate)
    db.commit()
    db.refresh(mandate)
    return mandate


def get_mandates(db: Session, owner_id: int):
    return db.query(Mandate).filter(Mandate.owner_id == owner_id).all()


def delete_mandate(db: Session, mandate_id: int):
    mandate = db.query(Mandate).filter(Mandate.id == mandate_id).first()
    if mandate:
        db.delete(mandate)
        db.commit()
    return {"message": "Mandat supprimé"}


def _mandate_pdf_bytes(mandate: Mandate) -> bytes:
    """Génère un PDF représentant le mandat avant signature."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2 * cm, leftMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("MANDAT DE GESTION IMMOBILIÈRE", styles["Title"]),
        Spacer(1, 0.8 * cm),
    ]
    owner = mandate.owner
    owner_name = owner.company_name or f"{owner.first_name or ''} {owner.last_name or ''}".strip()
    rows = [
        ["Référence", mandate.reference],
        ["Propriétaire", owner_name],
        ["Type de mandat", mandate.mandate_type.value if mandate.mandate_type else "-"],
        ["Début", mandate.start_date.isoformat()],
        ["Fin", mandate.end_date.isoformat() if mandate.end_date else "Indéterminée"],
        ["Renouvellement automatique", "Oui" if mandate.renewal_automatic else "Non"],
        ["Honoraires (%)", str(mandate.fees_percentage) if mandate.fees_percentage is not None else "-"],
        ["Honoraires fixes", str(mandate.fees_fixed) if mandate.fees_fixed is not None else "-"],
    ]
    if mandate.property_id is not None:
        rows.append(["Bien associé", f"#{mandate.property_id}"])
    table = Table(rows, colWidths=[6 * cm, 11 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eff6ff")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.extend([table, Spacer(1, 1 * cm), Paragraph(
        "Ce document représente le mandat à signer. La signature électronique est effectuée "
        "avec consentement explicite, horodatage, adresse IP et empreinte SHA-256 du document.",
        styles["BodyText"],
    )])
    doc.build(elements)
    return buffer.getvalue()


def _save_signature_image(encoded: str, directory: Path) -> str:
    value = encoded.split(",", 1)[-1] if encoded.startswith("data:") else encoded
    try:
        content = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("Signature encodée invalide")
    if not content or len(content) > 2 * 1024 * 1024:
        raise ValueError("La signature doit être une image PNG/JPEG de moins de 2 Mo")
    expected = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")
    if not any(content.startswith(sig) for sig in expected):
        raise ValueError("La signature doit être une image PNG ou JPEG")
    ext = "png" if content.startswith(b"\x89PNG") else "jpg"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.{ext}"
    path.write_bytes(content)
    return str(path)


def sign_mandate(db: Session, owner_id: int, mandate_id: int, data: MandateSignatureRequest,
                 ip: str, user_agent: str) -> Mandate:
    """Signe électroniquement un mandat et conserve un dossier de preuve."""
    mandate = db.query(Mandate).filter(
        Mandate.id == mandate_id,
        Mandate.owner_id == owner_id
    ).first()
    if not mandate:
        raise ValueError("Mandat non trouvé")

    pdf = _mandate_pdf_bytes(mandate)
    document_hash = hashlib.sha256(pdf).hexdigest()

    evidence_dir = Path(settings.private_upload_dir_path) / "mandates" / str(owner_id)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"evidence-{mandate.reference}.pdf"

    # Preuve = PDF du mandat + bloc de signature
    proof_parts = [pdf, f"--- SIGNATURE ---\n".encode(), data.typed_signature.encode()]
    if data.signature_image_base64:
        image_path = _save_signature_image(data.signature_image_base64, evidence_dir / "signatures")
        proof_parts.append(Path(image_path).read_bytes())
    else:
        image_path = None

    proof_path = evidence_dir / f"proof-{mandate.reference}.pdf"
    signature_hash = hashlib.sha256(b"".join(proof_parts)).hexdigest()

    evidence = _mandate_pdf_bytes(mandate)
    proof_doc = SimpleDocTemplate(str(evidence_path), pagesize=A4, rightMargin=2 * cm,
                                  leftMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("DOSSIER DE PREUVE DE SIGNATURE", styles["Title"]),
        Spacer(1, 0.5 * cm),
        Paragraph(f"Mandat : {mandate.reference}", styles["BodyText"]),
        Paragraph(f"Empreinte SHA-256 du mandat : {document_hash}", styles["BodyText"]),
        Paragraph(f"Empreinte de la preuve signée : {signature_hash}", styles["BodyText"]),
        Paragraph(f"Signataire : {data.typed_signature}", styles["BodyText"]),
        Paragraph(f"Date : {datetime.now(timezone.utc).isoformat()}", styles["BodyText"]),
        Paragraph(f"Adresse IP : {ip}", styles["BodyText"]),
        Paragraph(f"User-Agent : {user_agent[:1000]}", styles["BodyText"]),
        Spacer(1, 0.5 * cm),
        Paragraph("Ce dossier atteste d'une signature électronique simple avec consentement explicite, horodatage, empreinte du document et éléments d'audit. Il ne constitue pas automatiquement une signature qualifiée au sens eIDAS.", styles["BodyText"]),
    ]
    proof_doc.build(story)

    mandate.signed_date = date.today()
    mandate.status = "signed"
    mandate.signature_hash = signature_hash
    mandate.signature_document_hash = document_hash
    mandate.signature_evidence_path = str(evidence_path)
    mandate.signature_image_path = image_path
    mandate.signature_consent_at = datetime.now(timezone.utc)
    mandate.signature_ip = ip
    mandate.signature_user_agent = user_agent[:1000]
    mandate.signature_provider = "internal_simple_signature"
    mandate.signature_requested_at = datetime.now(timezone.utc)
    mandate.document_url = f"/api/owners/{owner_id}/mandates/{mandate.id}/evidence"
    db.commit()
    db.refresh(mandate)
    return mandate
