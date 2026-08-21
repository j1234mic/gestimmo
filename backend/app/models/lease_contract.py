"""Modèles du module 4 : baux, signatures, révisions et états des lieux."""

import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
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


class LeaseContractType(str, enum.Enum):
    RESIDENTIAL_UNFURNISHED = "residential_unfurnished"
    RESIDENTIAL_FURNISHED = "residential_furnished"
    COMMERCIAL_369 = "commercial_369"
    PROFESSIONAL = "professional"
    SHORT_TERM_DEROGATORY = "short_term_derogatory"
    SEASONAL = "seasonal"
    PRECARIOUS_OCCUPANCY = "precarious_occupancy"
    MIXED_USE = "mixed_use"


class ChargeMethod(str, enum.Enum):
    FLAT = "flat"
    PROVISION = "provision"


class RentFrequency(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"


class RentIndexType(str, enum.Enum):
    NONE = "none"
    IRL = "irl"
    ICC = "icc"
    ILAT = "ilat"
    ILC = "ilc"
    CUSTOM = "custom"


class RevisionStatus(str, enum.Enum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    APPLIED = "applied"
    CANCELLED = "cancelled"


class RenewalMode(str, enum.Enum):
    AUTOMATIC = "automatic"
    AMENDMENT = "amendment"
    NEW_LEASE = "new_lease"


class RenewalStatus(str, enum.Enum):
    PLANNED = "planned"
    NOTIFIED = "notified"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class NoticeGivenBy(str, enum.Enum):
    TENANT = "tenant"
    OWNER = "owner"


class NoticeReason(str, enum.Enum):
    TENANT_DEPARTURE = "tenant_departure"
    SALE = "sale"
    REPOSSESSION = "repossession"
    LEGITIMATE_REASON = "legitimate_reason"
    LEASE_EXPIRY = "lease_expiry"
    OTHER = "other"


class NoticeStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ContractDocumentType(str, enum.Enum):
    LEASE = "lease"
    DPE = "dpe"
    ERNMT = "ernmt"
    LEAD_DIAGNOSIS = "lead_diagnosis"
    ASBESTOS_DIAGNOSIS = "asbestos_diagnosis"
    CONDO_RULES_EXTRACT = "condo_rules_extract"
    INFORMATION_NOTICE = "information_notice"
    AMENDMENT = "amendment"
    NOTICE_LETTER = "notice_letter"
    ENTRY_INSPECTION = "entry_inspection"
    EXIT_INSPECTION = "exit_inspection"
    SIGNATURE_CERTIFICATE = "signature_certificate"
    INSURANCE = "insurance"
    OTHER = "other"


class ArchiveStatus(str, enum.Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DESTROYED = "destroyed"


class SignatureEnvelopeStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    PARTIALLY_SIGNED = "partially_signed"
    COMPLETED = "completed"
    DECLINED = "declined"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SignaturePartyStatus(str, enum.Enum):
    PENDING = "pending"
    VIEWED = "viewed"
    SIGNED = "signed"
    DECLINED = "declined"


class InspectionType(str, enum.Enum):
    ENTRY = "entry"
    EXIT = "exit"
    INTERMEDIATE = "intermediate"


class InspectionStatus(str, enum.Enum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    READY_FOR_SIGNATURE = "ready_for_signature"
    SIGNED = "signed"
    ARCHIVED = "archived"


class ItemCondition(str, enum.Enum):
    NEW = "new"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    DAMAGED = "damaged"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class LeaseTemplate(Base):
    __tablename__ = "lease_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    lease_type = Column(Enum(LeaseContractType), nullable=False, index=True)
    description = Column(Text)
    title_template = Column(String(500), default="Contrat de location — ${property_address}")
    introduction_template = Column(Text)
    footer_template = Column(Text)
    variables_schema = Column(JSON, default=dict)
    version = Column(Integer, default=1, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    clauses = relationship("LeaseTemplateClause", back_populates="template", cascade="all, delete-orphan")


class LeaseClause(Base):
    __tablename__ = "lease_clauses"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(80), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content_template = Column(Text, nullable=False)
    compatible_lease_types = Column(JSON, default=list)
    category = Column(String(100), default="general")
    is_mandatory = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class LeaseTemplateClause(Base):
    __tablename__ = "lease_template_clauses"
    __table_args__ = (UniqueConstraint("template_id", "clause_id", name="uq_template_clause"),)

    id = Column(Integer, primary_key=True)
    template_id = Column(Integer, ForeignKey("lease_templates.id", ondelete="CASCADE"), nullable=False)
    clause_id = Column(Integer, ForeignKey("lease_clauses.id", ondelete="CASCADE"), nullable=False)
    display_order = Column(Integer, default=0)
    is_required = Column(Boolean, default=False)

    template = relationship("LeaseTemplate", back_populates="clauses")
    clause = relationship("LeaseClause")


class LeaseContractSettings(Base):
    __tablename__ = "lease_contract_settings"

    id = Column(Integer, primary_key=True, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    lease_type = Column(Enum(LeaseContractType), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("lease_templates.id", ondelete="SET NULL"))
    duration_months = Column(Integer)
    tacit_renewal = Column(Boolean, default=True, nullable=False)
    renewal_notice_months = Column(Integer, default=6)
    charge_method = Column(Enum(ChargeMethod), default=ChargeMethod.PROVISION, nullable=False)
    rent_frequency = Column(Enum(RentFrequency), default=RentFrequency.MONTHLY, nullable=False)
    payment_method = Column(String(80), default="bank_transfer")
    rent_index_type = Column(Enum(RentIndexType), default=RentIndexType.NONE, nullable=False)
    base_index_value = Column(Float)
    base_index_date = Column(Date)
    next_revision_date = Column(Date)
    resolutory_clause = Column(Boolean, default=True, nullable=False)
    resolutory_clause_text = Column(Text)
    special_conditions = Column(Text)
    custom_variables = Column(JSON, default=dict)
    contract_version = Column(Integer, default=1, nullable=False)
    pdf_document_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="SET NULL"))
    signature_status = Column(String(30), default="not_started")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    lease = relationship("Lease")
    template = relationship("LeaseTemplate")
    clause_assignments = relationship("LeaseClauseAssignment", back_populates="settings", cascade="all, delete-orphan")
    pdf_document = relationship("ContractDocument", foreign_keys=[pdf_document_id], post_update=True)


class LeaseClauseAssignment(Base):
    __tablename__ = "lease_clause_assignments"

    id = Column(Integer, primary_key=True)
    settings_id = Column(Integer, ForeignKey("lease_contract_settings.id", ondelete="CASCADE"), nullable=False, index=True)
    clause_id = Column(Integer, ForeignKey("lease_clauses.id", ondelete="SET NULL"))
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    display_order = Column(Integer, default=0)
    is_required = Column(Boolean, default=False)
    source = Column(String(30), default="custom")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    settings = relationship("LeaseContractSettings", back_populates="clause_assignments")
    clause = relationship("LeaseClause")


class RentIndexValue(Base):
    __tablename__ = "rent_index_values"
    __table_args__ = (UniqueConstraint("index_type", "period", "geography", name="uq_rent_index_period_geo"),)

    id = Column(Integer, primary_key=True)
    index_type = Column(Enum(RentIndexType), nullable=False, index=True)
    period = Column(String(20), nullable=False)
    publication_date = Column(Date, nullable=False)
    value = Column(Float, nullable=False)
    geography = Column(String(100), default="France", nullable=False)
    source = Column(String(255))
    source_url = Column(String(1000))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RentCapRule(Base):
    __tablename__ = "rent_cap_rules"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    lease_type = Column(Enum(LeaseContractType))
    geography = Column(String(100), default="France")
    valid_from = Column(Date, nullable=False)
    valid_to = Column(Date)
    maximum_increase_percent = Column(Float, nullable=False)
    legal_reference = Column(String(500), nullable=False)
    source_url = Column(String(1000))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class RentRevision(Base):
    __tablename__ = "rent_revisions"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(Enum(RevisionStatus), default=RevisionStatus.DRAFT, nullable=False)
    effective_date = Column(Date, nullable=False)
    old_rent = Column(Float, nullable=False)
    index_type = Column(Enum(RentIndexType), nullable=False)
    old_index_value = Column(Float, nullable=False)
    new_index_value = Column(Float, nullable=False)
    calculated_rent = Column(Float, nullable=False)
    cap_rule_id = Column(Integer, ForeignKey("rent_cap_rules.id", ondelete="SET NULL"))
    cap_percent = Column(Float)
    capped_rent = Column(Float, nullable=False)
    applied_rent = Column(Float)
    calculation_details = Column(JSON, default=dict)
    tenant_notified_at = Column(DateTime(timezone=True))
    applied_at = Column(DateTime(timezone=True))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lease = relationship("Lease")
    cap_rule = relationship("RentCapRule")


class LeaseRenewal(Base):
    __tablename__ = "lease_renewals"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    mode = Column(Enum(RenewalMode), nullable=False)
    status = Column(Enum(RenewalStatus), default=RenewalStatus.PLANNED, nullable=False)
    planned_date = Column(Date, nullable=False)
    new_end_date = Column(Date)
    new_rent = Column(Float)
    amendment_id = Column(Integer, ForeignKey("lease_amendments.id", ondelete="SET NULL"))
    new_lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="SET NULL"))
    notified_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lease = relationship("Lease", foreign_keys=[lease_id])
    new_lease = relationship("Lease", foreign_keys=[new_lease_id])


class LeaseAmendment(Base):
    __tablename__ = "lease_amendments"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    amendment_number = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    effective_date = Column(Date, nullable=False)
    reason = Column(Text)
    changes = Column(JSON, default=dict)
    clauses = Column(JSON, default=list)
    document_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="SET NULL"))
    status = Column(String(30), default="draft", nullable=False)
    signature_status = Column(String(30), default="not_started")
    applied_at = Column(DateTime(timezone=True))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lease = relationship("Lease")
    document = relationship("ContractDocument", foreign_keys=[document_id], post_update=True)


class LeaseNotice(Base):
    __tablename__ = "lease_notices"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    given_by = Column(Enum(NoticeGivenBy), nullable=False)
    reason = Column(Enum(NoticeReason), nullable=False)
    reason_details = Column(Text)
    notice_date = Column(Date, nullable=False)
    notice_period_months = Column(Integer, nullable=False)
    effective_end_date = Column(Date, nullable=False)
    legal_basis = Column(String(500))
    delivery_method = Column(String(100))
    status = Column(Enum(NoticeStatus), default=NoticeStatus.DRAFT, nullable=False)
    letter_document_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="SET NULL"))
    sent_at = Column(DateTime(timezone=True))
    acknowledged_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lease = relationship("Lease")
    letter_document = relationship("ContractDocument", foreign_keys=[letter_document_id], post_update=True)


class ContractDocument(Base):
    __tablename__ = "contract_documents"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type = Column(Enum(ContractDocumentType), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    original_filename = Column(String(255))
    storage_path = Column(String(700), nullable=False)
    mime_type = Column(String(100), default="application/pdf")
    file_size = Column(Integer)
    checksum_sha256 = Column(String(64), nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    is_required = Column(Boolean, default=False)
    archive_status = Column(Enum(ArchiveStatus), default=ArchiveStatus.ACTIVE, nullable=False)
    archived_at = Column(DateTime(timezone=True))
    retention_until = Column(Date)
    legal_hold = Column(Boolean, default=False)
    signed_at = Column(DateTime(timezone=True))
    uploaded_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lease = relationship("Lease")


class SignatureEnvelope(Base):
    __tablename__ = "signature_envelopes"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="RESTRICT"), nullable=False)
    subject = Column(String(255), nullable=False)
    message = Column(Text)
    provider = Column(String(50), default="internal_simple_signature")
    status = Column(Enum(SignatureEnvelopeStatus), default=SignatureEnvelopeStatus.PENDING, nullable=False)
    expires_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    evidence_document_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="SET NULL"))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lease = relationship("Lease")
    document = relationship("ContractDocument", foreign_keys=[document_id])
    evidence_document = relationship("ContractDocument", foreign_keys=[evidence_document_id], post_update=True)
    parties = relationship("SignatureParty", back_populates="envelope", cascade="all, delete-orphan")


class SignatureParty(Base):
    __tablename__ = "signature_parties"

    id = Column(Integer, primary_key=True, index=True)
    envelope_id = Column(Integer, ForeignKey("signature_envelopes.id", ondelete="CASCADE"), nullable=False, index=True)
    party_type = Column(String(30), nullable=False)
    party_id = Column(Integer)
    full_name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    signing_order = Column(Integer, default=1)
    access_token_hash = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(Enum(SignaturePartyStatus), default=SignaturePartyStatus.PENDING, nullable=False)
    viewed_at = Column(DateTime(timezone=True))
    signed_at = Column(DateTime(timezone=True))
    declined_at = Column(DateTime(timezone=True))
    decline_reason = Column(Text)
    typed_signature = Column(String(255))
    signature_image_path = Column(String(700))
    consent_text = Column(Text)
    ip_address = Column(String(64))
    user_agent = Column(String(1000))
    signed_document_checksum = Column(String(64))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    envelope = relationship("SignatureEnvelope", back_populates="parties")


class PropertyInspection(Base):
    __tablename__ = "property_inspections"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False)
    client_uuid = Column(String(36), unique=True, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    inspection_type = Column(Enum(InspectionType), nullable=False, index=True)
    status = Column(Enum(InspectionStatus), default=InspectionStatus.DRAFT, nullable=False)
    inspection_date = Column(DateTime(timezone=True), nullable=False)
    conducted_by = Column(String(255))
    general_comments = Column(Text)
    comparison_inspection_id = Column(Integer, ForeignKey("property_inspections.id", ondelete="SET NULL"))
    document_id = Column(Integer, ForeignKey("contract_documents.id", ondelete="SET NULL"))
    total_suggested_deductions = Column(Float, default=0)
    total_approved_deductions = Column(Float, default=0)
    sync_version = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    lease = relationship("Lease")
    comparison_inspection = relationship("PropertyInspection", remote_side=[id])
    document = relationship("ContractDocument", foreign_keys=[document_id], post_update=True)
    rooms = relationship("InspectionRoom", back_populates="inspection", cascade="all, delete-orphan")
    meters = relationship("InspectionMeter", back_populates="inspection", cascade="all, delete-orphan")
    keys = relationship("InspectionKey", back_populates="inspection", cascade="all, delete-orphan")
    photos = relationship("InspectionPhoto", back_populates="inspection", cascade="all, delete-orphan")
    signatures = relationship("InspectionSignature", back_populates="inspection", cascade="all, delete-orphan")
    deductions = relationship("InspectionDeduction", back_populates="inspection", cascade="all, delete-orphan")


class InspectionRoom(Base):
    __tablename__ = "inspection_rooms"
    __table_args__ = (UniqueConstraint("inspection_id", "client_uuid", name="uq_inspection_room_client"),)

    id = Column(Integer, primary_key=True)
    inspection_id = Column(Integer, ForeignKey("property_inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    client_uuid = Column(String(36))
    name = Column(String(150), nullable=False)
    room_type = Column(String(80))
    display_order = Column(Integer, default=0)
    comments = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    inspection = relationship("PropertyInspection", back_populates="rooms")
    items = relationship("InspectionItem", back_populates="room", cascade="all, delete-orphan")


class InspectionItem(Base):
    __tablename__ = "inspection_items"
    __table_args__ = (UniqueConstraint("room_id", "client_uuid", name="uq_inspection_item_client"),)

    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("inspection_rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    client_uuid = Column(String(36))
    category = Column(String(50), nullable=False)  # floor, wall, ceiling, equipment
    name = Column(String(255), nullable=False)
    condition = Column(Enum(ItemCondition), nullable=False)
    cleanliness = Column(String(50))
    description = Column(Text)
    estimated_repair_cost = Column(Float, default=0)
    depreciation_percent = Column(Float, default=0)
    tenant_responsibility_percent = Column(Float, default=100)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    room = relationship("InspectionRoom", back_populates="items")
    photos = relationship("InspectionPhoto", back_populates="item")


class InspectionMeter(Base):
    __tablename__ = "inspection_meters"

    id = Column(Integer, primary_key=True)
    inspection_id = Column(Integer, ForeignKey("property_inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    meter_type = Column(String(30), nullable=False)  # water, gas, electricity
    serial_number = Column(String(100))
    reading = Column(String(100), nullable=False)
    unit = Column(String(30))
    location = Column(String(255))
    photo_id = Column(Integer, ForeignKey("inspection_photos.id", ondelete="SET NULL"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    inspection = relationship("PropertyInspection", back_populates="meters")


class InspectionKey(Base):
    __tablename__ = "inspection_keys"

    id = Column(Integer, primary_key=True)
    inspection_id = Column(Integer, ForeignKey("property_inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    key_type = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    comments = Column(Text)

    inspection = relationship("PropertyInspection", back_populates="keys")


class InspectionPhoto(Base):
    __tablename__ = "inspection_photos"

    id = Column(Integer, primary_key=True)
    inspection_id = Column(Integer, ForeignKey("property_inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    room_id = Column(Integer, ForeignKey("inspection_rooms.id", ondelete="CASCADE"))
    item_id = Column(Integer, ForeignKey("inspection_items.id", ondelete="SET NULL"))
    original_filename = Column(String(255))
    storage_path = Column(String(700), nullable=False)
    mime_type = Column(String(100))
    checksum_sha256 = Column(String(64), nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    latitude = Column(Float)
    longitude = Column(Float)
    caption = Column(String(500))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    inspection = relationship("PropertyInspection", back_populates="photos")
    room = relationship("InspectionRoom")
    item = relationship("InspectionItem", back_populates="photos")


class InspectionSignature(Base):
    __tablename__ = "inspection_signatures"

    id = Column(Integer, primary_key=True)
    inspection_id = Column(Integer, ForeignKey("property_inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    signer_type = Column(String(30), nullable=False)
    signer_name = Column(String(255), nullable=False)
    signer_email = Column(String(255))
    signature_image_path = Column(String(700), nullable=False)
    consent_text = Column(Text, nullable=False)
    signed_at = Column(DateTime(timezone=True), server_default=func.now())
    ip_address = Column(String(64))
    user_agent = Column(String(1000))
    document_checksum = Column(String(64))

    inspection = relationship("PropertyInspection", back_populates="signatures")


class InspectionDeduction(Base):
    __tablename__ = "inspection_deductions"

    id = Column(Integer, primary_key=True)
    inspection_id = Column(Integer, ForeignKey("property_inspections.id", ondelete="CASCADE"), nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("inspection_items.id", ondelete="SET NULL"))
    label = Column(String(500), nullable=False)
    deterioration = Column(String(100))
    estimated_cost = Column(Float, nullable=False)
    depreciation_percent = Column(Float, default=0)
    responsibility_percent = Column(Float, default=100)
    suggested_amount = Column(Float, nullable=False)
    approved_amount = Column(Float)
    approval_notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    inspection = relationship("PropertyInspection", back_populates="deductions")
    item = relationship("InspectionItem")


class ContractEvent(Base):
    __tablename__ = "contract_events"

    id = Column(Integer, primary_key=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(80), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    details = Column(JSON, default=dict)
    actor = Column(String(255))
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    lease = relationship("Lease")
