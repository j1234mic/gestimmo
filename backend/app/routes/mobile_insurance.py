"""API mobile synchronisable et gestion assurances/sinistres."""
from datetime import date, datetime, timedelta
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from app.auth import require_read, require_write
from app.database import get_db
from app.models.insurance import *

router=APIRouter(prefix="/api",tags=["Mobile et assurances"])
class SyncIn(BaseModel):
 device_id:str; operation_id:str; entity:str; action:str; payload:dict[str,Any]=Field(default_factory=dict)
class MediaIn(BaseModel):
 entity:str; entity_id:int; url:str; latitude:Optional[float]=None; longitude:Optional[float]=None; captured_at:Optional[datetime]=None; metadata:dict[str,Any]=Field(default_factory=dict)
class ContractIn(BaseModel):
 property_id:int; insurance_type:InsuranceType; policy_number:str; company:str; broker:Optional[str]=None; expiry_date:date; premium:float=0; document_id:Optional[int]=None; notes:Optional[str]=None
class AttestationIn(BaseModel): property_id:int; tenant_id:Optional[int]=None
class ClaimIn(BaseModel):
 property_id:int; claim_type:ClaimType; incident_date:date; circumstances:Optional[str]=None; involved_people:list[Any]=Field(default_factory=list); evidence:list[Any]=Field(default_factory=list)

def obj(x):
 d={c.name:getattr(x,c.name) for c in x.__table__.columns}
 for k,v in d.items():
  if hasattr(v,"value"): d[k]=v.value
 return d

@router.get("/mobile/dashboard")
def mobile_dashboard(db:Session=Depends(get_db), user=Depends(require_read)):
 return {"role":getattr(user,"role","manager"),"features":["properties_map","contacts","calendar","maintenance","inspections","quotes","push","offline_sync","document_scan"],"pending_sync":db.query(SyncOperation).count(),"open_claims":db.query(InsuranceClaim).filter(InsuranceClaim.status!=ClaimStatus.CLOSED).count()}
@router.post("/mobile/sync",status_code=201)
def sync(data:SyncIn,db:Session=Depends(get_db),user=Depends(require_write)):
 existing=db.query(SyncOperation).filter_by(operation_id=data.operation_id).first()
 if existing:return {"id":existing.id,"duplicate":True}
 row=SyncOperation(**data.model_dump());db.add(row);db.commit();db.refresh(row)
 return {"id":row.id,"accepted":True,"synced_at":datetime.utcnow()}
@router.get("/mobile/sync")
def sync_pull(since:Optional[datetime]=None,db:Session=Depends(get_db),user=Depends(require_read)):
 q=db.query(SyncOperation).order_by(SyncOperation.id)
 if since:q=q.filter(SyncOperation.created_at>=since)
 return {"data":[obj(x) for x in q.all()],"has_more":False}
@router.post("/mobile/media",status_code=201)
def media(data:MediaIn,db:Session=Depends(get_db),user=Depends(require_write)):
 row=MobileMedia(entity=data.entity,entity_id=data.entity_id,url=data.url,latitude=data.latitude,longitude=data.longitude,captured_at=data.captured_at,metadata_json=data.metadata);db.add(row);db.commit();db.refresh(row);return obj(row)

@router.post("/insurance/contracts",status_code=201)
def contract(data:ContractIn,db:Session=Depends(get_db),user=Depends(require_write)):
 row=InsuranceContract(**data.model_dump());db.add(row);db.commit();db.refresh(row);return obj(row)
@router.get("/insurance/contracts")
def contracts(expiring_before:Optional[date]=None,db:Session=Depends(get_db),user=Depends(require_read)):
 q=db.query(InsuranceContract)
 if expiring_before:q=q.filter(InsuranceContract.expiry_date<=expiring_before)
 return {"data":[obj(x) for x in q.order_by(InsuranceContract.expiry_date).all()]}
@router.post("/insurance/attestations",status_code=201)
def attestation(data:AttestationIn,db:Session=Depends(get_db),user=Depends(require_write)):
 row=InsuranceAttestation(**data.model_dump());db.add(row);db.commit();db.refresh(row);return obj(row)
@router.post("/insurance/claims",status_code=201)
def claim(data:ClaimIn,db:Session=Depends(get_db),user=Depends(require_write)):
 row=InsuranceClaim(**data.model_dump());db.add(row);db.commit();db.refresh(row);return obj(row)
@router.get("/insurance/claims")
def claims(property_id:Optional[int]=None,db:Session=Depends(get_db),user=Depends(require_read)):
 q=db.query(InsuranceClaim)
 if property_id:q=q.filter_by(property_id=property_id)
 return {"data":[obj(x) for x in q.order_by(InsuranceClaim.incident_date.desc()).all()]}
@router.get("/insurance/reporting")
def reporting(db:Session=Depends(get_db),user=Depends(require_read)):
 contracts=db.query(InsuranceContract).all(); claims=db.query(InsuranceClaim).all(); today=date.today()
 return {"contracts_total":len(contracts),"expiring_30_days":sum(today<=x.expiry_date<=today+timedelta(days=30) for x in contracts),"claims_total":len(claims),"claims_open":sum(x.status!=ClaimStatus.CLOSED for x in claims),"proposed_indemnity":sum(x.proposed_indemnity or 0 for x in claims),"received_indemnity":sum(x.received_indemnity or 0 for x in claims)}
