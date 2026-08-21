"""Paiement en ligne Stripe et génération des quittances."""

import hashlib
import hmac
import io
import json
import time
from datetime import datetime, timezone

import httpx
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors
from sqlalchemy.orm import Session

from app.config import settings
from app.models.tenant import PaymentAttempt, PaymentStatus, RentPayment, RentReceipt
from app.services.tenant_service import calculate_reliability_score, ensure_receipt


def create_stripe_checkout(db: Session, payment: RentPayment) -> PaymentAttempt:
    if not settings.STRIPE_SECRET_KEY:
        raise RuntimeError("Le paiement en ligne n'est pas configuré (STRIPE_SECRET_KEY manquante)")
    remaining = round(float(payment.amount_due) - float(payment.amount_paid or 0), 2)
    if remaining <= 0 or payment.status in (PaymentStatus.PAID, PaymentStatus.CANCELLED):
        raise ValueError("Ce paiement est déjà soldé ou annulé")

    success_url = settings.PAYMENT_SUCCESS_URL.replace("{payment_id}", str(payment.id))
    cancel_url = settings.PAYMENT_CANCEL_URL.replace("{payment_id}", str(payment.id))
    payload = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": payment.reference,
        "customer_email": payment.tenant.email,
        "metadata[payment_id]": str(payment.id),
        "metadata[tenant_id]": str(payment.tenant_id),
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": settings.PAYMENT_CURRENCY.lower(),
        "line_items[0][price_data][unit_amount]": str(int(round(remaining * 100))),
        "line_items[0][price_data][product_data][name]": f"Loyer {payment.period}",
        "line_items[0][price_data][product_data][description]": payment.reference,
    }
    response = httpx.post(
        "https://api.stripe.com/v1/checkout/sessions",
        data=payload,
        auth=(settings.STRIPE_SECRET_KEY, ""),
        timeout=20,
    )
    if response.status_code >= 400:
        detail = response.json().get("error", {}).get("message", "Erreur du prestataire de paiement")
        raise RuntimeError(detail)
    stripe_session = response.json()
    attempt = PaymentAttempt(
        payment_id=payment.id,
        provider="stripe",
        provider_session_id=stripe_session["id"],
        amount=remaining,
        status="pending",
        checkout_url=stripe_session.get("url"),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def verify_stripe_signature(payload: bytes, signature_header: str) -> bool:
    if not settings.STRIPE_WEBHOOK_SECRET or not signature_header:
        return False
    values = {}
    for part in signature_header.split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            values.setdefault(key, []).append(value)
    try:
        timestamp = int(values["t"][0])
    except (KeyError, ValueError, TypeError):
        return False
    if abs(int(time.time()) - timestamp) > 300:
        return False
    signed = f"{timestamp}.".encode() + payload
    expected = hmac.new(settings.STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in values.get("v1", []))


def process_stripe_event(db: Session, payload: bytes) -> dict:
    event = json.loads(payload.decode("utf-8"))
    if event.get("type") != "checkout.session.completed":
        return {"received": True, "processed": False}
    session = event.get("data", {}).get("object", {})
    attempt = db.query(PaymentAttempt).filter(PaymentAttempt.provider_session_id == session.get("id")).first()
    if not attempt:
        return {"received": True, "processed": False, "reason": "unknown_session"}
    if attempt.status == "completed":
        return {"received": True, "processed": True, "idempotent": True}

    payment = attempt.payment
    paid_amount = float(session.get("amount_total", 0)) / 100
    payment.amount_paid = min(payment.amount_due, float(payment.amount_paid or 0) + paid_amount)
    payment.status = PaymentStatus.PAID if payment.amount_paid >= payment.amount_due else PaymentStatus.PARTIAL
    payment.paid_at = datetime.now(timezone.utc)
    payment.payment_method = "online_stripe"
    payment.external_reference = session.get("payment_intent") or session.get("id")
    attempt.status = "completed"
    attempt.completed_at = datetime.now(timezone.utc)
    ensure_receipt(db, payment)
    calculate_reliability_score(db, payment.tenant, commit=False)
    db.commit()
    return {"received": True, "processed": True, "payment_id": payment.id}


def generate_receipt_pdf(receipt: RentReceipt) -> io.BytesIO:
    payment = receipt.payment
    tenant = receipt.tenant
    lease = receipt.lease
    prop = lease.property
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Quittance {receipt.reference}",
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("QUITTANCE DE LOYER", styles["Title"]),
        Spacer(1, 0.5 * cm),
        Paragraph(f"Référence : {receipt.reference}", styles["Normal"]),
        Paragraph(f"Période : {receipt.period}", styles["Normal"]),
        Paragraph(f"Date d'émission : {receipt.issued_at.strftime('%d/%m/%Y') if receipt.issued_at else ''}", styles["Normal"]),
        Spacer(1, 0.6 * cm),
        Paragraph(f"Locataire : {tenant.first_name} {tenant.last_name}", styles["Heading3"]),
        Paragraph(f"Logement : {prop.address}, {prop.postal_code} {prop.city}", styles["Normal"]),
        Spacer(1, 0.6 * cm),
    ]
    charges = float(lease.monthly_charges or 0)
    rent = max(0, float(payment.amount_due) - charges)
    table = Table([
        ["Désignation", "Montant"],
        ["Loyer hors charges", f"{rent:.2f} €"],
        ["Provision pour charges", f"{charges:.2f} €"],
        ["Total acquitté", f"{float(payment.amount_paid):.2f} €"],
    ], colWidths=[11 * cm, 4 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#244C66")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 1), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E8F0F4")),
    ]))
    story.extend([
        table,
        Spacer(1, 1 * cm),
        Paragraph(
            f"Le bailleur reconnaît avoir reçu la somme de {float(payment.amount_paid):.2f} € "
            f"au titre du loyer et des charges pour la période {receipt.period}, sous réserve de tous droits.",
            styles["BodyText"],
        ),
        Spacer(1, 1 * cm),
        Paragraph("Document généré électroniquement par GestImmo.", styles["Italic"]),
    ])
    document.build(story)
    output.seek(0)
    return output
