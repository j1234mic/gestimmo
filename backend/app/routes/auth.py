"""Authentification email/mot de passe, 2FA, sessions, SSO et biométrie."""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    principal_from_admin,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.models.admin_security import (
    AdminUser,
    AuthChallenge,
    SecuritySession,
    SSOProvider,
    TrustedDevice,
    UserRoleAssignment,
    UserScope,
)
from app.schemas.admin_security import (
    BiometricChallengeRequest,
    BiometricVerifyRequest,
    DeviceRegister,
    RefreshRequest,
    TwoFactorConfirm,
    TwoFactorLoginVerify,
    TwoFactorSetup,
)
from app.services import admin_security_service as security_service

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def _client(request: Request) -> tuple[str | None, str | None]:
    return (
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
    )


def _issue_tokens(db: Session, user: AdminUser, request: Request) -> dict:
    policy = security_service.get_user_policy(db, user)
    ip, user_agent = _client(request)
    session = SecuritySession(
        user_id=user.id,
        ip_address=ip,
        user_agent=user_agent,
        expires_at=security_service.utcnow() + timedelta(days=policy.refresh_token_days),
    )
    db.add(session)
    db.flush()
    claims = {"sub": user.email, "uid": user.id, "sid": session.id, "actor": "user"}
    access_token = create_access_token(
        claims, expires_delta=timedelta(minutes=policy.session_timeout_minutes)
    )
    refresh_token = create_refresh_token(
        claims, expires_delta=timedelta(days=policy.refresh_token_days)
    )
    session.refresh_token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    session.last_seen_at = security_service.utcnow()
    db.commit()
    db.refresh(user)
    principal = principal_from_admin(user, session.id)
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": policy.session_timeout_minutes * 60,
        "user": {
            "id": user.public_id,
            "database_id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": principal.role,
            "permissions": principal.permissions,
            "granular_permissions": principal.granular_permissions,
            "organization_ids": principal.organization_ids,
            "organization_wide_ids": principal.organization_wide_ids,
            "agency_ids": principal.agency_ids,
            "data_scopes": principal.data_scopes,
            "must_change_password": user.must_change_password,
        },
    }


def _resolve_sso_user(db: Session, provider: SSOProvider, profile: dict) -> AdminUser | None:
    email = profile.get("email")
    if not email:
        return None
    user = db.query(AdminUser).filter(AdminUser.email == email.lower()).first()
    if not user and provider.auto_provision and provider.default_role_id:
        user = AdminUser(
            email=email.lower(), full_name=profile.get("name") or email.split("@", 1)[0],
            password_hash=security_service.pwd_context.hash(secrets.token_urlsafe(48)),
        )
        db.add(user)
        db.flush()
        db.add(UserRoleAssignment(
            user_id=user.id, role_id=provider.default_role_id,
            organization_id=provider.organization_id, assigned_by=f"sso:{provider.slug}",
        ))
        if provider.organization_id:
            db.add(UserScope(user_id=user.id, organization_id=provider.organization_id, is_default=True))
        db.flush()
    return user if user and user.is_active else None


def _challenge_response(challenge, code: str | None, method: str) -> dict:
    response = {
        "two_factor_required": True,
        "challenge_token": challenge.id,
        "method": method,
        "expires_in": 300,
        "delivery": challenge.challenge,
    }
    # Un code transmis par SMS/email n'est jamais renvoyé en production. En
    # développement, il rend le flux testable sans prétendre qu'un SMS a été envoyé.
    if settings.ENVIRONMENT != "production" and code:
        response["debug_code"] = code
    return response


@router.post("/login")
def login(request: Request, login_data: LoginRequest, db: Session = Depends(get_db)):
    email = login_data.email.lower()
    user = db.query(AdminUser).filter(AdminUser.email == email).first()
    if not user:
        security_service.record_login(db, email, False, request, reason="unknown_user")
        db.commit()
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    now = security_service.utcnow()
    if user.locked_until and user.locked_until.replace(tzinfo=None) > now:
        security_service.record_login(db, email, False, request, user.id, "locked")
        db.commit()
        raise HTTPException(
            status_code=423,
            detail={"message": "Compte temporairement bloqué", "locked_until": user.locked_until.isoformat()},
        )
    if not user.is_active:
        security_service.record_login(db, email, False, request, user.id, "disabled")
        db.commit()
        raise HTTPException(status_code=403, detail="Compte désactivé")
    if not verify_password(login_data.password, user.password_hash):
        policy = security_service.get_user_policy(db, user)
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= policy.max_login_attempts:
            user.locked_until = now + timedelta(minutes=policy.lockout_minutes)
            user.failed_login_attempts = 0
        security_service.record_login(db, email, False, request, user.id, "bad_password")
        db.commit()
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    user.failed_login_attempts = 0
    user.locked_until = None
    policy = security_service.get_user_policy(db, user)
    if policy.password_expiry_days and user.password_changed_at:
        changed_at = user.password_changed_at.replace(tzinfo=None)
        if changed_at + timedelta(days=policy.password_expiry_days) <= now:
            user.must_change_password = True
    if policy.require_2fa and not user.two_factor_enabled:
        security_service.record_login(db, email, False, request, user.id, "2fa_setup_required")
        db.commit()
        raise HTTPException(status_code=403, detail="La politique impose l'activation préalable du 2FA")
    if user.two_factor_enabled:
        challenge, code = security_service.create_otp_challenge(
            db, user, "login_2fa", user.two_factor_method or "authenticator"
        )
        try:
            challenge.challenge = security_service.deliver_otp_code(db, user, challenge.method, code)
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail=str(exc))
        db.commit()
        return _challenge_response(challenge, code, challenge.method)

    user.last_login_at = now
    security_service.record_login(db, email, True, request, user.id)
    db.flush()
    return _issue_tokens(db, user, request)


@router.post("/2fa/verify")
def verify_login_2fa(data: TwoFactorLoginVerify, request: Request, db: Session = Depends(get_db)):
    try:
        challenge = security_service.verify_challenge(db, data.challenge_token, data.code, "login_2fa")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    user = db.query(AdminUser).filter(AdminUser.id == challenge.user_id, AdminUser.is_active == True).first()
    if not user:
        raise HTTPException(status_code=403, detail="Compte désactivé")
    user.last_login_at = security_service.utcnow()
    security_service.record_login(db, user.email, True, request, user.id, method=f"password+{challenge.method}")
    db.flush()
    return _issue_tokens(db, user, request)


@router.post("/refresh")
def refresh(data: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    try:
        payload = decode_token(data.refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Jeton de renouvellement invalide")
    if payload.get("type") != "refresh" or not payload.get("sid") or not payload.get("uid"):
        raise HTTPException(status_code=401, detail="Jeton de renouvellement invalide")
    session = db.query(SecuritySession).filter(
        SecuritySession.id == payload["sid"], SecuritySession.user_id == int(payload["uid"])
    ).first()
    token_hash = hashlib.sha256(data.refresh_token.encode()).hexdigest()
    now = security_service.utcnow()
    if (
        not session or session.revoked_at or session.expires_at.replace(tzinfo=None) <= now
        or not secrets.compare_digest(session.refresh_token_hash or "", token_hash)
    ):
        raise HTTPException(status_code=401, detail="Session expirée ou révoquée")
    user = db.query(AdminUser).filter(AdminUser.id == session.user_id, AdminUser.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur désactivé")
    policy = security_service.get_user_policy(db, user)
    last_seen = session.last_seen_at.replace(tzinfo=None) if session.last_seen_at else session.created_at.replace(tzinfo=None)
    if last_seen + timedelta(minutes=policy.session_timeout_minutes) <= now:
        session.revoked_at = now
        session.revoke_reason = "idle_timeout"
        db.commit()
        raise HTTPException(status_code=401, detail="Session expirée pour inactivité")
    # Rotation : l'ancien refresh token est immédiatement invalidé.
    session.revoked_at = now
    session.revoke_reason = "refresh_rotation"
    db.flush()
    return _issue_tokens(db, user, request)


@router.post("/logout")
def logout(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    if current_user.session_id:
        session = db.query(SecuritySession).filter(SecuritySession.id == current_user.session_id).first()
        if session and not session.revoked_at:
            session.revoked_at = security_service.utcnow()
            session.revoke_reason = "logout"
            db.commit()
    return {"logged_out": True}


@router.get("/sessions")
def sessions(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    rows = db.query(SecuritySession).filter(SecuritySession.user_id == current_user.db_id).order_by(
        SecuritySession.created_at.desc()
    ).all()
    return {"data": [security_service.model_dict(row, exclude={"refresh_token_hash"}) for row in rows]}


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: str, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    session = db.query(SecuritySession).filter(
        SecuritySession.id == session_id, SecuritySession.user_id == current_user.db_id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session introuvable")
    session.revoked_at = security_service.utcnow()
    session.revoke_reason = "user_revoked"
    db.commit()
    return {"revoked": True, "session_id": session_id}


@router.post("/2fa/setup")
def setup_2fa(data: TwoFactorSetup, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user = db.query(AdminUser).filter(AdminUser.id == current_user.db_id).first()
    policy = security_service.get_user_policy(db, user)
    if data.method not in (policy.allowed_2fa_methods or []):
        raise HTTPException(status_code=400, detail="Méthode 2FA interdite par la politique")
    if data.method == "sms" and not user.phone:
        raise HTTPException(status_code=400, detail="Un numéro de téléphone est requis")
    if data.method == "authenticator":
        user.two_factor_secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    user.two_factor_method = data.method
    user.two_factor_enabled = False
    challenge, code = security_service.create_otp_challenge(db, user, "setup_2fa", data.method)
    try:
        challenge.challenge = security_service.deliver_otp_code(db, user, data.method, code)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc))
    db.commit()
    result = {
        "challenge_token": challenge.id, "method": data.method, "expires_in": 300,
        "delivery": challenge.challenge,
    }
    if data.method == "authenticator":
        result.update({
            "secret": user.two_factor_secret,
            "provisioning_uri": f"otpauth://totp/GestImmo:{user.email}?secret={user.two_factor_secret}&issuer=GestImmo",
        })
    elif settings.ENVIRONMENT != "production":
        result["debug_code"] = code
    return result


@router.post("/2fa/confirm")
def confirm_2fa(data: TwoFactorConfirm, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    try:
        challenge = security_service.verify_challenge(db, data.challenge_token, data.code, "setup_2fa")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if challenge.user_id != current_user.db_id:
        raise HTTPException(status_code=403, detail="Challenge d'un autre utilisateur")
    user = db.query(AdminUser).filter(AdminUser.id == current_user.db_id).first()
    user.two_factor_enabled = True
    db.commit()
    return {"enabled": True, "method": user.two_factor_method}


@router.delete("/2fa")
def disable_2fa(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user = db.query(AdminUser).filter(AdminUser.id == current_user.db_id).first()
    policy = security_service.get_user_policy(db, user)
    if policy.require_2fa:
        raise HTTPException(status_code=409, detail="La politique de sécurité impose le 2FA")
    user.two_factor_enabled = False
    user.two_factor_method = None
    user.two_factor_secret = None
    db.commit()
    return {"enabled": False}


@router.post("/biometric/enrollment-challenge")
def biometric_enrollment_challenge(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    challenge = AuthChallenge(
        user_id=current_user.db_id, purpose="biometric_enrollment", method="public_key",
        challenge=secrets.token_urlsafe(48), expires_at=security_service.utcnow() + timedelta(minutes=5),
    )
    db.add(challenge)
    db.commit()
    return {"challenge_token": challenge.id, "challenge": challenge.challenge, "expires_in": 300}


@router.post("/biometric/devices", status_code=201)
def register_biometric_device(data: DeviceRegister, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    challenge = db.query(AuthChallenge).filter(AuthChallenge.id == data.challenge_token).first()
    if (
        not challenge or challenge.user_id != current_user.db_id or challenge.purpose != "biometric_enrollment"
        or challenge.consumed_at or challenge.expires_at.replace(tzinfo=None) < security_service.utcnow()
    ):
        raise HTTPException(status_code=400, detail="Challenge d'enrôlement invalide")
    try:
        public_key = serialization.load_pem_public_key(data.public_key_pem.encode())
        if not isinstance(public_key, (rsa.RSAPublicKey, ec.EllipticCurvePublicKey)):
            raise ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="Clé publique RSA/ECDSA invalide")
    if db.query(TrustedDevice).filter(
        TrustedDevice.user_id == current_user.db_id,
        TrustedDevice.device_identifier == data.device_identifier,
    ).first():
        raise HTTPException(status_code=409, detail="Appareil déjà enregistré")
    device = TrustedDevice(
        user_id=current_user.db_id, device_identifier=data.device_identifier,
        name=data.name, platform=data.platform, public_key_pem=data.public_key_pem,
    )
    challenge.consumed_at = security_service.utcnow()
    db.add(device)
    db.commit()
    db.refresh(device)
    return security_service.model_dict(device, exclude={"public_key_pem"})


@router.post("/biometric/challenge")
def biometric_challenge(data: BiometricChallengeRequest, db: Session = Depends(get_db)):
    user = db.query(AdminUser).filter(AdminUser.email == data.email.lower(), AdminUser.is_active == True).first()
    device = db.query(TrustedDevice).filter(
        TrustedDevice.user_id == (user.id if user else -1),
        TrustedDevice.device_identifier == data.device_identifier,
        TrustedDevice.is_active == True,
    ).first()
    # Réponse de forme identique pour ne pas permettre l'énumération des comptes.
    if not user or not device:
        return {
            "challenge_token": secrets.token_urlsafe(32),
            "challenge": secrets.token_urlsafe(48),
            "expires_in": 120,
        }
    challenge = AuthChallenge(
        user_id=user.id, purpose="biometric_login", method=str(device.id),
        challenge=secrets.token_urlsafe(48), expires_at=security_service.utcnow() + timedelta(minutes=2),
    )
    db.add(challenge)
    db.commit()
    return {"challenge_token": challenge.id, "challenge": challenge.challenge, "expires_in": 120}


@router.post("/biometric/verify")
def biometric_verify(data: BiometricVerifyRequest, request: Request, db: Session = Depends(get_db)):
    challenge = db.query(AuthChallenge).filter(AuthChallenge.id == data.challenge_token).first()
    if (
        not challenge or challenge.purpose != "biometric_login" or challenge.consumed_at
        or challenge.expires_at.replace(tzinfo=None) < security_service.utcnow()
    ):
        raise HTTPException(status_code=400, detail="Challenge biométrique invalide")
    device = db.query(TrustedDevice).filter(
        TrustedDevice.id == int(challenge.method), TrustedDevice.user_id == challenge.user_id,
        TrustedDevice.is_active == True,
    ).first()
    user = db.query(AdminUser).filter(AdminUser.id == challenge.user_id, AdminUser.is_active == True).first()
    if not device or not user:
        raise HTTPException(status_code=403, detail="Appareil ou utilisateur désactivé")
    try:
        public_key = serialization.load_pem_public_key(device.public_key_pem.encode())
        signature = base64.b64decode(data.signature_base64, validate=True)
        message = challenge.challenge.encode()
        if isinstance(public_key, rsa.RSAPublicKey):
            public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
        else:
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
    except (ValueError, InvalidSignature):
        challenge.attempts += 1
        db.commit()
        raise HTTPException(status_code=401, detail="Signature biométrique invalide")
    challenge.consumed_at = security_service.utcnow()
    device.last_used_at = security_service.utcnow()
    user.last_login_at = security_service.utcnow()
    security_service.record_login(db, user.email, True, request, user.id, method="biometric")
    db.flush()
    return _issue_tokens(db, user, request)


@router.get("/sso/providers")
def public_sso_providers(db: Session = Depends(get_db)):
    providers = db.query(SSOProvider).filter(SSOProvider.is_enabled == True).all()
    return {"data": [{"name": p.name, "slug": p.slug, "protocol": p.protocol} for p in providers]}


@router.get("/sso/{slug}/login")
def sso_login(slug: str, request: Request, db: Session = Depends(get_db)):
    provider = db.query(SSOProvider).filter(SSOProvider.slug == slug, SSOProvider.is_enabled == True).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Fournisseur SSO introuvable")
    callback = str(request.url_for("sso_callback", slug=slug))
    if provider.protocol == "saml":
        # La validation XML-signature dépend d'un moteur SAML certifié. On ne
        # fabrique jamais d'assertion : la configuration/metadata est exposée
        # mais l'ACS refuse tant qu'aucun adaptateur n'est installé.
        return {
            "protocol": "saml", "metadata_url": provider.metadata_url,
            "identity_provider_sso_url": provider.authorization_url,
            "acs_url": str(request.base_url).rstrip("/") + f"/api/auth/sso/{slug}/acs",
            "sp_entity_id": provider.entity_id,
            "requires_signed_assertion": True,
        }
    state = create_access_token(
        {"sub": "sso-state", "provider": provider.slug, "nonce": secrets.token_urlsafe(24)},
        expires_delta=timedelta(minutes=10),
    )
    query = urlencode({
        "client_id": provider.client_id,
        "redirect_uri": callback,
        "response_type": "code",
        "scope": " ".join(provider.scopes or ["openid", "email", "profile"]),
        "state": state,
    })
    return {"protocol": "oauth2", "authorization_url": f"{provider.authorization_url}?{query}", "state_expires_in": 600}


@router.post("/sso/{slug}/acs")
def saml_acs(
    slug: str, request: Request, SAMLResponse: str = Form(...), RelayState: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Assertion Consumer Service SAML 2.0.

    Seul le sous-arbre couvert par XMLDSig est lu. Le certificat X.509 de
    l'IdP configuré, l'émetteur, l'audience, la fenêtre temporelle et le rejeu
    de l'assertion sont contrôlés avant d'émettre une session GestImmo.
    """
    provider = db.query(SSOProvider).filter(
        SSOProvider.slug == slug, SSOProvider.protocol == "saml", SSOProvider.is_enabled == True
    ).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Fournisseur SAML introuvable")
    if not provider.certificate:
        raise HTTPException(status_code=503, detail="Certificat SAML de l'IdP non configuré")
    try:
        xml = base64.b64decode(SAMLResponse, validate=True)
        if len(xml) > 512_000:
            raise ValueError("Assertion trop volumineuse")
        from lxml import etree
        from signxml import XMLVerifier

        parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
        root = etree.fromstring(xml, parser=parser)
        verified = XMLVerifier().verify(root, x509_cert=provider.certificate)
        assertion = verified.signed_xml
    except Exception:
        raise HTTPException(status_code=400, detail="Signature ou document SAML invalide")

    def first_text(local_name: str):
        nodes = assertion.xpath(f".//*[local-name()='{local_name}']")
        return nodes[0].text.strip() if nodes and nodes[0].text else None

    assertion_id = assertion.get("ID")
    if not assertion_id or db.query(AuthChallenge).filter(
        AuthChallenge.purpose == "saml_assertion", AuthChallenge.challenge == assertion_id
    ).first():
        raise HTTPException(status_code=400, detail="Assertion SAML rejouée ou sans identifiant")
    issuer = first_text("Issuer")
    if provider.issuer and issuer != provider.issuer:
        raise HTTPException(status_code=403, detail="Émetteur SAML inattendu")
    now = security_service.utcnow()
    conditions = assertion.xpath(".//*[local-name()='Conditions']")
    if not conditions:
        raise HTTPException(status_code=403, detail="Conditions temporelles SAML absentes")
    condition = conditions[0]

    def saml_time(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None) if value else None

    try:
        not_before = saml_time(condition.get("NotBefore"))
        not_after = saml_time(condition.get("NotOnOrAfter"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Horodatage SAML invalide")
    if (not_before and now + timedelta(minutes=2) < not_before) or not not_after or now - timedelta(minutes=2) >= not_after:
        raise HTTPException(status_code=403, detail="Assertion SAML expirée ou prématurée")
    audiences = [node.text.strip() for node in assertion.xpath(".//*[local-name()='Audience']") if node.text]
    if provider.entity_id and provider.entity_id not in audiences:
        raise HTTPException(status_code=403, detail="Audience SAML inattendue")
    recipients = [
        node.get("Recipient") for node in assertion.xpath(".//*[local-name()='SubjectConfirmationData']")
        if node.get("Recipient")
    ]
    expected_recipient = str(request.url)
    if recipients and expected_recipient not in recipients:
        raise HTTPException(status_code=403, detail="Destinataire SAML inattendu")
    profile = {"email": None, "name": first_text("NameID")}
    for attribute in assertion.xpath(".//*[local-name()='Attribute']"):
        name = attribute.get("Name") or attribute.get("FriendlyName")
        values = attribute.xpath("./*[local-name()='AttributeValue']")
        value = values[0].text.strip() if values and values[0].text else None
        if name in {provider.email_claim, "email", "mail", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress"}:
            profile["email"] = value
        elif name in {"name", "displayName"} and value:
            profile["name"] = value
    if not profile["email"] and profile["name"] and "@" in profile["name"]:
        profile["email"] = profile["name"]
    if not profile["email"]:
        raise HTTPException(status_code=403, detail="L'assertion SAML ne contient pas d'email")
    user = _resolve_sso_user(db, provider, profile)
    if not user:
        raise HTTPException(status_code=403, detail="Aucun compte actif autorisé pour cette identité SAML")
    replay = AuthChallenge(
        user_id=user.id, purpose="saml_assertion", method=slug, challenge=assertion_id,
        expires_at=not_after, consumed_at=now,
    )
    db.add(replay)
    user.last_login_at = now
    security_service.record_login(db, user.email, True, request, user.id, method=f"saml:{slug}")
    db.flush()
    return _issue_tokens(db, user, request)


@router.get("/sso/{slug}/callback", name="sso_callback")
async def sso_callback(slug: str, request: Request, code: str | None = None, state: str | None = None, db: Session = Depends(get_db)):
    provider = db.query(SSOProvider).filter(SSOProvider.slug == slug, SSOProvider.is_enabled == True).first()
    if not provider:
        raise HTTPException(status_code=404, detail="Fournisseur SSO introuvable")
    if provider.protocol == "saml":
        raise HTTPException(status_code=501, detail="Adaptateur de validation SAML signé non installé")
    try:
        state_payload = decode_token(state or "")
        if state_payload.get("provider") != slug or state_payload.get("sub") != "sso-state":
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="État OAuth2 invalide")
    if not code:
        raise HTTPException(status_code=400, detail="Code OAuth2 manquant")
    callback = str(request.url_for("sso_callback", slug=slug))
    client_secret = security_service.decrypt_secret(provider.encrypted_client_secret)
    async with httpx.AsyncClient(timeout=10) as client:
        token_response = await client.post(provider.token_url, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": callback,
            "client_id": provider.client_id, "client_secret": client_secret,
        })
        if token_response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Échange OAuth2 refusé par le fournisseur")
        access_token = token_response.json().get("access_token")
        info_response = await client.get(provider.userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
        if info_response.status_code >= 400:
            raise HTTPException(status_code=502, detail="Profil OAuth2 indisponible")
    profile = info_response.json()
    email = profile.get(provider.email_claim or "email")
    if not email:
        raise HTTPException(status_code=403, detail="Le fournisseur n'a pas transmis d'email")
    profile["email"] = email
    user = _resolve_sso_user(db, provider, profile)
    if not user:
        raise HTTPException(status_code=403, detail="Aucun compte actif autorisé pour cette identité SSO")
    user.last_login_at = security_service.utcnow()
    security_service.record_login(db, user.email, True, request, user.id, method=f"sso:{slug}")
    db.flush()
    return _issue_tokens(db, user, request)


@router.get("/me")
def me(current_user=Depends(get_current_user)):
    return current_user.model_dump()


@router.get("/verify")
def verify(current_user=Depends(get_current_user)):
    return {"valid": True, "user": {"email": current_user.email, "role": current_user.role}}
