"""API du module 16 : prédictions, assistants, RPA, OCR et marché."""

from datetime import date
from types import SimpleNamespace
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.auth import GranularPermissionChecker
from app.core.tenant_security import get_current_tenant
from app.database import get_db
from app.models.ai_automation import (
    AIPrediction,
    AssistantAppointment,
    WorkflowExecution,
    AutomationWorkflow,
    ChatMessage,
    IntelligentOCRJob,
    MarketObservation,
    MarketPriceIndex,
)
from app.models.maintenance import TicketCategory, TicketSource, TicketUrgency
from app.models.tenant import Lease
from app.schemas.ai_automation import (
    AppointmentCreate,
    AssistantTicketCreate,
    AutomationEvent,
    ChatMessageCreate,
    ChatSessionCreate,
    FinancialAnomalyRequest,
    ManagerSearchRequest,
    MarketIndexCreate,
    MarketObservationCreate,
    PaymentRiskRequest,
    PredictionReview,
    QuickActionRequest,
    RentEstimateRequest,
    SalePriceRequest,
    VacancyPredictionRequest,
    WorkflowCreate,
    WorkflowUpdate,
)
from app.services import ai_automation_service as service
from app.services import ged_service, maintenance_service


router = APIRouter(prefix="/api/ai", tags=["Intelligence artificielle et automatisation"])
tenant_router = APIRouter(prefix="/tenant-portal/assistant", tags=["Assistant virtuel locataire"])
ai_read = GranularPermissionChecker("artificial_intelligence", "read")
ai_create = GranularPermissionChecker("artificial_intelligence", "create")
ai_update = GranularPermissionChecker("artificial_intelligence", "update")
ai_admin = GranularPermissionChecker("artificial_intelligence", "admin")


def _actor(user) -> str:
    return getattr(user, "email", None) or getattr(user, "id", "system")


def _not_found_or_bad_request(exc: ValueError) -> HTTPException:
    text = str(exc)
    return HTTPException(status_code=404 if "introuvable" in text else 400, detail=text)


# ---------------------------------------------------------------------------
# Prédiction explicable
# ---------------------------------------------------------------------------
@router.post("/predictions/rent", status_code=201)
def estimate_rent(data: RentEstimateRequest, db: Session = Depends(get_db), user=Depends(ai_create)):
    """Estime le loyer avec régression ridge ou comparables pondérés."""
    try:
        row = service.estimate_property_price(db, data, "rent_estimate", _actor(user))
    except ValueError as exc:
        raise _not_found_or_bad_request(exc)
    return service.prediction_view(row)


@router.post("/predictions/sale-price", status_code=201)
def recommend_sale_price(data: SalePriceRequest, db: Session = Depends(get_db), user=Depends(ai_create)):
    try:
        row = service.estimate_property_price(db, data, "sale_price_recommendation", _actor(user))
    except ValueError as exc:
        raise _not_found_or_bad_request(exc)
    return service.prediction_view(row)


@router.post("/predictions/vacancy", status_code=201)
def vacancy_risk(data: VacancyPredictionRequest, db: Session = Depends(get_db), user=Depends(ai_create)):
    try:
        row = service.predict_vacancy(db, data.property_id, data.horizon_days, _actor(user))
    except ValueError as exc:
        raise _not_found_or_bad_request(exc)
    return service.prediction_view(row)


@router.post("/predictions/payment-default", status_code=201)
def payment_default(data: PaymentRiskRequest, db: Session = Depends(get_db), user=Depends(ai_create)):
    try:
        row = service.predict_payment_risk(db, data.tenant_id, data.horizon_days, _actor(user))
    except ValueError as exc:
        raise _not_found_or_bad_request(exc)
    return service.prediction_view(row)


@router.post("/anomalies/financial", status_code=201)
def financial_anomalies(data: FinancialAnomalyRequest, db: Session = Depends(get_db), user=Depends(ai_create)):
    row = service.detect_financial_anomalies(db, data, _actor(user))
    return service.prediction_view(row)


@router.get("/predictions")
def prediction_history(
    prediction_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    risk_level: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(ai_read),
):
    query = db.query(AIPrediction)
    if prediction_type:
        query = query.filter(AIPrediction.prediction_type == prediction_type)
    if entity_type:
        query = query.filter(AIPrediction.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AIPrediction.entity_id == entity_id)
    if risk_level:
        query = query.filter(AIPrediction.risk_level == risk_level)
    rows = query.order_by(AIPrediction.created_at.desc()).limit(limit).all()
    return {"data": [service.prediction_view(row) for row in rows], "count": len(rows)}


@router.put("/predictions/{prediction_id}/review")
def review_prediction(
    prediction_id: int,
    data: PredictionReview,
    db: Session = Depends(get_db),
    user=Depends(ai_update),
):
    row = db.query(AIPrediction).filter(AIPrediction.id == prediction_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Prédiction introuvable")
    row.review_decision = data.decision
    row.reviewed_by = _actor(user)
    row.reviewed_at = service.utcnow()
    explanation = dict(row.explanation or {})
    if data.notes:
        explanation["review_notes"] = data.notes
    row.explanation = explanation
    db.commit()
    db.refresh(row)
    return service.prediction_view(row)


# ---------------------------------------------------------------------------
# Assistant gestionnaire
# ---------------------------------------------------------------------------
@router.post("/assistant/sessions", status_code=201)
def manager_session(data: ChatSessionCreate, db: Session = Depends(get_db), user=Depends(ai_create)):
    row = service.create_chat_session(db, "manager", user.db_id or 0, data.locale, data.context)
    return service.chat_session_view(row)


@router.post("/assistant/sessions/{session_id}/messages", status_code=201)
def manager_message(
    session_id: str,
    data: ChatMessageCreate,
    db: Session = Depends(get_db),
    user=Depends(ai_create),
):
    try:
        session = service.get_chat_session(db, session_id, "manager", user.db_id or 0)
        return service.answer_chat(db, session, data.message, data.context)
    except ValueError as exc:
        raise _not_found_or_bad_request(exc)


@router.post("/assistant/search")
def assistant_search(data: ManagerSearchRequest, db: Session = Depends(get_db), user=Depends(ai_read)):
    rows = service.manager_search(db, data.query, data.entity_types, data.limit)
    return {"data": rows, "count": len(rows), "query": data.query}


CONTEXT_HELP = {
    "properties": {"title": "Biens", "tips": ["Filtrez par statut et ville", "L'estimation IA reste soumise à validation humaine"]},
    "finance": {"title": "Finance", "tips": ["Rapprochez les lignes bancaires", "Contrôlez chaque anomalie avant correction"]},
    "maintenance": {"title": "Maintenance", "tips": ["Précisez l'urgence et la localisation", "Le SLA est calculé à la création"]},
    "automation": {"title": "Automatisation", "tips": ["Testez un workflow en mode dry-run", "Utilisez une clé d'idempotence stable"]},
}


@router.get("/assistant/context-help")
def context_help(screen: str, user=Depends(ai_read)):
    return CONTEXT_HELP.get(screen, {"title": screen, "tips": ["Consultez la documentation OpenAPI pour les actions disponibles"]})


@router.post("/assistant/actions")
def quick_action(data: QuickActionRequest, db: Session = Depends(get_db), user=Depends(ai_create)):
    if not data.confirm:
        return {"executed": False, "requires_confirmation": True, "action": data.action, "parameters": data.parameters}
    parameters = data.parameters
    try:
        if data.action == "trigger_workflow":
            result = service.execute_event(
                db, parameters["event_type"], parameters.get("payload", {}),
                parameters.get("idempotency_key") or service.reference("ACT"), _actor(user),
            )
            return {"executed": True, "result": result}
        if data.action == "create_appointment":
            appointment_data = AppointmentCreate(**parameters)
            row = service.create_appointment(db, appointment_data, None, None)
            return {"executed": True, "result": service.model_view(row)}
        ticket_data = AssistantTicketCreate(**{**parameters, "confirm": True})
        ticket_input = SimpleNamespace(
            property_id=ticket_data.property_id, tenant_id=parameters.get("tenant_id"),
            owner_id=parameters.get("owner_id"), lease_id=ticket_data.lease_id,
            source=TicketSource.MANAGER, category=TicketCategory(ticket_data.category),
            urgency=TicketUrgency(ticket_data.urgency), title=ticket_data.title,
            description=ticket_data.description, location=ticket_data.location,
            provider_id=None, estimated_cost=0,
        )
        ticket = maintenance_service.create_ticket(db, ticket_input, _actor(user))
        return {"executed": True, "result": {"ticket_id": ticket.id, "reference": ticket.reference}}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Workflows / règles / événements
# ---------------------------------------------------------------------------
@router.get("/automation/catalog")
def automation_catalog(user=Depends(ai_read)):
    return {
        "operators": sorted(service.ALLOWED_OPERATORS),
        "actions": sorted(service.ALLOWED_ACTIONS),
        "condition_format": {"field": "amount", "operator": "gte", "value": 1000},
        "template_format": "${event.field}",
    }


@router.post("/automation/workflows", status_code=201)
def create_workflow(data: WorkflowCreate, db: Session = Depends(get_db), user=Depends(ai_create)):
    try:
        service.validate_workflow(data.conditions, data.actions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    row = AutomationWorkflow(**data.model_dump(), created_by=_actor(user), updated_by=_actor(user))
    db.add(row)
    db.commit()
    db.refresh(row)
    return service.model_view(row)


@router.get("/automation/workflows")
def list_workflows(
    event_type: Optional[str] = None,
    active_only: bool = False,
    db: Session = Depends(get_db),
    user=Depends(ai_read),
):
    query = db.query(AutomationWorkflow)
    if event_type:
        query = query.filter(AutomationWorkflow.event_type == event_type)
    if active_only:
        query = query.filter(AutomationWorkflow.is_active == True)  # noqa: E712
    rows = query.order_by(AutomationWorkflow.priority, AutomationWorkflow.id).all()
    return {"data": [service.model_view(row) for row in rows], "count": len(rows)}


@router.get("/automation/workflows/{workflow_id}")
def get_workflow(workflow_id: int, db: Session = Depends(get_db), user=Depends(ai_read)):
    row = db.query(AutomationWorkflow).filter(AutomationWorkflow.id == workflow_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow introuvable")
    result = service.model_view(row)
    runs = db.query(WorkflowExecution).filter(WorkflowExecution.workflow_id == row.id).order_by(WorkflowExecution.started_at.desc()).limit(20).all()
    result["recent_runs"] = [service.model_view(run) for run in runs]
    return result


@router.put("/automation/workflows/{workflow_id}")
def update_workflow(
    workflow_id: int,
    data: WorkflowUpdate,
    db: Session = Depends(get_db),
    user=Depends(ai_update),
):
    row = db.query(AutomationWorkflow).filter(AutomationWorkflow.id == workflow_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow introuvable")
    payload = data.model_dump(exclude_unset=True)
    try:
        service.validate_workflow(payload.get("conditions", row.conditions or []), payload.get("actions", row.actions or []))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    for key, value in payload.items():
        setattr(row, key, value)
    row.version = (row.version or 1) + 1
    row.updated_by = _actor(user)
    db.commit()
    db.refresh(row)
    return service.model_view(row)


@router.delete("/automation/workflows/{workflow_id}")
def deactivate_workflow(workflow_id: int, db: Session = Depends(get_db), user=Depends(ai_admin)):
    row = db.query(AutomationWorkflow).filter(AutomationWorkflow.id == workflow_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Workflow introuvable")
    row.is_active = False
    row.updated_by = _actor(user)
    db.commit()
    return {"id": row.id, "is_active": False}


@router.post("/automation/events")
def trigger_event(data: AutomationEvent, db: Session = Depends(get_db), user=Depends(ai_create)):
    return service.execute_event(db, data.event_type, data.payload, data.idempotency_key, _actor(user), data.dry_run)


@router.get("/automation/runs")
def automation_runs(
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(ai_read),
):
    query = db.query(WorkflowExecution)
    if status:
        query = query.filter(WorkflowExecution.status == status)
    rows = query.order_by(WorkflowExecution.started_at.desc()).limit(limit).all()
    return {"data": [service.model_view(row) for row in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# OCR intelligent
# ---------------------------------------------------------------------------
@router.post("/ocr/documents/{document_id}/analyse", status_code=201)
def analyse_document(
    document_id: int,
    expected_type: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(ai_create),
):
    try:
        document = ged_service.get_document(db, document_id)
        row = service.analyse_ged_document(db, document, expected_type, _actor(user))
    except ValueError as exc:
        raise _not_found_or_bad_request(exc)
    return service.model_view(row)


@router.post("/ocr/analyse", status_code=201)
async def upload_and_analyse(
    file: UploadFile = File(...),
    expected_type: Optional[str] = Form(None),
    property_id: Optional[int] = Form(None),
    tenant_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    user=Depends(ai_create),
):
    content = await file.read()
    document_type = expected_type if expected_type in ged_service.DOCUMENT_TYPES else "other"
    try:
        document = ged_service.create_document(
            db, title=file.filename or "Document OCR", filename=file.filename or "document",
            content=content, mime_type=file.content_type, document_type=document_type,
            actor=_actor(user), actor_role=getattr(user, "role", None), property_id=property_id,
            tenant_id=tenant_id,
        )
        row = service.analyse_ged_document(db, document, expected_type, _actor(user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = service.model_view(row)
    result["ged_document"] = ged_service.document_view(document)
    return result


@router.get("/ocr/jobs")
def ocr_jobs(
    manual_review_only: bool = False,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(ai_read),
):
    query = db.query(IntelligentOCRJob)
    if manual_review_only:
        query = query.filter(IntelligentOCRJob.requires_manual_review == True)  # noqa: E712
    rows = query.order_by(IntelligentOCRJob.created_at.desc()).limit(limit).all()
    return {"data": [service.model_view(row) for row in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# Analyse de marché
# ---------------------------------------------------------------------------
@router.post("/market/observations", status_code=201)
def create_observation(data: MarketObservationCreate, db: Session = Depends(get_db), user=Depends(ai_create)):
    row = MarketObservation(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    result = service.model_view(row)
    result["price_per_sqm"] = round(row.price / row.area, 2)
    return result


@router.get("/market/observations")
def list_observations(
    city: Optional[str] = None,
    listing_type: Optional[str] = None,
    competitor: Optional[str] = None,
    active_only: bool = True,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user=Depends(ai_read),
):
    query = db.query(MarketObservation)
    if city:
        query = query.filter(MarketObservation.city.ilike(city))
    if listing_type:
        query = query.filter(MarketObservation.listing_type == listing_type)
    if competitor:
        query = query.filter(MarketObservation.competitor.ilike(f"%{competitor}%"))
    if active_only:
        query = query.filter(MarketObservation.is_active == True)  # noqa: E712
    rows = query.order_by(MarketObservation.observed_on.desc()).limit(limit).all()
    return {"data": [{**service.model_view(row), "price_per_sqm": round(row.price / row.area, 2)} for row in rows], "count": len(rows)}


@router.get("/market/properties/{property_id}/comparables")
def comparables(
    property_id: int,
    listing_type: str = Query("rent", pattern="^(rent|sale)$"),
    area_tolerance_percent: float = Query(30, ge=5, le=100),
    db: Session = Depends(get_db),
    user=Depends(ai_read),
):
    try:
        rows = service.market_comparables(db, property_id, listing_type, area_tolerance_percent)
    except ValueError as exc:
        raise _not_found_or_bad_request(exc)
    return {"data": rows, "count": len(rows)}


@router.get("/market/trends")
def trends(
    city: str,
    listing_type: str = Query("rent", pattern="^(rent|sale)$"),
    property_type: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(ai_read),
):
    return service.market_trends(db, city, listing_type, property_type)


@router.post("/market/indices", status_code=201)
def create_market_index(data: MarketIndexCreate, db: Session = Depends(get_db), user=Depends(ai_create)):
    existing = db.query(MarketPriceIndex).filter(
        MarketPriceIndex.code == data.code,
        MarketPriceIndex.geography == data.geography,
        MarketPriceIndex.period == data.period,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Indice déjà enregistré pour cette période et cette zone")
    row = MarketPriceIndex(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return service.model_view(row)


@router.get("/market/indices")
def list_indices(
    code: Optional[str] = None,
    geography: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(ai_read),
):
    query = db.query(MarketPriceIndex)
    if code:
        query = query.filter(MarketPriceIndex.code == code)
    if geography:
        query = query.filter(MarketPriceIndex.geography.ilike(f"%{geography}%"))
    rows = query.order_by(MarketPriceIndex.period.desc()).all()
    return {"data": [service.model_view(row) for row in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# Assistant locataire authentifié, disponible 24/7
# ---------------------------------------------------------------------------
@tenant_router.get("/faq")
def tenant_faq():
    return {
        "available_24_7": True,
        "topics": [
            {"keywords": sorted(keywords), "answer": answer}
            for keywords, answer in service.FAQS
        ],
    }


@tenant_router.post("/sessions", status_code=201)
def tenant_session(
    data: ChatSessionCreate,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    row = service.create_chat_session(db, "tenant", tenant.id, data.locale, data.context)
    return service.chat_session_view(row)


@tenant_router.post("/sessions/{session_id}/messages", status_code=201)
def tenant_message(
    session_id: str,
    data: ChatMessageCreate,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    try:
        session = service.get_chat_session(db, session_id, "tenant", tenant.id)
        return service.answer_chat(db, session, data.message, data.context)
    except ValueError as exc:
        raise _not_found_or_bad_request(exc)


@tenant_router.get("/sessions/{session_id}/messages")
def tenant_history(
    session_id: str,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    try:
        session = service.get_chat_session(db, session_id, "tenant", tenant.id)
    except ValueError as exc:
        raise _not_found_or_bad_request(exc)
    rows = db.query(ChatMessage).filter(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at).all()
    return {"data": [service.model_view(row) for row in rows], "count": len(rows)}


@tenant_router.post("/tickets", status_code=201)
def tenant_ticket(
    data: AssistantTicketCreate,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    if not data.confirm:
        return {"created": False, "requires_confirmation": True, "preview": data.model_dump(exclude={"confirm"})}
    lease = db.query(Lease).filter(
        Lease.tenant_id == tenant.id,
        Lease.property_id == data.property_id,
    ).first()
    if not lease or (data.lease_id and lease.id != data.lease_id):
        raise HTTPException(status_code=403, detail="Ce logement n'est pas rattaché à votre dossier")
    ticket_input = SimpleNamespace(
        property_id=data.property_id, tenant_id=tenant.id, owner_id=None,
        lease_id=lease.id, source=TicketSource.TENANT,
        category=TicketCategory(data.category), urgency=TicketUrgency(data.urgency),
        title=data.title, description=data.description, location=data.location,
        provider_id=None, estimated_cost=0,
    )
    try:
        ticket = maintenance_service.create_ticket(db, ticket_input, created_by=f"tenant:{tenant.id}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"created": True, "ticket_id": ticket.id, "reference": ticket.reference, "status": ticket.status.value}


@tenant_router.post("/appointments", status_code=201)
def tenant_appointment(
    data: AppointmentCreate,
    session_id: Optional[str] = None,
    db: Session = Depends(get_db),
    tenant=Depends(get_current_tenant),
):
    session = None
    if session_id:
        try:
            session = service.get_chat_session(db, session_id, "tenant", tenant.id)
        except ValueError as exc:
            raise _not_found_or_bad_request(exc)
    if data.property_id:
        allowed = db.query(Lease).filter(Lease.tenant_id == tenant.id, Lease.property_id == data.property_id).first()
        if not allowed:
            raise HTTPException(status_code=403, detail="Ce logement n'est pas rattaché à votre dossier")
    try:
        row = service.create_appointment(db, data, tenant.id, session.id if session else None)
    except ValueError as exc:
        raise _not_found_or_bad_request(exc)
    return service.model_view(row)


@tenant_router.get("/appointments")
def tenant_appointments(db: Session = Depends(get_db), tenant=Depends(get_current_tenant)):
    rows = db.query(AssistantAppointment).filter(AssistantAppointment.tenant_id == tenant.id).order_by(AssistantAppointment.starts_at).all()
    return {"data": [service.model_view(row) for row in rows], "count": len(rows)}
