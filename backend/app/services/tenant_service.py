"""Règles métier du module locataires : scoring, workflow et suivi."""

import hashlib
import secrets
import uuid
from datetime import date, datetime, timezone
from typing import Dict, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.property import Property
from app.models.tenant import (
    ApplicationStatus,
    ApplicationStatusHistory,
    ContractType,
    DocumentType,
    EmploymentStatus,
    GuaranteeScheme,
    Guarantor,
    IncidentStatus,
    IncomeType,
    LegalCaseStatus,
    PaymentStatus,
    RentPayment,
    RentReceipt,
    RentalApplication,
    Tenant,
    TenantAlert,
    TenantIncome,
    TenantIncident,
    TenantInteraction,
    TenantNotification,
    LegalCase,
    VerificationStatus,
)
from app.schemas.tenant import ApplicationCreate, TenantCreate


def generate_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def generate_tracking_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_tracking_token(token)


def hash_tracking_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_tracking_token(application: RentalApplication, token: str) -> bool:
    if not token:
        return False
    return secrets.compare_digest(application.tracking_token_hash, hash_tracking_token(token))


def create_notification(
    db: Session,
    *,
    title: str,
    content: str,
    notification_type: str = "info",
    tenant_id: Optional[int] = None,
    application_id: Optional[int] = None,
) -> TenantNotification:
    notification = TenantNotification(
        tenant_id=tenant_id,
        application_id=application_id,
        channel="in_app",
        notification_type=notification_type,
        title=title,
        content=content,
        delivery_status="delivered",
    )
    db.add(notification)
    return notification


def _property_rent(application: RentalApplication) -> float:
    if application.property:
        return float(application.property.rent_price or 0) + float(application.property.charges or 0)
    return float(application.current_monthly_rent or 0)


def document_completeness(application: RentalApplication) -> Dict:
    usable = [
        document for document in application.documents
        if document.guarantor_id is None and document.verification_status != VerificationStatus.REJECTED
    ]
    counts = {document_type.value: 0 for document_type in DocumentType}
    for document in usable:
        counts[document.document_type.value] = counts.get(document.document_type.value, 0) + 1

    requirements = {
        DocumentType.IDENTITY.value: 1,
        DocumentType.PAY_SLIP.value: 3,
        DocumentType.TAX_NOTICE.value: 1,
        DocumentType.PROOF_OF_ADDRESS.value: 1,
        DocumentType.EMPLOYMENT_CONTRACT.value: 1,
        DocumentType.EMPLOYER_CERTIFICATE.value: 1,
    }
    satisfied_units = sum(min(counts.get(kind, 0), required) for kind, required in requirements.items())
    total_units = sum(requirements.values())
    missing = {
        kind: required - counts.get(kind, 0)
        for kind, required in requirements.items()
        if counts.get(kind, 0) < required
    }
    return {
        "percentage": round(satisfied_units / total_units * 100, 2),
        "complete": not missing,
        "missing": missing,
        "counts": {kind: counts.get(kind, 0) for kind in requirements},
    }


def calculate_application_score(db: Session, application: RentalApplication, commit: bool = True) -> Dict:
    """Calcule un score explicable de 0 à 100, sans décision discriminatoire.

    Le moteur n'utilise que revenus, stabilité professionnelle, complétude et
    vérification des pièces, et présence d'une garantie. Les données sensibles
    (nationalité, âge, lieu de naissance) sont volontairement exclues.
    """
    income = float(application.monthly_net_income or 0) + float(application.other_monthly_income or 0)
    rent = _property_rent(application)
    ratio = income / rent if rent > 0 else 0

    if rent <= 0:
        affordability = 18.0
    elif ratio >= 3.5:
        affordability = 35.0
    elif ratio >= 3:
        affordability = 31.0
    elif ratio >= 2.5:
        affordability = 25.0
    elif ratio >= 2:
        affordability = 17.0
    elif ratio >= 1.5:
        affordability = 9.0
    else:
        affordability = 3.0

    employment_points = {
        EmploymentStatus.CIVIL_SERVANT: 20,
        EmploymentStatus.EMPLOYEE: 16,
        EmploymentStatus.SELF_EMPLOYED: 13,
        EmploymentStatus.RETIRED: 14,
        EmploymentStatus.STUDENT: 8,
        EmploymentStatus.UNEMPLOYED: 2,
        EmploymentStatus.OTHER: 7,
    }.get(application.employment_status, 5)
    if application.contract_type in (ContractType.CDI, ContractType.PUBLIC_SERVICE):
        employment_points = min(20, employment_points + 4)
    elif application.contract_type in (ContractType.CDD, ContractType.APPRENTICESHIP):
        employment_points = min(20, employment_points + 1)

    completeness = document_completeness(application)
    document_points = completeness["percentage"] / 100 * 25
    candidate_documents = [d for d in application.documents if d.guarantor_id is None]
    verified_count = sum(d.verification_status == VerificationStatus.VERIFIED for d in candidate_documents)
    verification_points = min(10, verified_count * 2)

    guarantee_points = 0.0
    if application.guarantors:
        if any(g.guarantee_scheme in (GuaranteeScheme.VISALE, GuaranteeScheme.GLI) for g in application.guarantors):
            guarantee_points = 10.0
        elif any((g.monthly_net_income or 0) + (g.other_monthly_income or 0) >= max(rent * 3, 1) for g in application.guarantors):
            guarantee_points = 10.0
        else:
            guarantee_points = 6.0

    score = round(min(100, affordability + employment_points + document_points + verification_points + guarantee_points), 2)
    if score >= 75:
        risk_level = "low"
        recommendation = "favorable"
    elif score >= 55:
        risk_level = "moderate"
        recommendation = "manual_review"
    else:
        risk_level = "high"
        recommendation = "unfavorable"

    breakdown = {
        "affordability": round(affordability, 2),
        "employment_stability": round(float(employment_points), 2),
        "document_completeness": round(document_points, 2),
        "document_verification": round(float(verification_points), 2),
        "guarantee": round(guarantee_points, 2),
        "income_to_rent_ratio": round(ratio, 2) if rent else None,
        "declared_monthly_income": round(income, 2),
        "target_monthly_rent": round(rent, 2),
        "documents": completeness,
        "recommendation": recommendation,
        "method_version": "1.0",
    }
    application.solvency_score = score
    application.score_breakdown = breakdown
    application.risk_level = risk_level
    application.scored_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
        db.refresh(application)
    return {"score": score, "risk_level": risk_level, "breakdown": breakdown}


def create_application(db: Session, data: ApplicationCreate) -> tuple[RentalApplication, str]:
    if data.property_id and not db.query(Property).filter(Property.id == data.property_id, Property.is_active == True).first():
        raise ValueError("Bien non trouvé ou inactif")

    token, token_hash = generate_tracking_token()
    payload = data.model_dump(exclude={"guarantors"})
    application = RentalApplication(
        **payload,
        reference=generate_reference("APP"),
        tracking_token_hash=token_hash,
        status=ApplicationStatus.PENDING,
    )
    db.add(application)
    db.flush()
    for guarantor_data in data.guarantors:
        db.add(Guarantor(application_id=application.id, **guarantor_data.model_dump()))
    db.add(ApplicationStatusHistory(
        application_id=application.id,
        previous_status=None,
        new_status=ApplicationStatus.PENDING,
        reason="Candidature déposée en ligne",
        changed_by="candidate",
    ))
    create_notification(
        db,
        application_id=application.id,
        notification_type="application_submitted",
        title="Candidature reçue",
        content=f"Votre candidature {application.reference} a bien été reçue et est en cours d'étude.",
    )
    db.flush()
    calculate_application_score(db, application, commit=False)
    db.commit()
    db.refresh(application)
    return application, token


def _copy_application_to_tenant(db: Session, application: RentalApplication) -> Tenant:
    tenant = Tenant(
        reference=generate_reference("TEN"),
        first_name=application.first_name,
        last_name=application.last_name,
        birth_date=application.birth_date,
        birth_place=application.birth_place,
        nationality=application.nationality,
        email=application.email,
        phone=application.phone,
        address=application.address,
        postal_code=application.postal_code,
        city=application.city,
        country=application.country,
        employment_status=application.employment_status,
        occupation=application.occupation,
        employer_name=application.employer_name,
        employer_address=application.employer_address,
        contract_type=application.contract_type,
        employment_start_date=application.employment_start_date,
        trial_period_end=application.trial_period_end,
        monthly_net_income=application.monthly_net_income,
        other_monthly_income=application.other_monthly_income,
        solvency_score=application.solvency_score,
        reliability_score=100,
        score_breakdown={"solvency": application.score_breakdown or {}},
    )
    db.add(tenant)
    db.flush()
    application.tenant_id = tenant.id
    for document in application.documents:
        document.tenant_id = tenant.id
    for guarantor in application.guarantors:
        guarantor.tenant_id = tenant.id
    if application.monthly_net_income:
        db.add(TenantIncome(
            tenant_id=tenant.id,
            income_type=IncomeType.SALARY,
            label="Revenu principal déclaré lors de la candidature",
            monthly_amount=application.monthly_net_income,
            payer=application.employer_name,
            is_verified=any(
                d.document_type == DocumentType.PAY_SLIP and d.verification_status == VerificationStatus.VERIFIED
                for d in application.documents
            ),
        ))
    return tenant


ALLOWED_TRANSITIONS = {
    ApplicationStatus.DRAFT: {ApplicationStatus.PENDING, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.PENDING: {ApplicationStatus.ACCEPTED, ApplicationStatus.REFUSED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.REFUSED: {ApplicationStatus.PENDING},
    ApplicationStatus.WITHDRAWN: {ApplicationStatus.PENDING},
    ApplicationStatus.ACCEPTED: set(),
}


def transition_application(
    db: Session,
    application: RentalApplication,
    new_status: ApplicationStatus,
    *,
    reason: Optional[str],
    changed_by: str,
    force: bool = False,
) -> RentalApplication:
    old_status = application.status
    if new_status == old_status:
        return application
    if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
        raise ValueError(f"Transition impossible : {old_status.value} → {new_status.value}")
    if new_status == ApplicationStatus.REFUSED and not reason:
        raise ValueError("Un motif de refus est requis")
    completeness = document_completeness(application)
    if new_status == ApplicationStatus.ACCEPTED and not completeness["complete"] and not force:
        missing = ", ".join(f"{kind} ({count})" for kind, count in completeness["missing"].items())
        raise ValueError(f"Dossier incomplet : {missing}. Utilisez force=true pour une dérogation tracée.")

    application.status = new_status
    application.reviewed_at = datetime.now(timezone.utc)
    application.reviewed_by = changed_by
    application.rejection_reason = reason if new_status == ApplicationStatus.REFUSED else None
    db.add(ApplicationStatusHistory(
        application_id=application.id,
        previous_status=old_status,
        new_status=new_status,
        reason=(f"Dérogation : {reason or 'validation manuelle'}" if force and new_status == ApplicationStatus.ACCEPTED else reason),
        changed_by=changed_by,
    ))

    if new_status == ApplicationStatus.ACCEPTED and not application.tenant_id:
        tenant = _copy_application_to_tenant(db, application)
        create_notification(
            db,
            tenant_id=tenant.id,
            application_id=application.id,
            notification_type="application_accepted",
            title="Candidature acceptée",
            content="Votre candidature est acceptée. Vous pouvez maintenant activer votre portail locataire.",
        )
    else:
        label = {
            ApplicationStatus.REFUSED: ("Candidature non retenue", "error"),
            ApplicationStatus.PENDING: ("Candidature remise à l'étude", "info"),
            ApplicationStatus.WITHDRAWN: ("Candidature retirée", "info"),
        }.get(new_status, ("Mise à jour de votre candidature", "info"))
        create_notification(
            db,
            application_id=application.id,
            notification_type=label[1],
            title=label[0],
            content=reason or f"Le statut de votre candidature est maintenant : {new_status.value}.",
        )

    db.commit()
    db.refresh(application)
    return application


def create_tenant(db: Session, data: TenantCreate) -> Tenant:
    nested = {"incomes", "emergency_contacts", "rental_history", "guarantors"}
    tenant = Tenant(reference=generate_reference("TEN"), **data.model_dump(exclude=nested))
    db.add(tenant)
    db.flush()
    from app.models.tenant import EmergencyContact, RentalHistory

    for item in data.incomes:
        db.add(TenantIncome(tenant_id=tenant.id, **item.model_dump()))
    for item in data.emergency_contacts:
        db.add(EmergencyContact(tenant_id=tenant.id, **item.model_dump()))
    for item in data.rental_history:
        db.add(RentalHistory(tenant_id=tenant.id, **item.model_dump()))
    for item in data.guarantors:
        db.add(Guarantor(tenant_id=tenant.id, **item.model_dump()))
    db.commit()
    db.refresh(tenant)
    return tenant


def calculate_reliability_score(db: Session, tenant: Tenant, commit: bool = True) -> Dict:
    payments = db.query(RentPayment).filter(RentPayment.tenant_id == tenant.id).all()
    relevant = [p for p in payments if p.status != PaymentStatus.CANCELLED]
    late = [
        p for p in relevant
        if p.status == PaymentStatus.OVERDUE
        or (p.paid_at and p.paid_at.date() > p.due_date)
        or (p.status not in (PaymentStatus.PAID, PaymentStatus.CANCELLED) and p.due_date < date.today())
    ]
    payment_penalty = min(50.0, (len(late) / max(len(relevant), 1)) * 50)

    unresolved_incidents = db.query(TenantInteraction).filter(
        TenantInteraction.tenant_id == tenant.id,
        TenantInteraction.interaction_type == "complaint_unresolved",
    ).count()
    open_incidents = db.query(TenantIncident).filter(
        TenantIncident.tenant_id == tenant.id,
        TenantIncident.status.in_([IncidentStatus.OPEN, IncidentStatus.IN_PROGRESS]),
    ).count()
    incident_penalty = min(20.0, open_incidents * 4 + unresolved_incidents * 2)

    active_cases = db.query(LegalCase).filter(
        LegalCase.tenant_id == tenant.id,
        LegalCase.status != LegalCaseStatus.CLOSED,
    ).count()
    legal_penalty = min(30.0, active_cases * 20)
    score = round(max(0, 100 - payment_penalty - incident_penalty - legal_penalty), 2)
    breakdown = {
        "payment_history": round(50 - payment_penalty, 2),
        "incident_management": round(20 - incident_penalty, 2),
        "legal_situation": round(30 - legal_penalty, 2),
        "late_payments": len(late),
        "payments_observed": len(relevant),
        "open_incidents": open_incidents,
        "active_legal_cases": active_cases,
        "method_version": "1.0",
    }
    tenant.reliability_score = score
    combined = dict(tenant.score_breakdown or {})
    combined["reliability"] = breakdown
    tenant.score_breakdown = combined
    tenant.score_updated_at = datetime.now(timezone.utc)
    if commit:
        db.commit()
        db.refresh(tenant)
    return {"score": score, "breakdown": breakdown}


def ensure_receipt(db: Session, payment: RentPayment) -> Optional[RentReceipt]:
    if payment.status != PaymentStatus.PAID or payment.amount_paid < payment.amount_due:
        return None
    if payment.receipt:
        return payment.receipt
    receipt = RentReceipt(
        reference=generate_reference("REC"),
        payment_id=payment.id,
        tenant_id=payment.tenant_id,
        lease_id=payment.lease_id,
        period=payment.period,
    )
    db.add(receipt)
    db.flush()
    return receipt


def refresh_late_payment_alerts(db: Session) -> list[TenantAlert]:
    overdue = db.query(RentPayment).filter(
        RentPayment.due_date < date.today(),
        RentPayment.status.in_([PaymentStatus.DUE, PaymentStatus.PARTIAL, PaymentStatus.OVERDUE]),
    ).all()
    touched_tenants = set()
    for payment in overdue:
        payment.status = PaymentStatus.OVERDUE
        alert = db.query(TenantAlert).filter(
            TenantAlert.alert_type == "late_payment",
            TenantAlert.related_entity_id == payment.id,
        ).first()
        days_late = (date.today() - payment.due_date).days
        if not alert:
            alert = TenantAlert(
                tenant_id=payment.tenant_id,
                alert_type="late_payment",
                severity="critical" if days_late >= 30 else "warning",
                title=f"Retard de loyer — {payment.period}",
                content=f"Paiement {payment.reference} en retard de {days_late} jour(s).",
                related_entity_id=payment.id,
            )
            db.add(alert)
            create_notification(
                db,
                tenant_id=payment.tenant_id,
                notification_type="late_payment",
                title="Retard de paiement",
                content=f"Le loyer de la période {payment.period} reste à régulariser.",
            )
        else:
            alert.is_active = True
            alert.severity = "critical" if days_late >= 30 else "warning"
            alert.content = f"Paiement {payment.reference} en retard de {days_late} jour(s)."
        touched_tenants.add(payment.tenant_id)

    # Désactiver les alertes dont le paiement a depuis été soldé.
    active_alerts = db.query(TenantAlert).filter(TenantAlert.alert_type == "late_payment", TenantAlert.is_active == True).all()
    for alert in active_alerts:
        payment = db.query(RentPayment).filter(RentPayment.id == alert.related_entity_id).first()
        if not payment or payment.status in (PaymentStatus.PAID, PaymentStatus.CANCELLED):
            alert.is_active = False
            touched_tenants.add(alert.tenant_id)

    db.flush()
    for tenant_id in touched_tenants:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant:
            calculate_reliability_score(db, tenant, commit=False)
    db.commit()
    return db.query(TenantAlert).filter(TenantAlert.alert_type == "late_payment", TenantAlert.is_active == True).all()


def search_tenants(db: Session, search: Optional[str], status: Optional[str], skip: int, limit: int):
    query = db.query(Tenant).filter(Tenant.is_active == True)
    if search:
        term = f"%{search}%"
        query = query.filter(or_(
            Tenant.reference.ilike(term), Tenant.first_name.ilike(term), Tenant.last_name.ilike(term),
            Tenant.email.ilike(term), Tenant.city.ilike(term),
        ))
    if status:
        query = query.filter(Tenant.status == status)
    total = query.count()
    return query.order_by(Tenant.last_name, Tenant.first_name).offset(skip).limit(limit).all(), total
