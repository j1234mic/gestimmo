"""Schémas Pydantic du module 11 : gestion documentaire."""

from datetime import date
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    parent_id: Optional[int] = None
    scope: str = Field("custom", pattern="^(property|owner|tenant|contract|type|custom)$")
    property_id: Optional[int] = None
    owner_id: Optional[int] = None
    tenant_id: Optional[int] = None
    lease_id: Optional[int] = None
    document_type: Optional[str] = None


class FolderUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[int] = None


class DocumentMetaUpdate(BaseModel):
    title: Optional[str] = None
    document_type: Optional[str] = None
    folder_id: Optional[int] = None
    tags: Optional[List[str]] = None
    classification: Optional[str] = None
    property_id: Optional[int] = None
    owner_id: Optional[int] = None
    tenant_id: Optional[int] = None
    lease_id: Optional[int] = None
    retention_years: Optional[int] = None
    legal_hold: Optional[bool] = None


class TemplateCreate(BaseModel):
    key: str = Field(..., min_length=2, max_length=80)
    name: str
    category: str
    body: str
    variables: List[str] = Field(default_factory=list)


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    body: Optional[str] = None
    variables: Optional[List[str]] = None
    is_active: Optional[bool] = None


class GenerateDocumentRequest(BaseModel):
    template_key: str
    title: Optional[str] = None
    property_id: Optional[int] = None
    owner_id: Optional[int] = None
    tenant_id: Optional[int] = None
    lease_id: Optional[int] = None
    folder_id: Optional[int] = None
    variables: Dict[str, Any] = Field(default_factory=dict)
    preview_only: bool = False


class SignerIn(BaseModel):
    name: str
    email: str
    role: Optional[str] = None
    signing_order: int = 1


class EnvelopeCreate(BaseModel):
    document_id: int
    provider: str = Field("yousign", pattern="^(docusign|yousign|hellosign)$")
    signature_level: str = Field("simple", pattern="^(simple|advanced|qualified)$")
    signers: List[SignerIn] = Field(..., min_length=1)


class SignRequest(BaseModel):
    typed_signature: str = Field(..., min_length=2, max_length=255)
    consent: bool = True


class SettingsUpdate(BaseModel):
    max_upload_mb: Optional[int] = Field(None, ge=1, le=100)
    compress_images: Optional[bool] = None
    default_retention_years: Optional[int] = Field(None, ge=1, le=50)
    allowed_extensions: Optional[List[str]] = None


class EraseRequest(BaseModel):
    reason: str = Field(..., min_length=3, max_length=255)
