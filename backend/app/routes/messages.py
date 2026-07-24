# backend/app/routes/messages.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.auth import require_read, require_write
from app.services.message_service import (
    send_message, get_messages_for_owner, get_unread_count,
    mark_as_read, get_all_messages, delete_message
)
from app.schemas.message import MessageCreate, MessageResponse

router = APIRouter(prefix="/api/messages", tags=["Messages"])


@router.post("/", response_model=MessageResponse, status_code=201)
def create_message(
    data: MessageCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Envoyer un message (admin → propriétaire)."""
    return send_message(db, data)


@router.get("/owner/{owner_id}")
def list_owner_messages(
    owner_id: int,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Messages d'un propriétaire."""
    return get_messages_for_owner(db, owner_id, limit)


@router.get("/owner/{owner_id}/unread")
def owner_unread_count(
    owner_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Nombre de messages non lus."""
    return {"unread_count": get_unread_count(db, owner_id)}


@router.put("/{message_id}/read")
def read_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Marquer comme lu."""
    return mark_as_read(db, message_id)


@router.get("/all")
def list_all_messages(
    limit: int = Query(100),
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Admin : tous les messages."""
    return get_all_messages(db, limit)


@router.delete("/{message_id}")
def remove_message(
    message_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Supprimer un message."""
    return delete_message(db, message_id)