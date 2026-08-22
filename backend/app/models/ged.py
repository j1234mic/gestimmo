"""Modèles du module 11 : gestion documentaire (GED).

Arborescence, versioning, modèles de génération, signature électronique
journalisée, OCR / classification, audit, rétention et gel juridique.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class GedFolder(Base):
    """Dossier / sous-dossier de l'arborescence documentaire."""

    __tablename__ = "ged_folders"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    parent_id = Column(Integer, ForeignKey("ged_folders.id", ondelete="CASCADE"), nullable=True, index=True)
    scope = Column(String(30), default="custom", nullable=False, index=True)
    # property | owner | tenant | contract | type | custom
    property_id = Column(Integer, index=True)
    owner_id = Column(Integer, index=True)
    tenant_id = Column(Integer, index=True)
    lease_id = Column(Integer, index=True)
    document_type = Column(String(50), index=True)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    parent = relationship("GedFolder", remote_side="GedFolder.id", backref="children")
    documents = relationship("GedDocument", back_populates="folder")


class GedDocument(Base):
    __tablename__ = "ged_documents"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    folder_id = Column(Integer, ForeignKey("ged_folders.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    document_type = Column(String(50), default="other", nullable=False, index=True)
    original_filename = Column(String(255))
    storage_path = Column(String(700))
    mime_type = Column(String(100))
    file_size = Column(Integer)
    file_hash = Column(String(64), index=True)
    current_version = Column(Integer, default=1, nullable=False)
    tags = Column(JSON, default=list)
    ocr_text = Column(Text)
    ocr_confidence = Column(Float, default=0)
    extracted_data = Column(JSON, default=dict)
    classification = Column(String(50))
    classification_source = Column(String(20))  # auto | manual
    property_id = Column(Integer, index=True)
    owner_id = Column(Integer, index=True)
    tenant_id = Column(Integer, index=True)
    lease_id = Column(Integer, index=True)
    retention_years = Column(Integer)
    retain_until = Column(Date, index=True)
    legal_hold = Column(Boolean, default=False, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False, index=True)
    deleted_at = Column(DateTime(timezone=True))
    deleted_reason = Column(String(255))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    folder = relationship("GedFolder", back_populates="documents")
    versions = relationship(
        "GedDocumentVersion", back_populates="document", cascade="all, delete-orphan"
    )
    envelopes = relationship("GedSignatureEnvelope", back_populates="document")
    audit_logs = relationship("GedAuditLog", back_populates="document", cascade="all, delete-orphan")


class GedDocumentVersion(Base):
    __tablename__ = "ged_versions"
    __table_args__ = (UniqueConstraint("document_id", "version_number", name="uq_ged_version"),)

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("ged_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    storage_path = Column(String(700), nullable=False)
    file_size = Column(Integer)
    file_hash = Column(String(64))
    mime_type = Column(String(100))
    original_filename = Column(String(255))
    comment = Column(String(255))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("GedDocument", back_populates="versions")


class GedTemplate(Base):
    """Modèle de document générable (fusion publipostage)."""

    __tablename__ = "ged_templates"

    id = Column(Integer, primary_key=True)
    key = Column(String(80), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(50), nullable=False, index=True)
    body = Column(Text, nullable=False)
    variables = Column(JSON, default=list)
    is_system = Column(Boolean, default=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    updated_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class GedSignatureEnvelope(Base):
    """Enveloppe de signature électronique (DocuSign / Yousign / HelloSign)."""

    __tablename__ = "ged_envelopes"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("ged_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(30), default="yousign", nullable=False)
    signature_level = Column(String(20), default="simple", nullable=False)
    # simple | advanced | qualified
    status = Column(String(20), default="draft", nullable=False, index=True)
    # draft | sent | in_progress | completed | declined | expired
    provider_envelope_id = Column(String(255))
    evidence_path = Column(String(700))
    evidence_hash = Column(String(64))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    sent_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    document = relationship("GedDocument", back_populates="envelopes")
    signers = relationship("GedSigner", back_populates="envelope", cascade="all, delete-orphan")


class GedSigner(Base):
    __tablename__ = "ged_signers"

    id = Column(Integer, primary_key=True)
    envelope_id = Column(Integer, ForeignKey("ged_envelopes.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    role = Column(String(50))
    signing_order = Column(Integer, default=1, nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    signed_at = Column(DateTime(timezone=True))
    ip_address = Column(String(64))
    user_agent = Column(String(255))
    consent_text = Column(Text)
    signature_hash = Column(String(64))
    token = Column(String(64), unique=True, index=True)

    envelope = relationship("GedSignatureEnvelope", back_populates="signers")


class GedAuditLog(Base):
    """Traçabilité : qui a vu / modifié / téléchargé un document."""

    __tablename__ = "ged_audit"

    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("ged_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(30), nullable=False, index=True)
    actor = Column(String(255), nullable=False)
    actor_role = Column(String(30))
    details = Column(JSON, default=dict)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    document = relationship("GedDocument", back_populates="audit_logs")


class GedSettings(Base):
    """Paramètres globaux de la GED (une seule ligne attendue)."""

    __tablename__ = "ged_settings"

    id = Column(Integer, primary_key=True)
    max_upload_mb = Column(Integer, default=20, nullable=False)
    compress_images = Column(Boolean, default=True, nullable=False)
    default_retention_years = Column(Integer, default=10, nullable=False)
    allowed_extensions = Column(JSON, default=list)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
