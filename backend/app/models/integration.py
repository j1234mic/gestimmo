"""Module 17 — intégrations, API publique, webhooks et transferts de données."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.database import Base


class APICredential(Base):
    """Clé d'API dont seul le condensat est conservé."""

    __tablename__ = "integration_api_credentials"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    key_prefix = Column(String(20), unique=True, nullable=False, index=True)
    key_hash = Column(String(64), unique=True, nullable=False)
    scopes = Column(JSON, default=list)
    rate_limit_per_minute = Column(Integer, default=100, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), index=True)
    last_used_at = Column(DateTime(timezone=True))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True))


class OAuthClient(Base):
    __tablename__ = "integration_oauth_clients"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    client_id = Column(String(80), unique=True, nullable=False, index=True)
    client_secret_hash = Column(String(64), nullable=False)
    scopes = Column(JSON, default=list)
    rate_limit_per_minute = Column(Integer, default=100, nullable=False)
    is_confidential = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    token_lifetime_seconds = Column(Integer, default=3600, nullable=False)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used_at = Column(DateTime(timezone=True))


class IntegrationConnection(Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint("provider", "name", name="uq_integration_provider_name"),
    )

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False, index=True)
    provider = Column(String(80), nullable=False, index=True)
    status = Column(String(30), default="not_configured", nullable=False, index=True)
    config = Column(JSON, default=dict)
    encrypted_credentials = Column(LargeBinary)
    credential_fields = Column(JSON, default=list)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    last_tested_at = Column(DateTime(timezone=True))
    last_sync_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class IntegrationSyncJob(Base):
    __tablename__ = "integration_sync_jobs"

    id = Column(Integer, primary_key=True)
    connection_id = Column(Integer, nullable=False, index=True)
    direction = Column(String(20), default="pull", nullable=False)
    resource = Column(String(80), nullable=False, index=True)
    status = Column(String(30), default="queued", nullable=False, index=True)
    cursor = Column(String(500))
    records_read = Column(Integer, default=0)
    records_written = Column(Integer, default=0)
    records_failed = Column(Integer, default=0)
    details = Column(JSON, default=dict)
    error = Column(Text)
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class WebhookSubscription(Base):
    __tablename__ = "integration_webhook_subscriptions"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    target_url = Column(String(1000), nullable=False)
    events = Column(JSON, default=list)
    encrypted_secret = Column(LargeBinary, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    failure_count = Column(Integer, default=0, nullable=False)
    disabled_reason = Column(String(255))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class WebhookEvent(Base):
    __tablename__ = "integration_webhook_events"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(80), unique=True, nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    api_version = Column(String(20), default="2026-01", nullable=False)
    data = Column(JSON, default=dict)
    idempotency_key = Column(String(160), index=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class WebhookDelivery(Base):
    __tablename__ = "integration_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("subscription_id", "event_id", "attempt", name="uq_webhook_delivery_attempt"),
    )

    id = Column(Integer, primary_key=True)
    subscription_id = Column(Integer, nullable=False, index=True)
    event_id = Column(Integer, nullable=False, index=True)
    attempt = Column(Integer, default=1, nullable=False)
    status = Column(String(30), default="queued", nullable=False, index=True)
    response_status = Column(Integer)
    response_body = Column(Text)
    error = Column(Text)
    signature = Column(String(80))
    next_retry_at = Column(DateTime(timezone=True), index=True)
    delivered_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DataTransferJob(Base):
    """Analyse/import/export massif avec mapping et rapport d'erreurs."""

    __tablename__ = "integration_data_transfer_jobs"

    id = Column(Integer, primary_key=True)
    reference = Column(String(40), unique=True, nullable=False, index=True)
    operation = Column(String(20), nullable=False, index=True)  # import | export | migration
    entity_type = Column(String(50), nullable=False, index=True)
    source_format = Column(String(20), nullable=False)
    source_system = Column(String(100))
    filename = Column(String(255))
    storage_path = Column(String(700))
    mapping = Column(JSON, default=dict)
    duplicate_strategy = Column(String(20), default="skip")
    status = Column(String(30), default="analysed", nullable=False, index=True)
    columns = Column(JSON, default=list)
    preview = Column(JSON, default=list)
    total_rows = Column(Integer, default=0)
    processed_rows = Column(Integer, default=0)
    created_rows = Column(Integer, default=0)
    updated_rows = Column(Integer, default=0)
    skipped_rows = Column(Integer, default=0)
    failed_rows = Column(Integer, default=0)
    errors = Column(JSON, default=list)
    output_path = Column(String(700))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True))
