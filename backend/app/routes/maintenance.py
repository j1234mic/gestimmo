"""API du module 6 : maintenance et travaux."""

import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.config import settings
from app.database import get_db
from app.models.maintenance import (
    Equipment,
    MaintenanceExpense,
    MaintenanceTicket,
    PreventiveMaintenancePlan,
    PreventiveMaintenanceTask,
    ProviderEvaluation,
    ProviderQuote,
    PurchaseOrder,
    QuoteStatus,
    ServiceProvider,
    TicketCategory,
    TicketSource,
    TicketStatus,
    TicketUrgency,
    WorkDocument,
    WorkDocumentType,
    WorkPhase,
    WorkProject,
)
from app.schemas.maintenance import (
    EquipmentCreate,
    EquipmentLogCreate,
    EquipmentUpdate,
    EvaluationCreate,
    MaintenanceExpenseCreate,
    PreventivePlanCreate,
    PreventiveTaskUpdate,
    ProviderQuoteCreate,
    PurchaseOrderCreate,
    PurchaseOrderStatusUpdate,
    QualityControl,
    QuoteStatusUpdate,
    ServiceProviderCreate,
    ServiceProviderUpdate,
    TicketCreate,
    TicketStatusChange,
    TicketUpdate,
    WorkPhaseCreate,
    WorkPhaseUpdate,
    WorkProjectCreate,
    WorkProjectUpdate,
)
from app.services.maintenance_service import (
    accept_quote,
    add_equipment_log,
    add_provider_evaluation,
    add_provider_quote,
    add_work_document,
    add_work_phase,
    apply_quality_control,
    attach_file,
    change_status,
    compare_quotes,
    complete_preventive_task,
    create_equipment,
    create_maintenance_expense,
    create_preventive_plan,
    create_provider,
    create_purchase_order,
    create_ticket,
    create_work_project,
    escalate_overdue_tickets,
    equipment_maintenance_history,
    is_sla_breached,
    maintenance_budget,
    maintenance_calendar,
    maintenance_reporting,
    materialize_planned_tasks,
    receive_work_project,
    update_equipment,
    update_provider,
    update_purchase_order_status,
    update_work_project,
    work_project_gantt,
)

router = APIRouter(prefix="/api/maintenance", tags=["Maintenance et travaux"])


def _ticket_or_404(db: Session, ticket_id: int) -> MaintenanceTicket:
    ticket = db.query(MaintenanceTicket).filter(MaintenanceTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket non trouvé")
    return ticket


def _provider_or_404(db: Session, provider_id: int) -> ServiceProvider:
    provider = db.query(ServiceProvider).filter(ServiceProvider.id == provider_id).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Prestataire non trouvé")
    return provider


# ---------------------------------------------------------------------------
# Prestataires
# ---------------------------------------------------------------------------
@router.post("/providers", status_code=201)
def create_provider_endpoint(data: ServiceProviderCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    provider = create_provider(db, data)
    return _provider_view(provider)


@router.get("/providers")
def list_providers(
    specialty: Optional[str] = None,
    zone: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    query = db.query(ServiceProvider).filter(ServiceProvider.is_active.is_(True))
    if specialty:
        query = query.filter(ServiceProvider.specialties.contains(specialty))
    if zone:
        query = query.filter(ServiceProvider.intervention_zone.ilike(f"%{zone}%"))
    providers = query.order_by(ServiceProvider.company_name).all()
    return {"data": [_provider_view(p) for p in providers], "count": len(providers)}


@router.get("/providers/{provider_id}")
def get_provider(provider_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    provider = _provider_or_404(db, provider_id)
    return _provider_view(provider)


@router.put("/providers/{provider_id}")
def update_provider_endpoint(provider_id: int, data: ServiceProviderUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    provider = _provider_or_404(db, provider_id)
    try:
        provider = update_provider(db, provider_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _provider_view(provider)


# ---------------------------------------------------------------------------
# Tickets / demandes d'intervention
# ---------------------------------------------------------------------------
@router.post("/tickets", status_code=201)
def create_ticket_endpoint(data: TicketCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        ticket = create_ticket(db, data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _ticket_view(ticket)


@router.get("/tickets")
def list_tickets(
    status: Optional[TicketStatus] = None,
    category: Optional[TicketCategory] = None,
    urgency: Optional[TicketUrgency] = None,
    property_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    sla_breached: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    query = db.query(MaintenanceTicket)
    if status:
        query = query.filter(MaintenanceTicket.status == status)
    if category:
        query = query.filter(MaintenanceTicket.category == category)
    if urgency:
        query = query.filter(MaintenanceTicket.urgency == urgency)
    if property_id:
        query = query.filter(MaintenanceTicket.property_id == property_id)
    if tenant_id:
        query = query.filter(MaintenanceTicket.tenant_id == tenant_id)
    tickets = query.order_by(MaintenanceTicket.reported_at.desc()).all()
    data = []
    for t in tickets:
        view = _ticket_view(t)
        if sla_breached is not None:
            view["sla_breached"] = is_sla_breached(t)
            if sla_breached and not view["sla_breached"]:
                continue
            if not sla_breached and view["sla_breached"]:
                continue
        data.append(view)
    total = len(data)
    return {"data": data, "count": total}


@router.get("/tickets/{ticket_id}")
def get_ticket(ticket_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    ticket = _ticket_or_404(db, ticket_id)
    view = _ticket_view(ticket)
    view["sla_breached"] = is_sla_breached(ticket)
    view["attachments"] = [
        {"id": a.id, "filename": a.original_filename, "mime_type": a.mime_type, "caption": a.caption}
        for a in ticket.attachments
    ]
    view["status_history"] = [
        {"id": h.id, "from_status": h.from_status.value if h.from_status else None, "to_status": h.to_status.value, "note": h.note, "changed_by": h.changed_by, "changed_at": h.changed_at}
        for h in ticket.status_history
    ]
    view["quotes"] = [
        {"id": q.id, "provider_id": q.provider_id, "provider_name": q.provider.company_name if q.provider else "", "amount": q.amount, "status": q.status.value, "valid_until": q.valid_until}
        for q in ticket.quotes
    ]
    return view


@router.put("/tickets/{ticket_id}")
def update_ticket(ticket_id: int, data: TicketUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    ticket = _ticket_or_404(db, ticket_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ticket, field, value)
    if data.status:
        try:
            ticket = change_status(db, ticket_id, data.status, note="Mise à jour du ticket", changed_by=current_user.email)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    db.refresh(ticket)
    return _ticket_view(ticket)


@router.post("/tickets/{ticket_id}/status")
def change_ticket_status(ticket_id: int, data: TicketStatusChange, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _ticket_or_404(db, ticket_id)
    try:
        ticket = change_status(db, ticket_id, data.status, data.note, data.changed_by or current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return _ticket_view(ticket)


@router.post("/tickets/{ticket_id}/quotes", status_code=201)
def add_quote(ticket_id: int, data: ProviderQuoteCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _ticket_or_404(db, ticket_id)
    try:
        quote = add_provider_quote(db, ticket_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _quote_view(quote)


@router.post("/tickets/{ticket_id}/quotes/{quote_id}/accept")
def accept_ticket_quote(ticket_id: int, quote_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _ticket_or_404(db, ticket_id)
    quote = db.query(ProviderQuote).filter(ProviderQuote.id == quote_id, ProviderQuote.ticket_id == ticket_id).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Devis non trouvé")
    try:
        quote = accept_quote(db, quote_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _quote_view(quote)


@router.get("/tickets/{ticket_id}/quotes/compare")
def compare_ticket_quotes(ticket_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _ticket_or_404(db, ticket_id)
    try:
        return compare_quotes(db, ticket_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/tickets/{ticket_id}/purchase-orders", status_code=201)
def create_purchase_order_endpoint(ticket_id: int, data: PurchaseOrderCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _ticket_or_404(db, ticket_id)
    try:
        order = create_purchase_order(db, ticket_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _purchase_order_view(order)


@router.get("/tickets/{ticket_id}/purchase-orders")
def list_purchase_orders(ticket_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    _ticket_or_404(db, ticket_id)
    orders = db.query(PurchaseOrder).filter(PurchaseOrder.ticket_id == ticket_id).order_by(PurchaseOrder.issued_at.desc()).all()
    return {"data": [_purchase_order_view(o) for o in orders], "count": len(orders)}


@router.put("/purchase-orders/{order_id}/status")
def update_purchase_order_status_endpoint(order_id: int, data: PurchaseOrderStatusUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        order = update_purchase_order_status(db, order_id, data.status)
    except ValueError as exc:
        raise HTTPException(status_code=404 if "trouvé" in str(exc) else 400, detail=str(exc))
    return _purchase_order_view(order)


@router.post("/tickets/{ticket_id}/quality-control")
def quality_control_endpoint(ticket_id: int, data: QualityControl, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _ticket_or_404(db, ticket_id)
    try:
        ticket = apply_quality_control(db, ticket_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _ticket_view(ticket)


@router.post("/tickets/{ticket_id}/evaluations", status_code=201)
def evaluate_provider(ticket_id: int, data: EvaluationCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    _ticket_or_404(db, ticket_id)
    try:
        evaluation = add_provider_evaluation(db, ticket_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": evaluation.id,
        "provider_id": evaluation.provider_id,
        "rating": evaluation.rating,
        "comment": evaluation.comment,
        "would_reuse": evaluation.would_reuse,
    }


@router.post("/tickets/{ticket_id}/attachments", status_code=201)
async def upload_ticket_attachment(
    ticket_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    """Ajoute une photo / vidéo jointe à une demande d'intervention."""
    _ticket_or_404(db, ticket_id)
    extension = Path(file.filename or "").suffix.lower().lstrip(".")
    if extension not in {"jpg", "jpeg", "png", "webp", "mp4", "mov", "pdf"}:
        raise HTTPException(status_code=400, detail="Format de fichier non autorisé")
    content = await file.read()
    if not content or len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier vide ou supérieur à 50 Mo")
    directory = Path(settings.private_upload_dir_path) / "maintenance" / str(ticket_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.{extension}"
    async with aiofiles.open(path, "wb") as output:
        await output.write(content)
    try:
        attachment = attach_file(db, ticket_id, str(path), file.filename or f"attachment.{extension}", file.content_type, len(content), caption)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": attachment.id, "file": attachment.original_filename, "mime_type": attachment.mime_type}


@router.get("/tickets/{ticket_id}/attachments/{attachment_id}/download")
def download_ticket_attachment(ticket_id: int, attachment_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    from app.models.maintenance import TicketAttachment
    attachment = db.query(TicketAttachment).filter(TicketAttachment.id == attachment_id, TicketAttachment.ticket_id == ticket_id).first()
    if not attachment or not os.path.isfile(attachment.storage_path):
        raise HTTPException(status_code=404, detail="Pièce jointe non trouvée")
    return FileResponse(attachment.storage_path, media_type=attachment.mime_type, filename=attachment.original_filename)


@router.post("/tickets/escalate")
def run_escalation(db: Session = Depends(get_db), current_user=Depends(require_write)):
    return escalate_overdue_tickets(db)


# ---------------------------------------------------------------------------
# Maintenance préventive
# ---------------------------------------------------------------------------
@router.post("/preventive/plans", status_code=201)
def create_preventive_plan_endpoint(data: PreventivePlanCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        plan = create_preventive_plan(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _preventive_plan_view(plan)


@router.get("/preventive/plans")
def list_preventive_plans(property_id: Optional[int] = None, maintenance_type: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    query = db.query(PreventiveMaintenancePlan).filter(PreventiveMaintenancePlan.status == "active")
    if property_id:
        query = query.filter(PreventiveMaintenancePlan.property_id == property_id)
    if maintenance_type:
        query = query.filter(PreventiveMaintenancePlan.maintenance_type == maintenance_type)
    plans = query.order_by(PreventiveMaintenancePlan.next_due_date).all()
    return {"data": [_preventive_plan_view(p) for p in plans], "count": len(plans)}


@router.post("/preventive/materialize")
def materialize_preventive(as_of: Optional[date] = Query(None), db: Session = Depends(get_db), current_user=Depends(require_write)):
    return materialize_planned_tasks(db, as_of)


@router.post("/preventive/tasks/{task_id}/complete")
def complete_preventive_task_endpoint(task_id: int, data: PreventiveTaskUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        task = complete_preventive_task(db, task_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": task.id, "status": task.status, "completed_at": task.completed_at, "cost": task.cost}


@router.get("/calendar")
def get_maintenance_calendar(
    start_date: date = Query(...),
    end_date: date = Query(...),
    property_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    return maintenance_calendar(db, start_date, end_date, property_id)


# ---------------------------------------------------------------------------
# Travaux lourds
# ---------------------------------------------------------------------------
@router.post("/projects", status_code=201)
def create_work_project_endpoint(data: WorkProjectCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        project = create_work_project(db, data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _work_project_view(project)


@router.get("/projects")
def list_work_projects(property_id: Optional[int] = None, status: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    query = db.query(WorkProject)
    if property_id:
        query = query.filter(WorkProject.property_id == property_id)
    if status:
        query = query.filter(WorkProject.status == status)
    projects = query.order_by(WorkProject.created_at.desc()).all()
    return {"data": [_work_project_view(p) for p in projects], "count": len(projects)}


@router.get("/projects/{project_id}")
def get_work_project(project_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    project = db.query(WorkProject).filter(WorkProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    view = _work_project_view(project)
    view["phases"] = [
        {"id": p.id, "name": p.name, "start_date": p.start_date, "end_date": p.end_date, "progress": p.progress, "display_order": p.display_order}
        for p in sorted(project.phases, key=lambda x: x.display_order)
    ]
    view["documents"] = [
        {"id": d.id, "document_type": d.document_type.value, "title": d.title, "filename": d.original_filename}
        for d in project.documents
    ]
    return view


@router.get("/projects/{project_id}/gantt")
def get_work_project_gantt(project_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return work_project_gantt(db, project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/projects/{project_id}")
def update_work_project_endpoint(project_id: int, data: WorkProjectUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    project = db.query(WorkProject).filter(WorkProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    try:
        project = update_work_project(db, project_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _work_project_view(project)


@router.post("/projects/{project_id}/phases", status_code=201)
def add_phase(project_id: int, data: WorkPhaseCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    project = db.query(WorkProject).filter(WorkProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    phase = add_work_phase(db, project_id, data)
    return {"id": phase.id, "name": phase.name, "start_date": phase.start_date, "end_date": phase.end_date, "progress": phase.progress}


@router.put("/projects/{project_id}/phases/{phase_id}")
def update_phase(project_id: int, phase_id: int, data: WorkPhaseUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    phase = db.query(WorkPhase).filter(WorkPhase.id == phase_id, WorkPhase.project_id == project_id).first()
    if not phase:
        raise HTTPException(status_code=404, detail="Phase non trouvée")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(phase, field, value)
    db.commit()
    db.refresh(phase)
    return {"id": phase.id, "name": phase.name, "progress": phase.progress}


@router.post("/projects/{project_id}/documents", status_code=201)
async def upload_work_document(
    project_id: int,
    file: UploadFile = File(...),
    document_type: WorkDocumentType = Form(WorkDocumentType.OTHER),
    title: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    project = db.query(WorkProject).filter(WorkProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    extension = Path(file.filename or "").suffix.lower().lstrip(".")
    if extension not in {"pdf", "jpg", "jpeg", "png", "doc", "docx", "xls", "xlsx"}:
        raise HTTPException(status_code=400, detail="Format non autorisé")
    content = await file.read()
    if not content or len(content) > 40 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier vide ou trop volumineux")
    directory = Path(settings.private_upload_dir_path) / "works" / str(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid.uuid4().hex}.{extension}"
    async with aiofiles.open(path, "wb") as output:
        await output.write(content)
    document = add_work_document(db, project_id, document_type, title or file.filename, str(path), file.filename or f"doc.{extension}", file.content_type, len(content))
    return {"id": document.id, "document_type": document_type.value, "title": document.title}


@router.post("/projects/{project_id}/receive")
def receive_project(project_id: int, comment: Optional[str] = Query(None), db: Session = Depends(get_db), current_user=Depends(require_write)):
    project = db.query(WorkProject).filter(WorkProject.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    try:
        project = receive_work_project(db, project_id, comment)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _work_project_view(project)


# ---------------------------------------------------------------------------
# Équipements
# ---------------------------------------------------------------------------
@router.post("/equipment", status_code=201)
def create_equipment_endpoint(data: EquipmentCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        equipment = create_equipment(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _equipment_view(equipment)


@router.get("/equipment")
def list_equipment(property_id: Optional[int] = None, category: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    query = db.query(Equipment)
    if property_id:
        query = query.filter(Equipment.property_id == property_id)
    if category:
        query = query.filter(Equipment.category == category)
    equipment = query.order_by(Equipment.name).all()
    return {"data": [_equipment_view(e) for e in equipment], "count": len(equipment)}


@router.get("/equipment/{equipment_id}")
def get_equipment(equipment_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="Équipement non trouvé")
    return _equipment_view(equipment)


@router.put("/equipment/{equipment_id}")
def update_equipment_endpoint(equipment_id: int, data: EquipmentUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="Équipement non trouvé")
    try:
        equipment = update_equipment(db, equipment_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) 
    return _equipment_view(equipment)


@router.post("/equipment/{equipment_id}/logs", status_code=201)
def add_equipment_log_endpoint(equipment_id: int, data: EquipmentLogCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise HTTPException(status_code=404, detail="Équipement non trouvé")
    try:
        log = add_equipment_log(db, equipment_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": log.id, "log_type": log.log_type, "description": log.description, "cost": log.cost}


@router.get("/equipment/{equipment_id}/history")
def equipment_history(equipment_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        return equipment_maintenance_history(db, equipment_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Suivi financier
# ---------------------------------------------------------------------------
@router.post("/expenses", status_code=201)
def create_expense(data: MaintenanceExpenseCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        expense = create_maintenance_expense(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _expense_view(expense)


@router.get("/expenses")
def list_expenses(property_id: Optional[int] = None, db: Session = Depends(get_db), current_user=Depends(require_read)):
    query = db.query(MaintenanceExpense)
    if property_id:
        query = query.filter(MaintenanceExpense.property_id == property_id)
    expenses = query.order_by(MaintenanceExpense.expense_date.desc()).all()
    return {"data": [_expense_view(e) for e in expenses], "count": len(expenses)}


@router.get("/budget")
def get_maintenance_budget(property_id: int = Query(...), year: int = Query(...), db: Session = Depends(get_db), current_user=Depends(require_read)):
    return maintenance_budget(db, property_id, year)


@router.get("/reporting")
def get_maintenance_reporting(year: int = Query(...), property_id: Optional[int] = Query(None), db: Session = Depends(get_db), current_user=Depends(require_read)):
    return maintenance_reporting(db, year, property_id)


# ---------------------------------------------------------------------------
# Helpers de sérialisation
# ---------------------------------------------------------------------------
def _provider_view(p: ServiceProvider) -> dict:
    return {
        "id": p.id,
        "reference": p.reference,
        "company_name": p.company_name,
        "contact_name": p.contact_name,
        "email": p.email,
        "phone": p.phone,
        "city": p.city,
        "siret": p.siret,
        "specialties": p.specialties or [],
        "intervention_zone": p.intervention_zone,
        "tariff_hourly": p.tariff_hourly,
        "insurance_reference": p.insurance_reference,
        "insurance_expiry": p.insurance_expiry,
        "certifications": p.certifications or [],
        "rating": p.rating,
        "rating_count": p.rating_count,
        "is_active": p.is_active,
    }


def _ticket_view(t: MaintenanceTicket) -> dict:
    return {
        "id": t.id,
        "reference": t.reference,
        "source": t.source.value,
        "tenant_id": t.tenant_id,
        "owner_id": t.owner_id,
        "property_id": t.property_id,
        "lease_id": t.lease_id,
        "category": t.category.value,
        "urgency": t.urgency.value,
        "status": t.status.value,
        "title": t.title,
        "description": t.description,
        "location": t.location,
        "sla_deadline": t.sla_deadline,
        "escalated": t.escalated,
        "provider_id": t.provider_id,
        "estimated_cost": t.estimated_cost,
        "final_cost": t.final_cost,
        "reported_at": t.reported_at,
        "resolved_at": t.resolved_at,
    }


def _quote_view(q: ProviderQuote) -> dict:
    return {
        "id": q.id,
        "reference": q.reference,
        "ticket_id": q.ticket_id,
        "provider_id": q.provider_id,
        "provider_name": q.provider.company_name if q.provider else "",
        "amount": q.amount,
        "description": q.description,
        "valid_until": q.valid_until,
        "status": q.status.value,
    }


def _purchase_order_view(o: PurchaseOrder) -> dict:
    return {
        "id": o.id,
        "reference": o.reference,
        "ticket_id": o.ticket_id,
        "quote_id": o.quote_id,
        "provider_id": o.provider_id,
        "provider_name": o.provider.company_name if o.provider else "",
        "amount": o.amount,
        "status": o.status.value,
        "description": o.description,
        "planned_date": o.planned_date,
        "issued_at": o.issued_at,
        "confirmed_at": o.confirmed_at,
    }


def _preventive_plan_view(p: PreventiveMaintenancePlan) -> dict:
    return {
        "id": p.id,
        "property_id": p.property_id,
        "maintenance_type": p.maintenance_type.value,
        "title": p.title,
        "interval_months": p.interval_months,
        "frequency_label": p.frequency_label,
        "next_due_date": p.next_due_date,
        "status": p.status.value,
        "assigned_provider_id": p.assigned_provider_id,
        "estimated_cost": p.estimated_cost,
        "last_completed_at": p.last_completed_at,
    }


def _work_project_view(p: WorkProject) -> dict:
    return {
        "id": p.id,
        "reference": p.reference,
        "property_id": p.property_id,
        "title": p.title,
        "description": p.description,
        "project_type": p.project_type,
        "status": p.status.value,
        "budget": p.budget,
        "actual_cost": p.actual_cost,
        "start_date": p.start_date,
        "end_date": p.end_date,
        "progress": p.progress,
        "responsible": p.responsible,
    }


def _equipment_view(e: Equipment) -> dict:
    return {
        "id": e.id,
        "reference": e.reference,
        "property_id": e.property_id,
        "name": e.name,
        "category": e.category,
        "brand": e.brand,
        "model": e.model,
        "serial_number": e.serial_number,
        "location": e.location,
        "installation_date": e.installation_date,
        "warranty_until": e.warranty_until,
        "maintenance_contract": e.maintenance_contract,
        "replacement_date": e.replacement_date,
        "status": e.status.value,
    }


def _expense_view(e: MaintenanceExpense) -> dict:
    return {
        "id": e.id,
        "reference": e.reference,
        "property_id": e.property_id,
        "ticket_id": e.ticket_id,
        "project_id": e.project_id,
        "amount": e.amount,
        "vat_rate": e.vat_rate,
        "expense_date": e.expense_date,
        "imputation": e.imputation.value,
        "cost_type": e.cost_type,
        "description": e.description,
        "provider_name": e.provider_name,
        "paid": e.paid,
    }
