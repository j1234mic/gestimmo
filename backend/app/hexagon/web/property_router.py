"""Adaptateur HTTP du contexte Property (architecture hexagonale).

Routeur ``/api/v2/properties``. Il délègue toute la logique aux cas d'usage
de ``app.hexagon.application.use_cases`` et n'effectue aucun accès direct à
SQLAlchemy. La résolution d'un bien accepte un id entier OU un secure_id.

Le comportement (filtrage public, périmètre multi-sociétés) reste identique
à la route historique ``app.routes.properties``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user, get_optional_user
from app.hexagon.application.dto import (
    PropertyCreateDTO,
    PropertyFilterDTO,
    PropertyStatusDTO,
    PropertyTypeDTO,
    PropertyUpdateDTO,
)
from app.hexagon.application.use_cases import (
    ConflictError,
    NotFoundError,
    create_property,
    delete_property,
    get_property,
    list_properties,
    property_statistics,
    update_property,
)
from app.hexagon.dependencies import property_repository_dep
from app.hexagon.domain.ports import PropertyRepository
from app.routes import properties as legacy_properties
from app.schemas.property import PropertyCreate, PropertyResponse, PropertyUpdate

router = APIRouter(prefix="/api/v2/properties", tags=["Properties (hexagonal)"])


def _to_create_dto(data: PropertyCreate) -> PropertyCreateDTO:
    return PropertyCreateDTO(
        type=PropertyTypeDTO(data.type.value),
        status=PropertyStatusDTO(data.status.value) if data.status else None,
        title=data.title,
        description=data.description,
        address=data.address,
        address_complement=data.address_complement,
        postal_code=data.postal_code,
        city=data.city,
        country=data.country,
        latitude=data.latitude,
        longitude=data.longitude,
        entity_id=data.entity_id,
        agency_id=data.agency_id,
        portfolio_id=data.portfolio_id,
        living_area=data.living_area,
        total_area=data.total_area,
        land_area=data.land_area,
        rooms=data.rooms,
        bedrooms=data.bedrooms,
        bathrooms=data.bathrooms,
        toilets=data.toilets,
        floor=data.floor,
        total_floors=data.total_floors,
        construction_year=data.construction_year,
        renovation_year=data.renovation_year,
        rent_price=data.rent_price,
        charges=data.charges,
        deposit=data.deposit,
        sale_price=data.sale_price,
        property_tax=data.property_tax,
        tags=list(data.tags or []),
        equipment=dict(data.equipment.model_dump()) if data.equipment else {},
    )


def _resolve_id(property_id: str):
    # Accepte un entier ou un secure_id (chaîne).
    return property_id


@router.post("/", response_model=PropertyResponse, status_code=201)
def create_property_endpoint(
    data: PropertyCreate,
    repo: PropertyRepository = Depends(property_repository_dep),
    current_user=Depends(legacy_properties.require_write),
):
    # Périmètre multi-sociétés (réutilise la logique historique).
    legacy_properties._prepare_property_scope(data, current_user)
    try:
        entity = create_property(repo, _to_create_dto(data))
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 - garde-fou identique au v1
        raise HTTPException(status_code=500, detail="Erreur lors de la création")
    return PropertyResponse.model_validate(entity, from_attributes=True)


@router.get("/")
def list_properties_endpoint(
    search: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    min_area: Optional[float] = Query(None),
    max_area: Optional[float] = Query(None),
    min_rooms: Optional[int] = Query(None),
    entity_id: Optional[int] = Query(None),
    agency_id: Optional[int] = Query(None),
    portfolio_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    repo: PropertyRepository = Depends(property_repository_dep),
    current_user=Depends(get_optional_user),
):
    if current_user and getattr(current_user, "db_id", None) is not None and not \
            legacy_properties._has_property_action(current_user, "read"):
        raise HTTPException(status_code=403, detail="Permission properties:read requise")

    # Comportement public identique au v1 : sans auth, on limite à "available".
    if not current_user and not status:
        status = "available"

    skip = (page - 1) * limit
    dto = PropertyFilterDTO(
        search=search,
        type=[type] if type else None,
        status=[status] if status else None,
        city=city,
        min_price=min_price,
        max_price=max_price,
        min_area=min_area,
        max_area=max_area,
        min_rooms=min_rooms,
        entity_id=entity_id,
        agency_id=agency_id,
        portfolio_id=portfolio_id,
    )
    # Périmètre multi-sociétés (réutilise la logique historique).
    if current_user and getattr(current_user, "db_id", None) is not None and not \
            legacy_properties._has_global_property_scope(current_user):
        if entity_id is not None and entity_id not in current_user.organization_ids:
            raise HTTPException(status_code=403, detail="Société hors périmètre")
        if agency_id is not None and agency_id not in current_user.agency_ids:
            raise HTTPException(status_code=403, detail="Agence hors périmètre")
        if portfolio_id is not None and portfolio_id not in current_user.portfolio_ids:
            raise HTTPException(status_code=403, detail="Portefeuille hors périmètre")
        dto.allowed_scopes = current_user.data_scopes

    items, total = list_properties(repo, dto, skip=skip, limit=limit)
    return {
        "data": [i.__dict__ if hasattr(i, "__dict__") else dict(i) for i in items],
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
        "authenticated": current_user is not None,
    }


@router.get("/statistics")
def statistics_endpoint(
    repo: PropertyRepository = Depends(property_repository_dep),
    current_user=Depends(legacy_properties.require_read),
):
    return property_statistics(repo)


@router.get("/{property_id}", response_model=PropertyResponse)
def get_property_endpoint(
    property_id: str,
    repo: PropertyRepository = Depends(property_repository_dep),
    current_user=Depends(get_optional_user),
):
    try:
        entity = get_property(repo, _resolve_id(property_id))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Bien non trouvé")

    if current_user and not legacy_properties._property_in_scope(current_user, _as_model(entity)):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")
    if not current_user and entity.status.value != "available":
        raise HTTPException(status_code=403, detail="Accès non autorisé")
    return PropertyResponse.model_validate(entity, from_attributes=True)


@router.put("/{property_id}", response_model=PropertyResponse)
def update_property_endpoint(
    property_id: str,
    data: PropertyUpdate,
    repo: PropertyRepository = Depends(property_repository_dep),
    current_user=Depends(legacy_properties.require_write),
):
    existing = repo.find_by_id(_resolve_id(property_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    if not legacy_properties._property_in_scope(current_user, _as_model(existing)):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")

    update_data = data.model_dump(exclude_unset=True)
    if update_data.get("type") is not None:
        update_data["type"] = PropertyTypeDTO(update_data["type"].value)
    if update_data.get("status") is not None:
        update_data["status"] = PropertyStatusDTO(update_data["status"].value)
    dto = PropertyUpdateDTO(**{k: v for k, v in update_data.items() if k in PropertyUpdateDTO.__dataclass_fields__})

    try:
        entity = update_property(repo, _resolve_id(property_id), dto)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    return PropertyResponse.model_validate(entity, from_attributes=True)


@router.delete("/{property_id}")
def delete_property_endpoint(
    property_id: str,
    repo: PropertyRepository = Depends(property_repository_dep),
    current_user=Depends(legacy_properties.require_delete),
):
    existing = repo.find_by_id(_resolve_id(property_id))
    if existing is None:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    if not legacy_properties._property_in_scope(current_user, _as_model(existing)):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")
    try:
        delete_property(repo, _resolve_id(property_id))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    return {"message": "Bien supprimé avec succès", "id": property_id}


def _as_model(entity):
    """Petit shim pour réutiliser les helpers de périmètre du v1 (attendus ORM)."""
    from app.models.property import Property as PropertyModel

    model = PropertyModel()
    model.id = entity.id
    model.entity_id = entity.entity_id
    model.agency_id = entity.agency_id
    model.portfolio_id = entity.portfolio_id
    model.status = entity.status.value if entity.status else None
    return model
