"""Schémas d'entrée du module 17."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, model_validator


DEFAULT_API_SCOPES = ["properties:read"]


class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    scopes: List[str] = Field(default_factory=lambda: list(DEFAULT_API_SCOPES))
    rate_limit_per_minute: int = Field(100, ge=1, le=10_000)
    expires_at: Optional[datetime] = None


class OAuthClientCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    scopes: List[str] = Field(default_factory=lambda: list(DEFAULT_API_SCOPES))
    rate_limit_per_minute: int = Field(100, ge=1, le=10_000)
    token_lifetime_seconds: int = Field(3600, ge=300, le=86_400)


class OAuthTokenRequest(BaseModel):
    grant_type: str = Field("client_credentials", pattern="^client_credentials$")
    client_id: str
    client_secret: str
    scope: Optional[str] = None


class ConnectionCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    provider: str = Field(..., min_length=2, max_length=80)
    config: Dict[str, Any] = Field(default_factory=dict)
    credentials: Dict[str, str] = Field(default_factory=dict)
    is_active: bool = True


class ConnectionUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    config: Optional[Dict[str, Any]] = None
    credentials: Optional[Dict[str, str]] = None
    is_active: Optional[bool] = None


class SyncRequest(BaseModel):
    direction: str = Field("pull", pattern="^(pull|push|bidirectional)$")
    resource: str = Field(..., min_length=2, max_length=80)
    cursor: Optional[str] = None
    options: Dict[str, Any] = Field(default_factory=dict)


class WebhookCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    target_url: HttpUrl
    events: List[str] = Field(..., min_length=1, max_length=50)
    secret: Optional[str] = Field(None, min_length=16, max_length=255)
    is_active: bool = True


class WebhookUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    target_url: Optional[HttpUrl] = None
    events: Optional[List[str]] = Field(None, min_length=1, max_length=50)
    secret: Optional[str] = Field(None, min_length=16, max_length=255)
    is_active: Optional[bool] = None


class WebhookEventCreate(BaseModel):
    event_type: str = Field(..., min_length=3, max_length=100)
    data: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = Field(None, max_length=160)
    deliver_now: bool = False


class ImportExecute(BaseModel):
    mapping: Dict[str, str] = Field(default_factory=dict)
    duplicate_strategy: str = Field("skip", pattern="^(skip|update|error)$")
    dry_run: bool = False


class ExportRequest(BaseModel):
    entity_type: str = Field(..., pattern="^(properties|tenants|owners)$")
    output_format: str = Field("csv", pattern="^(csv|xlsx|json)$")
    fields: List[str] = Field(default_factory=list)
    filters: Dict[str, Any] = Field(default_factory=dict)
