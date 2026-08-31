"""Authentification partagée de l'application.

Le module 12 remplace le magasin en mémoire par des comptes persistants, tout
en conservant les trois objets historiques comme solution de compatibilité
pour une base non initialisée.
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.admin_security_service import (
    effective_permissions,
    get_user_policy,
    has_permission,
    pwd_context,
    utcnow,
)

security = HTTPBearer(auto_error=False)


class User(BaseModel):
    id: str
    db_id: Optional[int] = None
    email: str
    full_name: str
    role: str
    permissions: list = Field(default_factory=list)
    granular_permissions: list = Field(default_factory=list)
    organization_ids: list[int] = Field(default_factory=list)
    organization_wide_ids: list[int] = Field(default_factory=list)
    agency_ids: list[int] = Field(default_factory=list)
    portfolio_ids: list[int] = Field(default_factory=list)
    data_scopes: list[dict] = Field(default_factory=list)
    session_id: Optional[str] = None
    is_superuser: bool = False


class UserInDB(User):
    hashed_password: str
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None


USERS_DB = {
    "admin@immogest.com": UserInDB(
        id="user_001", email="admin@immogest.com", full_name="Administrateur", role="admin",
        permissions=["read", "write", "delete", "admin"],
        hashed_password=pwd_context.hash("Admin@2024!"), is_superuser=True,
    ),
    "gestionnaire@immogest.com": UserInDB(
        id="user_002", email="gestionnaire@immogest.com", full_name="Gestionnaire", role="manager",
        permissions=["read", "write"], hashed_password=pwd_context.hash("Manager@2024!"),
    ),
    "lecteur@immogest.com": UserInDB(
        id="user_003", email="lecteur@immogest.com", full_name="Lecteur", role="viewer",
        permissions=["read"], hashed_password=pwd_context.hash("Viewer@2024!"),
    ),
}


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def get_user(email: str):
    return USERS_DB.get(email.lower())


def authenticate_user(email: str, password: str, db: Optional[Session] = None):
    """Authentifie un compte persistant, puis le compte historique si les
    tables du module 12 ne sont pas disponibles."""
    if db is not None:
        try:
            from app.models.admin_security import AdminUser
            user = db.query(AdminUser).filter(AdminUser.email == email.lower()).first()
            if user and user.is_active and verify_password(password, user.password_hash):
                return user
            if user:
                return None
        except Exception:
            # Compatibilité explicite avec une installation n'ayant pas encore
            # créé les tables du module 12.
            pass
    user = get_user(email)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


def create_access_token(data: dict, expires_delta=None):
    to_encode = data.copy()
    expire = utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")


def create_refresh_token(data: dict, expires_delta=None):
    to_encode = data.copy()
    expire = utcnow() + (expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str):
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])


def principal_from_admin(user, session_id: Optional[str] = None) -> User:
    granular = effective_permissions(user)
    actions = set()
    for permission in granular:
        actions.update(permission.get("actions") or [])
    legacy_actions = []
    if "read" in actions or user.is_superuser:
        legacy_actions.append("read")
    if {"create", "update"} & actions or user.is_superuser:
        legacy_actions.append("write")
    if "delete" in actions or user.is_superuser:
        legacy_actions.append("delete")
    if "admin" in actions or user.is_superuser:
        legacy_actions.append("admin")
    primary_role = "admin" if user.is_superuser else "viewer"
    if not user.is_superuser:
        for assignment in user.role_assignments:
            if assignment.role and assignment.role.is_active:
                primary_role = assignment.role.profile_key or assignment.role.name
                break
    return User(
        id=user.public_id,
        db_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=primary_role,
        permissions=legacy_actions,
        granular_permissions=granular,
        organization_ids=sorted({scope.organization_id for scope in user.scopes}),
        organization_wide_ids=sorted({scope.organization_id for scope in user.scopes if scope.agency_id is None}),
        agency_ids=sorted({scope.agency_id for scope in user.scopes if scope.agency_id is not None}),
        portfolio_ids=sorted({item for scope in user.scopes for item in (scope.portfolio_ids or [])}),
        data_scopes=[{
            "organization_id": scope.organization_id,
            "agency_id": scope.agency_id,
            "portfolio_ids": scope.portfolio_ids or [],
            "is_default": scope.is_default,
        } for scope in user.scopes],
        session_id=session_id,
        is_superuser=user.is_superuser,
    )


async def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.headers.get("Authorization", "").replace("Bearer ", "", 1).strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authentification requise")
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Token d'accès requis")
    email = payload.get("sub")
    user_id = payload.get("uid")
    if user_id:
        from app.models.admin_security import AdminUser, SecuritySession
        user = db.query(AdminUser).filter(AdminUser.id == int(user_id)).first()
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="Utilisateur désactivé ou introuvable")
        if user.email != email:
            raise HTTPException(status_code=401, detail="Identité du token invalide")
        password_change_path = f"/api/admin/users/{user.id}/password"
        allowed_when_expired = {"/api/auth/me", "/api/auth/logout", "/api/auth/sessions", password_change_path}
        if user.must_change_password and request.url.path not in allowed_when_expired:
            raise HTTPException(
                status_code=403,
                detail={"code": "password_change_required", "message": "Le mot de passe doit être renouvelé"},
            )
        session_id = payload.get("sid")
        if not session_id:
            raise HTTPException(status_code=401, detail="Session invalide")
        session = db.query(SecuritySession).filter(SecuritySession.id == session_id, SecuritySession.user_id == user.id).first()
        now = utcnow()
        if not session or session.revoked_at or session.expires_at.replace(tzinfo=None) <= now:
            raise HTTPException(status_code=401, detail="Session expirée ou révoquée")
        policy = get_user_policy(db, user)
        last_seen = session.last_seen_at.replace(tzinfo=None) if session.last_seen_at else now
        if last_seen + timedelta(minutes=policy.session_timeout_minutes) <= now:
            session.revoked_at = now
            session.revoke_reason = "idle_timeout"
            db.commit()
            raise HTTPException(status_code=401, detail="Session expirée pour inactivité")
        # Une écriture toutes les 60 secondes suffit à mesurer l'inactivité sans
        # surcharger la base à chaque requête.
        if (now - last_seen).total_seconds() >= 60:
            session.last_seen_at = now
            db.commit()
        return principal_from_admin(user, session_id)
    # Jetons historiques émis avant activation du module 12.
    legacy = get_user(email or "")
    if not legacy:
        raise HTTPException(status_code=401, detail="Utilisateur non trouvé")
    return legacy


async def get_optional_user(request: Request, db: Session = Depends(get_db)):
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None


def _module_from_path(path: str) -> str:
    segment = path.removeprefix("/api/").split("/", 1)[0]
    mapping = {
        "properties": "properties", "owners": "owners", "owner-portal": "owners",
        "tenants": "tenants", "applications": "tenants", "tenant-portal": "tenants",
        "leases": "leases", "lease-signatures": "leases", "inspections": "leases",
        "finance": "finance", "accounting": "finance", "export": "finance",
        "maintenance": "maintenance", "condo": "condo", "crm": "crm",
        "reporting": "reporting", "comms": "communication", "communication": "communication",
        "messages": "communication", "notifications": "communication", "ged": "ged",
        "documents": "ged", "history": "properties", "admin": "administration",
        "geolocation": "geolocation",
        "subscriptions": "subscriptions",
    }
    return mapping.get(segment, segment or "unknown")


class PermissionChecker:
    def __init__(self, perms):
        self.perms = perms

    def __call__(
        self, request: Request, user=Depends(get_current_user), db: Session = Depends(get_db)
    ):
        if user.db_id is not None:
            from app.models.admin_security import AdminUser
            db_user = db.query(AdminUser).filter(AdminUser.id == user.db_id).first()
            module = _module_from_path(request.url.path)
            if "admin" in self.perms:
                action = "admin"
            elif "delete" in self.perms or request.method == "DELETE":
                action = "delete"
            elif "write" in self.perms:
                action = "create" if request.method == "POST" else "update"
            else:
                action = "read"
            if not db_user or not has_permission(db_user, module, action):
                raise HTTPException(status_code=403, detail=f"Permission {module}:{action} requise")
            return user
        for permission in self.perms:
            if permission not in user.permissions:
                raise HTTPException(status_code=403, detail=f"Permission '{permission}' requise")
        return user


class GranularPermissionChecker:
    def __init__(self, module: str, action: str):
        self.module = module
        self.action = action

    def __call__(self, user=Depends(get_current_user), db: Session = Depends(get_db)):
        if user.db_id is None:
            if user.role == "admin" or "admin" in user.permissions:
                return user
            needed = "read" if self.action in {"read", "export"} else "write"
            if needed in user.permissions:
                return user
            raise HTTPException(status_code=403, detail="Permission granulaire requise")
        from app.models.admin_security import AdminUser
        db_user = db.query(AdminUser).filter(AdminUser.id == user.db_id).first()
        if not db_user or not has_permission(db_user, self.module, self.action):
            raise HTTPException(status_code=403, detail=f"Permission {self.module}:{self.action} requise")
        return user


require_read = PermissionChecker(["read"])
require_write = PermissionChecker(["read", "write"])
require_delete = PermissionChecker(["read", "write", "delete"])
require_admin = PermissionChecker(["read", "write", "delete", "admin"])
