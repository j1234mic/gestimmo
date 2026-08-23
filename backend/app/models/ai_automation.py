"""Module 16 — intelligence artificielle et automatisation.

Les prédictions sont historisées avec leur méthode, leur niveau de confiance et
les facteurs explicatifs. Aucun résultat n'est présenté comme une décision
automatique : les scores sont des aides à la décision révisables par un humain.
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
from sqlalchemy.sql import func

from app.database import Base


class AIModelSnapshot(Base):
    """Version reproductible d'un estimateur entraîné sur les données locales."""

    __tablename__ = "ai_model_snapshots"

    id = Column(Integer, primary_key=True)
    model_type = Column(String(50), nullable=False, index=True)
    version = Column(String(50), nullable=False)
    algorithm = Column(String(80), nullable=False)
    sample_count = Column(Integer, default=0, nullable=False)
    features = Column(JSON, default=list)
    parameters = Column(JSON, default=dict)
    metrics = Column(JSON, default=dict)
    training_scope = Column(JSON, default=dict)
    trained_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    is_active = Column(Boolean, default=True, nullable=False)


class AIPrediction(Base):
    __tablename__ = "ai_predictions"

    id = Column(Integer, primary_key=True)
    prediction_type = Column(String(50), nullable=False, index=True)
    entity_type = Column(String(30), nullable=False, index=True)
    entity_id = Column(Integer, index=True)
    model_id = Column(Integer, ForeignKey("ai_model_snapshots.id", ondelete="SET NULL"), index=True)
    input_data = Column(JSON, default=dict)
    result = Column(JSON, default=dict)
    confidence = Column(Float, default=0, nullable=False)
    risk_level = Column(String(20), index=True)
    explanation = Column(JSON, default=dict)
    requested_by = Column(String(255))
    reviewed_by = Column(String(255))
    reviewed_at = Column(DateTime(timezone=True))
    review_decision = Column(String(30))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ChatSession(Base):
    __tablename__ = "ai_chat_sessions"

    id = Column(Integer, primary_key=True)
    public_id = Column(String(64), unique=True, nullable=False, index=True)
    actor_type = Column(String(20), nullable=False, index=True)  # tenant | manager
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), index=True)
    user_id = Column(Integer, index=True)
    locale = Column(String(10), default="fr", nullable=False)
    status = Column(String(20), default="open", nullable=False, index=True)
    context = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_activity_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    closed_at = Column(DateTime(timezone=True))


class ChatMessage(Base):
    __tablename__ = "ai_chat_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("ai_chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # user | assistant | system
    content = Column(Text, nullable=False)
    intent = Column(String(80), index=True)
    confidence = Column(Float)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class ChatKnowledge(Base):
    """Mémoire conversationnelle isolée par acteur.

    Ce n'est pas un entraînement des poids d'un modèle : les questions et les
    réponses validées par la conversation sont réutilisées comme contexte lors
    du prochain appel au fournisseur IA. Cette séparation évite qu'une donnée
    d'un locataire soit proposée à un autre utilisateur.
    """

    __tablename__ = "ai_chat_knowledge"

    id = Column(Integer, primary_key=True)
    actor_type = Column(String(20), nullable=False, index=True)
    actor_id = Column(Integer, nullable=False, index=True)
    question = Column(Text, nullable=False)
    normalized_question = Column(String(1000), nullable=False, index=True)
    answer = Column(Text, nullable=False)
    usage_count = Column(Integer, default=1, nullable=False)
    last_used_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class AssistantAppointment(Base):
    __tablename__ = "ai_assistant_appointments"

    id = Column(Integer, primary_key=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    session_id = Column(Integer, ForeignKey("ai_chat_sessions.id", ondelete="SET NULL"), index=True)
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes = Column(Integer, default=30, nullable=False)
    purpose = Column(String(255), nullable=False)
    status = Column(String(20), default="requested", nullable=False, index=True)
    contact_email = Column(String(255))
    contact_phone = Column(String(30))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AutomationWorkflow(Base):
    """Règle événementielle composée de conditions et d'actions autorisées."""

    __tablename__ = "automation_workflows"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    event_type = Column(String(100), nullable=False, index=True)
    conditions = Column(JSON, default=list)
    actions = Column(JSON, default=list)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    priority = Column(Integer, default=100, nullable=False)
    stop_on_error = Column(Boolean, default=True, nullable=False)
    version = Column(Integer, default=1, nullable=False)
    execution_count = Column(Integer, default=0, nullable=False)
    last_run_at = Column(DateTime(timezone=True))
    created_by = Column(String(255))
    updated_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class WorkflowExecution(Base):
    __tablename__ = "automation_runs"
    __table_args__ = (
        UniqueConstraint("workflow_id", "idempotency_key", name="uq_automation_run_idempotency"),
    )

    id = Column(Integer, primary_key=True)
    workflow_id = Column(Integer, ForeignKey("automation_workflows.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    idempotency_key = Column(String(160), nullable=False)
    event_payload = Column(JSON, default=dict)
    status = Column(String(30), default="running", nullable=False, index=True)
    matched = Column(Boolean, default=False, nullable=False)
    action_results = Column(JSON, default=list)
    error = Column(Text)
    started_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True))


class IntelligentOCRJob(Base):
    __tablename__ = "ai_ocr_jobs"

    id = Column(Integer, primary_key=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("ged_documents.id", ondelete="SET NULL"), index=True)
    expected_type = Column(String(50), index=True)
    detected_type = Column(String(50), index=True)
    status = Column(String(30), default="processing", nullable=False, index=True)
    engine = Column(String(50))
    confidence = Column(Float, default=0)
    extracted_data = Column(JSON, default=dict)
    checks = Column(JSON, default=dict)
    requires_manual_review = Column(Boolean, default=True, nullable=False)
    error = Column(Text)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at = Column(DateTime(timezone=True))


class MarketObservation(Base):
    """Annonce comparable ou observation de veille concurrentielle."""

    __tablename__ = "market_observations"

    id = Column(Integer, primary_key=True)
    source = Column(String(100), nullable=False, index=True)
    external_reference = Column(String(255), index=True)
    competitor = Column(String(255), index=True)
    listing_type = Column(String(20), nullable=False, index=True)  # rent | sale
    property_type = Column(String(50), nullable=False, index=True)
    city = Column(String(100), nullable=False, index=True)
    postal_code = Column(String(10), index=True)
    area = Column(Float, nullable=False)
    rooms = Column(Integer)
    price = Column(Float, nullable=False)
    charges = Column(Float, default=0)
    url = Column(String(1000))
    attributes = Column(JSON, default=dict)
    observed_on = Column(Date, nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MarketPriceIndex(Base):
    __tablename__ = "market_price_indices"
    __table_args__ = (
        UniqueConstraint("code", "geography", "period", name="uq_market_index_period"),
    )

    id = Column(Integer, primary_key=True)
    code = Column(String(50), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    geography = Column(String(120), nullable=False, index=True)
    period = Column(String(20), nullable=False, index=True)
    value = Column(Float, nullable=False)
    variation_percent = Column(Float)
    source = Column(String(255), nullable=False)
    source_url = Column(String(1000))
    published_on = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
