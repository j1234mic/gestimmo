"""Routes du module « Abonnements & revenus récurrents ».

Endpoints d'administration (CRUD clients, comptes de paiement, abonnements
premium), d'encaissement réel via prestataire (checkout) et webhooks publics
de notification des prestataires de paiement.

⚠️ Ordre des routes : les routes statiques (``/overview``, ``/clients``,
``/payment-accounts``, ``/payments``, ``/webhooks``) sont déclarées AVANT les
routes paramétrées ``/{subscription_id}`` afin que FastAPI ne capture pas un
segment statique (ex. ``/payments``) dans un paramètre entier.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.database import get_db
from app.models.subscription import (
    ClientPaymentAccount,
    PaymentProvider,
    PremiumSubscription,
    SubscriptionClient,
    SubscriptionPayment,
    SubscriptionPaymentStatus,
    SubscriptionPlan,
    SubscriptionStatus,
)
from app.schemas.subscription import (
    CheckoutCreate,
    CheckoutResponse,
    ClientCreate,
    ClientResponse,
    ClientUpdate,
    ConfirmResponse,
    PaymentAccountCreate,
    PaymentAccountResponse,
    PaymentAccountUpdate,
    PaymentResponse,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
)
from app.services.subscription_service import (
    cancel_subscription,
    confirm_by_token,
    create_checkout,
    create_client,
    create_payment_account,
    create_subscription,
    process_provider_event,
    update_client,
)

router = APIRouter(prefix="/api/subscriptions", tags=["Abonnements & revenus"])


# ---------------------------------------------------------------------------
# Vue d'ensemble
# ---------------------------------------------------------------------------
@router.get("/overview")
def subscriptions_overview(db: Session = Depends(get_db), user=Depends(require_read)):
    counts = {
        "clients": db.query(SubscriptionClient).count(),
        "payment_accounts": db.query(ClientPaymentAccount).count(),
        "subscriptions": db.query(PremiumSubscription).count(),
        "active_subscriptions": db.query(PremiumSubscription)
        .filter(PremiumSubscription.status == SubscriptionStatus.ACTIVE)
        .count(),
        "payments": db.query(SubscriptionPayment).count(),
        "succeeded_payments": db.query(SubscriptionPayment)
        .filter(SubscriptionPayment.status == SubscriptionPaymentStatus.SUCCEEDED)
        .count(),
    }
    total_revenue = (
        db.query(SubscriptionPayment.amount)
        .filter(SubscriptionPayment.status == SubscriptionPaymentStatus.SUCCEEDED)
        .all()
    )
    counts["total_revenue"] = round(sum(row[0] for row in total_revenue), 2)
    return {"data": counts}


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@router.post("/clients", response_model=ClientResponse, status_code=201)
def add_client(data: ClientCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    try:
        client = create_client(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return client


@router.get("/clients")
def list_clients(
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    query = db.query(SubscriptionClient)
    if search:
        like = f"%{search}%"
        query = query.filter(
            (SubscriptionClient.name.ilike(like))
            | (SubscriptionClient.email.ilike(like))
            | (SubscriptionClient.reference.ilike(like))
        )
    if is_active is not None:
        query = query.filter(SubscriptionClient.is_active == is_active)
    total = query.count()
    rows = query.order_by(SubscriptionClient.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [ClientResponse.model_validate(r).model_dump() for r in rows], "total": total}


@router.get("/clients/{client_id}", response_model=ClientResponse)
def get_client(client_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    client = db.query(SubscriptionClient).filter(SubscriptionClient.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return client


@router.patch("/clients/{client_id}", response_model=ClientResponse)
def modify_client(
    client_id: int,
    data: ClientUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    client = db.query(SubscriptionClient).filter(SubscriptionClient.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return update_client(db, client, data)


# ---------------------------------------------------------------------------
# Comptes de paiement
# ---------------------------------------------------------------------------
@router.post("/payment-accounts", response_model=PaymentAccountResponse, status_code=201)
def add_payment_account(data: PaymentAccountCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    try:
        account = create_payment_account(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return account


@router.get("/payment-accounts")
def list_payment_accounts(
    client_id: Optional[int] = None,
    provider: Optional[PaymentProvider] = None,
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    query = db.query(ClientPaymentAccount)
    if client_id is not None:
        query = query.filter(ClientPaymentAccount.client_id == client_id)
    if provider is not None:
        query = query.filter(ClientPaymentAccount.provider == provider)
    rows = query.order_by(ClientPaymentAccount.id.desc()).all()
    return {"data": [PaymentAccountResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.patch("/payment-accounts/{account_id}", response_model=PaymentAccountResponse)
def modify_payment_account(
    account_id: int,
    data: PaymentAccountUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    account = db.query(ClientPaymentAccount).filter(ClientPaymentAccount.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Compte de paiement introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return account


# ---------------------------------------------------------------------------
# Paiements / revenus
# ---------------------------------------------------------------------------
@router.get("/payments")
def list_payments(
    subscription_id: Optional[int] = None,
    client_id: Optional[int] = None,
    status: Optional[SubscriptionPaymentStatus] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    query = db.query(SubscriptionPayment)
    if subscription_id is not None:
        query = query.filter(SubscriptionPayment.subscription_id == subscription_id)
    if client_id is not None:
        query = query.filter(SubscriptionPayment.client_id == client_id)
    if status is not None:
        query = query.filter(SubscriptionPayment.status == status)
    total = query.count()
    rows = query.order_by(SubscriptionPayment.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [PaymentResponse.model_validate(r).model_dump() for r in rows], "total": total}


@router.get("/payments/{reference}", response_model=PaymentResponse)
def get_payment(reference: str, db: Session = Depends(get_db), user=Depends(require_read)):
    payment = db.query(SubscriptionPayment).filter(SubscriptionPayment.reference == reference).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    return payment


@router.post("/payments/{reference}/confirm", response_model=ConfirmResponse)
def confirm_simulated_payment(
    reference: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    """Confirme un encaissement en mode simulation (aucun prestataire live)."""
    payment = db.query(SubscriptionPayment).filter(SubscriptionPayment.reference == reference).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    try:
        confirmed = confirm_by_token(db, reference, token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    subscription = confirmed.subscription
    return {
        "payment_id": confirmed.id,
        "reference": confirmed.reference,
        "status": confirmed.status,
        "subscription_id": confirmed.subscription_id,
        "subscription_status": subscription.status,
        "paid_amount": confirmed.amount,
        "currency": confirmed.currency,
    }


# ---------------------------------------------------------------------------
# Webhooks prestataires (publics, comme le webhook Stripe locataire)
# ---------------------------------------------------------------------------
@router.post("/webhooks/{provider}")
async def payment_webhook(
    provider: PaymentProvider,
    request: Request,
    stripe_signature: str = Header("", alias="Stripe-Signature"),
    x_provider_signature: str = Header("", alias="X-Provider-Signature"),
    db: Session = Depends(get_db),
):
    signature = stripe_signature or x_provider_signature
    body = await request.body()
    return process_provider_event(db, provider, body, signature)


# ---------------------------------------------------------------------------
# Abonnements premium
# ---------------------------------------------------------------------------
@router.post("", response_model=SubscriptionResponse, status_code=201)
def add_subscription(data: SubscriptionCreate, db: Session = Depends(get_db), user=Depends(require_write)):
    try:
        subscription = create_subscription(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return subscription


@router.get("")
def list_subscriptions(
    status: Optional[SubscriptionStatus] = None,
    plan: Optional[SubscriptionPlan] = None,
    client_id: Optional[int] = None,
    provider: Optional[PaymentProvider] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=Depends(require_read),
):
    query = db.query(PremiumSubscription)
    if status is not None:
        query = query.filter(PremiumSubscription.status == status)
    if plan is not None:
        query = query.filter(PremiumSubscription.plan == plan)
    if client_id is not None:
        query = query.filter(PremiumSubscription.client_id == client_id)
    if provider is not None:
        query = query.filter(PremiumSubscription.provider == provider)
    total = query.count()
    rows = query.order_by(PremiumSubscription.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [SubscriptionResponse.model_validate(r).model_dump() for r in rows], "total": total}


@router.get("/{subscription_id}", response_model=SubscriptionResponse)
def get_subscription(subscription_id: int, db: Session = Depends(get_db), user=Depends(require_read)):
    sub = db.query(PremiumSubscription).filter(PremiumSubscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Abonnement introuvable")
    return sub


@router.patch("/{subscription_id}", response_model=SubscriptionResponse)
def modify_subscription(
    subscription_id: int,
    data: SubscriptionUpdate,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    sub = db.query(PremiumSubscription).filter(PremiumSubscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Abonnement introuvable")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(sub, field, value)
    db.commit()
    db.refresh(sub)
    return sub


@router.post("/{subscription_id}/cancel", response_model=SubscriptionResponse)
def cancel_premium_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    sub = db.query(PremiumSubscription).filter(PremiumSubscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Abonnement introuvable")
    return cancel_subscription(db, sub)


@router.post("/{subscription_id}/checkout", response_model=CheckoutResponse, status_code=201)
def start_checkout(
    subscription_id: int,
    data: Optional[CheckoutCreate] = None,
    db: Session = Depends(get_db),
    user=Depends(require_write),
):
    sub = db.query(PremiumSubscription).filter(PremiumSubscription.id == subscription_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Abonnement introuvable")
    data = data or CheckoutCreate()
    try:
        payment = create_checkout(db, sub, provider=data.provider, amount_override=data.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "payment_id": payment.id,
        "payment_reference": payment.reference,
        "subscription_id": payment.subscription_id,
        "client_id": payment.client_id,
        "provider": payment.provider,
        "session_id": payment.provider_session_id,
        "checkout_url": getattr(payment, "checkout_url", None),
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.status,
        "simulated": getattr(payment, "is_simulated", False),
    }
