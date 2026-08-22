"""Schémas Pydantic du module 7 : gestion de copropriété."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.condo import (
    AssemblyType,
    AttendanceStatus,
    BookEntryType,
    ChargeNature,
    ContractStatus,
    LotType,
    OccupantType,
    SyndicType,
    VoteChoice,
    VoteMajority,
    WorksFundMovementType,
)


# ---------------------------------------------------------------------------
# Fiche copropriété / immeuble
# ---------------------------------------------------------------------------
class CondoBuildingCreate(BaseModel):
    name: str
    address: str
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: str = "France"
    construction_year: Optional[int] = None
    total_tantiemes: int = 10000
    syndic_type: SyndicType = SyndicType.PROFESSIONAL
    syndic_name: Optional[str] = None
    syndic_contact_name: Optional[str] = None
    syndic_email: Optional[str] = None
    syndic_phone: Optional[str] = None
    syndic_address: Optional[str] = None
    syndic_mandate_number: Optional[str] = None
    syndic_contract_start: Optional[date] = None
    syndic_contract_end: Optional[date] = None
    notes: Optional[str] = None


class CondoBuildingUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    construction_year: Optional[int] = None
    total_tantiemes: Optional[int] = None
    syndic_type: Optional[SyndicType] = None
    syndic_name: Optional[str] = None
    syndic_contact_name: Optional[str] = None
    syndic_email: Optional[str] = None
    syndic_phone: Optional[str] = None
    syndic_address: Optional[str] = None
    syndic_mandate_number: Optional[str] = None
    syndic_contract_start: Optional[date] = None
    syndic_contract_end: Optional[date] = None
    notes: Optional[str] = None


class CondoLotCreate(BaseModel):
    lot_number: str
    lot_type: LotType = LotType.APARTMENT
    floor: Optional[int] = None
    description: Optional[str] = None
    tantiemes: int = 0
    tantiemes_breakdown: Dict[str, int] = Field(default_factory=dict)
    owner_id: Optional[int] = None
    property_id: Optional[int] = None
    occupant_type: OccupantType = OccupantType.VACANT
    occupant_tenant_id: Optional[int] = None
    occupant_name: Optional[str] = None


class CondoLotUpdate(BaseModel):
    lot_number: Optional[str] = None
    lot_type: Optional[LotType] = None
    floor: Optional[int] = None
    description: Optional[str] = None
    tantiemes: Optional[int] = None
    tantiemes_breakdown: Optional[Dict[str, int]] = None
    owner_id: Optional[int] = None
    property_id: Optional[int] = None
    occupant_type: Optional[OccupantType] = None
    occupant_tenant_id: Optional[int] = None
    occupant_name: Optional[str] = None


class CondoCommonAreaCreate(BaseModel):
    name: str
    description: Optional[str] = None
    area_m2: Optional[float] = None
    maintenance_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Charges de copropriété
# ---------------------------------------------------------------------------
class CondoBudgetLineCreate(BaseModel):
    category: str
    charge_nature: ChargeNature = ChargeNature.COURANTE
    amount: float = 0
    notes: Optional[str] = None


class CondoBudgetCreate(BaseModel):
    fiscal_year: int
    label: str = "Budget prévisionnel"
    courante_amount: float = 0
    exceptionnelle_amount: float = 0
    travaux_amount: float = 0
    notes: Optional[str] = None
    lines: List[CondoBudgetLineCreate] = Field(default_factory=list)


class CondoBudgetVote(BaseModel):
    assembly_id: Optional[int] = None


class CondoFundCallCreate(BaseModel):
    budget_id: Optional[int] = None
    period_label: str
    charge_nature: ChargeNature = ChargeNature.COURANTE
    call_date: date
    due_date: date
    total_amount: Optional[float] = None    # Si absent, calculé depuis le budget/tantièmes
    notes: Optional[str] = None


class FundCallPayment(BaseModel):
    amount: float
    paid_at: Optional[datetime] = None


class CondoWorksFundConfig(BaseModel):
    annual_contribution_rate: Optional[float] = None
    notes: Optional[str] = None


class CondoWorksFundMovementCreate(BaseModel):
    movement_type: WorksFundMovementType
    amount: float
    movement_date: date
    description: Optional[str] = None


# ---------------------------------------------------------------------------
# Assemblée Générale
# ---------------------------------------------------------------------------
class AGAgendaItemCreate(BaseModel):
    title: str
    description: Optional[str] = None
    position: int = 0


class GeneralAssemblyCreate(BaseModel):
    assembly_type: AssemblyType = AssemblyType.ORDINARY
    meeting_date: datetime
    location: Optional[str] = None
    notes: Optional[str] = None
    agenda_items: List[AGAgendaItemCreate] = Field(default_factory=list)


class AssemblyConvene(BaseModel):
    convened_at: Optional[datetime] = None


class AttendanceRecord(BaseModel):
    lot_id: int
    status: AttendanceStatus
    proxy_holder_name: Optional[str] = None


class AttendanceSheetSubmit(BaseModel):
    records: List[AttendanceRecord]


class AGResolutionCreate(BaseModel):
    agenda_item_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    majority_required: VoteMajority = VoteMajority.ARTICLE_24


class VoteRecord(BaseModel):
    lot_id: int
    choice: VoteChoice


class ResolutionVoteSubmit(BaseModel):
    votes: List[VoteRecord]


class AssemblyClose(BaseModel):
    minutes: Optional[str] = None


# ---------------------------------------------------------------------------
# Conseil syndical
# ---------------------------------------------------------------------------
class CouncilMemberCreate(BaseModel):
    owner_id: Optional[int] = None
    full_name: str
    role: str = "membre"
    start_date: Optional[date] = None
    end_date: Optional[date] = None


class CouncilMemberUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_active: Optional[bool] = None


class CouncilMeetingCreate(BaseModel):
    meeting_date: datetime
    title: Optional[str] = None
    agenda: Optional[str] = None
    attendees: List[str] = Field(default_factory=list)


class CouncilMeetingMinutes(BaseModel):
    minutes: str


# ---------------------------------------------------------------------------
# Carnet d'entretien
# ---------------------------------------------------------------------------
class CondoBookEntryCreate(BaseModel):
    entry_type: BookEntryType
    title: str
    description: Optional[str] = None
    entry_date: date
    end_date: Optional[date] = None
    provider_name: Optional[str] = None
    cost: float = 0
    contract_status: Optional[ContractStatus] = None


# ---------------------------------------------------------------------------
# Comptabilité copropriété
# ---------------------------------------------------------------------------
class CondoAccountCreate(BaseModel):
    code: str
    label: str
    account_type: str


class CondoJournalLineInput(BaseModel):
    account_code: str
    debit: float = 0
    credit: float = 0
    lot_id: Optional[int] = None
    label: Optional[str] = None


class CondoJournalEntryCreate(BaseModel):
    entry_date: date
    label: str
    reference: Optional[str] = None
    source_type: Optional[str] = "manual"
    source_id: Optional[int] = None
    lines: List[CondoJournalLineInput]
