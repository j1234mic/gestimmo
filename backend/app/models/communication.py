"""Modèles du module 10 : communication et notifications.

Couvre la messagerie interne (conversations par bien / dossier, fil,
pièces jointes, recherche, archivage), les envois multicanal journalisés
(email, SMS, push, in-app, courrier), les modèles, le centre de
préférences, les scénarios d'automatisation et l'historique.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Conversation(Base):
    """Fil de discussion rattaché à un bien, un dossier ou un contact."""

    __tablename__ = "comm_conversations"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    subject = Column(String(255), nullable=False)
    conversation_type = Column(String(30), default="general", nullable=False, index=True)
    # property | dossier | lease | tenant | owner | general

    property_id = Column(Integer, index=True)
    lease_id = Column(Integer, index=True)
    tenant_id = Column(Integer, index=True)
    owner_id = Column(Integer, index=True)
    deal_id = Column(Integer, index=True)

    is_archived = Column(Boolean, default=False, nullable=False, index=True)
    archived_at = Column(DateTime(timezone=True))
    archived_by = Column(String(255))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    participants = relationship(
        "ConversationParticipant", back_populates="conversation", cascade="all, delete-orphan"
    )
    messages = relationship(
        "ThreadMessage", back_populates="conversation", cascade="all, delete-orphan"
    )


class ConversationParticipant(Base):
    __tablename__ = "comm_participants"
    __table_args__ = (
        UniqueConstraint("conversation_id", "participant_type", "participant_key", name="uq_comm_participant"),
    )

    id = Column(Integer, primary_key=True)
    conversation_id = Column(
        Integer, ForeignKey("comm_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    participant_type = Column(String(20), nullable=False)  # admin | owner | tenant | prospect | agent
    participant_id = Column(Integer)
    participant_key = Column(String(255), nullable=False)  # email ou identifiant stable
    name = Column(String(255))
    email = Column(String(255))
    last_read_at = Column(DateTime(timezone=True))
    joined_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("Conversation", back_populates="participants")


class ThreadMessage(Base):
    __tablename__ = "comm_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(
        Integer, ForeignKey("comm_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_type = Column(String(20), nullable=False)
    sender_id = Column(Integer)
    sender_name = Column(String(255))
    sender_email = Column(String(255))
    body = Column(Text, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    conversation = relationship("Conversation", back_populates="messages")
    attachments = relationship(
        "MessageAttachment", back_populates="message", cascade="all, delete-orphan"
    )


class MessageAttachment(Base):
    __tablename__ = "comm_attachments"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("comm_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    storage_path = Column(String(700), nullable=False)
    mime_type = Column(String(100))
    file_size = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("ThreadMessage", back_populates="attachments")


class EmailTemplate(Base):
    """Modèle d'email personnalisable, avec variables dynamiques."""

    __tablename__ = "comm_email_templates"

    id = Column(Integer, primary_key=True)
    key = Column(String(80), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    subject = Column(String(255), nullable=False)
    body_html = Column(Text, nullable=False)
    body_text = Column(Text)
    variables = Column(JSON, default=list)
    is_system = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    updated_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class NotificationPreference(Base):
    """Centre de préférences : canaux, fréquence, désabonnement."""

    __tablename__ = "comm_preferences"
    __table_args__ = (
        UniqueConstraint(
            "contact_type", "contact_key", "notification_type", name="uq_comm_pref_contact_type"
        ),
    )

    id = Column(Integer, primary_key=True)
    contact_type = Column(String(20), nullable=False)  # tenant | owner | prospect | agent
    contact_id = Column(Integer)
    contact_key = Column(String(255), nullable=False, index=True)
    email = Column(String(255), index=True)
    phone = Column(String(30))
    notification_type = Column(String(50), nullable=False, index=True)
    channels = Column(JSON, default=list)  # email, sms, push, in_app, postal
    frequency = Column(String(20), default="immediate", nullable=False)
    # immediate | daily_digest | weekly | never
    unsubscribed = Column(Boolean, default=False, nullable=False)
    unsubscribe_token = Column(String(64), unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class OutboundMessage(Base):
    """Historique unifié de toutes les communications sortantes."""

    __tablename__ = "comm_outbound"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    channel = Column(String(20), nullable=False, index=True)
    notification_type = Column(String(50), nullable=False, index=True)
    recipient_type = Column(String(20))
    recipient_id = Column(Integer, index=True)
    recipient_email = Column(String(255), index=True)
    recipient_phone = Column(String(30))
    recipient_name = Column(String(255))
    property_id = Column(Integer, index=True)
    lease_id = Column(Integer, index=True)
    tenant_id = Column(Integer, index=True)
    owner_id = Column(Integer, index=True)
    deal_id = Column(Integer, index=True)
    conversation_id = Column(Integer, index=True)
    related_entity_type = Column(String(50), index=True)
    related_entity_id = Column(Integer, index=True)
    subject = Column(String(255))
    body = Column(Text)
    template_key = Column(String(80))
    variables = Column(JSON, default=dict)
    status = Column(String(20), default="queued", nullable=False, index=True)
    # queued | sent | delivered | opened | failed | cancelled | skipped
    skip_reason = Column(String(255))
    provider = Column(String(50))
    provider_message_id = Column(String(255))
    tracking_token = Column(String(64), unique=True, index=True)
    unsubscribe_token = Column(String(64), index=True)
    opened_at = Column(DateTime(timezone=True))
    open_count = Column(Integer, default=0, nullable=False)
    sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class AutomationScenario(Base):
    """Scénario automatisé personnalisable (règles + canaux + modèle)."""

    __tablename__ = "comm_scenarios"

    id = Column(Integer, primary_key=True)
    key = Column(String(80), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    trigger_type = Column(String(80), nullable=False, index=True)
    template_key = Column(String(80))
    channels = Column(JSON, default=list)
    offset_days = Column(Integer, default=0)
    rules = Column(JSON, default=dict)
    is_enabled = Column(Boolean, default=True, nullable=False)
    is_system = Column(Boolean, default=True, nullable=False)
    last_run_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    runs = relationship("AutomationRun", back_populates="scenario", cascade="all, delete-orphan")


class AutomationRun(Base):
    __tablename__ = "comm_scenario_runs"

    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("comm_scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(20), default="ok")
    processed_count = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    skipped_count = Column(Integer, default=0)
    details = Column(JSON, default=list)
    ran_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    scenario = relationship("AutomationScenario", back_populates="runs")


class InAppNotification(Base):
    __tablename__ = "comm_in_app"

    id = Column(Integer, primary_key=True, index=True)
    recipient_type = Column(String(20), default="agent")
    recipient_key = Column(String(255), index=True)
    recipient_id = Column(Integer, index=True)
    notification_type = Column(String(50), default="info")
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    related_type = Column(String(50))
    related_id = Column(Integer)
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    read_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class PostalShipment(Base):
    """Envoi postal journalisé, prêt à être branché sur un prestataire."""

    __tablename__ = "comm_postal"

    id = Column(Integer, primary_key=True)
    outbound_id = Column(Integer, ForeignKey("comm_outbound.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(50), default="service_courrier")
    recipient_name = Column(String(255))
    address = Column(String(500))
    postal_code = Column(String(10))
    city = Column(String(100))
    country = Column(String(100), default="France")
    tracking_number = Column(String(80))
    status = Column(String(20), default="queued")
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
