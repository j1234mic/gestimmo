# backend/app/schemas/message.py

from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class MessageCreate(BaseModel):
    recipient_id: Optional[int] = None
    recipient_type: str = "owner"
    subject: str
    content: str
    attachment_url: Optional[str] = None


class MessageResponse(BaseModel):
    id: int
    sender_id: Optional[int] = None
    sender_type: str
    recipient_id: Optional[int] = None
    subject: str
    content: str
    is_read: bool
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True