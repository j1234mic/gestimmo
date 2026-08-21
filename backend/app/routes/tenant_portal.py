"""Espace dédié au locataire : bail, loyers, quittances, incidents et messages."""

import hashlib
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.tenant_security import (
    create_tenant_tokens,
    get_current_tenant,
    hash_portal_password,
    refresh_tenant_tokens,
    verify_portal_password,
)
from app.database import get_db
from app.models.lease_contract import SignatureEnvelopeStatus, SignatureParty
from app.models.tenant import (
    ApplicationStatus,
    IncidentStatus,
    Lease,
    PaymentStatus,
    RentPayment,
    RentReceipt,
    RentalApplication,
    Tenant,
    TenantIncident,
    TenantInteraction,
    TenantMessage,
    TenantNotification,
)
from app.schemas.lease_contract import PublicSignatureInput
from app.schemas.tenant import (
    IncidentCreate,
    PortalActivation,
    PortalLogin,
    PortalRefresh,
    TenantMessageCreate,
)
from app.services.lease_service import complete_signature, datetime_is_past
from app.services.tenant_payment_service import (
    create_stripe_checkout,
    generate_receipt_pdf,
    process_stripe_event,
    verify_stripe_signature,
)
from app.services.tenant_service import (
    calculate_reliability_score,
    create_notification,
    generate_reference,
    verify_tracking_token,
)

router = APIRouter(prefix="/tenant-portal", tags=["Portail locataire"])


def _lease_view(lease: Lease) -> dict:
    return {
        "id": lease.id,
        "reference": lease.reference,
        "status": lease.status.value,
        "start_date": lease.start_date,
        "end_date": lease.end_date,
        "monthly_rent": lease.monthly_rent,
        "monthly_charges": lease.monthly_charges,
        "deposit": lease.deposit,
        "payment_day": lease.payment_day,
        "lease_type": lease.lease_type,
        "signed_at": lease.signed_at,
        "property": {
            "reference": lease.property.reference,
            "title": lease.property.title,
            "address": lease.property.address,
            "postal_code": lease.property.postal_code,
            "city": lease.property.city,
        },
        "document_url": f"/tenant-portal/leases/{lease.id}/document" if lease.document_storage_path else None,
    }


def _payment_view(payment: RentPayment) -> dict:
    return {
        "id": payment.id,
        "reference": payment.reference,
        "lease_id": payment.lease_id,
        "period": payment.period,
        "due_date": payment.due_date,
        "amount_due": payment.amount_due,
        "amount_paid": payment.amount_paid,
        "remaining_amount": round(max(0, payment.amount_due - payment.amount_paid), 2),
        "status": payment.status.value,
        "paid_at": payment.paid_at,
        "payment_method": payment.payment_method,
        "receipt_id": payment.receipt.id if payment.receipt else None,
    }


# Authentification et webhook (routes publiques)
@router.post("/activate")
def activate_portal(data: PortalActivation, db: Session = Depends(get_db)):
    application = db.query(RentalApplication).filter(RentalApplication.reference == data.application_reference).first()
    if not application or not verify_tracking_token(application, data.tracking_token):
        raise HTTPException(status_code=404, detail="Candidature ou jeton de suivi invalide")
    if application.status != ApplicationStatus.ACCEPTED or not application.tenant:
        raise HTTPException(status_code=409, detail="Le portail est disponible après acceptation de la candidature")
    tenant = application.tenant
    tenant.portal_password_hash = hash_portal_password(data.password)
    tenant.portal_enabled = True
    db.commit()
    tokens = create_tenant_tokens(tenant)
    return {
        **tokens,
        "tenant": {"id": tenant.id, "reference": tenant.reference, "first_name": tenant.first_name, "last_name": tenant.last_name},
    }


@router.post("/login")
def portal_login(data: PortalLogin, db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter(Tenant.email == str(data.email), Tenant.is_active.is_(True)).order_by(Tenant.id.desc()).first()
    if not tenant or not tenant.portal_enabled or not verify_portal_password(data.password, tenant.portal_password_hash):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")
    tenant.last_portal_login_at = datetime.now(timezone.utc)
    db.commit()
    return {
        **create_tenant_tokens(tenant),
        "tenant": {"id": tenant.id, "reference": tenant.reference, "first_name": tenant.first_name, "last_name": tenant.last_name},
    }


@router.post("/refresh")
def portal_refresh(data: PortalRefresh, db: Session = Depends(get_db)):
    return refresh_tenant_tokens(db, data.refresh_token)


@router.post("/payments/webhook/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header("", alias="Stripe-Signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()
    if not verify_stripe_signature(payload, stripe_signature):
        raise HTTPException(status_code=400, detail="Signature Stripe invalide")
    try:
        return process_stripe_event(db, payload)
    except ValueError:
        raise HTTPException(status_code=400, detail="Événement invalide")


# Espace authentifié
@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    active_leases = [lease for lease in tenant.leases if lease.status.value == "active"]
    outstanding = [
        payment for payment in tenant.payments
        if payment.status in (PaymentStatus.DUE, PaymentStatus.PARTIAL, PaymentStatus.OVERDUE)
    ]
    next_payment = min(outstanding, key=lambda item: item.due_date, default=None)
    unread_messages = db.query(TenantMessage).filter(
        TenantMessage.tenant_id == tenant.id,
        TenantMessage.sender_type == "manager",
        TenantMessage.is_read.is_(False),
    ).count()
    unread_notifications = db.query(TenantNotification).filter(
        TenantNotification.tenant_id == tenant.id,
        TenantNotification.is_read.is_(False),
    ).count()
    return {
        "tenant": {
            "id": tenant.id,
            "reference": tenant.reference,
            "name": f"{tenant.first_name} {tenant.last_name}",
            "reliability_score": tenant.reliability_score,
        },
        "active_leases": len(active_leases),
        "outstanding_balance": round(sum(max(0, p.amount_due - p.amount_paid) for p in outstanding), 2),
        "next_payment": _payment_view(next_payment) if next_payment else None,
        "open_incidents": sum(i.status in (IncidentStatus.OPEN, IncidentStatus.IN_PROGRESS) for i in tenant.incidents),
        "unread_messages": unread_messages,
        "unread_notifications": unread_notifications,
    }


@router.get("/profile")
def profile(tenant: Tenant = Depends(get_current_tenant)):
    return {
        "id": tenant.id,
        "reference": tenant.reference,
        "status": tenant.status.value,
        "first_name": tenant.first_name,
        "last_name": tenant.last_name,
        "email": tenant.email,
        "phone": tenant.phone,
        "mobile": tenant.mobile,
        "address": tenant.address,
        "postal_code": tenant.postal_code,
        "city": tenant.city,
        "country": tenant.country,
        "occupation": tenant.occupation,
        "employer_name": tenant.employer_name,
        "solvency_score": tenant.solvency_score,
        "reliability_score": tenant.reliability_score,
    }


@router.get("/contract-signatures")
def pending_contract_signatures(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    parties = db.query(SignatureParty).filter(
        SignatureParty.party_type == "tenant",
        (SignatureParty.party_id == tenant.id) | (SignatureParty.email == tenant.email),
    ).order_by(SignatureParty.created_at.desc()).all()
    return [
        {
            "party_id": party.id,
            "status": party.status.value,
            "signing_order": party.signing_order,
            "envelope": {
                "reference": party.envelope.reference,
                "subject": party.envelope.subject,
                "message": party.envelope.message,
                "status": party.envelope.status.value,
                "expires_at": party.envelope.expires_at,
            },
            "document": {
                "id": party.envelope.document.id,
                "title": party.envelope.document.title,
                "checksum_sha256": party.envelope.document.checksum_sha256,
                "download_url": f"/tenant-portal/contract-signatures/{party.id}/document",
            },
        }
        for party in parties
    ]


@router.get("/contract-signatures/{party_id}/document")
def contract_signature_document(
    party_id: int,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    party = db.query(SignatureParty).filter(
        SignatureParty.id == party_id,
        SignatureParty.party_type == "tenant",
        (SignatureParty.party_id == tenant.id) | (SignatureParty.email == tenant.email),
    ).first()
    if not party:
        raise HTTPException(status_code=404, detail="Demande de signature non trouvée")
    document = party.envelope.document
    if not os.path.isfile(document.storage_path):
        raise HTTPException(status_code=404, detail="Document non trouvé")
    with open(document.storage_path, "rb") as source:
        checksum = hashlib.sha256(source.read()).hexdigest()
    if checksum != document.checksum_sha256:
        raise HTTPException(status_code=409, detail="L'intégrité du document ne peut pas être vérifiée")
    return FileResponse(document.storage_path, media_type=document.mime_type, filename=document.original_filename)


@router.post("/contract-signatures/{party_id}/sign")
def sign_contract_from_portal(
    party_id: int,
    data: PublicSignatureInput,
    request: Request,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    party = db.query(SignatureParty).filter(
        SignatureParty.id == party_id,
        SignatureParty.party_type == "tenant",
        (SignatureParty.party_id == tenant.id) | (SignatureParty.email == tenant.email),
    ).first()
    if not party:
        raise HTTPException(status_code=404, detail="Demande de signature non trouvée")
    if party.envelope.expires_at and datetime_is_past(party.envelope.expires_at):
        party.envelope.status = SignatureEnvelopeStatus.EXPIRED
        db.commit()
        raise HTTPException(status_code=410, detail="Demande de signature expirée")
    if party.envelope.status in {
        SignatureEnvelopeStatus.CANCELLED,
        SignatureEnvelopeStatus.DECLINED,
        SignatureEnvelopeStatus.EXPIRED,
    }:
        raise HTTPException(status_code=409, detail="Cette procédure de signature n'est plus active")
    try:
        complete_signature(
            db,
            party,
            data.typed_signature,
            data.signature_image_base64,
            request.client.host if request.client else "unknown",
            request.headers.get("User-Agent", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": party.status.value, "signed_at": party.signed_at, "envelope_status": party.envelope.status.value}


@router.get("/leases")
def leases(tenant: Tenant = Depends(get_current_tenant)):
    return [_lease_view(lease) for lease in sorted(tenant.leases, key=lambda item: item.start_date, reverse=True)]


@router.get("/leases/{lease_id}")
def lease_detail(lease_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    lease = db.query(Lease).filter(Lease.id == lease_id, Lease.tenant_id == tenant.id).first()
    if not lease:
        raise HTTPException(status_code=404, detail="Bail non trouvé")
    return _lease_view(lease)


@router.get("/leases/{lease_id}/document")
def lease_document(lease_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    lease = db.query(Lease).filter(Lease.id == lease_id, Lease.tenant_id == tenant.id).first()
    if not lease or not lease.document_storage_path or not os.path.isfile(lease.document_storage_path):
        raise HTTPException(status_code=404, detail="Document de bail non trouvé")
    return FileResponse(lease.document_storage_path, media_type="application/pdf", filename=f"bail-{lease.reference}.pdf")


@router.get("/payments")
def payments(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    records = db.query(RentPayment).filter(RentPayment.tenant_id == tenant.id).order_by(RentPayment.due_date.desc()).all()
    return [_payment_view(payment) for payment in records]


@router.post("/payments/{payment_id}/checkout", status_code=201)
def create_checkout(payment_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    payment = db.query(RentPayment).filter(RentPayment.id == payment_id, RentPayment.tenant_id == tenant.id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Paiement non trouvé")
    try:
        attempt = create_stripe_checkout(db, payment)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "payment_id": payment.id,
        "provider": attempt.provider,
        "session_id": attempt.provider_session_id,
        "checkout_url": attempt.checkout_url,
        "amount": attempt.amount,
        "status": attempt.status,
    }


@router.get("/receipts")
def receipts(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    records = db.query(RentReceipt).filter(RentReceipt.tenant_id == tenant.id).order_by(RentReceipt.issued_at.desc()).all()
    return [
        {
            "id": receipt.id,
            "reference": receipt.reference,
            "period": receipt.period,
            "issued_at": receipt.issued_at,
            "amount": receipt.payment.amount_paid,
            "download_url": f"/tenant-portal/receipts/{receipt.id}/download",
        }
        for receipt in records
    ]


@router.get("/receipts/{receipt_id}/download")
def receipt_download(receipt_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    receipt = db.query(RentReceipt).filter(RentReceipt.id == receipt_id, RentReceipt.tenant_id == tenant.id).first()
    if not receipt:
        raise HTTPException(status_code=404, detail="Quittance non trouvée")
    return StreamingResponse(
        generate_receipt_pdf(receipt),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="quittance-{receipt.period}.pdf"'},
    )


@router.get("/incidents")
def incidents(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    return db.query(TenantIncident).filter(TenantIncident.tenant_id == tenant.id).order_by(TenantIncident.reported_at.desc()).all()


@router.post("/incidents", status_code=201)
def report_incident(data: IncidentCreate, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    if data.lease_id and not db.query(Lease).filter(Lease.id == data.lease_id, Lease.tenant_id == tenant.id).first():
        raise HTTPException(status_code=400, detail="Bail invalide")
    incident = TenantIncident(tenant_id=tenant.id, reference=generate_reference("INC"), **data.model_dump())
    db.add(incident)
    db.add(TenantInteraction(
        tenant_id=tenant.id,
        interaction_type="incident",
        direction="incoming",
        subject=data.title,
        content=data.description,
        actor=f"tenant:{tenant.id}",
    ))
    create_notification(
        db,
        tenant_id=tenant.id,
        notification_type="incident_received",
        title="Demande d'intervention reçue",
        content=f"Votre demande {incident.reference} a été transmise au gestionnaire.",
    )
    db.flush()
    calculate_reliability_score(db, tenant, commit=False)
    db.commit()
    db.refresh(incident)
    return incident


@router.get("/messages")
def messages(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    records = db.query(TenantMessage).filter(TenantMessage.tenant_id == tenant.id).order_by(TenantMessage.created_at.desc()).all()
    now = datetime.now(timezone.utc)
    for message in records:
        if message.sender_type == "manager" and not message.is_read:
            message.is_read = True
            message.read_at = now
    db.commit()
    return records


@router.post("/messages", status_code=201)
def send_message(data: TenantMessageCreate, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    message = TenantMessage(
        tenant_id=tenant.id,
        sender_type="tenant",
        sender_name=f"{tenant.first_name} {tenant.last_name}",
        **data.model_dump(),
    )
    db.add(message)
    db.add(TenantInteraction(
        tenant_id=tenant.id,
        interaction_type="message",
        direction="incoming",
        subject=data.subject,
        content=data.content,
        actor=f"tenant:{tenant.id}",
    ))
    db.commit()
    db.refresh(message)
    return message


@router.get("/notifications")
def notifications(only_unread: bool = False, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    query = db.query(TenantNotification).filter(TenantNotification.tenant_id == tenant.id)
    if only_unread:
        query = query.filter(TenantNotification.is_read.is_(False))
    return query.order_by(TenantNotification.sent_at.desc()).all()


@router.put("/notifications/{notification_id}/read")
def read_notification(notification_id: int, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    notification = db.query(TenantNotification).filter(
        TenantNotification.id == notification_id,
        TenantNotification.tenant_id == tenant.id,
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification non trouvée")
    notification.is_read = True
    notification.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"message": "Notification marquée comme lue"}
