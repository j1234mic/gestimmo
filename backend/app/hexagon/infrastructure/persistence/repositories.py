"""Adaptateurs SQLAlchemy des ports de repository.

Implémentent ``PropertyRepository`` et ``OwnerRepository`` en utilisant
``Session`` de SQLAlchemy et les mappers. Appliquent la règle de sécurité
des identifiants : tout nouvel enregistrement reçoit un ``secure_id``
chiffré ; la résolution par id accepte un entier OU un secure_id.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.hexagon.domain.owner import Owner, OwnerListItem
from app.hexagon.domain.ports import OwnerRepository, PropertyRepository
from app.hexagon.domain.property import (
    Property,
    PropertyFilter,
    PropertyListItem,
    PropertyStatistics,
    PropertyStatus,
    PropertyType,
)
from app.hexagon.infrastructure.persistence.mappers import (
    apply_owner_to_model,
    apply_to_model,
    to_owner_entity,
    to_property_entity,
    to_property_list_item,
    to_property_statistics,
)
from app.hexagon.infrastructure.security.id_cipher import decrypt_id, encrypt_id, is_secure_id
from app.models.owner import Owner as OwnerModel
from app.models.property import Property as PropertyModel
from app.models.property import PropertyPhoto


class SqlAlchemyPropertyRepository(PropertyRepository):
    def __init__(self, db: Session):
        self.db = db

    def _resolve_filter(self, property_id):
        if property_id is None:
            return None
        if is_secure_id(property_id):
            return PropertyModel.secure_id == str(property_id)
        try:
            return PropertyModel.id == int(property_id)
        except (TypeError, ValueError):
            return PropertyModel.secure_id == str(property_id)

    def save(self, property: Property) -> Property:
        model = None
        if property.id is not None:
            model = self.db.query(PropertyModel).filter(PropertyModel.id == property.id).first()
        if model is None:
            model = PropertyModel()
            self.db.add(model)
        apply_to_model(property, model)
        self.db.flush()
        # Attribution du secure_id chiffré (une seule fois).
        if not model.secure_id:
            model.secure_id = encrypt_id(model.id)
            self.db.flush()
        self.db.commit()
        self.db.refresh(model)
        return to_property_entity(model)

    def find_by_id(self, property_id) -> Optional[Property]:
        clause = self._resolve_filter(property_id)
        if clause is None:
            return None
        model = self.db.query(PropertyModel).filter(clause).first()
        if model is None or not model.is_active:
            return None
        return to_property_entity(model)

    def find_by_reference(self, reference: str) -> Optional[Property]:
        model = self.db.query(PropertyModel).filter(
            PropertyModel.reference == reference, PropertyModel.is_active == True  # noqa: E712
        ).first()
        return to_property_entity(model) if model else None

    def search(self, filters: PropertyFilter, skip: int = 0, limit: int = 100):
        query = self.db.query(PropertyModel).filter(PropertyModel.is_active == True)  # noqa: E712

        if filters.entity_id is not None:
            query = query.filter(PropertyModel.entity_id == filters.entity_id)
        if filters.agency_id is not None:
            query = query.filter(PropertyModel.agency_id == filters.agency_id)
        if filters.portfolio_id is not None:
            query = query.filter(PropertyModel.portfolio_id == filters.portfolio_id)
        if filters.allowed_scopes is not None:
            from sqlalchemy import and_

            scope_clauses = []
            for scope in filters.allowed_scopes:
                clauses = [PropertyModel.entity_id == scope.get("organization_id")]
                if scope.get("agency_id") is not None:
                    clauses.append(PropertyModel.agency_id == scope["agency_id"])
                if scope.get("portfolio_ids"):
                    clauses.append(PropertyModel.portfolio_id.in_(scope["portfolio_ids"]))
                scope_clauses.append(and_(*clauses))
            query = query.filter(or_(*scope_clauses)) if scope_clauses else query.filter(False)
        else:
            if filters.allowed_entity_ids is not None:
                query = query.filter(PropertyModel.entity_id.in_(filters.allowed_entity_ids))
            if filters.allowed_agency_ids is not None:
                query = query.filter(or_(PropertyModel.agency_id.is_(None),
                                         PropertyModel.agency_id.in_(filters.allowed_agency_ids)))
            if filters.allowed_portfolio_ids is not None:
                query = query.filter(or_(PropertyModel.portfolio_id.is_(None),
                                         PropertyModel.portfolio_id.in_(filters.allowed_portfolio_ids)))

        if filters.search:
            term = f"%{filters.search}%"
            query = query.filter(
                or_(
                    PropertyModel.title.ilike(term),
                    PropertyModel.address.ilike(term),
                    PropertyModel.city.ilike(term),
                    PropertyModel.description.ilike(term),
                    PropertyModel.reference.ilike(term),
                )
            )
        if filters.type:
            enums = []
            for t in filters.type:
                enums.append(PropertyType(t.lower()) if isinstance(t, str) else t)
            query = query.filter(PropertyModel.type.in_(enums))
        if filters.status:
            enums = []
            for s in filters.status:
                enums.append(PropertyStatus(s.lower()) if isinstance(s, str) else s)
            query = query.filter(PropertyModel.status.in_(enums))
        if filters.city:
            query = query.filter(PropertyModel.city.ilike(f"%{filters.city}%"))
        if filters.min_price is not None:
            query = query.filter(or_(PropertyModel.rent_price >= filters.min_price,
                                     PropertyModel.sale_price >= filters.min_price))
        if filters.max_price is not None:
            query = query.filter(or_(PropertyModel.rent_price <= filters.max_price,
                                     PropertyModel.sale_price <= filters.max_price))
        if filters.min_area is not None:
            query = query.filter(PropertyModel.living_area >= filters.min_area)
        if filters.max_area is not None:
            query = query.filter(PropertyModel.living_area <= filters.max_area)
        if filters.min_rooms is not None:
            query = query.filter(PropertyModel.rooms >= filters.min_rooms)

        total = query.count()
        models = query.offset(skip).limit(limit).all()
        items: list[PropertyListItem] = []
        for m in models:
            photo = self.db.query(PropertyPhoto).filter(
                PropertyPhoto.property_id == m.id, PropertyPhoto.is_main == True  # noqa: E712
            ).first()
            items.append(to_property_list_item(m, photo.url if photo else None))
        return items, total

    def statistics(self) -> PropertyStatistics:
        total = self.db.query(PropertyModel).filter(PropertyModel.is_active == True).count()  # noqa: E712
        by_type: dict = {}
        for pt in PropertyType:
            c = self.db.query(PropertyModel).filter(
                PropertyModel.is_active == True, PropertyModel.type == pt  # noqa: E712
            ).count()
            if c > 0:
                by_type[pt.value] = c
        by_status: dict = {}
        for st in PropertyStatus:
            c = self.db.query(PropertyModel).filter(
                PropertyModel.is_active == True, PropertyModel.status == st  # noqa: E712
            ).count()
            if c > 0:
                by_status[st.value] = c
        for_sale = self.db.query(PropertyModel).filter(
            PropertyModel.is_active == True, PropertyModel.sale_price.isnot(None)  # noqa: E712
        ).count()
        return to_property_statistics(total, by_type, by_status, for_sale)

    def delete(self, property_id) -> Optional[Property]:
        clause = self._resolve_filter(property_id)
        if clause is None:
            return None
        model = self.db.query(PropertyModel).filter(clause).first()
        if model is None:
            return None
        entity = to_property_entity(model)
        entity.soft_delete()
        apply_to_model(entity, model)
        self.db.commit()
        return entity


class SqlAlchemyOwnerRepository(OwnerRepository):
    def __init__(self, db: Session):
        self.db = db

    def _resolve_filter(self, owner_id):
        if owner_id is None:
            return None
        if is_secure_id(owner_id):
            return OwnerModel.secure_id == str(owner_id)
        try:
            return OwnerModel.id == int(owner_id)
        except (TypeError, ValueError):
            return OwnerModel.secure_id == str(owner_id)

    def save(self, owner: Owner) -> Owner:
        model = None
        if owner.id is not None:
            model = self.db.query(OwnerModel).filter(OwnerModel.id == owner.id).first()
        if model is None:
            model = OwnerModel()
            self.db.add(model)
        apply_owner_to_model(owner, model)
        self.db.flush()
        if not model.secure_id:
            model.secure_id = encrypt_id(model.id)
            self.db.flush()
        self.db.commit()
        self.db.refresh(model)
        return to_owner_entity(model)

    def find_by_id(self, owner_id) -> Optional[Owner]:
        clause = self._resolve_filter(owner_id)
        if clause is None:
            return None
        model = self.db.query(OwnerModel).filter(clause).first()
        if model is None or not model.is_active:
            return None
        return to_owner_entity(model)

    def search(self, skip: int = 0, limit: int = 100, search: Optional[str] = None,
               owner_type: Optional[str] = None):
        query = self.db.query(OwnerModel).filter(OwnerModel.is_active == True)  # noqa: E712
        if search:
            term = f"%{search}%"
            query = query.filter(
                or_(
                    OwnerModel.first_name.ilike(term),
                    OwnerModel.last_name.ilike(term),
                    OwnerModel.company_name.ilike(term),
                    OwnerModel.email.ilike(term),
                    OwnerModel.city.ilike(term),
                    OwnerModel.reference.ilike(term),
                )
            )
        if owner_type:
            query = query.filter(OwnerModel.owner_type == owner_type)
        total = query.count()
        models = query.order_by(OwnerModel.last_name, OwnerModel.first_name).offset(skip).limit(limit).all()
        items: list[OwnerListItem] = []
        for m in models:
            items.append(OwnerListItem(
                id=m.id,
                secure_id=m.secure_id,
                reference=m.reference,
                owner_type=m.owner_type.value if m.owner_type else "individual",
                display_name=(
                    m.company_name if m.owner_type == "company" and m.company_name
                    else " ".join(p for p in (m.first_name, m.last_name) if p) or m.reference
                ),
                email=m.email,
                city=m.city,
                is_active=m.is_active,
                properties_count=len(m.properties) if m.properties else 0,
            ))
        return items, total

    def delete(self, owner_id) -> Optional[Owner]:
        clause = self._resolve_filter(owner_id)
        if clause is None:
            return None
        model = self.db.query(OwnerModel).filter(clause).first()
        if model is None:
            return None
        entity = to_owner_entity(model)
        entity.soft_delete()
        apply_owner_to_model(entity, model)
        self.db.commit()
        return entity
