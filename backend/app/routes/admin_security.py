"""API du module 12 : administration, sécurité, audit, sauvegarde et RGPD."""

import json
import smtplib
import textwrap

import httpx
from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import GranularPermissionChecker, get_current_user, verify_password
from app.database import get_db
from app.models.admin_security import (
    AdminRole,
    AdminUser,
    Agency,
    AuditLog,
    BackupPolicy,
    BackupRecord,
    ConsentRecord,
    DataProcessingRecord,
    DataSubjectRequest,
    GeneralSettings,
    LoginHistory,
    NumberingSequence,
    Organization,
    PasswordHistory,
    PrivacyPolicy,
    ReferenceIndex,
    RolePermission,
    SMTPSettings,
    SecurityPolicy,
    SecuritySession,
    SSOProvider,
    UserRoleAssignment,
    UserScope,
)
from app.models.property import Property
from app.schemas.admin_security import (
    AgencyCreate,
    AgencyUpdate,
    BackupPolicyUpdate,
    ConsentCreate,
    DataSubjectProcess,
    DataSubjectRequestCreate,
    DeactivateUser,
    GeneralSettingsUpdate,
    NumberingSequenceConfig,
    OrganizationCreate,
    OrganizationUpdate,
    PasswordChange,
    PrivacyPolicyCreate,
    ProcessingRecordCreate,
    ReferenceIndexCreate,
    RestoreRequest,
    RoleCreate,
    RoleUpdate,
    SMTPSettingsUpdate,
    SSOProviderCreate,
    SecurityPolicyUpdate,
    UserCreate,
    UserUpdate,
)
from app.services import admin_security_service as service

router = APIRouter(prefix="/api/admin", tags=["Administration et sécurité"])
public_router = APIRouter(prefix="/api/privacy", tags=["RGPD"])
admin_read = GranularPermissionChecker("administration", "read")
admin_create = GranularPermissionChecker("administration", "create")
admin_update = GranularPermissionChecker("administration", "update")
admin_delete = GranularPermissionChecker("administration", "delete")
admin_export = GranularPermissionChecker("administration", "export")
admin_manage = GranularPermissionChecker("administration", "admin")


def _admin_unrestricted(user) -> bool:
    return bool(user.is_superuser or any(
        permission.get("module") in {"*", "administration"} and permission.get("scope_type") == "all"
        for permission in user.granular_permissions
    ))


def _require_entity_scope(user, organization_id: Optional[int], agency_id: Optional[int] = None):
    if _admin_unrestricted(user):
        return
    if organization_id is None or organization_id not in user.organization_ids:
        raise HTTPException(status_code=403, detail="Société hors périmètre")
    if (
        agency_id is not None
        and organization_id not in user.organization_wide_ids
        and agency_id not in user.agency_ids
    ):
        raise HTTPException(status_code=403, detail="Agence hors périmètre")


def _require_global_admin(user):
    if not _admin_unrestricted(user):
        raise HTTPException(status_code=403, detail="Administration globale requise")


def _require_user_scope(actor, target: AdminUser):
    if _admin_unrestricted(actor):
        return
    target_organizations = {scope.organization_id for scope in target.scopes}
    if not target_organizations.intersection(actor.organization_ids):
        raise HTTPException(status_code=403, detail="Utilisateur hors périmètre")


def _not_found(label="Ressource"):
    raise HTTPException(status_code=404, detail=f"{label} introuvable")


def _integrity_error(db: Session, message: str):
    db.rollback()
    raise HTTPException(status_code=409, detail=message)


def _update_model(obj, data):
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(obj, field, value)


# ---------------------------------------------------------------------------
# Sociétés et agences
# ---------------------------------------------------------------------------
@router.post("/organizations", status_code=201)
def create_organization(
    data: OrganizationCreate, request: Request, db: Session = Depends(get_db), current_user=Depends(admin_create)
):
    if not _admin_unrestricted(current_user):
        raise HTTPException(status_code=403, detail="Seul un administrateur global peut créer une société")
    organization = Organization(**data.model_dump(mode="json"))
    db.add(organization)
    db.flush()
    db.add(GeneralSettings(organization_id=organization.id))
    db.add(SecurityPolicy(organization_id=organization.id))
    service.log_audit(
        db, actor=current_user, action="create", module="administration", resource_type="organization",
        resource_id=organization.id, after=service.model_dict(organization), request=request,
        organization_id=organization.id,
    )
    db.commit()
    db.refresh(organization)
    return service.model_dict(organization)


@router.get("/organizations")
def list_organizations(
    active_only: bool = True, db: Session = Depends(get_db), current_user=Depends(admin_read)
):
    query = db.query(Organization)
    if not _admin_unrestricted(current_user):
        query = query.filter(Organization.id.in_(current_user.organization_ids))
    if active_only:
        query = query.filter(Organization.is_active == True)
    rows = query.order_by(Organization.name).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows)}


@router.get("/organizations/{organization_id}")
def get_organization(organization_id: int, db: Session = Depends(get_db), current_user=Depends(admin_read)):
    row = db.query(Organization).filter(Organization.id == organization_id).first()
    if not row:
        _not_found("Société")
    _require_entity_scope(current_user, row.id)
    data = service.model_dict(row)
    data["agencies"] = [service.model_dict(agency) for agency in row.agencies]
    return data


@router.put("/organizations/{organization_id}")
def update_organization(
    organization_id: int, data: OrganizationUpdate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_update),
):
    row = db.query(Organization).filter(Organization.id == organization_id).first()
    if not row:
        _not_found("Société")
    _require_entity_scope(current_user, row.id)
    before = service.model_dict(row)
    _update_model(row, data)
    db.flush()
    service.log_audit(
        db, actor=current_user, action="update", module="administration", resource_type="organization",
        resource_id=row.id, before=before, after=service.model_dict(row), request=request,
        organization_id=row.id,
    )
    db.commit()
    return service.model_dict(row)


@router.get("/organizations/{organization_id}/reporting")
def organization_reporting(
    organization_id: int, consolidated: bool = True,
    db: Session = Depends(get_db), current_user=Depends(admin_read),
):
    organization = db.query(Organization).filter(Organization.id == organization_id).first()
    if not organization:
        _not_found("Société")
    _require_entity_scope(current_user, organization_id)
    agency_rows = []
    agencies = db.query(Agency).filter(Agency.organization_id == organization_id).all()
    for agency in agencies:
        query = db.query(Property).filter(Property.is_active == True, Property.agency_id == agency.id)
        agency_rows.append({
            "agency_id": agency.id,
            "agency": agency.name,
            "properties": query.count(),
            "monthly_rent": float(query.with_entities(func.coalesce(func.sum(Property.rent_price), 0)).scalar() or 0),
            "sale_value": float(query.with_entities(func.coalesce(func.sum(Property.sale_price), 0)).scalar() or 0),
        })
    unassigned_query = db.query(Property).filter(
        Property.is_active == True, Property.entity_id == organization_id, Property.agency_id.is_(None)
    )
    result = {"organization_id": organization_id, "by_agency": agency_rows}
    if consolidated:
        org_query = db.query(Property).filter(Property.is_active == True, Property.entity_id == organization_id)
        result["consolidated"] = {
            "properties": org_query.count(),
            "monthly_rent": float(org_query.with_entities(func.coalesce(func.sum(Property.rent_price), 0)).scalar() or 0),
            "sale_value": float(org_query.with_entities(func.coalesce(func.sum(Property.sale_price), 0)).scalar() or 0),
            "unassigned_properties": unassigned_query.count(),
        }
    return result


@router.post("/agencies", status_code=201)
def create_agency(
    data: AgencyCreate, request: Request, db: Session = Depends(get_db), current_user=Depends(admin_create)
):
    _require_entity_scope(current_user, data.organization_id)
    if not db.query(Organization).filter(Organization.id == data.organization_id, Organization.is_active == True).first():
        _not_found("Société")
    agency = Agency(**data.model_dump(mode="json"))
    db.add(agency)
    try:
        db.flush()
    except IntegrityError:
        _integrity_error(db, "Ce code d'agence existe déjà dans la société")
    service.log_audit(
        db, actor=current_user, action="create", module="administration", resource_type="agency",
        resource_id=agency.id, after=service.model_dict(agency), request=request,
        organization_id=agency.organization_id, agency_id=agency.id,
    )
    db.commit()
    return service.model_dict(agency)


@router.get("/agencies")
def list_agencies(
    organization_id: Optional[int] = None, active_only: bool = True,
    db: Session = Depends(get_db), current_user=Depends(admin_read),
):
    query = db.query(Agency)
    if not _admin_unrestricted(current_user):
        query = query.filter(or_(
            Agency.organization_id.in_(current_user.organization_wide_ids),
            Agency.id.in_(current_user.agency_ids),
        ))
    if organization_id is not None:
        _require_entity_scope(current_user, organization_id)
        query = query.filter(Agency.organization_id == organization_id)
    if active_only:
        query = query.filter(Agency.is_active == True)
    rows = query.order_by(Agency.name).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows)}


@router.put("/agencies/{agency_id}")
def update_agency(
    agency_id: int, data: AgencyUpdate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_update),
):
    row = db.query(Agency).filter(Agency.id == agency_id).first()
    if not row:
        _not_found("Agence")
    _require_entity_scope(current_user, row.organization_id, row.id)
    before = service.model_dict(row)
    _update_model(row, data)
    try:
        db.flush()
    except IntegrityError:
        _integrity_error(db, "Ce code d'agence existe déjà dans la société")
    service.log_audit(
        db, actor=current_user, action="update", module="administration", resource_type="agency",
        resource_id=row.id, before=before, after=service.model_dict(row), request=request,
        organization_id=row.organization_id, agency_id=row.id,
    )
    db.commit()
    return service.model_dict(row)


# ---------------------------------------------------------------------------
# Rôles, profils et permissions
# ---------------------------------------------------------------------------
@router.get("/roles/profiles")
def predefined_profiles(current_user=Depends(admin_read)):
    return {"data": [dict(key=key, **profile) for key, profile in service.PROFILE_DEFINITIONS.items()]}


@router.post("/roles", status_code=201)
def create_role(data: RoleCreate, request: Request, db: Session = Depends(get_db), current_user=Depends(admin_create)):
    _require_entity_scope(current_user, data.organization_id)
    role = AdminRole(
        organization_id=data.organization_id, name=data.name, description=data.description,
        is_system=False,
    )
    db.add(role)
    try:
        db.flush()
    except IntegrityError:
        _integrity_error(db, "Un rôle de ce nom existe déjà")
    for permission in data.permissions:
        db.add(RolePermission(role_id=role.id, **permission.model_dump()))
    db.flush()
    service.log_audit(
        db, actor=current_user, action="create", module="administration", resource_type="role",
        resource_id=role.id, after=service.role_view(role), request=request,
        organization_id=role.organization_id,
    )
    db.commit()
    db.refresh(role)
    return service.role_view(role)


@router.get("/roles")
def list_roles(
    organization_id: Optional[int] = None, db: Session = Depends(get_db), current_user=Depends(admin_read)
):
    query = db.query(AdminRole)
    if not _admin_unrestricted(current_user):
        query = query.filter(or_(AdminRole.organization_id.in_(current_user.organization_ids), AdminRole.organization_id.is_(None)))
    if organization_id is not None:
        _require_entity_scope(current_user, organization_id)
        query = query.filter(or_(AdminRole.organization_id == organization_id, AdminRole.organization_id.is_(None)))
    roles = query.order_by(AdminRole.is_system.desc(), AdminRole.name).all()
    return {"data": [service.role_view(role) for role in roles], "count": len(roles)}


@router.get("/roles/{role_id}")
def get_role(role_id: int, db: Session = Depends(get_db), current_user=Depends(admin_read)):
    role = db.query(AdminRole).filter(AdminRole.id == role_id).first()
    if not role:
        _not_found("Rôle")
    if role.organization_id is not None:
        _require_entity_scope(current_user, role.organization_id)
    return service.role_view(role)


@router.put("/roles/{role_id}")
def update_role(
    role_id: int, data: RoleUpdate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_update),
):
    role = db.query(AdminRole).filter(AdminRole.id == role_id).first()
    if not role:
        _not_found("Rôle")
    if role.is_system:
        raise HTTPException(status_code=409, detail="Un profil système ne peut pas être modifié")
    _require_entity_scope(current_user, role.organization_id)
    before = service.role_view(role)
    scalar = data.model_dump(exclude_unset=True, exclude={"permissions"})
    for field, value in scalar.items():
        setattr(role, field, value)
    if data.permissions is not None:
        db.query(RolePermission).filter(RolePermission.role_id == role.id).delete(synchronize_session=False)
        for permission in data.permissions:
            db.add(RolePermission(role_id=role.id, **permission.model_dump()))
    db.flush()
    if data.permissions is not None:
        db.expire(role, ["permissions"])
    service.log_audit(
        db, actor=current_user, action="update", module="administration", resource_type="role",
        resource_id=role.id, before=before, after=service.role_view(role), request=request,
        organization_id=role.organization_id,
    )
    db.commit()
    return service.role_view(role)


@router.delete("/roles/{role_id}")
def delete_role(
    role_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(admin_delete)
):
    role = db.query(AdminRole).filter(AdminRole.id == role_id).first()
    if not role:
        _not_found("Rôle")
    if role.is_system:
        raise HTTPException(status_code=409, detail="Un profil système ne peut pas être supprimé")
    _require_entity_scope(current_user, role.organization_id)
    if db.query(UserRoleAssignment).filter(UserRoleAssignment.role_id == role.id).count():
        raise HTTPException(status_code=409, detail="Le rôle est encore attribué")
    before = service.role_view(role)
    db.delete(role)
    service.log_audit(
        db, actor=current_user, action="delete", module="administration", resource_type="role",
        resource_id=role_id, before=before, request=request, organization_id=role.organization_id,
    )
    db.commit()
    return {"deleted": True, "id": role_id}


# ---------------------------------------------------------------------------
# Utilisateurs
# ---------------------------------------------------------------------------
@router.post("/users", status_code=201)
def create_user(data: UserCreate, request: Request, db: Session = Depends(get_db), current_user=Depends(admin_create)):
    for scope in data.scopes:
        _require_entity_scope(current_user, scope.organization_id, scope.agency_id)
    for assignment in data.roles:
        _require_entity_scope(current_user, assignment.organization_id, assignment.agency_id)
    if db.query(AdminUser).filter(AdminUser.email == data.email.lower()).first():
        raise HTTPException(status_code=409, detail="Cet email est déjà utilisé")
    policy = service.get_policy(db, data.scopes[0].organization_id if data.scopes else None)
    try:
        service.validate_password(data.password, policy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    user = AdminUser(
        email=data.email.lower(), full_name=data.full_name, phone=data.phone,
        password_hash=service.pwd_context.hash(data.password), locale=data.locale,
        timezone=data.timezone, must_change_password=data.must_change_password,
    )
    db.add(user)
    db.flush()
    try:
        service.assign_user_roles_and_scopes(db, user, data.roles, data.scopes, current_user.email)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    service.log_audit(
        db, actor=current_user, action="create", module="administration", resource_type="user",
        resource_id=user.id, after=service.user_view(user), request=request,
    )
    db.commit()
    db.refresh(user)
    return service.user_view(user)


@router.get("/users")
def list_users(
    q: Optional[str] = None, active: Optional[bool] = None,
    organization_id: Optional[int] = None, agency_id: Optional[int] = None,
    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db), current_user=Depends(admin_read),
):
    query = db.query(AdminUser)
    if not _admin_unrestricted(current_user):
        query = query.filter(AdminUser.scopes.any(UserScope.organization_id.in_(current_user.organization_ids)))
    if q:
        term = f"%{q}%"
        query = query.filter(or_(AdminUser.email.ilike(term), AdminUser.full_name.ilike(term)))
    if active is not None:
        query = query.filter(AdminUser.is_active == active)
    if organization_id is not None:
        query = query.filter(AdminUser.scopes.any(UserScope.organization_id == organization_id))
    if agency_id is not None:
        query = query.filter(AdminUser.scopes.any(UserScope.agency_id == agency_id))
    total = query.distinct().count()
    users = query.distinct().order_by(AdminUser.full_name).offset((page - 1) * limit).limit(limit).all()
    return {"data": [service.user_view(user) for user in users], "count": len(users), "total": total, "page": page}


@router.get("/users/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db), current_user=Depends(admin_read)):
    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not user:
        _not_found("Utilisateur")
    _require_user_scope(current_user, user)
    data = service.user_view(user)
    data["effective_permissions"] = service.effective_permissions(user)
    return data


@router.put("/users/{user_id}")
def update_user(
    user_id: int, data: UserUpdate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_update),
):
    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not user:
        _not_found("Utilisateur")
    _require_user_scope(current_user, user)
    for scope in data.scopes or []:
        _require_entity_scope(current_user, scope.organization_id, scope.agency_id)
    for assignment in data.roles or []:
        _require_entity_scope(current_user, assignment.organization_id, assignment.agency_id)
    before = service.user_view(user)
    for field, value in data.model_dump(exclude_unset=True, exclude={"roles", "scopes"}).items():
        setattr(user, field, value.lower() if field == "email" else value)
    try:
        service.assign_user_roles_and_scopes(db, user, data.roles, data.scopes, current_user.email)
        db.flush()
        if data.roles is not None:
            db.expire(user, ["role_assignments"])
        if data.scopes is not None:
            db.expire(user, ["scopes"])
    except IntegrityError:
        _integrity_error(db, "Cet email est déjà utilisé")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    service.log_audit(
        db, actor=current_user, action="update", module="administration", resource_type="user",
        resource_id=user.id, before=before, after=service.user_view(user), request=request,
    )
    db.commit()
    return service.user_view(user)


@router.post("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: int, data: DeactivateUser, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_update),
):
    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not user:
        _not_found("Utilisateur")
    _require_user_scope(current_user, user)
    if user.id == current_user.db_id:
        raise HTTPException(status_code=409, detail="Vous ne pouvez pas désactiver votre propre compte")
    user.is_active = False
    user.deactivated_at = service.utcnow()
    user.deactivated_reason = data.reason
    db.query(SecuritySession).filter(
        SecuritySession.user_id == user.id, SecuritySession.revoked_at.is_(None)
    ).update({"revoked_at": service.utcnow(), "revoke_reason": "user_deactivated"}, synchronize_session=False)
    service.log_audit(
        db, actor=current_user, action="deactivate", module="administration", resource_type="user",
        resource_id=user.id, description=data.reason, request=request,
    )
    db.commit()
    return {"deactivated": True, "user_id": user.id}


@router.post("/users/{user_id}/activate")
def activate_user(
    user_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(admin_update)
):
    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not user:
        _not_found("Utilisateur")
    _require_user_scope(current_user, user)
    user.is_active = True
    user.deactivated_at = None
    user.deactivated_reason = None
    service.log_audit(
        db, actor=current_user, action="activate", module="administration", resource_type="user",
        resource_id=user.id, request=request,
    )
    db.commit()
    return service.user_view(user)


@router.put("/users/{user_id}/password")
def change_password(
    user_id: int, data: PasswordChange, request: Request,
    db: Session = Depends(get_db), current_user=Depends(get_current_user),
):
    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not user:
        _not_found("Utilisateur")
    self_change = current_user.db_id == user_id
    if not self_change:
        _require_user_scope(current_user, user)
        actor = db.query(AdminUser).filter(AdminUser.id == current_user.db_id).first()
        if not actor or not service.has_permission(actor, "administration", "admin"):
            raise HTTPException(status_code=403, detail="Permission administration:admin requise")
    elif not data.current_password or not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    policy = service.get_user_policy(db, user)
    try:
        service.validate_password(data.new_password, policy, user, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.add(PasswordHistory(user_id=user.id, password_hash=user.password_hash))
    user.password_hash = service.pwd_context.hash(data.new_password)
    user.password_changed_at = service.utcnow()
    user.must_change_password = False
    db.query(SecuritySession).filter(
        SecuritySession.user_id == user.id, SecuritySession.id != current_user.session_id,
        SecuritySession.revoked_at.is_(None),
    ).update({"revoked_at": service.utcnow(), "revoke_reason": "password_changed"}, synchronize_session=False)
    service.log_audit(
        db, actor=current_user, action="password_change", module="administration", resource_type="user",
        resource_id=user.id, request=request,
    )
    db.commit()
    return {"changed": True}


@router.get("/users/{user_id}/login-history")
def user_login_history(
    user_id: int, limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db), current_user=Depends(admin_read),
):
    target = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if not target:
        _not_found("Utilisateur")
    _require_user_scope(current_user, target)
    rows = db.query(LoginHistory).filter(LoginHistory.user_id == user_id).order_by(
        LoginHistory.occurred_at.desc()
    ).limit(limit).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# Politique de sécurité, SSO et paramètres généraux
# ---------------------------------------------------------------------------
@router.get("/security-policy")
def get_security_policy(
    organization_id: Optional[int] = None, db: Session = Depends(get_db), current_user=Depends(admin_read)
):
    _require_entity_scope(current_user, organization_id)
    return service.model_dict(service.get_policy(db, organization_id))


@router.put("/security-policy")
def update_security_policy(
    data: SecurityPolicyUpdate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_manage),
):
    _require_entity_scope(current_user, data.organization_id)
    policy = service.get_policy(db, data.organization_id)
    before = service.model_dict(policy)
    for field, value in data.model_dump(exclude_unset=True, exclude={"organization_id"}).items():
        setattr(policy, field, value)
    service.log_audit(
        db, actor=current_user, action="update", module="administration", resource_type="security_policy",
        resource_id=policy.id, before=before, after=service.model_dict(policy), request=request,
        organization_id=policy.organization_id,
    )
    db.commit()
    return service.model_dict(policy)


@router.post("/sso-providers", status_code=201)
def create_sso_provider(
    data: SSOProviderCreate, request: Request, db: Session = Depends(get_db), current_user=Depends(admin_manage)
):
    _require_entity_scope(current_user, data.organization_id)
    values = data.model_dump(exclude={"client_secret"})
    provider = SSOProvider(**values, encrypted_client_secret=service.encrypt_secret(data.client_secret))
    db.add(provider)
    try:
        db.flush()
    except IntegrityError:
        _integrity_error(db, "Ce slug SSO existe déjà")
    service.log_audit(
        db, actor=current_user, action="create", module="administration", resource_type="sso_provider",
        resource_id=provider.id, after=service.sso_view(provider), request=request,
        organization_id=provider.organization_id,
    )
    db.commit()
    return service.sso_view(provider)


@router.get("/sso-providers")
def list_sso_providers(db: Session = Depends(get_db), current_user=Depends(admin_read)):
    query = db.query(SSOProvider)
    if not _admin_unrestricted(current_user):
        query = query.filter(SSOProvider.organization_id.in_(current_user.organization_ids))
    rows = query.order_by(SSOProvider.name).all()
    return {"data": [service.sso_view(row) for row in rows], "count": len(rows)}


@router.put("/sso-providers/{provider_id}")
def update_sso_provider(
    provider_id: int, data: SSOProviderCreate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_manage),
):
    provider = db.query(SSOProvider).filter(SSOProvider.id == provider_id).first()
    if not provider:
        _not_found("Fournisseur SSO")
    _require_entity_scope(current_user, provider.organization_id)
    _require_entity_scope(current_user, data.organization_id)
    before = service.sso_view(provider)
    for field, value in data.model_dump(exclude={"client_secret"}).items():
        setattr(provider, field, value)
    if data.client_secret:
        provider.encrypted_client_secret = service.encrypt_secret(data.client_secret)
    db.flush()
    service.log_audit(
        db, actor=current_user, action="update", module="administration", resource_type="sso_provider",
        resource_id=provider.id, before=before, after=service.sso_view(provider), request=request,
        organization_id=provider.organization_id,
    )
    db.commit()
    return service.sso_view(provider)


@router.post("/sso-providers/{provider_id}/sync-metadata")
async def sync_saml_metadata(
    provider_id: int, db: Session = Depends(get_db), current_user=Depends(admin_manage)
):
    provider = db.query(SSOProvider).filter(SSOProvider.id == provider_id).first()
    if not provider:
        _not_found("Fournisseur SSO")
    _require_entity_scope(current_user, provider.organization_id)
    if provider.protocol != "saml" or not provider.metadata_url:
        raise HTTPException(status_code=400, detail="URL de métadonnées SAML absente")
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(provider.metadata_url)
            response.raise_for_status()
        from lxml import etree
        root = etree.fromstring(
            response.content,
            parser=etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False),
        )
        provider.issuer = root.get("entityID")
        sso_nodes = root.xpath(".//*[local-name()='SingleSignOnService']")
        redirect = next((node for node in sso_nodes if "HTTP-Redirect" in (node.get("Binding") or "")), None)
        selected = redirect or (sso_nodes[0] if sso_nodes else None)
        certificate_nodes = root.xpath(".//*[local-name()='IDPSSODescriptor']//*[local-name()='X509Certificate']")
        if selected is None or not certificate_nodes or not certificate_nodes[0].text:
            raise ValueError("Métadonnées IdP incomplètes")
        provider.authorization_url = selected.get("Location")
        compact = "".join(certificate_nodes[0].text.split())
        provider.certificate = "-----BEGIN CERTIFICATE-----\n" + "\n".join(textwrap.wrap(compact, 64)) + "\n-----END CERTIFICATE-----\n"
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"Synchronisation SAML impossible : {str(exc)[:200]}")
    return service.sso_view(provider)


@router.delete("/sso-providers/{provider_id}")
def delete_sso_provider(
    provider_id: int, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_manage),
):
    provider = db.query(SSOProvider).filter(SSOProvider.id == provider_id).first()
    if not provider:
        _not_found("Fournisseur SSO")
    _require_entity_scope(current_user, provider.organization_id)
    before = service.sso_view(provider)
    db.delete(provider)
    service.log_audit(
        db, actor=current_user, action="delete", module="administration", resource_type="sso_provider",
        resource_id=provider_id, before=before, request=request, organization_id=provider.organization_id,
    )
    db.commit()
    return {"deleted": True, "id": provider_id}


@router.get("/settings/general")
def get_general_settings(
    organization_id: Optional[int] = None, db: Session = Depends(get_db), current_user=Depends(admin_read)
):
    _require_entity_scope(current_user, organization_id)
    row = db.query(GeneralSettings).filter(GeneralSettings.organization_id == organization_id).first()
    if not row:
        row = GeneralSettings(organization_id=organization_id)
        db.add(row)
        db.commit()
    return service.model_dict(row)


@router.put("/settings/general")
def update_general_settings(
    data: GeneralSettingsUpdate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_update),
):
    _require_entity_scope(current_user, data.organization_id)
    row = db.query(GeneralSettings).filter(GeneralSettings.organization_id == data.organization_id).first()
    if not row:
        row = GeneralSettings(organization_id=data.organization_id)
        db.add(row)
        db.flush()
    before = service.model_dict(row)
    for field, value in data.model_dump(exclude_unset=True, exclude={"organization_id"}).items():
        setattr(row, field, value.upper() if field == "currency" else value)
    service.log_audit(
        db, actor=current_user, action="update", module="administration", resource_type="general_settings",
        resource_id=row.id, before=before, after=service.model_dict(row), request=request,
        organization_id=row.organization_id,
    )
    db.commit()
    return service.model_dict(row)


@router.put("/settings/numbering")
def configure_numbering(
    data: NumberingSequenceConfig, db: Session = Depends(get_db), current_user=Depends(admin_update)
):
    _require_entity_scope(current_user, data.organization_id)
    row = db.query(NumberingSequence).filter(
        NumberingSequence.organization_id == data.organization_id,
        NumberingSequence.document_type == data.document_type,
        NumberingSequence.period == data.period,
    ).first()
    if not row:
        row = NumberingSequence(**data.model_dump())
        db.add(row)
    else:
        for field, value in data.model_dump(exclude={"organization_id", "document_type", "period"}).items():
            setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return service.model_dict(row)


@router.post("/settings/numbering/next")
def next_number(
    document_type: str, organization_id: Optional[int] = None, period: str = "global",
    db: Session = Depends(get_db), current_user=Depends(admin_update),
):
    _require_entity_scope(current_user, organization_id)
    row = db.query(NumberingSequence).filter(
        NumberingSequence.organization_id == organization_id,
        NumberingSequence.document_type == document_type,
        NumberingSequence.period == period,
    ).with_for_update().first()
    if not row:
        raise HTTPException(status_code=404, detail="Séquence de numérotation non configurée")
    value = row.next_value
    row.next_value += 1
    now = service.utcnow()
    prefix = (row.prefix or "").replace("{YYYY}", str(now.year)).replace("{MM}", f"{now.month:02d}")
    number = f"{prefix}{value:0{row.padding}d}"
    db.commit()
    return {
        "number": number, "value": value, "next_value": row.next_value,
        "document_type": document_type, "period": period,
    }


@router.get("/settings/numbering")
def list_numbering(
    organization_id: Optional[int] = None, db: Session = Depends(get_db), current_user=Depends(admin_read)
):
    query = db.query(NumberingSequence)
    if not _admin_unrestricted(current_user):
        query = query.filter(NumberingSequence.organization_id.in_(current_user.organization_ids))
    if organization_id is not None:
        _require_entity_scope(current_user, organization_id)
        query = query.filter(NumberingSequence.organization_id == organization_id)
    rows = query.order_by(NumberingSequence.document_type, NumberingSequence.period).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows)}


@router.post("/settings/reference-indices", status_code=201)
def create_reference_index(
    data: ReferenceIndexCreate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_update),
):
    _require_entity_scope(current_user, data.organization_id)
    row = ReferenceIndex(**data.model_dump(mode="json"))
    row.code = row.code.upper()
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        _integrity_error(db, "Une valeur existe déjà pour cet indice et cette période")
    service.log_audit(
        db, actor=current_user, action="create", module="administration", resource_type="reference_index",
        resource_id=row.id, after=service.model_dict(row), request=request,
        organization_id=row.organization_id,
    )
    db.commit()
    return service.model_dict(row)


@router.get("/settings/reference-indices")
def list_reference_indices(
    code: Optional[str] = None, organization_id: Optional[int] = None,
    db: Session = Depends(get_db), current_user=Depends(admin_read),
):
    query = db.query(ReferenceIndex)
    if not _admin_unrestricted(current_user):
        query = query.filter(ReferenceIndex.organization_id.in_(current_user.organization_ids))
    if code:
        query = query.filter(ReferenceIndex.code == code.upper())
    if organization_id is not None:
        _require_entity_scope(current_user, organization_id)
        query = query.filter(ReferenceIndex.organization_id == organization_id)
    rows = query.order_by(ReferenceIndex.code, ReferenceIndex.period.desc()).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows)}


@router.get("/settings/smtp")
def get_smtp_settings(
    organization_id: Optional[int] = None, db: Session = Depends(get_db), current_user=Depends(admin_read)
):
    _require_entity_scope(current_user, organization_id)
    row = db.query(SMTPSettings).filter(SMTPSettings.organization_id == organization_id).first()
    if not row:
        row = SMTPSettings(organization_id=organization_id)
        db.add(row)
        db.commit()
    return service.smtp_view(row)


@router.put("/settings/smtp")
def update_smtp_settings(
    data: SMTPSettingsUpdate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_manage),
):
    _require_entity_scope(current_user, data.organization_id)
    row = db.query(SMTPSettings).filter(SMTPSettings.organization_id == data.organization_id).first()
    if not row:
        row = SMTPSettings(organization_id=data.organization_id)
        db.add(row)
        db.flush()
    before = service.smtp_view(row)
    for field, value in data.model_dump(exclude_unset=True, exclude={"organization_id", "password"}).items():
        setattr(row, field, value)
    if data.password is not None:
        row.encrypted_password = service.encrypt_secret(data.password)
    service.log_audit(
        db, actor=current_user, action="update", module="administration", resource_type="smtp_settings",
        resource_id=row.id, before=before, after=service.smtp_view(row), request=request,
        organization_id=row.organization_id,
    )
    db.commit()
    return service.smtp_view(row)


@router.post("/settings/smtp/test")
def test_smtp(
    organization_id: Optional[int] = None, db: Session = Depends(get_db), current_user=Depends(admin_manage)
):
    _require_entity_scope(current_user, organization_id)
    row = db.query(SMTPSettings).filter(SMTPSettings.organization_id == organization_id).first()
    if not row or not row.host:
        raise HTTPException(status_code=400, detail="Configuration SMTP incomplète")
    try:
        client_class = smtplib.SMTP_SSL if row.use_ssl else smtplib.SMTP
        with client_class(row.host, row.port, timeout=5) as client:
            if row.use_tls:
                client.starttls()
            password = service.decrypt_secret(row.encrypted_password)
            if row.username and password:
                client.login(row.username, password)
            status = client.noop()[0]
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Connexion SMTP impossible : {str(exc)[:200]}")
    return {"connected": status == 250, "status": status}


# ---------------------------------------------------------------------------
# Audit et historique des modifications
# ---------------------------------------------------------------------------
@router.get("/audit-logs")
def list_audit_logs(
    actor: Optional[str] = None, module: Optional[str] = None, action: Optional[str] = None,
    resource_type: Optional[str] = None, resource_id: Optional[str] = None,
    organization_id: Optional[int] = None, agency_id: Optional[int] = None,
    page: int = Query(1, ge=1), limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db), current_user=Depends(admin_read),
):
    query = db.query(AuditLog)
    if not _admin_unrestricted(current_user):
        query = query.filter(AuditLog.organization_id.in_(current_user.organization_ids))
    for column, value in [
        (AuditLog.actor_email, actor), (AuditLog.module, module), (AuditLog.action, action),
        (AuditLog.resource_type, resource_type), (AuditLog.resource_id, resource_id),
        (AuditLog.organization_id, organization_id), (AuditLog.agency_id, agency_id),
    ]:
        if value is not None:
            query = query.filter(column == value)
    total = query.count()
    rows = query.order_by(AuditLog.occurred_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows), "total": total, "page": page}


@router.get("/audit-logs/export")
def export_audit_logs(
    module: Optional[str] = None, organization_id: Optional[int] = None,
    db: Session = Depends(get_db), current_user=Depends(admin_export),
):
    query = db.query(AuditLog)
    if not _admin_unrestricted(current_user):
        query = query.filter(AuditLog.organization_id.in_(current_user.organization_ids))
    if module:
        query = query.filter(AuditLog.module == module)
    if organization_id is not None:
        query = query.filter(AuditLog.organization_id == organization_id)
    logs = query.order_by(AuditLog.occurred_at.desc()).all()
    return Response(
        service.audit_csv(logs), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=audit-logs.csv"},
    )


@router.get("/resources/{resource_type}/{resource_id}/history")
def resource_history(
    resource_type: str, resource_id: str,
    db: Session = Depends(get_db), current_user=Depends(admin_read),
):
    query = db.query(AuditLog).filter(
        AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id
    )
    if not _admin_unrestricted(current_user):
        query = query.filter(AuditLog.organization_id.in_(current_user.organization_ids))
    rows = query.order_by(AuditLog.occurred_at.desc()).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# Sauvegarde et restauration
# ---------------------------------------------------------------------------
@router.get("/backups/policy")
def get_backup_policy(db: Session = Depends(get_db), current_user=Depends(admin_read)):
    _require_global_admin(current_user)
    policy = db.query(BackupPolicy).first()
    if not policy:
        policy = BackupPolicy()
        db.add(policy)
        db.commit()
    return service.model_dict(policy)


@router.put("/backups/policy")
def update_backup_policy(
    data: BackupPolicyUpdate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_manage),
):
    _require_global_admin(current_user)
    policy = db.query(BackupPolicy).first() or BackupPolicy()
    if policy.id is None:
        db.add(policy)
        db.flush()
    before = service.model_dict(policy)
    _update_model(policy, data)
    service.log_audit(
        db, actor=current_user, action="update", module="administration", resource_type="backup_policy",
        resource_id=policy.id, before=before, after=service.model_dict(policy), request=request,
    )
    db.commit()
    return service.model_dict(policy)


@router.post("/backups", status_code=201)
def create_manual_backup(
    request: Request, db: Session = Depends(get_db), current_user=Depends(admin_manage)
):
    _require_global_admin(current_user)
    record = service.create_backup(db, current_user.email, "manual")
    service.log_audit(
        db, actor=current_user, action="backup", module="administration", resource_type="backup",
        resource_id=record.id, after=service.model_dict(record), request=request,
    )
    db.commit()
    if record.status == "failed":
        raise HTTPException(status_code=500, detail=record.error_message)
    return service.model_dict(record, exclude={"storage_path"})


@router.post("/backups/run-daily")
def run_daily_backup(db: Session = Depends(get_db), current_user=Depends(admin_manage)):
    _require_global_admin(current_user)
    return service.run_daily_backup_if_due(db, current_user.email)


@router.post("/backups/retention")
def apply_retention(db: Session = Depends(get_db), current_user=Depends(admin_manage)):
    _require_global_admin(current_user)
    return service.apply_backup_retention(db)


@router.get("/backups")
def list_backups(db: Session = Depends(get_db), current_user=Depends(admin_read)):
    _require_global_admin(current_user)
    rows = db.query(BackupRecord).order_by(BackupRecord.created_at.desc()).all()
    return {"data": [service.model_dict(row, exclude={"storage_path"}) for row in rows], "count": len(rows)}


@router.post("/backups/{backup_id}/restore")
def restore_backup(
    backup_id: int, data: RestoreRequest, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_manage),
):
    _require_global_admin(current_user)
    if data.confirmation != f"RESTORE-{backup_id}":
        raise HTTPException(status_code=400, detail=f"Confirmation RESTORE-{backup_id} requise")
    record = db.query(BackupRecord).filter(BackupRecord.id == backup_id).first()
    if not record:
        _not_found("Sauvegarde")
    # Point de retour obligatoire juste avant toute restauration.
    safety = service.create_backup(db, current_user.email, "manual")
    if safety.status != "completed":
        raise HTTPException(status_code=500, detail="La sauvegarde de sécurité préalable a échoué")
    service.log_audit(
        db, actor=current_user, action="restore", module="administration", resource_type="backup",
        resource_id=backup_id, description=f"Point de retour : {safety.id}", request=request,
    )
    db.commit()
    try:
        service.restore_backup(db, record)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"restored": True, "backup_id": backup_id, "safety_backup_id": safety.id, "restart_recommended": True}


# ---------------------------------------------------------------------------
# RGPD : consentements, portabilité, oubli, registre et politique
# ---------------------------------------------------------------------------
@router.post("/gdpr/consents", status_code=201)
def record_consent(
    data: ConsentCreate, request: Request, db: Session = Depends(get_db), current_user=Depends(admin_create)
):
    _require_global_admin(current_user)
    if not data.granted:
        latest = db.query(ConsentRecord).filter(
            ConsentRecord.subject_type == data.subject_type,
            ConsentRecord.subject_id == data.subject_id,
            ConsentRecord.purpose == data.purpose,
            ConsentRecord.granted == True,
            ConsentRecord.withdrawn_at.is_(None),
        ).order_by(ConsentRecord.recorded_at.desc()).first()
        if latest:
            latest.withdrawn_at = service.utcnow()
    row = ConsentRecord(
        **data.model_dump(), ip_address=request.client.host if request.client else None
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return service.model_dict(row)


@router.get("/gdpr/consents")
def list_consents(
    subject_type: Optional[str] = None, subject_id: Optional[str] = None,
    db: Session = Depends(get_db), current_user=Depends(admin_read),
):
    _require_global_admin(current_user)
    query = db.query(ConsentRecord)
    if subject_type:
        query = query.filter(ConsentRecord.subject_type == subject_type)
    if subject_id:
        query = query.filter(ConsentRecord.subject_id == subject_id)
    rows = query.order_by(ConsentRecord.recorded_at.desc()).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows)}


@router.get("/gdpr/portability/{subject_type}/{subject_id}")
def export_subject_data(
    subject_type: str, subject_id: str, db: Session = Depends(get_db), current_user=Depends(admin_export)
):
    _require_global_admin(current_user)
    content = json.dumps(service.subject_data(db, subject_type, subject_id), ensure_ascii=False, indent=2, default=str).encode()
    return Response(
        content, media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=portabilite-{subject_type}-{subject_id}.json"},
    )


@router.post("/gdpr/requests", status_code=201)
def create_gdpr_request(
    data: DataSubjectRequestCreate, db: Session = Depends(get_db), current_user=Depends(admin_create)
):
    _require_global_admin(current_user)
    row = DataSubjectRequest(
        reference=f"RGPD-{service.utcnow().strftime('%Y%m%d')}-{service.secrets.token_hex(4).upper()}",
        due_at=service.utcnow() + timedelta(days=30), **data.model_dump(mode="json"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return service.model_dict(row)


@router.get("/gdpr/requests")
def list_gdpr_requests(
    status: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(admin_read)
):
    _require_global_admin(current_user)
    query = db.query(DataSubjectRequest)
    if status:
        query = query.filter(DataSubjectRequest.status == status)
    rows = query.order_by(DataSubjectRequest.requested_at.desc()).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows)}


@router.post("/gdpr/requests/{request_id}/process")
def process_gdpr_request(
    request_id: int, data: DataSubjectProcess, request: Request,
    db: Session = Depends(get_db), current_user=Depends(admin_manage),
):
    _require_global_admin(current_user)
    row = db.query(DataSubjectRequest).filter(DataSubjectRequest.id == request_id).first()
    if not row:
        _not_found("Demande RGPD")
    if data.action == "reject":
        if not data.rejection_reason:
            raise HTTPException(status_code=400, detail="Un motif de refus est requis")
        row.status = "rejected"
        row.rejection_reason = data.rejection_reason
        row.processed_at = service.utcnow()
    elif data.action == "approve":
        row.status = "approved"
    elif row.request_type == "erasure":
        # Le gel juridique ou une rétention GED active prime sur le droit à l'oubli.
        from app.models.ged import GedDocument
        column = GedDocument.tenant_id if row.subject_type == "tenant" else GedDocument.owner_id if row.subject_type == "owner" else None
        blocked = False
        if column is not None:
            try:
                subject_id = int(row.subject_id)
                blocked = db.query(GedDocument).filter(
                    column == subject_id, GedDocument.is_deleted == False,
                    or_(GedDocument.legal_hold == True, GedDocument.retain_until >= service.utcnow().date()),
                ).count() > 0
            except ValueError:
                blocked = False
        if blocked:
            raise HTTPException(status_code=409, detail="Effacement bloqué par une obligation de conservation ou un gel juridique")
        result = service.anonymize_subject(db, row.subject_type, row.subject_id)
        row.status = "completed" if result["anonymized"] else "not_found"
        row.processed_at = service.utcnow()
    elif row.request_type in {"portability", "access"}:
        export_dir = Path(service.settings.private_upload_dir_path) / "gdpr_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"{row.reference}.json"
        path.write_text(json.dumps(service.subject_data(db, row.subject_type, row.subject_id), ensure_ascii=False, indent=2, default=str))
        row.result_path = str(path)
        row.status = "completed"
        row.processed_at = service.utcnow()
    else:
        row.status = "completed"
        row.processed_at = service.utcnow()
    row.processed_by = current_user.email
    service.log_audit(
        db, actor=current_user, action=f"gdpr_{data.action}", module="administration",
        resource_type="gdpr_request", resource_id=row.id, after=service.model_dict(row), request=request,
    )
    db.commit()
    return service.model_dict(row, exclude={"result_path"})


@router.post("/gdpr/processing-register", status_code=201)
def create_processing_record(
    data: ProcessingRecordCreate, db: Session = Depends(get_db), current_user=Depends(admin_create)
):
    _require_entity_scope(current_user, data.organization_id)
    row = DataProcessingRecord(**data.model_dump(mode="json"))
    db.add(row)
    db.commit()
    db.refresh(row)
    return service.model_dict(row)


@router.get("/gdpr/processing-register")
def list_processing_records(db: Session = Depends(get_db), current_user=Depends(admin_read)):
    query = db.query(DataProcessingRecord)
    if not _admin_unrestricted(current_user):
        query = query.filter(DataProcessingRecord.organization_id.in_(current_user.organization_ids))
    rows = query.order_by(DataProcessingRecord.name).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows)}


@router.put("/gdpr/processing-register/{record_id}")
def update_processing_record(
    record_id: int, data: ProcessingRecordCreate,
    db: Session = Depends(get_db), current_user=Depends(admin_update),
):
    row = db.query(DataProcessingRecord).filter(DataProcessingRecord.id == record_id).first()
    if not row:
        _not_found("Traitement")
    _require_entity_scope(current_user, row.organization_id)
    _require_entity_scope(current_user, data.organization_id)
    _update_model(row, data)
    db.commit()
    return service.model_dict(row)


@router.post("/gdpr/privacy-policies", status_code=201)
def create_privacy_policy(
    data: PrivacyPolicyCreate, db: Session = Depends(get_db), current_user=Depends(admin_create)
):
    _require_entity_scope(current_user, data.organization_id)
    if data.publish:
        db.query(PrivacyPolicy).filter(
            PrivacyPolicy.organization_id == data.organization_id, PrivacyPolicy.is_published == True
        ).update({"is_published": False}, synchronize_session=False)
    row = PrivacyPolicy(
        organization_id=data.organization_id, version=data.version, title=data.title,
        content=data.content, is_published=data.publish,
        published_at=service.utcnow() if data.publish else None, created_by=current_user.email,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return service.model_dict(row)


@router.get("/gdpr/privacy-policies")
def list_privacy_policies(db: Session = Depends(get_db), current_user=Depends(admin_read)):
    query = db.query(PrivacyPolicy)
    if not _admin_unrestricted(current_user):
        query = query.filter(PrivacyPolicy.organization_id.in_(current_user.organization_ids))
    rows = query.order_by(PrivacyPolicy.created_at.desc()).all()
    return {"data": [service.model_dict(row) for row in rows], "count": len(rows)}


@public_router.get("/current")
def current_privacy_policy(organization_id: Optional[int] = None, db: Session = Depends(get_db)):
    row = db.query(PrivacyPolicy).filter(
        PrivacyPolicy.organization_id == organization_id, PrivacyPolicy.is_published == True
    ).order_by(PrivacyPolicy.published_at.desc()).first()
    if not row:
        _not_found("Politique de confidentialité")
    return service.model_dict(row)
