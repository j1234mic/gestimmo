"""Services métier du module 10 : communication et notifications.

Aucun envoi réel email / SMS / push / courrier n'est simulé : chaque
émission est journalisée avec destinataire, canal et statut, prête à
être branchée sur un prestataire.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.communication import (
    AutomationRun,
    AutomationScenario,
    Conversation,
    ConversationParticipant,
    EmailTemplate,
    InAppNotification,
    MessageAttachment,
    NotificationPreference,
    OutboundMessage,
    PostalShipment,
    ThreadMessage,
)
from app.models.owner import Owner
from app.models.property import Property
from app.models.tenant import Lease, LeaseStatus, PaymentStatus, RentPayment, Tenant

CHANNELS = ("email", "sms", "push", "in_app", "postal")
SMS_DEFAULT_TYPES = {
    "urgent_alert",
    "visit_reminder",
    "payment_reminder",
    "unpaid_followup",
}
DEFAULT_CHANNELS_BY_TYPE = {
    "welcome_tenant": ["email", "in_app"],
    "payment_reminder": ["email", "sms", "in_app"],
    "unpaid_followup": ["email", "sms", "in_app"],
    "lease_anniversary": ["email", "in_app"],
    "renewal_reminder": ["email", "in_app"],
    "payment_confirmation": ["email", "in_app"],
    "visit_confirmation": ["email", "in_app"],
    "visit_reminder": ["email", "sms", "in_app"],
    "owner_monthly_report": ["email", "in_app"],
    "urgent_alert": ["email", "sms", "push", "in_app"],
    "message": ["in_app", "email"],
}

SYSTEM_TEMPLATES: List[Dict[str, Any]] = [
    {
        "key": "welcome_tenant",
        "name": "Bienvenue nouveau locataire",
        "subject": "Bienvenue {{prenom}} — votre espace locataire",
        "body": (
            "Bonjour {{prenom}} {{nom}},\n\n"
            "Bienvenue dans votre logement {{bien}} à {{ville}}.\n"
            "Votre loyer mensuel est de {{loyer}} € (charges {{charges}} €).\n\n"
            "L'équipe {{agence}}"
        ),
        "variables": ["prenom", "nom", "bien", "ville", "loyer", "charges", "agence"],
    },
    {
        "key": "payment_reminder",
        "name": "Rappel paiement J-3",
        "subject": "Rappel : loyer {{periode}} à régler le {{echeance}}",
        "body": (
            "Bonjour {{prenom}},\n\n"
            "Votre loyer de {{periode}} ({{montant}} €) arrive à échéance le {{echeance}}.\n"
            "Bien : {{bien}}.\n\n"
            "L'équipe {{agence}}"
        ),
        "variables": ["prenom", "periode", "montant", "echeance", "bien", "agence"],
    },
    {
        "key": "unpaid_followup",
        "name": "Relance impayé",
        "subject": "Relance — loyer impayé {{periode}}",
        "body": (
            "Bonjour {{prenom}} {{nom}},\n\n"
            "Le loyer de la période {{periode}} ({{montant}} €) reste impayé "
            "(échéance {{echeance}}).\nMerci de régulariser rapidement.\n\n"
            "L'équipe {{agence}}"
        ),
        "variables": ["prenom", "nom", "periode", "montant", "echeance", "agence"],
    },
    {
        "key": "lease_anniversary",
        "name": "Anniversaire du bail",
        "subject": "Anniversaire de votre bail {{reference_bail}}",
        "body": (
            "Bonjour {{prenom}},\n\n"
            "Votre bail {{reference_bail}} sur {{bien}} a été signé le {{date_debut}}.\n"
            "N'hésitez pas à nous signaler toute question.\n\n"
            "L'équipe {{agence}}"
        ),
        "variables": ["prenom", "reference_bail", "bien", "date_debut", "agence"],
    },
    {
        "key": "renewal_reminder",
        "name": "Rappel renouvellement",
        "subject": "Votre bail {{reference_bail}} arrive à échéance",
        "body": (
            "Bonjour {{prenom}},\n\n"
            "Le bail {{reference_bail}} ({{bien}}) se termine le {{date_fin}}.\n"
            "Contactez-nous pour convenir des modalités de renouvellement.\n\n"
            "L'équipe {{agence}}"
        ),
        "variables": ["prenom", "reference_bail", "bien", "date_fin", "agence"],
    },
    {
        "key": "payment_confirmation",
        "name": "Confirmation de paiement",
        "subject": "Paiement reçu — {{periode}}",
        "body": (
            "Bonjour {{prenom}},\n\n"
            "Nous confirmons la réception de {{montant}} € pour la période {{periode}}.\n"
            "Votre quittance est disponible dans votre espace.\n\n"
            "L'équipe {{agence}}"
        ),
        "variables": ["prenom", "montant", "periode", "agence"],
    },
    {
        "key": "visit_confirmation",
        "name": "Confirmation de visite",
        "subject": "Visite confirmée le {{date_visite}} à {{heure_visite}}",
        "body": (
            "Bonjour {{prenom}},\n\n"
            "Votre visite de {{bien}} est confirmée le {{date_visite}} à {{heure_visite}}.\n\n"
            "L'équipe {{agence}}"
        ),
        "variables": ["prenom", "bien", "date_visite", "heure_visite", "agence"],
    },
    {
        "key": "owner_monthly_report",
        "name": "Bilan mensuel propriétaire",
        "subject": "Bilan de gestion {{periode}} — {{agence}}",
        "body": (
            "Bonjour {{prenom}},\n\n"
            "Voici le bilan de gestion du mois {{periode}} pour votre patrimoine.\n"
            "Encaissements : {{encaissements}} € — Impayés : {{impayes}} €.\n\n"
            "L'équipe {{agence}}"
        ),
        "variables": ["prenom", "periode", "encaissements", "impayes", "agence"],
    },
]

SYSTEM_SCENARIOS: List[Dict[str, Any]] = [
    {
        "key": "welcome_tenant",
        "name": "Bienvenue nouveau locataire",
        "trigger_type": "welcome_tenant",
        "template_key": "welcome_tenant",
        "channels": ["email", "in_app"],
        "offset_days": 0,
        "description": "Message de bienvenue à la création d'un locataire.",
    },
    {
        "key": "payment_reminder_j3",
        "name": "Rappel paiement J-3",
        "trigger_type": "payment_reminder",
        "template_key": "payment_reminder",
        "channels": ["email", "sms", "in_app"],
        "offset_days": -3,
        "description": "Rappel automatique 3 jours avant l'échéance.",
    },
    {
        "key": "unpaid_followup",
        "name": "Relance impayé",
        "trigger_type": "unpaid_followup",
        "template_key": "unpaid_followup",
        "channels": ["email", "sms", "in_app"],
        "offset_days": 1,
        "description": "Relance dès qu'un loyer est en retard.",
    },
    {
        "key": "lease_anniversary",
        "name": "Anniversaire du bail",
        "trigger_type": "lease_anniversary",
        "template_key": "lease_anniversary",
        "channels": ["email", "in_app"],
        "offset_days": 0,
        "description": "Message le jour anniversaire de la prise d'effet.",
    },
    {
        "key": "renewal_reminder",
        "name": "Rappel renouvellement",
        "trigger_type": "renewal_reminder",
        "template_key": "renewal_reminder",
        "channels": ["email", "in_app"],
        "offset_days": -60,
        "description": "Alerte 60 jours avant la fin du bail.",
    },
    {
        "key": "payment_confirmation",
        "name": "Confirmation de paiement",
        "trigger_type": "payment_confirmation",
        "template_key": "payment_confirmation",
        "channels": ["email", "in_app"],
        "offset_days": 0,
        "description": "Accusé de réception d'un loyer soldé.",
    },
    {
        "key": "visit_confirmation",
        "name": "Confirmation de visite",
        "trigger_type": "visit_confirmation",
        "template_key": "visit_confirmation",
        "channels": ["email", "in_app"],
        "offset_days": 0,
        "description": "Confirmation d'une visite programmée.",
    },
    {
        "key": "owner_monthly_report",
        "name": "Bilan mensuel propriétaire",
        "trigger_type": "owner_monthly_report",
        "template_key": "owner_monthly_report",
        "channels": ["email", "in_app"],
        "offset_days": 0,
        "description": "Bilan de gestion envoyé en début de mois.",
    },
]


def generate_reference(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token() -> str:
    return secrets.token_urlsafe(24)


def render_template(text: str, variables: Optional[Dict[str, Any]] = None) -> str:
    rendered = text or ""
    for key, value in (variables or {}).items():
        rendered = rendered.replace("{{" + str(key) + "}}", "" if value is None else str(value))
        rendered = rendered.replace("{" + str(key) + "}", "" if value is None else str(value))
    return rendered


def merge_context(
    db: Session,
    *,
    tenant_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    property_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "agence": "GestImmo",
        "date": date.today().strftime("%d/%m/%Y"),
    }
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first() if tenant_id else None
    owner = db.query(Owner).filter(Owner.id == owner_id).first() if owner_id else None
    property_ = db.query(Property).filter(Property.id == property_id).first() if property_id else None
    lease = db.query(Lease).filter(Lease.id == lease_id).first() if lease_id else None
    if lease and not tenant:
        tenant = lease.tenant
    if lease and not property_:
        property_ = lease.property
    if tenant:
        ctx.update(
            {
                "prenom": tenant.first_name,
                "nom": tenant.last_name,
                "email": tenant.email,
                "telephone": tenant.mobile or tenant.phone,
            }
        )
    if owner:
        ctx.setdefault("prenom", owner.first_name or owner.company_name or "")
        ctx.setdefault("nom", owner.last_name or "")
        ctx["proprietaire"] = owner.company_name or f"{owner.first_name or ''} {owner.last_name or ''}".strip()
    if property_:
        ctx.update(
            {
                "bien": property_.title,
                "ville": property_.city,
                "adresse": property_.address,
                "loyer": property_.rent_price,
                "charges": property_.charges,
            }
        )
    if lease:
        ctx.update(
            {
                "reference_bail": lease.reference,
                "loyer": lease.monthly_rent,
                "charges": lease.monthly_charges,
                "date_debut": lease.start_date.strftime("%d/%m/%Y") if lease.start_date else "",
                "date_fin": lease.end_date.strftime("%d/%m/%Y") if lease.end_date else "",
            }
        )
    if extra:
        ctx.update(extra)
    return ctx


# ---------------------------------------------------------------------------
# Catalogue / seed
# ---------------------------------------------------------------------------
def ensure_system_catalog(db: Session) -> None:
    if db.query(EmailTemplate).count() == 0:
        for item in SYSTEM_TEMPLATES:
            db.add(
                EmailTemplate(
                    key=item["key"],
                    name=item["name"],
                    subject=item["subject"],
                    body_html=item["body"].replace("\n", "<br/>"),
                    body_text=item["body"],
                    variables=item["variables"],
                    is_system=True,
                )
            )
    if db.query(AutomationScenario).count() == 0:
        for item in SYSTEM_SCENARIOS:
            db.add(
                AutomationScenario(
                    key=item["key"],
                    name=item["name"],
                    description=item.get("description"),
                    trigger_type=item["trigger_type"],
                    template_key=item["template_key"],
                    channels=item["channels"],
                    offset_days=item["offset_days"],
                    rules={},
                    is_system=True,
                )
            )
    db.commit()


# ---------------------------------------------------------------------------
# Messagerie interne
# ---------------------------------------------------------------------------
def create_conversation(db: Session, data, actor: str) -> Conversation:
    conversation = Conversation(
        reference=generate_reference("MSG"),
        subject=data.subject,
        conversation_type=data.conversation_type,
        property_id=data.property_id,
        lease_id=data.lease_id,
        tenant_id=data.tenant_id,
        owner_id=data.owner_id,
        deal_id=data.deal_id,
        created_by=actor,
    )
    db.add(conversation)
    db.flush()
    db.add(
        ConversationParticipant(
            conversation_id=conversation.id,
            participant_type="agent",
            participant_id=None,
            participant_key=actor,
            name=actor,
            email=actor,
        )
    )
    for participant in data.participants or []:
        key = participant.email or f"{participant.participant_type}:{participant.participant_id}"
        db.add(
            ConversationParticipant(
                conversation_id=conversation.id,
                participant_type=participant.participant_type,
                participant_id=participant.participant_id,
                participant_key=key,
                name=participant.name,
                email=participant.email,
            )
        )
    if data.first_message:
        db.add(
            ThreadMessage(
                conversation_id=conversation.id,
                sender_type="agent",
                sender_name=actor,
                sender_email=actor,
                body=data.first_message,
            )
        )
    db.commit()
    db.refresh(conversation)
    return conversation


def list_conversations(
    db: Session,
    *,
    conversation_type: Optional[str] = None,
    property_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    archived: Optional[bool] = False,
    q: Optional[str] = None,
) -> List[Conversation]:
    query = db.query(Conversation)
    if conversation_type:
        query = query.filter(Conversation.conversation_type == conversation_type)
    if property_id:
        query = query.filter(Conversation.property_id == property_id)
    if deal_id:
        query = query.filter(Conversation.deal_id == deal_id)
    if tenant_id:
        query = query.filter(Conversation.tenant_id == tenant_id)
    if owner_id:
        query = query.filter(Conversation.owner_id == owner_id)
    if lease_id:
        query = query.filter(Conversation.lease_id == lease_id)
    if archived is not None:
        query = query.filter(Conversation.is_archived == archived)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Conversation.subject.ilike(like),
                Conversation.reference.ilike(like),
                Conversation.id.in_(
                    db.query(ThreadMessage.conversation_id).filter(ThreadMessage.body.ilike(like))
                ),
            )
        )
    return query.order_by(Conversation.created_at.desc()).all()


def get_conversation(db: Session, conversation_id: int) -> Conversation:
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise ValueError("Conversation non trouvée")
    return conversation


def archive_conversation(db: Session, conversation_id: int, archived: bool, actor: str) -> Conversation:
    conversation = get_conversation(db, conversation_id)
    conversation.is_archived = archived
    conversation.archived_at = _now() if archived else None
    conversation.archived_by = actor if archived else None
    db.commit()
    db.refresh(conversation)
    return conversation


def post_message(db: Session, conversation_id: int, body: str, actor: str) -> ThreadMessage:
    conversation = get_conversation(db, conversation_id)
    if conversation.is_archived:
        raise ValueError("Conversation archivée")
    message = ThreadMessage(
        conversation_id=conversation.id,
        sender_type="agent",
        sender_name=actor,
        sender_email=actor,
        body=body,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def add_attachment(
    db: Session,
    message_id: int,
    filename: str,
    content: bytes,
    mime_type: Optional[str],
) -> MessageAttachment:
    message = db.query(ThreadMessage).filter(ThreadMessage.id == message_id).first()
    if not message:
        raise ValueError("Message non trouvé")
    directory = Path(settings.private_upload_dir_path) / "comms" / "attachments" / str(message.conversation_id)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(filename).suffix or ".bin"
    stored = directory / f"{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(content)
    attachment = MessageAttachment(
        message_id=message.id,
        filename=filename,
        storage_path=str(stored),
        mime_type=mime_type,
        file_size=len(content),
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return attachment


def search_messages(db: Session, q: str, limit: int = 50) -> List[Dict[str, Any]]:
    like = f"%{q}%"
    rows = (
        db.query(ThreadMessage)
        .filter(ThreadMessage.is_deleted == False, ThreadMessage.body.ilike(like))  # noqa: E712
        .order_by(ThreadMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_message_view(m) for m in rows]


def conversation_view(conversation: Conversation, include_messages: bool = False) -> Dict[str, Any]:
    payload = {
        "id": conversation.id,
        "reference": conversation.reference,
        "subject": conversation.subject,
        "conversation_type": conversation.conversation_type,
        "property_id": conversation.property_id,
        "lease_id": conversation.lease_id,
        "tenant_id": conversation.tenant_id,
        "owner_id": conversation.owner_id,
        "deal_id": conversation.deal_id,
        "is_archived": conversation.is_archived,
        "archived_at": conversation.archived_at.isoformat() if conversation.archived_at else None,
        "created_by": conversation.created_by,
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "participants": [
            {
                "id": p.id,
                "participant_type": p.participant_type,
                "participant_id": p.participant_id,
                "name": p.name,
                "email": p.email,
            }
            for p in conversation.participants
        ],
        "message_count": len(conversation.messages),
    }
    if include_messages:
        payload["messages"] = [_message_view(m) for m in conversation.messages if not m.is_deleted]
    return payload


def _message_view(message: ThreadMessage) -> Dict[str, Any]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "sender_type": message.sender_type,
        "sender_name": message.sender_name,
        "sender_email": message.sender_email,
        "body": message.body,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "attachments": [
            {
                "id": a.id,
                "filename": a.filename,
                "file_size": a.file_size,
                "mime_type": a.mime_type,
                "download_url": f"/api/comms/attachments/{a.id}",
            }
            for a in message.attachments
        ],
    }


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
def list_templates(db: Session) -> List[EmailTemplate]:
    ensure_system_catalog(db)
    return db.query(EmailTemplate).order_by(EmailTemplate.name).all()


def create_template(db: Session, data, actor: str) -> EmailTemplate:
    if db.query(EmailTemplate).filter(EmailTemplate.key == data.key).first():
        raise ValueError("Une clé de modèle existe déjà")
    template = EmailTemplate(
        key=data.key,
        name=data.name,
        subject=data.subject,
        body_html=data.body_html,
        body_text=data.body_text or data.body_html,
        variables=data.variables,
        is_system=False,
        updated_by=actor,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def update_template(db: Session, template_id: int, data, actor: str) -> EmailTemplate:
    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template:
        raise ValueError("Modèle non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    template.updated_by = actor
    db.commit()
    db.refresh(template)
    return template


def template_view(template: EmailTemplate) -> Dict[str, Any]:
    return {
        "id": template.id,
        "key": template.key,
        "name": template.name,
        "subject": template.subject,
        "body_html": template.body_html,
        "body_text": template.body_text,
        "variables": template.variables or [],
        "is_system": template.is_system,
        "is_active": template.is_active,
    }


# ---------------------------------------------------------------------------
# Préférences
# ---------------------------------------------------------------------------
def upsert_preference(db: Session, data) -> NotificationPreference:
    key = data.email or f"{data.contact_type}:{data.contact_id}"
    if not key:
        raise ValueError("Un email ou un identifiant de contact est requis")
    invalid = [c for c in data.channels if c not in CHANNELS]
    if invalid:
        raise ValueError(f"Canaux inconnus : {', '.join(invalid)}")
    pref = (
        db.query(NotificationPreference)
        .filter(
            NotificationPreference.contact_type == data.contact_type,
            NotificationPreference.contact_key == key,
            NotificationPreference.notification_type == data.notification_type,
        )
        .first()
    )
    if not pref:
        pref = NotificationPreference(
            contact_type=data.contact_type,
            contact_id=data.contact_id,
            contact_key=key,
            email=data.email,
            phone=data.phone,
            notification_type=data.notification_type,
            unsubscribe_token=_token(),
        )
        db.add(pref)
    pref.channels = data.channels
    pref.frequency = data.frequency
    pref.unsubscribed = data.unsubscribed
    if data.email:
        pref.email = data.email
    if data.phone:
        pref.phone = data.phone
    db.commit()
    db.refresh(pref)
    return pref


def list_preferences(
    db: Session, contact_type: Optional[str] = None, email: Optional[str] = None
) -> List[NotificationPreference]:
    query = db.query(NotificationPreference)
    if contact_type:
        query = query.filter(NotificationPreference.contact_type == contact_type)
    if email:
        query = query.filter(NotificationPreference.email == email)
    return query.order_by(NotificationPreference.notification_type).all()


def preference_view(pref: NotificationPreference) -> Dict[str, Any]:
    return {
        "id": pref.id,
        "contact_type": pref.contact_type,
        "contact_id": pref.contact_id,
        "email": pref.email,
        "phone": pref.phone,
        "notification_type": pref.notification_type,
        "channels": pref.channels or [],
        "frequency": pref.frequency,
        "unsubscribed": pref.unsubscribed,
        "unsubscribe_token": pref.unsubscribe_token,
    }


def unsubscribe_by_token(db: Session, token: str) -> Dict[str, Any]:
    pref = db.query(NotificationPreference).filter(NotificationPreference.unsubscribe_token == token).first()
    outbound = None
    if not pref:
        outbound = db.query(OutboundMessage).filter(OutboundMessage.unsubscribe_token == token).first()
        if not outbound:
            raise ValueError("Jeton de désabonnement invalide")
        updated = (
            db.query(NotificationPreference)
            .filter(NotificationPreference.email == outbound.recipient_email)
            .all()
        )
        if not updated:
            pref = NotificationPreference(
                contact_type=outbound.recipient_type or "tenant",
                contact_id=outbound.recipient_id,
                contact_key=outbound.recipient_email or token,
                email=outbound.recipient_email,
                notification_type=outbound.notification_type,
                channels=[],
                frequency="never",
                unsubscribed=True,
                unsubscribe_token=_token(),
            )
            db.add(pref)
            updated = [pref]
        for item in updated:
            item.unsubscribed = True
            item.frequency = "never"
            item.channels = []
        db.commit()
        return {"unsubscribed": True, "email": outbound.recipient_email, "count": len(updated)}
    pref.unsubscribed = True
    pref.frequency = "never"
    pref.channels = []
    db.commit()
    return {"unsubscribed": True, "email": pref.email, "notification_type": pref.notification_type}


def _matching_preference(
    db: Session, *, contact_type: str, contact_id: Optional[int], email: Optional[str], notification_type: str
) -> Optional[NotificationPreference]:
    query = db.query(NotificationPreference).filter(
        NotificationPreference.notification_type == notification_type
    )
    if email:
        found = query.filter(NotificationPreference.email == email).first()
        if found:
            return found
    if contact_id:
        found = query.filter(
            NotificationPreference.contact_type == contact_type,
            NotificationPreference.contact_id == contact_id,
        ).first()
        if found:
            return found
    return None


def allowed_channels(
    db: Session,
    *,
    notification_type: str,
    requested: Iterable[str],
    contact_type: str,
    contact_id: Optional[int],
    email: Optional[str],
    force: bool = False,
) -> List[str]:
    requested = [c for c in requested if c in CHANNELS]
    if force:
        return requested
    pref = _matching_preference(
        db,
        contact_type=contact_type,
        contact_id=contact_id,
        email=email,
        notification_type=notification_type,
    )
    if pref:
        if pref.unsubscribed or pref.frequency == "never":
            return []
        allowed = set(pref.channels or [])
        return [c for c in requested if c in allowed]
    return requested


# ---------------------------------------------------------------------------
# Dispatch multicanal
# ---------------------------------------------------------------------------
def dispatch(db: Session, data, actor: Optional[str] = None) -> Dict[str, Any]:
    ensure_system_catalog(db)
    variables = merge_context(
        db,
        tenant_id=data.tenant_id or (data.recipient_id if data.recipient_type == "tenant" else None),
        owner_id=data.owner_id or (data.recipient_id if data.recipient_type == "owner" else None),
        property_id=data.property_id,
        lease_id=data.lease_id,
        extra=data.variables,
    )
    subject = data.subject
    body = data.body
    if data.template_key:
        template = db.query(EmailTemplate).filter(EmailTemplate.key == data.template_key).first()
        if not template:
            raise ValueError("Modèle introuvable")
        subject = subject or render_template(template.subject, variables)
        body = body or render_template(template.body_text or template.body_html, variables)
    if not subject:
        subject = data.notification_type
    if body is None:
        body = ""

    channels = allowed_channels(
        db,
        notification_type=data.notification_type,
        requested=data.channels,
        contact_type=data.recipient_type,
        contact_id=data.recipient_id,
        email=data.recipient_email,
        force=data.force,
    )
    created = []
    skipped = []
    if not channels:
        skipped.append({"reason": "preference_blocked", "channels": list(data.channels)})
    unsubscribe_token = _token()
    for channel in data.channels:
        if channel not in CHANNELS:
            skipped.append({"channel": channel, "reason": "unknown_channel"})
            continue
        if channel not in channels:
            skipped.append({"channel": channel, "reason": "preference_or_unsubscribed"})
            continue
        if channel == "sms" and not data.recipient_phone and data.notification_type not in SMS_DEFAULT_TYPES:
            # SMS sans numéro : on journalise l'échec plutôt que d'inventer un envoi
            outbound = _record_outbound(
                db,
                channel=channel,
                data=data,
                subject=subject,
                body=body,
                status="failed",
                skip_reason="missing_phone",
                unsubscribe_token=unsubscribe_token,
            )
            created.append(outbound)
            continue
        outbound = _record_outbound(
            db,
            channel=channel,
            data=data,
            subject=subject,
            body=body,
            status="sent",
            unsubscribe_token=unsubscribe_token,
        )
        if channel == "in_app":
            db.add(
                InAppNotification(
                    recipient_type=data.recipient_type,
                    recipient_key=data.recipient_email or actor,
                    recipient_id=data.recipient_id,
                    notification_type=data.notification_type,
                    title=subject,
                    body=body,
                    related_type=data.related_entity_type,
                    related_id=data.related_entity_id,
                )
            )
        if channel == "postal":
            address = data.postal_address or {}
            db.add(
                PostalShipment(
                    outbound_id=outbound.id,
                    provider="service_courrier",
                    recipient_name=data.recipient_name,
                    address=address.get("address"),
                    postal_code=address.get("postal_code"),
                    city=address.get("city"),
                    country=address.get("country") or "France",
                    status="submitted",
                )
            )
        created.append(outbound)
    db.commit()
    return {
        "sent": [outbound_view(item) for item in created if item.status == "sent"],
        "failed": [outbound_view(item) for item in created if item.status != "sent"],
        "skipped": skipped,
        "count": len([item for item in created if item.status == "sent"]),
    }


def _record_outbound(
    db: Session,
    *,
    channel: str,
    data,
    subject: str,
    body: str,
    status: str,
    unsubscribe_token: str,
    skip_reason: Optional[str] = None,
) -> OutboundMessage:
    outbound = OutboundMessage(
        reference=generate_reference("OUT"),
        channel=channel,
        notification_type=data.notification_type,
        recipient_type=data.recipient_type,
        recipient_id=data.recipient_id,
        recipient_email=data.recipient_email,
        recipient_phone=data.recipient_phone,
        recipient_name=data.recipient_name,
        property_id=data.property_id,
        lease_id=data.lease_id,
        tenant_id=data.tenant_id,
        owner_id=data.owner_id,
        deal_id=data.deal_id,
        related_entity_type=data.related_entity_type,
        related_entity_id=data.related_entity_id,
        subject=subject,
        body=body,
        template_key=data.template_key,
        variables=data.variables,
        status=status,
        skip_reason=skip_reason,
        provider=_provider_for(channel),
        tracking_token=_token() if channel == "email" else None,
        unsubscribe_token=unsubscribe_token,
        sent_at=_now() if status == "sent" else None,
    )
    db.add(outbound)
    db.flush()
    return outbound


def _provider_for(channel: str) -> str:
    return {
        "email": "smtp",
        "sms": "sms_gateway",
        "push": "push_gateway",
        "in_app": "in_app",
        "postal": "service_courrier",
    }.get(channel, channel)


def outbound_view(item: OutboundMessage) -> Dict[str, Any]:
    return {
        "id": item.id,
        "reference": item.reference,
        "channel": item.channel,
        "notification_type": item.notification_type,
        "recipient_type": item.recipient_type,
        "recipient_id": item.recipient_id,
        "recipient_email": item.recipient_email,
        "recipient_phone": item.recipient_phone,
        "recipient_name": item.recipient_name,
        "property_id": item.property_id,
        "lease_id": item.lease_id,
        "tenant_id": item.tenant_id,
        "owner_id": item.owner_id,
        "deal_id": item.deal_id,
        "subject": item.subject,
        "body": item.body,
        "template_key": item.template_key,
        "status": item.status,
        "skip_reason": item.skip_reason,
        "provider": item.provider,
        "tracking_token": item.tracking_token,
        "unsubscribe_token": item.unsubscribe_token,
        "open_count": item.open_count,
        "opened_at": item.opened_at.isoformat() if item.opened_at else None,
        "sent_at": item.sent_at.isoformat() if item.sent_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "tracking_url": f"/api/comms/track/{item.tracking_token}" if item.tracking_token else None,
        "unsubscribe_url": f"/api/comms/unsubscribe/{item.unsubscribe_token}" if item.unsubscribe_token else None,
    }


def track_open(db: Session, token: str) -> OutboundMessage:
    outbound = db.query(OutboundMessage).filter(OutboundMessage.tracking_token == token).first()
    if not outbound:
        raise ValueError("Jeton de suivi invalide")
    outbound.open_count = (outbound.open_count or 0) + 1
    if not outbound.opened_at:
        outbound.opened_at = _now()
    if outbound.status == "sent":
        outbound.status = "opened"
    db.commit()
    db.refresh(outbound)
    return outbound


def list_in_app(
    db: Session, recipient_key: Optional[str] = None, unread_only: bool = False
) -> List[InAppNotification]:
    query = db.query(InAppNotification)
    if recipient_key:
        query = query.filter(InAppNotification.recipient_key == recipient_key)
    if unread_only:
        query = query.filter(InAppNotification.is_read == False)  # noqa: E712
    return query.order_by(InAppNotification.created_at.desc()).all()


def mark_in_app_read(db: Session, notification_id: int) -> InAppNotification:
    item = db.query(InAppNotification).filter(InAppNotification.id == notification_id).first()
    if not item:
        raise ValueError("Notification non trouvée")
    item.is_read = True
    item.read_at = _now()
    db.commit()
    db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Historique
# ---------------------------------------------------------------------------
def search_history(
    db: Session,
    *,
    channel: Optional[str] = None,
    notification_type: Optional[str] = None,
    recipient_email: Optional[str] = None,
    property_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    q: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    limit: int = 100,
) -> List[OutboundMessage]:
    query = db.query(OutboundMessage)
    if channel:
        query = query.filter(OutboundMessage.channel == channel)
    if notification_type:
        query = query.filter(OutboundMessage.notification_type == notification_type)
    if recipient_email:
        query = query.filter(OutboundMessage.recipient_email == recipient_email)
    if property_id:
        query = query.filter(OutboundMessage.property_id == property_id)
    if lease_id:
        query = query.filter(OutboundMessage.lease_id == lease_id)
    if tenant_id:
        query = query.filter(OutboundMessage.tenant_id == tenant_id)
    if owner_id:
        query = query.filter(OutboundMessage.owner_id == owner_id)
    if deal_id:
        query = query.filter(OutboundMessage.deal_id == deal_id)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                OutboundMessage.subject.ilike(like),
                OutboundMessage.body.ilike(like),
                OutboundMessage.recipient_name.ilike(like),
                OutboundMessage.reference.ilike(like),
            )
        )
    if date_from:
        query = query.filter(OutboundMessage.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.filter(OutboundMessage.created_at <= datetime.combine(date_to, datetime.max.time()))
    return query.order_by(OutboundMessage.created_at.desc()).limit(limit).all()


# ---------------------------------------------------------------------------
# Automatisation
# ---------------------------------------------------------------------------
def list_scenarios(db: Session) -> List[AutomationScenario]:
    ensure_system_catalog(db)
    return db.query(AutomationScenario).order_by(AutomationScenario.name).all()


def update_scenario(db: Session, scenario_id: int, data) -> AutomationScenario:
    scenario = db.query(AutomationScenario).filter(AutomationScenario.id == scenario_id).first()
    if not scenario:
        raise ValueError("Scénario non trouvé")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(scenario, field, value)
    db.commit()
    db.refresh(scenario)
    return scenario


def create_scenario(db: Session, data) -> AutomationScenario:
    if db.query(AutomationScenario).filter(AutomationScenario.key == data.key).first():
        raise ValueError("Une clé de scénario existe déjà")
    scenario = AutomationScenario(
        key=data.key,
        name=data.name,
        description=data.description,
        trigger_type=data.trigger_type,
        template_key=data.template_key,
        channels=data.channels,
        offset_days=data.offset_days,
        rules=data.rules,
        is_system=False,
        is_enabled=data.is_enabled,
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


def scenario_view(scenario: AutomationScenario) -> Dict[str, Any]:
    return {
        "id": scenario.id,
        "key": scenario.key,
        "name": scenario.name,
        "description": scenario.description,
        "trigger_type": scenario.trigger_type,
        "template_key": scenario.template_key,
        "channels": scenario.channels or [],
        "offset_days": scenario.offset_days,
        "rules": scenario.rules or {},
        "is_enabled": scenario.is_enabled,
        "is_system": scenario.is_system,
        "last_run_at": scenario.last_run_at.isoformat() if scenario.last_run_at else None,
    }


class _DispatchData:
    """Objet minimal compatible avec dispatch() pour les scénarios."""

    def __init__(self, **kwargs):
        self.notification_type = kwargs.get("notification_type")
        self.channels = kwargs.get("channels") or []
        self.recipient_type = kwargs.get("recipient_type", "tenant")
        self.recipient_id = kwargs.get("recipient_id")
        self.recipient_email = kwargs.get("recipient_email")
        self.recipient_phone = kwargs.get("recipient_phone")
        self.recipient_name = kwargs.get("recipient_name")
        self.subject = kwargs.get("subject")
        self.body = kwargs.get("body")
        self.template_key = kwargs.get("template_key")
        self.variables = kwargs.get("variables") or {}
        self.property_id = kwargs.get("property_id")
        self.lease_id = kwargs.get("lease_id")
        self.tenant_id = kwargs.get("tenant_id")
        self.owner_id = kwargs.get("owner_id")
        self.deal_id = kwargs.get("deal_id")
        self.related_entity_type = kwargs.get("related_entity_type")
        self.related_entity_id = kwargs.get("related_entity_id")
        self.postal_address = kwargs.get("postal_address")
        self.force = kwargs.get("force", False)


def already_sent(db: Session, notification_type: str, entity_type: str, entity_id: int) -> bool:
    return (
        db.query(OutboundMessage)
        .filter(
            OutboundMessage.notification_type == notification_type,
            OutboundMessage.related_entity_type == entity_type,
            OutboundMessage.related_entity_id == entity_id,
            OutboundMessage.status.in_(["sent", "opened", "delivered"]),
        )
        .first()
        is not None
    )


def process_automations(db: Session, only_key: Optional[str] = None) -> Dict[str, Any]:
    ensure_system_catalog(db)
    query = db.query(AutomationScenario).filter(AutomationScenario.is_enabled == True)  # noqa: E712
    if only_key:
        query = query.filter(AutomationScenario.key == only_key)
    scenarios = query.all()
    results = []
    for scenario in scenarios:
        processed, sent, skipped, details = _run_scenario(db, scenario)
        run = AutomationRun(
            scenario_id=scenario.id,
            status="ok",
            processed_count=processed,
            sent_count=sent,
            skipped_count=skipped,
            details=details[:50],
        )
        db.add(run)
        scenario.last_run_at = _now()
        results.append(
            {
                "key": scenario.key,
                "name": scenario.name,
                "processed": processed,
                "sent": sent,
                "skipped": skipped,
                "details": details,
            }
        )
    db.commit()
    return {"count": len(results), "scenarios": results}


def _run_scenario(db: Session, scenario: AutomationScenario):
    handlers = {
        "welcome_tenant": _run_welcome_tenant,
        "payment_reminder": _run_payment_reminder,
        "unpaid_followup": _run_unpaid,
        "lease_anniversary": _run_lease_anniversary,
        "renewal_reminder": _run_renewal,
        "payment_confirmation": _run_payment_confirmation,
        "visit_confirmation": _run_visit_confirmation,
        "owner_monthly_report": _run_owner_monthly,
    }
    handler = handlers.get(scenario.trigger_type)
    if not handler:
        return 0, 0, 0, [{"error": f"Déclencheur inconnu : {scenario.trigger_type}"}]
    return handler(db, scenario)


def _emit(db: Session, scenario: AutomationScenario, **kwargs) -> int:
    payload = _DispatchData(
        notification_type=scenario.trigger_type,
        channels=scenario.channels or ["email", "in_app"],
        template_key=scenario.template_key,
        **kwargs,
    )
    result = dispatch(db, payload)
    return result["count"]


def _run_welcome_tenant(db: Session, scenario: AutomationScenario):
    horizon = date.today() - timedelta(days=int((scenario.rules or {}).get("created_within_days", 7)))
    tenants = db.query(Tenant).filter(Tenant.is_active == True).all()  # noqa: E712
    processed = sent = skipped = 0
    details = []
    for tenant in tenants:
        processed += 1
        created = tenant.created_at.date() if tenant.created_at else date.today()
        if created < horizon:
            skipped += 1
            continue
        if already_sent(db, scenario.trigger_type, "tenant", tenant.id):
            skipped += 1
            continue
        count = _emit(
            db,
            scenario,
            recipient_type="tenant",
            recipient_id=tenant.id,
            recipient_email=tenant.email,
            recipient_phone=tenant.mobile or tenant.phone,
            recipient_name=f"{tenant.first_name} {tenant.last_name}",
            tenant_id=tenant.id,
            related_entity_type="tenant",
            related_entity_id=tenant.id,
        )
        sent += count
        details.append({"tenant_id": tenant.id, "sent": count})
    return processed, sent, skipped, details


def _run_payment_reminder(db: Session, scenario: AutomationScenario):
    offset = scenario.offset_days if scenario.offset_days is not None else -3
    target = date.today() - timedelta(days=offset) if offset < 0 else date.today() + timedelta(days=offset)
    # offset -3 → target = today + 3
    if offset < 0:
        target = date.today() + timedelta(days=abs(offset))
    payments = (
        db.query(RentPayment)
        .filter(
            RentPayment.due_date == target,
            RentPayment.status.in_([PaymentStatus.DUE, PaymentStatus.PARTIAL]),
        )
        .all()
    )
    processed = sent = skipped = 0
    details = []
    for payment in payments:
        processed += 1
        if already_sent(db, scenario.trigger_type, "payment", payment.id):
            skipped += 1
            continue
        tenant = payment.tenant
        count = _emit(
            db,
            scenario,
            recipient_type="tenant",
            recipient_id=tenant.id if tenant else None,
            recipient_email=tenant.email if tenant else None,
            recipient_phone=(tenant.mobile or tenant.phone) if tenant else None,
            recipient_name=f"{tenant.first_name} {tenant.last_name}" if tenant else None,
            tenant_id=payment.tenant_id,
            lease_id=payment.lease_id,
            property_id=payment.lease.property_id if payment.lease else None,
            related_entity_type="payment",
            related_entity_id=payment.id,
            variables={
                "periode": payment.period,
                "montant": payment.amount_due,
                "echeance": payment.due_date.strftime("%d/%m/%Y"),
            },
        )
        sent += count
        details.append({"payment_id": payment.id, "sent": count})
    return processed, sent, skipped, details


def _run_unpaid(db: Session, scenario: AutomationScenario):
    payments = (
        db.query(RentPayment)
        .filter(
            RentPayment.due_date < date.today(),
            RentPayment.status.in_([PaymentStatus.DUE, PaymentStatus.PARTIAL, PaymentStatus.OVERDUE]),
        )
        .all()
    )
    processed = sent = skipped = 0
    details = []
    for payment in payments:
        processed += 1
        if already_sent(db, scenario.trigger_type, "payment", payment.id):
            skipped += 1
            continue
        tenant = payment.tenant
        count = _emit(
            db,
            scenario,
            recipient_type="tenant",
            recipient_id=tenant.id if tenant else None,
            recipient_email=tenant.email if tenant else None,
            recipient_phone=(tenant.mobile or tenant.phone) if tenant else None,
            recipient_name=f"{tenant.first_name} {tenant.last_name}" if tenant else None,
            tenant_id=payment.tenant_id,
            lease_id=payment.lease_id,
            property_id=payment.lease.property_id if payment.lease else None,
            related_entity_type="payment",
            related_entity_id=payment.id,
            variables={
                "periode": payment.period,
                "montant": round(payment.amount_due - (payment.amount_paid or 0), 2),
                "echeance": payment.due_date.strftime("%d/%m/%Y"),
            },
        )
        sent += count
        details.append({"payment_id": payment.id, "sent": count})
    return processed, sent, skipped, details


def _run_lease_anniversary(db: Session, scenario: AutomationScenario):
    today = date.today()
    leases = db.query(Lease).filter(Lease.status == LeaseStatus.ACTIVE).all()
    processed = sent = skipped = 0
    details = []
    for lease in leases:
        processed += 1
        if not lease.start_date:
            skipped += 1
            continue
        if lease.start_date.month != today.month or lease.start_date.day != today.day:
            skipped += 1
            continue
        if lease.start_date.year >= today.year:
            skipped += 1
            continue
        year_key = today.year * 100000 + lease.id
        if already_sent(db, scenario.trigger_type, "lease_year", year_key):
            skipped += 1
            continue
        tenant = lease.tenant
        count = _emit(
            db,
            scenario,
            recipient_type="tenant",
            recipient_id=tenant.id if tenant else None,
            recipient_email=tenant.email if tenant else None,
            recipient_name=f"{tenant.first_name} {tenant.last_name}" if tenant else None,
            tenant_id=lease.tenant_id,
            lease_id=lease.id,
            property_id=lease.property_id,
            related_entity_type="lease_year",
            related_entity_id=year_key,
        )
        sent += count
        details.append({"lease_id": lease.id, "sent": count})
    return processed, sent, skipped, details


def _run_renewal(db: Session, scenario: AutomationScenario):
    offset = abs(scenario.offset_days or 60)
    horizon = date.today() + timedelta(days=offset)
    leases = (
        db.query(Lease)
        .filter(
            Lease.status == LeaseStatus.ACTIVE,
            Lease.end_date != None,  # noqa: E711
            Lease.end_date <= horizon,
            Lease.end_date >= date.today(),
        )
        .all()
    )
    processed = sent = skipped = 0
    details = []
    for lease in leases:
        processed += 1
        if already_sent(db, scenario.trigger_type, "lease", lease.id):
            skipped += 1
            continue
        tenant = lease.tenant
        count = _emit(
            db,
            scenario,
            recipient_type="tenant",
            recipient_id=tenant.id if tenant else None,
            recipient_email=tenant.email if tenant else None,
            recipient_name=f"{tenant.first_name} {tenant.last_name}" if tenant else None,
            tenant_id=lease.tenant_id,
            lease_id=lease.id,
            property_id=lease.property_id,
            related_entity_type="lease",
            related_entity_id=lease.id,
        )
        sent += count
        details.append({"lease_id": lease.id, "sent": count})
    return processed, sent, skipped, details


def _run_payment_confirmation(db: Session, scenario: AutomationScenario):
    payments = db.query(RentPayment).filter(RentPayment.status == PaymentStatus.PAID).all()
    processed = sent = skipped = 0
    details = []
    for payment in payments:
        processed += 1
        if already_sent(db, scenario.trigger_type, "payment", payment.id):
            skipped += 1
            continue
        tenant = payment.tenant
        count = _emit(
            db,
            scenario,
            recipient_type="tenant",
            recipient_id=tenant.id if tenant else None,
            recipient_email=tenant.email if tenant else None,
            recipient_name=f"{tenant.first_name} {tenant.last_name}" if tenant else None,
            tenant_id=payment.tenant_id,
            lease_id=payment.lease_id,
            related_entity_type="payment",
            related_entity_id=payment.id,
            variables={"periode": payment.period, "montant": payment.amount_paid},
        )
        sent += count
        details.append({"payment_id": payment.id, "sent": count})
    return processed, sent, skipped, details


def _run_visit_confirmation(db: Session, scenario: AutomationScenario):
    try:
        from app.models.crm import Visit, VisitStatus
    except Exception:
        return 0, 0, 0, [{"error": "module CRM indisponible"}]
    visits = (
        db.query(Visit)
        .filter(Visit.status.in_([VisitStatus.CONFIRMED, VisitStatus.SCHEDULED]))
        .all()
    )
    processed = sent = skipped = 0
    details = []
    for visit in visits:
        processed += 1
        if already_sent(db, scenario.trigger_type, "visit", visit.id):
            skipped += 1
            continue
        prospect = visit.prospect
        count = _emit(
            db,
            scenario,
            recipient_type="prospect",
            recipient_id=visit.prospect_id,
            recipient_email=prospect.email if prospect else None,
            recipient_phone=(prospect.mobile or prospect.phone) if prospect else None,
            recipient_name=f"{prospect.first_name} {prospect.last_name}" if prospect else None,
            property_id=visit.property_id,
            related_entity_type="visit",
            related_entity_id=visit.id,
            variables={
                "prenom": prospect.first_name if prospect else "",
                "date_visite": visit.scheduled_date.strftime("%d/%m/%Y") if visit.scheduled_date else "",
                "heure_visite": visit.start_time or "",
                "bien": visit.property.title if visit.property else "",
            },
        )
        sent += count
        details.append({"visit_id": visit.id, "sent": count})
    return processed, sent, skipped, details


def _run_owner_monthly(db: Session, scenario: AutomationScenario):
    day = int((scenario.rules or {}).get("day_of_month", 1))
    if date.today().day != day and not (scenario.rules or {}).get("force"):
        return 0, 0, 0, [{"skipped": "hors jour d'envoi"}]
    period = date.today().strftime("%Y-%m")
    owners = db.query(Owner).filter(Owner.is_active == True).all()  # noqa: E712
    processed = sent = skipped = 0
    details = []
    for owner in owners:
        processed += 1
        period_key = int(date.today().strftime("%Y%m")) * 100000 + owner.id
        if already_sent(db, scenario.trigger_type, "owner_month", period_key):
            skipped += 1
            continue
        count = _emit(
            db,
            scenario,
            recipient_type="owner",
            recipient_id=owner.id,
            recipient_email=owner.email,
            recipient_name=owner.company_name or f"{owner.first_name or ''} {owner.last_name or ''}".strip(),
            owner_id=owner.id,
            related_entity_type="owner_month",
            related_entity_id=period_key,
            variables={"periode": period, "encaissements": 0, "impayes": 0, "prenom": owner.first_name or owner.company_name},
        )
        sent += count
        details.append({"owner_id": owner.id, "sent": count})
    return processed, sent, skipped, details
