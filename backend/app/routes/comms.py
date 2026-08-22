"""API du module 10 : communication et notifications."""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.auth import require_read, require_write
from app.database import get_db
from app.models.communication import MessageAttachment
from app.schemas.communication import (
    ConversationArchive,
    ConversationCreate,
    DispatchRequest,
    EmailTemplateCreate,
    EmailTemplateUpdate,
    PreferenceUpsert,
    ScenarioCreate,
    ScenarioUpdate,
    ThreadMessageCreate,
)
from app.services import communication_service

router = APIRouter(prefix="/api/comms", tags=["Communication et notifications"])

PIXEL_GIF = bytes.fromhex(
    "47494638396101000100800000ffffff00000021f90401000000002c00000000010001000002024401003b"
)


# ---------------------------------------------------------------------------
# Messagerie interne
# ---------------------------------------------------------------------------
@router.post("/conversations", status_code=201)
def create_conversation(data: ConversationCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    conversation = communication_service.create_conversation(db, data, current_user.email)
    return communication_service.conversation_view(conversation, include_messages=True)


@router.get("/conversations")
def list_conversations(
    conversation_type: Optional[str] = None,
    property_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    tenant_id: Optional[int] = None,
    owner_id: Optional[int] = None,
    lease_id: Optional[int] = None,
    archived: Optional[bool] = False,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    conversations = communication_service.list_conversations(
        db,
        conversation_type=conversation_type,
        property_id=property_id,
        deal_id=deal_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        lease_id=lease_id,
        archived=archived,
        q=q,
    )
    return {
        "data": [communication_service.conversation_view(c) for c in conversations],
        "count": len(conversations),
    }


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    try:
        conversation = communication_service.get_conversation(db, conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return communication_service.conversation_view(conversation, include_messages=True)


@router.post("/conversations/{conversation_id}/messages", status_code=201)
def post_message(
    conversation_id: int,
    data: ThreadMessageCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    try:
        message = communication_service.post_message(db, conversation_id, data.body, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return communication_service._message_view(message)


@router.post("/conversations/{conversation_id}/messages/{message_id}/attachments", status_code=201)
async def attach_file(
    conversation_id: int,
    message_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Fichier vide")
    try:
        attachment = communication_service.add_attachment(
            db, message_id, file.filename or "piece-jointe", content, file.content_type
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "file_size": attachment.file_size,
        "download_url": f"/api/comms/attachments/{attachment.id}",
    }


@router.put("/conversations/{conversation_id}/archive")
def archive_conversation(
    conversation_id: int,
    data: ConversationArchive,
    db: Session = Depends(get_db),
    current_user=Depends(require_write),
):
    try:
        conversation = communication_service.archive_conversation(
            db, conversation_id, data.archived, current_user.email
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return communication_service.conversation_view(conversation)


@router.get("/messages/search")
def search_messages(q: str, db: Session = Depends(get_db), current_user=Depends(require_read)):
    return {"data": communication_service.search_messages(db, q), "query": q}


@router.get("/attachments/{attachment_id}")
def download_attachment(attachment_id: int, db: Session = Depends(get_db), current_user=Depends(require_read)):
    attachment = db.query(MessageAttachment).filter(MessageAttachment.id == attachment_id).first()
    if not attachment:
        raise HTTPException(status_code=404, detail="Pièce jointe non trouvée")
    from pathlib import Path

    path = Path(attachment.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return Response(
        content=path.read_bytes(),
        media_type=attachment.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{attachment.filename}"'},
    )


# ---------------------------------------------------------------------------
# Templates email
# ---------------------------------------------------------------------------
@router.get("/templates")
def list_templates(db: Session = Depends(get_db), current_user=Depends(require_read)):
    templates = communication_service.list_templates(db)
    return {"data": [communication_service.template_view(t) for t in templates], "count": len(templates)}


@router.post("/templates", status_code=201)
def create_template(data: EmailTemplateCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        template = communication_service.create_template(db, data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return communication_service.template_view(template)


@router.put("/templates/{template_id}")
def update_template(
    template_id: int, data: EmailTemplateUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)
):
    try:
        template = communication_service.update_template(db, template_id, data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return communication_service.template_view(template)


# ---------------------------------------------------------------------------
# Notifications multicanal
# ---------------------------------------------------------------------------
@router.post("/dispatch")
def dispatch(data: DispatchRequest, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        return communication_service.dispatch(db, data, current_user.email)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/in-app")
def list_in_app(
    unread_only: bool = False,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    items = communication_service.list_in_app(db, recipient_key=current_user.email, unread_only=unread_only)
    return {
        "data": [
            {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "notification_type": n.notification_type,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() if n.created_at else None,
            }
            for n in items
        ],
        "count": len(items),
    }


@router.put("/in-app/{notification_id}/read")
def read_in_app(notification_id: int, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        item = communication_service.mark_in_app_read(db, notification_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"id": item.id, "is_read": item.is_read}


@router.get("/track/{token}")
def track_open(token: str, db: Session = Depends(get_db)):
    """Pixel de suivi d'ouverture (public, sans authentification)."""
    try:
        communication_service.track_open(db, token)
    except ValueError:
        pass
    return Response(content=PIXEL_GIF, media_type="image/gif")


@router.get("/unsubscribe/{token}")
def unsubscribe(token: str, db: Session = Depends(get_db)):
    try:
        return communication_service.unsubscribe_by_token(db, token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Centre de préférences
# ---------------------------------------------------------------------------
@router.get("/preferences")
def list_preferences(
    contact_type: Optional[str] = None,
    email: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    prefs = communication_service.list_preferences(db, contact_type, email)
    return {"data": [communication_service.preference_view(p) for p in prefs], "count": len(prefs)}


@router.put("/preferences")
def upsert_preference(data: PreferenceUpsert, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        pref = communication_service.upsert_preference(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return communication_service.preference_view(pref)


# ---------------------------------------------------------------------------
# Automatisation
# ---------------------------------------------------------------------------
@router.get("/scenarios")
def list_scenarios(db: Session = Depends(get_db), current_user=Depends(require_read)):
    scenarios = communication_service.list_scenarios(db)
    return {"data": [communication_service.scenario_view(s) for s in scenarios], "count": len(scenarios)}


@router.post("/scenarios", status_code=201)
def create_scenario(data: ScenarioCreate, db: Session = Depends(get_db), current_user=Depends(require_write)):
    try:
        scenario = communication_service.create_scenario(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return communication_service.scenario_view(scenario)


@router.put("/scenarios/{scenario_id}")
def update_scenario(
    scenario_id: int, data: ScenarioUpdate, db: Session = Depends(get_db), current_user=Depends(require_write)
):
    try:
        scenario = communication_service.update_scenario(db, scenario_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return communication_service.scenario_view(scenario)


@router.post("/scenarios/run")
def run_scenarios(
    key: Optional[str] = None, db: Session = Depends(get_db), current_user=Depends(require_write)
):
    """Exécute les scénarios échus (à déclencher par un cron)."""
    return communication_service.process_automations(db, only_key=key)


# ---------------------------------------------------------------------------
# Historique
# ---------------------------------------------------------------------------
@router.get("/history")
def history(
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
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user=Depends(require_read),
):
    rows = communication_service.search_history(
        db,
        channel=channel,
        notification_type=notification_type,
        recipient_email=recipient_email,
        property_id=property_id,
        lease_id=lease_id,
        tenant_id=tenant_id,
        owner_id=owner_id,
        deal_id=deal_id,
        q=q,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return {"data": [communication_service.outbound_view(r) for r in rows], "count": len(rows)}
