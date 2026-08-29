"""API mobile synchronisable et gestion assurances/sinistres."""
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.database import get_db
from app.models.insurance import *
from app.models.property import Property
from app.schemas.insurance import (
    AttestationCreate,
    AttestationResponse,
    AttestationUpdate,
    ClaimCreate,
    ClaimResponse,
    ClaimUpdate,
    InsuranceContractCreate,
    InsuranceContractResponse,
    InsuranceContractUpdate,
)

router = APIRouter(prefix="/api", tags=["Mobile et assurances"])


class SyncIn(BaseModel):
    device_id: str
    operation_id: str
    entity: str
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class MediaIn(BaseModel):
    entity: str
    entity_id: int
    url: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    captured_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def obj(x):
    d = {c.name: getattr(x, c.name) for c in x.__table__.columns}
    for k, v in d.items():
        if hasattr(v, "value"):
            d[k] = v.value
    return d


def _scope_filter(query, model, user):
    """Restreint les assurances aux sociétés/agences du périmètre de l'utilisateur."""
    if not user or getattr(user, "db_id", None) is None or getattr(user, "is_superuser", False):
        return query
    orgs = getattr(user, "organization_ids", None) or []
    agencys = getattr(user, "agency_ids", None) or []
    clauses = []
    if orgs:
        clauses.append(model.entity_id.in_(orgs))
    if agencys:
        clauses.append(model.agency_id.in_(agencys))
    if not clauses:
        return query.filter(False)
    return query.filter(or_(*clauses))


def _prop_scope(property_id: int, db: Session, user) -> tuple[Optional[int], Optional[int]]:
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Bien non trouvé")
    if user and getattr(user, "db_id", None) is not None and not getattr(user, "is_superuser", False):
        scopes = getattr(user, "data_scopes", [])
        if scopes and not any(
            prop.entity_id == scope.get("organization_id")
            and (scope.get("agency_id") is None or prop.agency_id == scope.get("agency_id"))
            and (not scope.get("portfolio_ids") or prop.portfolio_id in scope.get("portfolio_ids", []))
            for scope in scopes
        ):
            raise HTTPException(status_code=403, detail="Bien hors périmètre")
    return prop.entity_id, prop.agency_id


@router.get("/mobile/dashboard")
def mobile_dashboard(db: Session = Depends(get_db), user=Depends(require_read)):
    return {
        "role": getattr(user, "role", "manager"),
        "features": ["properties_map", "contacts", "calendar", "maintenance", "inspections", "quotes", "push", "offline_sync", "document_scan"],
        "pending_sync": db.query(SyncOperation).count(),
        "open_claims": db.query(InsuranceClaim).filter(InsuranceClaim.status != ClaimStatus.CLOSED).count(),
    }


@router.post("/mobile/sync", status_code=201)
def sync(data: SyncIn, db: Session = Depends(get_db), user=Depends(require_write)):
    existing = db.query(SyncOperation).filter_by(operation_id=data.operation_id).first()
    if existing:
        return {"id": existing.id, "duplicate": True}
    row = SyncOperation(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "accepted": True, "synced_at": datetime.utcnow()}


@router.get("/mobile/sync")
def sync_pull(since: Optional[datetime] = None, db: Session = Depends(get_db), user=Depends(require_read)):
    q = db.query(SyncOperation).order_by(SyncOperation.id)
    if since:
        q = q.filter(SyncOperation.created_at >= since)
    return {"data": [obj(x) for x in q.all()], "has_more": False}


@router.post("/mobile/media", status_code=201)
def media(data: MediaIn, db: Session = Depends(get_db), user=Depends(require_write)):
    row = MobileMedia(
        entity=data.entity,
        entity_id=data.entity_id,
        url=data.url,
        latitude=data.latitude,
        longitude=data.longitude,
        captured_at=data.captured_at,
        metadata_json=data.metadata,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return obj(row)


# ============================================
# CONTRATS D'ASSURANCE
# ============================================
@router.post("/insurance/contracts", response_model=InsuranceContractResponse, status_code=201)
def create_contract(
    data: InsuranceContractCreate,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    entity_id, agency_id = _prop_scope(data.property_id, db, user)
    row = InsuranceContract(**{
        **data.model_dump(),
        "entity_id": data.entity_id if data.entity_id is not None else entity_id,
        "agency_id": data.agency_id if data.agency_id is not None else agency_id,
    })
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/insurance/contracts")
def list_contracts(
    expiring_before: Optional[date] = None,
    property_id: Optional[int] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(InsuranceContract)
    q = _scope_filter(q, InsuranceContract, user)
    if expiring_before:
        q = q.filter(InsuranceContract.expiry_date <= expiring_before)
    if property_id:
        q = q.filter(InsuranceContract.property_id == property_id)
    total = q.count()
    rows = q.order_by(InsuranceContract.expiry_date).offset((page - 1) * limit).limit(limit).all()
    return {"data": [obj(x) for x in rows], "total": total, "page": page}


@router.get("/insurance/contracts/{contract_id}", response_model=InsuranceContractResponse)
def get_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    row = db.query(InsuranceContract).filter(InsuranceContract.id == contract_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Contrat non trouvé")
    q = _scope_filter(db.query(InsuranceContract), InsuranceContract, user).filter(InsuranceContract.id == contract_id)
    if not q.first():
        raise HTTPException(status_code=403, detail="Contrat hors périmètre")
    return row


@router.put("/insurance/contracts/{contract_id}", response_model=InsuranceContractResponse)
def update_contract(
    contract_id: int,
    data: InsuranceContractUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    row = db.query(InsuranceContract).filter(InsuranceContract.id == contract_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Contrat non trouvé")
    q = _scope_filter(db.query(InsuranceContract), InsuranceContract, user).filter(InsuranceContract.id == contract_id)
    if not q.first():
        raise HTTPException(status_code=403, detail="Contrat hors périmètre")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/insurance/contracts/{contract_id}")
def delete_contract(
    contract_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    row = db.query(InsuranceContract).filter(InsuranceContract.id == contract_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Contrat non trouvé")
    q = _scope_filter(db.query(InsuranceContract), InsuranceContract, user).filter(InsuranceContract.id == contract_id)
    if not q.first():
        raise HTTPException(status_code=403, detail="Contrat hors périmètre")
    db.delete(row)
    db.commit()
    return {"message": "Contrat supprimé", "contract_id": contract_id}


# ============================================
# ATTESTATIONS
# ============================================
@router.post("/insurance/attestations", response_model=AttestationResponse, status_code=201)
def create_attestation(
    data: AttestationCreate,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    entity_id, agency_id = _prop_scope(data.property_id, db, user)
    row = InsuranceAttestation(**{
        **data.model_dump(),
        "entity_id": data.entity_id if data.entity_id is not None else entity_id,
        "agency_id": data.agency_id if data.agency_id is not None else agency_id,
    })
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/insurance/attestations")
def list_attestations(
    property_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(InsuranceAttestation)
    q = _scope_filter(q, InsuranceAttestation, user)
    if property_id:
        q = q.filter(InsuranceAttestation.property_id == property_id)
    if tenant_id:
        q = q.filter(InsuranceAttestation.tenant_id == tenant_id)
    if status:
        q = q.filter(InsuranceAttestation.status == status)
    total = q.count()
    rows = q.order_by(InsuranceAttestation.requested_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [obj(x) for x in rows], "total": total, "page": page}


@router.get("/insurance/attestations/{attestation_id}", response_model=AttestationResponse)
def get_attestation(
    attestation_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    row = db.query(InsuranceAttestation).filter(InsuranceAttestation.id == attestation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Attestation non trouvée")
    q = _scope_filter(db.query(InsuranceAttestation), InsuranceAttestation, user).filter(InsuranceAttestation.id == attestation_id)
    if not q.first():
        raise HTTPException(status_code=403, detail="Attestation hors périmètre")
    return row


@router.put("/insurance/attestations/{attestation_id}", response_model=AttestationResponse)
def update_attestation(
    attestation_id: int,
    data: AttestationUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    row = db.query(InsuranceAttestation).filter(InsuranceAttestation.id == attestation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Attestation non trouvée")
    q = _scope_filter(db.query(InsuranceAttestation), InsuranceAttestation, user).filter(InsuranceAttestation.id == attestation_id)
    if not q.first():
        raise HTTPException(status_code=403, detail="Attestation hors périmètre")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.post("/insurance/attestations/{attestation_id}/remind")
def remind_attestation(
    attestation_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    row = db.query(InsuranceAttestation).filter(InsuranceAttestation.id == attestation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Attestation non trouvée")
    q = _scope_filter(db.query(InsuranceAttestation), InsuranceAttestation, user).filter(InsuranceAttestation.id == attestation_id)
    if not q.first():
        raise HTTPException(status_code=403, detail="Attestation hors périmètre")
    row.reminder_count = (row.reminder_count or 0) + 1
    row.last_reminded_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return obj(row)


@router.delete("/insurance/attestations/{attestation_id}")
def delete_attestation(
    attestation_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    row = db.query(InsuranceAttestation).filter(InsuranceAttestation.id == attestation_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Attestation non trouvée")
    q = _scope_filter(db.query(InsuranceAttestation), InsuranceAttestation, user).filter(InsuranceAttestation.id == attestation_id)
    if not q.first():
        raise HTTPException(status_code=403, detail="Attestation hors périmètre")
    db.delete(row)
    db.commit()
    return {"message": "Attestation supprimée", "attestation_id": attestation_id}


# ============================================
# SINISTRES
# ============================================
@router.post("/insurance/claims", response_model=ClaimResponse, status_code=201)
def create_claim(
    data: ClaimCreate,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    entity_id, agency_id = _prop_scope(data.property_id, db, user)
    row = InsuranceClaim(**{
        **data.model_dump(),
        "entity_id": data.entity_id if data.entity_id is not None else entity_id,
        "agency_id": data.agency_id if data.agency_id is not None else agency_id,
    })
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/insurance/claims")
def list_claims(
    property_id: Optional[int] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    q = db.query(InsuranceClaim)
    q = _scope_filter(q, InsuranceClaim, user)
    if property_id:
        q = q.filter(InsuranceClaim.property_id == property_id)
    if status:
        q = q.filter(InsuranceClaim.status == status)
    total = q.count()
    rows = q.order_by(InsuranceClaim.incident_date.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [obj(x) for x in rows], "total": total, "page": page}


@router.get("/insurance/claims/{claim_id}", response_model=ClaimResponse)
def get_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    row = db.query(InsuranceClaim).filter(InsuranceClaim.id == claim_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Sinistre non trouvé")
    q = _scope_filter(db.query(InsuranceClaim), InsuranceClaim, user).filter(InsuranceClaim.id == claim_id)
    if not q.first():
        raise HTTPException(status_code=403, detail="Sinistre hors périmètre")
    return row


@router.put("/insurance/claims/{claim_id}", response_model=ClaimResponse)
def update_claim(
    claim_id: int,
    data: ClaimUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    row = db.query(InsuranceClaim).filter(InsuranceClaim.id == claim_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Sinistre non trouvé")
    q = _scope_filter(db.query(InsuranceClaim), InsuranceClaim, user).filter(InsuranceClaim.id == claim_id)
    if not q.first():
        raise HTTPException(status_code=403, detail="Sinistre hors périmètre")
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/insurance/claims/{claim_id}")
def delete_claim(
    claim_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    row = db.query(InsuranceClaim).filter(InsuranceClaim.id == claim_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Sinistre non trouvé")
    q = _scope_filter(db.query(InsuranceClaim), InsuranceClaim, user).filter(InsuranceClaim.id == claim_id)
    if not q.first():
        raise HTTPException(status_code=403, detail="Sinistre hors périmètre")
    db.delete(row)
    db.commit()
    return {"message": "Sinistre supprimé", "claim_id": claim_id}


@router.get("/insurance/reporting")
def reporting(db: Session = Depends(get_db), user=Depends(require_read)):
    contracts_q = _scope_filter(db.query(InsuranceContract), InsuranceContract, user)
    claims_q = _scope_filter(db.query(InsuranceClaim), InsuranceClaim, user)
    attestations_q = _scope_filter(db.query(InsuranceAttestation), InsuranceAttestation, user)
    contracts = contracts_q.all()
    claims = claims_q.all()
    attestations = attestations_q.all()
    today = date.today()
    return {
        "contracts_total": len(contracts),
        "expiring_30_days": sum(today <= x.expiry_date <= today + timedelta(days=30) for x in contracts),
        "claims_total": len(claims),
        "claims_open": sum(x.status != ClaimStatus.CLOSED for x in claims),
        "proposed_indemnity": sum(x.proposed_indemnity or 0 for x in claims),
        "received_indemnity": sum(x.received_indemnity or 0 for x in claims),
        "attestations_pending": sum(x.status == "requested" for x in attestations),
        "attestations_expiring": sum(bool(x.valid_until and x.valid_until <= today + timedelta(days=30)) for x in attestations),
    }
