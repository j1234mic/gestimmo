from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, OAuth2PasswordBearer
from pydantic import BaseModel
import secrets
from app.config import settings
from app.utils.logger import security_logger

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

class User(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    permissions: list = []

class UserInDB(User):
    hashed_password: str
    failed_login_attempts: int = 0
    locked_until: Optional[datetime] = None

USERS_DB = {
    "admin@immogest.com": UserInDB(
        id="user_001", email="admin@immogest.com",
        full_name="Administrateur", role="admin",
        permissions=["read", "write", "delete", "admin"],
        hashed_password=pwd_context.hash("Admin@2024!"),
    ),
    "gestionnaire@immogest.com": UserInDB(
        id="user_002", email="gestionnaire@immogest.com",
        full_name="Gestionnaire", role="manager",
        permissions=["read", "write"],
        hashed_password=pwd_context.hash("Manager@2024!"),
    ),
    "lecteur@immogest.com": UserInDB(
        id="user_003", email="lecteur@immogest.com",
        full_name="Lecteur", role="viewer",
        permissions=["read"],
        hashed_password=pwd_context.hash("Viewer@2024!"),
    ),
}

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def get_user(email: str):
    return USERS_DB.get(email)

def authenticate_user(email: str, password: str):
    user = get_user(email)
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user

def create_access_token(data: dict, expires_delta=None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=30))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")

def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(days=7)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm="HS256")

def decode_token(token: str):
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])

async def get_current_user(request: Request):
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        raise HTTPException(status_code=401, detail="Authentification requise")
    try:
        payload = decode_token(token)
        email = payload.get("sub")
        user = get_user(email)
        if not user:
            raise HTTPException(status_code=401, detail="Utilisateur non trouvé")
        return user
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")

async def get_optional_user(request: Request):
    try:
        return await get_current_user(request)
    except HTTPException:
        return None

class PermissionChecker:
    def __init__(self, perms):
        self.perms = perms
    def __call__(self, user=Depends(get_current_user)):
        for p in self.perms:
            if p not in user.permissions:
                raise HTTPException(status_code=403, detail=f"Permission '{p}' requise")
        return user

require_read = PermissionChecker(["read"])
require_write = PermissionChecker(["read", "write"])
require_delete = PermissionChecker(["read", "write", "delete"])
require_admin = PermissionChecker(['read', 'write', 'delete', 'admin'])
