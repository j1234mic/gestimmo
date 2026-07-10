# backend/app/routes/properties.py

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import aiofiles
import os
from datetime import date

from app.database import get_db
from app.services.property_service import (
    create_property, get_property, get_properties,
    update_property, delete_property, add_evaluation,
    get_property_statistics
)
from app.schemas.property import (
    PropertyCreate, PropertyUpdate, PropertyResponse,
    PropertyDetailResponse, PropertyFilter
)

router = APIRouter(prefix="/api/properties", tags=["Properties"])

UPLOAD_DIR = "uploads/properties"

@router.post("/", response_model=PropertyResponse, status_code=201)
def create_new_property(property_data: PropertyCreate, db: Session = Depends(get_db)):
    """
    Crée un nouveau bien immobilier avec référence auto-générée
    """
    property = create_property(db, property_data)
    return property

@router.get("/", response_model=dict)
def list_properties(
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
    db: Session = Depends(get_db)
):
    """
    Liste paginée des biens avec filtres avancés
    """
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
    
    skip = (page - 1) * limit
    properties, total = get_properties(db, filters, skip, limit)
    
    return {
        "data": properties,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit
    }

@router.get("/statistics")
def get_statistics(db: Session = Depends(get_db)):
    """
    Statistiques globales sur le parc immobilier
    """
    return get_property_statistics(db)

@router.get("/{property_id}", response_model=PropertyDetailResponse)
def get_property_detail(property_id: int, db: Session = Depends(get_db)):
    """
    Récupère les détails complets d'un bien
    """
    property = get_property(db, property_id)
    if not property:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    return property

@router.put("/{property_id}", response_model=PropertyResponse)
def update_property_info(
    property_id: int,
    property_data: PropertyUpdate,
    db: Session = Depends(get_db)
):
    """
    Met à jour un bien immobilier
    """
    property = update_property(db, property_id, property_data)
    if not property:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    return property

@router.delete("/{property_id}")
def delete_property_endpoint(property_id: int, db: Session = Depends(get_db)):
    """
    Supprime (désactive) un bien immobilier
    """
    property = delete_property(db, property_id)
    if not property:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    return {"message": "Bien supprimé avec succès"}

@router.post("/{property_id}/photos")
async def upload_photos(
    property_id: int,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload de photos pour un bien
    """
    property = get_property(db, property_id)
    if not property:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    results = []
    
    for file in files:
        filename = f"{uuid.uuid4()}_{file.filename}"
        file_path = os.path.join(UPLOAD_DIR, filename)
        
        async with aiofiles.open(file_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        
        photo = PropertyPhoto(
            property_id=property_id,
            url=f"/{UPLOAD_DIR}/{filename}",
            filename=filename
        )
        db.add(photo)
        results.append({"filename": filename, "url": photo.url})
    
    db.commit()
    return {"uploaded": results}

@router.post("/{property_id}/evaluations")
def add_property_evaluation(
    property_id: int,
    value: float,
    evaluation_date: date,
    source: str = "manual",
    notes: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Ajoute une évaluation pour un bien
    """
    property = get_property(db, property_id)
    if not property:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    
    evaluation = add_evaluation(db, property_id, value, evaluation_date, source, notes)
    return evaluation

@router.get("/{property_id}/export")
def export_property_data(property_id: int, format: str = "pdf", db: Session = Depends(get_db)):
    """
    Exporte les données du bien au format PDF ou Excel
    """
    property = get_property(db, property_id)
    if not property:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    
    # Logique d'export à implémenter
    return {"message": f"Export en {format} en cours..."}