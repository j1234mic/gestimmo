"""Modèles du module 8 : CRM et gestion commerciale.

Couvre la gestion des prospects (acheteur / locataire, source d'acquisition,
critères de recherche, budget, score de qualité explicable), le pipeline
commercial configurable avec vue Kanban, la gestion des visites (créneaux de
disponibilité, confirmation, rappels, compte-rendu, retour du visiteur,
agenda jour/semaine/mois), le matching automatique bien ↔ prospect, la
diffusion multi-portails des annonces avec statistiques, le suivi des
transactions de vente (offre, compromis, conditions suspensives, notaire,
acte authentique, commission) et les notifications commerciales.
"""

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


# ---------------------------------------------------------------------------
# Enums métier
# ---------------------------------------------------------------------------
class ProspectType(str, enum.Enum):
    BUYER = "acheteur"          # Recherche à l'achat
    TENANT = "locataire"        # Recherche en location
    BUYER_TENANT = "acheteur_locataire"  # Les deux selon l'opportunité


class ProspectSource(str, enum.Enum):
    WEBSITE = "site_web"
    PORTAL = "portail"
    AGENCY = "agence"
    REFERRAL = "parrainage"
    WALK_IN = "passage"
    PHONE = "telephone"
    SOCIAL = "reseaux_sociaux"
    OTHER = "autre"


class ProspectStatus(str, enum.Enum):
    ACTIVE = "actif"
    CONVERTED = "converti"
    DORMANT = "dormant"
    LOST = "perdu"


class DealStatus(str, enum.Enum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"


class VisitStatus(str, enum.Enum):
    SCHEDULED = "planifiee"
    CONFIRMED = "confirmee"
    COMPLETED = "effectuee"
    CANCELLED = "annulee"
    NO_SHOW = "absent"


class InterestLevel(str, enum.Enum):
    VERY_HIGH = "tres_fort"
    HIGH = "fort"
    MEDIUM = "moyen"
    LOW = "faible"
    NONE = "nul"


class Portal(str, enum.Enum):
    SELOGER = "seloger"
    LEBONCOIN = "leboncoin"
    LOGIC_IMMO = "logic_immo"
    BIENICI = "bienici"
    PAP = "pap"
    AGENCY_WEBSITE = "site_agence"


class PublicationStatus(str, enum.Enum):
    PENDING = "en_attente"
    PUBLISHED = "publiee"
    PAUSED = "en_pause"
    REJECTED = "rejetee"
    ERROR = "erreur"
    REMOVED = "retiree"


class ListingStatus(str, enum.Enum):
    DRAFT = "brouillon"
    PUBLISHED = "publiee"
    PAUSED = "en_pause"
    WITHDRAWN = "retiree"


class OfferStatus(str, enum.Enum):
    PENDING = "en_attente"
    ACCEPTED = "acceptee"
    REFUSED = "refusee"
    WITHDRAWN = "retiree"
    EXPIRED = "expiree"


class TransactionStage(str, enum.Enum):
    OFFER = "offre"
    COMPROMIS = "compromis"
    SUSPENSIVE = "conditions_suspensives"
    ACTE = "acte_authentique"
    CLOSED = "signee"
    CANCELLED = "annulee"


class ConditionStatus(str, enum.Enum):
    PENDING = "en_attente"
    SATISFIED = "satisfaite"
    WAIVED = "levee"
    FAILED = "echouee"


class ConditionType(str, enum.Enum):
    FINANCING = "financement"
    LOAN = "pret"
    DIAGNOSTIC = "diagnostic"
    PRE_EMPTION = "preemption"
    COOLING_OFF = "retractation"
    SALE_ANOTHER = "vente_autre_biens"
    OTHER = "autre"


# ---------------------------------------------------------------------------
# Prospects
# ---------------------------------------------------------------------------
class Prospect(Base):
    __tablename__ = "crm_prospects"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), index=True)
    phone = Column(String(30))
    mobile = Column(String(30))

    prospect_type = Column(Enum(ProspectType), default=ProspectType.TENANT, nullable=False, index=True)
    source = Column(Enum(ProspectSource), default=ProspectSource.WEBSITE, nullable=False, index=True)
    status = Column(Enum(ProspectStatus), default=ProspectStatus.ACTIVE, nullable=False, index=True)

    # Budget
    budget_min = Column(Float)
    budget_max = Column(Float)

    # Critères de recherche (libres, documentés dans le schéma)
    # {property_types, cities, postal_codes, min_surface, max_surface,
    #  min_rooms, min_bedrooms, min_bathrooms, ground_floor_ok, elevator_required,
    #  equipment: [...], exterior: [...], max_construction_year, other: [...]}
    search_criteria = Column(JSON, default=dict)

    # Score de qualité (0-100), recalculé et expliqué par le service
    quality_score = Column(Integer, default=0)
    score_detail = Column(JSON, default=dict)

    # Affectation et suivi
    assigned_agent = Column(String(255))          # email de l'agent référent
    notes = Column(Text)
    last_contact_at = Column(DateTime(timezone=True))
    converted_at = Column(DateTime(timezone=True))
    lost_reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    deals = relationship("PipelineDeal", back_populates="prospect", cascade="all, delete-orphan")
    visits = relationship("Visit", back_populates="prospect", cascade="all, delete-orphan")
    matches = relationship("MatchAlert", back_populates="prospect", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Pipeline commercial
# ---------------------------------------------------------------------------
class PipelineStage(Base):
    """Étape configurable du pipeline commercial."""
    __tablename__ = "crm_pipeline_stages"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    display_order = Column(Integer, nullable=False, default=0)
    probability = Column(Float, default=0.0, nullable=False)  # Probabilité de conversion (0-1)
    color = Column(String(20))
    is_won = Column(Boolean, default=False, nullable=False)   # Étape de signature
    is_lost = Column(Boolean, default=False, nullable=False)  # Étape « perdu »
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PipelineDeal(Base):
    """Opportunité commerciale : un prospect (et optionnellement un bien)
    progressant dans le pipeline."""
    __tablename__ = "crm_deals"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    prospect_id = Column(Integer, ForeignKey("crm_prospects.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    stage_id = Column(Integer, ForeignKey("crm_pipeline_stages.id", ondelete="RESTRICT"), nullable=False, index=True)

    deal_type = Column(String(30), default="location")  # location | vente
    status = Column(Enum(DealStatus), default=DealStatus.OPEN, nullable=False, index=True)

    estimated_value = Column(Float, default=0)    # Valeur estimée du dossier
    expected_commission = Column(Float, default=0)
    probability = Column(Float)                   # Par défaut celle de l'étape
    expected_close_date = Column(Date)
    actual_close_date = Column(Date)
    lost_reason = Column(String(255))
    assigned_agent = Column(String(255), index=True)
    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    closed_at = Column(DateTime(timezone=True))

    prospect = relationship("Prospect", back_populates="deals")
    property = relationship("Property")
    stage = relationship("PipelineStage")
    stage_history = relationship("DealStageHistory", back_populates="deal", cascade="all, delete-orphan")


class DealStageHistory(Base):
    __tablename__ = "crm_deal_stage_history"

    id = Column(Integer, primary_key=True, index=True)
    deal_id = Column(Integer, ForeignKey("crm_deals.id", ondelete="CASCADE"), nullable=False, index=True)
    from_stage_id = Column(Integer, ForeignKey("crm_pipeline_stages.id", ondelete="SET NULL"), nullable=True)
    to_stage_id = Column(Integer, ForeignKey("crm_pipeline_stages.id", ondelete="SET NULL"), nullable=False)
    comment = Column(String(500))
    changed_by = Column(String(255))
    changed_at = Column(DateTime(timezone=True), server_default=func.now())

    deal = relationship("PipelineDeal", back_populates="stage_history")


# ---------------------------------------------------------------------------
# Gestion des visites
# ---------------------------------------------------------------------------
class PropertyAvailability(Base):
    """Créneau de disponibilité d'un bien pour les visites."""
    __tablename__ = "crm_property_availability"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    available_date = Column(Date, nullable=False, index=True)
    start_time = Column(String(5), nullable=False)  # HH:MM
    end_time = Column(String(5), nullable=False)    # HH:MM
    is_booked = Column(Boolean, default=False, nullable=False)
    visit_id = Column(Integer, ForeignKey("crm_visits.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Visit(Base):
    __tablename__ = "crm_visits"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    prospect_id = Column(Integer, ForeignKey("crm_prospects.id", ondelete="CASCADE"), nullable=False, index=True)
    deal_id = Column(Integer, ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True, index=True)

    scheduled_date = Column(Date, nullable=False, index=True)
    start_time = Column(String(5), nullable=False)   # HH:MM
    end_time = Column(String(5), nullable=False)     # HH:MM
    status = Column(Enum(VisitStatus), default=VisitStatus.SCHEDULED, nullable=False, index=True)
    auto_confirm = Column(Boolean, default=True, nullable=False)
    confirmed_at = Column(DateTime(timezone=True))
    cancelled_reason = Column(String(255))

    assigned_agent = Column(String(255))
    availability_id = Column(Integer, ForeignKey("crm_property_availability.id", ondelete="SET NULL"), nullable=True)
    reminder_email_sent_at = Column(DateTime(timezone=True))
    reminder_sms_sent_at = Column(DateTime(timezone=True))

    completed_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    property = relationship("Property")
    prospect = relationship("Prospect", back_populates="visits")
    deal = relationship("PipelineDeal")
    report = relationship("VisitReport", back_populates="visit", uselist=False, cascade="all, delete-orphan")
    reminders = relationship("VisitReminder", back_populates="visit", cascade="all, delete-orphan")


class VisitReport(Base):
    """Compte-rendu de visite (côté agent) et retour du visiteur."""
    __tablename__ = "crm_visit_reports"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("crm_visits.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    # Compte-rendu agent
    overall_rating = Column(Integer)          # 1 à 5
    interest_level = Column(Enum(InterestLevel))
    strengths = Column(Text)
    weaknesses = Column(Text)
    comments = Column(Text)
    next_step = Column(String(255))
    follow_up_date = Column(Date)

    # Retour du visiteur
    visitor_rating = Column(Integer)          # 1 à 5
    visitor_comments = Column(Text)
    visitor_would_apply = Column(Boolean)
    visitor_feedback_at = Column(DateTime(timezone=True))

    reported_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    visit = relationship("Visit", back_populates="report")


class VisitReminder(Base):
    """Historique des rappels envoyés (email / SMS)."""
    __tablename__ = "crm_visit_reminders"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("crm_visits.id", ondelete="CASCADE"), nullable=False, index=True)
    channel = Column(String(20), nullable=False)  # email | sms
    recipient = Column(String(255))
    sent_at = Column(DateTime(timezone=True), server_default=func.now())

    visit = relationship("Visit", back_populates="reminders")


# ---------------------------------------------------------------------------
# Matching automatique prospect ↔ bien
# ---------------------------------------------------------------------------
class MatchAlert(Base):
    __tablename__ = "crm_match_alerts"

    id = Column(Integer, primary_key=True, index=True)
    prospect_id = Column(Integer, ForeignKey("crm_prospects.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    score = Column(Integer, nullable=False)      # 0-100
    detail = Column(JSON, default=dict)          # Détail explicable du score
    status = Column(String(20), default="nouvelle", index=True)  # nouvelle, notifiee, ecartee, convertie
    notified_at = Column(DateTime(timezone=True))
    dismissed_reason = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    prospect = relationship("Prospect", back_populates="matches")
    property = relationship("Property")

    __table_args__ = (
        UniqueConstraint("prospect_id", "property_id", name="uq_match_prospect_property"),
    )


# ---------------------------------------------------------------------------
# Diffusion des annonces (portails)
# ---------------------------------------------------------------------------
class ListingTemplate(Base):
    """Modèle d'annonce réutilisable."""
    __tablename__ = "crm_listing_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    property_type = Column(String(30))             # apartment, house… (null = tous)
    language = Column(String(10), default="fr")
    title_template = Column(String(500))
    description_template = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Listing(Base):
    """Annonce d'un bien, diffusée sur un ou plusieurs portails."""
    __tablename__ = "crm_listings"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id = Column(Integer, ForeignKey("crm_listing_templates.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    price = Column(Float)                          # Loyer ou prix de vente selon le mandat
    listing_type = Column(String(20), default="location")  # location | vente
    status = Column(Enum(ListingStatus), default=ListingStatus.DRAFT, nullable=False, index=True)
    published_at = Column(DateTime(timezone=True))
    withdrawn_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    property = relationship("Property")
    template = relationship("ListingTemplate")
    publications = relationship("PortalPublication", back_populates="listing", cascade="all, delete-orphan")
    daily_stats = relationship("ListingDailyStat", back_populates="listing", cascade="all, delete-orphan")


class PortalPublication(Base):
    __tablename__ = "crm_portal_publications"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("crm_listings.id", ondelete="CASCADE"), nullable=False, index=True)
    portal = Column(Enum(Portal), nullable=False, index=True)
    status = Column(Enum(PublicationStatus), default=PublicationStatus.PENDING, nullable=False, index=True)
    external_reference = Column(String(100))
    message = Column(String(500))
    published_at = Column(DateTime(timezone=True))
    removed_at = Column(DateTime(timezone=True))
    last_sync_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    listing = relationship("Listing", back_populates="publications")


class ListingDailyStat(Base):
    """Statistiques journalières d'une annonce (globales ou par portail)."""
    __tablename__ = "crm_listing_daily_stats"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("crm_listings.id", ondelete="CASCADE"), nullable=False, index=True)
    portal = Column(Enum(Portal), nullable=True)   # null = cumul toutes destinations
    stat_date = Column(Date, nullable=False, index=True)
    views = Column(Integer, default=0)
    contacts = Column(Integer, default=0)
    favorites = Column(Integer, default=0)
    leads = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    listing = relationship("Listing", back_populates="daily_stats")


# ---------------------------------------------------------------------------
# Transactions (vente)
# ---------------------------------------------------------------------------
class PurchaseOffer(Base):
    __tablename__ = "crm_purchase_offers"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    prospect_id = Column(Integer, ForeignKey("crm_prospects.id", ondelete="SET NULL"), nullable=True, index=True)
    deal_id = Column(Integer, ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Float, nullable=False)
    offer_date = Column(Date, nullable=False)
    validity_date = Column(Date)
    status = Column(Enum(OfferStatus), default=OfferStatus.PENDING, nullable=False, index=True)
    financing_ok = Column(Boolean, default=True)   # Accord de financement joint
    conditions = Column(JSON, default=list)
    response_note = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    property = relationship("Property")
    prospect = relationship("Prospect")


class SaleTransaction(Base):
    """Dossier de vente : offre → compromis → conditions suspensives → acte."""
    __tablename__ = "crm_sale_transactions"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    offer_id = Column(Integer, ForeignKey("crm_purchase_offers.id", ondelete="SET NULL"), nullable=True)
    prospect_id = Column(Integer, ForeignKey("crm_prospects.id", ondelete="SET NULL"), nullable=True, index=True)
    deal_id = Column(Integer, ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True)

    buyer_name = Column(String(255))
    seller_owner_id = Column(Integer, ForeignKey("owners.id", ondelete="SET NULL"), nullable=True)

    stage = Column(Enum(TransactionStage), default=TransactionStage.OFFER, nullable=False, index=True)
    sale_price = Column(Float, nullable=False)

    # Compromis de vente
    compromis_date = Column(Date)
    compromis_signed_at = Column(Date)
    notary_name = Column(String(255))
    notary_email = Column(String(255))
    notary_phone = Column(String(30))

    # Acte authentique
    acte_date = Column(Date)                       # Date prévue de l'acte
    acte_signed_at = Column(Date)                  # Date réelle de signature
    effective_sale_date = Column(Date)

    # Commission agence
    commission_rate = Column(Float, default=0)     # % du prix de vente
    commission_fixed = Column(Float, default=0)    # Montant fixe éventuel
    commission_amount = Column(Float, default=0)   # Calculé à la signature
    vat_rate = Column(Float, default=20)
    commission_total_ttc = Column(Float, default=0)

    cancelled_reason = Column(String(255))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    closed_at = Column(DateTime(timezone=True))

    property = relationship("Property")
    prospect = relationship("Prospect")
    conditions = relationship("SuspensiveCondition", back_populates="transaction", cascade="all, delete-orphan")
    events = relationship("TransactionEvent", back_populates="transaction", cascade="all, delete-orphan")


class SuspensiveCondition(Base):
    __tablename__ = "crm_suspensive_conditions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("crm_sale_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(255), nullable=False)
    condition_type = Column(Enum(ConditionType), default=ConditionType.OTHER, nullable=False)
    deadline = Column(Date)
    status = Column(Enum(ConditionStatus), default=ConditionStatus.PENDING, nullable=False, index=True)
    satisfied_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    transaction = relationship("SaleTransaction", back_populates="conditions")


class TransactionEvent(Base):
    """Journal de suivi (notaire, signatures, relances…)."""
    __tablename__ = "crm_transaction_events"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("crm_sale_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # notaire, signature, condition, autre
    label = Column(String(255), nullable=False)
    event_date = Column(Date)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    transaction = relationship("SaleTransaction", back_populates="events")


# ---------------------------------------------------------------------------
# Notifications commerciales internes
# ---------------------------------------------------------------------------
class CrmNotification(Base):
    __tablename__ = "crm_notifications"

    id = Column(Integer, primary_key=True, index=True)
    recipient = Column(String(255), index=True)     # Email de l'agent (null = toute l'équipe)
    type = Column(String(50), default="info")       # matching, visite, deal, annonce, transaction
    title = Column(String(255), nullable=False)
    message = Column(Text)
    link = Column(String(500))
    is_read = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
