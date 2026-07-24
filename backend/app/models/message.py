# backend/app/models/message.py

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    
    # Expéditeur et destinataire
    sender_id = Column(Integer, ForeignKey("owners.id", ondelete="SET NULL"), nullable=True)
    sender_type = Column(String(20), default="admin")  # admin, owner, tenant
    recipient_id = Column(Integer, ForeignKey("owners.id", ondelete="SET NULL"), nullable=True)
    recipient_type = Column(String(20), default="owner")
    
    # Contenu
    subject = Column(String(255))
    content = Column(Text)
    
    # Pièce jointe
    attachment_url = Column(String(500))
    
    # Statut
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime(timezone=True))
    
    # Métadonnées
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relations
    sender = relationship("Owner", foreign_keys=[sender_id], backref="sent_messages")
    recipient = relationship("Owner", foreign_keys=[recipient_id], backref="received_messages")