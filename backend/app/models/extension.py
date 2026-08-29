"""Modèles des modules complémentaires de gestion immobilière (18 à 31).

Ces tables regroupent les domaines décrits dans
``COMPLEMENTS-GESTION-IMMOBILIERE.md`` : courte durée, contentieux, fiscalité,
financement, services résidentiels, clés/accès, compteurs/énergie,
développement/VEFA, investisseurs/fonds, rénovation énergétique, satisfaction,
tâches internes et sourcing.
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
# Module 18 — Location courte durée & saisonnière
# ---------------------------------------------------------------------------
class ShortTermPlatform(str, enum.Enum):
    AIRBNB = "airbnb"
    BOOKING = "booking"
    ABRITEL = "abritel"
    VRBO = "vrbo"
    DIRECT = "direct"
    AUTRE = "autre"


class BookingStatus(str, enum.Enum):
    PENDING = "en_attente"
    CONFIRMED = "confirme"
    CHECKED_IN = "arrive"
    CHECKED_OUT = "depart"
    CANCELLED = "annule"
    NO_SHOW = "no_show"


class ShortTermListing(Base):
    __tablename__ = "short_term_listings"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(Enum(ShortTermPlatform), default=ShortTermPlatform.DIRECT, nullable=False, index=True)
    external_id = Column(String(120))
    name = Column(String(255))
    nightly_rate = Column(Float, default=0)
    min_nights = Column(Integer, default=1)
    max_guests = Column(Integer, default=2)
    cleaning_fee = Column(Float, default=0)
    cancellation_policy = Column(String(80))
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    bookings = relationship("ShortTermBooking", back_populates="listing", cascade="all, delete-orphan")
    price_rules = relationship("ShortTermPriceRule", back_populates="listing", cascade="all, delete-orphan")


class ShortTermBooking(Base):
    __tablename__ = "short_term_bookings"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("short_term_listings.id", ondelete="CASCADE"), nullable=False, index=True)
    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
    guest_name = Column(String(255), nullable=False)
    guest_email = Column(String(255))
    guests = Column(Integer, default=1)
    amount = Column(Float, default=0)
    cleaning_fee = Column(Float, default=0)
    tax_amount = Column(Float, default=0)
    status = Column(Enum(BookingStatus), default=BookingStatus.PENDING, nullable=False, index=True)
    source = Column(String(80))
    external_reservation_id = Column(String(120))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    listing = relationship("ShortTermListing", back_populates="bookings")


class ShortTermPriceRule(Base):
    __tablename__ = "short_term_price_rules"

    id = Column(Integer, primary_key=True, index=True)
    listing_id = Column(Integer, ForeignKey("short_term_listings.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(255))
    date_from = Column(Date, nullable=False, index=True)
    date_to = Column(Date, nullable=False, index=True)
    rate_multiplier = Column(Float, default=1.0)
    weekend_multiplier = Column(Float, default=1.0)
    min_nights = Column(Integer)
    active = Column(Boolean, default=True)

    listing = relationship("ShortTermListing", back_populates="price_rules")


# ---------------------------------------------------------------------------
# Module 19 — Contentieux & conformité juridique
# ---------------------------------------------------------------------------
class LegalCaseType(str, enum.Enum):
    UNPAID = "impaye"
    TROUBLE = "troubles"
    LEASE = "bail"
    CONDO = "copropriete"
    PROVIDER = "prestataire"
    INSURANCE = "assurance"
    OTHER = "autre"


class LegalFileStatus(str, enum.Enum):
    OPEN = "ouvert"
    MEDIATION = "mediation"
    PENDING = "en_attente"
    WON = "gagne"
    LOST = "perdu"
    CLOSED = "cloture"
    ARCHIVED = "archive"


class LegalCaseFile(Base):
    __tablename__ = "legal_cases"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    case_type = Column(Enum(LegalCaseType), default=LegalCaseType.OTHER, nullable=False, index=True)
    status = Column(Enum(LegalFileStatus), default=LegalFileStatus.OPEN, nullable=False, index=True)
    subject = Column(String(255), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="SET NULL"), index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), index=True)
    provider_id = Column(Integer, ForeignKey("service_providers.id", ondelete="SET NULL"), index=True)
    amount_in_dispute = Column(Float, default=0)
    court = Column(String(255))
    case_number = Column(String(120))
    opened_at = Column(Date, default=func.now(), index=True)
    closed_at = Column(Date)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    actions = relationship("LegalAction", back_populates="case", cascade="all, delete-orphan")


class LegalAction(Base):
    __tablename__ = "legal_actions"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("legal_cases.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type = Column(String(80), nullable=False)
    action_date = Column(Date, nullable=False, index=True)
    description = Column(Text)
    outcome = Column(Text)
    created_by = Column(String(255))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    case = relationship("LegalCaseFile", back_populates="actions")


# ---------------------------------------------------------------------------
# Module 20 — Fiscalité & déclarations immobilières
# ---------------------------------------------------------------------------
class FiscalDeclarationStatus(str, enum.Enum):
    DRAFT = "brouillon"
    READY = "pret"
    SUBMITTED = "depose"
    VALIDATED = "valide"
    ARCHIVED = "archive"


class FiscalYearRecord(Base):
    __tablename__ = "fiscal_year_records"
    __table_args__ = (UniqueConstraint("owner_id", "property_id", "fiscal_year", name="uq_fiscal_owner_prop_year"),)

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    fiscal_year = Column(Integer, nullable=False, index=True)
    regime = Column(String(50))
    rental_income = Column(Float, default=0)
    deductible_charges = Column(Float, default=0)
    amortization = Column(Float, default=0)
    result = Column(Float, default=0)
    tax_amount = Column(Float, default=0)
    status = Column(Enum(FiscalDeclarationStatus), default=FiscalDeclarationStatus.DRAFT, nullable=False)
    generated_pdf_url = Column(String(500))
    submitted_at = Column(Date)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Module 21 — Financement & gestion des prêts
# ---------------------------------------------------------------------------
class LoanType(str, enum.Enum):
    CLASSIC = "classique"
    RELAY = "relais"
    CONSTRUCTION = "construction"
    FIXED = "taux_fixe"
    VARIABLE = "taux_variable"
    OTHER = "autre"


class LoanStatus(str, enum.Enum):
    DRAFT = "brouillon"
    ACTIVE = "en_cours"
    MATURED = "amorti"
    REFINANCED = "refinance"
    CANCELLED = "annule"


class PropertyLoan(Base):
    __tablename__ = "property_loans"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    lender = Column(String(255), nullable=False)
    loan_type = Column(Enum(LoanType), default=LoanType.CLASSIC, nullable=False)
    principal = Column(Float, nullable=False)
    interest_rate = Column(Float, nullable=False)
    duration_months = Column(Integer, nullable=False)
    start_date = Column(Date, nullable=False)
    monthly_payment = Column(Float, default=0)
    insurance_monthly = Column(Float, default=0)
    status = Column(Enum(LoanStatus), default=LoanStatus.DRAFT, nullable=False, index=True)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    payments = relationship("LoanPayment", back_populates="loan", cascade="all, delete-orphan")


class LoanPayment(Base):
    __tablename__ = "loan_payments"

    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("property_loans.id", ondelete="CASCADE"), nullable=False, index=True)
    payment_number = Column(Integer, nullable=False, index=True)
    due_date = Column(Date, nullable=False, index=True)
    principal_part = Column(Float, default=0)
    interest_part = Column(Float, default=0)
    total_part = Column(Float, default=0)
    insurance_part = Column(Float, default=0)
    status = Column(String(20), default="pending")
    paid_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    loan = relationship("PropertyLoan", back_populates="payments")


# ---------------------------------------------------------------------------
# Module 22 — Portail public / site vitrine de l'agence
# ---------------------------------------------------------------------------
class PublicPage(Base):
    __tablename__ = "public_pages"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(120), unique=True, nullable=False, index=True)
    content = Column(Text, default="")
    status = Column(String(20), default="draft", index=True)  # draft | published
    seo_title = Column(String(255))
    seo_description = Column(String(500))
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PublicAgent(Base):
    __tablename__ = "public_agents"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    role = Column(String(120))
    email = Column(String(255))
    phone = Column(String(50))
    photo_url = Column(String(500))
    bio = Column(Text)
    order = Column(Integer, default=0)
    active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PublicTestimonial(Base):
    __tablename__ = "public_testimonials"

    id = Column(Integer, primary_key=True, index=True)
    client_name = Column(String(255), nullable=False)
    client_role = Column(String(120))
    content = Column(Text, nullable=False)
    rating = Column(Integer, default=5)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    published = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PublicNewsPost(Base):
    __tablename__ = "public_news_posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    slug = Column(String(120), unique=True, nullable=False, index=True)
    excerpt = Column(String(500))
    content = Column(Text, default="")
    author = Column(String(255))
    cover_url = Column(String(500))
    status = Column(String(20), default="draft", index=True)  # draft | published
    published_at = Column(DateTime(timezone=True), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PublicLeadStatus(str, enum.Enum):
    NEW = "nouveau"
    CONTACTED = "contacte"
    PROCESSING = "en_cours"
    CONVERTED = "converti"
    ARCHIVED = "archive"


class PublicLead(Base):
    __tablename__ = "public_leads"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    tracking_token = Column(String(64), unique=True, nullable=False, index=True)
    request_type = Column(String(30), nullable=False, index=True)  # contact | visit | estimate | application
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=False)
    phone = Column(String(50))
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    message = Column(Text)
    status = Column(Enum(PublicLeadStatus), default=PublicLeadStatus.NEW, nullable=False, index=True)
    preferred_date = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


# ---------------------------------------------------------------------------
# Module 23 — Services résidentiels & conciergerie
# ---------------------------------------------------------------------------
class ServiceAgreementStatus(str, enum.Enum):
    DRAFT = "brouillon"
    ACTIVE = "actif"
    SUSPENDED = "suspendu"
    TERMINATED = "resilie"


class ServiceAgreement(Base):
    __tablename__ = "service_agreements"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), index=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="SET NULL"), index=True)
    service_type = Column(String(80), nullable=False, index=True)
    contract_label = Column(String(255))
    monthly_amount = Column(Float, default=0)
    billing_type = Column(String(40), default="monthly")
    start_date = Column(Date)
    end_date = Column(Date)
    status = Column(Enum(ServiceAgreementStatus), default=ServiceAgreementStatus.DRAFT, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    invoices = relationship("ServiceInvoice", back_populates="agreement", cascade="all, delete-orphan")


class ServiceInvoice(Base):
    __tablename__ = "service_invoices"

    id = Column(Integer, primary_key=True, index=True)
    agreement_id = Column(Integer, ForeignKey("service_agreements.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(String(7), nullable=False, index=True)
    amount = Column(Float, default=0)
    vat_amount = Column(Float, default=0)
    total = Column(Float, default=0)
    status = Column(String(20), default="pending")
    due_date = Column(Date)
    paid_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    agreement = relationship("ServiceAgreement", back_populates="invoices")


# ---------------------------------------------------------------------------
# Module 24 — Accès, clés & sûreté
# ---------------------------------------------------------------------------
class AccessKeyStatus(str, enum.Enum):
    AVAILABLE = "disponible"
    BORROWED = "prete"
    RETURNED = "rendu"
    LOST = "perdu"
    BLOCKED = "bloque"


class AccessKey(Base):
    __tablename__ = "access_keys"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(255), nullable=False)
    key_type = Column(String(50), default="cle")  # key | badge | code | remote
    serial = Column(String(120))
    location = Column(String(255))
    status = Column(Enum(AccessKeyStatus), default=AccessKeyStatus.AVAILABLE, nullable=False, index=True)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    operations = relationship("KeyOperation", back_populates="key", cascade="all, delete-orphan")


class KeyOperation(Base):
    __tablename__ = "key_operations"

    id = Column(Integer, primary_key=True, index=True)
    key_id = Column(Integer, ForeignKey("access_keys.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(30), nullable=False, index=True)  # issue | return | lost | replacement | block
    borrowed_by = Column(String(255))
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    returned_at = Column(DateTime(timezone=True))
    notes = Column(Text)

    key = relationship("AccessKey", back_populates="operations")


# ---------------------------------------------------------------------------
# Module 25 — Compteurs & consommation énergie
# ---------------------------------------------------------------------------
class UtilityMeterType(str, enum.Enum):
    WATER = "eau"
    ELECTRICITY = "electricite"
    GAS = "gaz"
    HEATING = "chauffage"
    OTHER = "autre"


class UtilityMeter(Base):
    __tablename__ = "utility_meters"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    meter_type = Column(Enum(UtilityMeterType), default=UtilityMeterType.OTHER, nullable=False, index=True)
    serial = Column(String(120))
    unit = Column(String(20), default="kWh")
    location = Column(String(255))
    initial_reading = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    readings = relationship("UtilityReading", back_populates="meter", cascade="all, delete-orphan")


class UtilityReading(Base):
    __tablename__ = "utility_readings"

    id = Column(Integer, primary_key=True, index=True)
    meter_id = Column(Integer, ForeignKey("utility_meters.id", ondelete="CASCADE"), nullable=False, index=True)
    reading_date = Column(Date, nullable=False, index=True)
    value = Column(Float, nullable=False)
    photo_url = Column(String(500))
    source = Column(String(80), default="manual")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    meter = relationship("UtilityMeter", back_populates="readings")


class UtilityBill(Base):
    __tablename__ = "utility_bills"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(String(7), nullable=False, index=True)
    utility_type = Column(Enum(UtilityMeterType), default=UtilityMeterType.OTHER, nullable=False, index=True)
    amount = Column(Float, default=0)
    consumption = Column(Float, default=0)
    unit_price = Column(Float, default=0)
    status = Column(String(20), default="pending")
    settled_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Module 26 — Développement & promotion immobilière (VEFA)
# ---------------------------------------------------------------------------
class DevelopmentProgramStatus(str, enum.Enum):
    PLANNING = "en_etude"
    PERMIT = "permis_en_cours"
    PERMIT_GRANTED = "permis_obtenu"
    UNDER_CONSTRUCTION = "en_construction"
    DELIVERED = "livre"
    SOLD_OUT = "commercialise"
    CANCELLED = "annule"


class DevelopmentProgram(Base):
    __tablename__ = "development_programs"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    program_type = Column(String(80), default="residential")
    address = Column(String(500))
    postal_code = Column(String(10))
    city = Column(String(100))
    surface = Column(Float)
    total_units = Column(Integer, default=0)
    expected_delivery = Column(Date)
    permit_number = Column(String(120))
    status = Column(Enum(DevelopmentProgramStatus), default=DevelopmentProgramStatus.PLANNING, nullable=False)
    developer = Column(String(255))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    units = relationship("DevelopmentUnit", back_populates="program", cascade="all, delete-orphan")


class DevelopmentUnit(Base):
    __tablename__ = "development_units"

    id = Column(Integer, primary_key=True, index=True)
    program_id = Column(Integer, ForeignKey("development_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(120), nullable=False)
    unit_type = Column(String(80), default="apartment")
    surface = Column(Float)
    price_ht = Column(Float)
    tva_rate = Column(Float, default=20)
    price_ttc = Column(Float)
    status = Column(String(30), default="available")
    floor = Column(Integer)
    notes = Column(Text)

    program = relationship("DevelopmentProgram", back_populates="units")
    reservations = relationship("VefaReservation", back_populates="unit", cascade="all, delete-orphan")


class VefaReservation(Base):
    __tablename__ = "vefa_reservations"

    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("development_units.id", ondelete="CASCADE"), nullable=False, index=True)
    buyer_name = Column(String(255), nullable=False)
    buyer_email = Column(String(255))
    deposit = Column(Float, default=0)
    reservation_date = Column(Date, nullable=False)
    status = Column(String(30), default="reserved")
    signed_at = Column(DateTime(timezone=True))
    notes = Column(Text)

    unit = relationship("DevelopmentUnit", back_populates="reservations")


# ---------------------------------------------------------------------------
# Module 27 — Investisseurs & gestion de fonds / SCPI
# ---------------------------------------------------------------------------
class InvestmentFund(Base):
    __tablename__ = "investment_funds"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    fund_type = Column(String(80), default="scpi")
    description = Column(Text)
    total_capital = Column(Float, default=0)
    nav = Column(Float, default=0)
    nav_date = Column(Date)
    status = Column(String(20), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    subscriptions = relationship("FundSubscription", back_populates="fund", cascade="all, delete-orphan")
    distributions = relationship("FundDistribution", back_populates="fund", cascade="all, delete-orphan")


class FundSubscription(Base):
    __tablename__ = "fund_subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    fund_id = Column(Integer, ForeignKey("investment_funds.id", ondelete="CASCADE"), nullable=False, index=True)
    investor_name = Column(String(255), nullable=False)
    investor_email = Column(String(255))
    amount = Column(Float, default=0)
    units = Column(Float, default=0)
    subscription_date = Column(Date, nullable=False)
    status = Column(String(20), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    fund = relationship("InvestmentFund", back_populates="subscriptions")


class FundDistribution(Base):
    __tablename__ = "fund_distributions"

    id = Column(Integer, primary_key=True, index=True)
    fund_id = Column(Integer, ForeignKey("investment_funds.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(String(20), nullable=False, index=True)
    amount_per_unit = Column(Float, default=0)
    total_amount = Column(Float, default=0)
    payment_date = Column(Date)
    status = Column(String(20), default="planned")
    notes = Column(Text)

    fund = relationship("InvestmentFund", back_populates="distributions")


# ---------------------------------------------------------------------------
# Module 28 — Performance énergétique & rénovation
# ---------------------------------------------------------------------------
class EnergyAudit(Base):
    __tablename__ = "energy_audits"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    audit_date = Column(Date, nullable=False, index=True)
    energy_class_before = Column(String(5))
    energy_class_after = Column(String(5))
    primary_energy = Column(Float)
    ghg = Column(Float)
    estimated_cost = Column(Float)
    advisor = Column(String(255))
    report_url = Column(String(500))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    projects = relationship("EnergyRenovationProject", back_populates="audit", cascade="all, delete-orphan")


class EnergyRenovationProject(Base):
    __tablename__ = "energy_renovation_projects"

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(Integer, ForeignKey("energy_audits.id", ondelete="CASCADE"), index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    budget = Column(Float, default=0)
    estimated_savings = Column(Float, default=0)
    status = Column(String(30), default="proposed")
    start_date = Column(Date)
    completion_date = Column(Date)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    audit = relationship("EnergyAudit", back_populates="projects")
    grants = relationship("EnergyGrant", back_populates="project", cascade="all, delete-orphan")


class EnergyGrant(Base):
    __tablename__ = "energy_grants"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("energy_renovation_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    program_name = Column(String(255), nullable=False)
    amount = Column(Float, default=0)
    application_date = Column(Date)
    status = Column(String(20), default="pending")
    granted_at = Column(Date)
    notes = Column(Text)

    project = relationship("EnergyRenovationProject", back_populates="grants")


# ---------------------------------------------------------------------------
# Module 29 — Qualité de service & satisfaction clients
# ---------------------------------------------------------------------------
class SatisfactionSurvey(Base):
    __tablename__ = "satisfaction_surveys"

    id = Column(Integer, primary_key=True, index=True)
    respondent_type = Column(String(30), nullable=False)  # owner | tenant | provider
    respondent_id = Column(Integer, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), index=True)
    nps_score = Column(Integer)
    csat = Column(Integer)
    comment = Column(Text)
    source = Column(String(80), default="app")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Module 30 — Tâches, plannings & workflow interne
# ---------------------------------------------------------------------------
class TaskPriority(str, enum.Enum):
    LOW = "faible"
    NORMAL = "normale"
    HIGH = "haute"
    URGENT = "urgente"


class TaskStatus(str, enum.Enum):
    TODO = "a_faire"
    IN_PROGRESS = "en_cours"
    WAITING = "en_attente"
    DONE = "terminee"
    CANCELLED = "annulee"


class Task(Base):
    __tablename__ = "internal_tasks"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(80), nullable=False, index=True)
    entity_id = Column(Integer, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    assignee_id = Column(Integer, index=True)
    priority = Column(Enum(TaskPriority), default=TaskPriority.NORMAL, nullable=False)
    status = Column(Enum(TaskStatus), default=TaskStatus.TODO, nullable=False, index=True)
    due_date = Column(DateTime(timezone=True), index=True)
    related_url = Column(String(500))
    created_by = Column(String(255))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    comments = relationship("TaskComment", back_populates="task", cascade="all, delete-orphan")


class TaskComment(Base):
    __tablename__ = "task_comments"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(Integer, ForeignKey("internal_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    author = Column(String(255))
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    task = relationship("Task", back_populates="comments")
    attachments = Column(JSON, default=list)


# ---------------------------------------------------------------------------
# Module 31 — Sourcing & acquisitions immobilières
# ---------------------------------------------------------------------------
class AcquisitionStatus(str, enum.Enum):
    PROSPECTING = "prospection"
    ANALYZING = "analyse"
    DUE_DILIGENCE = "due_diligence"
    OFFER = "offre"
    WON = "gagne"
    LOST = "perdu"
    ARCHIVED = "archive"


class AcquisitionOpportunity(Base):
    __tablename__ = "acquisition_opportunities"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    source = Column(String(80))
    address = Column(String(500))
    postal_code = Column(String(10))
    city = Column(String(100))
    cadastre = Column(String(120))
    expected_price = Column(Float)
    market_price = Column(Float)
    potential_rent = Column(Float)
    total_area = Column(Float)
    condition = Column(String(50))
    status = Column(Enum(AcquisitionStatus), default=AcquisitionStatus.PROSPECTING, nullable=False, index=True)
    contact_name = Column(String(255))
    contact_email = Column(String(255))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    diligence_items = relationship("DueDiligenceItem", back_populates="opportunity", cascade="all, delete-orphan")


class DueDiligenceItem(Base):
    __tablename__ = "due_diligence_items"

    id = Column(Integer, primary_key=True, index=True)
    opportunity_id = Column(Integer, ForeignKey("acquisition_opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(255), nullable=False)
    category = Column(String(80))
    status = Column(String(20), default="todo")
    due_date = Column(Date)
    completed_at = Column(DateTime(timezone=True))
    notes = Column(Text)

    opportunity = relationship("AcquisitionOpportunity", back_populates="diligence_items")
