# backend/app/routes/history.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.database import get_db
from app.auth import require_read, require_write
from app.models.property import Property, PropertyHistory
from app.services.property_service import add_history_entry

router = APIRouter(prefix="/api/properties/{property_id}/history", tags=["History"])


@router.get("/")
def list_history(
    property_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Lister l'historique complet d'un bien."""
    property_obj = db.query(Property).filter(Property.id == property_id).first()
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")

    history = db.query(PropertyHistory).filter(
        PropertyHistory.property_id == property_id
    ).order_by(PropertyHistory.date.desc(), PropertyHistory.created_at.desc()).all()

    return {
        "data": [
            {
                "id": h.id,
                "event_type": h.event_type,
                "description": h.description,
                "details": h.details,
                "date": h.date.isoformat() if h.date else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in history
        ],
        "total": len(history)
    }


@router.post("/")
def add_history(
    property_id: int,
    event_type: str,
    description: str,
    date: date,
    details: Optional[dict] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Ajouter une entrée dans l'historique."""
    property_obj = db.query(Property).filter(Property.id == property_id).first()
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")

    entry = add_history_entry(db, property_id, event_type, description, date, details)
    
    return {
        "id": entry.id,
        "event_type": entry.event_type,
        "description": entry.description,
        "date": entry.date.isoformat() if entry.date else None,
    }


@router.delete("/{history_id}")
def delete_history(
    property_id: int,
    history_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Supprimer une entrée d'historique."""
    entry = db.query(PropertyHistory).filter(
        PropertyHistory.id == history_id,
        PropertyHistory.property_id == property_id
    ).first()

    if not entry:
        raise HTTPException(status_code=404, detail="Entrée non trouvée")

    db.delete(entry)
    db.commit()

    return {"message": "Entrée supprimée", "history_id": history_id}