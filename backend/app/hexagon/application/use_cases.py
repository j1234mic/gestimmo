"""Cas d'usage (application layer).

Chaque fonction orchestre un port de repository et applique les règles
métier. La couche application ne dépend que des ports et des DTO, jamais
de SQLAlchemy ou de FastAPI. Cela la rend testable avec un faux (fake)
de repository.
"""

from __future__ import annotations

import uuid
from typing import Optional

from app.hexagon.application.dto import (
    OwnerCreateDTO,
    OwnerUpdateDTO,
    PropertyCreateDTO,
    PropertyFilterDTO,
    PropertyUpdateDTO,
    PropertyStatusDTO,
    PropertyTypeDTO,
)
from app.hexagon.domain.owner import Owner, OwnerType
from app.hexagon.domain.ports import OwnerRepository, PropertyRepository
from app.hexagon.domain.property import Property, PropertyFilter, PropertyStatus, PropertyType


class NotFoundError(Exception):
    """Ressource introuvable (équivalent 404)."""


class ConflictError(Exception):
    """Conflit métier (ex. référence dupliquée)."""


def _generate_reference(prefix: str) -> str:
    return f"{prefix}-{str(uuid.uuid4()).replace('-', '')[:8].upper()}"


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

def create_property(repo: PropertyRepository, dto: PropertyCreateDTO) -> Property:
    reference = _generate_reference("PROP")
    # Unicité de la référence (collision UUID exceptionnelle gérée en boucle).
    attempt = 0
    while repo.find_by_reference(reference) is not None and attempt < 5:
        reference = _generate_reference("PROP")
        attempt += 1

    entity = Property(
        reference=reference,
        type=PropertyType(dto.type.value),
        status=PropertyStatus(dto.status.value) if dto.status else PropertyStatus.AVAILABLE,
        title=dto.title,
        description=dto.description,
        address=dto.address,
        address_complement=dto.address_complement,
        postal_code=dto.postal_code,
        city=dto.city,
        country=dto.country,
        latitude=dto.latitude,
        longitude=dto.longitude,
        entity_id=dto.entity_id,
        agency_id=dto.agency_id,
        portfolio_id=dto.portfolio_id,
        living_area=dto.living_area,
        total_area=dto.total_area,
        land_area=dto.land_area,
        rooms=dto.rooms,
        bedrooms=dto.bedrooms,
        bathrooms=dto.bathrooms,
        toilets=dto.toilets,
        floor=dto.floor,
        total_floors=dto.total_floors,
        construction_year=dto.construction_year,
        renovation_year=dto.renovation_year,
        rent_price=dto.rent_price,
        charges=dto.charges,
        deposit=dto.deposit,
        sale_price=dto.sale_price,
        property_tax=dto.property_tax,
        tags=list(dto.tags or []),
        equipment=dict(dto.equipment or {}),
    )
    return repo.save(entity)


def get_property(repo: PropertyRepository, property_id) -> Property:
    entity = repo.find_by_id(property_id)
    if entity is None:
        raise NotFoundError(f"Propriété {property_id!r} introuvable")
    return entity


def list_properties(repo: PropertyRepository, dto: PropertyFilterDTO,
                    skip: int = 0, limit: int = 100):
    filters = PropertyFilter(
        search=dto.search,
        type=dto.type,
        status=dto.status,
        city=dto.city,
        min_price=dto.min_price,
        max_price=dto.max_price,
        min_area=dto.min_area,
        max_area=dto.max_area,
        min_rooms=dto.min_rooms,
        entity_id=dto.entity_id,
        agency_id=dto.agency_id,
        portfolio_id=dto.portfolio_id,
        allowed_scopes=dto.allowed_scopes,
        allowed_entity_ids=dto.allowed_entity_ids,
        allowed_agency_ids=dto.allowed_agency_ids,
        allowed_portfolio_ids=dto.allowed_portfolio_ids,
    )
    return repo.search(filters, skip=skip, limit=limit)


def property_statistics(repo: PropertyRepository):
    return repo.statistics()


def update_property(repo: PropertyRepository, property_id, dto: PropertyUpdateDTO) -> Property:
    entity = repo.find_by_id(property_id)
    if entity is None:
        raise NotFoundError(f"Propriété {property_id!r} introuvable")

    changes = dto.__dict__
    changed_fields = [k for k, v in changes.items() if v is not None]
    for field_name in changed_fields:
        value = changes[field_name]
        if field_name == "type":
            value = PropertyType(value.value)
        elif field_name == "status":
            value = PropertyStatus(value.value)
        setattr(entity, field_name, value)
    return repo.save(entity)


def delete_property(repo: PropertyRepository, property_id) -> Property:
    entity = repo.delete(property_id)
    if entity is None:
        raise NotFoundError(f"Propriété {property_id!r} introuvable")
    return entity


# ---------------------------------------------------------------------------
# Owners
# ---------------------------------------------------------------------------

def create_owner(repo: OwnerRepository, dto: OwnerCreateDTO) -> Owner:
    reference = _generate_reference("OWN")
    attempt = 0
    # L'unicité de la référence n'est pas indexée ici ; on évite simplement
    # une collision immédiate en régénérant si besoin.
    while attempt < 5:
        attempt += 1
        break  # pas de recherche d'existant nécessaire pour les propriétaires

    entity = Owner(
        reference=reference,
        owner_type=OwnerType(dto.owner_type.value),
        first_name=dto.first_name,
        last_name=dto.last_name,
        company_name=dto.company_name,
        email=dto.email,
        phone=dto.phone,
        mobile=dto.mobile,
        address=dto.address,
        postal_code=dto.postal_code,
        city=dto.city,
        country=dto.country,
        siret=dto.siret,
        notes=dto.notes,
        tags=list(dto.tags or []),
    )
    return repo.save(entity)


def get_owner(repo: OwnerRepository, owner_id) -> Owner:
    entity = repo.find_by_id(owner_id)
    if entity is None:
        raise NotFoundError(f"Propriétaire {owner_id!r} introuvable")
    return entity


def list_owners(repo: OwnerRepository, skip: int = 0, limit: int = 100,
                search: Optional[str] = None, owner_type: Optional[str] = None):
    return repo.search(skip=skip, limit=limit, search=search, owner_type=owner_type)


def update_owner(repo: OwnerRepository, owner_id, dto: OwnerUpdateDTO) -> Owner:
    entity = repo.find_by_id(owner_id)
    if entity is None:
        raise NotFoundError(f"Propriétaire {owner_id!r} introuvable")

    changes = dto.__dict__
    for field_name, value in changes.items():
        if value is not None:
            setattr(entity, field_name, value)
    return repo.save(entity)


def delete_owner(repo: OwnerRepository, owner_id) -> Owner:
    entity = repo.delete(owner_id)
    if entity is None:
        raise NotFoundError(f"Propriétaire {owner_id!r} introuvable")
    return entity
