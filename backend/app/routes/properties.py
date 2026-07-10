from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.services.property_service import (
    create_property, get_property, get_properties,
    update_property, delete_property, get_property_statistics
)
from app.schemas.property import (
    PropertyCreate, PropertyUpdate, PropertyResponse,
    PropertyDetailResponse
)

router = APIRouter(prefix="/api/properties", tags=["Properties"])

@router.post("/", response_model=PropertyResponse, status_code=201)
def create_new_property(
    property_data: PropertyCreate,
    db: Session = Depends(get_db)
):
    """Créer un nouveau bien immobilier"""
    return create_property(db, property_data)

@router.get("/")
def list_properties(
    search: Optional[str] = Query(None, description="Recherche textuelle"),
    type: Optional[str] = Query(None, description="Type de bien"),
    status: Optional[str] = Query(None, description="Statut"),
    city: Optional[str] = Query(None, description="Ville"),
    min_price: Optional[float] = Query(None, description="Prix minimum"),
    max_price: Optional[float] = Query(None, description="Prix maximum"),
    min_area: Optional[float] = Query(None, description="Surface minimum"),
    max_area: Optional[float] = Query(None, description="Surface maximum"),
    min_rooms: Optional[int] = Query(None, description="Pièces minimum"),
    page: int = Query(1, ge=1, description="Page"),
    limit: int = Query(20, ge=1, le=100, description="Éléments par page"),
    db: Session = Depends(get_db)
):
    """Lister les biens avec filtres"""
    skip = (page - 1) * limit
    properties, total = get_properties(
        db, skip, limit, search, type, status, city,
        min_price, max_price, min_area, max_area, min_rooms
    )
    
    return {
        "data": properties,
        "total": total,
        "page": page,
        "total_pages": (total + limit - 1) // limit
    }

@router.get("/statistics")
def get_statistics(db: Session = Depends(get_db)):
    """Statistiques globales"""
    return get_property_statistics(db)

@router.get("/{property_id}", response_model=PropertyDetailResponse)
def get_property_detail(
    property_id: int,
    db: Session = Depends(get_db)
):
    """Détails d'un bien"""
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
    """Modifier un bien"""
    property = update_property(db, property_id, property_data)
    if not property:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    return property

@router.delete("/{property_id}")
def delete_property_endpoint(
    property_id: int,
    db: Session = Depends(get_db)
):
    """Supprimer un bien"""
    property = delete_property(db, property_id)
    if not property:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    return {"message": "Bien supprimé avec succès"}
