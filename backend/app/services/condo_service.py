"""Services métier du module 7 : gestion de copropriété.

Centralise la fiche copropriété (lots, tantièmes, parties communes, syndic),
les charges de copropriété (budget, appels de fonds, fonds travaux),
l'assemblée générale (convocation, présence, résolutions/votes, PV), le
conseil syndical, le carnet d'entretien et la comptabilité dédiée
(plan comptable, journal, grand livre, bilan, répartition des charges).
"""

import uuid
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.condo import (
    AGAgendaItem,
    AGAttendance,
    AGResolution,
    AGVote,
    AssemblyStatus,
    AttendanceStatus,
    BudgetStatus,
    CondoAccount,
    CondoBookEntry,
    CondoBudget,
    CondoBudgetLine,
    CondoBuilding,
    CondoCommonArea,
    CondoFundCall,
    CondoFundCallLine,
    CondoJournalEntry,
    CondoJournalEntryStatus,
    CondoJournalLine,
    CondoLot,
    CondoWorksFund,
    CondoWorksFundMovement,
    FundCallLineStatus,
    FundCallStatus,
    GeneralAssembly,
    ResolutionStatus,
    SyndicCouncilMeeting,
    SyndicCouncilMember,
    VoteChoice,
    VoteMajority,
    WorksFundMovementType,
)


def generate_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Fiche copropriété / immeuble
# ---------------------------------------------------------------------------
def create_building(db: Session, data) -> CondoBuilding:
    building = CondoBuilding(reference=generate_reference("COP"), **data.model_dump())
    db.add(building)
    db.commit()
    db.refresh(building)
    # Crée automatiquement le fonds de travaux (obligation légale ALUR).
    db.add(CondoWorksFund(building_id=building.id))
    db.commit()
    return building


def update_building(db: Session, building_id: int, data) -> CondoBuilding:
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(building, field, value)
    db.commit()
    db.refresh(building)
    return building


def create_lot(db: Session, building_id: int, data) -> CondoLot:
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    lot = CondoLot(building_id=building_id, **data.model_dump())
    db.add(lot)
    building.total_lots = db.query(CondoLot).filter(CondoLot.building_id == building_id).count() + 1
    db.commit()
    db.refresh(lot)
    return lot


def update_lot(db: Session, lot_id: int, data) -> CondoLot:
    lot = db.query(CondoLot).filter(CondoLot.id == lot_id).first()
    if not lot:
        raise ValueError("Lot non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(lot, field, value)
    db.commit()
    db.refresh(lot)
    return lot


def tantiemes_balance(db: Session, building_id: int) -> Dict:
    """Contrôle la répartition des tantièmes (somme des lots vs total déclaré)."""
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    lots = db.query(CondoLot).filter(CondoLot.building_id == building_id).all()
    allocated = sum(l.tantiemes or 0 for l in lots)
    return {
        "building_id": building_id,
        "total_tantiemes": building.total_tantiemes,
        "allocated_tantiemes": allocated,
        "remaining_tantiemes": building.total_tantiemes - allocated,
        "balanced": allocated == building.total_tantiemes,
        "lot_count": len(lots),
    }


def create_common_area(db: Session, building_id: int, data) -> CondoCommonArea:
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    area = CondoCommonArea(building_id=building_id, **data.model_dump())
    db.add(area)
    db.commit()
    db.refresh(area)
    return area


# ---------------------------------------------------------------------------
# Charges de copropriété
# ---------------------------------------------------------------------------
def create_budget(db: Session, building_id: int, data) -> CondoBudget:
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    payload = data.model_dump(exclude={"lines"})
    budget = CondoBudget(building_id=building_id, status=BudgetStatus.DRAFT, **payload)
    db.add(budget)
    db.flush()
    for line in data.lines:
        db.add(CondoBudgetLine(budget_id=budget.id, **line.model_dump()))
    db.commit()
    db.refresh(budget)
    return budget


def vote_budget(db: Session, budget_id: int, assembly_id: Optional[int] = None) -> CondoBudget:
    budget = db.query(CondoBudget).filter(CondoBudget.id == budget_id).first()
    if not budget:
        raise ValueError("Budget non trouvé")
    if assembly_id:
        assembly = db.query(GeneralAssembly).filter(GeneralAssembly.id == assembly_id).first()
        if not assembly:
            raise ValueError("Assemblée non trouvée")
        budget.voted_assembly_id = assembly_id
    budget.status = BudgetStatus.VOTED
    db.commit()
    db.refresh(budget)
    return budget


def _lot_shares(db: Session, building_id: int) -> List[CondoLot]:
    return db.query(CondoLot).filter(CondoLot.building_id == building_id).all()


def create_fund_call(db: Session, building_id: int, data) -> CondoFundCall:
    """Crée un appel de fonds et répartit automatiquement le montant par tantièmes."""
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    total_amount = data.total_amount
    if total_amount is None:
        if not data.budget_id:
            raise ValueError("Indiquez un montant total ou un budget de référence")
        budget = db.query(CondoBudget).filter(CondoBudget.id == data.budget_id).first()
        if not budget:
            raise ValueError("Budget non trouvé")
        # Appel trimestriel standard = 1/4 du budget annuel voté.
        total_amount = round(budget.total_amount / 4, 2)

    lots = _lot_shares(db, building_id)
    if not lots:
        raise ValueError("Aucun lot enregistré pour répartir l'appel de fonds")
    if building.total_tantiemes <= 0:
        raise ValueError("Le total des tantièmes de la copropriété doit être positif")

    fund_call = CondoFundCall(
        reference=generate_reference("AF"),
        building_id=building_id,
        budget_id=data.budget_id,
        period_label=data.period_label,
        charge_nature=data.charge_nature,
        call_date=data.call_date,
        due_date=data.due_date,
        total_amount=total_amount,
        status=FundCallStatus.DRAFT,
        notes=data.notes,
    )
    db.add(fund_call)
    db.flush()

    allocated_total = 0.0
    created_lines = []
    for lot in lots:
        share = round(total_amount * (lot.tantiemes or 0) / building.total_tantiemes, 2)
        allocated_total += share
        line = CondoFundCallLine(
            fund_call_id=fund_call.id,
            lot_id=lot.id,
            tantiemes_used=lot.tantiemes or 0,
            amount=share,
            status=FundCallLineStatus.PENDING,
        )
        db.add(line)
        created_lines.append(line)
    # Ajuste l'écart d'arrondi sur la dernière ligne pour un total exact.
    rounding_gap = round(total_amount - allocated_total, 2)
    if rounding_gap and created_lines:
        created_lines[-1].amount = round(created_lines[-1].amount + rounding_gap, 2)
    db.commit()
    db.refresh(fund_call)
    return fund_call


def send_fund_call(db: Session, fund_call_id: int) -> CondoFundCall:
    fund_call = db.query(CondoFundCall).filter(CondoFundCall.id == fund_call_id).first()
    if not fund_call:
        raise ValueError("Appel de fonds non trouvé")
    fund_call.status = FundCallStatus.SENT
    db.commit()
    db.refresh(fund_call)
    return fund_call


def pay_fund_call_line(db: Session, line_id: int, data) -> CondoFundCallLine:
    line = db.query(CondoFundCallLine).filter(CondoFundCallLine.id == line_id).first()
    if not line:
        raise ValueError("Ligne d'appel de fonds non trouvée")
    line.paid_amount = round((line.paid_amount or 0) + data.amount, 2)
    line.paid_at = data.paid_at or _now()
    if line.paid_amount >= line.amount:
        line.status = FundCallLineStatus.PAID
    else:
        line.status = FundCallLineStatus.PARTIAL
    db.commit()
    db.refresh(line)
    _refresh_fund_call_status(db, line.fund_call_id)
    db.refresh(line)
    return line


def _refresh_fund_call_status(db: Session, fund_call_id: int) -> None:
    fund_call = db.query(CondoFundCall).filter(CondoFundCall.id == fund_call_id).first()
    if not fund_call:
        return
    lines = db.query(CondoFundCallLine).filter(CondoFundCallLine.fund_call_id == fund_call_id).all()
    if lines and all(l.status == FundCallLineStatus.PAID for l in lines):
        fund_call.status = FundCallStatus.PAID
    elif any(l.status in (FundCallLineStatus.PAID, FundCallLineStatus.PARTIAL) for l in lines):
        fund_call.status = FundCallStatus.PARTIALLY_PAID
    elif fund_call.due_date < date.today() and fund_call.status != FundCallStatus.DRAFT:
        fund_call.status = FundCallStatus.OVERDUE
    db.commit()


def charges_repartition(db: Session, building_id: int, fiscal_year: int) -> Dict:
    """Répartition des charges courantes/exceptionnelles/travaux par lot sur l'année."""
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    calls = db.query(CondoFundCall).filter(
        CondoFundCall.building_id == building_id,
        CondoFundCall.call_date >= date(fiscal_year, 1, 1),
        CondoFundCall.call_date <= date(fiscal_year, 12, 31),
    ).all()
    by_lot: Dict[int, Dict] = {}
    for call in calls:
        for line in call.lines:
            entry = by_lot.setdefault(line.lot_id, {"lot_id": line.lot_id, "lot_number": line.lot.lot_number, "called": 0.0, "paid": 0.0})
            entry["called"] += line.amount
            entry["paid"] += line.paid_amount or 0
    for entry in by_lot.values():
        entry["called"] = round(entry["called"], 2)
        entry["paid"] = round(entry["paid"], 2)
        entry["balance"] = round(entry["called"] - entry["paid"], 2)
    return {
        "building_id": building_id,
        "fiscal_year": fiscal_year,
        "fund_call_count": len(calls),
        "total_called": round(sum(e["called"] for e in by_lot.values()), 2),
        "total_paid": round(sum(e["paid"] for e in by_lot.values()), 2),
        "by_lot": list(by_lot.values()),
    }


def works_fund_contribute(db: Session, building_id: int, data) -> CondoWorksFund:
    fund = db.query(CondoWorksFund).filter(CondoWorksFund.building_id == building_id).first()
    if not fund:
        raise ValueError("Fonds travaux non trouvé")
    movement = CondoWorksFundMovement(fund_id=fund.id, **data.model_dump())
    db.add(movement)
    if data.movement_type == WorksFundMovementType.CONTRIBUTION:
        fund.balance = round((fund.balance or 0) + data.amount, 2)
    else:
        if (fund.balance or 0) < data.amount:
            raise ValueError("Solde du fonds travaux insuffisant")
        fund.balance = round((fund.balance or 0) - data.amount, 2)
    db.commit()
    db.refresh(fund)
    return fund


def get_works_fund(db: Session, building_id: int) -> CondoWorksFund:
    fund = db.query(CondoWorksFund).filter(CondoWorksFund.building_id == building_id).first()
    if not fund:
        raise ValueError("Fonds travaux non trouvé")
    return fund


def update_works_fund_config(db: Session, building_id: int, data) -> CondoWorksFund:
    fund = get_works_fund(db, building_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(fund, field, value)
    db.commit()
    db.refresh(fund)
    return fund


# ---------------------------------------------------------------------------
# Assemblée Générale
# ---------------------------------------------------------------------------
def create_assembly(db: Session, building_id: int, data) -> GeneralAssembly:
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    payload = data.model_dump(exclude={"agenda_items"})
    assembly = GeneralAssembly(
        reference=generate_reference("AG"),
        building_id=building_id,
        status=AssemblyStatus.DRAFT,
        quorum_tantiemes=0,
        **payload,
    )
    db.add(assembly)
    db.flush()
    for idx, item in enumerate(data.agenda_items):
        db.add(AGAgendaItem(assembly_id=assembly.id, position=item.position or idx, title=item.title, description=item.description))
    db.commit()
    db.refresh(assembly)
    return assembly


def convene_assembly(db: Session, assembly_id: int, data) -> GeneralAssembly:
    """Convocation : verrouille l'ordre du jour et notifie les copropriétaires."""
    assembly = db.query(GeneralAssembly).filter(GeneralAssembly.id == assembly_id).first()
    if not assembly:
        raise ValueError("Assemblée non trouvée")
    if not assembly.agenda_items:
        raise ValueError("Impossible de convoquer sans ordre du jour")
    assembly.status = AssemblyStatus.CONVENED
    assembly.convened_at = data.convened_at or _now()
    # Pré-crée une ligne de présence par lot du bien pour préparer la feuille.
    lots = db.query(CondoLot).filter(CondoLot.building_id == assembly.building_id).all()
    existing_lot_ids = {a.lot_id for a in assembly.attendances}
    for lot in lots:
        if lot.id not in existing_lot_ids:
            db.add(AGAttendance(assembly_id=assembly.id, lot_id=lot.id, status=AttendanceStatus.ABSENT))
    db.commit()
    db.refresh(assembly)
    return assembly


def submit_attendance_sheet(db: Session, assembly_id: int, data) -> Dict:
    """Enregistre la feuille de présence et calcule le quorum atteint."""
    assembly = db.query(GeneralAssembly).filter(GeneralAssembly.id == assembly_id).first()
    if not assembly:
        raise ValueError("Assemblée non trouvée")
    building = db.query(CondoBuilding).filter(CondoBuilding.id == assembly.building_id).first()
    lots_by_id = {l.id: l for l in db.query(CondoLot).filter(CondoLot.building_id == assembly.building_id).all()}

    for record in data.records:
        lot = lots_by_id.get(record.lot_id)
        if not lot:
            raise ValueError(f"Lot {record.lot_id} inconnu pour cette copropriété")
        attendance = db.query(AGAttendance).filter(
            AGAttendance.assembly_id == assembly_id, AGAttendance.lot_id == record.lot_id
        ).first()
        if not attendance:
            attendance = AGAttendance(assembly_id=assembly_id, lot_id=record.lot_id)
            db.add(attendance)
        attendance.status = record.status
        attendance.proxy_holder_name = record.proxy_holder_name
        attendance.tantiemes_present = lot.tantiemes if record.status in (AttendanceStatus.PRESENT, AttendanceStatus.REPRESENTED) else 0
        attendance.signed_at = _now()

    db.flush()
    tantiemes_present = sum(a.tantiemes_present or 0 for a in assembly.attendances)
    quorum_met = tantiemes_present > (building.total_tantiemes / 2) if building.total_tantiemes else False
    assembly.quorum_tantiemes = tantiemes_present
    assembly.quorum_met = quorum_met
    if assembly.status == AssemblyStatus.CONVENED:
        assembly.status = AssemblyStatus.HELD
    db.commit()
    return {
        "assembly_id": assembly.id,
        "tantiemes_present": tantiemes_present,
        "total_tantiemes": building.total_tantiemes,
        "quorum_met": quorum_met,
    }


def add_resolution(db: Session, assembly_id: int, data) -> AGResolution:
    assembly = db.query(GeneralAssembly).filter(GeneralAssembly.id == assembly_id).first()
    if not assembly:
        raise ValueError("Assemblée non trouvée")
    number = len(assembly.resolutions) + 1
    resolution = AGResolution(assembly_id=assembly_id, number=number, **data.model_dump(exclude={"agenda_item_id"}), agenda_item_id=data.agenda_item_id)
    db.add(resolution)
    db.commit()
    db.refresh(resolution)
    return resolution


_MAJORITY_THRESHOLDS = {
    VoteMajority.ARTICLE_24: "expressed",   # Majorité des voix exprimées (présents/représentés)
    VoteMajority.ARTICLE_25: "syndicate",   # Majorité absolue de tous les copropriétaires
    VoteMajority.ARTICLE_26: "syndicate_double",  # Double majorité (approximée à 2/3 du syndicat)
    VoteMajority.UNANIMITY: "unanimity",
}


def record_resolution_votes(db: Session, resolution_id: int, data) -> AGResolution:
    """Enregistre les votes par lot et détermine l'adoption selon la majorité requise."""
    resolution = db.query(AGResolution).filter(AGResolution.id == resolution_id).first()
    if not resolution:
        raise ValueError("Résolution non trouvée")
    assembly = resolution.assembly
    building = db.query(CondoBuilding).filter(CondoBuilding.id == assembly.building_id).first()
    lots_by_id = {l.id: l for l in db.query(CondoLot).filter(CondoLot.building_id == assembly.building_id).all()}

    # Réinitialise les votes existants pour permettre une ressaisie.
    db.query(AGVote).filter(AGVote.resolution_id == resolution_id).delete()

    tantiemes_for = tantiemes_against = tantiemes_abstain = 0
    for record in data.votes:
        lot = lots_by_id.get(record.lot_id)
        if not lot:
            raise ValueError(f"Lot {record.lot_id} inconnu pour cette copropriété")
        db.add(AGVote(resolution_id=resolution_id, lot_id=record.lot_id, choice=record.choice, tantiemes=lot.tantiemes or 0))
        if record.choice == VoteChoice.FOR:
            tantiemes_for += lot.tantiemes or 0
        elif record.choice == VoteChoice.AGAINST:
            tantiemes_against += lot.tantiemes or 0
        else:
            tantiemes_abstain += lot.tantiemes or 0

    resolution.tantiemes_for = tantiemes_for
    resolution.tantiemes_against = tantiemes_against
    resolution.tantiemes_abstain = tantiemes_abstain
    resolution.decided_at = _now()

    total_tantiemes = building.total_tantiemes or 1
    expressed = tantiemes_for + tantiemes_against
    rule = _MAJORITY_THRESHOLDS[resolution.majority_required]
    if rule == "expressed":
        adopted = tantiemes_for > tantiemes_against
    elif rule == "syndicate":
        adopted = tantiemes_for > total_tantiemes / 2
    elif rule == "syndicate_double":
        adopted = tantiemes_for > (2 * total_tantiemes / 3)
    else:  # unanimity
        adopted = tantiemes_against == 0 and tantiemes_abstain == 0 and tantiemes_for > 0

    resolution.status = ResolutionStatus.ADOPTED if adopted else ResolutionStatus.REJECTED
    db.commit()
    db.refresh(resolution)
    return resolution


def close_assembly(db: Session, assembly_id: int, data) -> GeneralAssembly:
    """Clôture l'assemblée et enregistre le procès-verbal (résolutions figées)."""
    assembly = db.query(GeneralAssembly).filter(GeneralAssembly.id == assembly_id).first()
    if not assembly:
        raise ValueError("Assemblée non trouvée")
    pending = [r for r in assembly.resolutions if r.status == ResolutionStatus.PENDING]
    if pending:
        raise ValueError("Toutes les résolutions doivent être votées avant clôture")
    assembly.status = AssemblyStatus.CLOSED
    if data.minutes:
        assembly.notes = (assembly.notes or "") + f"\nPV : {data.minutes}"
    db.commit()
    db.refresh(assembly)
    return assembly


def assembly_minutes(db: Session, assembly_id: int) -> Dict:
    """Génère le contenu structuré du procès-verbal (résolutions, votes, présence)."""
    assembly = db.query(GeneralAssembly).filter(GeneralAssembly.id == assembly_id).first()
    if not assembly:
        raise ValueError("Assemblée non trouvée")
    return {
        "assembly_id": assembly.id,
        "reference": assembly.reference,
        "meeting_date": assembly.meeting_date,
        "status": assembly.status.value,
        "quorum_met": assembly.quorum_met,
        "quorum_tantiemes": assembly.quorum_tantiemes,
        "attendance": [
            {"lot_id": a.lot_id, "lot_number": a.lot.lot_number, "status": a.status.value, "tantiemes": a.tantiemes_present}
            for a in assembly.attendances
        ],
        "resolutions": [
            {
                "number": r.number,
                "title": r.title,
                "majority_required": r.majority_required.value,
                "status": r.status.value,
                "tantiemes_for": r.tantiemes_for,
                "tantiemes_against": r.tantiemes_against,
                "tantiemes_abstain": r.tantiemes_abstain,
            }
            for r in assembly.resolutions
        ],
    }


# ---------------------------------------------------------------------------
# Conseil syndical
# ---------------------------------------------------------------------------
def add_council_member(db: Session, building_id: int, data) -> SyndicCouncilMember:
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    member = SyndicCouncilMember(building_id=building_id, **data.model_dump())
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def update_council_member(db: Session, member_id: int, data) -> SyndicCouncilMember:
    member = db.query(SyndicCouncilMember).filter(SyndicCouncilMember.id == member_id).first()
    if not member:
        raise ValueError("Membre du conseil syndical non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(member, field, value)
    db.commit()
    db.refresh(member)
    return member


def create_council_meeting(db: Session, building_id: int, data) -> SyndicCouncilMeeting:
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    meeting = SyndicCouncilMeeting(building_id=building_id, **data.model_dump())
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting


def set_council_meeting_minutes(db: Session, meeting_id: int, data) -> SyndicCouncilMeeting:
    meeting = db.query(SyndicCouncilMeeting).filter(SyndicCouncilMeeting.id == meeting_id).first()
    if not meeting:
        raise ValueError("Réunion non trouvée")
    meeting.minutes = data.minutes
    db.commit()
    db.refresh(meeting)
    return meeting


# ---------------------------------------------------------------------------
# Carnet d'entretien
# ---------------------------------------------------------------------------
def add_book_entry(db: Session, building_id: int, data) -> CondoBookEntry:
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    entry = CondoBookEntry(building_id=building_id, **data.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# Comptabilité copropriété
# ---------------------------------------------------------------------------
_STANDARD_CONDO_ACCOUNTS = {
    "45": {"label": "Copropriétaires - compte individuel", "type": "asset"},
    "512": {"label": "Banque copropriété", "type": "asset"},
    "16": {"label": "Fonds travaux (article 14-2)", "type": "liability"},
    "60": {"label": "Achats et fournitures", "type": "expense"},
    "61": {"label": "Services extérieurs (contrats, assurances)", "type": "expense"},
    "62": {"label": "Honoraires syndic", "type": "expense"},
    "70": {"label": "Produits (appels de fonds)", "type": "income"},
    "40": {"label": "Fournisseurs copropriété", "type": "liability"},
}


def create_standard_chart(db: Session) -> List[CondoAccount]:
    created = []
    for code, bundle in _STANDARD_CONDO_ACCOUNTS.items():
        existing = db.query(CondoAccount).filter(CondoAccount.code == code).first()
        if existing:
            continue
        account = CondoAccount(code=code, label=bundle["label"], account_type=bundle["type"], is_system=True)
        db.add(account)
        created.append(account)
    db.commit()
    for account in created:
        db.refresh(account)
    return created


def create_account(db: Session, data) -> CondoAccount:
    existing = db.query(CondoAccount).filter(CondoAccount.code == data.code).first()
    if existing:
        raise ValueError("Un compte avec ce code existe déjà")
    account = CondoAccount(**data.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _get_or_create_account(db: Session, code: str) -> CondoAccount:
    account = db.query(CondoAccount).filter(CondoAccount.code == code).first()
    if account:
        return account
    bundle = _STANDARD_CONDO_ACCOUNTS.get(code, {"label": code, "type": "other"})
    account = CondoAccount(code=code, label=bundle["label"], account_type=bundle["type"], is_system=True)
    db.add(account)
    db.flush()
    return account


def create_journal_entry(db: Session, building_id: int, data) -> CondoJournalEntry:
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    entry = CondoJournalEntry(
        building_id=building_id,
        code=generate_reference("ECOP"),
        entry_date=data.entry_date,
        label=data.label,
        reference=data.reference,
        source_type=data.source_type,
        source_id=data.source_id,
        status=CondoJournalEntryStatus.DRAFT,
    )
    db.add(entry)
    db.flush()
    total_debit = total_credit = 0.0
    for line in data.lines:
        account = _get_or_create_account(db, line.account_code)
        db.add(CondoJournalLine(entry_id=entry.id, account_id=account.id, lot_id=line.lot_id, debit=line.debit, credit=line.credit, label=line.label))
        total_debit += line.debit
        total_credit += line.credit
    if round(total_debit, 2) != round(total_credit, 2):
        db.rollback()
        raise ValueError(f"Écriture déséquilibrée : débit {total_debit} vs crédit {total_credit}")
    db.commit()
    db.refresh(entry)
    return entry


def validate_journal_entry(db: Session, entry_id: int) -> CondoJournalEntry:
    entry = db.query(CondoJournalEntry).filter(CondoJournalEntry.id == entry_id).first()
    if not entry:
        raise ValueError("Écriture non trouvée")
    entry.status = CondoJournalEntryStatus.VALIDATED
    db.commit()
    db.refresh(entry)
    return entry


def general_ledger(db: Session, building_id: int, account_code: Optional[str] = None) -> Dict:
    """Grand livre de la copropriété, éventuellement filtré sur un compte."""
    query = db.query(CondoJournalLine).join(CondoJournalEntry).filter(CondoJournalEntry.building_id == building_id)
    if account_code:
        query = query.join(CondoAccount).filter(CondoAccount.code == account_code)
    lines = query.order_by(CondoJournalEntry.entry_date).all()
    balance = 0.0
    ledger = []
    for line in lines:
        balance += (line.debit or 0) - (line.credit or 0)
        ledger.append({
            "entry_date": line.entry.entry_date,
            "entry_code": line.entry.code,
            "account_code": line.account.code,
            "account_label": line.account.label,
            "label": line.label or line.entry.label,
            "debit": line.debit,
            "credit": line.credit,
            "balance": round(balance, 2),
        })
    return {"building_id": building_id, "account_code": account_code, "lines": ledger, "final_balance": round(balance, 2)}


def condo_balance_sheet(db: Session, building_id: int, as_of: Optional[date] = None) -> Dict:
    """Bilan simplifié de la copropriété (actif / passif / résultat)."""
    building = db.query(CondoBuilding).filter(CondoBuilding.id == building_id).first()
    if not building:
        raise ValueError("Copropriété non trouvée")
    query = db.query(CondoJournalLine).join(CondoJournalEntry).filter(CondoJournalEntry.building_id == building_id)
    if as_of:
        query = query.filter(CondoJournalEntry.entry_date <= as_of)
    lines = query.all()
    by_type: Dict[str, float] = {"asset": 0.0, "liability": 0.0, "income": 0.0, "expense": 0.0, "other": 0.0}
    for line in lines:
        account_type = line.account.account_type or "other"
        by_type[account_type] = by_type.get(account_type, 0.0) + (line.debit or 0) - (line.credit or 0)
    result = -by_type.get("income", 0.0) - by_type.get("expense", 0.0)
    return {
        "building_id": building_id,
        "as_of": as_of,
        "assets": round(by_type.get("asset", 0.0), 2),
        "liabilities": round(-by_type.get("liability", 0.0), 2),
        "income": round(-by_type.get("income", 0.0), 2),
        "expenses": round(by_type.get("expense", 0.0), 2),
        "result": round(result, 2),
        "works_fund_balance": building.works_fund.balance if building.works_fund else 0,
    }
