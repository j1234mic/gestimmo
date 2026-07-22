from sqlalchemy import (
    Column, Integer, String, Float, Text, Boolean,
    DateTime, Enum, ForeignKey, Date
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class TransactionType(str, enum.Enum):
    RENTAL_INCOME = "rental_income"
    CHARGES = "charges"
    OWNER_PAYMENT = "owner_payment"
    MANAGEMENT_FEE = "management_fee"
    MAINTENANCE = "maintenance"
    TAX = "tax"
    INSURANCE = "insurance"
    OTHER = "other"


class OwnerTransaction(Base):
    __tablename__ = "owner_transactions"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False)
    property_id = Column(Integer, nullable=True)  # Pas de FK
    
    transaction_type = Column(Enum(TransactionType), nullable=False)
    reference = Column(String(50), unique=True)
    
    amount = Column(Float, nullable=False)
    vat_amount = Column(Float, default=0)
    
    transaction_date = Column(Date, nullable=False)
    period_start = Column(Date)
    period_end = Column(Date)
    
    description = Column(Text)
    category = Column(String(100))
    
    status = Column(String(20), default="completed")
    payment_method = Column(String(50))
    
    document_url = Column(String(500))
    notes = Column(Text)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations - LIEN DIRECT sans backref problématique
    owner = relationship("Owner", backref="transactions")


class OwnerBalance(Base):
    __tablename__ = "owner_balances"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="CASCADE"), unique=True)
    
    current_balance = Column(Float, default=0)
    total_income = Column(Float, default=0)
    total_expenses = Column(Float, default=0)
    total_paid = Column(Float, default=0)
    
    last_calculated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    owner = relationship("Owner", backref="balance", uselist=False)