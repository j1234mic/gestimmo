from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="CASCADE"), nullable=False)
    report_type = Column(String(50))  # monthly, quarterly, annual
    period_start = Column(DateTime)
    period_end = Column(DateTime)
    file_url = Column(String(500))  # chemin vers le fichier généré
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("Owner", backref="reports")