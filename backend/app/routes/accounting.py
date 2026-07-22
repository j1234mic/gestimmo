# backend/app/routes/accounting.py

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from datetime import date
from datetime import timedelta
from app.database import get_db
from app.auth import require_read, require_write
from app.services.accounting_service import (
    create_transaction, generate_statement_pdf, get_transactions, get_balance,
    get_monthly_summary, delete_transaction

)
from app.schemas.accounting import TransactionCreate, TransactionResponse, BalanceResponse
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/accounting", tags=["Accounting"])


@router.post("/transactions", response_model=TransactionResponse, status_code=201)
def add_transaction(
    data: TransactionCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Ajouter une transaction comptable."""
    return create_transaction(db, data)


@router.get("/owners/{owner_id}/transactions")
def list_transactions(
    owner_id: int,
    transaction_type: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Lister les transactions d'un propriétaire."""
    skip = (page - 1) * limit
    transactions, total = get_transactions(db, owner_id, skip, limit, transaction_type, start_date, end_date)
    
    return {
        "data": transactions,
        "total": total,
        "page": page
    }


@router.get("/owners/{owner_id}/balance", response_model=BalanceResponse)
def get_owner_balance(
    owner_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Solde du compte propriétaire."""
    return get_balance(db, owner_id)


@router.get("/owners/{owner_id}/summary")
def get_owner_summary(
    owner_id: int,
    year: int = Query(...),
    month: int = Query(..., ge=1, le=12),
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Résumé mensuel."""
    return get_monthly_summary(db, owner_id, year, month)


@router.delete("/transactions/{transaction_id}")
def remove_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_write)
):
    """Supprimer une transaction."""
    return delete_transaction(db, transaction_id)

@router.get("/owners/{owner_id}/statement")
def get_owner_statement(
    owner_id: int,
    year: int = Query(...),
    period: str = Query("monthly", regex="^(monthly|quarterly|annual)$"),
    month: Optional[int] = Query(None, ge=1, le=12),
    quarter: Optional[int] = Query(None, ge=1, le=4),
    format: str = Query("json", regex="^(json|pdf)$"),
    db: Session = Depends(get_db),
    current_user = Depends(require_read)
):
    """Relevé de gestion (mensuel/trimestriel/annuel) en JSON ou PDF."""
    from datetime import date
    from app.services.accounting_service import get_statement
    
    statement = get_statement(db, owner_id, year, period, month, quarter)
    
    if format == "pdf":
        # Générer PDF
        buffer = generate_statement_pdf(statement)
        return StreamingResponse(buffer, media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=releve-{owner_id}-{year}-{period}.pdf"})
    
    return statement