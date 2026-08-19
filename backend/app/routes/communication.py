from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta

from app.database import get_db
from app.models.owner import Owner
from app.models.notification import Notification
from app.models.report import Report
from app.schemas.notification import NotificationResponse
from app.schemas.report import ReportResponse, ReportGenerate
from app.core.security import get_current_owner

router = APIRouter(prefix="/communication", tags=["Communication"])

@router.get("/notifications", response_model=List[NotificationResponse])
def get_notifications(
    only_unread: bool = False,
    db: Session = Depends(get_db),
    current_owner: Owner = Depends(get_current_owner)
):
    """Liste des notifications du propriétaire"""
    query = db.query(Notification).filter(Notification.owner_id == current_owner.id)
    if only_unread:
        query = query.filter(Notification.is_read == False)
    return query.order_by(Notification.created_at.desc()).all()

@router.put("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_owner: Owner = Depends(get_current_owner)
):
    """Marquer une notification comme lue"""
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.owner_id == current_owner.id
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification non trouvée")
    notification.is_read = True
    db.commit()
    return {"message": "Notification marquée comme lue"}

@router.get("/reports", response_model=List[ReportResponse])
def get_reports(
    db: Session = Depends(get_db),
    current_owner: Owner = Depends(get_current_owner)
):
    """Liste des rapports périodiques disponibles"""
    return db.query(Report).filter(Report.owner_id == current_owner.id).order_by(Report.created_at.desc()).all()

@router.post("/reports/generate", response_model=ReportResponse, status_code=201)
def generate_report(
    payload: ReportGenerate,
    db: Session = Depends(get_db),
    current_owner: Owner = Depends(get_current_owner)
):
    """Génération d'un rapport (ici simulation : on crée une entrée en base)"""
    # Dans une vraie application, vous généreriez un PDF et stockeriez l'URL
    report = Report(
        owner_id=current_owner.id,
        report_type=payload.report_type,
        period_start=payload.period_start,
        period_end=payload.period_end,
        file_url=None  # À remplacer par le chemin du fichier généré
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report