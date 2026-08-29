"""Mappers entre les modèles SQLAlchemy et les entités du domaine.

Isole la conversion au niveau de l'adaptateur d'infrastructure ; le
domaine ne connaît que ses propres entités.
"""

from __future__ import annotations

from typing import Optional

from app.hexagon.domain.owner import Owner as OwnerEntity
from app.hexagon.domain.owner import OwnerType, TaxRegime
from app.hexagon.domain.property import (
    EnergyClass,
    HeatingType,
    Property,
    PropertyListItem,
    PropertyStatus,
    PropertyType,
    PropertyStatistics,
)
from app.models.owner import Owner as OwnerModel
from app.models.property import Property as PropertyModel


def to_property_entity(model: PropertyModel) -> Property:
    return Property(
        id=model.id,
        secure_id=model.secure_id,
        reference=model.reference,
        type=PropertyType(model.type) if model.type is not None else None,
        status=PropertyStatus(model.status) if model.status is not None else PropertyStatus.AVAILABLE,
        title=model.title,
        description=model.description,
        address=model.address,
        address_complement=model.address_complement,
        postal_code=model.postal_code,
        city=model.city,
        country=model.country,
        latitude=model.latitude,
        longitude=model.longitude,
        entity_id=model.entity_id,
        agency_id=model.agency_id,
        portfolio_id=model.portfolio_id,
        living_area=model.living_area,
        total_area=model.total_area,
        land_area=model.land_area,
        rooms=model.rooms,
        bedrooms=model.bedrooms,
        bathrooms=model.bathrooms,
        toilets=model.toilets,
        floor=model.floor,
        total_floors=model.total_floors,
        construction_year=model.construction_year,
        renovation_year=model.renovation_year,
        heating_type=HeatingType(model.heating_type) if model.heating_type is not None else None,
        energy_class=EnergyClass(model.energy_class) if model.energy_class is not None else None,
        ges_class=EnergyClass(model.ges_class) if model.ges_class is not None else None,
        equipment=model.equipment or {},
        rent_price=model.rent_price,
        charges=model.charges,
        deposit=model.deposit,
        sale_price=model.sale_price,
        property_tax=model.property_tax,
        tags=model.tags or [],
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def apply_to_model(entity: Property, model: PropertyModel) -> None:
    """Copie les champs modifiables de l'entité vers le modèle SQLAlchemy."""
    model.reference = entity.reference
    model.type = entity.type.value if entity.type is not None else None
    model.status = entity.status.value if entity.status is not None else None
    model.title = entity.title
    model.description = entity.description
    model.address = entity.address
    model.address_complement = entity.address_complement
    model.postal_code = entity.postal_code
    model.city = entity.city
    model.country = entity.country
    model.latitude = entity.latitude
    model.longitude = entity.longitude
    model.entity_id = entity.entity_id
    model.agency_id = entity.agency_id
    model.portfolio_id = entity.portfolio_id
    model.living_area = entity.living_area
    model.total_area = entity.total_area
    model.land_area = entity.land_area
    model.rooms = entity.rooms
    model.bedrooms = entity.bedrooms
    model.bathrooms = entity.bathrooms
    model.toilets = entity.toilets
    model.floor = entity.floor
    model.total_floors = entity.total_floors
    model.construction_year = entity.construction_year
    model.renovation_year = entity.renovation_year
    model.heating_type = entity.heating_type.value if entity.heating_type is not None else None
    model.energy_class = entity.energy_class.value if entity.energy_class is not None else None
    model.ges_class = entity.ges_class.value if entity.ges_class is not None else None
    model.equipment = entity.equipment or {}
    model.rent_price = entity.rent_price
    model.charges = entity.charges
    model.deposit = entity.deposit
    model.sale_price = entity.sale_price
    model.property_tax = entity.property_tax
    model.tags = entity.tags or []
    model.is_active = entity.is_active


def to_property_list_item(model: PropertyModel, main_photo: Optional[str] = None) -> PropertyListItem:
    return PropertyListItem(
        id=model.id,
        secure_id=model.secure_id,
        reference=model.reference,
        type=model.type.value if model.type is not None else "",
        status=model.status.value if model.status is not None else "",
        title=model.title,
        city=model.city,
        postal_code=model.postal_code,
        rent_price=model.rent_price,
        sale_price=model.sale_price,
        living_area=model.living_area,
        rooms=model.rooms,
        main_photo=main_photo,
        tags=model.tags or [],
        entity_id=model.entity_id,
        agency_id=model.agency_id,
        portfolio_id=model.portfolio_id,
    )


def to_property_statistics(total: int, by_type: dict, by_status: dict,
                           properties_for_sale: int) -> PropertyStatistics:
    return PropertyStatistics(
        total_properties=total,
        by_type=by_type,
        by_status=by_status,
        properties_for_sale=properties_for_sale,
    )


def to_owner_entity(model: OwnerModel) -> OwnerEntity:
    return OwnerEntity(
        id=model.id,
        secure_id=model.secure_id,
        reference=model.reference,
        owner_type=OwnerType(model.owner_type) if model.owner_type is not None else OwnerType.INDIVIDUAL,
        first_name=model.first_name,
        last_name=model.last_name,
        company_name=model.company_name,
        birth_date=model.birth_date,
        birth_place=model.birth_place,
        nationality=model.nationality,
        email=model.email,
        phone=model.phone,
        mobile=model.mobile,
        address=model.address,
        postal_code=model.postal_code,
        city=model.city,
        country=model.country,
        bank_name=model.bank_name,
        iban=model.iban,
        bic=model.bic,
        account_holder=model.account_holder,
        tax_regime=TaxRegime(model.tax_regime) if model.tax_regime is not None else None,
        siret=model.siret,
        vat_number=model.vat_number,
        tax_id=model.tax_id,
        notes=model.notes,
        tags=model.tags or [],
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def apply_owner_to_model(entity: OwnerEntity, model: OwnerModel) -> None:
    model.reference = entity.reference
    model.owner_type = entity.owner_type.value if entity.owner_type is not None else None
    model.first_name = entity.first_name
    model.last_name = entity.last_name
    model.company_name = entity.company_name
    model.birth_date = entity.birth_date
    model.birth_place = entity.birth_place
    model.nationality = entity.nationality
    model.email = entity.email
    model.phone = entity.phone
    model.mobile = entity.mobile
    model.address = entity.address
    model.postal_code = entity.postal_code
    model.city = entity.city
    model.country = entity.country
    model.bank_name = entity.bank_name
    model.iban = entity.iban
    model.bic = entity.bic
    model.account_holder = entity.account_holder
    model.tax_regime = entity.tax_regime.value if entity.tax_regime is not None else None
    model.siret = entity.siret
    model.vat_number = entity.vat_number
    model.tax_id = entity.tax_id
    model.notes = entity.notes
    model.tags = entity.tags or []
    model.is_active = entity.is_active
