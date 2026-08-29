# backend/app/services/accounting_service.py

import uuid
from sqlalchemy.orm import Session
from sqlalchemy import func as sqlfunc
from datetime import date, datetime
from typing import Optional

from app.models.accounting import OwnerTransaction, OwnerBalance, TransactionType
from app.models.owner import Owner, PropertyOwner
from app.models.property import Property
from app.models.tenant import Lease
from app.schemas.accounting import TransactionCreate
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import cm
import io
from datetime import date, datetime, timedelta    


def generate_reference():
    return f"TRX-{str(uuid.uuid4())[:8].upper()}"


def create_transaction(db: Session, data: TransactionCreate):
    reference = generate_reference()
    
    # ✅ Conversion sécurisée des dates
    if isinstance(data.transaction_date, str):
        tx_date = datetime.strptime(data.transaction_date, "%Y-%m-%d").date()
    else:
        tx_date = data.transaction_date or date.today()
    
    p_start = None
    if data.period_start:
        p_start = datetime.strptime(data.period_start, "%Y-%m-%d").date() if isinstance(data.period_start, str) else data.period_start
    
    p_end = None
    if data.period_end:
        p_end = datetime.strptime(data.period_end, "%Y-%m-%d").date() if isinstance(data.period_end, str) else data.period_end
    
    transaction = OwnerTransaction(
        reference=reference,
        transaction_type=data.transaction_type,
        amount=data.amount,
        vat_amount=data.vat_amount or 0,
        transaction_date=tx_date,
        period_start=p_start,
        period_end=p_end,
        description=data.description,
        category=data.category,
        status=data.status or "completed",
        payment_method=data.payment_method,
        notes=data.notes,
        owner_id=data.owner_id,
        property_id=data.property_id
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    
    update_balance(db, data.owner_id)
    db.commit()
    
    return transaction


def get_transactions(db: Session, owner_id: int, skip: int = 0, limit: int = 100, 
                     transaction_type: Optional[str] = None,
                     start_date: Optional[date] = None, end_date: Optional[date] = None):
    """Récupérer les transactions d'un propriétaire."""
    query = db.query(OwnerTransaction).filter(OwnerTransaction.owner_id == owner_id)
    
    if transaction_type:
        query = query.filter(OwnerTransaction.transaction_type == transaction_type)
    if start_date:
        query = query.filter(OwnerTransaction.transaction_date >= start_date)
    if end_date:
        query = query.filter(OwnerTransaction.transaction_date <= end_date)
    
    total = query.count()
    transactions = query.order_by(OwnerTransaction.transaction_date.desc()).offset(skip).limit(limit).all()
    
    return transactions, total


def update_balance(db: Session, owner_id: int):
    """Recalculer le solde d'un propriétaire."""
    # Calculer les totaux
    income = db.query(sqlfunc.coalesce(sqlfunc.sum(OwnerTransaction.amount), 0)).filter(
        OwnerTransaction.owner_id == owner_id,
        OwnerTransaction.amount > 0,
        OwnerTransaction.status == "completed"
    ).scalar() or 0
    
    expenses = db.query(sqlfunc.coalesce(sqlfunc.sum(OwnerTransaction.amount), 0)).filter(
        OwnerTransaction.owner_id == owner_id,
        OwnerTransaction.amount < 0,
        OwnerTransaction.status == "completed"
    ).scalar() or 0
    
    paid = db.query(sqlfunc.coalesce(sqlfunc.sum(OwnerTransaction.amount), 0)).filter(
        OwnerTransaction.owner_id == owner_id,
        OwnerTransaction.transaction_type == "owner_payment",
        OwnerTransaction.status == "completed"
    ).scalar() or 0
    
    # Récupérer ou créer le solde
    balance = db.query(OwnerBalance).filter(OwnerBalance.owner_id == owner_id).first()
    if not balance:
        balance = OwnerBalance(owner_id=owner_id)
        db.add(balance)
    
    balance.total_income = income
    balance.total_expenses = abs(expenses)
    balance.total_paid = abs(paid)
    balance.current_balance = income - abs(expenses) - abs(paid)
    balance.last_calculated_at = datetime.utcnow()
    
    db.flush()
    return balance


def get_balance(db: Session, owner_id: int):
    """Récupérer le solde d'un propriétaire."""
    balance = db.query(OwnerBalance).filter(OwnerBalance.owner_id == owner_id).first()
    if not balance:
        balance = update_balance(db, owner_id)
    return balance


def get_monthly_summary(db: Session, owner_id: int, year: int, month: int):
    """Résumé mensuel."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    
    transactions = db.query(OwnerTransaction).filter(
        OwnerTransaction.owner_id == owner_id,
        OwnerTransaction.transaction_date >= start,
        OwnerTransaction.transaction_date < end,
        OwnerTransaction.status == "completed"
    ).all()
    
    income = sum(t.amount for t in transactions if t.amount > 0)
    expenses = sum(abs(t.amount) for t in transactions if t.amount < 0)
    
    return {
        "period": f"{year}-{month:02d}",
        "total_income": income,
        "total_expenses": expenses,
        "balance": income - expenses,
        "transaction_count": len(transactions),
        "transactions": [
            {
                "id": t.id,
                "reference": t.reference,
                "type": t.transaction_type.value if t.transaction_type else None,
                "amount": t.amount,
                "date": t.transaction_date.isoformat(),
                "description": t.description
            }
            for t in transactions
        ]
    }


def get_owner_property_summary(db: Session, owner_id: int):
    """Synthèse financière par bien pour un propriétaire."""
    links = db.query(PropertyOwner).filter(PropertyOwner.owner_id == owner_id).all()
    results = []
    for link in links:
        prop = db.query(Property).filter(Property.id == link.property_id).first()
        if not prop:
            continue
        transactions = db.query(OwnerTransaction).filter(
            OwnerTransaction.owner_id == owner_id,
            OwnerTransaction.property_id == prop.id,
            OwnerTransaction.status == "completed",
        ).all()

        income = sum(t.amount for t in transactions if t.amount > 0)
        expenses = sum(abs(t.amount) for t in transactions if t.amount < 0)
        occupied = db.query(Lease).filter(
            Lease.property_id == prop.id,
            Lease.status == "active"
        ).count() > 0

        results.append({
            "property_id": prop.id,
            "reference": prop.reference,
            "title": prop.title,
            "city": prop.city,
            "status": prop.status.value if prop.status else None,
            "ownership_percentage": link.ownership_percentage,
            "is_main_owner": link.is_main_owner,
            "acquisition_date": link.acquisition_date.isoformat() if link.acquisition_date else None,
            "acquisition_price": link.acquisition_price,
            "current_rent": prop.rent_price,
            "current_sale_price": prop.sale_price,
            "occupied": occupied,
            "income": income,
            "expenses": expenses,
            "balance": income - expenses,
            "transaction_count": len(transactions),
        })
    total_income = sum(r["income"] for r in results)
    total_expenses = sum(r["expenses"] for r in results)
    return {
        "owner_id": owner_id,
        "total_income": total_income,
        "total_expenses": total_expenses,
        "total_balance": total_income - total_expenses,
        "properties": results,
    }


def delete_transaction(db: Session, transaction_id: int):
    """Supprimer une transaction."""
    t = db.query(OwnerTransaction).filter(OwnerTransaction.id == transaction_id).first()
    if t:
        owner_id = t.owner_id
        db.delete(t)
        update_balance(db, owner_id)
        db.commit()
    return {"message": "Transaction supprimée"}

def get_statement(db: Session, owner_id: int, year: int, period: str, month: int = None, quarter: int = None):
    """Générer un relevé mensuel/trimestriel/annuel."""
    from datetime import date
    
    if period == "monthly":
        # Valeur par défaut : janvier si le mois n'est pas précisé
        month = month or 1
        start = date(year, month, 1)
        if month == 12:
            end = date(year + 1, 1, 1)
        else:
            end = date(year, month + 1, 1)
        period_label = f"{month:02d}/{year}"
    elif period == "quarterly":
        # Valeur par défaut : 1er trimestre si non précisé
        quarter = quarter or 1
        start_month = (quarter - 1) * 3 + 1
        start = date(year, start_month, 1)
        end_month = start_month + 3
        if end_month > 12:
            end = date(year + 1, end_month - 12, 1)
        else:
            end = date(year, end_month, 1)
        period_label = f"T{quarter} {year}"
    elif period == "annual":
        start = date(year, 1, 1)
        end = date(year + 1, 1, 1)
        period_label = str(year)
    
    transactions = db.query(OwnerTransaction).filter(
        OwnerTransaction.owner_id == owner_id,
        OwnerTransaction.transaction_date >= start,
        OwnerTransaction.transaction_date < end,
        OwnerTransaction.status == "completed"
    ).order_by(OwnerTransaction.transaction_date).all()
    
    income = sum(t.amount for t in transactions if t.amount > 0)
    expenses = sum(abs(t.amount) for t in transactions if t.amount < 0)
    
    # Regrouper par type
    by_type = {}
    for t in transactions:
        ttype = t.transaction_type.value if t.transaction_type else "other"
        if ttype not in by_type:
            by_type[ttype] = 0
        by_type[ttype] += t.amount
    
    return {
        "period": period_label,
        "period_type": period,
        "start_date": start.isoformat(),
        "end_date": (end - timedelta(days=1)).isoformat(),
        "total_income": income,
        "total_expenses": expenses,
        "net_balance": income - expenses,
        "by_type": by_type,
        "transaction_count": len(transactions),
        "transactions": [
            {
                "id": t.id,
                "reference": t.reference,
                "type": t.transaction_type.value if t.transaction_type else None,
                "amount": t.amount,
                "date": t.transaction_date.isoformat(),
                "description": t.description
            }
            for t in transactions
        ]
    }


def generate_statement_pdf(statement: dict):
    """Générer un PDF à partir du relevé."""
    
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm)
    styles = getSampleStyleSheet()
    elements = []
    
    elements.append(Paragraph(f"Relevé de Gestion - {statement['period']}", styles['Title']))
    elements.append(Spacer(1, 0.5*cm))
    elements.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y')}", styles['Normal']))
    elements.append(Spacer(1, 1*cm))
    
    # Résumé
    summary_data = [
        ["Revenus", "Dépenses", "Solde net"],
        [f"{statement['total_income']:,.2f} €", f"{statement['total_expenses']:,.2f} €", f"{statement['net_balance']:,.2f} €"]
    ]
    table = Table(summary_data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2563eb')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('BACKGROUND', (0,1), (-1,1), colors.HexColor('#f8fafc')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTSIZE', (0,0), (-1,-1), 12),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 1*cm))
    
    # Détail par type
    elements.append(Paragraph("Détail par type", styles['Heading3']))
    for ttype, amount in statement['by_type'].items():
        elements.append(Paragraph(f"{ttype}: {amount:,.2f} €", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer


def get_global_overview(db: Session):
    """Synthèse globale de la comptabilité."""
    
    # Total des revenus
    total_income = db.query(sqlfunc.coalesce(sqlfunc.sum(OwnerTransaction.amount), 0)).filter(
        OwnerTransaction.amount > 0,
        OwnerTransaction.status == "completed"
    ).scalar() or 0
    
    # Total des dépenses
    total_expenses = db.query(sqlfunc.coalesce(sqlfunc.sum(OwnerTransaction.amount), 0)).filter(
        OwnerTransaction.amount < 0,
        OwnerTransaction.status == "completed"
    ).scalar() or 0
    
    # Total versé aux propriétaires
    total_paid = db.query(sqlfunc.coalesce(sqlfunc.sum(OwnerTransaction.amount), 0)).filter(
        OwnerTransaction.transaction_type == "owner_payment",
        OwnerTransaction.status == "completed"
    ).scalar() or 0
    
    # Nombre de propriétaires avec un solde positif
    from app.models.accounting import OwnerBalance
    positive_balances = db.query(OwnerBalance).filter(
        OwnerBalance.current_balance > 0
    ).count()
    
    # Top 5 propriétaires par revenus
    top_owners = db.query(
        Owner, sqlfunc.sum(OwnerTransaction.amount).label('total')
    ).join(OwnerTransaction).filter(
        OwnerTransaction.amount > 0,
        OwnerTransaction.status == "completed"
    ).group_by(Owner.id).order_by(sqlfunc.sum(OwnerTransaction.amount).desc()).limit(5).all()
    
    return {
        "total_income": float(total_income),
        "total_expenses": float(abs(total_expenses)),
        "total_paid_to_owners": float(abs(total_paid)),
        "net_in_account": float(total_income - abs(total_expenses) - abs(total_paid)),
        "positive_balances_count": positive_balances,
        "top_owners": [
            {
                "id": o.id,
                "name": o.company_name or f"{o.first_name or ''} {o.last_name or ''}".strip(),
                "total": float(total)
            }
            for o, total in top_owners
        ]
    }