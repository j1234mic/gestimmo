# backend/app/routes/properties.py

from app.models.property import PropertyPhoto
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional, List
import os
import uuid
import aiofiles
from datetime import date, datetime
import sys

from app.database import get_db
from app.auth import (
    get_current_user,
    get_optional_user,
    require_read,
    require_write,
    require_delete,
    require_admin,
    PermissionChecker
)
from app.services.property_service import (
    create_property, get_property, get_properties,
    update_property, delete_property, get_property_statistics,
    add_evaluation, list_saved_searches, create_saved_search,
    update_saved_search, delete_saved_search
)
from app.schemas.property import (
    PropertyCreate, PropertyUpdate, PropertyResponse,
    PropertyDetailResponse, PropertyFilter, SavedSearchCreate,
    SavedSearchUpdate, SavedSearchResponse, VirtualTourUpdate, PhotoUpdate
)
from app.config import settings
from app.utils.logger import security_logger

router = APIRouter(prefix="/api/properties", tags=["Properties"])


def _has_property_action(user, action: str) -> bool:
    return bool(user and (getattr(user, "is_superuser", False) or any(
        permission.get("module") in {"*", "properties"} and action in (permission.get("actions") or [])
        for permission in getattr(user, "granular_permissions", [])
    )))


def _has_global_property_scope(user) -> bool:
    return bool(user and (getattr(user, "is_superuser", False) or any(
        permission.get("module") in {"*", "properties"} and permission.get("scope_type") == "all"
        for permission in getattr(user, "granular_permissions", [])
    )))


def _property_in_scope(user, property_obj) -> bool:
    if _has_global_property_scope(user):
        return True
    if not user or getattr(user, "db_id", None) is None:
        return True
    return any(
        property_obj.entity_id == scope["organization_id"]
        and (scope["agency_id"] is None or property_obj.agency_id == scope["agency_id"])
        and (not scope["portfolio_ids"] or property_obj.portfolio_id in scope["portfolio_ids"])
        for scope in user.data_scopes
    )


def _prepare_property_scope(data, user):
    if _has_global_property_scope(user) or getattr(user, "db_id", None) is None:
        return
    if data.entity_id is None and len(user.organization_ids) == 1:
        data.entity_id = user.organization_ids[0]
    if data.agency_id is None and len(user.agency_ids) == 1:
        data.agency_id = user.agency_ids[0]
    if data.entity_id not in user.organization_ids:
        raise HTTPException(status_code=403, detail="Société hors périmètre")
    if (
        data.agency_id is not None
        and data.entity_id not in user.organization_wide_ids
        and data.agency_id not in user.agency_ids
    ):
        raise HTTPException(status_code=403, detail="Agence hors périmètre")
    if data.portfolio_id is not None and user.portfolio_ids and data.portfolio_id not in user.portfolio_ids:
        raise HTTPException(status_code=403, detail="Portefeuille hors périmètre")

# ============================================
# CREATE - Authentification requise + Permission write
# ============================================
@router.post("/", response_model=PropertyResponse, status_code=201)
def create_new_property(
    request: Request,
    property_data: PropertyCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Créer un nouveau bien immobilier."""
    _prepare_property_scope(property_data, current_user)
    try:
        result = create_property(db, property_data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail="Erreur lors de la création")


# ============================================
# READ - Authentification optionnelle (public)
# ============================================
# backend/app/routes/properties.py

@router.get("/")
def list_properties(
    request: Request,
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
    owner_id: Optional[int] = Query(None),
    manager_id: Optional[int] = Query(None),
    tags: Optional[List[str]] = Query(None),
    available_from: Optional[date] = Query(None),
    available_until: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user = Depends(get_optional_user)
):
    """Lister les biens avec filtres."""
    if current_user and getattr(current_user, "db_id", None) is not None and not _has_property_action(current_user, "read"):
        raise HTTPException(status_code=403, detail="Permission properties:read requise")
    skip = (page - 1) * limit

    # ✅ Si NON connecté et AUCUN statut spécifié → montrer seulement "available"
    # ✅ Si NON connecté et statut spécifié → montrer ce statut (ex: "for_sale")
    if not current_user and not status:
        status = "available"

    # Créer le filtre
    filters = PropertyFilter(
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
        owner_id=owner_id,
        manager_id=manager_id,
        tags=tags,
        available_from=available_from,
        available_until=available_until,
    )
    if current_user and getattr(current_user, "db_id", None) is not None and not _has_global_property_scope(current_user):
        if entity_id is not None and entity_id not in current_user.organization_ids:
            raise HTTPException(status_code=403, detail="Société hors périmètre")
        if agency_id is not None and agency_id not in current_user.agency_ids:
            raise HTTPException(status_code=403, detail="Agence hors périmètre")
        if portfolio_id is not None and portfolio_id not in current_user.portfolio_ids:
            raise HTTPException(status_code=403, detail="Portefeuille hors périmètre")
        filters.allowed_scopes = current_user.data_scopes

    properties, total = get_properties(db, filters, skip, limit)

    return {
        "data": properties,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit,
        "authenticated": current_user is not None
    }


# ============================================
# STATISTICS - Authentification requise
# ============================================
@router.get("/statistics")
def get_statistics(
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Statistiques globales."""
    return get_property_statistics(db)


# ============================================
# RECHERCHES FAVORITES
# ============================================
@router.get("/saved-searches")
def list_saved_search_endpoint(
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Lister les recherches favorites de l'utilisateur connecté."""
    rows = list_saved_searches(db, current_user.db_id or 0)
    return {"data": [SavedSearchResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.post("/saved-searches", response_model=SavedSearchResponse, status_code=201)
def create_saved_search_endpoint(
    data: SavedSearchCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Sauvegarder une recherche favorite."""
    scope = {"entity_id": None, "agency_id": None, "portfolio_id": None}
    if current_user.db_id is not None and hasattr(current_user, "organization_ids") and current_user.organization_ids:
        scope["entity_id"] = current_user.organization_ids[0]
    return create_saved_search(db, current_user.db_id or 0, data, scope)


@router.put("/saved-searches/{search_id}", response_model=SavedSearchResponse)
def update_saved_search_endpoint(
    search_id: int,
    data: SavedSearchUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Modifier une recherche favorite."""
    row = update_saved_search(db, current_user.db_id or 0, search_id, data)
    if not row:
        raise HTTPException(status_code=404, detail="Recherche favorite non trouvée")
    return row


@router.delete("/saved-searches/{search_id}")
def delete_saved_search_endpoint(
    search_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Supprimer une recherche favorite."""
    if not delete_saved_search(db, current_user.db_id or 0, search_id):
        raise HTTPException(status_code=404, detail="Recherche favorite non trouvée")
    return {"message": "Recherche favorite supprimée", "search_id": search_id}


# ============================================
# DETAIL - Authentification optionnelle
# ============================================
@router.get("/{property_id}", response_model=PropertyDetailResponse)
def get_property_detail(
    property_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_optional_user)
):
    """Détails d'un bien."""
    property_obj = get_property(db, property_id)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")

    if current_user and not _property_in_scope(current_user, property_obj):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")
    if not current_user and property_obj.status != "available":
        raise HTTPException(status_code=403, detail="Accès non autorisé")

    return property_obj


# ============================================
# UPDATE - Authentification requise + Permission write
# ============================================
@router.put("/{property_id}", response_model=PropertyResponse)
def update_property_info(
    property_id: int,
    property_data: PropertyUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    
    print('Uploading photos for property:', property_id)
    """Modifier un bien."""
    existing = get_property(db, property_id)
    print('Existing property:', existing )

    if not existing:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    if not _property_in_scope(current_user, existing):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")
    if not _has_global_property_scope(current_user) and getattr(current_user, "db_id", None) is not None:
        if property_data.entity_id is not None and property_data.entity_id not in current_user.organization_ids:
            raise HTTPException(status_code=403, detail="Société hors périmètre")
        target_entity = property_data.entity_id if property_data.entity_id is not None else existing.entity_id
        if (
            property_data.agency_id is not None
            and target_entity not in current_user.organization_wide_ids
            and property_data.agency_id not in current_user.agency_ids
        ):
            raise HTTPException(status_code=403, detail="Agence hors périmètre")
        if (
            property_data.portfolio_id is not None and current_user.portfolio_ids
            and property_data.portfolio_id not in current_user.portfolio_ids
        ):
            raise HTTPException(status_code=403, detail="Portefeuille hors périmètre")

    property_obj = update_property(db, property_id, property_data)
    return property_obj


# ============================================
# DELETE - Authentification requise + Permission delete
# ============================================
@router.delete("/{property_id}")
def delete_property_endpoint(
    property_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user = Depends(require_delete)
):
    
    """Supprimer un bien (soft delete)."""
    existing = get_property(db, property_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    if not _property_in_scope(current_user, existing):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")

    delete_property(db, property_id)
    return {
        "message": "Bien supprimé avec succès",
        "property_id": property_id
    }


# ============================================
# UPLOAD PHOTOS - Authentification requise + Permission write
# ============================================
@router.post("/{property_id}/photos")
async def upload_property_photos(
    property_id: int,
    files: List[UploadFile] = File(...),
    is_main: Optional[bool] = False,
    is_360: Optional[bool] = False,
    virtual_tour_url: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Uploader des photos/vidéos avec compression et gestion de la photo principale."""
    property_obj = get_property(db, property_id)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    if not _property_in_scope(current_user, property_obj):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")

    # Vérifier les extensions (images + vidéos)
    for file in files:
        ext = file.filename.split('.')[-1].lower()
        if ext not in settings.ALLOWED_EXTENSIONS and ext not in settings.ALLOWED_VIDEO_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Extension non autorisée: {ext}")

    # Limiter à 10 médias max
    existing_count = db.query(PropertyPhoto).filter(
        PropertyPhoto.property_id == property_id
    ).count()
    
    if existing_count + len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 médias par bien")

    upload_dir = os.path.join(settings.upload_dir_path, str(property_id))
    os.makedirs(upload_dir, exist_ok=True)

    # Si is_main=True, retirer le flag des autres photos
    if is_main:
        db.query(PropertyPhoto).filter(
            PropertyPhoto.property_id == property_id,
            PropertyPhoto.is_main == True
        ).update({"is_main": False})

    results = []
    image_exts = set(settings.ALLOWED_EXTENSIONS)
    for idx, file in enumerate(files):
        ext = file.filename.split('.')[-1].lower()
        media_type = "image" if ext in image_exts else "video"
        filename = f"{uuid.uuid4()}.{ext}"
        file_path = os.path.join(upload_dir, filename)

        # Lire et compresser l'image (les vidéos sont stockées en l'état)
        content = await file.read()
        if len(content) > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"Fichier trop volumineux (max {settings.MAX_UPLOAD_SIZE} octets)",
            )

        if media_type == "image":
            try:
                from PIL import Image
                import io

                # Compression
                img = Image.open(io.BytesIO(content))

                # Redimensionner si trop grand (max 1920px)
                max_size = 1920
                if img.width > max_size or img.height > max_size:
                    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

                # Sauvegarder avec optimisation
                if ext in ['jpg', 'jpeg']:
                    img.save(file_path, 'JPEG', quality=80, optimize=True)
                elif ext == 'png':
                    img.save(file_path, 'PNG', optimize=True)
                elif ext == 'webp':
                    img.save(file_path, 'WEBP', quality=80)
                else:
                    # Format original sans compression
                    async with aiofiles.open(file_path, 'wb') as f:
                        await f.write(content)

            except ImportError:
                # Pillow non installé, sauvegarder sans compression
                async with aiofiles.open(file_path, 'wb') as f:
                    await f.write(content)
        else:
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(content)

        # Créer l'entrée en base
        current_is_360 = bool(is_360 and idx == 0)
        current_virtual_tour = virtual_tour_url if (virtual_tour_url and idx == 0) else None
        photo = PropertyPhoto(
            property_id=property_id,
            url=f"/uploads/{property_id}/{filename}",
            filename=filename,
            media_type=media_type,
            is_main=is_main and idx == 0,  # Première photo = principale si is_main=True
            is_360=current_is_360,
            virtual_tour_url=current_virtual_tour,
            order=existing_count + idx
        )
        db.add(photo)
        db.flush()

        results.append({
            "id": photo.id,
            "filename": filename,
            "url": photo.url,
            "media_type": media_type,
            "is_main": photo.is_main,
            "is_360": photo.is_360,
            "virtual_tour_url": photo.virtual_tour_url,
        })

    db.commit()
    return {"uploaded": results, "total_photos": existing_count + len(files)}


@router.put("/{property_id}/photos/{photo_id}/main")
def set_main_photo(
    property_id: int,
    photo_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Définir une photo comme principale."""
    photo = db.query(PropertyPhoto).filter(
        PropertyPhoto.id == photo_id,
        PropertyPhoto.property_id == property_id
    ).first()
    
    if not photo:
        raise HTTPException(status_code=404, detail="Photo non trouvée")
    
    # Retirer le flag main de toutes les photos
    db.query(PropertyPhoto).filter(
        PropertyPhoto.property_id == property_id
    ).update({"is_main": False})
    
    # Définir la nouvelle photo principale
    photo.is_main = True
    db.commit()
    
    return {"message": "Photo principale définie", "photo_id": photo_id}


@router.put("/{property_id}/photos/{photo_id}")
def update_photo_metadata(
    property_id: int,
    photo_id: int,
    data: PhotoUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Mettre à jour les métadonnées d'un média (principale, 360°, visite virtuelle, ordre)."""
    property_obj = get_property(db, property_id)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    if not _property_in_scope(current_user, property_obj):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")

    photo = db.query(PropertyPhoto).filter(
        PropertyPhoto.id == photo_id,
        PropertyPhoto.property_id == property_id
    ).first()
    if not photo:
        raise HTTPException(status_code=404, detail="Média non trouvé")

    if data.is_main is not None and data.is_main:
        db.query(PropertyPhoto).filter(
            PropertyPhoto.property_id == property_id,
            PropertyPhoto.is_main == True
        ).update({"is_main": False})
    if data.is_main is not None:
        photo.is_main = data.is_main
    if data.is_360 is not None:
        photo.is_360 = data.is_360
    if data.virtual_tour_url is not None:
        photo.virtual_tour_url = data.virtual_tour_url
    if data.order is not None:
        photo.order = data.order

    db.commit()
    db.refresh(photo)
    return {
        "id": photo.id,
        "url": photo.url,
        "media_type": photo.media_type,
        "filename": photo.filename,
        "is_main": photo.is_main,
        "is_360": photo.is_360,
        "virtual_tour_url": photo.virtual_tour_url,
        "order": photo.order,
    }


# ============================================
# VISITE VIRTUELLE 360° - niveau bien
# ============================================
@router.put("/{property_id}/virtual-tour")
def set_property_virtual_tour(
    property_id: int,
    data: VirtualTourUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Renseigner le lien de visite virtuelle 360° d'un bien."""
    property_obj = get_property(db, property_id)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    if not _property_in_scope(current_user, property_obj):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")

    if data.virtual_tour_url is not None:
        property_obj.virtual_tour_url = data.virtual_tour_url
    if data.is_360_available is not None:
        property_obj.is_360_available = data.is_360_available

    if data.virtual_tour_url:
        db.query(PropertyPhoto).filter(
            PropertyPhoto.property_id == property_id
        ).update({"is_360": True, "virtual_tour_url": data.virtual_tour_url})

    db.commit()
    db.refresh(property_obj)
    return {
        "property_id": property_obj.id,
        "virtual_tour_url": property_obj.virtual_tour_url,
        "is_360_available": property_obj.is_360_available,
    }


@router.delete("/{property_id}/photos/{photo_id}")
def delete_photo(
    property_id: int,
    photo_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Supprimer une photo."""
    photo = db.query(PropertyPhoto).filter(
        PropertyPhoto.id == photo_id,
        PropertyPhoto.property_id == property_id
    ).first()
    
    if not photo:
        raise HTTPException(status_code=404, detail="Photo non trouvée")
    
    # Supprimer le fichier physique
    file_path = os.path.join(settings.upload_dir_path, str(property_id), photo.filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    
    db.delete(photo)
    db.commit()
    
    return {"message": "Photo supprimée", "photo_id": photo_id}

@router.post("/{property_id}/evaluations")
def add_evaluation_endpoint(
    property_id: int,
    value: float,
    evaluation_date: date = None,  # ✅ date est importé
    source: str = "manual",
    notes: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Ajouter une évaluation."""
    from datetime import date  # ✅ Ajouter aussi ici par sécurité
    if not evaluation_date:
        evaluation_date = date.today()
    return add_evaluation(db, property_id, value, evaluation_date, source, notes)

@router.delete("/{property_id}/evaluations/{evaluation_id}")
def delete_evaluation_endpoint(
    property_id: int,
    evaluation_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Supprimer une évaluation."""
    from app.models.property import PropertyEvaluation
    
    evaluation = db.query(PropertyEvaluation).filter(
        PropertyEvaluation.id == evaluation_id,
        PropertyEvaluation.property_id == property_id
    ).first()
    
    if not evaluation:
        raise HTTPException(status_code=404, detail="Évaluation non trouvée")
    
    db.delete(evaluation)
    db.commit()
    
    return {"message": "Évaluation supprimée", "evaluation_id": evaluation_id}