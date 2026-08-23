"""Modèles du module 12 : administration, sécurité et conformité.

Les secrets applicatifs (mot de passe SMTP, secrets SSO) ne sont jamais
exposés par les vues API. Les mots de passe utilisateurs sont uniquement
stockés sous forme de condensat Passlib.
"""

import secrets

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Organization(Base):
    """Société juridique pouvant contenir plusieurs agences."""

    __tablename__ = "admin_organizations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    legal_name = Column(String(255))
    registration_number = Column(String(80))
    tax_number = Column(String(80))
    address = Column(String(500))
    postal_code = Column(String(20))
    city = Column(String(120))
    country = Column(String(80), default="France")
    phone = Column(String(40))
    email = Column(String(255))
    logo_url = Column(String(500))
    primary_color = Column(String(20), default="#1f6feb")
    secondary_color = Column(String(20), default="#ffffff")
    fiscal_settings = Column(JSON, default=dict)
    document_templates = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    agencies = relationship("Agency", back_populates="organization", cascade="all, delete-orphan")


class Agency(Base):
    __tablename__ = "admin_agencies"
    __table_args__ = (UniqueConstraint("organization_id", "code", name="uq_agency_org_code"),)

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(
        Integer, ForeignKey("admin_organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code = Column(String(30), nullable=False)
    name = Column(String(255), nullable=False)
    address = Column(String(500))
    postal_code = Column(String(20))
    city = Column(String(120))
    country = Column(String(80), default="France")
    phone = Column(String(40))
    email = Column(String(255))
    logo_url = Column(String(500))
    primary_color = Column(String(20))
    settings = Column(JSON, default=dict)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    organization = relationship("Organization", back_populates="agencies")


class AdminRole(Base):
    __tablename__ = "admin_roles"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_admin_role_org_name"),)

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("admin_organizations.id", ondelete="CASCADE"), index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text)
    profile_key = Column(String(50), index=True)  # super_admin | manager | agent | accountant | viewer
    is_system = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    permissions = relationship("RolePermission", back_populates="role", cascade="all, delete-orphan")


class RolePermission(Base):
    """Droit granulaire par module, action CRUD et périmètre."""

    __tablename__ = "admin_role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "module", name="uq_role_permission_module"),)

    id = Column(Integer, primary_key=True)
    role_id = Column(Integer, ForeignKey("admin_roles.id", ondelete="CASCADE"), nullable=False, index=True)
    module = Column(String(80), nullable=False, index=True)
    actions = Column(JSON, default=list, nullable=False)  # create | read | update | delete | export | admin
    scope_type = Column(String(20), default="assigned", nullable=False)  # all | entity | agency | portfolio | assigned
    scope_ids = Column(JSON, default=list)

    role = relationship("AdminRole", back_populates="permissions")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    public_id = Column(String(40), unique=True, nullable=False, default=lambda: secrets.token_hex(16), index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    phone = Column(String(40))
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_superuser = Column(Boolean, default=False, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)
    password_changed_at = Column(DateTime(timezone=True), server_default=func.now())
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True))
    two_factor_enabled = Column(Boolean, default=False, nullable=False)
    two_factor_method = Column(String(20))  # authenticator | email | sms
    two_factor_secret = Column(String(128))
    locale = Column(String(10), default="fr")
    timezone = Column(String(80), default="Europe/Paris")
    last_login_at = Column(DateTime(timezone=True))
    deactivated_at = Column(DateTime(timezone=True))
    deactivated_reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    role_assignments = relationship("UserRoleAssignment", back_populates="user", cascade="all, delete-orphan")
    scopes = relationship("UserScope", back_populates="user", cascade="all, delete-orphan")


class UserRoleAssignment(Base):
    __tablename__ = "admin_user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", "organization_id", "agency_id", name="uq_user_role_scope"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = Column(Integer, ForeignKey("admin_roles.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("admin_organizations.id", ondelete="CASCADE"), index=True)
    agency_id = Column(Integer, ForeignKey("admin_agencies.id", ondelete="CASCADE"), index=True)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    assigned_by = Column(String(255))

    user = relationship("AdminUser", back_populates="role_assignments")
    role = relationship("AdminRole")


class UserScope(Base):
    """Périmètre de données explicite d'un utilisateur."""

    __tablename__ = "admin_user_scopes"
    __table_args__ = (UniqueConstraint("user_id", "organization_id", "agency_id", name="uq_user_data_scope"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("admin_organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    agency_id = Column(Integer, ForeignKey("admin_agencies.id", ondelete="CASCADE"), index=True)
    portfolio_ids = Column(JSON, default=list)
    is_default = Column(Boolean, default=False, nullable=False)

    user = relationship("AdminUser", back_populates="scopes")


class SecurityPolicy(Base):
    __tablename__ = "admin_security_policy"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("admin_organizations.id", ondelete="CASCADE"), unique=True, index=True)
    password_min_length = Column(Integer, default=10, nullable=False)
    require_uppercase = Column(Boolean, default=True, nullable=False)
    require_lowercase = Column(Boolean, default=True, nullable=False)
    require_digit = Column(Boolean, default=True, nullable=False)
    require_special = Column(Boolean, default=True, nullable=False)
    password_expiry_days = Column(Integer, default=0, nullable=False)
    password_history_count = Column(Integer, default=5, nullable=False)
    max_login_attempts = Column(Integer, default=5, nullable=False)
    lockout_minutes = Column(Integer, default=15, nullable=False)
    session_timeout_minutes = Column(Integer, default=30, nullable=False)
    refresh_token_days = Column(Integer, default=7, nullable=False)
    require_2fa = Column(Boolean, default=False, nullable=False)
    allowed_2fa_methods = Column(JSON, default=lambda: ["authenticator", "email", "sms"])
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PasswordHistory(Base):
    __tablename__ = "admin_password_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    changed_at = Column(DateTime(timezone=True), server_default=func.now())


class LoginHistory(Base):
    __tablename__ = "admin_login_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="SET NULL"), index=True)
    email = Column(String(255), nullable=False, index=True)
    success = Column(Boolean, nullable=False, index=True)
    failure_reason = Column(String(80))
    ip_address = Column(String(64), index=True)
    user_agent = Column(String(500))
    method = Column(String(30), default="password")
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class SecuritySession(Base):
    __tablename__ = "admin_security_sessions"

    id = Column(String(64), primary_key=True, default=lambda: secrets.token_hex(24))
    user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_token_hash = Column(String(64), index=True)
    ip_address = Column(String(64))
    user_agent = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_seen_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at = Column(DateTime(timezone=True), index=True)
    revoke_reason = Column(String(120))


class AuthChallenge(Base):
    __tablename__ = "admin_auth_challenges"

    id = Column(String(64), primary_key=True, default=lambda: secrets.token_urlsafe(32))
    user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True)
    purpose = Column(String(30), nullable=False)  # login_2fa | setup_2fa | biometric
    method = Column(String(30), nullable=False)
    code_hash = Column(String(64))
    challenge = Column(String(255))
    attempts = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TrustedDevice(Base):
    """Clé publique enregistrée par une application utilisant Face ID/empreinte."""

    __tablename__ = "admin_trusted_devices"
    __table_args__ = (UniqueConstraint("user_id", "device_identifier", name="uq_user_device"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("admin_users.id", ondelete="CASCADE"), nullable=False, index=True)
    device_identifier = Column(String(128), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    platform = Column(String(30))
    public_key_pem = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True))


class SSOProvider(Base):
    __tablename__ = "admin_sso_providers"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("admin_organizations.id", ondelete="CASCADE"), index=True)
    name = Column(String(100), nullable=False)
    slug = Column(String(80), unique=True, nullable=False, index=True)
    protocol = Column(String(20), nullable=False)  # oauth2 | saml
    client_id = Column(String(255))
    encrypted_client_secret = Column(LargeBinary)
    authorization_url = Column(String(700))
    token_url = Column(String(700))
    userinfo_url = Column(String(700))
    scopes = Column(JSON, default=list)
    issuer = Column(String(500))
    metadata_url = Column(String(700))
    entity_id = Column(String(500))
    certificate = Column(Text)
    email_claim = Column(String(100), default="email")
    auto_provision = Column(Boolean, default=False, nullable=False)
    default_role_id = Column(Integer, ForeignKey("admin_roles.id", ondelete="SET NULL"))
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class GeneralSettings(Base):
    __tablename__ = "admin_general_settings"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("admin_organizations.id", ondelete="CASCADE"), unique=True, index=True)
    currency = Column(String(3), default="EUR", nullable=False)
    language = Column(String(10), default="fr", nullable=False)
    date_format = Column(String(30), default="DD/MM/YYYY", nullable=False)
    timezone = Column(String(80), default="Europe/Paris", nullable=False)
    numbering = Column(JSON, default=dict)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class NumberingSequence(Base):
    """Compteur transactionnel pour factures, baux et documents."""

    __tablename__ = "admin_numbering_sequences"
    __table_args__ = (UniqueConstraint("organization_id", "document_type", "period", name="uq_numbering_period"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("admin_organizations.id", ondelete="CASCADE"), index=True)
    document_type = Column(String(50), nullable=False, index=True)
    period = Column(String(20), default="global", nullable=False)
    prefix = Column(String(80), default="")
    next_value = Column(Integer, default=1, nullable=False)
    padding = Column(Integer, default=5, nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ReferenceIndex(Base):
    __tablename__ = "admin_reference_indices"
    __table_args__ = (UniqueConstraint("organization_id", "code", "period", name="uq_reference_index_period"),)

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("admin_organizations.id", ondelete="CASCADE"), index=True)
    code = Column(String(20), nullable=False, index=True)  # IRL | ICC | ILAT | ILC | custom
    label = Column(String(255))
    period = Column(String(20), nullable=False)  # 2026-Q1, 2026-M01...
    value = Column(String(40), nullable=False)  # Decimal sérialisé sans perte
    publication_date = Column(Date)
    source_url = Column(String(700))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SMTPSettings(Base):
    __tablename__ = "admin_smtp_settings"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, ForeignKey("admin_organizations.id", ondelete="CASCADE"), unique=True, index=True)
    host = Column(String(255))
    port = Column(Integer, default=587)
    username = Column(String(255))
    encrypted_password = Column(LargeBinary)
    from_email = Column(String(255))
    from_name = Column(String(255))
    use_tls = Column(Boolean, default=True, nullable=False)
    use_ssl = Column(Boolean, default=False, nullable=False)
    is_enabled = Column(Boolean, default=False, nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, index=True)
    agency_id = Column(Integer, index=True)
    actor_user_id = Column(Integer, index=True)
    actor_email = Column(String(255), index=True)
    action = Column(String(50), nullable=False, index=True)
    module = Column(String(80), nullable=False, index=True)
    resource_type = Column(String(100), index=True)
    resource_id = Column(String(100), index=True)
    description = Column(Text)
    before_data = Column(JSON)
    after_data = Column(JSON)
    ip_address = Column(String(64), index=True)
    user_agent = Column(String(500))
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class BackupRecord(Base):
    __tablename__ = "admin_backups"

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), unique=True, nullable=False)
    storage_path = Column(String(700), nullable=False)
    database_kind = Column(String(30), nullable=False)
    trigger = Column(String(20), nullable=False)  # manual | daily
    status = Column(String(30), default="pending", nullable=False, index=True)
    size_bytes = Column(Integer)
    checksum_sha256 = Column(String(64))
    encrypted = Column(Boolean, default=False, nullable=False)
    error_message = Column(Text)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True))
    restored_at = Column(DateTime(timezone=True))


class BackupPolicy(Base):
    __tablename__ = "admin_backup_policy"

    id = Column(Integer, primary_key=True)
    enabled = Column(Boolean, default=True, nullable=False)
    daily_hour_utc = Column(Integer, default=2, nullable=False)
    retention_days = Column(Integer, default=30, nullable=False)
    last_run_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ConsentRecord(Base):
    __tablename__ = "admin_gdpr_consents"

    id = Column(Integer, primary_key=True)
    subject_type = Column(String(30), nullable=False, index=True)  # tenant | owner | prospect | user
    subject_id = Column(String(100), nullable=False, index=True)
    purpose = Column(String(100), nullable=False, index=True)
    granted = Column(Boolean, nullable=False)
    legal_text_version = Column(String(50), nullable=False)
    source = Column(String(50))
    ip_address = Column(String(64))
    recorded_at = Column(DateTime(timezone=True), server_default=func.now())
    withdrawn_at = Column(DateTime(timezone=True))


class DataProcessingRecord(Base):
    __tablename__ = "admin_gdpr_processing_register"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, index=True)
    name = Column(String(255), nullable=False)
    purpose = Column(Text, nullable=False)
    legal_basis = Column(String(100), nullable=False)
    data_categories = Column(JSON, default=list)
    subject_categories = Column(JSON, default=list)
    recipients = Column(JSON, default=list)
    retention_period = Column(String(255))
    safeguards = Column(Text)
    international_transfers = Column(Text)
    owner = Column(String(255))
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PrivacyPolicy(Base):
    __tablename__ = "admin_privacy_policies"

    id = Column(Integer, primary_key=True)
    organization_id = Column(Integer, index=True)
    version = Column(String(50), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    is_published = Column(Boolean, default=False, nullable=False, index=True)
    published_at = Column(DateTime(timezone=True))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DataSubjectRequest(Base):
    __tablename__ = "admin_gdpr_requests"

    id = Column(Integer, primary_key=True)
    reference = Column(String(40), unique=True, nullable=False, index=True)
    request_type = Column(String(30), nullable=False, index=True)  # erasure | portability | access | rectification
    subject_type = Column(String(30), nullable=False)
    subject_id = Column(String(100), nullable=False, index=True)
    requester_email = Column(String(255))
    status = Column(String(30), default="received", nullable=False, index=True)
    reason = Column(Text)
    verification_details = Column(JSON, default=dict)
    result_path = Column(String(700))
    rejection_reason = Column(Text)
    requested_at = Column(DateTime(timezone=True), server_default=func.now())
    due_at = Column(DateTime(timezone=True))
    processed_at = Column(DateTime(timezone=True))
    processed_by = Column(String(255))
