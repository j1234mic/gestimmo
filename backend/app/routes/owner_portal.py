from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from typing import List, Optional
from datetime import date, datetime

from app.database import get_db
from app.models.owner import Owner
from app.models.property import Property
from app.models.accounting import OwnerTransaction, OwnerBalance
from app.models.message import Message
from app.schemas.accounting import TransactionResponse
from app.schemas.message import MessageResponse, MessageCreate
from app.schemas.owner import OwnerDetailResponse
from app.middleware.security import get_current_owner  # À adapter selon votre système d'auth

router = APIRouter(prefix="/owner-portal", tags=["Portail propriétaire"])

@router.get("/dashboard")
def get_dashboard(
    db: Session = Depends(get_db),
    current_owner: Owner = Depends(get_current_owner)
):
    """Tableau de bord personnalisé du propriétaire"""
    owner_id = current_owner.id

    # Solde actuel
    balance = db.query(OwnerBalance).filter(OwnerBalance.owner_id == owner_id).first()
    current_balance = balance.current_balance if balance else 0.0
    total_income = balance.total_income if balance else 0.0
    total_expenses = balance.total_expenses if balance else 0.0

    # Nombre de biens
    properties_count = db.query(Property).join(Property.owners).filter(Owner.id == owner_id).count()

    # Taux d'occupation global (exemple simple : propriétés louées / total)
    rented = db.query(Property).join(Property.owners).filter(
        Owner.id == owner_id,
        Property.status == "rented"
    ).count()
    occupancy_rate = (rented / properties_count * 100) if properties_count > 0 else 0

    # Mandats actifs
    active_mandates = db.query(Mandate).filter(
        Mandate.owner_id == owner_id,
        Mandate.status == "active"
    ).count()

    # Derniers messages non lus
    unread_messages = db.query(Message).filter(
        Message.recipient_id == owner_id,
        Message.recipient_type == "owner",
        Message.is_read == False
    ).count()

    return {
        "owner_id": owner_id,
        "current_balance": current_balance,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "properties_count": properties_count,
        "occupancy_rate": occupancy_rate,
        "active_mandates": active_mandates,
        "unread_messages": unread_messages
    }

@router.get("/transactions", response_model=List[TransactionResponse])
def get_owner_transactions(
    transaction_type: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db),
    current_owner: Owner = Depends(get_current_owner)
):
    """Consultation des revenus/charges du propriétaire"""
    query = db.query(OwnerTransaction).filter(OwnerTransaction.owner_id == current_owner.id)
    if transaction_type:
        query = query.filter(OwnerTransaction.transaction_type == transaction_type)
    if start_date:
        query = query.filter(OwnerTransaction.transaction_date >= start_date)
    if end_date:
        query = query.filter(OwnerTransaction.transaction_date <= end_date)
    return query.order_by(OwnerTransaction.transaction_date.desc()).all()

@router.get("/documents")
def get_owner_documents(
    db: Session = Depends(get_db),
    current_owner: Owner = Depends(get_current_owner)
):
    """Liste des documents disponibles pour le propriétaire"""
    # Documents provenant des propriétés
    property_docs = []
    properties = db.query(Property).join(Property.owners).filter(Owner.id == current_owner.id).all()
    for prop in properties:
        for doc in prop.documents:
            property_docs.append({
                "id": doc.id,
                "type": doc.type,
                "title": doc.title,
                "url": doc.url,
                "filename": doc.filename,
                "uploaded_at": doc.uploaded_at,
                "source": "property",
                "property_reference": prop.reference
            })

    # Documents de transactions (si document_url est présent)
    transaction_docs = []
    transactions = db.query(OwnerTransaction).filter(OwnerTransaction.owner_id == current_owner.id).all()
    for trans in transactions:
        if trans.document_url:
            transaction_docs.append({
                "id": trans.id,
                "type": "transaction_document",
                "title": f"Justificatif - {trans.reference}",
                "url": trans.document_url,
                "filename": None,
                "uploaded_at": trans.created_at,
                "source": "transaction",
                "transaction_reference": trans.reference
            })

    return {"property_documents": property_docs, "transaction_documents": transaction_docs}

@router.get("/messages", response_model=List[MessageResponse])
def get_owner_messages(
    db: Session = Depends(get_db),
    current_owner: Owner = Depends(get_current_owner)
):
    """Historique des messages échangés avec le gestionnaire"""
    messages = db.query(Message).filter(
        (Message.recipient_id == current_owner.id) | (Message.sender_id == current_owner.id)
    ).order_by(Message.created_at.desc()).all()
    return messages

@router.post("/messages", response_model=MessageResponse, status_code=201)
def send_message(
    message: MessageCreate,
    db: Session = Depends(get_db),
    current_owner: Owner = Depends(get_current_owner)
):
    """Envoi d'un message au gestionnaire (admin)"""
    # On suppose que le gestionnaire a un compte admin avec id=1 ou un rôle particulier
    # Pour simplifier, on envoie toujours au premier admin (à adapter)
    admin = db.query(Owner).filter(Owner.owner_type == "admin").first()  # Exemple : ajout d'un type admin fictif
    if not admin:
        raise HTTPException(status_code=404, detail="Aucun gestionnaire trouvé")

    db_message = Message(
        sender_id=current_owner.id,
        sender_type="owner",
        recipient_id=admin.id,
        recipient_type="admin",
        subject=message.subject,
        content=message.content,
        attachment_url=message.attachment_url
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message

@router.get("/tax-declaration")
def get_tax_declaration(
    year: int = Query(..., description="Année fiscale"),
    db: Session = Depends(get_db),
    current_owner: Owner = Depends(get_current_owner)
):
    """Déclaration fiscale : synthèse des revenus et charges pour une année"""
    start = date(year, 1, 1)
    end = date(year, 12, 31)

    incomes = db.query(func.sum(OwnerTransaction.amount)).filter(
        OwnerTransaction.owner_id == current_owner.id,
        OwnerTransaction.transaction_type.in_(["rental_income"]),
        OwnerTransaction.transaction_date.between(start, end)
    ).scalar() or 0.0

    deductible_charges = db.query(func.sum(OwnerTransaction.amount)).filter(
        OwnerTransaction.owner_id == current_owner.id,
        OwnerTransaction.transaction_type.in_(["charges", "management_fee", "maintenance", "tax", "insurance"]),
        OwnerTransaction.transaction_date.between(start, end)
    ).scalar() or 0.0

    net_taxable = incomes - deductible_charges

    # Régime fiscal
    regime = current_owner.tax_regime.value if current_owner.tax_regime else "micro_foncier"
    if regime == "micro_foncier":
        # Abattement 30% (simplification)
        taxable_after_abatement = incomes * 0.7
    else:
        taxable_after_abatement = net_taxable

    return {
        "year": year,
        "regime": regime,
        "gross_income": incomes,
        "deductible_charges": deductible_charges,
        "net_taxable": net_taxable,
        "taxable_after_abatement": taxable_after_abatement
    }