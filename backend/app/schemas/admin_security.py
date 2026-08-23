"""Schémas API du module 12."""

from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


HEX_COLOR = r"^#[0-9a-fA-F]{6}$"
ACTIONS = {"create", "read", "update", "delete", "export", "admin"}
SCOPES = {"all", "entity", "agency", "portfolio", "assigned"}


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    legal_name: Optional[str] = None
    registration_number: Optional[str] = None
    tax_number: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: str = "France"
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    logo_url: Optional[str] = None
    primary_color: str = Field("#1f6feb", pattern=HEX_COLOR)
    secondary_color: str = Field("#ffffff", pattern=HEX_COLOR)
    fiscal_settings: Dict[str, Any] = Field(default_factory=dict)
    document_templates: Dict[str, Any] = Field(default_factory=dict)


class OrganizationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    legal_name: Optional[str] = None
    registration_number: Optional[str] = None
    tax_number: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = Field(None, pattern=HEX_COLOR)
    secondary_color: Optional[str] = Field(None, pattern=HEX_COLOR)
    fiscal_settings: Optional[Dict[str, Any]] = None
    document_templates: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class AgencyCreate(BaseModel):
    organization_id: int
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=2, max_length=255)
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: str = "France"
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = Field(None, pattern=HEX_COLOR)
    settings: Dict[str, Any] = Field(default_factory=dict)


class AgencyUpdate(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=30)
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = Field(None, pattern=HEX_COLOR)
    settings: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None


class PermissionInput(BaseModel):
    module: str = Field(min_length=1, max_length=80)
    actions: List[str]
    scope_type: str = "assigned"
    scope_ids: List[int] = Field(default_factory=list)

    @field_validator("actions")
    @classmethod
    def validate_actions(cls, value):
        invalid = set(value) - ACTIONS
        if invalid:
            raise ValueError(f"Actions inconnues : {', '.join(sorted(invalid))}")
        return sorted(set(value))

    @field_validator("scope_type")
    @classmethod
    def validate_scope(cls, value):
        if value not in SCOPES:
            raise ValueError("Périmètre inconnu")
        return value


class RoleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: Optional[str] = None
    organization_id: Optional[int] = None
    permissions: List[PermissionInput] = Field(default_factory=list)

    @field_validator("permissions")
    @classmethod
    def one_rule_per_module(cls, value):
        modules = [permission.module for permission in value]
        if len(modules) != len(set(modules)):
            raise ValueError("Une seule règle de permission est autorisée par module")
        return value


class RoleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = None
    is_active: Optional[bool] = None
    permissions: Optional[List[PermissionInput]] = None

    @field_validator("permissions")
    @classmethod
    def one_rule_per_module(cls, value):
        if value is None:
            return value
        modules = [permission.module for permission in value]
        if len(modules) != len(set(modules)):
            raise ValueError("Une seule règle de permission est autorisée par module")
        return value


class RoleAssignmentInput(BaseModel):
    role_id: int
    organization_id: Optional[int] = None
    agency_id: Optional[int] = None


class ScopeInput(BaseModel):
    organization_id: int
    agency_id: Optional[int] = None
    portfolio_ids: List[int] = Field(default_factory=list)
    is_default: bool = False


def _valid_timezone(value: Optional[str]):
    if value is None:
        return value
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError:
        raise ValueError("Fuseau horaire IANA inconnu")
    return value


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str
    phone: Optional[str] = None
    locale: str = "fr"
    timezone: str = "Europe/Paris"
    must_change_password: bool = False
    roles: List[RoleAssignmentInput] = Field(default_factory=list)
    scopes: List[ScopeInput] = Field(default_factory=list)

    _timezone = field_validator("timezone")(_valid_timezone)

    @model_validator(mode="after")
    def unique_assignments(self):
        role_keys = [(item.role_id, item.organization_id, item.agency_id) for item in self.roles]
        scope_keys = [(item.organization_id, item.agency_id) for item in self.scopes]
        if len(role_keys) != len(set(role_keys)) or len(scope_keys) != len(set(scope_keys)):
            raise ValueError("Rôle ou périmètre attribué en double")
        return self


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    phone: Optional[str] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    is_active: Optional[bool] = None
    must_change_password: Optional[bool] = None
    roles: Optional[List[RoleAssignmentInput]] = None
    scopes: Optional[List[ScopeInput]] = None

    _timezone = field_validator("timezone")(_valid_timezone)

    @model_validator(mode="after")
    def unique_assignments(self):
        if self.roles is not None:
            keys = [(item.role_id, item.organization_id, item.agency_id) for item in self.roles]
            if len(keys) != len(set(keys)):
                raise ValueError("Rôle attribué en double")
        if self.scopes is not None:
            keys = [(item.organization_id, item.agency_id) for item in self.scopes]
            if len(keys) != len(set(keys)):
                raise ValueError("Périmètre attribué en double")
        return self


class PasswordChange(BaseModel):
    current_password: Optional[str] = None
    new_password: str


class DeactivateUser(BaseModel):
    reason: str = Field(min_length=3, max_length=255)


class SecurityPolicyUpdate(BaseModel):
    organization_id: Optional[int] = None
    password_min_length: Optional[int] = Field(None, ge=8, le=128)
    require_uppercase: Optional[bool] = None
    require_lowercase: Optional[bool] = None
    require_digit: Optional[bool] = None
    require_special: Optional[bool] = None
    password_expiry_days: Optional[int] = Field(None, ge=0, le=730)
    password_history_count: Optional[int] = Field(None, ge=0, le=24)
    max_login_attempts: Optional[int] = Field(None, ge=1, le=20)
    lockout_minutes: Optional[int] = Field(None, ge=1, le=1440)
    session_timeout_minutes: Optional[int] = Field(None, ge=5, le=1440)
    refresh_token_days: Optional[int] = Field(None, ge=1, le=90)
    require_2fa: Optional[bool] = None
    allowed_2fa_methods: Optional[List[str]] = None

    @field_validator("allowed_2fa_methods")
    @classmethod
    def methods(cls, value):
        if value is not None and set(value) - {"authenticator", "email", "sms"}:
            raise ValueError("Méthode 2FA inconnue")
        return sorted(set(value)) if value is not None else None


class TwoFactorSetup(BaseModel):
    method: str

    @field_validator("method")
    @classmethod
    def method_allowed(cls, value):
        if value not in {"authenticator", "email", "sms"}:
            raise ValueError("Méthode 2FA inconnue")
        return value


class TwoFactorConfirm(BaseModel):
    challenge_token: str
    code: str = Field(min_length=6, max_length=8)


class TwoFactorLoginVerify(TwoFactorConfirm):
    pass


class RefreshRequest(BaseModel):
    refresh_token: str


class DeviceRegister(BaseModel):
    challenge_token: str
    device_identifier: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=2, max_length=255)
    platform: Optional[str] = None
    public_key_pem: str = Field(min_length=100)


class BiometricChallengeRequest(BaseModel):
    email: EmailStr
    device_identifier: str


class BiometricVerifyRequest(BaseModel):
    challenge_token: str
    signature_base64: str


class SSOProviderCreate(BaseModel):
    organization_id: Optional[int] = None
    name: str
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,78}[a-z0-9]$")
    protocol: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    authorization_url: Optional[str] = None
    token_url: Optional[str] = None
    userinfo_url: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    issuer: Optional[str] = None
    metadata_url: Optional[str] = None
    entity_id: Optional[str] = None
    certificate: Optional[str] = None
    email_claim: str = "email"
    auto_provision: bool = False
    default_role_id: Optional[int] = None
    is_enabled: bool = True

    @field_validator("protocol")
    @classmethod
    def protocol_allowed(cls, value):
        if value not in {"oauth2", "saml"}:
            raise ValueError("Protocole SSO inconnu")
        return value

    @model_validator(mode="after")
    def protocol_fields(self):
        if self.protocol == "oauth2" and not (
            self.client_id and self.authorization_url and self.token_url and self.userinfo_url
        ):
            raise ValueError("client_id, authorization_url, token_url et userinfo_url sont requis pour OAuth2")
        if self.protocol == "saml" and not self.entity_id:
            raise ValueError("entity_id du service provider est requis pour valider l'audience SAML")
        if self.protocol == "saml" and not (self.metadata_url or self.certificate):
            raise ValueError("metadata_url ou certificate est requis pour SAML")
        return self


class GeneralSettingsUpdate(BaseModel):
    organization_id: Optional[int] = None
    currency: Optional[str] = Field(None, min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")
    language: Optional[str] = Field(None, min_length=2, max_length=10)
    date_format: Optional[str] = None
    timezone: Optional[str] = None
    numbering: Optional[Dict[str, Any]] = None

    _timezone = field_validator("timezone")(_valid_timezone)


class NumberingSequenceConfig(BaseModel):
    organization_id: Optional[int] = None
    document_type: str = Field(min_length=2, max_length=50)
    period: str = Field("global", min_length=1, max_length=20)
    prefix: str = Field("", max_length=80)
    next_value: int = Field(1, ge=1)
    padding: int = Field(5, ge=1, le=12)


class ReferenceIndexCreate(BaseModel):
    organization_id: Optional[int] = None
    code: str = Field(min_length=2, max_length=20)
    label: Optional[str] = None
    period: str = Field(min_length=4, max_length=20)
    value: str
    publication_date: Optional[date] = None
    source_url: Optional[str] = None


class SMTPSettingsUpdate(BaseModel):
    organization_id: Optional[int] = None
    host: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = None
    password: Optional[str] = None
    from_email: Optional[EmailStr] = None
    from_name: Optional[str] = None
    use_tls: Optional[bool] = None
    use_ssl: Optional[bool] = None
    is_enabled: Optional[bool] = None

    @model_validator(mode="after")
    def tls_or_ssl(self):
        if self.use_tls is True and self.use_ssl is True:
            raise ValueError("TLS explicite et SSL implicite ne peuvent pas être activés ensemble")
        return self


class BackupPolicyUpdate(BaseModel):
    enabled: Optional[bool] = None
    daily_hour_utc: Optional[int] = Field(None, ge=0, le=23)
    retention_days: Optional[int] = Field(None, ge=1, le=3650)


class RestoreRequest(BaseModel):
    confirmation: str


class ConsentCreate(BaseModel):
    subject_type: str
    subject_id: str
    purpose: str
    granted: bool
    legal_text_version: str
    source: Optional[str] = None


class ProcessingRecordCreate(BaseModel):
    organization_id: Optional[int] = None
    name: str
    purpose: str
    legal_basis: str
    data_categories: List[str] = Field(default_factory=list)
    subject_categories: List[str] = Field(default_factory=list)
    recipients: List[str] = Field(default_factory=list)
    retention_period: Optional[str] = None
    safeguards: Optional[str] = None
    international_transfers: Optional[str] = None
    owner: Optional[str] = None


class PrivacyPolicyCreate(BaseModel):
    organization_id: Optional[int] = None
    version: str
    title: str
    content: str = Field(min_length=20)
    publish: bool = False


class DataSubjectRequestCreate(BaseModel):
    request_type: str
    subject_type: str
    subject_id: str
    requester_email: Optional[EmailStr] = None
    reason: Optional[str] = None
    verification_details: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_type")
    @classmethod
    def type_allowed(cls, value):
        if value not in {"erasure", "portability", "access", "rectification"}:
            raise ValueError("Type de demande RGPD inconnu")
        return value


class DataSubjectProcess(BaseModel):
    action: str  # approve | reject | complete
    rejection_reason: Optional[str] = None

    @field_validator("action")
    @classmethod
    def action_allowed(cls, value):
        if value not in {"approve", "reject", "complete"}:
            raise ValueError("Action RGPD inconnue")
        return value
