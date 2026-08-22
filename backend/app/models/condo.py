"""Modèles du module 7 : gestion de copropriété.

Couvre la fiche copropriété/immeuble (lots, tantièmes, parties communes,
syndic), les charges de copropriété (budget, appels de fonds, fonds de
travaux), l'assemblée générale (convocation, feuille de présence,
résolutions/votes, procès-verbal), le conseil syndical, le carnet
d'entretien et la comptabilité de copropriété (plan comptable, grand livre,
bilan, répartition des charges).
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
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# ---------------------------------------------------------------------------
# Enums métier
# ---------------------------------------------------------------------------
class LotType(str, enum.Enum):
    APARTMENT = "appartement"
    PARKING = "parking"
    CELLAR = "cave"
    COMMERCIAL = "local_commercial"
    OFFICE = "bureau"
    ATTIC = "grenier"
    OTHER = "autre"


class OccupantType(str, enum.Enum):
    OWNER = "proprietaire_occupant"
    TENANT = "locataire"
    VACANT = "vacant"


class SyndicType(str, enum.Enum):
    PROFESSIONAL = "professionnel"
    VOLUNTEER = "benevole"
    COOPERATIVE = "cooperatif"


class ChargeNature(str, enum.Enum):
    COURANTE = "courante"
    EXCEPTIONNELLE = "exceptionnelle"
    TRAVAUX = "travaux"


class BudgetStatus(str, enum.Enum):
    DRAFT = "draft"
    VOTED = "vote"
    CLOSED = "cloture"


class FundCallStatus(str, enum.Enum):
    DRAFT = "draft"
    SENT = "envoye"
    PARTIALLY_PAID = "partiellement_paye"
    PAID = "paye"
    OVERDUE = "en_retard"


class FundCallLineStatus(str, enum.Enum):
    PENDING = "en_attente"
    PARTIAL = "partiel"
    PAID = "paye"


class WorksFundMovementType(str, enum.Enum):
    CONTRIBUTION = "cotisation"
    WITHDRAWAL = "prelevement"


class AssemblyType(str, enum.Enum):
    ORDINARY = "ordinaire"
    EXTRAORDINARY = "extraordinaire"


class AssemblyStatus(str, enum.Enum):
    DRAFT = "draft"
    CONVENED = "convoquee"
    HELD = "tenue"
    CLOSED = "cloturee"


class AttendanceStatus(str, enum.Enum):
    PRESENT = "present"
    REPRESENTED = "represente"
    ABSENT = "absent"


class VoteMajority(str, enum.Enum):
    ARTICLE_24 = "article_24"   # Majorité simple des voix exprimées
    ARTICLE_25 = "article_25"   # Majorité absolue des voix du syndicat
    ARTICLE_26 = "article_26"   # Double majorité
    UNANIMITY = "unanimite"


class ResolutionStatus(str, enum.Enum):
    PENDING = "en_attente"
    ADOPTED = "adoptee"
    REJECTED = "rejetee"


class VoteChoice(str, enum.Enum):
    FOR = "pour"
    AGAINST = "contre"
    ABSTAIN = "abstention"


class BookEntryType(str, enum.Enum):
    WORKS = "travaux"
    CONTRACT = "contrat"
    DIAGNOSTIC = "diagnostic"
    CLAIM = "sinistre"


class ContractStatus(str, enum.Enum):
    ACTIVE = "en_cours"
    ENDED = "termine"
    CANCELLED = "resilie"


class CondoJournalEntryStatus(str, enum.Enum):
    DRAFT = "draft"
    VALIDATED = "validated"


# ---------------------------------------------------------------------------
# Fiche copropriété / immeuble
# ---------------------------------------------------------------------------
class CondoBuilding(Base):
    __tablename__ = "condo_buildings"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    address = Column(String(500), nullable=False)
    postal_code = Column(String(10))
    city = Column(String(100))
    country = Column(String(100), default="France")
    construction_year = Column(Integer)
    total_lots = Column(Integer, default=0)
    total_tantiemes = Column(Integer, default=10000)
    regulation_document_path = Column(String(700))   # Règlement de copropriété
    regulation_updated_at = Column(Date)

    # Syndic
    syndic_type = Column(Enum(SyndicType), default=SyndicType.PROFESSIONAL)
    syndic_name = Column(String(255))
    syndic_contact_name = Column(String(255))
    syndic_email = Column(String(255))
    syndic_phone = Column(String(30))
    syndic_address = Column(String(500))
    syndic_mandate_number = Column(String(100))
    syndic_contract_start = Column(Date)
    syndic_contract_end = Column(Date)

    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    lots = relationship("CondoLot", back_populates="building", cascade="all, delete-orphan")
    common_areas = relationship("CondoCommonArea", back_populates="building", cascade="all, delete-orphan")
    budgets = relationship("CondoBudget", back_populates="building", cascade="all, delete-orphan")
    fund_calls = relationship("CondoFundCall", back_populates="building", cascade="all, delete-orphan")
    works_fund = relationship("CondoWorksFund", back_populates="building", uselist=False, cascade="all, delete-orphan")
    assemblies = relationship("GeneralAssembly", back_populates="building", cascade="all, delete-orphan")
    council_members = relationship("SyndicCouncilMember", back_populates="building", cascade="all, delete-orphan")
    council_meetings = relationship("SyndicCouncilMeeting", back_populates="building", cascade="all, delete-orphan")
    book_entries = relationship("CondoBookEntry", back_populates="building", cascade="all, delete-orphan")
    journal_entries = relationship("CondoJournalEntry", back_populates="building", cascade="all, delete-orphan")


class CondoLot(Base):
    __tablename__ = "condo_lots"

    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("condo_buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    lot_number = Column(String(30), nullable=False)
    lot_type = Column(Enum(LotType), default=LotType.APARTMENT, nullable=False)
    floor = Column(Integer)
    description = Column(String(500))
    tantiemes = Column(Integer, nullable=False, default=0)
    tantiemes_breakdown = Column(JSON, default=dict)  # Clés multiples : général, chauffage, ascenseur...
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="SET NULL"), nullable=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    occupant_type = Column(Enum(OccupantType), default=OccupantType.VACANT)
    occupant_tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True)
    occupant_name = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    building = relationship("CondoBuilding", back_populates="lots")
    owner = relationship("Owner")
    property = relationship("Property")
    tenant = relationship("Tenant")
    fund_call_lines = relationship("CondoFundCallLine", back_populates="lot", cascade="all, delete-orphan")
    attendances = relationship("AGAttendance", back_populates="lot", cascade="all, delete-orphan")
    votes = relationship("AGVote", back_populates="lot", cascade="all, delete-orphan")


class CondoCommonArea(Base):
    __tablename__ = "condo_common_areas"

    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("condo_buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    area_m2 = Column(Float)
    maintenance_notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    building = relationship("CondoBuilding", back_populates="common_areas")


# ---------------------------------------------------------------------------
# Charges de copropriété
# ---------------------------------------------------------------------------
class CondoBudget(Base):
    """Budget prévisionnel voté (annuel) de la copropriété."""
    __tablename__ = "condo_budgets"

    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("condo_buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    fiscal_year = Column(Integer, nullable=False, index=True)
    label = Column(String(255), default="Budget prévisionnel")
    courante_amount = Column(Float, default=0)
    exceptionnelle_amount = Column(Float, default=0)
    travaux_amount = Column(Float, default=0)
    status = Column(Enum(BudgetStatus), default=BudgetStatus.DRAFT, nullable=False)
    voted_assembly_id = Column(Integer, ForeignKey("general_assemblies.id", ondelete="SET NULL"), nullable=True)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    building = relationship("CondoBuilding", back_populates="budgets")
    lines = relationship("CondoBudgetLine", back_populates="budget", cascade="all, delete-orphan")

    @property
    def total_amount(self) -> float:
        return (self.courante_amount or 0) + (self.exceptionnelle_amount or 0) + (self.travaux_amount or 0)


class CondoBudgetLine(Base):
    """Poste budgétaire détaillé (entretien, assurance, honoraires syndic...)."""
    __tablename__ = "condo_budget_lines"

    id = Column(Integer, primary_key=True, index=True)
    budget_id = Column(Integer, ForeignKey("condo_budgets.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(150), nullable=False)
    charge_nature = Column(Enum(ChargeNature), default=ChargeNature.COURANTE, nullable=False)
    amount = Column(Float, nullable=False, default=0)
    notes = Column(Text)

    budget = relationship("CondoBudget", back_populates="lines")


class CondoFundCall(Base):
    """Appel de fonds trimestriel/ponctuel réparti sur les lots."""
    __tablename__ = "condo_fund_calls"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    building_id = Column(Integer, ForeignKey("condo_buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    budget_id = Column(Integer, ForeignKey("condo_budgets.id", ondelete="SET NULL"), nullable=True)
    period_label = Column(String(100), nullable=False)   # ex: "T1 2026"
    charge_nature = Column(Enum(ChargeNature), default=ChargeNature.COURANTE, nullable=False)
    call_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    total_amount = Column(Float, nullable=False, default=0)
    status = Column(Enum(FundCallStatus), default=FundCallStatus.DRAFT, nullable=False, index=True)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    building = relationship("CondoBuilding", back_populates="fund_calls")
    lines = relationship("CondoFundCallLine", back_populates="fund_call", cascade="all, delete-orphan")


class CondoFundCallLine(Base):
    """Quote-part d'un lot dans un appel de fonds (répartition par tantièmes)."""
    __tablename__ = "condo_fund_call_lines"

    id = Column(Integer, primary_key=True, index=True)
    fund_call_id = Column(Integer, ForeignKey("condo_fund_calls.id", ondelete="CASCADE"), nullable=False, index=True)
    lot_id = Column(Integer, ForeignKey("condo_lots.id", ondelete="CASCADE"), nullable=False, index=True)
    tantiemes_used = Column(Integer, nullable=False, default=0)
    amount = Column(Float, nullable=False, default=0)
    paid_amount = Column(Float, default=0)
    status = Column(Enum(FundCallLineStatus), default=FundCallLineStatus.PENDING, nullable=False)
    paid_at = Column(DateTime(timezone=True))

    fund_call = relationship("CondoFundCall", back_populates="lines")
    lot = relationship("CondoLot", back_populates="fund_call_lines")


class CondoWorksFund(Base):
    """Fonds travaux (loi ALUR) alimenté par cotisation annuelle obligatoire."""
    __tablename__ = "condo_works_funds"

    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("condo_buildings.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    balance = Column(Float, default=0)
    annual_contribution_rate = Column(Float, default=0.05)  # 5% du budget prévisionnel par défaut
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    building = relationship("CondoBuilding", back_populates="works_fund")
    movements = relationship("CondoWorksFundMovement", back_populates="fund", cascade="all, delete-orphan")


class CondoWorksFundMovement(Base):
    __tablename__ = "condo_works_fund_movements"

    id = Column(Integer, primary_key=True, index=True)
    fund_id = Column(Integer, ForeignKey("condo_works_funds.id", ondelete="CASCADE"), nullable=False, index=True)
    movement_type = Column(Enum(WorksFundMovementType), nullable=False)
    amount = Column(Float, nullable=False)
    movement_date = Column(Date, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    fund = relationship("CondoWorksFund", back_populates="movements")


# ---------------------------------------------------------------------------
# Assemblée Générale
# ---------------------------------------------------------------------------
class GeneralAssembly(Base):
    __tablename__ = "general_assemblies"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    building_id = Column(Integer, ForeignKey("condo_buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    assembly_type = Column(Enum(AssemblyType), default=AssemblyType.ORDINARY, nullable=False)
    status = Column(Enum(AssemblyStatus), default=AssemblyStatus.DRAFT, nullable=False, index=True)
    meeting_date = Column(DateTime(timezone=True), nullable=False)
    location = Column(String(255))
    convened_at = Column(DateTime(timezone=True))
    convocation_document_path = Column(String(700))
    minutes_document_path = Column(String(700))         # Procès-verbal
    quorum_tantiemes = Column(Integer, default=0)
    quorum_met = Column(Boolean)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    building = relationship("CondoBuilding", back_populates="assemblies")
    agenda_items = relationship("AGAgendaItem", back_populates="assembly", cascade="all, delete-orphan", order_by="AGAgendaItem.position")
    attendances = relationship("AGAttendance", back_populates="assembly", cascade="all, delete-orphan")
    resolutions = relationship("AGResolution", back_populates="assembly", cascade="all, delete-orphan")


class AGAgendaItem(Base):
    __tablename__ = "ag_agenda_items"

    id = Column(Integer, primary_key=True, index=True)
    assembly_id = Column(Integer, ForeignKey("general_assemblies.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, default=0)
    title = Column(String(500), nullable=False)
    description = Column(Text)

    assembly = relationship("GeneralAssembly", back_populates="agenda_items")


class AGAttendance(Base):
    """Feuille de présence : un enregistrement par lot convoqué."""
    __tablename__ = "ag_attendances"

    id = Column(Integer, primary_key=True, index=True)
    assembly_id = Column(Integer, ForeignKey("general_assemblies.id", ondelete="CASCADE"), nullable=False, index=True)
    lot_id = Column(Integer, ForeignKey("condo_lots.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(Enum(AttendanceStatus), default=AttendanceStatus.ABSENT, nullable=False)
    proxy_holder_name = Column(String(255))     # Titulaire du pouvoir si représenté
    tantiemes_present = Column(Integer, default=0)
    signed_at = Column(DateTime(timezone=True))

    assembly = relationship("GeneralAssembly", back_populates="attendances")
    lot = relationship("CondoLot", back_populates="attendances")


class AGResolution(Base):
    __tablename__ = "ag_resolutions"

    id = Column(Integer, primary_key=True, index=True)
    assembly_id = Column(Integer, ForeignKey("general_assemblies.id", ondelete="CASCADE"), nullable=False, index=True)
    agenda_item_id = Column(Integer, ForeignKey("ag_agenda_items.id", ondelete="SET NULL"), nullable=True)
    number = Column(Integer, nullable=False)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    majority_required = Column(Enum(VoteMajority), default=VoteMajority.ARTICLE_24, nullable=False)
    status = Column(Enum(ResolutionStatus), default=ResolutionStatus.PENDING, nullable=False)
    tantiemes_for = Column(Integer, default=0)
    tantiemes_against = Column(Integer, default=0)
    tantiemes_abstain = Column(Integer, default=0)
    decided_at = Column(DateTime(timezone=True))

    assembly = relationship("GeneralAssembly", back_populates="resolutions")
    agenda_item = relationship("AGAgendaItem")
    votes = relationship("AGVote", back_populates="resolution", cascade="all, delete-orphan")


class AGVote(Base):
    """Détail des votes par lot pour une résolution."""
    __tablename__ = "ag_votes"

    id = Column(Integer, primary_key=True, index=True)
    resolution_id = Column(Integer, ForeignKey("ag_resolutions.id", ondelete="CASCADE"), nullable=False, index=True)
    lot_id = Column(Integer, ForeignKey("condo_lots.id", ondelete="CASCADE"), nullable=False, index=True)
    choice = Column(Enum(VoteChoice), nullable=False)
    tantiemes = Column(Integer, nullable=False, default=0)

    resolution = relationship("AGResolution", back_populates="votes")
    lot = relationship("CondoLot", back_populates="votes")


# ---------------------------------------------------------------------------
# Conseil syndical
# ---------------------------------------------------------------------------
class SyndicCouncilMember(Base):
    __tablename__ = "syndic_council_members"

    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("condo_buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="SET NULL"), nullable=True)
    full_name = Column(String(255), nullable=False)
    role = Column(String(100), default="membre")   # president, membre, suppleant
    start_date = Column(Date)
    end_date = Column(Date)
    is_active = Column(Boolean, default=True)

    building = relationship("CondoBuilding", back_populates="council_members")
    owner = relationship("Owner")


class SyndicCouncilMeeting(Base):
    __tablename__ = "syndic_council_meetings"

    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("condo_buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    meeting_date = Column(DateTime(timezone=True), nullable=False)
    title = Column(String(255))
    agenda = Column(Text)
    attendees = Column(JSON, default=list)
    minutes = Column(Text)                       # Compte-rendu
    minutes_document_path = Column(String(700))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    building = relationship("CondoBuilding", back_populates="council_meetings")


# ---------------------------------------------------------------------------
# Carnet d'entretien
# ---------------------------------------------------------------------------
class CondoBookEntry(Base):
    __tablename__ = "condo_book_entries"

    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("condo_buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    entry_type = Column(Enum(BookEntryType), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    entry_date = Column(Date, nullable=False)
    end_date = Column(Date)                       # Pour un contrat en cours
    provider_name = Column(String(255))
    cost = Column(Float, default=0)
    contract_status = Column(Enum(ContractStatus), nullable=True)
    document_path = Column(String(700))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    building = relationship("CondoBuilding", back_populates="book_entries")


# ---------------------------------------------------------------------------
# Comptabilité de copropriété
# ---------------------------------------------------------------------------
class CondoAccount(Base):
    """Plan comptable copropriété (nomenclature dédiée, distincte du plan de
    gestion locative du module 5)."""
    __tablename__ = "condo_accounts"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(20), unique=True, nullable=False, index=True)
    label = Column(String(255), nullable=False)
    account_type = Column(String(30), nullable=False)  # asset, liability, income, expense
    is_system = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CondoJournalEntry(Base):
    __tablename__ = "condo_journal_entries"

    id = Column(Integer, primary_key=True, index=True)
    building_id = Column(Integer, ForeignKey("condo_buildings.id", ondelete="CASCADE"), nullable=False, index=True)
    code = Column(String(30), unique=True, nullable=False, index=True)
    entry_date = Column(Date, nullable=False, index=True)
    label = Column(String(255), nullable=False)
    reference = Column(String(100))
    source_type = Column(String(50))    # fund_call, works_fund, expense, manual
    source_id = Column(Integer)
    status = Column(Enum(CondoJournalEntryStatus), default=CondoJournalEntryStatus.DRAFT, nullable=False)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    building = relationship("CondoBuilding", back_populates="journal_entries")
    lines = relationship("CondoJournalLine", back_populates="entry", cascade="all, delete-orphan")


class CondoJournalLine(Base):
    __tablename__ = "condo_journal_lines"

    id = Column(Integer, primary_key=True, index=True)
    entry_id = Column(Integer, ForeignKey("condo_journal_entries.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("condo_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    lot_id = Column(Integer, ForeignKey("condo_lots.id", ondelete="SET NULL"), nullable=True)
    debit = Column(Float, default=0)
    credit = Column(Float, default=0)
    label = Column(Text)

    entry = relationship("CondoJournalEntry", back_populates="lines")
    account = relationship("CondoAccount")
    lot = relationship("CondoLot")
