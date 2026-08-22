"""Schémas Pydantic du module 10 : communication et notifications."""

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ParticipantIn(BaseModel):
    participant_type: str = "tenant"
    participant_id: Optional[int] = None
    name: Optional[str] = None
    email: Optional[str] = None


class ConversationCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=255)
    conversation_type: str = Field("general", pattern="^(property|dossier|lease|tenant|owner|general)$")
    property_id: Optional[int] = None
    lease_id: Optional[int] = None
    tenant_id: Optional[int] = None
    owner_id: Optional[int] = None
    deal_id: Optional[int] = None
    participants: List[ParticipantIn] = Field(default_factory=list)
    first_message: Optional[str] = None


class ConversationArchive(BaseModel):
    archived: bool = True


class ThreadMessageCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=20000)


class EmailTemplateCreate(BaseModel):
    key: str = Field(..., min_length=2, max_length=80)
    name: str
    subject: str
    body_html: str
    body_text: Optional[str] = None
    variables: List[str] = Field(default_factory=list)


class EmailTemplateUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    body_html: Optional[str] = None
    body_text: Optional[str] = None
    variables: Optional[List[str]] = None
    is_active: Optional[bool] = None


class PreferenceUpsert(BaseModel):
    contact_type: str = Field(..., pattern="^(tenant|owner|prospect|agent)$")
    contact_id: Optional[int] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notification_type: str
    channels: List[str] = Field(default_factory=lambda: ["email", "in_app"])
    frequency: str = Field("immediate", pattern="^(immediate|daily_digest|weekly|never)$")
    unsubscribed: bool = False


class DispatchRequest(BaseModel):
    notification_type: str
    channels: List[str] = Field(default_factory=lambda: ["email", "in_app"])
    recipient_type: str = "tenant"
    recipient_id: Optional[int] = None
    recipient_email: Optional[str] = None
    recipient_phone: Optional[str] = None
    recipient_name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    template_key: Optional[str] = None
    variables: Dict[str, Any] = Field(default_factory=dict)
    property_id: Optional[int] = None
    lease_id: Optional[int] = None
    tenant_id: Optional[int] = None
    owner_id: Optional[int] = None
    deal_id: Optional[int] = None
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[int] = None
    postal_address: Optional[Dict[str, str]] = None
    force: bool = False


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    template_key: Optional[str] = None
    channels: Optional[List[str]] = None
    offset_days: Optional[int] = None
    rules: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None


class ScenarioCreate(BaseModel):
    key: str = Field(..., min_length=2, max_length=80)
    name: str
    description: Optional[str] = None
    trigger_type: str
    template_key: Optional[str] = None
    channels: List[str] = Field(default_factory=lambda: ["email", "in_app"])
    offset_days: int = 0
    rules: Dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True


class HistoryQuery(BaseModel):
    channel: Optional[str] = None
    notification_type: Optional[str] = None
    recipient_email: Optional[str] = None
    contact_type: Optional[str] = None
    contact_id: Optional[int] = None
    property_id: Optional[int] = None
    lease_id: Optional[int] = None
    tenant_id: Optional[int] = None
    owner_id: Optional[int] = None
    deal_id: Optional[int] = None
    q: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
