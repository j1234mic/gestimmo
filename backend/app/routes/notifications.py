# backend/app/routes/notifications.py

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth import require_read
from app.services.notification_service import get_notifications

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


@router.get("/")
def list_notifications(
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Récupérer toutes les notifications."""
    return get_notifications(db)