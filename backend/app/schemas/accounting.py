# backend/app/schemas/accounting.py

from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime
from app.models.accounting import TransactionType


class TransactionCreate(BaseModel):
    owner_id: int
    property_id: Optional[int] = None
    transaction_type: str = "other"
    amount: float
    vat_amount: Optional[float] = 0
    transaction_date: str  # YYYY-MM-DD
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = "completed"
    payment_method: Optional[str] = None
    notes: Optional[str] = None


class TransactionResponse(BaseModel):
    id: int
    owner_id: int
    property_id: Optional[int] = None
    transaction_type: str
    reference: str
    amount: float
    transaction_date: date
    description: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class BalanceResponse(BaseModel):
    owner_id: int
    current_balance: float
    total_income: float
    total_expenses: float
    total_paid: float
    last_calculated_at: Optional[datetime] = None