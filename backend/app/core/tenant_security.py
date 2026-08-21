"""Authentification JWT dédiée au portail locataire."""


from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.auth import create_access_token, create_refresh_token, decode_token, pwd_context
from app.database import get_db
from app.models.tenant import Tenant


def hash_portal_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_portal_password(password: str, password_hash: str) -> bool:
    return bool(password_hash) and pwd_context.verify(password, password_hash)


def create_tenant_tokens(tenant: Tenant) -> dict:
    claims = {
        "sub": tenant.email,
        "tenant_id": tenant.id,
        "actor": "tenant",
    }
    return {
        "access_token": create_access_token(claims),
        "refresh_token": create_refresh_token(claims),
        "token_type": "bearer",
    }


async def get_current_tenant(request: Request, db: Session = Depends(get_db)) -> Tenant:
    token = request.headers.get("Authorization", "").replace("Bearer ", "", 1).strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification locataire requise")
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Jeton locataire invalide")
    if payload.get("type") != "access" or payload.get("actor") != "tenant" or not payload.get("tenant_id"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Jeton locataire invalide")
    try:
        tenant_id = int(payload["tenant_id"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Jeton locataire invalide")
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id,
        Tenant.is_active == True,
        Tenant.portal_enabled == True,
    ).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Portail locataire désactivé")
    return tenant


def refresh_tenant_tokens(db: Session, refresh_token: str) -> dict:
    try:
        payload = decode_token(refresh_token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Jeton de renouvellement invalide")
    if payload.get("type") != "refresh" or payload.get("actor") != "tenant":
        raise HTTPException(status_code=401, detail="Jeton de renouvellement invalide")
    try:
        tenant_id = int(payload.get("tenant_id", 0))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Jeton de renouvellement invalide")
    tenant = db.query(Tenant).filter(
        Tenant.id == tenant_id,
        Tenant.is_active == True,
        Tenant.portal_enabled == True,
    ).first()
    if not tenant:
        raise HTTPException(status_code=403, detail="Portail locataire désactivé")
    return create_tenant_tokens(tenant)
