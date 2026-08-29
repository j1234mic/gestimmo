"""Adaptateur HTTP du contexte Owner (architecture hexagonale).

Routeur ``/api/v2/owners``. Délègue la logique aux cas d'usage et accepte
un id entier OU un secure_id dans l'URL. Comportement identique à
``app.routes.owners``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_optional_user, require_read, require_write
from app.hexagon.application.dto import (
    OwnerCreateDTO,
    OwnerTypeDTO,
    OwnerUpdateDTO,
)
from app.hexagon.application.use_cases import (
    NotFoundError,
    create_owner,
    delete_owner,
    get_owner,
    list_owners,
    update_owner,
)
from app.hexagon.dependencies import owner_repository_dep
from app.hexagon.domain.ports import OwnerRepository
from app.schemas.owner import OwnerCreate, OwnerResponse, OwnerUpdate

router = APIRouter(prefix="/api/v2/owners", tags=["Owners (hexagonal)"])


@router.post("/", response_model=OwnerResponse, status_code=201)
def create_owner_endpoint(
    data: OwnerCreate,
    repo: OwnerRepository = Depends(owner_repository_dep),
    current_user=Depends(require_write),
):
    dto = OwnerCreateDTO(
        owner_type=OwnerTypeDTO(data.owner_type.value),
        first_name=data.first_name,
        last_name=data.last_name,
        company_name=data.company_name,
        email=str(data.email) if data.email else None,
        phone=data.phone,
        mobile=data.mobile,
        address=data.address,
        postal_code=data.postal_code,
        city=data.city,
        country=data.country,
        tax_regime=data.tax_regime.value if data.tax_regime else None,
        siret=data.siret,
        notes=data.notes,
        tags=list(data.tags or []),
    )
    try:
        entity = create_owner(repo, dto)
    except Exception:  # noqa: BLE001 - garde-fou identique au v1
        raise HTTPException(status_code=500, detail="Erreur lors de la création")
    return OwnerResponse.model_validate(entity, from_attributes=True)


@router.get("/")
def list_owners_endpoint(
    search: Optional[str] = Query(None),
    owner_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    repo: OwnerRepository = Depends(owner_repository_dep),
    current_user=Depends(require_read),
):
    skip = (page - 1) * limit
    items, total = list_owners(repo, skip=skip, limit=limit, search=search, owner_type=owner_type)
    return {
        "data": [OwnerResponse.model_validate(i, from_attributes=True).model_dump() for i in items],
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
    }


@router.get("/{owner_id}", response_model=OwnerResponse)
def get_owner_endpoint(
    owner_id: str,
    repo: OwnerRepository = Depends(owner_repository_dep),
    current_user=Depends(get_optional_user),
):
    try:
        entity = get_owner(repo, owner_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Propriétaire non trouvé")
    return OwnerResponse.model_validate(entity, from_attributes=True)


@router.put("/{owner_id}", response_model=OwnerResponse)
def update_owner_endpoint(
    owner_id: str,
    data: OwnerUpdate,
    repo: OwnerRepository = Depends(owner_repository_dep),
    current_user=Depends(require_write),
):
    update_data = data.model_dump(exclude_unset=True)
    if update_data.get("tax_regime") is not None:
        update_data["tax_regime"] = update_data["tax_regime"].value
    dto = OwnerUpdateDTO(**{k: v for k, v in update_data.items() if k in OwnerUpdateDTO.__dataclass_fields__})
    try:
        entity = update_owner(repo, owner_id, dto)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Propriétaire non trouvé")
    return OwnerResponse.model_validate(entity, from_attributes=True)


@router.delete("/{owner_id}")
def delete_owner_endpoint(
    owner_id: str,
    repo: OwnerRepository = Depends(owner_repository_dep),
    current_user=Depends(require_write),
):
    try:
        delete_owner(repo, owner_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Propriétaire non trouvé")
    return {"message": "Propriétaire supprimé avec succès", "id": owner_id}
