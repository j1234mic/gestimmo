# backend/app/routes/owners.py - CODE COMPLET CORRIGÉ

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import date, datetime, timezone
import os
import secrets
import string
import uuid
import aiofiles

from app.database import get_db
from app.auth import require_read, require_write, get_optional_user
from app.config import settings
from app.models.admin_security import AdminRole, AdminUser, UserRoleAssignment
from app.models.owner import Owner, PropertyOwner, Mandate
from app.services import admin_security_service as security_service
from app.services.admin_security_service import pwd_context
from app.services.owner_service import (
    create_owner, get_owner, get_owners, update_owner, delete_owner,
    link_property_to_owner, unlink_property_from_owner,
    create_mandate, get_mandates, delete_mandate, sign_mandate
)
from app.schemas.owner import (
    OwnerCreate, OwnerUpdate, OwnerResponse, OwnerDetailResponse,
    MandateCreate, MandateResponse, MandateSignatureRequest, PropertyOwnerLink,
    OwnerCredentialsRequest,
)
from fastapi.responses import FileResponse
from pathlib import Path

router = APIRouter(prefix="/api/owners", tags=["Owners"])


# ============================================
# CRUD OWNERS
# ============================================
@router.post("/", response_model=OwnerResponse, status_code=201)
def create_new_owner(
    data: OwnerCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Créer un nouveau propriétaire."""
    return create_owner(db, data)


@router.get("/")
def list_owners(
    search: Optional[str] = Query(None),
    owner_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user = Depends(get_optional_user)
):
    """Lister les propriétaires."""
    skip = (page - 1) * limit
    owners, total = get_owners(db, skip, limit, search, owner_type)
    
    return {
        "data": owners,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit
    }


@router.get("/{owner_id}")
def get_owner_detail(
    owner_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_optional_user)
):
    """Détails d'un propriétaire."""
    owner = get_owner(db, owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Propriétaire non trouvé")
    
    return {
        "id": owner.id,
        "reference": owner.reference,
        "owner_type": owner.owner_type.value if owner.owner_type else "individual",
        "first_name": owner.first_name,
        "last_name": owner.last_name,
        "company_name": owner.company_name,
        "birth_date": owner.birth_date.isoformat() if owner.birth_date else None,
        "birth_place": owner.birth_place,
        "nationality": owner.nationality,
        "email": owner.email,
        "phone": owner.phone,
        "mobile": owner.mobile,
        "address": owner.address,
        "postal_code": owner.postal_code,
        "city": owner.city,
        "country": owner.country,
        "bank_name": owner.bank_name,
        "iban": owner.iban,
        "bic": owner.bic,
        "account_holder": owner.account_holder,
        "tax_regime": owner.tax_regime.value if owner.tax_regime else None,
        "siret": owner.siret,
        "vat_number": owner.vat_number,
        "tax_id": owner.tax_id,
        "id_document_url": owner.id_document_url,
        "tax_notice_url": owner.tax_notice_url,
        "bank_rib_url": owner.bank_rib_url,
        "notes": owner.notes,
        "tags": owner.tags or [],
        "is_active": owner.is_active,
        "properties_count": len(owner.properties) if owner.properties else 0,
        "created_at": owner.created_at.isoformat() if owner.created_at else None,
        "properties": [
            {
                "id": p.id,
                "reference": p.reference,
                "title": p.title,
                "city": p.city,
                "living_area": p.living_area,
                "rent_price": p.rent_price,
                "status": p.status.value if p.status else None
            }
            for p in (owner.properties or [])
        ],
        "mandates": [
            {
                "id": m.id,
                "reference": m.reference,
                "mandate_type": m.mandate_type.value if m.mandate_type else None,
                "status": m.status,
                "start_date": m.start_date.isoformat() if m.start_date else None,
                "end_date": m.end_date.isoformat() if m.end_date else None,
                "signed_date": m.signed_date.isoformat() if m.signed_date else None,
            }
            for m in (owner.mandates or [])
        ]
    }


@router.put("/{owner_id}", response_model=OwnerResponse)
def update_owner_info(
    owner_id: int,
    data: OwnerUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Modifier un propriétaire."""
    owner = update_owner(db, owner_id, data)
    if not owner:
        raise HTTPException(status_code=404, detail="Propriétaire non trouvé")
    return owner


@router.delete("/{owner_id}")
def delete_owner_endpoint(
    owner_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Supprimer un propriétaire."""
    owner = delete_owner(db, owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Propriétaire non trouvé")
    return {"message": "Propriétaire supprimé"}


# ============================================
# CONNEXION / COMPTE PROPRIÉTAIRE
# ============================================
def _generate_temp_password(length: int = 16) -> str:
    """Génère un mot de passe conforme à la politique par défaut du module 12
    (majuscule, minuscule, chiffre et caractère spécial)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in password)
            and any(c.isupper() for c in password)
            and any(c.isdigit() for c in password)
            and any(c in "!@#$%^&*" for c in password)
        ):
            return password


def _owner_display_name(owner: Owner) -> str:
    return (
        owner.company_name
        or " ".join(part for part in (owner.first_name, owner.last_name) if part).strip()
        or (owner.email or "")
    ).strip()


@router.post("/{owner_id}/credentials", status_code=201)
def generate_owner_credentials(
    owner_id: int,
    data: OwnerCredentialsRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Crée un compte de connexion (AdminUser) pour un propriétaire existant.

    Le compte est lié au propriétaire par l'email : une fois connecté via
    ``POST /api/auth/login``, ``get_current_owner`` résout le propriétaire en
    base et l'accès au portail propriétaire (``/owner-portal/*``) est possible.

    Le mot de passe généré n'est renvoyé qu'à la création (ou lors d'une
    réinitialisation demandée) et le compte est marqué
    ``must_change_password`` pour forcer son renouvellement à la première
    connexion.
    """
    owner = get_owner(db, owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Propriétaire non trouvé")

    email = (data.email or owner.email or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=400,
            detail="Le propriétaire n'a pas d'email : renseignez-en un pour créer une connexion",
        )

    existing = db.query(AdminUser).filter(AdminUser.email == email).first()
    if existing and not data.reset_existing:
        raise HTTPException(
            status_code=409,
            detail="Un compte de connexion existe déjà pour cet email (utilisez reset_existing=true pour réinitialiser le mot de passe)",
        )

    generated = data.password is None
    password = data.password or _generate_temp_password()

    if data.password is not None:
        # Contrôle la politique de mot de passe du module 12 (par défaut,
        # sans société rattachée) pour un mot de passe imposé par l'agent.
        policy = security_service.get_policy(db, None)
        try:
            security_service.validate_password(data.password, policy)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    if existing is None:
        user = AdminUser(
            email=email,
            full_name=_owner_display_name(owner),
            password_hash=pwd_context.hash(password),
            must_change_password=True,
        )
        db.add(user)
        db.flush()
    else:
        user = existing
        user.full_name = _owner_display_name(owner)
        user.password_hash = pwd_context.hash(password)
        user.must_change_password = True
        user.is_active = True
        user.locked_until = None
        user.failed_login_attempts = 0

    # Synchronise l'email du propriétaire pour que ``get_current_owner``
    # puisse résoudre le compte de connexion vers le bon propriétaire.
    if owner.email != email:
        owner.email = email

    # Attribue le profil « Lecture seule » (viewer) si aucun rôle n'est déjà
    # affecté, afin de disposer d'un principal correct sans donner de droits
    # d'administration.
    has_role = db.query(UserRoleAssignment).filter(
        UserRoleAssignment.user_id == user.id
    ).first()
    if not has_role:
        viewer_role = db.query(AdminRole).filter(
            AdminRole.profile_key == "viewer", AdminRole.is_system == True
        ).first()
        if viewer_role:
            db.add(UserRoleAssignment(
                user_id=user.id, role_id=viewer_role.id, assigned_by="owner_credentials",
            ))

    db.commit()
    db.refresh(user)

    response = {
        "owner_id": owner.id,
        "reference": owner.reference,
        "full_name": user.full_name,
        "email": user.email,
        "must_change_password": user.must_change_password,
        "login_url": "/api/auth/login",
        "portal_url": "/owner-portal/dashboard",
    }
    if generated:
        response["password"] = password
    return response


# ============================================
# DOCUMENTS PROPRIÉTAIRE
# ============================================
@router.post("/{owner_id}/documents")
async def upload_owner_document(
    owner_id: int,
    file: UploadFile = File(...),
    doc_type: str = Form("id"),
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Uploader un document pour un propriétaire (pièce d'identité, avis fiscal, RIB)."""
    owner = get_owner(db, owner_id)
    if not owner:
        raise HTTPException(status_code=404, detail="Propriétaire non trouvé")
    
    ext = file.filename.split('.')[-1].lower() if '.' in file.filename else 'pdf'
    if ext not in ['pdf', 'jpg', 'jpeg', 'png']:
        raise HTTPException(status_code=400, detail="Format non autorisé (PDF, JPG, PNG)")
    
    upload_dir = os.path.join(settings.UPLOAD_DIR, "owners", str(owner_id))
    os.makedirs(upload_dir, exist_ok=True)
    
    filename = f"{uuid.uuid4()}.{ext}"
    file_path = os.path.join(upload_dir, filename)
    
    content = await file.read()
    async with aiofiles.open(file_path, 'wb') as f:
        await f.write(content)
    
    url = f"/uploads/owners/{owner_id}/{filename}"
    if doc_type == "id":
        owner.id_document_url = url
    elif doc_type == "tax_notice":
        owner.tax_notice_url = url
    elif doc_type == "bank_rib":
        owner.bank_rib_url = url
    
    db.commit()
    
    return {"message": "Document uploadé", "url": url, "type": doc_type}


# ============================================
# LIEN PROPRIÉTAIRE ↔ BIEN
# ============================================
@router.post("/{owner_id}/properties")
def add_property_to_owner(
    owner_id: int,
    link: PropertyOwnerLink,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Associer un bien à un propriétaire."""
    return link_property_to_owner(
        db, link.property_id, owner_id,
        link.ownership_percentage, link.is_main_owner,
        link.acquisition_date, link.acquisition_price
    )


@router.delete("/{owner_id}/properties/{property_id}")
def remove_property_from_owner(
    owner_id: int,
    property_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Dissocier un bien d'un propriétaire."""
    return unlink_property_from_owner(db, property_id, owner_id)


# ============================================
# MANDATS
# ============================================
@router.post("/{owner_id}/mandates", response_model=MandateResponse, status_code=201)
def create_owner_mandate(
    owner_id: int,
    data: MandateCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Créer un mandat pour un propriétaire."""
    return create_mandate(db, owner_id, data)


@router.get("/{owner_id}/mandates")
def list_owner_mandates(
    owner_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_optional_user)
):
    """Lister les mandats d'un propriétaire."""
    return get_mandates(db, owner_id)


@router.put("/{owner_id}/mandates/{mandate_id}")
def update_mandate(
    owner_id: int,
    mandate_id: int,
    data: MandateCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Modifier un mandat."""
    mandate = db.query(Mandate).filter(
        Mandate.id == mandate_id,
        Mandate.owner_id == owner_id
    ).first()
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandat non trouvé")
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(mandate, field, value)
    
    db.commit()
    db.refresh(mandate)
    return mandate


@router.put("/{owner_id}/mandates/{mandate_id}/terminate")
def terminate_mandate(
    owner_id: int,
    mandate_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Résilier un mandat."""
    mandate = db.query(Mandate).filter(
        Mandate.id == mandate_id,
        Mandate.owner_id == owner_id
    ).first()
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandat non trouvé")
    
    mandate.status = "terminated"
    mandate.end_date = date.today()
    db.commit()
    return {"message": "Mandat résilié", "mandate_id": mandate_id}


@router.put("/{owner_id}/mandates/{mandate_id}/sign")
def sign_mandate_endpoint(
    owner_id: int,
    mandate_id: int,
    data: MandateSignatureRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Signer électroniquement un mandat avec dossier de preuve."""
    try:
        mandate = sign_mandate(
            db,
            owner_id,
            mandate_id,
            data,
            request.client.host if request.client else "unknown",
            request.headers.get("user-agent", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "message": "Mandat signé électroniquement",
        "mandate_id": mandate.id,
        "date": mandate.signed_date.isoformat() if mandate.signed_date else None,
        "signature_hash": mandate.signature_hash,
        "signature_document_hash": mandate.signature_document_hash,
        "evidence_url": f"/api/owners/{owner_id}/mandates/{mandate.id}/evidence",
    }


@router.post("/{owner_id}/mandates/{mandate_id}/signature-request")
def request_mandate_signature(
    owner_id: int,
    mandate_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Préparer une demande de signature (horodatage de la demande)."""
    mandate = db.query(Mandate).filter(
        Mandate.id == mandate_id,
        Mandate.owner_id == owner_id
    ).first()
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandat non trouvé")
    mandate.signature_requested_at = datetime.now(timezone.utc)
    mandate.signature_provider = "internal_simple_signature"
    db.commit()
    return {
        "message": "Demande de signature enregistrée",
        "mandate_id": mandate.id,
        "requested_at": mandate.signature_requested_at.isoformat(),
    }


@router.get("/{owner_id}/mandates/{mandate_id}/evidence")
def download_mandate_evidence(
    owner_id: int,
    mandate_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Télécharger le dossier de preuve de signature d'un mandat."""
    mandate = db.query(Mandate).filter(
        Mandate.id == mandate_id,
        Mandate.owner_id == owner_id
    ).first()
    if not mandate:
        raise HTTPException(status_code=404, detail="Mandat non trouvé")
    if not mandate.signature_evidence_path:
        raise HTTPException(status_code=404, detail="Aucun dossier de preuve disponible")
    path = Path(mandate.signature_evidence_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier de preuve introuvable")
    return FileResponse(path, media_type="application/pdf", filename=f"preuve-{mandate.reference}.pdf")


@router.delete("/{owner_id}/mandates/{mandate_id}")
def delete_owner_mandate(
    owner_id: int,
    mandate_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Supprimer un mandat."""
    return delete_mandate(db, mandate_id)


# ============================================
# ALERTES EXPIRATION MANDATS
# ============================================
@router.get("/mandates/expiring")
def list_expiring_mandates(
    days: int = Query(30, description="Jours avant expiration"),
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Lister les mandats qui expirent bientôt."""
    from datetime import timedelta
    threshold = date.today() + timedelta(days=days)
    
    mandates = db.query(Mandate).filter(
        Mandate.status == "active",
        Mandate.end_date <= threshold,
        Mandate.end_date > date.today()
    ).all()
    
    return [
        {
            "id": m.id,
            "reference": m.reference,
            "owner_name": m.owner.company_name or f"{m.owner.first_name or ''} {m.owner.last_name or ''}".strip(),
            "end_date": m.end_date.isoformat(),
            "days_remaining": (m.end_date - date.today()).days
        }
        for m in mandates
    ]