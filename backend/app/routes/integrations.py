"""API du module 17 : API publique versionnée, connecteurs et transferts."""

import json
import secrets
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import GranularPermissionChecker
from app.database import get_db
from app.models.integration import (
    APICredential,
    DataTransferJob,
    IntegrationConnection,
    IntegrationSyncJob,
    OAuthClient,
    WebhookDelivery,
    WebhookEvent,
    WebhookSubscription,
)
from app.models.property import Property
from app.models.tenant import Tenant
from app.schemas.integration import (
    APIKeyCreate,
    ConnectionCreate,
    ConnectionUpdate,
    ExportRequest,
    ImportExecute,
    OAuthClientCreate,
    OAuthTokenRequest,
    SyncRequest,
    WebhookCreate,
    WebhookEventCreate,
    WebhookUpdate,
)
from app.schemas.property import PropertyCreate
from app.services import integration_service as service
from app.services.property_service import create_property


router = APIRouter(prefix="/api/integrations", tags=["Intégrations et API"])
external_router = APIRouter(prefix="/api/v1", tags=["API publique v1"])
integration_read = GranularPermissionChecker("integrations", "read")
integration_create = GranularPermissionChecker("integrations", "create")
integration_update = GranularPermissionChecker("integrations", "update")
integration_delete = GranularPermissionChecker("integrations", "delete")
integration_admin = GranularPermissionChecker("integrations", "admin")


def _actor(user) -> str:
    return getattr(user, "email", None) or getattr(user, "id", "system")


def _transfer_view(row: DataTransferJob) -> dict:
    result = service.object_view(row, {"storage_path", "output_path"})
    result["download_available"] = bool(row.output_path and Path(row.output_path).is_file())
    return result


def _connection(db: Session, connection_id: int) -> IntegrationConnection:
    row = db.query(IntegrationConnection).filter(IntegrationConnection.id == connection_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Connexion introuvable")
    return row


def _external_auth(required_scope: str):
    async def dependency(request: Request, response: Response, db: Session = Depends(get_db)):
        api_key = request.headers.get("X-API-Key")
        authorization = request.headers.get("Authorization", "")
        bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
        try:
            principal = service.authenticate_api(db, api_key, bearer)
            service.enforce_scope(principal, required_scope)
            limit, remaining, reset = service.consume_rate_limit(principal)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc), headers={"WWW-Authenticate": "Bearer, ApiKey"})
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except OverflowError as exc:
            retry_after = str(exc)
            raise HTTPException(status_code=429, detail="Limite de requêtes dépassée", headers={"Retry-After": retry_after})
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset)
        response.headers["X-API-Version"] = "v1"
        return principal

    return dependency


# ---------------------------------------------------------------------------
# Catalogue et connexions natives
# ---------------------------------------------------------------------------
@router.get("/catalog")
def catalog(user=Depends(integration_read)):
    providers = service.provider_catalog()
    categories = {}
    for item in providers:
        categories.setdefault(item["category"], []).append(item["provider"])
    return {
        "providers": providers,
        "categories": categories,
        "api": {"version": "v1", "openapi": "/openapi.json", "swagger": "/docs"},
        "webhook_events": service.WEBHOOK_EVENTS,
    }


@router.post("/connections", status_code=201)
def create_connection(data: ConnectionCreate, db: Session = Depends(get_db), user=Depends(integration_create)):
    try:
        row = service.create_connection(db, data, _actor(user))
    except ValueError as exc:
        status = 409 if "UNIQUE" in str(exc).upper() else 400
        raise HTTPException(status_code=status, detail=str(exc))
    return service.connection_view(row)


@router.get("/connections")
def list_connections(
    category: Optional[str] = None,
    provider: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(integration_read),
):
    query = db.query(IntegrationConnection)
    if category:
        query = query.filter(IntegrationConnection.category == category)
    if provider:
        query = query.filter(IntegrationConnection.provider == provider)
    rows = query.order_by(IntegrationConnection.category, IntegrationConnection.name).all()
    return {"data": [service.connection_view(row) for row in rows], "count": len(rows)}


@router.get("/connections/{connection_id}")
def get_connection(connection_id: int, db: Session = Depends(get_db), user=Depends(integration_read)):
    return service.connection_view(_connection(db, connection_id))


@router.put("/connections/{connection_id}")
def update_connection(
    connection_id: int,
    data: ConnectionUpdate,
    db: Session = Depends(get_db),
    user=Depends(integration_update),
):
    row = _connection(db, connection_id)
    try:
        row = service.update_connection(db, row, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return service.connection_view(row)


@router.delete("/connections/{connection_id}")
def disable_connection(connection_id: int, db: Session = Depends(get_db), user=Depends(integration_delete)):
    row = _connection(db, connection_id)
    row.is_active = False
    row.status = "disabled"
    db.commit()
    return {"id": row.id, "is_active": False, "status": "disabled"}


@router.post("/connections/{connection_id}/test")
def test_connection(connection_id: int, db: Session = Depends(get_db), user=Depends(integration_update)):
    return service.test_connection(db, _connection(db, connection_id))


@router.post("/connections/{connection_id}/sync", status_code=202)
def sync_connection(
    connection_id: int,
    data: SyncRequest,
    db: Session = Depends(get_db),
    user=Depends(integration_update),
):
    row = service.create_sync_job(db, _connection(db, connection_id), data)
    result = service.object_view(row)
    result["connector_status_note"] = "Aucun succès distant n'est simulé : le statut indique explicitement si un worker fournisseur est requis."
    return result


@router.get("/sync-jobs")
def sync_jobs(
    connection_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(integration_read),
):
    query = db.query(IntegrationSyncJob)
    if connection_id:
        query = query.filter(IntegrationSyncJob.connection_id == connection_id)
    if status:
        query = query.filter(IntegrationSyncJob.status == status)
    rows = query.order_by(IntegrationSyncJob.created_at.desc()).limit(limit).all()
    return {"data": [service.object_view(row) for row in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# API keys et OAuth2 client_credentials
# ---------------------------------------------------------------------------
@router.post("/api-keys", status_code=201)
def api_key_create(data: APIKeyCreate, db: Session = Depends(get_db), user=Depends(integration_admin)):
    try:
        row, token = service.create_api_key(db, data, _actor(user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = service.object_view(row, {"key_hash"})
    result["api_key"] = token
    result["warning"] = "Cette clé ne sera plus affichée. Conservez-la dans un gestionnaire de secrets."
    return result


@router.get("/api-keys")
def api_keys(db: Session = Depends(get_db), user=Depends(integration_admin)):
    rows = db.query(APICredential).order_by(APICredential.created_at.desc()).all()
    return {"data": [service.object_view(row, {"key_hash"}) for row in rows], "count": len(rows)}


@router.delete("/api-keys/{credential_id}")
def revoke_api_key(credential_id: int, db: Session = Depends(get_db), user=Depends(integration_admin)):
    row = db.query(APICredential).filter(APICredential.id == credential_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Clé API introuvable")
    row.is_active = False
    row.revoked_at = service.utcnow()
    db.commit()
    return {"id": row.id, "revoked": True}


@router.post("/oauth/clients", status_code=201)
def oauth_client_create(data: OAuthClientCreate, db: Session = Depends(get_db), user=Depends(integration_admin)):
    try:
        row, client_secret = service.create_oauth_client(db, data, _actor(user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = service.object_view(row, {"client_secret_hash"})
    result["client_secret"] = client_secret
    result["warning"] = "Le secret client n'est affiché qu'une fois."
    return result


@router.get("/oauth/clients")
def oauth_clients(db: Session = Depends(get_db), user=Depends(integration_admin)):
    rows = db.query(OAuthClient).order_by(OAuthClient.created_at.desc()).all()
    return {"data": [service.object_view(row, {"client_secret_hash"}) for row in rows], "count": len(rows)}


@router.post(
    "/oauth/token",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "required": ["grant_type", "client_id", "client_secret"],
                        "properties": {
                            "grant_type": {"type": "string", "enum": ["client_credentials"]},
                            "client_id": {"type": "string"},
                            "client_secret": {"type": "string", "format": "password"},
                            "scope": {"type": "string"},
                        },
                    }
                },
                "application/json": {"schema": OAuthTokenRequest.model_json_schema()},
            },
        }
    },
)
async def oauth_token(request: Request, db: Session = Depends(get_db)):
    """Échange OAuth2 client_credentials (form standard ou JSON)."""
    try:
        if "application/json" in request.headers.get("content-type", ""):
            payload = await request.json()
        else:
            form = await request.form()
            payload = dict(form)
        data = OAuthTokenRequest.model_validate(payload)
        return service.issue_oauth_token(db, data.client_id, data.client_secret, data.scope)
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        # Les erreurs de validation et d'identifiants ne divulguent pas quel
        # élément du couple client_id/secret est correct.
        raise HTTPException(
            status_code=401, detail="Client OAuth2 invalide",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
@router.post("/webhooks", status_code=201)
def create_webhook(data: WebhookCreate, db: Session = Depends(get_db), user=Depends(integration_create)):
    try:
        row, generated_secret = service.create_webhook(db, data, _actor(user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = service.webhook_view(row)
    if generated_secret:
        result["signing_secret"] = generated_secret
        result["warning"] = "Le secret de signature ne sera plus affiché."
    return result


@router.get("/webhooks")
def list_webhooks(db: Session = Depends(get_db), user=Depends(integration_read)):
    rows = db.query(WebhookSubscription).order_by(WebhookSubscription.created_at.desc()).all()
    return {"data": [service.webhook_view(row) for row in rows], "count": len(rows)}


@router.put("/webhooks/{subscription_id}")
def update_webhook(
    subscription_id: int,
    data: WebhookUpdate,
    db: Session = Depends(get_db),
    user=Depends(integration_update),
):
    row = db.query(WebhookSubscription).filter(WebhookSubscription.id == subscription_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook introuvable")
    payload = data.model_dump(exclude_unset=True)
    if "target_url" in payload:
        target_url = str(payload.pop("target_url"))
        try:
            service._safe_webhook_url(target_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        row.target_url = target_url
    secret = payload.pop("secret", None)
    if secret:
        from app.services.admin_security_service import encrypt_secret
        row.encrypted_secret = encrypt_secret(secret)
    if "events" in payload:
        unknown = [event for event in payload["events"] if event not in service.WEBHOOK_EVENTS and event != "*"]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Événements webhook inconnus : {', '.join(unknown)}")
        payload["events"] = sorted(set(payload["events"]))
    for key, value in payload.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return service.webhook_view(row)


@router.delete("/webhooks/{subscription_id}")
def delete_webhook(subscription_id: int, db: Session = Depends(get_db), user=Depends(integration_delete)):
    row = db.query(WebhookSubscription).filter(WebhookSubscription.id == subscription_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Webhook introuvable")
    row.is_active = False
    row.disabled_reason = "Désactivé manuellement"
    db.commit()
    return {"id": row.id, "is_active": False}


@router.post("/webhook-events", status_code=201)
def emit_event(data: WebhookEventCreate, db: Session = Depends(get_db), user=Depends(integration_create)):
    try:
        row = service.create_webhook_event(
            db, data.event_type, data.data, data.idempotency_key, data.deliver_now
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    result = service.object_view(row)
    result["delivery_count"] = db.query(WebhookDelivery).filter(WebhookDelivery.event_id == row.id).count()
    return result


@router.get("/webhook-deliveries")
def deliveries(
    status: Optional[str] = None,
    subscription_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(integration_read),
):
    query = db.query(WebhookDelivery)
    if status:
        query = query.filter(WebhookDelivery.status == status)
    if subscription_id:
        query = query.filter(WebhookDelivery.subscription_id == subscription_id)
    rows = query.order_by(WebhookDelivery.created_at.desc()).limit(limit).all()
    return {"data": [service.object_view(row) for row in rows], "count": len(rows)}


@router.post("/webhook-deliveries/{delivery_id}/retry", status_code=202)
def replay_delivery(delivery_id: int, db: Session = Depends(get_db), user=Depends(integration_update)):
    row = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Livraison webhook introuvable")
    try:
        retry = service.retry_delivery(db, row)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return service.object_view(retry)


# ---------------------------------------------------------------------------
# Import / migration / export
# ---------------------------------------------------------------------------
@router.post("/imports/analyse", status_code=201)
async def analyse_import(
    file: UploadFile = File(...),
    entity_type: str = Form(...),
    source_system: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    user=Depends(integration_create),
):
    content = await file.read()
    try:
        row = service.analyse_import(
            db, file.filename or "import.csv", content, entity_type,
            source_system, _actor(user),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _transfer_view(row)


@router.post("/imports/{job_id}/execute")
def execute_import(
    job_id: int,
    data: ImportExecute,
    db: Session = Depends(get_db),
    user=Depends(integration_update),
):
    row = db.query(DataTransferJob).filter(DataTransferJob.id == job_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Import introuvable")
    try:
        return service.execute_import(db, row, data.mapping, data.duplicate_strategy, data.dry_run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/exports")
def export_data(data: ExportRequest, db: Session = Depends(get_db), user=Depends(integration_read)):
    try:
        job, content, media_type, filename = service.export_data(db, data, _actor(user))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Export-Job-Id": str(job.id),
            "X-Export-Reference": job.reference,
        },
    )


@router.get("/transfers")
def transfer_jobs(
    operation: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user=Depends(integration_read),
):
    query = db.query(DataTransferJob)
    if operation:
        query = query.filter(DataTransferJob.operation == operation)
    if status:
        query = query.filter(DataTransferJob.status == status)
    rows = query.order_by(DataTransferJob.created_at.desc()).limit(limit).all()
    return {"data": [_transfer_view(row) for row in rows], "count": len(rows)}


@router.get("/transfers/{job_id}/download")
def download_export(job_id: int, db: Session = Depends(get_db), user=Depends(integration_read)):
    row = db.query(DataTransferJob).filter(DataTransferJob.id == job_id, DataTransferJob.operation == "export").first()
    if not row or not row.output_path or not Path(row.output_path).is_file():
        raise HTTPException(status_code=404, detail="Export introuvable")
    path = Path(row.output_path)
    media = {".csv": "text/csv", ".json": "application/json", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(path.suffix, "application/octet-stream")
    return StreamingResponse(path.open("rb"), media_type=media, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})


# ---------------------------------------------------------------------------
# Zapier / Make : catalogue commun préconfiguré
# ---------------------------------------------------------------------------
@router.get("/automation-connectors")
def automation_connectors(user=Depends(integration_read)):
    return {
        "platforms": [
            {
                "key": "zapier", "name": "Zapier", "mode": "webhook_and_rest",
                "authentication": ["api_key", "oauth2_client_credentials"],
                **service.CONNECTOR_CATALOG,
            },
            {
                "key": "make", "name": "Make (Integromat)", "mode": "webhook_and_rest",
                "authentication": ["api_key", "oauth2_client_credentials"],
                **service.CONNECTOR_CATALOG,
            },
        ],
        "api_base": "/api/v1",
        "webhook_setup": "/api/integrations/webhooks",
    }


# ---------------------------------------------------------------------------
# REST API publique, version v1
# ---------------------------------------------------------------------------
def _api_metadata() -> dict:
    return {
        "name": "GestImmo Public API",
        "version": "v1",
        "documentation": "/docs",
        "openapi": "/openapi.json",
        "authentication": ["X-API-Key", "OAuth2 client_credentials"],
    }


@external_router.get("/")
def external_root(response: Response, principal=Depends(_external_auth("properties:read"))):
    return _api_metadata()


@external_router.get("/meta")
def external_meta(response: Response, principal=Depends(_external_auth("properties:read"))):
    return _api_metadata()


@external_router.get("/properties")
def external_properties(
    response: Response,
    city: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal=Depends(_external_auth("properties:read")),
):
    query = db.query(Property).filter(Property.is_active == True)  # noqa: E712
    if city:
        query = query.filter(Property.city.ilike(f"%{city}%"))
    if status:
        query = query.filter(Property.status == status)
    total = query.count()
    rows = query.order_by(Property.id).offset((page - 1) * limit).limit(limit).all()
    fields = ["id", "reference", "type", "status", "title", "address", "postal_code", "city", "living_area", "rooms", "rent_price", "sale_price", "updated_at"]
    data = []
    for row in rows:
        item = {}
        for field in fields:
            value = getattr(row, field)
            if hasattr(value, "value"):
                value = value.value
            item[field] = value
        data.append(item)
    return {"data": data, "pagination": {"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) // limit}}


@external_router.get("/properties/{property_id}")
def external_property(
    property_id: int,
    response: Response,
    db: Session = Depends(get_db),
    principal=Depends(_external_auth("properties:read")),
):
    row = db.query(Property).filter(Property.id == property_id, Property.is_active == True).first()  # noqa: E712
    if not row:
        raise HTTPException(status_code=404, detail="Bien introuvable")
    return service.object_view(row)


@external_router.post("/properties", status_code=201)
def external_property_create(
    data: PropertyCreate,
    response: Response,
    db: Session = Depends(get_db),
    principal=Depends(_external_auth("properties:write")),
):
    row = create_property(db, data)
    service.create_webhook_event(db, "property.created", {"id": row.id, "reference": row.reference})
    return service.object_view(row)


@external_router.get("/tenants")
def external_tenants(
    response: Response,
    q: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal=Depends(_external_auth("tenants:read")),
):
    query = db.query(Tenant).filter(Tenant.is_active == True)  # noqa: E712
    if q:
        term = f"%{q}%"
        query = query.filter(or_(Tenant.first_name.ilike(term), Tenant.last_name.ilike(term), Tenant.email.ilike(term), Tenant.reference.ilike(term)))
    total = query.count()
    rows = query.order_by(Tenant.id).offset((page - 1) * limit).limit(limit).all()
    # Cette ressource API ne divulgue jamais revenus, scores ni données bancaires.
    data = [{
        "id": row.id, "reference": row.reference, "status": row.status.value,
        "first_name": row.first_name, "last_name": row.last_name,
        "email": row.email, "phone": row.phone, "city": row.city,
    } for row in rows]
    return {"data": data, "pagination": {"page": page, "limit": limit, "total": total, "pages": (total + limit - 1) // limit}}
