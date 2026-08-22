"""Services métier du module 8 : CRM et gestion commerciale.

Centralise les prospects et leur score de qualité explicable, le pipeline
configurable (étapes, Kanban, probabilités), les visites (disponibilités,
confirmation, rappels, compte-rendu, retour visiteur, agenda), le matching
automatique prospect ↔ bien, la diffusion multi-portails des annonces avec
statistiques, le suivi des transactions de vente (offre, compromis,
conditions suspensives, notaire, acte, commission) et la performance des
agents.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.crm import (
    CrmNotification,
    DealStageHistory,
    DealStatus,
    Listing,
    ListingDailyStat,
    ListingStatus,
    ListingTemplate,
    MatchAlert,
    PipelineDeal,
    PipelineStage,
    Portal,
    PortalPublication,
    PublicationStatus,
    Prospect,
    ProspectSource,
    ProspectStatus,
    ProspectType,
    PropertyAvailability,
    PurchaseOffer,
    SaleTransaction,
    SuspensiveCondition,
    TransactionEvent,
    TransactionStage,
    Visit,
    VisitReminder,
    VisitReport,
    VisitStatus,
)
from app.models.property import Property, PropertyStatus
from app.models.tenant import Lease, LeaseStatus
from app.schemas.crm import SaleTransactionCreate

DEFAULT_STAGES: List[Tuple[str, float, bool, bool]] = [
    ("Premier contact", 0.10, False, False),
    ("Qualification", 0.25, False, False),
    ("Visite programmée", 0.40, False, False),
    ("Visite effectuée", 0.55, False, False),
    ("Dossier déposé", 0.70, False, False),
    ("Dossier validé", 0.85, False, False),
    ("Bail signé / Vente conclue", 1.00, True, False),
    ("Perdu", 0.00, False, True),
]

SOURCE_WEIGHTS = {
    ProspectSource.REFERRAL: 1.0,
    ProspectSource.AGENCY: 0.9,
    ProspectSource.WEBSITE: 0.7,
    ProspectSource.PORTAL: 0.7,
    ProspectSource.SOCIAL: 0.6,
    ProspectSource.PHONE: 0.6,
    ProspectSource.WALK_IN: 0.5,
    ProspectSource.OTHER: 0.4,
}


def generate_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def notify(
    db: Session,
    title: str,
    message: str,
    recipient: Optional[str] = None,
    type_: str = "info",
    link: Optional[str] = None,
) -> CrmNotification:
    notification = CrmNotification(
        recipient=recipient, type=type_, title=title, message=message, link=link
    )
    db.add(notification)
    return notification


# ---------------------------------------------------------------------------
# Prospects
# ---------------------------------------------------------------------------
def compute_quality_score(db: Session, prospect: Prospect) -> Dict:
    """Score de qualité 0-100, explicable et pondéré :

    - complétude de la fiche (contact + budget) : 40 pts ;
    - qualité de la source d'acquisition : 20 pts ;
    - engagement (visites effectuées, offres, deals ouverts) : 25 pts ;
    - actualité du contact (moins de 30 jours) : 15 pts.
    """
    detail: Dict[str, Any] = {"parts": [], "total": 0}

    # 1. Complétude de la fiche
    completeness = 0
    checks = {
        "email": bool(prospect.email),
        "telephone": bool(prospect.phone or prospect.mobile),
        "budget": prospect.budget_max is not None,
        "critères": bool(prospect.search_criteria),
        "agent_referent": bool(prospect.assigned_agent),
    }
    completeness = int(40 * sum(checks.values()) / len(checks))
    detail["parts"].append(
        {"label": "Complétude de la fiche", "points": completeness, "max": 40, "checks": checks}
    )

    # 2. Source d'acquisition
    source_points = int(20 * SOURCE_WEIGHTS.get(prospect.source, 0.5))
    detail["parts"].append(
        {
            "label": "Qualité de la source",
            "points": source_points,
            "max": 20,
            "source": prospect.source.value if prospect.source else None,
        }
    )

    # 3. Engagement
    visits_done = (
        db.query(Visit)
        .filter(Visit.prospect_id == prospect.id, Visit.status == VisitStatus.COMPLETED)
        .count()
    )
    open_deals = (
        db.query(PipelineDeal)
        .filter(PipelineDeal.prospect_id == prospect.id, PipelineDeal.status == DealStatus.OPEN)
        .count()
    )
    offers = (
        db.query(PurchaseOffer).filter(PurchaseOffer.prospect_id == prospect.id).count()
    )
    engagement = min(25, visits_done * 10 + open_deals * 8 + offers * 7)
    detail["parts"].append(
        {
            "label": "Engagement",
            "points": engagement,
            "max": 25,
            "visites_effectuees": visits_done,
            "dossiers_ouverts": open_deals,
            "offres": offers,
        }
    )

    # 4. Actualité du contact
    freshness = 0
    reference_date = prospect.last_contact_at or prospect.created_at
    if reference_date:
        days = (_now() - _as_utc(reference_date)).days
        if days <= 7:
            freshness = 15
        elif days <= 30:
            freshness = 8
        detail["parts"].append(
            {"label": "Actualité du contact", "points": freshness, "max": 15, "jours": days}
        )
    else:
        detail["parts"].append({"label": "Actualité du contact", "points": 0, "max": 15})

    total = completeness + source_points + engagement + freshness
    detail["total"] = total

    prospect.quality_score = total
    prospect.score_detail = detail
    return detail


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def create_prospect(db: Session, data) -> Prospect:
    criteria = data.search_criteria or {}
    if data.budget_max is None and criteria.get("budget_max"):
        pass  # budget prioritairement en champs dédiés
    prospect = Prospect(
        reference=generate_reference("PRO"),
        last_contact_at=_now(),
        **data.model_dump(),
    )
    db.add(prospect)
    db.flush()
    compute_quality_score(db, prospect)
    db.commit()
    db.refresh(prospect)
    return prospect


def update_prospect(db: Session, prospect_id: int, data) -> Prospect:
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise ValueError("Prospect non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(prospect, field, value)
    compute_quality_score(db, prospect)
    db.commit()
    db.refresh(prospect)
    return prospect


def set_prospect_status(db: Session, prospect_id: int, status: str, lost_reason: Optional[str] = None) -> Prospect:
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise ValueError("Prospect non trouvé")
    try:
        prospect.status = ProspectStatus(status)
    except ValueError:
        raise ValueError(f"Statut invalide : {status}")
    if prospect.status == ProspectStatus.CONVERTED:
        prospect.converted_at = _now()
    if prospect.status == ProspectStatus.LOST:
        prospect.lost_reason = lost_reason
    db.commit()
    db.refresh(prospect)
    return prospect


def list_prospects(
    db: Session,
    prospect_type: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    min_score: Optional[int] = None,
    search: Optional[str] = None,
) -> List[Prospect]:
    query = db.query(Prospect)
    if prospect_type:
        query = query.filter(Prospect.prospect_type == ProspectType(prospect_type))
    if source:
        query = query.filter(Prospect.source == ProspectSource(source))
    if status:
        query = query.filter(Prospect.status == ProspectStatus(status))
    if agent:
        query = query.filter(Prospect.assigned_agent == agent)
    if min_score is not None:
        query = query.filter(Prospect.quality_score >= min_score)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                Prospect.first_name.ilike(like),
                Prospect.last_name.ilike(like),
                Prospect.email.ilike(like),
                Prospect.reference.ilike(like),
            )
        )
    return query.order_by(Prospect.quality_score.desc(), Prospect.created_at.desc()).all()


# ---------------------------------------------------------------------------
# Pipeline commercial
# ---------------------------------------------------------------------------
def ensure_default_stages(db: Session) -> None:
    if db.query(PipelineStage).count() == 0:
        for order, (name, probability, is_won, is_lost) in enumerate(DEFAULT_STAGES):
            db.add(
                PipelineStage(
                    name=name,
                    display_order=order,
                    probability=probability,
                    is_won=is_won,
                    is_lost=is_lost,
                )
            )
        db.commit()


def list_stages(db: Session, include_inactive: bool = False) -> List[PipelineStage]:
    ensure_default_stages(db)
    query = db.query(PipelineStage)
    if not include_inactive:
        query = query.filter(PipelineStage.is_active == True)  # noqa: E712
    return query.order_by(PipelineStage.display_order).all()


def create_stage(db: Session, data) -> PipelineStage:
    stage = PipelineStage(**data.model_dump())
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return stage


def update_stage(db: Session, stage_id: int, data) -> PipelineStage:
    stage = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first()
    if not stage:
        raise ValueError("Étape non trouvée")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(stage, field, value)
    db.commit()
    db.refresh(stage)
    return stage


def create_deal(db: Session, data) -> PipelineDeal:
    prospect = db.query(Prospect).filter(Prospect.id == data.prospect_id).first()
    if not prospect:
        raise ValueError("Prospect non trouvé")
    stages = list_stages(db)
    if not stages:
        raise ValueError("Pipeline non configuré")
    stage = stages[0]
    if data.property_id:
        if not db.query(Property).filter(Property.id == data.property_id).first():
            raise ValueError("Bien non trouvé")
    deal = PipelineDeal(
        reference=generate_reference("AFF"),
        stage_id=stage.id,
        assigned_agent=data.assigned_agent or prospect.assigned_agent,
        **data.model_dump(exclude={"assigned_agent"}),
    )
    if deal.probability is None:
        deal.probability = stage.probability
    db.add(deal)
    db.flush()
    db.add(
        DealStageHistory(
            deal_id=deal.id, to_stage_id=stage.id, comment="Création du dossier", changed_by=deal.assigned_agent
        )
    )
    compute_quality_score(db, prospect)
    db.commit()
    db.refresh(deal)
    return deal


def update_deal(db: Session, deal_id: int, data) -> PipelineDeal:
    deal = db.query(PipelineDeal).filter(PipelineDeal.id == deal_id).first()
    if not deal:
        raise ValueError("Dossier non trouvé")
    payload = data.model_dump(exclude_unset=True)
    if "property_id" in payload and payload["property_id"]:
        if not db.query(Property).filter(Property.id == payload["property_id"]).first():
            raise ValueError("Bien non trouvé")
    for field, value in payload.items():
        setattr(deal, field, value)
    db.commit()
    db.refresh(deal)
    return deal


def move_deal_to_stage(db: Session, deal_id: int, data) -> PipelineDeal:
    deal = db.query(PipelineDeal).filter(PipelineDeal.id == deal_id).first()
    if not deal:
        raise ValueError("Dossier non trouvé")
    stage = db.query(PipelineStage).filter(PipelineStage.id == data.stage_id).first()
    if not stage:
        raise ValueError("Étape non trouvée")
    previous_stage_id = deal.stage_id
    deal.stage_id = stage.id
    deal.probability = stage.probability
    if stage.is_won:
        deal.status = DealStatus.WON
        deal.actual_close_date = date.today()
        deal.closed_at = _now()
        if deal.prospect:
            deal.prospect.status = ProspectStatus.CONVERTED
            deal.prospect.converted_at = _now()
    elif stage.is_lost:
        deal.status = DealStatus.LOST
        deal.actual_close_date = date.today()
        deal.closed_at = _now()
        if data.lost_reason:
            deal.lost_reason = data.lost_reason
    else:
        deal.status = DealStatus.OPEN
    db.add(
        DealStageHistory(
            deal_id=deal.id,
            from_stage_id=previous_stage_id,
            to_stage_id=stage.id,
            comment=data.comment,
            changed_by=data.changed_by,
        )
    )
    if deal.prospect:
        compute_quality_score(db, deal.prospect)
    db.commit()
    db.refresh(deal)
    return deal


def kanban_view(db: Session, agent: Optional[str] = None) -> Dict:
    stages = list_stages(db)
    query = db.query(PipelineDeal).filter(PipelineDeal.status == DealStatus.OPEN)
    if agent:
        query = query.filter(PipelineDeal.assigned_agent == agent)
    deals = query.all()
    columns = []
    for stage in stages:
        stage_deals = [d for d in deals if d.stage_id == stage.id]
        columns.append(
            {
                "stage": _stage_view(stage),
                "deals": [_deal_summary(d) for d in stage_deals],
                "count": len(stage_deals),
                "total_value": sum(d.estimated_value or 0 for d in stage_deals),
                "weighted_value": sum(
                    (d.estimated_value or 0) * ((d.probability if d.probability is not None else stage.probability) or 0)
                    for d in stage_deals
                ),
            }
        )
    return {
        "columns": columns,
        "totals": {
            "open_deals": len(deals),
            "total_value": sum(d.estimated_value or 0 for d in deals),
            "weighted_value": sum(
                (d.estimated_value or 0) * ((d.probability if d.probability is not None else 0) or 0)
                for d in deals
            ),
        },
    }


def _stage_view(stage: PipelineStage) -> Dict:
    return {
        "id": stage.id,
        "name": stage.name,
        "display_order": stage.display_order,
        "probability": stage.probability,
        "color": stage.color,
        "is_won": stage.is_won,
        "is_lost": stage.is_lost,
    }


def _deal_summary(deal: PipelineDeal) -> Dict:
    prospect = deal.prospect
    return {
        "id": deal.id,
        "reference": deal.reference,
        "title": deal.title,
        "deal_type": deal.deal_type,
        "status": deal.status.value if deal.status else None,
        "stage_id": deal.stage_id,
        "stage_name": deal.stage.name if deal.stage else None,
        "probability": deal.probability,
        "estimated_value": deal.estimated_value,
        "expected_commission": deal.expected_commission,
        "expected_close_date": deal.expected_close_date,
        "actual_close_date": deal.actual_close_date,
        "lost_reason": deal.lost_reason,
        "assigned_agent": deal.assigned_agent,
        "prospect": {
            "id": prospect.id,
            "name": f"{prospect.first_name} {prospect.last_name}",
            "type": prospect.prospect_type.value if prospect.prospect_type else None,
            "quality_score": prospect.quality_score,
        }
        if prospect
        else None,
        "property_id": deal.property_id,
    }


# ---------------------------------------------------------------------------
# Disponibilités et visites
# ---------------------------------------------------------------------------
def add_availability(db: Session, property_id: int, data) -> List[PropertyAvailability]:
    if not db.query(Property).filter(Property.id == property_id).first():
        raise ValueError("Bien non trouvé")
    created = []
    for slot in data.slots:
        if slot.start >= slot.end:
            raise ValueError("Créneau invalide : début après fin")
        availability = PropertyAvailability(
            property_id=property_id,
            available_date=data.available_date,
            start_time=slot.start,
            end_time=slot.end,
        )
        db.add(availability)
        created.append(availability)
    db.commit()
    return created


def list_availabilities(
    db: Session, property_id: Optional[int] = None, only_free: bool = False
) -> List[PropertyAvailability]:
    query = db.query(PropertyAvailability)
    if property_id:
        query = query.filter(PropertyAvailability.property_id == property_id)
    if only_free:
        query = query.filter(PropertyAvailability.is_booked == False)  # noqa: E712
    return query.order_by(PropertyAvailability.available_date, PropertyAvailability.start_time).all()


def create_visit(db: Session, data) -> Visit:
    property_ = db.query(Property).filter(Property.id == data.property_id).first()
    if not property_:
        raise ValueError("Bien non trouvé")
    prospect = db.query(Prospect).filter(Prospect.id == data.prospect_id).first()
    if not prospect:
        raise ValueError("Prospect non trouvé")
    if data.start_time >= data.end_time:
        raise ValueError("Créneau invalide : début après fin")

    availability = None
    if data.availability_id:
        availability = (
            db.query(PropertyAvailability).filter(PropertyAvailability.id == data.availability_id).first()
        )
        if not availability:
            raise ValueError("Créneau de disponibilité non trouvé")
        if availability.is_booked:
            raise ValueError("Créneau déjà réservé")
        if availability.available_date != data.scheduled_date:
            raise ValueError("Le créneau ne correspond pas à la date demandée")

    # Conflit : autre visite non annulée sur le même bien / créneau
    conflicting = (
        db.query(Visit)
        .filter(
            Visit.property_id == data.property_id,
            Visit.scheduled_date == data.scheduled_date,
            Visit.start_time < data.end_time,
            Visit.end_time > data.start_time,
            Visit.status.in_([VisitStatus.SCHEDULED, VisitStatus.CONFIRMED]),
        )
        .first()
    )
    if conflicting:
        raise ValueError("Un autre visite est déjà programmée sur ce créneau")

    visit = Visit(
        reference=generate_reference("VIS"),
        availability_id=data.availability_id,
        assigned_agent=data.assigned_agent or prospect.assigned_agent,
        **data.model_dump(exclude={"availability_id", "assigned_agent"}),
    )
    if visit.auto_confirm:
        visit.status = VisitStatus.CONFIRMED
        visit.confirmed_at = _now()
    db.add(visit)
    db.flush()
    if availability:
        availability.is_booked = True
        availability.visit_id = visit.id
    if prospect.status == ProspectStatus.DORMANT:
        prospect.status = ProspectStatus.ACTIVE
    prospect.last_contact_at = _now()
    compute_quality_score(db, prospect)
    db.commit()
    db.refresh(visit)
    notify(
        db,
        "Visite programmée",
        f"Visite de « {property_.title} » avec {prospect.first_name} {prospect.last_name} "
        f"le {data.scheduled_date.strftime('%d/%m/%Y')} à {data.start_time}.",
        recipient=visit.assigned_agent,
        type_="visite",
        link=f"/crm/visits/{visit.id}",
    )
    db.commit()
    return visit


def confirm_visit(db: Session, visit_id: int) -> Visit:
    visit = _visit_or_404(db, visit_id)
    if visit.status not in (VisitStatus.SCHEDULED, VisitStatus.CONFIRMED):
        raise ValueError("Seule une visite planifiée peut être confirmée")
    visit.status = VisitStatus.CONFIRMED
    visit.confirmed_at = _now()
    db.commit()
    db.refresh(visit)
    return visit


def cancel_visit(db: Session, visit_id: int, reason: Optional[str]) -> Visit:
    visit = _visit_or_404(db, visit_id)
    if visit.status in (VisitStatus.COMPLETED, VisitStatus.CANCELLED):
        raise ValueError("Visite déjà terminée ou annulée")
    visit.status = VisitStatus.CANCELLED
    visit.cancelled_reason = reason
    if visit.availability_id:
        availability = (
            db.query(PropertyAvailability).filter(PropertyAvailability.id == visit.availability_id).first()
        )
        if availability:
            availability.is_booked = False
            availability.visit_id = None
    db.commit()
    db.refresh(visit)
    return visit


def complete_visit(db: Session, visit_id: int) -> Visit:
    visit = _visit_or_404(db, visit_id)
    visit.status = VisitStatus.COMPLETED
    visit.completed_at = _now()
    if visit.prospect:
        compute_quality_score(db, visit.prospect)
    db.commit()
    db.refresh(visit)
    return visit


def send_visit_reminders(db: Session, visit_id: int, channels: List[str]) -> Dict:
    """Enregistre l'envoi des rappels (email + SMS).

    Les canaux externes ne sont pas simulés : chaque envoi est journalisé
    avec son destinataire, prêt à être branché sur un prestataire.
    """
    visit = _visit_or_404(db, visit_id)
    if visit.status not in (VisitStatus.SCHEDULED, VisitStatus.CONFIRMED):
        raise ValueError("Aucun rappel à envoyer pour une visite non planifiée")
    prospect = visit.prospect
    sent = []
    for channel in channels:
        if channel == "email":
            if not prospect.email:
                continue
            db.add(VisitReminder(visit_id=visit.id, channel="email", recipient=prospect.email))
            visit.reminder_email_sent_at = _now()
            sent.append({"channel": "email", "recipient": prospect.email})
        elif channel == "sms":
            number = prospect.mobile or prospect.phone
            if not number:
                continue
            db.add(VisitReminder(visit_id=visit.id, channel="sms", recipient=number))
            visit.reminder_sms_sent_at = _now()
            sent.append({"channel": "sms", "recipient": number})
    db.commit()
    return {"visit_id": visit.id, "sent": sent, "count": len(sent)}


def save_visit_report(db: Session, visit_id: int, data) -> VisitReport:
    visit = _visit_or_404(db, visit_id)
    report = db.query(VisitReport).filter(VisitReport.visit_id == visit_id).first()
    payload = data.model_dump(exclude_unset=True)
    if not report:
        report = VisitReport(visit_id=visit_id, **payload)
        db.add(report)
    else:
        for field, value in payload.items():
            setattr(report, field, value)
    if visit.status in (VisitStatus.SCHEDULED, VisitStatus.CONFIRMED):
        visit.status = VisitStatus.COMPLETED
        visit.completed_at = _now()
    if visit.prospect:
        visit.prospect.last_contact_at = _now()
        compute_quality_score(db, visit.prospect)
    db.commit()
    db.refresh(report)
    return report


def save_visitor_feedback(db: Session, visit_id: int, data) -> VisitReport:
    _visit_or_404(db, visit_id)
    report = db.query(VisitReport).filter(VisitReport.visit_id == visit_id).first()
    payload = data.model_dump(exclude_unset=True)
    if not report:
        report = VisitReport(visit_id=visit_id, **payload)
        db.add(report)
    else:
        for field, value in payload.items():
            setattr(report, field, value)
    report.visitor_feedback_at = _now()
    db.commit()
    db.refresh(report)
    return report


def _visit_or_404(db: Session, visit_id: int) -> Visit:
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise ValueError("Visite non trouvée")
    return visit


def agenda_view(db: Session, view: str, reference_date: date, agent: Optional[str] = None) -> Dict:
    """Vue agenda : jour, semaine ou mois."""
    if view == "day":
        start, end = reference_date, reference_date
    elif view == "week":
        start = reference_date - timedelta(days=reference_date.weekday())
        end = start + timedelta(days=6)
    elif view == "month":
        start = reference_date.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1) - timedelta(days=1)
    else:
        raise ValueError("Vue invalide : jour, semaine ou mois")

    query = db.query(Visit).filter(
        Visit.scheduled_date >= start, Visit.scheduled_date <= end
    )
    if agent:
        query = query.filter(Visit.assigned_agent == agent)
    visits = query.order_by(Visit.scheduled_date, Visit.start_time).all()
    by_day: Dict[str, List[Dict]] = {}
    for visit in visits:
        key = visit.scheduled_date.isoformat()
        by_day.setdefault(key, []).append(_visit_view(visit))
    return {
        "view": view,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": by_day,
        "count": len(visits),
    }


def _visit_view(visit: Visit) -> Dict:
    return {
        "id": visit.id,
        "reference": visit.reference,
        "property_id": visit.property_id,
        "property_title": visit.property.title if visit.property else None,
        "prospect_id": visit.prospect_id,
        "prospect_name": f"{visit.prospect.first_name} {visit.prospect.last_name}" if visit.prospect else None,
        "scheduled_date": visit.scheduled_date.isoformat() if visit.scheduled_date else None,
        "start_time": visit.start_time,
        "end_time": visit.end_time,
        "status": visit.status.value if visit.status else None,
        "auto_confirm": visit.auto_confirm,
        "confirmed_at": visit.confirmed_at.isoformat() if visit.confirmed_at else None,
        "completed_at": visit.completed_at.isoformat() if visit.completed_at else None,
        "cancelled_reason": visit.cancelled_reason,
        "assigned_agent": visit.assigned_agent,
        "reminder_email_sent_at": visit.reminder_email_sent_at.isoformat() if visit.reminder_email_sent_at else None,
        "reminder_sms_sent_at": visit.reminder_sms_sent_at.isoformat() if visit.reminder_sms_sent_at else None,
        "notes": visit.notes,
        "has_report": visit.report is not None,
    }


# ---------------------------------------------------------------------------
# Matching automatique
# ---------------------------------------------------------------------------
def match_score(prospect: Prospect, property_: Property) -> Tuple[int, Dict]:
    """Score de correspondance 0-100 entre les critères d'un prospect et un
    bien. Retourne le score et son détail explicable."""
    criteria = prospect.search_criteria or {}
    parts: List[Dict] = []

    # Type de bien (20 pts)
    wanted_types = criteria.get("property_types") or []
    if wanted_types:
        pts = 20 if (property_.type and property_.type.value in wanted_types) else 0
    else:
        pts = 12  # Pas de préférence : correspondance partielle
    parts.append({"criterium": "type_de_bien", "points": pts, "max": 20})

    # Localisation (25 pts)
    cities = [c.lower().strip() for c in (criteria.get("cities") or [])]
    postal_codes = [str(p) for p in (criteria.get("postal_codes") or [])]
    location_pts = 0
    if cities or postal_codes:
        if cities and property_.city and property_.city.lower().strip() in cities:
            location_pts = 15
        if postal_codes and property_.postal_code and property_.postal_code in postal_codes:
            location_pts = 25
        elif cities and property_.city and property_.city.lower().strip() in cities:
            location_pts = 15
    else:
        location_pts = 12
    parts.append({"criterium": "localisation", "points": location_pts, "max": 25})

    # Budget (25 pts)
    price = property_.rent_price if prospect.prospect_type != ProspectType.BUYER else property_.sale_price
    if price is None:
        price = property_.sale_price or property_.rent_price
    budget_pts = 0
    if price is not None:
        budget_min = prospect.budget_min or criteria.get("budget_min")
        budget_max = prospect.budget_max or criteria.get("budget_max")
        if budget_max is None:
            budget_pts = 12
        elif price <= budget_max and (budget_min is None or price >= budget_min):
            budget_pts = 25
        elif price <= budget_max * 1.1:  # Tolérance de 10 %
            budget_pts = 15
        parts.append({"criterium": "budget", "points": budget_pts, "max": 25, "prix": price})
    else:
        parts.append({"criterium": "budget", "points": 0, "max": 25})

    # Surface (15 pts)
    surface = property_.living_area or property_.total_area
    surface_pts = 0
    if surface is not None:
        min_surface = criteria.get("min_surface")
        max_surface = criteria.get("max_surface")
        if (min_surface is None or surface >= min_surface) and (max_surface is None or surface <= max_surface):
            surface_pts = 15
        elif min_surface and surface >= min_surface * 0.9:
            surface_pts = 8
        parts.append({"criterium": "surface", "points": surface_pts, "max": 15, "surface": surface})
    else:
        parts.append({"criterium": "surface", "points": 8, "max": 15})

    # Pièces (15 pts)
    rooms_pts = 8
    if property_.rooms is not None:
        min_rooms = criteria.get("min_rooms")
        max_rooms = criteria.get("max_rooms")
        if (min_rooms is None or property_.rooms >= min_rooms) and (max_rooms is None or property_.rooms <= max_rooms):
            rooms_pts = 15
        elif min_rooms and property_.rooms >= min_rooms - 1:
            rooms_pts = 8
    parts.append({"criterium": "pieces", "points": rooms_pts, "max": 15})

    total = sum(p["points"] for p in parts)
    return total, {"parts": parts, "total": total}


def run_matching(
    db: Session, prospect_id: Optional[int], min_score: int, notify_agent: bool
) -> Dict:
    prospects = (
        db.query(Prospect).filter(Prospect.id == prospect_id, Prospect.status == ProspectStatus.ACTIVE).all()
        if prospect_id
        else db.query(Prospect).filter(Prospect.status == ProspectStatus.ACTIVE).all()
    )
    # Biens susceptibles d'être proposés : disponibles ou à vendre
    properties = (
        db.query(Property)
        .filter(
            Property.is_active == True,  # noqa: E712
            Property.status.in_([PropertyStatus.AVAILABLE, PropertyStatus.FOR_SALE]),
        )
        .all()
    )
    created, updated = [], []
    for prospect in prospects:
        existing = {
            m.property_id: m
            for m in db.query(MatchAlert).filter(MatchAlert.prospect_id == prospect.id).all()
        }
        for property_ in properties:
            score, detail = match_score(prospect, property_)
            if score < min_score:
                continue
            alert = existing.get(property_.id)
            if alert:
                if alert.status == "ecartee":
                    continue
                changed = alert.score != score
                alert.score = score
                alert.detail = detail
                if changed:
                    updated.append(alert)
                continue
            alert = MatchAlert(
                prospect_id=prospect.id,
                property_id=property_.id,
                score=score,
                detail=detail,
            )
            db.add(alert)
            created.append(alert)
            if notify_agent:
                notify(
                    db,
                    "Bien correspondant à un prospect",
                    f"« {property_.title} » correspond à {score} % aux critères de "
                    f"{prospect.first_name} {prospect.last_name}.",
                    recipient=prospect.assigned_agent,
                    type_="matching",
                    link=f"/crm/prospects/{prospect.id}",
                )
    db.commit()
    return {
        "prospects_scanned": len(prospects),
        "properties_scanned": len(properties),
        "alerts_created": len(created),
        "alerts_updated": len(updated),
        "alerts": [
            {
                "id": a.id,
                "prospect_id": a.prospect_id,
                "property_id": a.property_id,
                "property_title": a.property.title if a.property else None,
                "score": a.score,
                "status": a.status,
            }
            for a in sorted(created, key=lambda x: -x.score)[:50]
        ],
    }


def suggest_properties(db: Session, prospect_id: int, limit: int = 10) -> List[Dict]:
    """Suggestion de biens classés par score pour un prospect."""
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise ValueError("Prospect non trouvé")
    properties = (
        db.query(Property)
        .filter(
            Property.is_active == True,  # noqa: E712
            Property.status.in_([PropertyStatus.AVAILABLE, PropertyStatus.FOR_SALE]),
        )
        .all()
    )
    scored = []
    for property_ in properties:
        score, detail = match_score(prospect, property_)
        scored.append(
            {
                "property_id": property_.id,
                "reference": property_.reference,
                "title": property_.title,
                "city": property_.city,
                "postal_code": property_.postal_code,
                "type": property_.type.value if property_.type else None,
                "rent_price": property_.rent_price,
                "sale_price": property_.sale_price,
                "living_area": property_.living_area,
                "rooms": property_.rooms,
                "score": score,
                "detail": detail,
            }
        )
    scored.sort(key=lambda s: -s["score"])
    return scored[:limit]


def notify_match(db: Session, match_id: int, also_email_prospect: bool) -> MatchAlert:
    alert = db.query(MatchAlert).filter(MatchAlert.id == match_id).first()
    if not alert:
        raise ValueError("Correspondance non trouvée")
    if alert.status == "ecartee":
        raise ValueError("Correspondance écartée")
    prospect, property_ = alert.prospect, alert.property
    notify(
        db,
        "Suggestion de bien envoyée",
        f"« {property_.title} » ({property_.city}) a été suggéré à "
        f"{prospect.first_name} {prospect.last_name}.",
        recipient=prospect.assigned_agent,
        type_="matching",
        link=f"/crm/prospects/{prospect.id}",
    )
    if also_email_prospect and prospect.email:
        # L'envoi réel vers le prospect dépend d'un prestataire externe :
        # il est journalisé comme notification dédiée, prêt à être branché.
        notify(
            db,
            "Envoi de la suggestion au prospect",
            f"Annonce « {property_.title} » envoyée par email à {prospect.email}.",
            recipient=prospect.assigned_agent,
            type_="matching",
        )
    alert.status = "notifiee"
    alert.notified_at = _now()
    db.commit()
    db.refresh(alert)
    return alert


def dismiss_match(db: Session, match_id: int, reason: Optional[str]) -> MatchAlert:
    alert = db.query(MatchAlert).filter(MatchAlert.id == match_id).first()
    if not alert:
        raise ValueError("Correspondance non trouvée")
    alert.status = "ecartee"
    alert.dismissed_reason = reason
    db.commit()
    db.refresh(alert)
    return alert


def list_matches(
    db: Session,
    prospect_id: Optional[int] = None,
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    min_score: Optional[int] = None,
) -> List[MatchAlert]:
    query = db.query(MatchAlert)
    if prospect_id:
        query = query.filter(MatchAlert.prospect_id == prospect_id)
    if property_id:
        query = query.filter(MatchAlert.property_id == property_id)
    if status:
        query = query.filter(MatchAlert.status == status)
    if min_score is not None:
        query = query.filter(MatchAlert.score >= min_score)
    return query.order_by(MatchAlert.score.desc()).all()


# ---------------------------------------------------------------------------
# Annonces et diffusion multi-portails
# ---------------------------------------------------------------------------
SUPPORTED_PORTALS = [p.value for p in Portal]


def create_listing_template(db: Session, data) -> ListingTemplate:
    template = ListingTemplate(**data.model_dump())
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def list_listing_templates(db: Session, active_only: bool = True) -> List[Dict]:
    query = db.query(ListingTemplate)
    if active_only:
        query = query.filter(ListingTemplate.is_active == True)  # noqa: E712
    templates = query.order_by(ListingTemplate.name).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "property_type": t.property_type,
            "language": t.language,
            "title_template": t.title_template,
            "description_template": t.description_template,
            "is_active": t.is_active,
        }
        for t in templates
    ]


def _fmt_number(value) -> str:
    if value is None:
        return ""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:g}"


def render_template(template: ListingTemplate, property_: Property, price: Optional[float]) -> Dict[str, str]:
    variables = {
        "titre": property_.title,
        "ville": property_.city or "",
        "code_postal": property_.postal_code or "",
        "adresse": property_.address or "",
        "surface": _fmt_number(property_.living_area or property_.total_area),
        "pieces": _fmt_number(property_.rooms),
        "chambres": _fmt_number(property_.bedrooms),
        "type": property_.type.value if property_.type else "",
        "prix": f"{price or 0:,.0f} €".replace(",", " "),
    }
    title = template.title_template or "{titre} — {ville}"
    description = template.description_template or "{type} de {surface} m² à {ville}."

    def render(text: str) -> str:
        for key, value in variables.items():
            text = text.replace("{" + key + "}", value)
        return text

    return {"title": render(title), "description": render(description)}


def create_listing(db: Session, data) -> Listing:
    property_ = db.query(Property).filter(Property.id == data.property_id).first()
    if not property_:
        raise ValueError("Bien non trouvé")
    price = data.price
    if price is None:
        price = property_.sale_price if data.listing_type == "vente" else property_.rent_price
    title, description = data.title, data.description
    if data.template_id:
        template = (
            db.query(ListingTemplate).filter(ListingTemplate.id == data.template_id).first()
        )
        if not template:
            raise ValueError("Modèle d'annonce non trouvé")
        rendered = render_template(template, property_, price)
        title = title or rendered["title"]
        description = description or rendered["description"]
    listing = Listing(
        reference=generate_reference("ANN"),
        price=price,
        title=title,
        description=description,
        **data.model_dump(exclude={"title", "description", "price"}),
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def update_listing(db: Session, listing_id: int, data) -> Listing:
    listing = _listing_or_404(db, listing_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(listing, field, value)
    db.commit()
    db.refresh(listing)
    return listing


def publish_listing(db: Session, listing_id: int, portals: List[Portal], external_references: Optional[Dict[str, str]]) -> Dict:
    """Publication multi-portails : chaque diffusion est journalisée avec son
    statut. Les portails ne proposent pas d'API publique universelle : la
    publication est enregistrée comme prête à diffuser, avec sa référence
    externe le cas échéant."""
    listing = _listing_or_404(db, listing_id)
    if listing.status == ListingStatus.WITHDRAWN:
        raise ValueError("Annonce retirée : créez une nouvelle annonce")
    results = []
    for portal in portals:
        publication = (
            db.query(PortalPublication)
            .filter(PortalPublication.listing_id == listing_id, PortalPublication.portal == portal)
            .first()
        )
        if publication and publication.status.value in ("publiee", "en_pause"):
            results.append({"portal": portal.value, "status": "deja_publiee"})
            continue
        if not publication:
            publication = PortalPublication(listing_id=listing_id, portal=portal)
            db.add(publication)
        publication.status = "publiee"  # type: ignore[assignment]
        publication.published_at = _now()
        publication.last_sync_at = _now()
        publication.message = "Annonce déposée sur le portail"
        if external_references and portal.value in external_references:
            publication.external_reference = external_references[portal.value]
        results.append({"portal": portal.value, "status": "publiee"})
    listing.status = ListingStatus.PUBLISHED
    if not listing.published_at:
        listing.published_at = _now()
    db.commit()
    return {
        "listing_id": listing_id,
        "reference": listing.reference,
        "status": listing.status.value,
        "portals": results,
        "published_count": len([r for r in results if r["status"] == "publiee"]),
    }


def unpublish_listing(db: Session, listing_id: int, portal: Optional[Portal]) -> Dict:
    listing = _listing_or_404(db, listing_id)
    query = db.query(PortalPublication).filter(PortalPublication.listing_id == listing_id)
    if portal:
        query = query.filter(PortalPublication.portal == portal)
    publications = query.all()
    if not publications:
        raise ValueError("Aucune diffusion à retirer")
    for publication in publications:
        publication.status = "retiree"  # type: ignore[assignment]
        publication.removed_at = _now()
        publication.last_sync_at = _now()
    db.flush()
    remaining = (
        db.query(PortalPublication)
        .filter(
            PortalPublication.listing_id == listing_id,
            PortalPublication.status == PublicationStatus.PUBLISHED,
        )
        .count()
    )
    if remaining == 0:
        listing.status = ListingStatus.WITHDRAWN
        listing.withdrawn_at = _now()
    else:
        listing.status = ListingStatus.PAUSED
    db.commit()
    return {
        "listing_id": listing_id,
        "status": listing.status.value,
        "removed": [p.portal.value for p in publications],
    }


def portal_sync_status(db: Session, listing_id: int) -> List[Dict]:
    _listing_or_404(db, listing_id)
    publications = (
        db.query(PortalPublication)
        .filter(PortalPublication.listing_id == listing_id)
        .all()
    )
    return [
        {
            "portal": p.portal.value,
            "status": p.status.value,
            "external_reference": p.external_reference,
            "published_at": p.published_at.isoformat() if p.published_at else None,
            "last_sync_at": p.last_sync_at.isoformat() if p.last_sync_at else None,
            "message": p.message,
        }
        for p in publications
    ]


def upload_listing_stats(db: Session, listing_id: int, entries) -> Dict:
    """Enregistre les statistiques d'une annonce remontées par les portails."""
    _listing_or_404(db, listing_id)
    saved = 0
    for entry in entries.entries:
        existing = (
            db.query(ListingDailyStat)
            .filter(
                ListingDailyStat.listing_id == listing_id,
                ListingDailyStat.stat_date == entry.stat_date,
                ListingDailyStat.portal == entry.portal,
            )
            .first()
        )
        if existing:
            existing.views = entry.views
            existing.contacts = entry.contacts
            existing.favorites = entry.favorites
            existing.leads = entry.leads
        else:
            db.add(
                ListingDailyStat(
                    listing_id=listing_id,
                    portal=entry.portal,
                    stat_date=entry.stat_date,
                    views=entry.views,
                    contacts=entry.contacts,
                    favorites=entry.favorites,
                    leads=entry.leads,
                )
            )
        saved += 1
    db.commit()
    return listing_stats(db, listing_id)


def listing_stats(db: Session, listing_id: int) -> Dict:
    """Statistiques d'une annonce : vues, contacts, conversion (globale et par
    portail)."""
    listing = _listing_or_404(db, listing_id)
    stats = db.query(ListingDailyStat).filter(ListingDailyStat.listing_id == listing_id).all()
    totals = {"views": 0, "contacts": 0, "favorites": 0, "leads": 0}
    by_portal: Dict[str, Dict[str, int]] = {}
    daily: Dict[str, Dict[str, int]] = {}
    for stat in stats:
        key = stat.portal.value if stat.portal else "toutes_destinations"
        bucket = by_portal.setdefault(key, {"views": 0, "contacts": 0, "favorites": 0, "leads": 0})
        for metric in totals:
            value = getattr(stat, metric) or 0
            totals[metric] += value
            bucket[metric] += value
        day = daily.setdefault(
            stat.stat_date.isoformat(), {"views": 0, "contacts": 0, "favorites": 0, "leads": 0}
        )
        for metric in day:
            day[metric] += getattr(stat, metric) or 0
    conversion_rate = round(totals["contacts"] / totals["views"] * 100, 2) if totals["views"] else 0.0
    return {
        "listing_id": listing_id,
        "reference": listing.reference,
        "title": listing.title,
        "status": listing.status.value,
        "totals": {**totals, "conversion_rate_pct": conversion_rate},
        "by_portal": by_portal,
        "daily": dict(sorted(daily.items())),
        "publications": portal_sync_status(db, listing_id),
    }


def centralized_listings_overview(db: Session) -> Dict:
    listings = db.query(Listing).all()
    overview = []
    for listing in listings:
        stats = listing_stats(db, listing.id)
        overview.append(
            {
                "listing_id": listing.id,
                "reference": listing.reference,
                "property_id": listing.property_id,
                "title": listing.title,
                "status": listing.status.value,
                "portals": [p["portal"] for p in stats["publications"]],
                "views": stats["totals"]["views"],
                "contacts": stats["totals"]["contacts"],
                "conversion_rate_pct": stats["totals"]["conversion_rate_pct"],
            }
        )
    totals_views = sum(o["views"] for o in overview)
    totals_contacts = sum(o["contacts"] for o in overview)
    return {
        "listings": overview,
        "count": len(overview),
        "totals": {
            "views": totals_views,
            "contacts": totals_contacts,
            "conversion_rate_pct": round(totals_contacts / totals_views * 100, 2) if totals_views else 0.0,
        },
    }


def _listing_or_404(db: Session, listing_id: int) -> Listing:
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise ValueError("Annonce non trouvée")
    return listing


# ---------------------------------------------------------------------------
# Transactions (vente)
# ---------------------------------------------------------------------------
def create_offer(db: Session, data) -> PurchaseOffer:
    property_ = db.query(Property).filter(Property.id == data.property_id).first()
    if not property_:
        raise ValueError("Bien non trouvé")
    if data.prospect_id and not db.query(Prospect).filter(Prospect.id == data.prospect_id).first():
        raise ValueError("Prospect non trouvé")
    offer = PurchaseOffer(reference=generate_reference("OFF"), **data.model_dump())
    db.add(offer)
    db.flush()
    if offer.prospect:
        compute_quality_score(db, offer.prospect)
    notify(
        db,
        "Offre d'achat reçue",
        f"Offre de {offer.amount:,.0f} € sur « {property_.title} ».".replace(",", " "),
        type_="transaction",
        link=f"/crm/offers/{offer.id}",
    )
    db.commit()
    db.refresh(offer)
    return offer


def decide_offer(db: Session, offer_id: int, decision: str, note: Optional[str], open_transaction: bool):
    offer = db.query(PurchaseOffer).filter(PurchaseOffer.id == offer_id).first()
    if not offer:
        raise ValueError("Offre non trouvée")
    if offer.status != "en_attente":
        raise ValueError("Offre déjà traitée")
    if decision == "acceptee":
        offer.status = "acceptee"  # type: ignore[assignment]
        if open_transaction:
            transaction = create_transaction(
                db,
                SaleTransactionCreate(**_transaction_payload_from_offer(offer)),
            )
            offer.response_note = note
            db.commit()
            return offer, transaction
    elif decision == "refusee":
        offer.status = "refusee"  # type: ignore[assignment]
    elif decision == "retiree":
        offer.status = "retiree"  # type: ignore[assignment]
    else:
        raise ValueError("Décision invalide")
    offer.response_note = note
    db.commit()
    db.refresh(offer)
    return offer, None


def _transaction_payload_from_offer(offer: PurchaseOffer) -> Dict:
    buyer = (
        f"{offer.prospect.first_name} {offer.prospect.last_name}" if offer.prospect else None
    )
    return {
        "property_id": offer.property_id,
        "offer_id": offer.id,
        "prospect_id": offer.prospect_id,
        "deal_id": offer.deal_id,
        "buyer_name": buyer,
        "sale_price": offer.amount,
    }


def create_transaction(db: Session, data) -> SaleTransaction:
    property_ = db.query(Property).filter(Property.id == data.property_id).first()
    if not property_:
        raise ValueError("Bien non trouvé")
    payload = data.model_dump()
    transaction = SaleTransaction(
        reference=generate_reference("VTE"),
        stage=TransactionStage.OFFER,
        commission_amount=round(data.sale_price * data.commission_rate / 100 + data.commission_fixed, 2),
        commission_total_ttc=round(
            (data.sale_price * data.commission_rate / 100 + data.commission_fixed)
            * (1 + data.vat_rate / 100),
            2,
        ),
        **payload,
    )
    db.add(transaction)
    db.flush()
    db.add(
        TransactionEvent(
            transaction_id=transaction.id,
            event_type="autre",
            label="Dossier de vente ouvert",
            event_date=date.today(),
        )
    )
    db.commit()
    db.refresh(transaction)
    return transaction


def sign_compromis(db: Session, transaction_id: int, data) -> SaleTransaction:
    transaction = _transaction_or_404(db, transaction_id)
    if transaction.stage not in (TransactionStage.OFFER, TransactionStage.COMPROMIS):
        raise ValueError("Le compromis ne peut être signé à cette étape")
    payload = data.model_dump(exclude_unset=True, exclude={"compromis_date"})
    for field, value in payload.items():
        setattr(transaction, field, value)
    transaction.compromis_date = data.compromis_date or date.today()
    transaction.compromis_signed_at = data.compromis_date or date.today()
    transaction.stage = TransactionStage.COMPROMIS
    db.add(
        TransactionEvent(
            transaction_id=transaction.id,
            event_type="signature",
            label="Compromis de vente signé",
            event_date=transaction.compromis_signed_at,
            notes=f"Notaire : {transaction.notary_name}" if transaction.notary_name else None,
        )
    )
    db.commit()
    db.refresh(transaction)
    return transaction


def add_condition(db: Session, transaction_id: int, data) -> SuspensiveCondition:
    transaction = _transaction_or_404(db, transaction_id)
    condition = SuspensiveCondition(transaction_id=transaction_id, **data.model_dump())
    db.add(condition)
    if transaction.stage == TransactionStage.COMPROMIS:
        transaction.stage = TransactionStage.SUSPENSIVE
    db.add(
        TransactionEvent(
            transaction_id=transaction.id,
            event_type="condition",
            label=f"Condition suspensive ajoutée : {data.label}",
            event_date=date.today(),
        )
    )
    db.commit()
    db.refresh(condition)
    return condition


def decide_condition(db: Session, condition_id: int, decision: str, notes: Optional[str]) -> SuspensiveCondition:
    from app.models.crm import ConditionStatus

    condition = (
        db.query(SuspensiveCondition).filter(SuspensiveCondition.id == condition_id).first()
    )
    if not condition:
        raise ValueError("Condition non trouvée")
    if condition.status != ConditionStatus.PENDING:
        raise ValueError("Condition déjà traitée")
    mapping = {
        "satisfaite": ConditionStatus.SATISFIED,
        "levee": ConditionStatus.WAIVED,
        "echouee": ConditionStatus.FAILED,
    }
    if decision not in mapping:
        raise ValueError("Décision invalide")
    condition.status = mapping[decision]
    condition.satisfied_at = _now() if decision != "echouee" else None
    condition.notes = notes or condition.notes
    transaction = condition.transaction
    if transaction:
        db.add(
            TransactionEvent(
                transaction_id=transaction.id,
                event_type="condition",
                label=f"Condition « {condition.label} » : {decision}",
                event_date=date.today(),
                notes=notes,
            )
        )
        if decision == "echouee":
            transaction.stage = TransactionStage.CANCELLED
            transaction.cancelled_reason = f"Condition suspensive échouée : {condition.label}"
    db.commit()
    db.refresh(condition)
    return condition


def update_notary(db: Session, transaction_id: int, data, event_label: Optional[str] = None) -> SaleTransaction:
    transaction = _transaction_or_404(db, transaction_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(transaction, field, value)
    if event_label:
        db.add(
            TransactionEvent(
                transaction_id=transaction.id,
                event_type="notaire",
                label=event_label,
                event_date=date.today(),
            )
        )
    db.commit()
    db.refresh(transaction)
    return transaction


def sign_acte(db: Session, transaction_id: int, data) -> Dict:
    """Signature de l'acte authentique : calcule la commission agence HT/TTC
    et clôture le dossier."""
    transaction = _transaction_or_404(db, transaction_id)
    if transaction.stage in (TransactionStage.CLOSED, TransactionStage.CANCELLED):
        raise ValueError("Dossier déjà clôturé")
    pending = [
        c for c in transaction.conditions
        if c.status.value == "en_attente"
    ]
    if pending:
        raise ValueError(
            "Des conditions suspensives sont encore en attente : "
            + ", ".join(c.label for c in pending)
        )
    rate = data.commission_rate if data.commission_rate is not None else transaction.commission_rate
    fixed = data.commission_fixed if data.commission_fixed is not None else transaction.commission_fixed
    amount = round(transaction.sale_price * rate / 100 + fixed, 2)
    total_ttc = round(amount * (1 + (transaction.vat_rate or 0) / 100), 2)

    transaction.commission_rate = rate
    transaction.commission_fixed = fixed
    transaction.commission_amount = amount
    transaction.commission_total_ttc = total_ttc
    transaction.acte_signed_at = data.acte_signed_at
    transaction.effective_sale_date = data.effective_sale_date or data.acte_signed_at
    transaction.stage = TransactionStage.CLOSED
    transaction.closed_at = _now()
    if transaction.property:
        transaction.property.status = PropertyStatus.WITHDRAWN
    if transaction.deal_id:
        deal = db.query(PipelineDeal).filter(PipelineDeal.id == transaction.deal_id).first()
        if deal:
            won_stage = (
                db.query(PipelineStage)
                .filter(PipelineStage.is_won == True)  # noqa: E712
                .order_by(PipelineStage.display_order)
                .first()
            )
            if won_stage:
                deal.stage_id = won_stage.id
                deal.status = DealStatus.WON
                deal.actual_close_date = data.acte_signed_at
                deal.closed_at = _now()
    db.add(
        TransactionEvent(
            transaction_id=transaction.id,
            event_type="signature",
            label="Acte authentique signé",
            event_date=data.acte_signed_at,
            notes=f"Commission : {amount:,.2f} € HT / {total_ttc:,.2f} € TTC".replace(",", " "),
        )
    )
    db.commit()
    db.refresh(transaction)
    return {
        "transaction": transaction,
        "commission_ht": amount,
        "commission_ttc": total_ttc,
    }


def get_transaction(db: Session, transaction_id: int) -> SaleTransaction:
    return _transaction_or_404(db, transaction_id)


def add_transaction_event(db: Session, transaction_id: int, data) -> TransactionEvent:
    _transaction_or_404(db, transaction_id)
    event = TransactionEvent(transaction_id=transaction_id, **data.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _transaction_or_404(db: Session, transaction_id: int) -> SaleTransaction:
    transaction = (
        db.query(SaleTransaction).filter(SaleTransaction.id == transaction_id).first()
    )
    if not transaction:
        raise ValueError("Dossier de vente non trouvé")
    return transaction


# ---------------------------------------------------------------------------
# Notifications CRM
# ---------------------------------------------------------------------------
def list_notifications(db: Session, unread_only: bool = False) -> List[CrmNotification]:
    query = db.query(CrmNotification)
    if unread_only:
        query = query.filter(CrmNotification.is_read == False)  # noqa: E712
    return query.order_by(CrmNotification.created_at.desc()).limit(200).all()


def mark_notification_read(db: Session, notification_id: int) -> CrmNotification:
    notification = (
        db.query(CrmNotification).filter(CrmNotification.id == notification_id).first()
    )
    if not notification:
        raise ValueError("Notification non trouvée")
    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return notification


# ---------------------------------------------------------------------------
# Suivi de la performance
# ---------------------------------------------------------------------------
def agent_performance(db: Session, date_from: Optional[date], date_to: Optional[date]) -> Dict:
    """KPIs par agent et globaux : dossiers gagnés, taux de conversion,
    commissions, ratio visites/signature, délai moyen de conclusion et
    chiffre d'affaires commercial."""
    date_to = date_to or date.today()
    date_from = date_from or date_to - timedelta(days=365)

    deals = (
        db.query(PipelineDeal)
        .filter(PipelineDeal.created_at >= datetime.combine(date_from, datetime.min.time()))
        .all()
    )
    visits = (
        db.query(Visit)
        .filter(Visit.scheduled_date >= date_from, Visit.scheduled_date <= date_to)
        .all()
    )
    transactions = (
        db.query(SaleTransaction)
        .filter(SaleTransaction.acte_signed_at >= date_from, SaleTransaction.acte_signed_at <= date_to)
        .all()
    )
    leases_signed = (
        db.query(Lease)
        .filter(Lease.signed_at >= datetime.combine(date_from, datetime.min.time()))
        .count()
    )

    agents: Dict[str, Dict[str, Any]] = {}
    for deal in deals:
        agent = deal.assigned_agent or "(non affecté)"
        stats = agents.setdefault(
            agent,
            {
                "agent": agent,
                "deals_created": 0,
                "deals_won": 0,
                "deals_lost": 0,
                "deals_open": 0,
                "value_won": 0.0,
                "commission_won": 0.0,
                "visits": 0,
                "visits_completed": 0,
                "total_close_days": 0,
                "closes": 0,
            },
        )
        stats["deals_created"] += 1
        if deal.status == DealStatus.WON:
            stats["deals_won"] += 1
            stats["value_won"] += deal.estimated_value or 0
            stats["commission_won"] += deal.expected_commission or 0
            if deal.actual_close_date:
                created = deal.created_at.date() if deal.created_at else deal.actual_close_date
                stats["total_close_days"] += (deal.actual_close_date - created).days
                stats["closes"] += 1
        elif deal.status == DealStatus.LOST:
            stats["deals_lost"] += 1
        else:
            stats["deals_open"] += 1
    for visit in visits:
        agent = visit.assigned_agent or "(non affecté)"
        stats = agents.setdefault(
            agent,
            {
                "agent": agent,
                "deals_created": 0,
                "deals_won": 0,
                "deals_lost": 0,
                "deals_open": 0,
                "value_won": 0.0,
                "commission_won": 0.0,
                "visits": 0,
                "visits_completed": 0,
                "total_close_days": 0,
                "closes": 0,
            },
        )
        stats["visits"] += 1
        if visit.status == VisitStatus.COMPLETED:
            stats["visits_completed"] += 1

    agent_list = []
    total_commission = 0.0
    for agent, stats in agents.items():
        won = stats["deals_won"]
        entry = {
            "agent": stats["agent"],
            "deals_created": stats["deals_created"],
            "deals_won": won,
            "deals_lost": stats["deals_lost"],
            "deals_open": stats["deals_open"],
            "win_rate_pct": round(won / stats["deals_created"] * 100, 1) if stats["deals_created"] else 0.0,
            "value_won": round(stats["value_won"], 2),
            "commission_won": round(stats["commission_won"], 2),
            "visits": stats["visits"],
            "visits_completed": stats["visits_completed"],
            "visits_per_signature": round(stats["visits_completed"] / won, 2) if won else None,
            "avg_close_days": round(stats["total_close_days"] / stats["closes"]) if stats["closes"] else None,
        }
        total_commission += stats["commission_won"]
        agent_list.append(entry)
    agent_list.sort(key=lambda e: -e["value_won"])

    # Taux d'occupation au jour J (partage avec le module reporting)
    rentable = db.query(Property).filter(
        Property.is_active == True, Property.rent_price != None  # noqa: E712
    ).count()
    occupied = db.query(Lease).filter(Lease.status == LeaseStatus.ACTIVE).count()
    occupancy_rate = round(occupied / rentable * 100, 2) if rentable else 0.0

    commission_ventes = sum(t.commission_total_ttc or 0 for t in transactions)
    return {
        "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
        "agents": agent_list,
        "global": {
            "deals_created": len(deals),
            "deals_won": sum(1 for d in deals if d.status == DealStatus.WON),
            "deals_lost": sum(1 for d in deals if d.status == DealStatus.LOST),
            "deals_open": sum(1 for d in deals if d.status == DealStatus.OPEN),
            "visits": len(visits),
            "visits_completed": sum(1 for v in visits if v.status == VisitStatus.COMPLETED),
            "visits_per_signature": round(
                sum(1 for v in visits if v.status == VisitStatus.COMPLETED) / max(won_total, 1), 2
            )
            if (won_total := sum(1 for d in deals if d.status == DealStatus.WON))
            else None,
            "avg_close_days": round(
                sum(
                    (d.actual_close_date - d.created_at.date()).days
                    for d in deals
                    if d.status == DealStatus.WON and d.actual_close_date and d.created_at
                )
                / max(
                    sum(1 for d in deals if d.status == DealStatus.WON and d.actual_close_date and d.created_at),
                    1,
                )
            )
            if any(d.status == DealStatus.WON and d.actual_close_date and d.created_at for d in deals)
            else None,
            "avg_rental_delay_days": average_rental_delay(db),
            "sales_closed": len(transactions),
            "sales_revenue": round(sum(t.sale_price or 0 for t in transactions), 2),
            "commission_deals": round(total_commission, 2),
            "commission_sales_ttc": round(commission_ventes, 2),
            "leases_signed": leases_signed,
            "occupancy_rate_pct": occupancy_rate,
        },
    }


def average_rental_delay(db: Session) -> Optional[int]:
    """Délai moyen (en jours) entre la création d'un dossier location et sa
    conclusion (gagnée)."""
    won_deals = (
        db.query(PipelineDeal)
        .filter(PipelineDeal.status == DealStatus.WON, PipelineDeal.deal_type == "location")
        .all()
    )
    delays = [
        (d.actual_close_date - d.created_at.date()).days
        for d in won_deals
        if d.actual_close_date and d.created_at
    ]
    return round(sum(delays) / len(delays)) if delays else None
