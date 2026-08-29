# backend/app/routes/history.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date

from app.database import get_db
from app.auth import require_read, require_write
from app.models.property import Property, PropertyHistory
from app.models.tenant import Lease, RentPayment, Tenant
from app.models.maintenance import MaintenanceTicket
from app.services.property_service import add_history_entry

router = APIRouter(prefix="/api/properties/{property_id}/history", tags=["History"])


@router.get("/")
def list_history(
    property_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Lister l'historique complet d'un bien."""
    property_obj = db.query(Property).filter(Property.id == property_id).first()
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")

    history = db.query(PropertyHistory).filter(
        PropertyHistory.property_id == property_id
    ).all()

    rows = [
        {
            "id": h.id,
            "source": "property",
            "event_type": h.event_type,
            "description": h.description,
            "details": h.details,
            "date": h.date.isoformat() if h.date else None,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        }
        for h in history
    ]

    # Historique des locataires / baux rattachés au bien
    leases = db.query(Lease).filter(Lease.property_id == property_id).all()
    for lease in leases:
        tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
        tenant_name = f"{tenant.first_name} {tenant.last_name}" if tenant else "locataire inconnu"
        rows.append({
            "id": f"lease-{lease.id}",
            "source": "lease",
            "event_type": "tenant_history",
            "description": f"Bail {lease.reference} — {tenant_name}",
            "details": {
                "lease_id": lease.id,
                "tenant_id": lease.tenant_id,
                "status": lease.status.value if hasattr(lease.status, "value") else lease.status,
                "start_date": lease.start_date.isoformat() if lease.start_date else None,
                "end_date": lease.end_date.isoformat() if lease.end_date else None,
                "monthly_rent": lease.monthly_rent,
            },
            "date": lease.start_date.isoformat() if lease.start_date else None,
            "created_at": lease.created_at.isoformat() if lease.created_at else None,
        })

    # Historique des loyers
    payments = db.query(RentPayment).join(Lease, RentPayment.lease_id == Lease.id).filter(
        Lease.property_id == property_id
    ).order_by(RentPayment.due_date.desc()).all()
    for payment in payments:
        rows.append({
            "id": f"payment-{payment.id}",
            "source": "rent",
            "event_type": "rent_change",
            "description": f"Loyer {payment.period} — payé {payment.amount_paid or 0:,.2f} € sur {payment.amount_due:,.2f} €",
            "details": {
                "payment_id": payment.id,
                "lease_id": payment.lease_id,
                "tenant_id": payment.tenant_id,
                "period": payment.period,
                "amount_due": payment.amount_due,
                "amount_paid": payment.amount_paid,
                "status": payment.status.value if hasattr(payment.status, "value") else payment.status,
            },
            "date": payment.due_date.isoformat() if payment.due_date else None,
            "created_at": payment.created_at.isoformat() if payment.created_at else None,
        })

    # Historique des demandes d'intervention / travaux
    tickets = db.query(MaintenanceTicket).filter(
        MaintenanceTicket.property_id == property_id
    ).order_by(MaintenanceTicket.reported_at.desc()).all()
    for ticket in tickets:
        status = ticket.status.value if hasattr(ticket.status, "value") else ticket.status
        rows.append({
            "id": f"ticket-{ticket.id}",
            "source": "maintenance",
            "event_type": "renovation",
            "description": f"Ticket {ticket.reference} — {ticket.title}",
            "details": {
                "ticket_id": ticket.id,
                "category": ticket.category.value if hasattr(ticket.category, "value") else ticket.category,
                "urgency": ticket.urgency.value if hasattr(ticket.urgency, "value") else ticket.urgency,
                "status": status,
                "estimated_cost": ticket.estimated_cost,
                "final_cost": ticket.final_cost,
            },
            "date": ticket.reported_at.date().isoformat() if ticket.reported_at else None,
            "created_at": ticket.reported_at.isoformat() if ticket.reported_at else None,
        })

    rows.sort(key=lambda x: (x.get("date") or "", x.get("created_at") or ""), reverse=True)

    return {
        "data": rows,
        "total": len(rows)
    }


@router.post("/")
def add_history(
    property_id: int,
    event_type: str,
    description: str,
    date: date,
    details: Optional[dict] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Ajouter une entrée dans l'historique."""
    property_obj = db.query(Property).filter(Property.id == property_id).first()
    if not property_obj:
        raise HTTPException(status_code=404, detail="Bien non trouvé")

    entry = add_history_entry(db, property_id, event_type, description, date, details)
    
    return {
        "id": entry.id,
        "event_type": entry.event_type,
        "description": entry.description,
        "date": entry.date.isoformat() if entry.date else None,
    }


@router.delete("/{history_id}")
def delete_history(
    property_id: int,
    history_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Supprimer une entrée d'historique."""
    entry = db.query(PropertyHistory).filter(
        PropertyHistory.id == history_id,
        PropertyHistory.property_id == property_id
    ).first()

    if not entry:
        raise HTTPException(status_code=404, detail="Entrée non trouvée")

    db.delete(entry)
    db.commit()

    return {"message": "Entrée supprimée", "history_id": history_id}