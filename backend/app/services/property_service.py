import uuid
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from datetime import datetime

from app.models.property import (
    Property, PropertyPhoto, PropertyDocument,
    PropertyHistory, PropertyEvaluation, PropertyStatus
)
from app.schemas.property import PropertyCreate, PropertyUpdate

def generate_reference():
    unique_id = str(uuid.uuid4()).replace("-", "")[:8].upper()
    return f"PROP-{unique_id}"

def create_property(db: Session, property_data: PropertyCreate):
    reference = generate_reference()
    while db.query(Property).filter(Property.reference == reference).first():
        reference = generate_reference()
    
    property_dict = property_data.dict()
    property_dict["reference"] = reference
    
    db_property = Property(**property_dict)
    db.add(db_property)
    db.commit()
    db.refresh(db_property)
    
    # Ajouter à l'historique
    history = PropertyHistory(
        property_id=db_property.id,
        event_type="created",
        description="Bien créé dans le système",
        date=datetime.now().date()
    )
    db.add(history)
    db.commit()
    
    return db_property

def get_property(db: Session, property_id: int):
    return db.query(Property).filter(
        Property.id == property_id,
        Property.is_active == True
    ).first()

def get_properties(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    city: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_area: Optional[float] = None,
    max_area: Optional[float] = None,
    min_rooms: Optional[int] = None
):
    query = db.query(Property).filter(Property.is_active == True)
    
    if search:
        search_term = f"%{search}%"
        query = query.filter(
            or_(
                Property.title.ilike(search_term),
                Property.address.ilike(search_term),
                Property.city.ilike(search_term),
                Property.reference.ilike(search_term)
            )
        )
    
    if type:
        query = query.filter(Property.type == type)
    if status:
        query = query.filter(Property.status == status)
    if city:
        query = query.filter(Property.city.ilike(f"%{city}%"))
    if min_price:
        query = query.filter(Property.rent_price >= min_price)
    if max_price:
        query = query.filter(Property.rent_price <= max_price)
    if min_area:
        query = query.filter(Property.living_area >= min_area)
    if max_area:
        query = query.filter(Property.living_area <= max_area)
    if min_rooms:
        query = query.filter(Property.rooms >= min_rooms)
    
    total = query.count()
    properties = query.offset(skip).limit(limit).all()
    
    return properties, total

def update_property(db: Session, property_id: int, property_data: PropertyUpdate):
    db_property = get_property(db, property_id)
    if not db_property:
        return None
    
    update_data = property_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_property, field, value)
    
    db.commit()
    db.refresh(db_property)
    return db_property

def delete_property(db: Session, property_id: int):
    db_property = get_property(db, property_id)
    if db_property:
        db_property.is_active = False
        db_property.status = PropertyStatus.WITHDRAWN
        db.commit()
    return db_property

def get_property_statistics(db: Session):
    total = db.query(Property).filter(Property.is_active == True).count()
    
    by_type = {}
    for t in ["apartment", "house", "studio", "commercial", "building"]:
        count = db.query(Property).filter(
            Property.is_active == True,
            Property.type == t
        ).count()
        if count > 0:
            by_type[t] = count
    
    by_status = {}
    for s in ["available", "rented", "for_sale"]:
        count = db.query(Property).filter(
            Property.is_active == True,
            Property.status == s
        ).count()
        if count > 0:
            by_status[s] = count
    
    return {
        "total_properties": total,
        "by_type": by_type,
        "by_status": by_status
    }
