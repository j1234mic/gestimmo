"""Modules 14-15: mobile field operations and insurance claims."""
import enum
from sqlalchemy import Column, Integer, String, Text, Float, Date, DateTime, ForeignKey, JSON, Enum
from sqlalchemy.sql import func
from app.database import Base

class InsuranceType(str, enum.Enum):
    PNO="pno"; MRH="mrh"; GLI="gli"; RC="responsabilite_civile"; CONDO="copropriete"
class ClaimType(str, enum.Enum):
    WATER="degat_des_eaux"; FIRE="incendie"; THEFT="vol"; NATURAL="catastrophe_naturelle"; OTHER="autre"
class ClaimStatus(str, enum.Enum):
    DECLARED="declare"; OPEN="ouvert"; EXPERTISE="expertise"; OFFER="indemnisation_proposee"; SETTLED="indemnise"; CLOSED="cloture"
class SyncOperation(Base):
    __tablename__="mobile_sync_operations"
    id=Column(Integer,primary_key=True); device_id=Column(String(120),index=True,nullable=False); operation_id=Column(String(120),unique=True,nullable=False,index=True); entity=Column(String(80),nullable=False); action=Column(String(20),nullable=False); payload=Column(JSON,default=dict); created_at=Column(DateTime(timezone=True),server_default=func.now())
class MobileMedia(Base):
    __tablename__="mobile_media"
    id=Column(Integer,primary_key=True); entity=Column(String(80),nullable=False); entity_id=Column(Integer,nullable=False,index=True); url=Column(String(500),nullable=False); latitude=Column(Float); longitude=Column(Float); captured_at=Column(DateTime(timezone=True)); metadata_json=Column(JSON,default=dict)
class InsuranceContract(Base):
    __tablename__="insurance_contracts"
    id=Column(Integer,primary_key=True); property_id=Column(Integer,ForeignKey("properties.id"),nullable=False,index=True); entity_id=Column(Integer,index=True); agency_id=Column(Integer,index=True); insurance_type=Column(Enum(InsuranceType),nullable=False); policy_number=Column(String(120),nullable=False); company=Column(String(255),nullable=False); broker=Column(String(255)); expiry_date=Column(Date,nullable=False,index=True); premium=Column(Float,default=0); document_id=Column(Integer); notes=Column(Text); created_at=Column(DateTime(timezone=True),server_default=func.now())
class InsuranceAttestation(Base):
    __tablename__="insurance_attestations"
    id=Column(Integer,primary_key=True); property_id=Column(Integer,ForeignKey("properties.id"),nullable=False,index=True); entity_id=Column(Integer,index=True); agency_id=Column(Integer,index=True); tenant_id=Column(Integer); status=Column(String(30),default="requested"); valid_until=Column(Date); document_url=Column(String(500)); requested_at=Column(DateTime(timezone=True),server_default=func.now()); reminder_count=Column(Integer,default=0); last_reminded_at=Column(DateTime(timezone=True))
class InsuranceClaim(Base):
    __tablename__="insurance_claims"
    id=Column(Integer,primary_key=True); property_id=Column(Integer,ForeignKey("properties.id"),nullable=False,index=True); entity_id=Column(Integer,index=True); agency_id=Column(Integer,index=True); claim_type=Column(Enum(ClaimType),nullable=False); status=Column(Enum(ClaimStatus),default=ClaimStatus.DECLARED); incident_date=Column(Date,nullable=False); circumstances=Column(Text); insurance_case_number=Column(String(120)); expert=Column(String(255)); key_dates=Column(JSON,default=dict); involved_people=Column(JSON,default=list); evidence=Column(JSON,default=list); proposed_indemnity=Column(Float); received_indemnity=Column(Float); restoration_work=Column(Text); created_at=Column(DateTime(timezone=True),server_default=func.now())
