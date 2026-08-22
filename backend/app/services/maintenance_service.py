"""Services métier du module 6 : maintenance et travaux.

Centralise le workflow d'intervention (avec SLA et escalade), l'annuaire des
prestataires, la comparaison de devis, la maintenance préventive, la gestion
des travaux lourds, le suivi financier et l'inventaire des équipements.
"""

import uuid
from datetime import date, datetime, timezone, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.maintenance import (
    Equipment,
    EquipmentLog,
    MaintenanceExpense,
    MaintenanceTicket,
    PreventiveMaintenancePlan,
    PreventiveMaintenanceTask,
    ProviderEvaluation,
    ProviderQuote,
    PurchaseOrder,
    PurchaseOrderStatus,
    QuoteStatus,
    ServiceProvider,
    TicketAttachment,
    TicketCategory,
    TicketSource,
    TicketStatus,
    TicketStatusHistory,
    TicketUrgency,
    WorkDocument,
    WorkDocumentType,
    WorkPhase,
    WorkProject,
    WorkProjectStatus,
)
from app.models.tenant import Lease, Tenant, PaymentStatus
from app.models.property import Property


# Délais maxima (en heures) par niveau d'urgence pour le SLA.
SLA_HOURS = {
    TicketUrgency.LOW: 72,        # 3 jours
    TicketUrgency.MEDIUM: 48,     # 2 jours
    TicketUrgency.HIGH: 12,       # 12h
    TicketUrgency.CRITICAL: 4,    # 4h
}


def generate_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


# ---------------------------------------------------------------------------
# SLA
# ---------------------------------------------------------------------------
def sla_deadline_for(urgency: TicketUrgency, reported_at: datetime = None) -> datetime:
    """Retourne l'échéance SLA pour un niveau d'urgence."""
    base = reported_at or _now()
    hours = SLA_HOURS.get(urgency, SLA_HOURS[TicketUrgency.MEDIUM])
    return base + timedelta(hours=hours)


def _to_aware_utc(value) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def is_sla_breached(ticket: MaintenanceTicket) -> bool:
    if not ticket.sla_deadline:
        return False
    deadline = _to_aware_utc(ticket.sla_deadline)
    return _now() > deadline and ticket.status not in (
        TicketStatus.CLOSED,
        TicketStatus.COMPLETED,
        TicketStatus.CANCELLED,
    )


def escalate_overdue_tickets(db: Session) -> Dict:
    """Escalade automatique des tickets ayant dépassé leur SLA."""
    now = _now()
    overdue = db.query(MaintenanceTicket).filter(
        MaintenanceTicket.sla_deadline.isnot(None),
        MaintenanceTicket.sla_deadline < now,
        MaintenanceTicket.escalated.is_(False),
        MaintenanceTicket.status.notin_([TicketStatus.CLOSED, TicketStatus.COMPLETED, TicketStatus.CANCELLED]),
    ).all()
    count = 0
    for ticket in overdue:
        ticket.escalated = True
        _record_status(db, ticket, ticket.status, note="Escalade automatique : SLA dépassé", changed_by="system", notify=False)
        _escalation_notification(db, ticket)
        count += 1
    db.commit()
    return {"escalated": count}


def _escalation_notification(db: Session, ticket: MaintenanceTicket) -> None:
    """Alerte spécifique d'escalade envoyée au gestionnaire/propriétaire."""
    message = f"SLA dépassé pour le ticket {ticket.reference} ({ticket.title}) — urgence {ticket.urgency.value}"
    if ticket.owner_id:
        from app.models.notification import Notification
        db.add(Notification(owner_id=ticket.owner_id, type="warning", title="Escalade SLA maintenance", content=message))
    if ticket.tenant_id:
        from app.models.tenant import TenantNotification
        db.add(TenantNotification(
            tenant_id=ticket.tenant_id,
            channel="in_app",
            notification_type="maintenance",
            title=f"Ticket {ticket.reference} en escalade",
            content="Votre demande dépasse le délai prévu, elle a été escaladée en priorité.",
        ))


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
def create_ticket(db: Session, data, created_by: str = None) -> MaintenanceTicket:
    property_obj = db.query(Property).filter(Property.id == data.property_id).first()
    if not property_obj:
        raise ValueError("Bien immobilier non trouvé")

    deadline = sla_deadline_for(data.urgency)
    ticket = MaintenanceTicket(
        reference=generate_reference("TKT"),
        source=data.source,
        tenant_id=data.tenant_id,
        owner_id=data.owner_id,
        property_id=data.property_id,
        lease_id=data.lease_id,
        category=data.category,
        urgency=data.urgency,
        status=TicketStatus.NEW,
        title=data.title,
        description=data.description,
        location=data.location,
        provider_id=data.provider_id,
        estimated_cost=data.estimated_cost,
        sla_deadline=deadline,
        created_by=created_by,
    )
    db.add(ticket)
    db.flush()
    _record_status(db, ticket, TicketStatus.NEW, note="Ticket créé", changed_by=created_by)
    # Création automatique d'un message vers le locataire si présent.
    if ticket.tenant_id and created_by:
        _notify_tenant(db, ticket, created_by)
    db.commit()
    db.refresh(ticket)
    return ticket


def _notify_tenant(db: Session, ticket: MaintenanceTicket, actor: str) -> None:
    from app.models.tenant import TenantNotification
    db.add(TenantNotification(
        tenant_id=ticket.tenant_id,
        channel="in_app",
        notification_type="maintenance",
        title=f"Demande d'intervention {ticket.reference}",
        content=ticket.title,
    ))


# Libellés utilisés pour les notifications automatiques à chaque étape du
# workflow d'intervention (locataire, propriétaire et in-app gestionnaire).
STATUS_NOTIFICATION_LABELS = {
    TicketStatus.NEW: "Votre demande a été enregistrée",
    TicketStatus.AWAITING_OWNER: "Votre demande est en attente de validation du propriétaire",
    TicketStatus.VALIDATED: "Votre demande a été validée",
    TicketStatus.PROVIDER_ASSIGNED: "Un prestataire a été assigné à votre demande",
    TicketStatus.QUOTE_PENDING: "Un devis est en attente pour votre demande",
    TicketStatus.QUOTE_VALIDATED: "Le devis de votre demande a été validé",
    TicketStatus.PLANNED: "Une intervention a été planifiée",
    TicketStatus.IN_PROGRESS: "L'intervention est en cours",
    TicketStatus.COMPLETED: "L'intervention est terminée",
    TicketStatus.QUALITY_CONTROL: "L'intervention est en cours de contrôle qualité",
    TicketStatus.CLOSED: "Votre demande a été clôturée",
    TicketStatus.CANCELLED: "Votre demande a été annulée",
}


def _notify_status_change(db: Session, ticket: MaintenanceTicket, to_status: TicketStatus) -> None:
    """Notifie automatiquement locataire/propriétaire à chaque étape du workflow."""
    label = STATUS_NOTIFICATION_LABELS.get(to_status, f"Statut mis à jour : {to_status.value}")
    if ticket.tenant_id:
        from app.models.tenant import TenantNotification
        db.add(TenantNotification(
            tenant_id=ticket.tenant_id,
            channel="in_app",
            notification_type="maintenance",
            title=f"Ticket {ticket.reference}",
            content=f"{label} ({ticket.title})",
        ))
    if ticket.owner_id:
        from app.models.notification import Notification
        db.add(Notification(
            owner_id=ticket.owner_id,
            type="info",
            title=f"Ticket {ticket.reference}",
            content=f"{label} ({ticket.title})",
        ))


def _record_status(db, ticket, to_status: TicketStatus, note=None, changed_by=None, notify: bool = True) -> None:
    is_transition = ticket.status != to_status
    db.add(TicketStatusHistory(
        ticket_id=ticket.id,
        from_status=ticket.status if ticket.status else None,
        to_status=to_status,
        note=note,
        changed_by=changed_by,
    ))
    ticket.status = to_status
    if to_status == TicketStatus.COMPLETED:
        ticket.resolved_at = _now()
    elif to_status == TicketStatus.CLOSED:
        ticket.closed_at = _now()
    if notify and is_transition:
        _notify_status_change(db, ticket, to_status)


def change_status(db: Session, ticket_id: int, to_status: TicketStatus, note=None, changed_by=None) -> MaintenanceTicket:
    ticket = db.query(MaintenanceTicket).filter(MaintenanceTicket.id == ticket_id).first()
    if not ticket:
        raise ValueError("Ticket non trouvé")
    valid_transitions = _VALID_TRANSITIONS.get(ticket.status, set()) | {ticket.status}
    if to_status not in valid_transitions:
        raise ValueError(f"Transition invalide {ticket.status.value} → {to_status.value}")
    _record_status(db, ticket, to_status, note=note, changed_by=changed_by)
    db.commit()
    db.refresh(ticket)
    return ticket


_VALID_TRANSITIONS = {
    TicketStatus.NEW: {TicketStatus.NEW, TicketStatus.AWAITING_OWNER, TicketStatus.VALIDATED, TicketStatus.CANCELLED},
    TicketStatus.AWAITING_OWNER: {TicketStatus.AWAITING_OWNER, TicketStatus.VALIDATED, TicketStatus.CANCELLED},
    TicketStatus.VALIDATED: {TicketStatus.VALIDATED, TicketStatus.PROVIDER_ASSIGNED, TicketStatus.QUOTE_PENDING, TicketStatus.PLANNED, TicketStatus.CANCELLED},
    TicketStatus.PROVIDER_ASSIGNED: {TicketStatus.PROVIDER_ASSIGNED, TicketStatus.QUOTE_PENDING, TicketStatus.PLANNED, TicketStatus.CANCELLED},
    TicketStatus.QUOTE_PENDING: {TicketStatus.QUOTE_PENDING, TicketStatus.QUOTE_VALIDATED, TicketStatus.PLANNED, TicketStatus.CANCELLED},
    TicketStatus.QUOTE_VALIDATED: {TicketStatus.QUOTE_VALIDATED, TicketStatus.PLANNED, TicketStatus.CANCELLED},
    TicketStatus.PLANNED: {TicketStatus.PLANNED, TicketStatus.IN_PROGRESS, TicketStatus.CANCELLED},
    TicketStatus.IN_PROGRESS: {TicketStatus.IN_PROGRESS, TicketStatus.COMPLETED, TicketStatus.CANCELLED},
    TicketStatus.COMPLETED: {TicketStatus.COMPLETED, TicketStatus.QUALITY_CONTROL, TicketStatus.CLOSED},
    TicketStatus.QUALITY_CONTROL: {TicketStatus.QUALITY_CONTROL, TicketStatus.CLOSED, TicketStatus.IN_PROGRESS},
    TicketStatus.CLOSED: {TicketStatus.CLOSED},
    TicketStatus.CANCELLED: {TicketStatus.CANCELLED},
}


def attach_file(db: Session, ticket_id: int, storage_path: str, filename: str, mime_type: str, file_size: int, caption=None) -> TicketAttachment:
    ticket = db.query(MaintenanceTicket).filter(MaintenanceTicket.id == ticket_id).first()
    if not ticket:
        raise ValueError("Ticket non trouvé")
    attachment = TicketAttachment(
        ticket_id=ticket.id,
        original_filename=filename,
        storage_path=storage_path,
        mime_type=mime_type,
        file_size=file_size,
        caption=caption,
        captured_at=_now(),
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


# ---------------------------------------------------------------------------
# Prestataires
# ---------------------------------------------------------------------------
def create_provider(db: Session, data) -> ServiceProvider:
    provider = ServiceProvider(reference=generate_reference("PRV"), **data.model_dump())
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


def update_provider(db: Session, provider_id: int, data) -> ServiceProvider:
    provider = db.query(ServiceProvider).filter(ServiceProvider.id == provider_id).first()
    if not provider:
        raise ValueError("Prestataire non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(provider, field, value)
    db.commit()
    db.refresh(provider)
    return provider


def add_provider_quote(db: Session, ticket_id: int, data) -> ProviderQuote:
    ticket = db.query(MaintenanceTicket).filter(MaintenanceTicket.id == ticket_id).first()
    if not ticket:
        raise ValueError("Ticket non trouvé")
    provider = db.query(ServiceProvider).filter(ServiceProvider.id == data.provider_id).first()
    if not provider:
        raise ValueError("Prestataire non trouvé")
    quote = ProviderQuote(reference=generate_reference("DEV"), ticket_id=ticket.id, **data.model_dump())
    db.add(quote)
    ticket.status = TicketStatus.QUOTE_PENDING
    db.commit()
    db.refresh(quote)
    return quote


def accept_quote(db: Session, quote_id: int) -> ProviderQuote:
    quote = db.query(ProviderQuote).filter(ProviderQuote.id == quote_id).first()
    if not quote:
        raise ValueError("Devis non trouvé")
    quote.status = QuoteStatus.ACCEPTED
    for other in quote.ticket.quotes:
        if other.id != quote.id and other.status == QuoteStatus.ACCEPTED:
            other.status = QuoteStatus.REJECTED
    quote.ticket.provider_id = quote.provider_id
    quote.ticket.estimated_cost = quote.amount
    _record_status(db, quote.ticket, TicketStatus.QUOTE_VALIDATED, note=f"Devis {quote.reference} accepté", changed_by=None)
    db.commit()
    db.refresh(quote)
    return quote


def compare_quotes(db: Session, ticket_id: int) -> Dict:
    ticket = db.query(MaintenanceTicket).filter(MaintenanceTicket.id == ticket_id).first()
    if not ticket:
        raise ValueError("Ticket non trouvé")
    quotes = sorted(ticket.quotes, key=lambda q: q.amount)
    cheapest = quotes[0] if quotes else None
    return {
        "ticket_id": ticket.id,
        "ticket_title": ticket.title,
        "quotes": [
            {
                "id": q.id,
                "reference": q.reference,
                "provider_id": q.provider_id,
                "provider_name": q.provider.company_name if q.provider else "",
                "provider_rating": q.provider.rating if q.provider else 0,
                "amount": q.amount,
                "status": q.status.value,
                "valid_until": q.valid_until,
            }
            for q in quotes
        ],
        "cheapest_quote_id": cheapest.id if cheapest else None,
        "cheapest_amount": cheapest.amount if cheapest else None,
        "best_value_quote_id": cheapest.id if cheapest else None,
    }


def create_purchase_order(db: Session, ticket_id: int, data) -> PurchaseOrder:
    """Émet un bon de commande auprès d'un prestataire pour un ticket."""
    ticket = db.query(MaintenanceTicket).filter(MaintenanceTicket.id == ticket_id).first()
    if not ticket:
        raise ValueError("Ticket non trouvé")
    provider = db.query(ServiceProvider).filter(ServiceProvider.id == data.provider_id).first()
    if not provider:
        raise ValueError("Prestataire non trouvé")
    if data.quote_id:
        quote = db.query(ProviderQuote).filter(ProviderQuote.id == data.quote_id, ProviderQuote.ticket_id == ticket_id).first()
        if not quote:
            raise ValueError("Devis non trouvé pour ce ticket")
    order = PurchaseOrder(
        reference=generate_reference("BDC"),
        ticket_id=ticket.id,
        quote_id=data.quote_id,
        provider_id=data.provider_id,
        amount=data.amount,
        description=data.description,
        planned_date=data.planned_date,
        status=PurchaseOrderStatus.DRAFT,
    )
    db.add(order)
    ticket.provider_id = data.provider_id
    if ticket.status in (TicketStatus.VALIDATED, TicketStatus.QUOTE_VALIDATED):
        _record_status(db, ticket, TicketStatus.PROVIDER_ASSIGNED, note=f"Bon de commande {order.reference} émis", changed_by=None)
    db.commit()
    db.refresh(order)
    return order


def update_purchase_order_status(db: Session, order_id: int, status: PurchaseOrderStatus) -> PurchaseOrder:
    order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not order:
        raise ValueError("Bon de commande non trouvé")
    order.status = status
    if status == PurchaseOrderStatus.CONFIRMED:
        order.confirmed_at = _now()
    db.commit()
    db.refresh(order)
    return order


def add_provider_evaluation(db: Session, ticket_id: int, data) -> ProviderEvaluation:
    ticket = db.query(MaintenanceTicket).filter(MaintenanceTicket.id == ticket_id).first()
    if not ticket:
        raise ValueError("Ticket non trouvé")
    provider = db.query(ServiceProvider).filter(ServiceProvider.id == data.provider_id).first()
    if not provider:
        raise ValueError("Prestataire non trouvé")
    evaluation = ProviderEvaluation(ticket_id=ticket.id, provider_id=provider.id, **data.model_dump())
    db.add(evaluation)
    # Recalcul de la note moyenne.
    ratings = db.query(ProviderEvaluation.rating).filter(ProviderEvaluation.provider_id == provider.id, ProviderEvaluation.rating.isnot(None)).all()
    if ratings:
        provider.rating = round(sum(r[0] for r in ratings) / len(ratings), 2)
        provider.rating_count = len(ratings)
    db.commit()
    db.refresh(evaluation)
    return evaluation


# ---------------------------------------------------------------------------
# Maintenance préventive
# ---------------------------------------------------------------------------
def create_preventive_plan(db: Session, data) -> PreventiveMaintenancePlan:
    plan = PreventiveMaintenancePlan(
        property_id=data.property_id,
        maintenance_type=data.maintenance_type,
        title=data.title or data.maintenance_type.value,
        interval_months=data.interval_months,
        frequency_label=data.frequency_label,
        next_due_date=data.next_due_date,
        assigned_provider_id=data.assigned_provider_id,
        estimated_cost=data.estimated_cost,
        notes=data.notes,
        status="active",
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def materialize_planned_tasks(db: Session, as_of: Optional[date] = None) -> Dict:
    """Crée les tâches de maintenance préventive arrivées à échéance.

    Alimente le calendrier de maintenance et déclenche des alertes.
    """
    reference_date = as_of or date.today()
    plans = db.query(PreventiveMaintenancePlan).filter(
        PreventiveMaintenancePlan.status == "active",
        PreventiveMaintenancePlan.next_due_date <= reference_date,
    ).all()
    created = []
    for plan in plans:
        existing = db.query(PreventiveMaintenanceTask).filter(
            PreventiveMaintenanceTask.plan_id == plan.id,
            PreventiveMaintenanceTask.scheduled_date == plan.next_due_date,
        ).first()
        if existing:
            continue
        task = PreventiveMaintenanceTask(
            reference=generate_reference("MAINT"),
            plan_id=plan.id,
            scheduled_date=plan.next_due_date,
            status="scheduled",
        )
        db.add(task)
        db.flush()
        created.append({"task_id": task.id, "plan_id": plan.id, "scheduled_date": plan.next_due_date, "maintenance_type": plan.maintenance_type.value})
        # Planifie la prochaine occurrence.
        plan.next_due_date = _add_months(plan.next_due_date, plan.interval_months)
    db.commit()
    return {"as_of": reference_date, "created": created, "count": len(created)}


def _add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    last_day = 28
    if month == 12:
        last_day = 31
    elif month in (1, 3, 5, 7, 8, 10):
        last_day = 31
    elif month in (4, 6, 9, 11):
        last_day = 30
    return date(year, month, min(value.day, last_day))


def complete_preventive_task(db: Session, task_id: int, data) -> PreventiveMaintenanceTask:
    task = db.query(PreventiveMaintenanceTask).filter(PreventiveMaintenanceTask.id == task_id).first()
    if not task:
        raise ValueError("Tâche non trouvée")
    task.status = data.status or task.status
    task.completed_at = data.completed_at or _now()
    task.cost = data.cost if data.cost is not None else task.cost
    task.performed_by = data.performed_by or task.performed_by
    task.observations = data.observations or task.observations
    if task.status == "done":
        task.plan.last_completed_at = _now()
        task.plan.status = "active"
    db.commit()
    db.refresh(task)
    return task


def maintenance_calendar(db: Session, start_date: date, end_date: date, property_id: Optional[int] = None) -> Dict:
    """Calendrier de maintenance sur une période."""
    query = db.query(PreventiveMaintenanceTask).filter(
        PreventiveMaintenanceTask.scheduled_date >= start_date,
        PreventiveMaintenanceTask.scheduled_date <= end_date,
    )
    if property_id:
        query = query.join(PreventiveMaintenancePlan).filter(PreventiveMaintenancePlan.property_id == property_id)
    tasks = query.order_by(PreventiveMaintenanceTask.scheduled_date).all()
    return {
        "start_date": start_date,
        "end_date": end_date,
        "tasks": [
            {
                "id": t.id,
                "reference": t.reference,
                "maintenance_type": t.plan.maintenance_type.value,
                "property_id": t.plan.property_id,
                "scheduled_date": t.scheduled_date,
                "status": t.status,
                "estimated_cost": t.cost,
            }
            for t in tasks
        ],
    }


# ---------------------------------------------------------------------------
# Travaux lourds
# ---------------------------------------------------------------------------
def create_work_project(db: Session, data, created_by: str = None) -> WorkProject:
    property_obj = db.query(Property).filter(Property.id == data.property_id).first()
    if not property_obj:
        raise ValueError("Bien immobilier non trouvé")
    project = WorkProject(
        reference=generate_reference("TRAV"),
        property_id=data.property_id,
        title=data.title,
        description=data.description,
        project_type=data.project_type,
        budget=data.budget,
        start_date=data.start_date,
        end_date=data.end_date,
        responsible=data.responsible,
        notes=data.notes,
        created_by=created_by,
        status=WorkProjectStatus.DRAFT,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def update_work_project(db: Session, project_id: int, data) -> WorkProject:
    project = db.query(WorkProject).filter(WorkProject.id == project_id).first()
    if not project:
        raise ValueError("Projet de travaux non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


def add_work_phase(db: Session, project_id: int, data) -> WorkPhase:
    project = db.query(WorkProject).filter(WorkProject.id == project_id).first()
    if not project:
        raise ValueError("Projet non trouvé")
    phase = WorkPhase(project_id=project.id, **data.model_dump())
    db.add(phase)
    db.commit()
    db.refresh(phase)
    return phase


def add_work_document(db: Session, project_id: int, document_type: WorkDocumentType, title: str, storage_path: str, filename: str, mime_type: str, file_size: int) -> WorkDocument:
    project = db.query(WorkProject).filter(WorkProject.id == project_id).first()
    if not project:
        raise ValueError("Projet non trouvé")
    document = WorkDocument(
        project_id=project.id,
        document_type=document_type,
        title=title,
        original_filename=filename,
        storage_path=storage_path,
        mime_type=mime_type,
        file_size=file_size,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def receive_work_project(db: Session, project_id: int, comment: str = None) -> WorkProject:
    project = db.query(WorkProject).filter(WorkProject.id == project_id).first()
    if not project:
        raise ValueError("Projet non trouvé")
    project.status = WorkProjectStatus.RECEIVED
    project.progress = 100
    if comment:
        project.notes = (project.notes or "") + f"\nRéception : {comment}"
    db.commit()
    db.refresh(project)
    return project


def work_project_gantt(db: Session, project_id: int) -> Dict:
    """Planning Gantt du projet : phases ordonnées avec dates et avancement."""
    project = db.query(WorkProject).filter(WorkProject.id == project_id).first()
    if not project:
        raise ValueError("Projet non trouvé")
    phases = sorted(project.phases, key=lambda p: (p.display_order, p.start_date or project.start_date or date.min))
    items = []
    for phase in phases:
        items.append({
            "id": phase.id,
            "name": phase.name,
            "start_date": phase.start_date,
            "end_date": phase.end_date,
            "progress": phase.progress,
            "display_order": phase.display_order,
            "duration_days": (phase.end_date - phase.start_date).days if phase.start_date and phase.end_date else None,
        })
    return {
        "project_id": project.id,
        "reference": project.reference,
        "title": project.title,
        "start_date": project.start_date,
        "end_date": project.end_date,
        "overall_progress": project.progress,
        "phases": items,
    }


def apply_quality_control(db: Session, ticket_id: int, data) -> MaintenanceTicket:
    """Contrôle qualité post-intervention avant clôture du ticket."""
    ticket = db.query(MaintenanceTicket).filter(MaintenanceTicket.id == ticket_id).first()
    if not ticket:
        raise ValueError("Ticket non trouvé")
    if ticket.status not in (TicketStatus.COMPLETED, TicketStatus.QUALITY_CONTROL):
        raise ValueError("Le contrôle qualité nécessite une intervention terminée")
    note = f"Contrôle qualité {'validé' if data.passed else 'refusé'}"
    if data.comment:
        note += f" : {data.comment}"
    if data.passed:
        _record_status(db, ticket, TicketStatus.CLOSED, note=note, changed_by=data.controlled_by)
    else:
        _record_status(db, ticket, TicketStatus.IN_PROGRESS, note=note, changed_by=data.controlled_by)
    db.commit()
    db.refresh(ticket)
    return ticket


# ---------------------------------------------------------------------------
# Équipements
# ---------------------------------------------------------------------------
def create_equipment(db: Session, data) -> Equipment:
    property_obj = db.query(Property).filter(Property.id == data.property_id).first()
    if not property_obj:
        raise ValueError("Bien immobilier non trouvé")
    equipment = Equipment(reference=generate_reference("EQP"), **data.model_dump())
    db.add(equipment)
    db.commit()
    db.refresh(equipment)
    return equipment


def update_equipment(db: Session, equipment_id: int, data) -> Equipment:
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise ValueError("Équipement non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(equipment, field, value)
    db.commit()
    db.refresh(equipment)
    return equipment


def add_equipment_log(db: Session, equipment_id: int, data) -> EquipmentLog:
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise ValueError("Équipement non trouvé")
    log = EquipmentLog(equipment_id=equipment.id, **data.model_dump())
    db.add(log)
    if data.log_type in ("panne", "maintenance"):
        equipment.status = "en_maintenance"
    db.commit()
    db.refresh(log)
    return log


def equipment_maintenance_history(db: Session, equipment_id: int) -> Dict:
    equipment = db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if not equipment:
        raise ValueError("Équipement non trouvé")
    return {
        "equipment": {
            "id": equipment.id,
            "reference": equipment.reference,
            "name": equipment.name,
            "category": equipment.category,
            "installation_date": equipment.installation_date,
            "warranty_until": equipment.warranty_until,
            "maintenance_contract": equipment.maintenance_contract,
            "replacement_date": equipment.replacement_date,
            "status": equipment.status.value,
        },
        "logs": [
            {"id": l.id, "log_type": l.log_type, "description": l.description, "cost": l.cost, "occurred_at": l.occurred_at}
            for l in sorted(equipment.logs, key=lambda x: x.occurred_at or _now(), reverse=True)
        ],
    }


# ---------------------------------------------------------------------------
# Suivi financier
# ---------------------------------------------------------------------------
def create_maintenance_expense(db: Session, data) -> MaintenanceExpense:
    property_obj = db.query(Property).filter(Property.id == data.property_id).first()
    if not property_obj:
        raise ValueError("Bien immobilier non trouvé")
    expense = MaintenanceExpense(reference=generate_reference("FMS"), **data.model_dump())
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


def maintenance_budget(db: Session, property_id: int, year: int) -> Dict:
    """Budget maintenance par bien : coûts réels vs prévisionnel."""
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    expenses = db.query(MaintenanceExpense).filter(
        MaintenanceExpense.property_id == property_id,
        MaintenanceExpense.expense_date >= start,
        MaintenanceExpense.expense_date <= end,
    ).all()
    actual = sum(float(e.amount) for e in expenses)
    by_imputation = {}
    for e in expenses:
        by_imputation[e.imputation.value] = by_imputation.get(e.imputation.value, 0) + float(e.amount)

    # Budget prévisionnel = somme des coûts estimés des plans préventifs + projets.
    plans = db.query(PreventiveMaintenancePlan).filter(
        PreventiveMaintenancePlan.property_id == property_id,
        PreventiveMaintenancePlan.status == "active",
    ).all()
    planned = sum(float(p.estimated_cost) for p in plans)
    projects = db.query(WorkProject).filter(
        WorkProject.property_id == property_id,
        WorkProject.start_date <= end,
        (WorkProject.end_date >= start) | (WorkProject.end_date.is_(None)),
    ).all()
    planned += sum(float(p.budget) for p in projects)
    difference = round(planned - actual, 2)
    return {
        "property_id": property_id,
        "year": year,
        "actual": round(actual, 2),
        "planned": round(planned, 2),
        "difference": difference,
        "progress_percent": round((actual / planned * 100) if planned else 0, 2),
        "by_imputation": by_imputation,
        "expense_count": len(expenses),
    }


def maintenance_reporting(db: Session, year: int, property_id: Optional[int] = None) -> Dict:
    """Reporting maintenance global."""
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    query = db.query(MaintenanceTicket)
    if property_id:
        query = query.filter(MaintenanceTicket.property_id == property_id)
    tickets = query.filter(
        MaintenanceTicket.reported_at >= datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc),
        MaintenanceTicket.reported_at <= datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc),
    ).all()
    by_status = {}
    by_category = {}
    for t in tickets:
        by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
        by_category[t.category.value] = by_category.get(t.category.value, 0) + 1

    expense_query = db.query(MaintenanceExpense)
    if property_id:
        expense_query = expense_query.filter(MaintenanceExpense.property_id == property_id)
    expenses = expense_query.filter(
        MaintenanceExpense.expense_date >= start,
        MaintenanceExpense.expense_date <= end,
    ).all()
    total_cost = sum(float(e.amount) for e in expenses)
    return {
        "year": year,
        "ticket_count": len(tickets),
        "by_status": by_status,
        "by_category": by_category,
        "total_cost": round(total_cost, 2),
        "expense_count": len(expenses),
    }
