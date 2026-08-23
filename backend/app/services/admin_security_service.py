"""Services du module 12 : RBAC, authentification, audit, backup et RGPD."""

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import smtplib
import sqlite3
import struct
import subprocess
import urllib.request
from email.message import EmailMessage
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, engine
from app.models.admin_security import (
    AdminRole,
    AdminUser,
    Agency,
    AuditLog,
    AuthChallenge,
    BackupPolicy,
    BackupRecord,
    ConsentRecord,
    DataProcessingRecord,
    DataSubjectRequest,
    GeneralSettings,
    LoginHistory,
    Organization,
    PasswordHistory,
    PrivacyPolicy,
    ReferenceIndex,
    RolePermission,
    SMTPSettings,
    SecurityPolicy,
    SecuritySession,
    SSOProvider,
    TrustedDevice,
    UserRoleAssignment,
    UserScope,
)

pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")
ALL_MODULES = [
    "properties", "owners", "tenants", "leases", "finance", "maintenance",
    "condo", "crm", "reporting", "communication", "ged", "administration", "geolocation",
]
ALL_ACTIONS = ["create", "read", "update", "delete", "export", "admin"]
PROFILE_DEFINITIONS = {
    "super_admin": {"label": "Super administrateur", "modules": {"*": ALL_ACTIONS}, "scope": "all"},
    "manager": {
        "label": "Gestionnaire",
        "modules": {
            **{module: ["create", "read", "update", "export"] for module in ALL_MODULES if module != "administration"},
            "administration": ["read"],
        },
        "scope": "assigned",
    },
    "agent": {
        "label": "Agent immobilier",
        "modules": {"properties": ["create", "read", "update"], "crm": ["create", "read", "update"], "geolocation": ["create", "read", "update"]},
        "scope": "assigned",
    },
    "accountant": {
        "label": "Comptable",
        "modules": {"finance": ["create", "read", "update", "export"], "reporting": ["read", "export"], "ged": ["create", "read"]},
        "scope": "assigned",
    },
    "viewer": {"label": "Lecture seule", "modules": {"*": ["read"]}, "scope": "assigned"},
}


def utcnow() -> datetime:
    return datetime.utcnow()


def _as_naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=None) if value.tzinfo else value


def model_dict(obj, exclude: Iterable[str] = ()) -> Dict[str, Any]:
    result = {}
    excluded = set(exclude)
    for column in inspect(obj).mapper.column_attrs:
        key = column.key
        if key in excluded:
            continue
        value = getattr(obj, key)
        if isinstance(value, (datetime,)):
            value = value.isoformat()
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        elif isinstance(value, bytes):
            value = "***"
        result[key] = value
    return result


def user_view(user: AdminUser) -> dict:
    roles = []
    for assignment in user.role_assignments:
        roles.append({
            "assignment_id": assignment.id,
            "role_id": assignment.role_id,
            "role": assignment.role.name if assignment.role else None,
            "profile_key": assignment.role.profile_key if assignment.role else None,
            "organization_id": assignment.organization_id,
            "agency_id": assignment.agency_id,
        })
    return {
        "id": user.id,
        "public_id": user.public_id,
        "email": user.email,
        "full_name": user.full_name,
        "phone": user.phone,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "must_change_password": user.must_change_password,
        "two_factor_enabled": user.two_factor_enabled,
        "two_factor_method": user.two_factor_method,
        "locale": user.locale,
        "timezone": user.timezone,
        "last_login_at": user.last_login_at,
        "locked_until": user.locked_until,
        "created_at": user.created_at,
        "roles": roles,
        "scopes": [model_dict(scope) for scope in user.scopes],
    }


def role_view(role: AdminRole) -> dict:
    return {
        "id": role.id,
        "organization_id": role.organization_id,
        "name": role.name,
        "description": role.description,
        "profile_key": role.profile_key,
        "is_system": role.is_system,
        "is_active": role.is_active,
        "permissions": [model_dict(permission) for permission in role.permissions],
    }


def sso_view(provider: SSOProvider) -> dict:
    data = model_dict(provider, exclude={"encrypted_client_secret", "certificate"})
    data["client_secret_configured"] = bool(provider.encrypted_client_secret)
    data["certificate_configured"] = bool(provider.certificate)
    return data


def smtp_view(smtp: SMTPSettings) -> dict:
    data = model_dict(smtp, exclude={"encrypted_password"})
    data["password_configured"] = bool(smtp.encrypted_password)
    return data


def _fernet() -> Fernet:
    key = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(value: Optional[str]) -> Optional[bytes]:
    return _fernet().encrypt(value.encode("utf-8")) if value else None


def decrypt_secret(value: Optional[bytes]) -> Optional[str]:
    if not value:
        return None
    try:
        return _fernet().decrypt(value).decode("utf-8")
    except InvalidToken:
        return None


def get_policy(db: Session, organization_id: Optional[int] = None) -> SecurityPolicy:
    query = db.query(SecurityPolicy)
    policy = query.filter(SecurityPolicy.organization_id == organization_id).first()
    if not policy and organization_id is not None:
        policy = query.filter(SecurityPolicy.organization_id.is_(None)).first()
    if not policy:
        policy = SecurityPolicy(organization_id=organization_id)
        db.add(policy)
        db.flush()
    return policy


def get_user_policy(db: Session, user: AdminUser) -> SecurityPolicy:
    default_scope = next((scope for scope in user.scopes if scope.is_default), None)
    scope = default_scope or (user.scopes[0] if user.scopes else None)
    return get_policy(db, scope.organization_id if scope else None)


def validate_password(password: str, policy: SecurityPolicy, user: Optional[AdminUser] = None, db: Optional[Session] = None):
    errors = []
    if len(password) < policy.password_min_length:
        errors.append(f"au moins {policy.password_min_length} caractères")
    if policy.require_uppercase and not re.search(r"[A-Z]", password):
        errors.append("une majuscule")
    if policy.require_lowercase and not re.search(r"[a-z]", password):
        errors.append("une minuscule")
    if policy.require_digit and not re.search(r"\d", password):
        errors.append("un chiffre")
    if policy.require_special and not re.search(r"[^A-Za-z0-9]", password):
        errors.append("un caractère spécial")
    if user and user.email.split("@", 1)[0].lower() in password.lower():
        errors.append("ne pas contenir l'identifiant email")
    if user and db and policy.password_history_count:
        history = (
            db.query(PasswordHistory)
            .filter(PasswordHistory.user_id == user.id)
            .order_by(PasswordHistory.changed_at.desc())
            .limit(policy.password_history_count)
            .all()
        )
        candidates = [user.password_hash] + [entry.password_hash for entry in history]
        if any(pwd_context.verify(password, old_hash) for old_hash in candidates if old_hash):
            errors.append("être différent des derniers mots de passe")
    if errors:
        raise ValueError("Le mot de passe doit contenir " + ", ".join(errors))


def _create_system_role(db: Session, profile_key: str) -> AdminRole:
    profile = PROFILE_DEFINITIONS[profile_key]
    role = AdminRole(
        name=profile["label"], description=f"Profil prédéfini {profile['label']}",
        profile_key=profile_key, is_system=True,
    )
    db.add(role)
    db.flush()
    for module, actions in profile["modules"].items():
        db.add(RolePermission(role_id=role.id, module=module, actions=actions, scope_type=profile["scope"]))
    return role


def bootstrap_security() -> None:
    """Crée les profils et comptes historiques sans écraser de configuration."""
    db = SessionLocal()
    try:
        roles = {}
        for key in PROFILE_DEFINITIONS:
            role = db.query(AdminRole).filter(AdminRole.profile_key == key, AdminRole.is_system == True).first()
            roles[key] = role or _create_system_role(db, key)
        if not db.query(SecurityPolicy).filter(SecurityPolicy.organization_id.is_(None)).first():
            db.add(SecurityPolicy())
        if not db.query(BackupPolicy).first():
            db.add(BackupPolicy())
        db.flush()

        legacy = [
            ("admin@immogest.com", "Administrateur", "Admin@2024!", "super_admin", True),
            ("gestionnaire@immogest.com", "Gestionnaire", "Manager@2024!", "manager", False),
            ("lecteur@immogest.com", "Lecteur", "Viewer@2024!", "viewer", False),
        ]
        for email, name, password, profile, superuser in legacy:
            if db.query(AdminUser).filter(AdminUser.email == email).first():
                continue
            user = AdminUser(
                email=email, full_name=name, password_hash=pwd_context.hash(password),
                is_superuser=superuser,
            )
            db.add(user)
            db.flush()
            db.add(UserRoleAssignment(user_id=user.id, role_id=roles[profile].id, assigned_by="bootstrap"))
        db.commit()
    finally:
        db.close()


def assign_user_roles_and_scopes(db: Session, user: AdminUser, roles, scopes, actor: str):
    if roles is not None:
        db.query(UserRoleAssignment).filter(UserRoleAssignment.user_id == user.id).delete(synchronize_session=False)
        for item in roles:
            role = db.query(AdminRole).filter(AdminRole.id == item.role_id, AdminRole.is_active == True).first()
            if not role:
                raise ValueError(f"Rôle {item.role_id} introuvable")
            if item.agency_id:
                agency = db.query(Agency).filter(Agency.id == item.agency_id, Agency.is_active == True).first()
                if not agency or (item.organization_id and agency.organization_id != item.organization_id):
                    raise ValueError("Agence incohérente avec la société")
            db.add(UserRoleAssignment(
                user_id=user.id, role_id=item.role_id, organization_id=item.organization_id,
                agency_id=item.agency_id, assigned_by=actor,
            ))
    if scopes is not None:
        db.query(UserScope).filter(UserScope.user_id == user.id).delete(synchronize_session=False)
        defaults = sum(1 for scope in scopes if scope.is_default)
        if defaults > 1:
            raise ValueError("Un seul périmètre peut être défini par défaut")
        for item in scopes:
            organization = db.query(Organization).filter(Organization.id == item.organization_id).first()
            if not organization:
                raise ValueError(f"Société {item.organization_id} introuvable")
            if item.agency_id:
                agency = db.query(Agency).filter(Agency.id == item.agency_id).first()
                if not agency or agency.organization_id != item.organization_id:
                    raise ValueError("Agence incohérente avec la société")
            db.add(UserScope(
                user_id=user.id, organization_id=item.organization_id, agency_id=item.agency_id,
                portfolio_ids=item.portfolio_ids, is_default=item.is_default,
            ))


def effective_permissions(user: AdminUser) -> list[dict]:
    if user.is_superuser:
        return [{"module": "*", "actions": ALL_ACTIONS, "scope_type": "all", "scope_ids": []}]
    merged: dict[tuple, set] = {}
    for assignment in user.role_assignments:
        if not assignment.role or not assignment.role.is_active:
            continue
        for permission in assignment.role.permissions:
            scope_ids = tuple(sorted(permission.scope_ids or []))
            key = (permission.module, permission.scope_type, scope_ids, assignment.organization_id, assignment.agency_id)
            merged.setdefault(key, set()).update(permission.actions or [])
    return [
        {
            "module": key[0], "scope_type": key[1], "scope_ids": list(key[2]),
            "organization_id": key[3], "agency_id": key[4], "actions": sorted(actions),
        }
        for key, actions in merged.items()
    ]


def has_permission(
    user: AdminUser, module: str, action: str,
    organization_id: Optional[int] = None, agency_id: Optional[int] = None,
    portfolio_id: Optional[int] = None,
) -> bool:
    if user.is_superuser:
        return True
    user_scopes = user.scopes or []
    for permission in effective_permissions(user):
        if permission["module"] not in {"*", module} or action not in permission["actions"]:
            continue
        assigned_org = permission.get("organization_id")
        assigned_agency = permission.get("agency_id")
        if organization_id is not None and assigned_org is not None and organization_id != assigned_org:
            continue
        if agency_id is not None and assigned_agency is not None and agency_id != assigned_agency:
            continue
        scope_type = permission["scope_type"]
        if scope_type == "all":
            return True
        if scope_type == "entity" and (organization_id is None or organization_id in permission["scope_ids"] or organization_id == assigned_org):
            return True
        if scope_type == "agency" and (agency_id is None or agency_id in permission["scope_ids"] or agency_id == assigned_agency):
            return True
        if scope_type == "portfolio" and (portfolio_id is None or portfolio_id in permission["scope_ids"]):
            return True
        if scope_type == "assigned":
            if organization_id is None and agency_id is None and portfolio_id is None:
                return True
            if any(
                (organization_id is None or scope.organization_id == organization_id)
                and (agency_id is None or scope.agency_id in {None, agency_id})
                and (portfolio_id is None or portfolio_id in (scope.portfolio_ids or []))
                for scope in user_scopes
            ):
                return True
    return False


def log_audit(
    db: Session, *, actor, action: str, module: str, resource_type: Optional[str] = None,
    resource_id: Optional[Any] = None, description: Optional[str] = None,
    before: Optional[dict] = None, after: Optional[dict] = None,
    request=None, organization_id: Optional[int] = None, agency_id: Optional[int] = None,
) -> AuditLog:
    entry = AuditLog(
        organization_id=organization_id,
        agency_id=agency_id,
        actor_user_id=getattr(actor, "db_id", None) or (getattr(actor, "id", None) if isinstance(getattr(actor, "id", None), int) else None),
        actor_email=getattr(actor, "email", str(actor) if actor else "system"),
        action=action, module=module, resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        description=description,
        before_data=json.loads(json.dumps(before, default=str)) if before is not None else None,
        after_data=json.loads(json.dumps(after, default=str)) if after is not None else None,
        ip_address=request.client.host if request is not None and request.client else None,
        user_agent=request.headers.get("user-agent") if request is not None else None,
    )
    db.add(entry)
    return entry


def record_login(db: Session, email: str, success: bool, request=None, user_id=None, reason=None, method="password"):
    db.add(LoginHistory(
        user_id=user_id, email=email.lower(), success=success, failure_reason=reason,
        ip_address=request.client.host if request is not None and request.client else None,
        user_agent=request.headers.get("user-agent") if request is not None else None,
        method=method,
    ))


def totp_code(secret: str, at_time: Optional[datetime] = None) -> str:
    moment = at_time or utcnow()
    counter = int(moment.timestamp()) // 30
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{number:06d}"


def verify_totp(secret: str, code: str) -> bool:
    return any(hmac.compare_digest(totp_code(secret, utcnow() + timedelta(seconds=offset)), code) for offset in (-30, 0, 30))


def create_otp_challenge(db: Session, user: AdminUser, purpose: str, method: str) -> tuple[AuthChallenge, Optional[str]]:
    challenge = AuthChallenge(
        user_id=user.id, purpose=purpose, method=method,
        expires_at=utcnow() + timedelta(minutes=5),
    )
    code = None
    if method == "authenticator":
        challenge.challenge = "totp"
    else:
        code = f"{secrets.randbelow(1_000_000):06d}"
        challenge.code_hash = hashlib.sha256(code.encode()).hexdigest()
        challenge.challenge = "delivery_queued"
    db.add(challenge)
    db.flush()
    return challenge, code


def deliver_otp_code(db: Session, user: AdminUser, method: str, code: Optional[str]) -> str:
    """Livre un code 2FA via la configuration réelle disponible.

    En développement le code est retourné par l'API et aucun envoi externe
    n'est simulé. En production, l'absence de transport configuré est une
    erreur explicite qui empêche de marquer le challenge comme envoyé.
    """
    if not code:
        return "authenticator"
    if settings.ENVIRONMENT != "production":
        return "development_code_returned"
    if method == "email":
        organization_id = next((scope.organization_id for scope in user.scopes if scope.is_default), None)
        smtp = db.query(SMTPSettings).filter(SMTPSettings.organization_id == organization_id).first()
        if not smtp:
            smtp = db.query(SMTPSettings).filter(SMTPSettings.organization_id.is_(None)).first()
        if not smtp or not smtp.is_enabled or not smtp.host or not smtp.from_email:
            raise ValueError("Transport SMTP 2FA non configuré")
        message = EmailMessage()
        message["Subject"] = "Votre code de sécurité GestImmo"
        message["From"] = f"{smtp.from_name} <{smtp.from_email}>" if smtp.from_name else smtp.from_email
        message["To"] = user.email
        message.set_content(f"Votre code de connexion GestImmo est : {code}\nIl expire dans 5 minutes.")
        client_class = smtplib.SMTP_SSL if smtp.use_ssl else smtplib.SMTP
        with client_class(smtp.host, smtp.port, timeout=10) as client:
            if smtp.use_tls:
                client.starttls()
            password = decrypt_secret(smtp.encrypted_password)
            if smtp.username and password:
                client.login(smtp.username, password)
            client.send_message(message)
        return "email_sent"
    if method == "sms":
        if not user.phone:
            raise ValueError("Numéro de téléphone absent")
        if not settings.SMS_WEBHOOK_URL:
            raise ValueError("Transport SMS 2FA non configuré")
        payload = json.dumps({"to": user.phone, "message": f"Code GestImmo : {code} (5 min)"}).encode()
        headers = {"Content-Type": "application/json"}
        if settings.SMS_WEBHOOK_TOKEN:
            headers["Authorization"] = f"Bearer {settings.SMS_WEBHOOK_TOKEN}"
        request = urllib.request.Request(settings.SMS_WEBHOOK_URL, payload, headers, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 300:
                raise ValueError(f"Transport SMS refusé ({response.status})")
        return "sms_sent"
    raise ValueError("Méthode de livraison 2FA inconnue")


def verify_challenge(db: Session, token: str, code: str, purpose: str) -> AuthChallenge:
    challenge = db.query(AuthChallenge).filter(AuthChallenge.id == token).first()
    if not challenge or challenge.purpose != purpose:
        raise ValueError("Challenge invalide")
    if challenge.consumed_at or _as_naive(challenge.expires_at) < utcnow():
        raise ValueError("Challenge expiré ou déjà utilisé")
    if challenge.attempts >= 5:
        raise ValueError("Nombre maximal d'essais atteint")
    challenge.attempts += 1
    user = db.query(AdminUser).filter(AdminUser.id == challenge.user_id).first()
    if challenge.method == "authenticator":
        valid = bool(user and user.two_factor_secret and verify_totp(user.two_factor_secret, code))
    else:
        valid = hmac.compare_digest(challenge.code_hash or "", hashlib.sha256(code.encode()).hexdigest())
    if not valid:
        db.commit()
        raise ValueError("Code invalide")
    challenge.consumed_at = utcnow()
    return challenge


def create_backup(db: Session, actor: str, trigger: str = "manual") -> BackupRecord:
    backup_dir = Path(settings.backup_dir_path)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%dT%H%M%S%f")
    dialect = engine.url.get_backend_name()
    suffix = ".sqlite3" if dialect == "sqlite" else ".dump"
    filename = f"gestimmo-{trigger}-{stamp}{suffix}"
    path = backup_dir / filename
    record = BackupRecord(
        filename=filename, storage_path=str(path), database_kind=dialect,
        trigger=trigger, status="running", created_by=actor,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    try:
        if dialect == "sqlite":
            source_path = engine.url.database
            if not source_path or source_path == ":memory:":
                raise ValueError("Les bases SQLite en mémoire ne peuvent pas être sauvegardées")
            source = sqlite3.connect(source_path)
            destination = sqlite3.connect(str(path))
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
        elif dialect in {"postgresql", "postgres"}:
            env = os.environ.copy()
            if engine.url.password:
                env["PGPASSWORD"] = engine.url.password
            command = ["pg_dump", "--format=custom", "--file", str(path), str(engine.url.set(password=None))]
            completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=900, check=False)
            if completed.returncode:
                raise RuntimeError(completed.stderr.strip() or "pg_dump a échoué")
        else:
            raise ValueError(f"Moteur de base non pris en charge : {dialect}")
        content = path.read_bytes()
        record.size_bytes = len(content)
        record.checksum_sha256 = hashlib.sha256(content).hexdigest()
        record.status = "completed"
        record.completed_at = utcnow()
    except Exception as exc:
        record.status = "failed"
        record.error_message = str(exc)[:2000]
        if path.exists():
            path.unlink()
    db.commit()
    db.refresh(record)
    return record


def validate_backup(record: BackupRecord) -> Path:
    path = Path(record.storage_path)
    if record.status != "completed" or not path.is_file():
        raise ValueError("Sauvegarde indisponible")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not hmac.compare_digest(digest, record.checksum_sha256 or ""):
        raise ValueError("L'intégrité de la sauvegarde est invalide")
    if record.database_kind == "sqlite":
        connection = sqlite3.connect(str(path))
        try:
            check = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()
        if check != "ok":
            raise ValueError("La sauvegarde SQLite est corrompue")
    return path


def restore_backup(db: Session, record: BackupRecord) -> BackupRecord:
    """Restaure SQLite. PostgreSQL nécessite pg_restore et un redémarrage contrôlé."""
    path = validate_backup(record)
    dialect = engine.url.get_backend_name()
    if dialect != "sqlite" or record.database_kind != "sqlite":
        raise ValueError("La restauration PostgreSQL doit être exécutée hors ligne avec pg_restore")
    destination = engine.url.database
    if not destination or destination == ":memory:":
        raise ValueError("Restauration impossible sur une base en mémoire")
    # Le demandeur doit avoir créé une sauvegarde de sécurité avant d'appeler
    # cette fonction. La copie atomique réduit la fenêtre d'incohérence.
    db.close()
    engine.dispose()
    temp = Path(destination).with_suffix(".restore.tmp")
    shutil.copy2(path, temp)
    os.replace(temp, destination)
    record.restored_at = utcnow()
    # La session reçue pointe vers l'ancien fichier : persistance via une session neuve.
    fresh = SessionLocal()
    try:
        restored = fresh.query(BackupRecord).filter(BackupRecord.id == record.id).first()
        if restored:
            restored.restored_at = record.restored_at
            fresh.commit()
    finally:
        fresh.close()
    return record


def apply_backup_retention(db: Session) -> dict:
    policy = db.query(BackupPolicy).first() or BackupPolicy()
    if policy.id is None:
        db.add(policy)
        db.flush()
    cutoff = utcnow() - timedelta(days=policy.retention_days)
    expired = db.query(BackupRecord).filter(BackupRecord.created_at < cutoff).all()
    deleted = 0
    for record in expired:
        path = Path(record.storage_path)
        if path.is_file():
            path.unlink()
        db.delete(record)
        deleted += 1
    db.commit()
    return {"deleted": deleted, "retention_days": policy.retention_days}


def run_daily_backup_if_due(db: Session, actor: str = "scheduler") -> dict:
    # Verrou transactionnel : plusieurs workers ne déclenchent pas chacun la
    # même sauvegarde quotidienne.
    policy = db.query(BackupPolicy).with_for_update().first()
    if not policy or not policy.enabled:
        return {"created": False, "reason": "disabled"}
    now = utcnow()
    last = _as_naive(policy.last_run_at)
    if now.hour < policy.daily_hour_utc or (last and last.date() == now.date()):
        return {"created": False, "reason": "not_due"}
    policy.last_run_at = now
    db.commit()  # réserve le créneau du jour avant la copie potentiellement longue
    record = create_backup(db, actor, "daily")
    apply_backup_retention(db)
    return {"created": record.status == "completed", "backup": model_dict(record)}


def audit_csv(logs: list[AuditLog]) -> bytes:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["id", "date", "acteur", "ip", "module", "action", "ressource", "identifiant", "description"])
    for log in logs:
        writer.writerow([
            log.id, log.occurred_at.isoformat() if log.occurred_at else "", log.actor_email,
            log.ip_address, log.module, log.action, log.resource_type, log.resource_id, log.description,
        ])
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def subject_data(db: Session, subject_type: str, subject_id: str) -> dict:
    """Produit un paquet portable JSON depuis les modèles connus.

    L'export est volontairement explicite : aucune introspection arbitraire de
    tables n'est exposée au client.
    """
    package = {
        "exported_at": utcnow().isoformat() + "Z",
        "subject": {"type": subject_type, "id": subject_id},
        "consents": [model_dict(item) for item in db.query(ConsentRecord).filter(
            ConsentRecord.subject_type == subject_type, ConsentRecord.subject_id == subject_id
        ).all()],
    }
    if subject_type == "user":
        try:
            user_id = int(subject_id)
        except ValueError:
            user_id = 0
        user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
        package["profile"] = user_view(user) if user else None
        package["login_history"] = [model_dict(item) for item in db.query(LoginHistory).filter(
            LoginHistory.user_id == user_id
        ).all()]
    elif subject_type in {"tenant", "owner"}:
        if subject_type == "tenant":
            from app.models.tenant import Tenant
            model = Tenant
        else:
            from app.models.owner import Owner
            model = Owner
        try:
            row = db.query(model).filter(model.id == int(subject_id)).first()
        except (ValueError, TypeError):
            row = None
        package["profile"] = model_dict(row, exclude={"portal_password_hash", "password_hash"}) if row else None
    else:
        package["profile"] = None
    return package


def anonymize_subject(db: Session, subject_type: str, subject_id: str) -> dict:
    """Anonymise les champs identifiants sans supprimer les écritures légales."""
    marker = hashlib.sha256(f"{subject_type}:{subject_id}:{settings.SECRET_KEY}".encode()).hexdigest()[:12]
    changed = False
    if subject_type == "user":
        user = db.query(AdminUser).filter(AdminUser.id == int(subject_id)).first()
        if user:
            user.email = f"deleted-{marker}@anonymized.invalid"
            user.full_name = "Utilisateur supprimé"
            user.phone = None
            user.password_hash = pwd_context.hash(secrets.token_urlsafe(48))
            user.is_active = False
            user.deactivated_at = utcnow()
            db.query(SecuritySession).filter(SecuritySession.user_id == user.id, SecuritySession.revoked_at.is_(None)).update(
                {"revoked_at": utcnow(), "revoke_reason": "gdpr_erasure"}, synchronize_session=False
            )
            changed = True
    elif subject_type in {"tenant", "owner"}:
        if subject_type == "tenant":
            from app.models.tenant import Tenant
            model = Tenant
        else:
            from app.models.owner import Owner
            model = Owner
        row = db.query(model).filter(model.id == int(subject_id)).first()
        if row:
            for field, value in {
                "email": f"deleted-{marker}@anonymized.invalid", "phone": None,
                "mobile": None, "address": None, "first_name": "Supprimé", "last_name": marker,
                "name": f"Sujet supprimé {marker}",
            }.items():
                if hasattr(row, field):
                    setattr(row, field, value)
            changed = True
    db.commit()
    return {"anonymized": changed, "marker": marker}
