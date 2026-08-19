from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class ReportResponse(BaseModel):
    id: int
    owner_id: int
    report_type: str
    period_start: datetime
    period_end: datetime
    file_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ReportGenerate(BaseModel):
    report_type: str  # monthly, quarterly, annual
    period_start: datetime
    period_end: datetime