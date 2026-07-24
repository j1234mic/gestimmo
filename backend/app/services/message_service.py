# backend/app/services/message_service.py

from sqlalchemy.orm import Session
from sqlalchemy import or_, desc
from typing import Optional
from app.models.message import Message
from app.schemas.message import MessageCreate


def send_message(db: Session, data: MessageCreate, sender_id: int = None, sender_type: str = "admin"):
    """Envoyer un message."""
    message = Message(
        sender_id=sender_id,
        sender_type=sender_type,
        recipient_id=data.recipient_id,
        recipient_type=data.recipient_type,
        subject=data.subject,
        content=data.content,
        attachment_url=data.attachment_url
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_messages_for_owner(db: Session, owner_id: int, limit: int = 50):
    """Récupérer les messages d'un propriétaire."""
    return db.query(Message).filter(
        or_(
            Message.recipient_id == owner_id,
            Message.sender_id == owner_id
        )
    ).order_by(desc(Message.created_at)).limit(limit).all()


def get_unread_count(db: Session, owner_id: int):
    """Nombre de messages non lus."""
    return db.query(Message).filter(
        Message.recipient_id == owner_id,
        Message.is_read == False
    ).count()


def mark_as_read(db: Session, message_id: int):
    """Marquer un message comme lu."""
    message = db.query(Message).filter(Message.id == message_id).first()
    if message:
        message.is_read = True
        from datetime import datetime
        message.read_at = datetime.utcnow()
        db.commit()
    return message


def get_all_messages(db: Session, limit: int = 100):
    """Admin : voir tous les messages."""
    return db.query(Message).order_by(desc(Message.created_at)).limit(limit).all()


def delete_message(db: Session, message_id: int):
    """Supprimer un message."""
    message = db.query(Message).filter(Message.id == message_id).first()
    if message:
        db.delete(message)
        db.commit()
    return {"message": "Message supprimé"}