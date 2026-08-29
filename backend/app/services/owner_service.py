
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional
from datetime import date

from app.models.owner import Owner, PropertyOwner, Mandate
from app.schemas.owner import OwnerCreate, OwnerUpdate, MandateCreate
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
