"""Services du module 16.

Les estimateurs fonctionnent sans service opaque externe : ils utilisent les
comparables locaux, une régression ridge légère lorsque l'échantillon le permet
et des règles explicables pour les risques. Cela rend chaque résultat
reproductible et auditable.
"""

from __future__ import annotations

import math
import re
import statistics
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Iterable, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.ai_automation import (
    AIModelSnapshot,
    AIPrediction,
    AssistantAppointment,
    WorkflowExecution,
    AutomationWorkflow,
    ChatMessage,
    ChatSession,
    IntelligentOCRJob,
    MarketObservation,
    MarketPriceIndex,
)
from app.models.finance import BankStatement, BankStatementLine, LatePayment
from app.models.maintenance import (
    MaintenanceTicket,
    TicketCategory,
    TicketSource,
    TicketStatus,
    TicketUrgency,
)
from app.models.property import Property, PropertyHistory, PropertyStatus
from app.models.tenant import Lease, LeaseStatus, PaymentStatus, RentPayment, Tenant, TenantNotification
from app.services import maintenance_service


DISCLAIMER = (
    "Aide à la décision fondée sur les données disponibles ; une validation "
    "humaine reste requise et aucune décision contractuelle ne doit être prise automatiquement."
)
ALLOWED_ACTIONS = {
    "create_notification",
    "create_maintenance_ticket",
    "update_property_status",
    "emit_webhook",
    "create_task",
}
ALLOWED_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "exists"}


def utcnow() -> datetime:
    return datetime.utcnow()


def reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def model_view(row) -> dict:
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        if hasattr(value, "value"):
            value = value.value
        result[column.name] = value
    return result


def prediction_view(row: AIPrediction) -> dict:
    data = model_view(row)
    data["disclaimer"] = DISCLAIMER
    return data


def _property_values(db: Session, data) -> dict:
    prop = None
    if data.property_id:
        prop = db.query(Property).filter(Property.id == data.property_id, Property.is_active == True).first()  # noqa: E712
        if not prop:
            raise ValueError("Bien introuvable")
    values = {
        "property_id": prop.id if prop else None,
        "property_type": (prop.type.value if prop and hasattr(prop.type, "value") else prop.type) if prop else data.property_type,
        "city": prop.city if prop else data.city,
        "postal_code": prop.postal_code if prop else data.postal_code,
        "living_area": prop.living_area if prop else data.living_area,
        "rooms": prop.rooms if prop else data.rooms,
        "bedrooms": prop.bedrooms if prop else data.bedrooms,
        "energy_class": (prop.energy_class.value if prop and prop.energy_class else None) if prop else data.energy_class,
        "equipment": (prop.equipment or {}) if prop else (data.equipment or {}),
    }
    if not values["living_area"] or values["living_area"] <= 0:
        raise ValueError("La surface habitable est requise pour cette estimation")
    return values


def _median(values: Iterable[float], default: float = 0) -> float:
    sequence = [float(value) for value in values if value is not None]
    return float(statistics.median(sequence)) if sequence else default


def _solve_linear_system(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Gauss-Jordan avec pivot partiel, suffisant pour nos trois variables."""
    n = len(vector)
    augmented = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-10:
            raise ValueError("Matrice de comparaison singulière")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][index] - factor * augmented[column][index]
                for index in range(n + 1)
            ]
    return [augmented[index][-1] for index in range(n)]


def _ridge_predict(samples: list[dict], target: dict) -> tuple[float, dict, dict]:
    """Régression ridge sur surface et nombre de pièces, avec standardisation."""
    areas = [sample["area"] for sample in samples]
    rooms = [sample.get("rooms") or 0 for sample in samples]
    area_mean, room_mean = statistics.mean(areas), statistics.mean(rooms)
    area_std = statistics.pstdev(areas) or 1.0
    room_std = statistics.pstdev(rooms) or 1.0
    rows = [
        [1.0, (sample["area"] - area_mean) / area_std, ((sample.get("rooms") or 0) - room_mean) / room_std]
        for sample in samples
    ]
    y = [sample["price"] for sample in samples]
    size = 3
    xtx = [[sum(row[i] * row[j] for row in rows) for j in range(size)] for i in range(size)]
    # Régularisation des coefficients, jamais de l'interception.
    for index in range(1, size):
        xtx[index][index] += 1.5
    xty = [sum(row[i] * value for row, value in zip(rows, y)) for i in range(size)]
    coefficients = _solve_linear_system(xtx, xty)
    target_row = [
        1.0,
        (target["living_area"] - area_mean) / area_std,
        ((target.get("rooms") or 0) - room_mean) / room_std,
    ]
    predicted = sum(coefficient * value for coefficient, value in zip(coefficients, target_row))
    fitted = [sum(coefficient * value for coefficient, value in zip(coefficients, row)) for row in rows]
    mae = statistics.mean(abs(actual - estimate) for actual, estimate in zip(y, fitted))
    metrics = {"mae": round(mae, 2), "mean_price": round(statistics.mean(y), 2)}
    parameters = {
        "coefficients": [round(item, 6) for item in coefficients],
        "area_mean": round(area_mean, 4),
        "area_std": round(area_std, 4),
        "rooms_mean": round(room_mean, 4),
        "rooms_std": round(room_std, 4),
        "ridge_alpha": 1.5,
    }
    return predicted, parameters, metrics


def _property_comparables(db: Session, values: dict, price_field: str, listing_type: str, include_market: bool) -> list[dict]:
    column = Property.rent_price if price_field == "rent_price" else Property.sale_price
    query = db.query(Property).filter(
        Property.is_active == True,  # noqa: E712
        column.isnot(None),
        column > 0,
        Property.living_area.isnot(None),
        Property.living_area > 0,
    )
    if values.get("property_id"):
        query = query.filter(Property.id != values["property_id"])
    properties = query.all()

    def property_score(prop: Property) -> float:
        score = 0.0
        if (prop.city or "").casefold() == (values.get("city") or "").casefold():
            score += 5
        if values.get("postal_code") and prop.postal_code == values["postal_code"]:
            score += 3
        prop_type = prop.type.value if hasattr(prop.type, "value") else prop.type
        if prop_type == values.get("property_type"):
            score += 3
        ratio = abs((prop.living_area or 0) - values["living_area"]) / values["living_area"]
        score += max(0, 3 - ratio * 5)
        if values.get("rooms") is not None and prop.rooms is not None:
            score += max(0, 2 - abs(prop.rooms - values["rooms"]) * 0.5)
        return score

    comparable_rows = []
    for prop in properties:
        score = property_score(prop)
        if score < 3:
            continue
        price = getattr(prop, price_field)
        comparable_rows.append({
            "source": "portfolio",
            "id": prop.id,
            "reference": prop.reference,
            "city": prop.city,
            "postal_code": prop.postal_code,
            "property_type": prop.type.value if hasattr(prop.type, "value") else prop.type,
            "area": float(prop.living_area),
            "rooms": prop.rooms,
            "price": float(price),
            "price_per_sqm": round(float(price) / float(prop.living_area), 2),
            "similarity": round(score, 2),
        })
    if include_market:
        observations = db.query(MarketObservation).filter(
            MarketObservation.listing_type == listing_type,
            MarketObservation.is_active == True,  # noqa: E712
            MarketObservation.area > 0,
            MarketObservation.price > 0,
        ).all()
        for observation in observations:
            score = 0.0
            if observation.city.casefold() == (values.get("city") or "").casefold():
                score += 5
            if values.get("postal_code") and observation.postal_code == values["postal_code"]:
                score += 3
            if observation.property_type == values.get("property_type"):
                score += 3
            ratio = abs(observation.area - values["living_area"]) / values["living_area"]
            score += max(0, 3 - ratio * 5)
            if score >= 3:
                comparable_rows.append({
                    "source": observation.source,
                    "id": observation.id,
                    "reference": observation.external_reference,
                    "city": observation.city,
                    "postal_code": observation.postal_code,
                    "property_type": observation.property_type,
                    "area": float(observation.area),
                    "rooms": observation.rooms,
                    "price": float(observation.price),
                    "price_per_sqm": round(float(observation.price) / float(observation.area), 2),
                    "similarity": round(score, 2),
                })
    comparable_rows.sort(key=lambda item: (-item["similarity"], abs(item["area"] - values["living_area"])))
    return comparable_rows[:30]


def estimate_property_price(db: Session, data, prediction_type: str, actor: str) -> AIPrediction:
    is_rent = prediction_type == "rent_estimate"
    values = _property_values(db, data)
    comparables = _property_comparables(
        db,
        values,
        "rent_price" if is_rent else "sale_price",
        "rent" if is_rent else "sale",
        data.include_market_observations,
    )
    if not comparables:
        raise ValueError("Pas assez de données comparables pour produire une estimation fiable")

    method = "weighted_comparables"
    parameters: dict = {}
    metrics: dict = {}
    if len(comparables) >= 5:
        try:
            estimate, parameters, metrics = _ridge_predict(comparables, values)
            method = "ridge_regression"
        except ValueError:
            estimate = _median(item["price_per_sqm"] for item in comparables) * values["living_area"]
    else:
        weighted_total = sum(item["price_per_sqm"] * item["similarity"] for item in comparables)
        estimate = values["living_area"] * weighted_total / sum(item["similarity"] for item in comparables)

    prices_per_sqm = [item["price_per_sqm"] for item in comparables]
    median_sqm = _median(prices_per_sqm)
    # Un petit échantillon ne doit pas autoriser l'extrapolation de la régression.
    floor, ceiling = median_sqm * values["living_area"] * 0.65, median_sqm * values["living_area"] * 1.35
    estimate = max(floor, min(ceiling, estimate))
    spread = statistics.pstdev(prices_per_sqm) / max(statistics.mean(prices_per_sqm), 1) if len(prices_per_sqm) > 1 else 0.35
    confidence = max(25.0, min(95.0, 45 + min(len(comparables), 20) * 2.5 - spread * 35))
    uncertainty = max(0.06, min(0.30, 0.32 - confidence / 400))
    lower, upper = estimate * (1 - uncertainty), estimate * (1 + uncertainty)
    currency_rounding = 10 if is_rent else 1000
    rounded = round(estimate / currency_rounding) * currency_rounding
    lower = round(lower / currency_rounding) * currency_rounding
    upper = round(upper / currency_rounding) * currency_rounding

    snapshot = AIModelSnapshot(
        model_type=prediction_type,
        version=f"{method}-2026.1",
        algorithm=method,
        sample_count=len(comparables),
        features=["living_area", "rooms", "locality", "property_type"],
        parameters=parameters,
        metrics={**metrics, "price_per_sqm_dispersion": round(spread, 4)},
        training_scope={"city": values.get("city"), "postal_code": values.get("postal_code")},
    )
    db.add(snapshot)
    db.flush()
    label = "estimated_monthly_rent" if is_rent else "recommended_sale_price"
    prediction = AIPrediction(
        prediction_type=prediction_type,
        entity_type="property",
        entity_id=values.get("property_id"),
        model_id=snapshot.id,
        input_data=values,
        result={
            label: rounded,
            "range": {"low": lower, "high": upper},
            "currency": "EUR",
            "median_price_per_sqm": round(median_sqm, 2),
            "comparable_count": len(comparables),
            "comparables": comparables[:10],
        },
        confidence=round(confidence, 2),
        risk_level="low" if confidence >= 75 else "medium" if confidence >= 50 else "high",
        explanation={
            "method": method,
            "factors": ["surface", "nombre de pièces", "localisation", "type de bien"],
            "limitations": ["qualité et volume des comparables", "évolution du marché après la date d'observation"],
        },
        requested_by=actor,
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    return prediction


def predict_vacancy(db: Session, property_id: int, horizon_days: int, actor: str) -> AIPrediction:
    prop = db.query(Property).filter(Property.id == property_id, Property.is_active == True).first()  # noqa: E712
    if not prop:
        raise ValueError("Bien introuvable")
    score = 20.0
    factors = []
    if prop.status == PropertyStatus.AVAILABLE:
        score += 35
        factors.append({"factor": "currently_available", "impact": 35})
    elif prop.status == PropertyStatus.RENTED:
        score -= 12
        factors.append({"factor": "currently_rented", "impact": -12})
    active_lease = db.query(Lease).filter(Lease.property_id == prop.id, Lease.status == LeaseStatus.ACTIVE).order_by(Lease.end_date).first()
    horizon = date.today() + timedelta(days=horizon_days)
    if not active_lease:
        score += 20
        factors.append({"factor": "no_active_lease", "impact": 20})
    elif active_lease.end_date and active_lease.end_date <= horizon:
        score += 25
        factors.append({"factor": "lease_ends_in_horizon", "impact": 25, "end_date": active_lease.end_date.isoformat()})
    else:
        score -= 15
        factors.append({"factor": "lease_continues_beyond_horizon", "impact": -15})

    city_rents = db.query(Property).filter(
        func.lower(Property.city) == (prop.city or "").lower(),
        Property.rent_price.isnot(None),
        Property.rent_price > 0,
        Property.living_area.isnot(None),
        Property.living_area > 0,
    ).all()
    market_sqm = _median(item.rent_price / item.living_area for item in city_rents)
    property_sqm = (prop.rent_price / prop.living_area) if prop.rent_price and prop.living_area else None
    if property_sqm and market_sqm:
        premium = (property_sqm / market_sqm - 1) * 100
        if premium > 15:
            impact = min(18, premium * 0.45)
            score += impact
            factors.append({"factor": "rent_above_local_median", "impact": round(impact, 2), "premium_percent": round(premium, 2)})
        elif premium < -10:
            score -= 6
            factors.append({"factor": "competitive_rent", "impact": -6})
    history_count = db.query(PropertyHistory).filter(
        PropertyHistory.property_id == prop.id,
        PropertyHistory.event_type.in_(["vacancy", "tenant_change"]),
    ).count()
    if history_count >= 2:
        impact = min(15, history_count * 3)
        score += impact
        factors.append({"factor": "turnover_history", "impact": impact, "events": history_count})
    probability = round(max(3, min(97, score)), 2)
    level = "high" if probability >= 65 else "medium" if probability >= 35 else "low"
    prediction = AIPrediction(
        prediction_type="vacancy_risk",
        entity_type="property",
        entity_id=prop.id,
        input_data={"property_id": prop.id, "horizon_days": horizon_days},
        result={"vacancy_probability_percent": probability, "horizon_days": horizon_days},
        confidence=round(min(90, 45 + len(factors) * 8 + min(len(city_rents), 10)), 2),
        risk_level=level,
        explanation={"method": "explainable_dynamic_scoring", "factors": factors, "limitations": ["absence de données externes de demande locale"]},
        requested_by=actor,
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    return prediction


def predict_payment_risk(db: Session, tenant_id: int, horizon_days: int, actor: str) -> AIPrediction:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id, Tenant.is_active == True).first()  # noqa: E712
    if not tenant:
        raise ValueError("Locataire introuvable")
    payments = db.query(RentPayment).filter(RentPayment.tenant_id == tenant.id).order_by(RentPayment.due_date.desc()).limit(24).all()
    late_cases = db.query(LatePayment).filter(LatePayment.tenant_id == tenant.id).all()
    total = len(payments)
    overdue = sum(payment.status in {PaymentStatus.OVERDUE, PaymentStatus.PARTIAL} for payment in payments)
    unpaid_amount = sum(max(0, (payment.amount_due or 0) - (payment.amount_paid or 0)) for payment in payments)
    average_rent = statistics.mean([payment.amount_due for payment in payments]) if payments else 0
    active_lease = db.query(Lease).filter(Lease.tenant_id == tenant.id, Lease.status == LeaseStatus.ACTIVE).first()
    rent = active_lease.monthly_rent if active_lease else average_rent
    income = (tenant.monthly_net_income or 0) + (tenant.other_monthly_income or 0)
    score = 8.0
    factors = []
    if total:
        late_rate = overdue / total
        impact = late_rate * 58
        score += impact
        factors.append({"factor": "late_payment_rate", "value": round(late_rate, 3), "impact": round(impact, 2)})
    else:
        score += 12
        factors.append({"factor": "no_payment_history", "impact": 12})
    if average_rent:
        arrears_months = unpaid_amount / average_rent
        impact = min(28, arrears_months * 14)
        score += impact
        factors.append({"factor": "outstanding_balance", "amount": round(unpaid_amount, 2), "impact": round(impact, 2)})
    open_cases = sum(case.status != "resolved" for case in late_cases)
    if open_cases:
        impact = min(20, open_cases * 6)
        score += impact
        factors.append({"factor": "open_late_payment_cases", "value": open_cases, "impact": impact})
    if income and rent:
        effort = rent / income
        if effort > 0.40:
            impact = min(18, (effort - 0.40) * 80)
            score += impact
            factors.append({"factor": "rent_to_income", "value": round(effort, 3), "impact": round(impact, 2)})
        elif effort <= 0.33:
            score -= 5
            factors.append({"factor": "affordable_rent_ratio", "value": round(effort, 3), "impact": -5})
    reliability = tenant.reliability_score if tenant.reliability_score is not None else 50
    score += max(-8, min(18, (70 - reliability) * 0.3))
    probability = round(max(2, min(98, score)), 2)
    level = "high" if probability >= 65 else "medium" if probability >= 35 else "low"
    prediction = AIPrediction(
        prediction_type="payment_default_risk",
        entity_type="tenant",
        entity_id=tenant.id,
        input_data={"tenant_id": tenant.id, "horizon_days": horizon_days, "payment_history_count": total},
        result={"default_probability_percent": probability, "horizon_days": horizon_days, "outstanding_amount": round(unpaid_amount, 2)},
        confidence=round(min(94, 40 + min(total, 18) * 3), 2),
        risk_level=level,
        explanation={
            "method": "dynamic_behavioral_scoring",
            "factors": factors,
            "protected_attributes_used": [],
            "limitations": ["score non contractuel", "historique interne uniquement"],
        },
        requested_by=actor,
    )
    db.add(prediction)
    db.commit()
    db.refresh(prediction)
    return prediction


def detect_financial_anomalies(db: Session, data, actor: str) -> AIPrediction:
    query = db.query(BankStatementLine).join(BankStatement)
    if data.bank_account_id:
        query = query.filter(BankStatement.bank_account_id == data.bank_account_id)
    if data.date_from:
        query = query.filter(BankStatementLine.transaction_date >= data.date_from)
    if data.date_to:
        query = query.filter(BankStatementLine.transaction_date <= data.date_to)
    lines = query.order_by(BankStatementLine.transaction_date).all()
    amounts = [abs(float(line.amount)) for line in lines]
    median_amount = _median(amounts)
    deviations = [abs(value - median_amount) for value in amounts]
    mad = _median(deviations)
    references: dict[str, int] = {}
    for line in lines:
        if line.reference:
            references[line.reference] = references.get(line.reference, 0) + 1
    anomalies = []
    for line, amount in zip(lines, amounts):
        reasons = []
        robust_z = 0.6745 * abs(amount - median_amount) / mad if mad else 0
        if len(lines) >= 5 and robust_z >= data.sensitivity:
            reasons.append({"code": "unusual_amount", "robust_z_score": round(robust_z, 2)})
        if line.reference and references.get(line.reference, 0) > 1:
            reasons.append({"code": "duplicate_reference", "reference": line.reference})
        if not line.label or len(line.label.strip()) < 3:
            reasons.append({"code": "missing_or_short_label"})
        if reasons:
            anomalies.append({
                "line_id": line.id,
                "transaction_date": line.transaction_date.isoformat(),
                "amount": line.amount,
                "label": line.label,
                "severity": "high" if robust_z >= data.sensitivity * 1.5 or any(item["code"] == "duplicate_reference" for item in reasons) else "medium",
                "reasons": reasons,
            })
    confidence = min(95, 35 + len(lines) * 2) if lines else 0
    prediction = AIPrediction(
        prediction_type="financial_anomaly_detection",
        entity_type="bank_account" if data.bank_account_id else "portfolio",
        entity_id=data.bank_account_id,
        input_data=data.model_dump(mode="json"),
        result={"analysed_lines": len(lines), "anomaly_count": len(anomalies), "anomalies": anomalies, "median_absolute_amount": round(median_amount, 2)},
        confidence=round(confidence, 2),
        risk_level="high" if any(item["severity"] == "high" for item in anomalies) else "medium" if anomalies else "low",
        explanation={"method": "median_absolute_deviation_and_duplicate_rules", "sensitivity": data.sensitivity},
        requested_by=actor,
    )
    if data.persist:
        db.add(prediction)
        db.commit()
        db.refresh(prediction)
    return prediction


# ---------------------------------------------------------------------------
# Chatbot et assistant gestionnaire
# ---------------------------------------------------------------------------
FAQS = [
    ({"quittance", "reçu", "receipt"}, "Vos quittances sont disponibles dans Portail locataire > Paiements > Quittances."),
    ({"payer", "paiement", "loyer"}, "Vous pouvez consulter vos échéances et régler un loyer depuis la rubrique Paiements de votre portail."),
    ({"assurance", "attestation"}, "Déposez votre attestation d'assurance dans Documents. Elle sera contrôlée puis rattachée à votre logement."),
    ({"préavis", "congé", "quitter"}, "La durée du préavis dépend du bail et de votre situation. Utilisez la rubrique Bail pour préparer une demande, puis faites-la valider."),
    ({"urgence", "fuite", "panne"}, "En cas de danger immédiat, contactez les secours. Pour le logement, créez un ticket en indiquant le bien, la pièce et des photos."),
    ({"rendez-vous", "rdv", "visite"}, "Je peux préparer une demande de rendez-vous. Indiquez la date, le motif et le bien concerné."),
]


def create_chat_session(db: Session, actor_type: str, actor_id: int, locale: str, context: dict) -> ChatSession:
    row = ChatSession(
        public_id=uuid.uuid4().hex,
        actor_type=actor_type,
        tenant_id=actor_id if actor_type == "tenant" else None,
        user_id=actor_id if actor_type == "manager" else None,
        locale=locale,
        context=context,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_chat_session(db: Session, public_id: str, actor_type: str, actor_id: int) -> ChatSession:
    query = db.query(ChatSession).filter(ChatSession.public_id == public_id, ChatSession.actor_type == actor_type)
    query = query.filter(ChatSession.tenant_id == actor_id) if actor_type == "tenant" else query.filter(ChatSession.user_id == actor_id)
    row = query.first()
    if not row:
        raise ValueError("Session de conversation introuvable")
    return row


def _normalize_words(message: str) -> set[str]:
    return set(re.findall(r"[a-zà-ÿ0-9]+", (message or "").casefold()))


def answer_chat(db: Session, session: ChatSession, message: str, context: dict) -> dict:
    db.add(ChatMessage(session_id=session.id, role="user", content=message, metadata_json=context))
    words = _normalize_words(message)
    intent, confidence = "fallback", 0.35
    suggestions = ["Consulter mes paiements", "Créer un ticket", "Prendre rendez-vous"]
    action = None
    answer = "Je n'ai pas assez d'informations pour répondre avec certitude. Reformulez votre demande ou contactez votre gestionnaire."

    if session.actor_type == "tenant" and words & {"ticket", "demande", "intervention", "réparation", "reparation"}:
        intent, confidence = "maintenance_ticket", 0.88
        tickets = db.query(MaintenanceTicket).filter(MaintenanceTicket.tenant_id == session.tenant_id).order_by(MaintenanceTicket.created_at.desc()).limit(3).all()
        if words & {"suivi", "statut", "où", "avancement"} and tickets:
            latest = tickets[0]
            status = latest.status.value if hasattr(latest.status, "value") else latest.status
            answer = f"Votre dernière demande {latest.reference} est au statut « {status} » : {latest.title}."
        else:
            answer = "Je peux préparer un ticket. Précisez le bien, le problème, la pièce et le niveau d'urgence ; la création devra être confirmée."
            action = {"type": "create_ticket", "requires_confirmation": True, "required_fields": ["property_id", "title", "description", "urgency"]}
    elif session.actor_type == "tenant" and words & {"impayé", "impaye", "échéance", "echeance", "paiement", "payer"}:
        intent, confidence = "payment_status", 0.92
        payment = db.query(RentPayment).filter(RentPayment.tenant_id == session.tenant_id).order_by(RentPayment.due_date.desc()).first()
        if payment:
            remaining = max(0, (payment.amount_due or 0) - (payment.amount_paid or 0))
            answer = f"L'échéance {payment.period} est au statut « {payment.status.value} ». Solde restant : {remaining:.2f} EUR."
        else:
            answer = "Aucune échéance n'est encore enregistrée dans votre dossier."
    else:
        best = None
        for keywords, response in FAQS:
            overlap = len(words & keywords)
            if overlap and (best is None or overlap > best[0]):
                best = (overlap, response)
        if best:
            intent, confidence, answer = "faq", min(0.95, 0.65 + best[0] * 0.12), best[1]
        elif session.actor_type == "manager":
            intent, confidence = "manager_help", 0.60
            answer = "Je peux rechercher un bien, un locataire, un bail ou un ticket, et préparer une action rapide soumise à confirmation."
            suggestions = ["Rechercher", "Créer un ticket", "Déclencher un workflow"]

    assistant = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=answer,
        intent=intent,
        confidence=confidence,
        metadata_json={"suggestions": suggestions, "action": action},
    )
    db.add(assistant)
    session.last_activity_at = utcnow()
    db.commit()
    db.refresh(assistant)
    return {
        "message_id": assistant.id,
        "answer": answer,
        "intent": intent,
        "confidence": confidence,
        "suggestions": suggestions,
        "proposed_action": action,
        "available_24_7": True,
        "automated_response": True,
    }


def create_appointment(db: Session, data, tenant_id: Optional[int], session_id: Optional[int]) -> AssistantAppointment:
    if data.property_id and not db.query(Property).filter(Property.id == data.property_id).first():
        raise ValueError("Bien introuvable")
    if data.starts_at.replace(tzinfo=None) <= utcnow():
        raise ValueError("Le rendez-vous doit être planifié dans le futur")
    conflict_query = db.query(AssistantAppointment).filter(
        AssistantAppointment.starts_at == data.starts_at,
        AssistantAppointment.status.in_(["requested", "confirmed"]),
    )
    if data.property_id:
        conflict_query = conflict_query.filter(AssistantAppointment.property_id == data.property_id)
    if conflict_query.first():
        raise ValueError("Ce créneau est déjà réservé")
    row = AssistantAppointment(
        reference=reference("RDV"), tenant_id=tenant_id, session_id=session_id,
        **data.model_dump(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def manager_search(db: Session, query: str, entity_types: list[str], limit: int) -> list[dict]:
    needle = f"%{query}%"
    results = []
    if "property" in entity_types:
        rows = db.query(Property).filter(or_(Property.reference.ilike(needle), Property.title.ilike(needle), Property.address.ilike(needle), Property.city.ilike(needle))).limit(limit).all()
        results.extend({"type": "property", "id": row.id, "reference": row.reference, "label": row.title, "detail": f"{row.address}, {row.city}"} for row in rows)
    if "tenant" in entity_types:
        rows = db.query(Tenant).filter(or_(Tenant.reference.ilike(needle), Tenant.first_name.ilike(needle), Tenant.last_name.ilike(needle), Tenant.email.ilike(needle))).limit(limit).all()
        results.extend({"type": "tenant", "id": row.id, "reference": row.reference, "label": f"{row.first_name} {row.last_name}", "detail": row.email} for row in rows)
    if "lease" in entity_types:
        rows = db.query(Lease).filter(Lease.reference.ilike(needle)).limit(limit).all()
        results.extend({"type": "lease", "id": row.id, "reference": row.reference, "label": row.reference, "detail": f"Bien {row.property_id} · Locataire {row.tenant_id}"} for row in rows)
    if "ticket" in entity_types:
        rows = db.query(MaintenanceTicket).filter(or_(MaintenanceTicket.reference.ilike(needle), MaintenanceTicket.title.ilike(needle), MaintenanceTicket.description.ilike(needle))).limit(limit).all()
        results.extend({"type": "ticket", "id": row.id, "reference": row.reference, "label": row.title, "detail": row.status.value} for row in rows)
    return results[:limit]


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------
def validate_workflow(conditions: list[dict], actions: list[dict]) -> None:
    for condition in conditions:
        if not isinstance(condition, dict) or not condition.get("field"):
            raise ValueError("Chaque condition doit définir un champ")
        if condition.get("operator", "eq") not in ALLOWED_OPERATORS:
            raise ValueError(f"Opérateur non autorisé : {condition.get('operator')}")
    for action in actions:
        if not isinstance(action, dict) or action.get("type") not in ALLOWED_ACTIONS:
            raise ValueError(f"Action non autorisée : {action.get('type') if isinstance(action, dict) else action}")


def _path(payload: dict, key: str) -> Any:
    value: Any = payload
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _matches(payload: dict, conditions: list[dict]) -> bool:
    for condition in conditions:
        actual = _path(payload, condition["field"])
        expected = condition.get("value")
        operator = condition.get("operator", "eq")
        try:
            if operator == "eq":
                passed = actual == expected
            elif operator == "ne":
                passed = actual != expected
            elif operator == "gt":
                passed = actual is not None and actual > expected
            elif operator == "gte":
                passed = actual is not None and actual >= expected
            elif operator == "lt":
                passed = actual is not None and actual < expected
            elif operator == "lte":
                passed = actual is not None and actual <= expected
            elif operator == "in":
                passed = expected is not None and actual in expected
            elif operator == "contains":
                passed = actual is not None and expected in actual
            else:  # exists
                passed = (actual is not None) == bool(expected if expected is not None else True)
        except (TypeError, ValueError):
            passed = False
        if not passed:
            return False
    return True


def _render(value: Any, payload: dict) -> Any:
    if isinstance(value, str):
        exact = re.fullmatch(r"\$\{event\.([a-zA-Z0-9_.-]+)\}", value)
        if exact:
            return _path(payload, exact.group(1))
        return re.sub(
            r"\$\{event\.([a-zA-Z0-9_.-]+)\}",
            lambda match: str(_path(payload, match.group(1)) or ""),
            value,
        )
    if isinstance(value, dict):
        return {key: _render(item, payload) for key, item in value.items()}
    if isinstance(value, list):
        return [_render(item, payload) for item in value]
    return value


def _execute_action(db: Session, action: dict, payload: dict, actor: str) -> dict:
    kind = action["type"]
    parameters = _render(action.get("parameters") or {}, payload)
    if kind == "create_notification":
        tenant_id = parameters.get("tenant_id")
        if not tenant_id:
            raise ValueError("create_notification requiert tenant_id")
        row = TenantNotification(
            tenant_id=int(tenant_id), channel=parameters.get("channel", "in_app"),
            notification_type=parameters.get("notification_type", "automation"),
            title=parameters.get("title", "Notification automatique"),
            content=parameters.get("content", "Une règle métier a été déclenchée."),
        )
        db.add(row)
        db.flush()
        return {"type": kind, "status": "completed", "notification_id": row.id}
    if kind == "create_maintenance_ticket":
        try:
            data = SimpleNamespace(
                property_id=int(parameters["property_id"]),
                tenant_id=int(parameters["tenant_id"]) if parameters.get("tenant_id") else None,
                owner_id=int(parameters["owner_id"]) if parameters.get("owner_id") else None,
                lease_id=int(parameters["lease_id"]) if parameters.get("lease_id") else None,
                source=TicketSource.AUTOMATIC,
                category=TicketCategory(parameters.get("category", "autre")),
                urgency=TicketUrgency(parameters.get("urgency", "moyen")),
                title=parameters.get("title", "Action automatique"),
                description=parameters.get("description"), location=parameters.get("location"),
                provider_id=None, estimated_cost=0,
            )
            ticket = maintenance_service.create_ticket(db, data, created_by=actor)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Ticket automatique invalide : {exc}") from exc
        return {"type": kind, "status": "completed", "ticket_id": ticket.id, "reference": ticket.reference}
    if kind == "update_property_status":
        prop = db.query(Property).filter(Property.id == int(parameters.get("property_id", 0))).first()
        if not prop:
            raise ValueError("Bien à mettre à jour introuvable")
        prop.status = PropertyStatus(parameters["status"])
        db.flush()
        return {"type": kind, "status": "completed", "property_id": prop.id, "new_status": prop.status.value}
    if kind == "emit_webhook":
        from app.services.integration_service import create_webhook_event

        event = create_webhook_event(
            db,
            parameters.get("event_type", "automation.completed"),
            parameters.get("data", payload),
            idempotency_key=parameters.get("idempotency_key"),
            deliver_now=False,
        )
        return {"type": kind, "status": "queued", "event_id": event.event_id}
    # create_task est un journal de tâche durable dans action_results du run.
    return {
        "type": kind,
        "status": "completed",
        "task": {
            "title": parameters.get("title", "Tâche automatique"),
            "assignee": parameters.get("assignee"),
            "due_at": parameters.get("due_at"),
        },
    }


def execute_event(db: Session, event_type: str, payload: dict, idempotency_key: str, actor: str, dry_run: bool = False) -> dict:
    workflows = db.query(AutomationWorkflow).filter(
        AutomationWorkflow.event_type == event_type,
        AutomationWorkflow.is_active == True,  # noqa: E712
    ).order_by(AutomationWorkflow.priority, AutomationWorkflow.id).all()
    output = []
    for workflow in workflows:
        matched = _matches(payload, workflow.conditions or [])
        if dry_run:
            output.append({"workflow_id": workflow.id, "workflow_name": workflow.name, "matched": matched, "actions": workflow.actions if matched else []})
            continue
        existing = db.query(WorkflowExecution).filter(
            WorkflowExecution.workflow_id == workflow.id,
            WorkflowExecution.idempotency_key == idempotency_key,
        ).first()
        if existing:
            output.append({"workflow_id": workflow.id, "run_id": existing.id, "duplicate": True, "status": existing.status})
            continue
        run = WorkflowExecution(
            workflow_id=workflow.id, event_type=event_type,
            idempotency_key=idempotency_key, event_payload=payload,
            matched=matched, status="running" if matched else "skipped",
        )
        db.add(run)
        db.flush()
        results = []
        error = None
        if matched:
            for action in workflow.actions or []:
                try:
                    results.append(_execute_action(db, action, payload, actor))
                except Exception as exc:  # résultat journalisé, jamais masqué
                    results.append({"type": action.get("type"), "status": "failed", "error": str(exc)})
                    error = str(exc)
                    if workflow.stop_on_error:
                        break
        run.action_results = results
        run.error = error
        run.status = "failed" if error else "completed" if matched else "skipped"
        run.completed_at = utcnow()
        workflow.execution_count = (workflow.execution_count or 0) + (1 if matched else 0)
        workflow.last_run_at = utcnow() if matched else workflow.last_run_at
        db.commit()
        output.append({"workflow_id": workflow.id, "run_id": run.id, "matched": matched, "status": run.status, "action_results": results})
    return {"event_type": event_type, "idempotency_key": idempotency_key, "dry_run": dry_run, "workflow_count": len(workflows), "runs": output}


# ---------------------------------------------------------------------------
# OCR et marché
# ---------------------------------------------------------------------------
def analyse_ged_document(db: Session, document, expected_type: Optional[str], actor: str) -> IntelligentOCRJob:
    text = document.ocr_text or ""
    normalized = text.casefold()
    aliases = {"invoice": "facture", "lease": "bail"}
    normalized_expected = aliases.get(expected_type, expected_type)
    detected = aliases.get(document.classification, document.classification) or aliases.get(document.document_type, document.document_type) or "other"
    extracted = dict(document.extracted_data or {})
    checks = {
        "text_extracted": len(normalized.strip()) >= 20,
        "expected_type_matches": normalized_expected is None or normalized_expected == detected or document.document_type == normalized_expected,
    }
    if detected == "facture" or normalized_expected == "facture":
        amounts = re.findall(r"(?:total\s*(?:ttc)?\s*[:\-]?\s*)(\d[\d\s]*(?:[.,]\d{2})?)", text, re.I)
        invoice_numbers = re.findall(r"(?:facture|invoice)\s*(?:n[°o]|num[eé]ro)?\s*[:#-]?\s*([A-Z0-9/_-]{3,})", text, re.I)
        siret = re.findall(r"\b\d{14}\b", text.replace(" ", ""))
        if amounts:
            extracted["total_ttc"] = amounts[0].replace(" ", "").replace(",", ".")
        if invoice_numbers:
            extracted["invoice_number"] = invoice_numbers[0]
        if siret:
            extracted["siret"] = siret[0]
        checks["invoice_amount_found"] = bool(amounts or extracted.get("montants"))
        checks["invoice_reference_found"] = bool(invoice_numbers)
        detected = "facture"
    elif detected == "bail" or normalized_expected == "bail":
        rents = re.findall(r"loyer[^\d]{0,30}(\d[\d\s]*(?:[.,]\d{2})?)\s*(?:€|euros?)", text, re.I)
        if rents:
            extracted["monthly_rent"] = rents[0].replace(" ", "").replace(",", ".")
        checks["lease_parties_found"] = "locataire" in normalized and ("bailleur" in normalized or "propriétaire" in normalized)
        checks["rent_found"] = bool(rents or extracted.get("montants"))
        detected = "bail"
    elif normalized_expected in {"identity", "proof"}:
        checks["identity_markers_found"] = any(item in normalized for item in ("nom", "prénom", "republique", "passeport"))
    confidence = float(document.ocr_confidence or 0)
    passed = checks.get("text_extracted") and checks.get("expected_type_matches") and all(
        value for key, value in checks.items() if key not in {"expected_type_matches"} or expected_type
    )
    row = IntelligentOCRJob(
        reference=reference("OCR"), document_id=document.id, expected_type=expected_type,
        detected_type=detected, status="completed", engine=extracted.get("engine", "unknown"),
        confidence=confidence, extracted_data=extracted, checks=checks,
        requires_manual_review=not bool(passed and confidence >= 60),
        created_by=actor, completed_at=utcnow(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def market_comparables(db: Session, property_id: int, listing_type: str, radius_percent: float = 30) -> list[dict]:
    prop = db.query(Property).filter(Property.id == property_id).first()
    if not prop:
        raise ValueError("Bien introuvable")
    if not prop.living_area:
        raise ValueError("La surface du bien est requise")
    minimum = prop.living_area * (1 - radius_percent / 100)
    maximum = prop.living_area * (1 + radius_percent / 100)
    prop_type = prop.type.value if hasattr(prop.type, "value") else prop.type
    rows = db.query(MarketObservation).filter(
        MarketObservation.listing_type == listing_type,
        MarketObservation.is_active == True,  # noqa: E712
        func.lower(MarketObservation.city) == (prop.city or "").lower(),
        MarketObservation.area.between(minimum, maximum),
    ).all()
    compatible = [row for row in rows if row.property_type == prop_type] or rows
    output = [{
        **model_view(row),
        "price_per_sqm": round(row.price / row.area, 2),
        "area_difference_percent": round((row.area / prop.living_area - 1) * 100, 2),
    } for row in compatible]
    output.sort(key=lambda item: abs(item["area_difference_percent"]))
    return output


def market_trends(db: Session, city: str, listing_type: str, property_type: Optional[str] = None) -> dict:
    query = db.query(MarketObservation).filter(
        func.lower(MarketObservation.city) == city.lower(),
        MarketObservation.listing_type == listing_type,
        MarketObservation.is_active == True,  # noqa: E712
    )
    if property_type:
        query = query.filter(MarketObservation.property_type == property_type)
    rows = query.order_by(MarketObservation.observed_on).all()
    grouped: dict[str, list[float]] = {}
    competitors: dict[str, int] = {}
    for row in rows:
        period = row.observed_on.strftime("%Y-%m")
        grouped.setdefault(period, []).append(row.price / row.area)
        if row.competitor:
            competitors[row.competitor] = competitors.get(row.competitor, 0) + 1
    series = [{"period": period, "median_price_per_sqm": round(_median(values), 2), "observation_count": len(values)} for period, values in grouped.items()]
    variation = None
    if len(series) >= 2 and series[0]["median_price_per_sqm"]:
        variation = round((series[-1]["median_price_per_sqm"] / series[0]["median_price_per_sqm"] - 1) * 100, 2)
    return {
        "city": city, "listing_type": listing_type, "property_type": property_type,
        "observation_count": len(rows), "series": series, "variation_percent": variation,
        "competitive_watch": [{"competitor": key, "active_listings": value} for key, value in sorted(competitors.items(), key=lambda item: -item[1])],
        "indices": [model_view(row) for row in db.query(MarketPriceIndex).filter(MarketPriceIndex.geography.ilike(f"%{city}%")).order_by(MarketPriceIndex.period).all()],
    }
