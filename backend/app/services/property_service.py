# backend/app/services/property_service.py - CODE COMPLET CORRIGÉ

import uuid
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional
from datetime import datetime, date
from app.models.property import (
    Property, PropertyPhoto, PropertyDocument,
    PropertyHistory, PropertyEvaluation, PropertyStatus, PropertyType
)
from app.schemas.property import PropertyCreate, PropertyUpdate, PropertyFilter, PropertyResponse


def generate_reference():
    """Génère une référence unique pour le bien"""
    unique_id = str(uuid.uuid4()).replace("-", "")[:8].upper()
    return f"PROP-{unique_id}"


def create_property(db: Session, property_data: PropertyCreate):
    """Crée un nouveau bien immobilier"""
    
    reference = generate_reference()
    existing = db.query(Property).filter(Property.reference == reference).first()
    while existing:
        reference = generate_reference()
        existing = db.query(Property).filter(Property.reference == reference).first()
    
    property_dict = property_data.model_dump()
    property_dict["reference"] = reference
    
    if "status" not in property_dict or property_dict["status"] is None:
        property_dict["status"] = PropertyStatus.AVAILABLE
    
    db_property = Property(**property_dict)
    db.add(db_property)
    db.commit()
    db.refresh(db_property)
    
    add_history_entry(
        db,
        property_id=db_property.id,
        event_type="created",
        description="Bien créé dans le système",
        date=datetime.now().date()
    )
    
    return db_property


def get_property(db: Session, property_id: int):
    """Récupère un bien par son ID"""
    return db.query(Property).filter(
        Property.id == property_id,
        Property.is_active == True
    ).first()


def get_property_by_reference(db: Session, reference: str):
    """Récupère un bien par sa référence"""
    return db.query(Property).filter(
        Property.reference == reference,
        Property.is_active == True
    ).first()


def get_properties(
    db: Session,
    filters: PropertyFilter,
    skip: int = 0,
    limit: int = 100
):
    """Récupère la liste des biens avec filtres"""
    query = db.query(Property).filter(Property.is_active == True)
    
    # Cloisonnement société / agence / portefeuille. Une liste autorisée vide
    # signifie explicitement qu'aucune donnée n'est accessible.
    if filters.entity_id is not None:
        query = query.filter(Property.entity_id == filters.entity_id)
    if filters.agency_id is not None:
        query = query.filter(Property.agency_id == filters.agency_id)
    if filters.portfolio_id is not None:
        query = query.filter(Property.portfolio_id == filters.portfolio_id)
    if filters.allowed_scopes is not None:
        scope_clauses = []
        for scope in filters.allowed_scopes:
            clauses = [Property.entity_id == scope.get("organization_id")]
            if scope.get("agency_id") is not None:
                clauses.append(Property.agency_id == scope["agency_id"])
            if scope.get("portfolio_ids"):
                clauses.append(Property.portfolio_id.in_(scope["portfolio_ids"]))
            scope_clauses.append(and_(*clauses))
        query = query.filter(or_(*scope_clauses)) if scope_clauses else query.filter(False)
    else:
        if filters.allowed_entity_ids is not None:
            query = query.filter(Property.entity_id.in_(filters.allowed_entity_ids))
        if filters.allowed_agency_ids is not None:
            query = query.filter(or_(Property.agency_id.is_(None), Property.agency_id.in_(filters.allowed_agency_ids)))
        if filters.allowed_portfolio_ids is not None:
            query = query.filter(or_(Property.portfolio_id.is_(None), Property.portfolio_id.in_(filters.allowed_portfolio_ids)))

    # Recherche textuelle
    if filters.search:
        search_term = f"%{filters.search}%"
        query = query.filter(
            or_(
                Property.title.ilike(search_term),
                Property.address.ilike(search_term),
                Property.city.ilike(search_term),
                Property.description.ilike(search_term),
                Property.reference.ilike(search_term)
            )
        )
    
    # ✅ Filtres par type - Conversion string → Enum
    if filters.type:
        type_enums = []
        for t in filters.type:
            if isinstance(t, str):
                try:
                    type_enums.append(PropertyType(t.lower()))
                except ValueError:
                    type_enums.append(t)
            else:
                type_enums.append(t)
        query = query.filter(Property.type.in_(type_enums))
    
    # ✅ Filtres par statut - Conversion string → Enum
    if filters.status:
        status_enums = []
        for s in filters.status:
            if isinstance(s, str):
                try:
                    status_enums.append(PropertyStatus(s.lower()))
                except ValueError:
                    status_enums.append(s)
            else:
                status_enums.append(s)
        query = query.filter(Property.status.in_(status_enums))
    
    # Filtre par ville
    if filters.city:
        query = query.filter(Property.city.ilike(f"%{filters.city}%"))
    
    # Filtres de prix
    if filters.min_price is not None:
        query = query.filter(
            or_(
                Property.rent_price >= filters.min_price,
                Property.sale_price >= filters.min_price
            )
        )
    if filters.max_price is not None:
        query = query.filter(
            or_(
                Property.rent_price <= filters.max_price,
                Property.sale_price <= filters.max_price
            )
        )
    
    # Filtres de surface
    if filters.min_area:
        query = query.filter(Property.living_area >= filters.min_area)
    if filters.max_area:
        query = query.filter(Property.living_area <= filters.max_area)
    
    # Filtre par nombre de pièces minimum
    if filters.min_rooms:
        query = query.filter(Property.rooms >= filters.min_rooms)
    
    total = query.count()
    properties = query.offset(skip).limit(limit).all()
    
    # Ajouter la photo principale à la réponse
    properties_with_photo = []
    for prop in properties:
        prop_dict = PropertyResponse.from_orm(prop).dict()
        main_photo = db.query(PropertyPhoto).filter(
            PropertyPhoto.property_id == prop.id,
            PropertyPhoto.is_main == True
        ).first()
        prop_dict["main_photo"] = main_photo.url if main_photo else None
        properties_with_photo.append(prop_dict)
    
    return properties_with_photo, total


def update_property(db: Session, property_id: int, property_data: PropertyUpdate):
    """Met à jour un bien immobilier"""
    db_property = get_property(db, property_id)
    if not db_property:
        return None
    
    update_data = property_data.dict(exclude_unset=True)
    
    # Ajouter les modifications à l'historique
    for field, value in update_data.items():
        if hasattr(db_property, field):
            old_value = getattr(db_property, field)
            if old_value != value:
                add_history_entry(
                    db,
                    property_id=property_id,
                    event_type="updated",
                    description=f"Mise à jour de {field}",
                    details={"field": field, "old_value": str(old_value), "new_value": str(value)},
                    date=datetime.now().date()
                )
    
    for field, value in update_data.items():
        setattr(db_property, field, value)
    
    db.commit()
    db.refresh(db_property)
    return db_property


def delete_property(db: Session, property_id: int):
    """Supprime un bien (soft delete)"""
    db_property = get_property(db, property_id)
    if db_property:
        db_property.is_active = False
        db_property.status = PropertyStatus.WITHDRAWN
        
        add_history_entry(
            db,
            property_id=property_id,
            event_type="deleted",
            description="Bien retiré du système",
            date=datetime.now().date()
        )
        
        db.commit()
    return db_property


def add_history_entry(
    db: Session,
    property_id: int,
    event_type: str,
    description: str,
    date: date,
    details: Optional[dict] = None
):
    """Ajoute une entrée dans l'historique du bien"""
    history_entry = PropertyHistory(
        property_id=property_id,
        event_type=event_type,
        description=description,
        details=details,
        date=date
    )
    db.add(history_entry)
    db.commit()
    return history_entry


def add_evaluation(
    db: Session,
    property_id: int,
    value: float,
    evaluation_date: date,
    source: str = "manual",
    notes: Optional[str] = None
):
    """Ajoute une évaluation pour un bien"""
    evaluation = PropertyEvaluation(
        property_id=property_id,
        value=value,
        evaluation_date=evaluation_date,
        source=source,
        notes=notes
    )
    db.add(evaluation)
    
    add_history_entry(
        db,
        property_id=property_id,
        event_type="evaluation",
        description=f"Nouvelle évaluation : {value:,.2f} €",
        details={"value": value, "source": source},
        date=evaluation_date
    )
    
    db.commit()
    return evaluation


def get_property_statistics(db: Session):
    """Statistiques globales sur le parc immobilier"""
    total = db.query(Property).filter(Property.is_active == True).count()
    
    by_type = {}
    for prop_type in PropertyType:
        count = db.query(Property).filter(
            Property.is_active == True,
            Property.type == prop_type
        ).count()
        if count > 0:
            by_type[prop_type.value] = count
    
    by_status = {}
    for status in PropertyStatus:
        count = db.query(Property).filter(
            Property.is_active == True,
            Property.status == status
        ).count()
        if count > 0:
            by_status[status.value] = count
    
    total_value = db.query(Property).filter(
        Property.is_active == True,
        Property.sale_price.isnot(None)
    ).count()
    
    return {
        "total_properties": total,
        "by_type": by_type,
        "by_status": by_status,
        "properties_for_sale": total_value
    }