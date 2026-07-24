from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
from app.models.owner import Mandate
from app.models.accounting import OwnerTransaction
from app.models.owner import Owner



def get_notifications(db: Session):
    """Récupérer toutes les notifications."""
    today = date.today()
    notifications = []
    
    # 1. Mandats qui expirent dans 30 jours
    threshold = today + timedelta(days=30)
    expiring_mandates = db.query(Mandate).filter(
        Mandate.status == "active",
        Mandate.end_date <= threshold,
        Mandate.end_date > today
    ).all()
    
    for m in expiring_mandates:
        days_left = (m.end_date - today).days
        notifications.append({
            "type": "mandate_expiring",
            "priority": "warning" if days_left <= 15 else "info",
            "title": f"Mandat {m.reference} expire bientôt",
            "message": f"Le mandat de {m.owner.company_name or f'{m.owner.first_name} {m.owner.last_name}'} expire dans {days_left} jours",
            "date": m.end_date.isoformat(),
            "link": f"/owners/{m.owner_id}"
        })
    
    # 2. Mandats déjà expirés
    expired = db.query(Mandate).filter(
        Mandate.status == "active",
        Mandate.end_date < today
    ).all()
    
    for m in expired:
        notifications.append({
            "type": "mandate_expired",
            "priority": "error",
            "title": f"Mandat {m.reference} expiré !",
            "message": f"Le mandat de {m.owner.company_name or f'{m.owner.first_name} {m.owner.last_name}'} a expiré le {m.end_date}",
            "date": m.end_date.isoformat(),
            "link": f"/owners/{m.owner_id}"
        })
    
    # 3. Propriétaires sans transaction depuis 60 jours
    two_months_ago = today - timedelta(days=60)
    inactive_owners = db.query(OwnerTransaction.owner_id).filter(
        OwnerTransaction.transaction_date >= two_months_ago
    ).distinct().all()
    active_owner_ids = [o[0] for o in inactive_owners]
    
    all_owners = db.query(Owner).filter(Owner.is_active == True).all()
    for owner in all_owners:
        if owner.id not in active_owner_ids and len(owner.properties) > 0:
            notifications.append({
                "type": "inactive_owner",
                "priority": "info",
                "title": "Aucune activité récente",
                "message": f"{owner.company_name or f'{owner.first_name} {owner.last_name}'} n'a pas eu de transaction depuis 60 jours",
                "link": f"/owners/{owner.id}"
            })
    
    # Trier par priorité
    priority_order = {"error": 0, "warning": 1, "info": 2}
    notifications.sort(key=lambda x: priority_order.get(x["priority"], 3))
    
    return notifications