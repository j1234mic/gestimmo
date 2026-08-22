"""API du module 7 : gestion de copropriété."""

from typing import Optional

from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.database import get_db
from app.models.condo import (
    AGResolution,
    CondoAccount,
    CondoBookEntry,
    CondoBudget,
    CondoBuilding,
    CondoCommonArea,
    CondoFundCall,
    CondoFundCallLine,
    CondoJournalEntry,
    CondoLot,
    GeneralAssembly,
    SyndicCouncilMeeting,
    SyndicCouncilMember,
)
from app.schemas.condo import (
    AGAgendaItemCreate,
    AGResolutionCreate,
    AssemblyClose,
    AssemblyConvene,
    AttendanceSheetSubmit,
    CondoAccountCreate,
    CondoBookEntryCreate,
    CondoBudgetCreate,
    CondoBudgetVote,
    CondoBuildingCreate,
    CondoBuildingUpdate,
    CondoCommonAreaCreate,
    CondoFundCallCreate,
    CondoJournalEntryCreate,
    CondoLotCreate,
    CondoLotUpdate,
    CondoWorksFundConfig,
    CondoWorksFundMovementCreate,
    CouncilMeetingCreate,
    CouncilMeetingMinutes,
    CouncilMemberCreate,
    CouncilMemberUpdate,
    FundCallPayment,
    GeneralAssemblyCreate,
    ResolutionVoteSubmit,
)
from app.services.condo_service import (
    add_book_entry,
    add_council_member,
    add_resolution,
    assembly_minutes,
    charges_repartition,
    close_assembly,
    condo_balance_sheet,
    convene_assembly,
    create_account,
    create_assembly,
    create_budget,
    create_building,
    create_common_area,
    create_council_meeting,
    create_fund_call,
    create_journal_entry,
    create_lot,
    create_standard_chart,
    general_ledger,
    get_works_fund,
    pay_fund_call_line,
    record_resolution_votes,
    send_fund_call,
    set_council_meeting_minutes,
    submit_attendance_sheet,
    tantiemes_balance,
    update_building,
    update_council_member,
    update_lot,
    update_works_fund_config,
    validate_journal_entry,
    vote_budget,
    works_fund_contribute,
)

router = APIRouter(prefix="/api/condo", tags=["Gestion de copropriété"])


def _building_or_404(db: Session, building_id: int) -> CondoBuilding:
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise HTTPException(status_code=404, detail="Copropriété non trouvée")
    return building


# ---------------------------------------------------------------------------
# Fiche copropriété / immeuble
# ---------------------------------------------------------------------------
@router.post("/buildings", status_code=201)
def create_building_endpoint(data: CondoBuildingCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    building = create_building(db, data)
    return _building_view(building)


@router.get("/buildings")
def list_buildings(search: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    query = db.query(CondoBuilding)
    if search:
        query = query.filter(CondoBuilding.name.ilike(f"%{search}%"))
    buildings = query.order_by(CondoBuilding.name).all()
    return {"data": [_building_view(b) for b in buildings], "count": len(buildings)}


@router.get("/buildings/{building_id}")
def get_building(building_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    building = _building_or_404(db, building_id)
    view = _building_view(building)
    view["lots"] = [_lot_view(l) for l in building.lots]
    view["common_areas"] = [_common_area_view(a) for a in building.common_areas]
    return view


@router.put("/buildings/{building_id}")
def update_building_endpoint(building_id: int, data: CondoBuildingUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _building_or_404(db, building_id)
    try:
        building = update_building(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _building_view(building)


@router.post("/buildings/{building_id}/lots", status_code=201)
def create_lot_endpoint(building_id: int, data: CondoLotCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        lot = create_lot(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _lot_view(lot)


@router.get("/buildings/{building_id}/lots")
def list_lots(building_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _building_or_404(db, building_id)
    lots = db.query(CondoLot).filter(CondoLot.building_id == building_id).order_by(CondoLot.lot_number).all()
    return {"data": [_lot_view(l) for l in lots], "count": len(lots)}


@router.put("/lots/{lot_id}")
def update_lot_endpoint(lot_id: int, data: CondoLotUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        lot = update_lot(db, lot_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _lot_view(lot)


@router.get("/buildings/{building_id}/tantiemes-balance")
def get_tantiemes_balance(building_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return tantiemes_balance(db, building_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/buildings/{building_id}/common-areas", status_code=201)
def create_common_area_endpoint(building_id: int, data: CondoCommonAreaCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        area = create_common_area(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _common_area_view(area)


# ---------------------------------------------------------------------------
# Charges de copropriété
# ---------------------------------------------------------------------------
@router.post("/buildings/{building_id}/budgets", status_code=201)
def create_budget_endpoint(building_id: int, data: CondoBudgetCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        budget = create_budget(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _budget_view(budget)


@router.get("/buildings/{building_id}/budgets")
def list_budgets(building_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _building_or_404(db, building_id)
    budgets = db.query(CondoBudget).filter(CondoBudget.building_id == building_id).order_by(CondoBudget.fiscal_year.desc()).all()
    return {"data": [_budget_view(b) for b in budgets], "count": len(budgets)}


@router.post("/budgets/{budget_id}/vote")
def vote_budget_endpoint(budget_id: int, data: CondoBudgetVote, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        budget = vote_budget(db, budget_id, data.assembly_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _budget_view(budget)


@router.post("/buildings/{building_id}/fund-calls", status_code=201)
def create_fund_call_endpoint(building_id: int, data: CondoFundCallCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        fund_call = create_fund_call(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _fund_call_view(fund_call)


@router.get("/buildings/{building_id}/fund-calls")
def list_fund_calls(building_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _building_or_404(db, building_id)
    calls = db.query(CondoFundCall).filter(CondoFundCall.building_id == building_id).order_by(CondoFundCall.call_date.desc()).all()
    return {"data": [_fund_call_view(c) for c in calls], "count": len(calls)}


@router.get("/fund-calls/{fund_call_id}")
def get_fund_call(fund_call_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    fund_call = db.query(CondoFundCall).filter(CondoFundCall.id == fund_call_id).first()
    if not fund_call:
        raise HTTPException(status_code=404, detail="Appel de fonds non trouvé")
    view = _fund_call_view(fund_call)
    view["lines"] = [_fund_call_line_view(l) for l in fund_call.lines]
    return view


@router.post("/fund-calls/{fund_call_id}/send")
def send_fund_call_endpoint(fund_call_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        fund_call = send_fund_call(db, fund_call_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _fund_call_view(fund_call)


@router.post("/fund-calls/lines/{line_id}/pay")
def pay_fund_call_line_endpoint(line_id: int, data: FundCallPayment, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        line = pay_fund_call_line(db, line_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _fund_call_line_view(line)


@router.get("/buildings/{building_id}/charges-repartition")
def get_charges_repartition(building_id: int, fiscal_year: int = Query(...), db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return charges_repartition(db, building_id, fiscal_year)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/buildings/{building_id}/works-fund")
def get_works_fund_endpoint(building_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        fund = get_works_fund(db, building_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _works_fund_view(fund)


@router.put("/buildings/{building_id}/works-fund")
def update_works_fund_endpoint(building_id: int, data: CondoWorksFundConfig, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        fund = update_works_fund_config(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _works_fund_view(fund)


@router.post("/buildings/{building_id}/works-fund/movements", status_code=201)
def works_fund_movement_endpoint(building_id: int, data: CondoWorksFundMovementCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        fund = works_fund_contribute(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _works_fund_view(fund)


# ---------------------------------------------------------------------------
# Assemblée Générale
# ---------------------------------------------------------------------------
@router.post("/buildings/{building_id}/assemblies", status_code=201)
def create_assembly_endpoint(building_id: int, data: GeneralAssemblyCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        assembly = create_assembly(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _assembly_view(assembly)


@router.get("/buildings/{building_id}/assemblies")
def list_assemblies(building_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _building_or_404(db, building_id)
    assemblies = db.query(GeneralAssembly).filter(GeneralAssembly.building_id == building_id).order_by(GeneralAssembly.meeting_date.desc()).all()
    return {"data": [_assembly_view(a) for a in assemblies], "count": len(assemblies)}


@router.get("/assemblies/{assembly_id}")
def get_assembly(assembly_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    assembly = db.query(GeneralAssembly).filter(GeneralAssembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(status_code=404, detail="Assemblée non trouvée")
    view = _assembly_view(assembly)
    view["agenda_items"] = [{"id": i.id, "title": i.title, "description": i.description, "position": i.position} for i in assembly.agenda_items]
    view["resolutions"] = [_resolution_view(r) for r in assembly.resolutions]
    return view


@router.post("/assemblies/{assembly_id}/convene")
def convene_assembly_endpoint(assembly_id: int, data: AssemblyConvene, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        assembly = convene_assembly(db, assembly_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _assembly_view(assembly)


@router.post("/assemblies/{assembly_id}/attendance")
def submit_attendance_endpoint(assembly_id: int, data: AttendanceSheetSubmit, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return submit_attendance_sheet(db, assembly_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/assemblies/{assembly_id}/resolutions", status_code=201)
def add_resolution_endpoint(assembly_id: int, data: AGResolutionCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        resolution = add_resolution(db, assembly_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _resolution_view(resolution)


@router.post("/resolutions/{resolution_id}/vote")
def vote_resolution_endpoint(resolution_id: int, data: ResolutionVoteSubmit, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        resolution = record_resolution_votes(db, resolution_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _resolution_view(resolution)


@router.post("/assemblies/{assembly_id}/close")
def close_assembly_endpoint(assembly_id: int, data: AssemblyClose, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        assembly = close_assembly(db, assembly_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _assembly_view(assembly)


@router.get("/assemblies/{assembly_id}/minutes")
def get_assembly_minutes(assembly_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return assembly_minutes(db, assembly_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Conseil syndical
# ---------------------------------------------------------------------------
@router.post("/buildings/{building_id}/council-members", status_code=201)
def add_council_member_endpoint(building_id: int, data: CouncilMemberCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        member = add_council_member(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _council_member_view(member)


@router.get("/buildings/{building_id}/council-members")
def list_council_members(building_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _building_or_404(db, building_id)
    members = db.query(SyndicCouncilMember).filter(SyndicCouncilMember.building_id == building_id).all()
    return {"data": [_council_member_view(m) for m in members], "count": len(members)}


@router.put("/council-members/{member_id}")
def update_council_member_endpoint(member_id: int, data: CouncilMemberUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        member = update_council_member(db, member_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _council_member_view(member)


@router.post("/buildings/{building_id}/council-meetings", status_code=201)
def create_council_meeting_endpoint(building_id: int, data: CouncilMeetingCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        meeting = create_council_meeting(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _council_meeting_view(meeting)


@router.get("/buildings/{building_id}/council-meetings")
def list_council_meetings(building_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _building_or_404(db, building_id)
    meetings = db.query(SyndicCouncilMeeting).filter(SyndicCouncilMeeting.building_id == building_id).order_by(SyndicCouncilMeeting.meeting_date.desc()).all()
    return {"data": [_council_meeting_view(m) for m in meetings], "count": len(meetings)}


@router.put("/council-meetings/{meeting_id}/minutes")
def set_council_meeting_minutes_endpoint(meeting_id: int, data: CouncilMeetingMinutes, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        meeting = set_council_meeting_minutes(db, meeting_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _council_meeting_view(meeting)


# ---------------------------------------------------------------------------
# Carnet d'entretien
# ---------------------------------------------------------------------------
@router.post("/buildings/{building_id}/book-entries", status_code=201)
def add_book_entry_endpoint(building_id: int, data: CondoBookEntryCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        entry = add_book_entry(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _book_entry_view(entry)


@router.get("/buildings/{building_id}/book-entries")
def list_book_entries(building_id: int, entry_type: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _building_or_404(db, building_id)
    query = db.query(CondoBookEntry).filter(CondoBookEntry.building_id == building_id)
    if entry_type:
        query = query.filter(CondoBookEntry.entry_type == entry_type)
    entries = query.order_by(CondoBookEntry.entry_date.desc()).all()
    return {"data": [_book_entry_view(e) for e in entries], "count": len(entries)}


# ---------------------------------------------------------------------------
# Comptabilité copropriété
# ---------------------------------------------------------------------------
@router.post("/accounts/standard")
def create_standard_chart_endpoint(db: Session = Depends(get_db), current_user=Depends(require_write)):
    accounts = create_standard_chart(db)
    return {"created": len(accounts)}


@router.post("/accounts", status_code=201)
def create_account_endpoint(data: CondoAccountCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        account = create_account(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": account.id, "code": account.code, "label": account.label, "account_type": account.account_type}


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db), current_user=Depends(require_read)):
    accounts = db.query(CondoAccount).order_by(CondoAccount.code).all()
    return {"data": [{"id": a.id, "code": a.code, "label": a.label, "account_type": a.account_type} for a in accounts], "count": len(accounts)}


@router.post("/buildings/{building_id}/journal-entries", status_code=201)
def create_journal_entry_endpoint(building_id: int, data: CondoJournalEntryCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        entry = create_journal_entry(db, building_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _journal_entry_view(entry)


@router.get("/buildings/{building_id}/journal-entries")
def list_journal_entries(building_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _building_or_404(db, building_id)
    entries = db.query(CondoJournalEntry).filter(CondoJournalEntry.building_id == building_id).order_by(CondoJournalEntry.entry_date.desc()).all()
    return {"data": [_journal_entry_view(e) for e in entries], "count": len(entries)}


@router.post("/journal-entries/{entry_id}/validate")
def validate_journal_entry_endpoint(entry_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        entry = validate_journal_entry(db, entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _journal_entry_view(entry)


@router.get("/buildings/{building_id}/general-ledger")
def get_general_ledger(building_id: int, account_code: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return general_ledger(db, building_id, account_code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/buildings/{building_id}/balance-sheet")
def get_balance_sheet(building_id: int, as_of: Optional[date] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return condo_balance_sheet(db, building_id, as_of)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Helpers de sérialisation
# ---------------------------------------------------------------------------
def _building_view(b: CondoBuilding) -> dict:
    return {
        "id": b.id,
        "reference": b.reference,
        "name": b.name,
        "address": b.address,
        "postal_code": b.postal_code,
        "city": b.city,
        "construction_year": b.construction_year,
        "total_lots": b.total_lots,
        "total_tantiemes": b.total_tantiemes,
        "syndic_type": b.syndic_type.value if b.syndic_type else None,
        "syndic_name": b.syndic_name,
        "syndic_contact_name": b.syndic_contact_name,
        "syndic_email": b.syndic_email,
        "syndic_phone": b.syndic_phone,
        "syndic_mandate_number": b.syndic_mandate_number,
        "syndic_contract_start": b.syndic_contract_start,
        "syndic_contract_end": b.syndic_contract_end,
    }


def _lot_view(l: CondoLot) -> dict:
    return {
        "id": l.id,
        "building_id": l.building_id,
        "lot_number": l.lot_number,
        "lot_type": l.lot_type.value,
        "floor": l.floor,
        "description": l.description,
        "tantiemes": l.tantiemes,
        "tantiemes_breakdown": l.tantiemes_breakdown or {},
        "owner_id": l.owner_id,
        "property_id": l.property_id,
        "occupant_type": l.occupant_type.value if l.occupant_type else None,
        "occupant_tenant_id": l.occupant_tenant_id,
        "occupant_name": l.occupant_name,
    }


def _common_area_view(a: CondoCommonArea) -> dict:
    return {"id": a.id, "name": a.name, "description": a.description, "area_m2": a.area_m2}


def _budget_view(b: CondoBudget) -> dict:
    return {
        "id": b.id,
        "building_id": b.building_id,
        "fiscal_year": b.fiscal_year,
        "label": b.label,
        "courante_amount": b.courante_amount,
        "exceptionnelle_amount": b.exceptionnelle_amount,
        "travaux_amount": b.travaux_amount,
        "total_amount": b.total_amount,
        "status": b.status.value,
        "voted_assembly_id": b.voted_assembly_id,
        "lines": [{"id": l.id, "category": l.category, "charge_nature": l.charge_nature.value, "amount": l.amount} for l in b.lines],
    }


def _fund_call_view(c: CondoFundCall) -> dict:
    return {
        "id": c.id,
        "reference": c.reference,
        "building_id": c.building_id,
        "budget_id": c.budget_id,
        "period_label": c.period_label,
        "charge_nature": c.charge_nature.value,
        "call_date": c.call_date,
        "due_date": c.due_date,
        "total_amount": c.total_amount,
        "status": c.status.value,
    }


def _fund_call_line_view(l: CondoFundCallLine) -> dict:
    return {
        "id": l.id,
        "fund_call_id": l.fund_call_id,
        "lot_id": l.lot_id,
        "lot_number": l.lot.lot_number if l.lot else None,
        "tantiemes_used": l.tantiemes_used,
        "amount": l.amount,
        "paid_amount": l.paid_amount,
        "status": l.status.value,
    }


def _works_fund_view(f) -> dict:
    return {
        "id": f.id,
        "building_id": f.building_id,
        "balance": f.balance,
        "annual_contribution_rate": f.annual_contribution_rate,
        "movements": [
            {"id": m.id, "movement_type": m.movement_type.value, "amount": m.amount, "movement_date": m.movement_date, "description": m.description}
            for m in f.movements
        ],
    }


def _assembly_view(a: GeneralAssembly) -> dict:
    return {
        "id": a.id,
        "reference": a.reference,
        "building_id": a.building_id,
        "assembly_type": a.assembly_type.value,
        "status": a.status.value,
        "meeting_date": a.meeting_date,
        "location": a.location,
        "convened_at": a.convened_at,
        "quorum_tantiemes": a.quorum_tantiemes,
        "quorum_met": a.quorum_met,
    }


def _resolution_view(r: AGResolution) -> dict:
    return {
        "id": r.id,
        "assembly_id": r.assembly_id,
        "number": r.number,
        "title": r.title,
        "description": r.description,
        "majority_required": r.majority_required.value,
        "status": r.status.value,
        "tantiemes_for": r.tantiemes_for,
        "tantiemes_against": r.tantiemes_against,
        "tantiemes_abstain": r.tantiemes_abstain,
    }


def _council_member_view(m: SyndicCouncilMember) -> dict:
    return {
        "id": m.id,
        "building_id": m.building_id,
        "owner_id": m.owner_id,
        "full_name": m.full_name,
        "role": m.role,
        "start_date": m.start_date,
        "end_date": m.end_date,
        "is_active": m.is_active,
    }


def _council_meeting_view(m: SyndicCouncilMeeting) -> dict:
    return {
        "id": m.id,
        "building_id": m.building_id,
        "meeting_date": m.meeting_date,
        "title": m.title,
        "agenda": m.agenda,
        "attendees": m.attendees or [],
        "minutes": m.minutes,
    }


def _book_entry_view(e: CondoBookEntry) -> dict:
    return {
        "id": e.id,
        "building_id": e.building_id,
        "entry_type": e.entry_type.value,
        "title": e.title,
        "description": e.description,
        "entry_date": e.entry_date,
        "end_date": e.end_date,
        "provider_name": e.provider_name,
        "cost": e.cost,
        "contract_status": e.contract_status.value if e.contract_status else None,
    }


def _journal_entry_view(e: CondoJournalEntry) -> dict:
    return {
        "id": e.id,
        "building_id": e.building_id,
        "code": e.code,
        "entry_date": e.entry_date,
        "label": e.label,
        "reference": e.reference,
        "source_type": e.source_type,
        "status": e.status.value,
        "lines": [
            {"account_code": l.account.code, "lot_id": l.lot_id, "debit": l.debit, "credit": l.credit, "label": l.label}
            for l in e.lines
        ],
    }
