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
    add_evaluation
)
from app.schemas.property import (
    PropertyCreate, PropertyUpdate, PropertyResponse,
    PropertyDetailResponse, PropertyFilter
)
from app.config import settings
from app.utils.logger import security_logger

router = APIRouter(prefix="/api/properties", tags=["Properties"])

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
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user = Depends(get_optional_user)
):
    """Lister les biens avec filtres."""
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
        min_rooms=min_rooms
    )

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
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Uploader des photos pour un bien."""
   
    property_obj = get_property(db, property_id)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")

    for file in files:
        ext = file.filename.split('.')[-1].lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Extension non autorisée: {ext}")

    upload_dir = os.path.join(settings.upload_dir_path, str(property_id))
    os.makedirs(upload_dir, exist_ok=True)

    results = []
    for file in files:
        filename = f"{uuid.uuid4()}_{file.filename}"
        file_path = os.path.join(upload_dir, filename)

        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)

        results.append({"filename": filename, "url": f"/uploads/{property_id}/{filename}"})

    return {"uploaded": results}

# backend/app/routes/properties.py
# Remplacez la route upload_property_photos par celle-ci :

@router.post("/{property_id}/photos")
async def upload_property_photos(
    property_id: int,
    files: List[UploadFile] = File(...),
    is_main: Optional[bool] = False,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Uploader des photos avec compression et gestion de la photo principale."""
    property_obj = get_property(db, property_id)
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")

    # Vérifier les extensions
    for file in files:
        ext = file.filename.split('.')[-1].lower()
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Extension non autorisée: {ext}")

    # Limiter à 10 photos max
    existing_count = db.query(PropertyPhoto).filter(
        PropertyPhoto.property_id == property_id
    ).count()
    
    if existing_count + len(files) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 photos par bien")

    upload_dir = os.path.join(settings.upload_dir_path, str(property_id))
    os.makedirs(upload_dir, exist_ok=True)

    # Si is_main=True, retirer le flag des autres photos
    if is_main:
        db.query(PropertyPhoto).filter(
            PropertyPhoto.property_id == property_id,
            PropertyPhoto.is_main == True
        ).update({"is_main": False})

    results = []
    for idx, file in enumerate(files):
        ext = file.filename.split('.')[-1].lower()
        filename = f"{uuid.uuid4()}.{ext}"
        file_path = os.path.join(upload_dir, filename)

        # Lire et compresser l'image
        content = await file.read()
        
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

        # Créer l'entrée en base
        photo = PropertyPhoto(
            property_id=property_id,
            url=f"/uploads/{property_id}/{filename}",
            filename=filename,
            is_main=is_main and idx == 0,  # Première photo = principale si is_main=True
            order=existing_count + idx
        )
        db.add(photo)
        db.flush()
        
        results.append({
            "id": photo.id,
            "filename": filename,
            "url": photo.url,
            "is_main": photo.is_main
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