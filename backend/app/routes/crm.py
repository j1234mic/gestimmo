"""API du module 8 : CRM et gestion commerciale."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.database import get_db
from app.models.crm import (
    DealStatus,
    Listing,
    OfferStatus,
    PipelineDeal,
    Prospect,
    PurchaseOffer,
    SaleTransaction,
    TransactionStage,
    Visit,
    VisitStatus,
)
from app.schemas.crm import (
    ActeSign,
    AvailabilityDayCreate,
    CompromisSign,
    ConditionDecision,
    DealCreate,
    DealStageChange,
    DealUpdate,
    ListingCreate,
    ListingPublishRequest,
    ListingStatsUpload,
    ListingTemplateCreate,
    ListingUpdate,
    MatchNotificationRequest,
    MatchingScanRequest,
    NotaryUpdate,
    OfferDecision,
    PipelineStageCreate,
    PipelineStageUpdate,
    ProspectAdminUpdate,
    ProspectCreate,
    ProspectUpdate,
    PurchaseOfferCreate,
    ReminderRequest,
    SaleTransactionCreate,
    SuspensiveConditionCreate,
    TransactionEventCreate,
    VisitCancel,
    VisitCreate,
    VisitReportCreate,
    VisitUpdate,
    VisitorFeedbackCreate,
)
from app.services import crm_service

router = APIRouter(prefix="/api/crm", tags=["CRM et gestion commerciale"])


def _prospect_view(prospect) -> dict:
    return {
        "id": prospect.id,
        "reference": prospect.reference,
        "first_name": prospect.first_name,
        "last_name": prospect.last_name,
        "full_name": f"{prospect.first_name} {prospect.last_name}",
        "email": prospect.email,
        "phone": prospect.phone,
        "mobile": prospect.mobile,
        "prospect_type": prospect.prospect_type.value if prospect.prospect_type else None,
        "source": prospect.source.value if prospect.source else None,
        "status": prospect.status.value if prospect.status else None,
        "budget_min": prospect.budget_min,
        "budget_max": prospect.budget_max,
        "search_criteria": prospect.search_criteria or {},
        "quality_score": prospect.quality_score,
        "score_detail": prospect.score_detail or {},
        "assigned_agent": prospect.assigned_agent,
        "notes": prospect.notes,
        "last_contact_at": prospect.last_contact_at.isoformat() if prospect.last_contact_at else None,
        "converted_at": prospect.converted_at.isoformat() if prospect.converted_at else None,
        "lost_reason": prospect.lost_reason,
        "created_at": prospect.created_at.isoformat() if prospect.created_at else None,
    }


def _stage_view(stage) -> dict:
    return crm_service._stage_view(stage)


def _visit_full_view(visit) -> dict:
    view = crm_service._visit_view(visit)
    report = visit.report
    if report:
        view["report"] = {
            "overall_rating": report.overall_rating,
            "interest_level": report.interest_level.value if report.interest_level else None,
            "strengths": report.strengths,
            "weaknesses": report.weaknesses,
            "comments": report.comments,
            "next_step": report.next_step,
            "follow_up_date": report.follow_up_date.isoformat() if report.follow_up_date else None,
            "visitor_rating": report.visitor_rating,
            "visitor_comments": report.visitor_comments,
            "visitor_would_apply": report.visitor_would_apply,
            "visitor_feedback_at": report.visitor_feedback_at.isoformat() if report.visitor_feedback_at else None,
        }
    view["reminders"] = [
        {"channel": r.channel, "recipient": r.recipient, "sent_at": r.sent_at.isoformat() if r.sent_at else None}
        for r in visit.reminders
    ]
    return view


def _match_view(alert) -> dict:
    property_ = alert.property
    prospect = alert.prospect
    return {
        "id": alert.id,
        "prospect_id": alert.prospect_id,
        "prospect_name": f"{prospect.first_name} {prospect.last_name}" if prospect else None,
        "property_id": alert.property_id,
        "property_reference": property_.reference if property_ else None,
        "property_title": property_.title if property_ else None,
        "city": property_.city if property_ else None,
        "score": alert.score,
        "detail": alert.detail or {},
        "status": alert.status,
        "notified_at": alert.notified_at.isoformat() if alert.notified_at else None,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }


def _listing_view(listing) -> dict:
    return {
        "id": listing.id,
        "reference": listing.reference,
        "property_id": listing.property_id,
        "title": listing.title,
        "description": listing.description,
        "price": listing.price,
        "listing_type": listing.listing_type,
        "status": listing.status.value if listing.status else None,
        "template_id": listing.template_id,
        "published_at": listing.published_at.isoformat() if listing.published_at else None,
        "withdrawn_at": listing.withdrawn_at.isoformat() if listing.withdrawn_at else None,
        "created_at": listing.created_at.isoformat() if listing.created_at else None,
    }


def _offer_view(offer) -> dict:
    return {
        "id": offer.id,
        "reference": offer.reference,
        "property_id": offer.property_id,
        "prospect_id": offer.prospect_id,
        "deal_id": offer.deal_id,
        "amount": offer.amount,
        "offer_date": offer.offer_date.isoformat(),
        "validity_date": offer.validity_date.isoformat() if offer.validity_date else None,
        "status": offer.status.value if offer.status else None,
        "financing_ok": offer.financing_ok,
        "conditions": offer.conditions or [],
        "response_note": offer.response_note,
    }


def _transaction_view(transaction) -> dict:
    return {
        "id": transaction.id,
        "reference": transaction.reference,
        "property_id": transaction.property_id,
        "offer_id": transaction.offer_id,
        "prospect_id": transaction.prospect_id,
        "deal_id": transaction.deal_id,
        "buyer_name": transaction.buyer_name,
        "seller_owner_id": transaction.seller_owner_id,
        "stage": transaction.stage.value if transaction.stage else None,
        "sale_price": transaction.sale_price,
        "compromis_date": transaction.compromis_date.isoformat() if transaction.compromis_date else None,
        "compromis_signed_at": transaction.compromis_signed_at.isoformat() if transaction.compromis_signed_at else None,
        "notary": {
            "name": transaction.notary_name,
            "email": transaction.notary_email,
            "phone": transaction.notary_phone,
        },
        "acte_date": transaction.acte_date.isoformat() if transaction.acte_date else None,
        "acte_signed_at": transaction.acte_signed_at.isoformat() if transaction.acte_signed_at else None,
        "effective_sale_date": transaction.effective_sale_date.isoformat() if transaction.effective_sale_date else None,
        "commission": {
            "rate_pct": transaction.commission_rate,
            "fixed": transaction.commission_fixed,
            "amount_ht": transaction.commission_amount,
            "vat_rate": transaction.vat_rate,
            "total_ttc": transaction.commission_total_ttc,
        },
        "cancelled_reason": transaction.cancelled_reason,
        "notes": transaction.notes,
        "conditions": [
            {
                "id": c.id,
                "label": c.label,
                "type": c.condition_type.value if c.condition_type else None,
                "deadline": c.deadline.isoformat() if c.deadline else None,
                "status": c.status.value if c.status else None,
            }
            for c in transaction.conditions
        ],
        "events": [
            {
                "id": e.id,
                "type": e.event_type,
                "label": e.label,
                "date": e.event_date.isoformat() if e.event_date else None,
                "notes": e.notes,
            }
            for e in transaction.events
        ],
        "created_at": transaction.created_at.isoformat() if transaction.created_at else None,
    }


# ---------------------------------------------------------------------------
# Prospects
# ---------------------------------------------------------------------------
@router.post("/prospects", status_code=201)
def create_prospect(data: ProspectCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    prospect = crm_service.create_prospect(db, data)
    return _prospect_view(prospect)


@router.get("/prospects")
def list_prospects(
    prospect_type: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    min_score: Optional[int] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    try:
        prospects = crm_service.list_prospects(db, prospect_type, source, status, agent, min_score, search)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"data": [_prospect_view(p) for p in prospects], "count": len(prospects)}


@router.get("/prospects/{prospect_id}")
def get_prospect(prospect_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect non trouvé")
    view = _prospect_view(prospect)
    view["deals"] = [crm_service._deal_summary(d) for d in prospect.deals]
    view["visits"] = [crm_service._visit_view(v) for v in prospect.visits]
    return view


@router.put("/prospects/{prospect_id}")
def update_prospect(prospect_id: int, data: ProspectUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        prospect = crm_service.update_prospect(db, prospect_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _prospect_view(prospect)


@router.put("/prospects/{prospect_id}/status")
def set_prospect_status(prospect_id: int, data: ProspectAdminUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        prospect = crm_service.set_prospect_status(db, prospect_id, data.status, data.lost_reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _prospect_view(prospect)


@router.post("/prospects/{prospect_id}/score")
def recompute_score(prospect_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    prospect = db.query(Prospect).filter(Prospect.id == prospect_id).first()
    if not prospect:
        raise HTTPException(status_code=404, detail="Prospect non trouvé")
    detail = crm_service.compute_quality_score(db, prospect)
    db.commit()
    return {"prospect_id": prospect_id, "quality_score": prospect.quality_score, "detail": detail}


# ---------------------------------------------------------------------------
# Pipeline commercial
# ---------------------------------------------------------------------------
@router.get("/pipeline/stages")
def list_stages(include_inactive: bool = False, db: Session = Depends(get_db), current_user=Depends(require_read)):
    stages = crm_service.list_stages(db, include_inactive)
    return {"data": [_stage_view(s) for s in stages], "count": len(stages)}


@router.post("/pipeline/stages", status_code=201)
def create_stage(data: PipelineStageCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    stage = crm_service.create_stage(db, data)
    return _stage_view(stage)


@router.put("/pipeline/stages/{stage_id}")
def update_stage(stage_id: int, data: PipelineStageUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        stage = crm_service.update_stage(db, stage_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _stage_view(stage)


@router.get("/pipeline/kanban")
def kanban(agent: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    return crm_service.kanban_view(db, agent)


@router.post("/deals", status_code=201)
def create_deal(data: DealCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        deal = crm_service.create_deal(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return crm_service._deal_summary(deal)


@router.get("/deals")
def list_deals(
    status: Optional[str] = None,
    agent: Optional[str] = None,
    property_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    query = db.query(PipelineDeal)
    if agent:
        query = query.filter(PipelineDeal.assigned_agent == agent)
    if property_id:
        query = query.filter(PipelineDeal.property_id == property_id)
    if status:
        query = query.filter(PipelineDeal.status == DealStatus(status))
    deals = query.order_by(PipelineDeal.created_at.desc()).all()
    return {"data": [crm_service._deal_summary(d) for d in deals], "count": len(deals)}


@router.get("/deals/{deal_id}")
def get_deal(deal_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    deal = db.query(PipelineDeal).filter(PipelineDeal.id == deal_id).first()
    if not deal:
        raise HTTPException(status_code=404, detail="Dossier non trouvé")
    view = crm_service._deal_summary(deal)
    view["stage_history"] = [
        {
            "from_stage_id": h.from_stage_id,
            "to_stage_id": h.to_stage_id,
            "comment": h.comment,
            "changed_by": h.changed_by,
            "changed_at": h.changed_at.isoformat() if h.changed_at else None,
        }
        for h in deal.stage_history
    ]
    return view


@router.put("/deals/{deal_id}")
def update_deal(deal_id: int, data: DealUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        deal = crm_service.update_deal(db, deal_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return crm_service._deal_summary(deal)


@router.post("/deals/{deal_id}/stage")
def move_deal(deal_id: int, data: DealStageChange, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        deal = crm_service.move_deal_to_stage(db, deal_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return crm_service._deal_summary(deal)


# ---------------------------------------------------------------------------
# Disponibilités et visites
# ---------------------------------------------------------------------------
@router.post("/properties/{property_id}/availabilities", status_code=201)
def add_availability(property_id: int, data: AvailabilityDayCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        created = crm_service.add_availability(db, property_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "data": [
            {
                "id": a.id,
                "property_id": a.property_id,
                "available_date": a.available_date.isoformat(),
                "start_time": a.start_time,
                "end_time": a.end_time,
                "is_booked": a.is_booked,
            }
            for a in created
        ],
        "count": len(created),
    }


@router.get("/properties/{property_id}/availabilities")
def list_availabilities(
    property_id: int,
    only_free: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    slots = crm_service.list_availabilities(db, property_id, only_free)
    return {
        "data": [
            {
                "id": a.id,
                "available_date": a.available_date.isoformat(),
                "start_time": a.start_time,
                "end_time": a.end_time,
                "is_booked": a.is_booked,
            }
            for a in slots
        ],
        "count": len(slots),
    }


@router.post("/visits", status_code=201)
def create_visit(data: VisitCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        visit = crm_service.create_visit(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _visit_full_view(visit)


@router.get("/visits")
def list_visits(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    status: Optional[str] = None,
    agent: Optional[str] = None,
    property_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    query = db.query(Visit)
    if date_from:
        query = query.filter(Visit.scheduled_date >= date_from)
    if date_to:
        query = query.filter(Visit.scheduled_date <= date_to)
    if agent:
        query = query.filter(Visit.assigned_agent == agent)
    if property_id:
        query = query.filter(Visit.property_id == property_id)
    if status:
        query = query.filter(Visit.status == VisitStatus(status))
    visits = query.order_by(Visit.scheduled_date, Visit.start_time).all()
    return {"data": [_visit_full_view(v) for v in visits], "count": len(visits)}


@router.get("/visits/agenda")
def visit_agenda(
    view: str = Query("week", pattern="^(day|week|month)$"),
    date_: Optional[date] = Query(None, alias="date"),
    agent: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    return crm_service.agenda_view(db, view, date_ or date.today(), agent)


@router.get("/visits/{visit_id}")
def get_visit(visit_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visite non trouvée")
    return _visit_full_view(visit)


@router.put("/visits/{visit_id}")
def update_visit(visit_id: int, data: VisitUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visite non trouvée")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(visit, field, value)
    db.commit()
    db.refresh(visit)
    return _visit_full_view(visit)


@router.post("/visits/{visit_id}/confirm")
def confirm_visit(visit_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        visit = crm_service.confirm_visit(db, visit_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _visit_full_view(visit)


@router.post("/visits/{visit_id}/cancel")
def cancel_visit(visit_id: int, data: VisitCancel, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        visit = crm_service.cancel_visit(db, visit_id, data.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _visit_full_view(visit)


@router.post("/visits/{visit_id}/complete")
def complete_visit(visit_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        visit = crm_service.complete_visit(db, visit_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _visit_full_view(visit)


@router.post("/visits/{visit_id}/reminders")
def send_reminders(visit_id: int, data: ReminderRequest, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        result = crm_service.send_visit_reminders(db, visit_id, data.channels)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/visits/{visit_id}/report", status_code=201)
def save_report(visit_id: int, data: VisitReportCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        crm_service.save_visit_report(db, visit_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    return _visit_full_view(visit)


@router.post("/visits/{visit_id}/feedback", status_code=201)
def save_feedback(visit_id: int, data: VisitorFeedbackCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        crm_service.save_visitor_feedback(db, visit_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    return _visit_full_view(visit)


# ---------------------------------------------------------------------------
# Matching automatique
# ---------------------------------------------------------------------------
@router.post("/matching/scan")
def run_matching(data: MatchingScanRequest, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return crm_service.run_matching(db, data.prospect_id, data.min_score, data.notify)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/matching/matches")
def list_matches(
    prospect_id: Optional[int] = None,
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    min_score: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    matches = crm_service.list_matches(db, prospect_id, property_id, status, min_score)
    return {"data": [_match_view(m) for m in matches], "count": len(matches)}


@router.get("/matching/suggestions/{prospect_id}")
def suggest(prospect_id: int, limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        suggestions = crm_service.suggest_properties(db, prospect_id, limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"data": suggestions, "count": len(suggestions)}


@router.post("/matching/matches/{match_id}/notify")
def notify_match(match_id: int, data: MatchNotificationRequest, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        alert = crm_service.notify_match(db, match_id, data.also_email_prospect)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _match_view(alert)


@router.post("/matching/matches/{match_id}/dismiss")
def dismiss_match(match_id: int, data: VisitCancel, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        alert = crm_service.dismiss_match(db, match_id, data.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _match_view(alert)


# ---------------------------------------------------------------------------
# Annonces et portails
# ---------------------------------------------------------------------------
@router.post("/listing-templates", status_code=201)
def create_listing_template(data: ListingTemplateCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    template = crm_service.create_listing_template(db, data)
    return {
        "id": template.id,
        "name": template.name,
        "property_type": template.property_type,
        "language": template.language,
        "title_template": template.title_template,
        "description_template": template.description_template,
        "is_active": template.is_active,
    }


@router.get("/listing-templates")
def list_listing_templates(db: Session = Depends(get_db), current_user=Depends(require_read)):
    templates = crm_service.list_listing_templates(db)
    return {"data": templates, "count": len(templates)}


@router.get("/portals")
def list_portals(current_user=Depends(require_read)):
    return {"data": crm_service.SUPPORTED_PORTALS}


@router.post("/listings", status_code=201)
def create_listing(data: ListingCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        listing = crm_service.create_listing(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _listing_view(listing)


@router.get("/listings")
def list_listings(db: Session = Depends(get_db), current_user=Depends(require_read)):
    return crm_service.centralized_listings_overview(db)


@router.get("/listings/{listing_id}")
def get_listing(listing_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Annonce non trouvée")
    view = _listing_view(listing)
    view["publications"] = crm_service.portal_sync_status(db, listing_id)
    return view


@router.put("/listings/{listing_id}")
def update_listing(listing_id: int, data: ListingUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        listing = crm_service.update_listing(db, listing_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _listing_view(listing)


@router.post("/listings/{listing_id}/publish")
def publish_listing(listing_id: int, data: ListingPublishRequest, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return crm_service.publish_listing(db, listing_id, data.portals, data.external_references)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/listings/{listing_id}/unpublish")
def unpublish_listing(
    listing_id: int,
    portal: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    from app.models.crm import Portal

    try:
        portal_enum = Portal(portal) if portal else None
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Portail inconnu : {portal}")
    try:
        return crm_service.unpublish_listing(db, listing_id, portal_enum)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/listings/{listing_id}/sync")
def listing_sync(listing_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return {"data": crm_service.portal_sync_status(db, listing_id)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/listings/{listing_id}/stats")
def listing_stats(listing_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return crm_service.listing_stats(db, listing_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/listings/{listing_id}/stats")
def upload_stats(listing_id: int, data: ListingStatsUpload, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return crm_service.upload_listing_stats(db, listing_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Transactions (vente)
# ---------------------------------------------------------------------------
@router.post("/offers", status_code=201)
def create_offer(data: PurchaseOfferCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        offer = crm_service.create_offer(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _offer_view(offer)


@router.get("/offers")
def list_offers(status: Optional[str] = None, property_id: Optional[int] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    query = db.query(PurchaseOffer)
    if status:
        query = query.filter(PurchaseOffer.status == OfferStatus(status))
    if property_id:
        query = query.filter(PurchaseOffer.property_id == property_id)
    offers = query.order_by(PurchaseOffer.created_at.desc()).all()
    return {"data": [_offer_view(o) for o in offers], "count": len(offers)}


@router.get("/offers/{offer_id}")
def get_offer(offer_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    offer = db.query(PurchaseOffer).filter(PurchaseOffer.id == offer_id).first()
    if not offer:
        raise HTTPException(status_code=404, detail="Offre non trouvée")
    return _offer_view(offer)


@router.post("/offers/{offer_id}/accept")
def accept_offer(offer_id: int, data: OfferDecision, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        offer, transaction = crm_service.decide_offer(db, offer_id, "acceptee", data.note, data.create_transaction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = _offer_view(offer)
    if transaction:
        result["transaction"] = _transaction_view(transaction)
    return result


@router.post("/offers/{offer_id}/refuse")
def refuse_offer(offer_id: int, data: OfferDecision, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        offer, _ = crm_service.decide_offer(db, offer_id, "refusee", data.note, False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _offer_view(offer)


@router.post("/offers/{offer_id}/withdraw")
def withdraw_offer(offer_id: int, data: OfferDecision, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        offer, _ = crm_service.decide_offer(db, offer_id, "retiree", data.note, False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _offer_view(offer)


@router.post("/transactions", status_code=201)
def create_transaction(data: SaleTransactionCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        transaction = crm_service.create_transaction(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _transaction_view(transaction)


@router.get("/transactions")
def list_transactions(stage: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    query = db.query(SaleTransaction)
    if stage:
        query = query.filter(SaleTransaction.stage == TransactionStage(stage))
    transactions = query.order_by(SaleTransaction.created_at.desc()).all()
    return {"data": [_transaction_view(t) for t in transactions], "count": len(transactions)}


@router.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        transaction = crm_service.get_transaction(db, transaction_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _transaction_view(transaction)


@router.post("/transactions/{transaction_id}/compromis")
def sign_compromis(transaction_id: int, data: CompromisSign, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        transaction = crm_service.sign_compromis(db, transaction_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _transaction_view(transaction)


@router.post("/transactions/{transaction_id}/conditions", status_code=201)
def add_condition(transaction_id: int, data: SuspensiveConditionCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        condition = crm_service.add_condition(db, transaction_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": condition.id,
        "transaction_id": condition.transaction_id,
        "label": condition.label,
        "type": condition.condition_type.value if condition.condition_type else None,
        "deadline": condition.deadline.isoformat() if condition.deadline else None,
        "status": condition.status.value if condition.status else None,
    }


@router.post("/transactions/conditions/{condition_id}/decision")
def decide_condition(condition_id: int, data: ConditionDecision, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        condition = crm_service.decide_condition(db, condition_id, data.decision, data.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": condition.id,
        "label": condition.label,
        "status": condition.status.value if condition.status else None,
    }


@router.put("/transactions/{transaction_id}/notary")
def update_notary(transaction_id: int, data: NotaryUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        transaction = crm_service.update_notary(db, transaction_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _transaction_view(transaction)


@router.post("/transactions/{transaction_id}/events", status_code=201)
def add_transaction_event(transaction_id: int, data: TransactionEventCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        event = crm_service.add_transaction_event(db, transaction_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "id": event.id,
        "transaction_id": event.transaction_id,
        "type": event.event_type,
        "label": event.label,
        "date": event.event_date.isoformat() if event.event_date else None,
        "notes": event.notes,
    }


@router.post("/transactions/{transaction_id}/acte")
def sign_acte(transaction_id: int, data: ActeSign, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        result = crm_service.sign_acte(db, transaction_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    view = _transaction_view(result["transaction"])
    view["commission_calculation"] = {
        "base": result["transaction"].sale_price,
        "rate_pct": result["transaction"].commission_rate,
        "fixed": result["transaction"].commission_fixed,
        "commission_ht": result["commission_ht"],
        "commission_ttc": result["commission_ttc"],
    }
    return view


# ---------------------------------------------------------------------------
# Notifications CRM
# ---------------------------------------------------------------------------
@router.get("/notifications")
def list_notifications(unread_only: bool = False, db: Session = Depends(get_db), current_user=Depends(require_read)):
    notifications = crm_service.list_notifications(db, unread_only)
    return {
        "data": [
            {
                "id": n.id,
                "recipient": n.recipient,
                "type": n.type,
                "title": n.title,
                "message": n.message,
                "link": n.link,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in notifications
        ],
        "count": len(notifications),
    }


@router.put("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        notification = crm_service.mark_notification_read(db, notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"id": notification.id, "is_read": notification.is_read}


# ---------------------------------------------------------------------------
# Suivi de la performance
# ---------------------------------------------------------------------------
@router.get("/performance")
def performance(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    return crm_service.agent_performance(db, date_from, date_to)
