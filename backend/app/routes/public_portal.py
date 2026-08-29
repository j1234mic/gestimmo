"""Portail public / site vitrine de l'agence (Module 22).

Endpoints lisibles sans authentification pour alimenter le site vitrine :
annonces, fiches bien, agents, témoignages, CMS, actualités et formulaire de
contact / visite / estimation avec suivi par jeton.
"""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.extension import (
    PublicAgent,
    PublicLead,
    PublicLeadStatus,
    PublicNewsPost,
    PublicPage,
    PublicTestimonial,
)
from app.models.property import Property, PropertyPhoto, PropertyStatus, PropertyType
from app.schemas.extension import (
    PublicAgentResponse,
    PublicLeadCreate,
    PublicLeadPublicResponse,
    PublicNewsPostResponse,
    PublicPageResponse,
    PublicTestimonialResponse,
)
from app.services.extension_service import generate_reference, generate_tracking_token, unique_reference

router = APIRouter(prefix="/api/public-portal", tags=["Portail public / site vitrine"])


def _public_property(property_row: Property, with_details: bool = False) -> dict:
    photos = sorted(property_row.photos, key=lambda p: (p.is_main is False, p.order, p.id))
    photo_list = [
        {
            "url": p.url,
            "filename": p.filename,
            "media_type": p.media_type,
            "is_main": p.is_main,
            "is_360": p.is_360,
            "virtual_tour_url": p.virtual_tour_url,
            "order": p.order,
        }
        for p in photos
    ]
    main_photo = next((p for p in photo_list if p["media_type"] == "image" and p["is_main"]), None)
    if not main_photo:
        main_photo = next((p for p in photo_list if p["media_type"] == "image"), None)
    payload = {
        "id": property_row.id,
        "secure_id": property_row.secure_id,
        "reference": property_row.reference,
        "type": property_row.type.value if hasattr(property_row.type, "value") else property_row.type,
        "status": property_row.status.value if hasattr(property_row.status, "value") else property_row.status,
        "title": property_row.title,
        "description": property_row.description,
        "address": property_row.address,
        "postal_code": property_row.postal_code,
        "city": property_row.city,
        "lat": property_row.latitude,
        "lng": property_row.longitude,
        "living_area": property_row.living_area,
        "rooms": property_row.rooms,
        "bedrooms": property_row.bedrooms,
        "bathrooms": property_row.bathrooms,
        "rent_price": property_row.rent_price,
        "charges": property_row.charges,
        "sale_price": property_row.sale_price,
        "deposit": property_row.deposit,
        "tags": property_row.tags or [],
        "equipment": property_row.equipment or {},
        "energy_class": property_row.energy_class.value if hasattr(property_row.energy_class, "value") else property_row.energy_class,
        "ges_class": property_row.ges_class.value if hasattr(property_row.ges_class, "value") else property_row.ges_class,
        "heating_type": property_row.heating_type.value if hasattr(property_row.heating_type, "value") else property_row.heating_type,
        "construction_year": property_row.construction_year,
        "floor": property_row.floor,
        "total_floors": property_row.total_floors,
        "virtual_tour_url": property_row.virtual_tour_url,
        "is_360_available": property_row.is_360_available,
        "main_photo": main_photo,
        "photos": photo_list if with_details else photo_list[:12],
        "can_visit": bool(property_row.status in (PropertyStatus.AVAILABLE, PropertyStatus.FOR_SALE)),
        "can_apply": bool(property_row.status == PropertyStatus.AVAILABLE),
    }
    if with_details:
        payload["documents_count"] = len(property_row.documents)
        payload["created_at"] = property_row.created_at
        payload["updated_at"] = property_row.updated_at
    return payload


def _get_public_property(db: Session, identifier) -> Property:
    query = db.query(Property).filter(Property.is_active.is_(True))
    if isinstance(identifier, int) or str(identifier).isdigit():
        query = query.filter(Property.id == int(identifier))
    else:
        query = query.filter(
            or_(Property.secure_id == identifier, Property.reference == identifier)
        )
    row = query.first()
    if not row:
        raise HTTPException(status_code=404, detail="Bien introuvable sur le portail public")
    return row


@router.get("/config")
def public_config(db: Session = Depends(get_db)):
    agents = db.query(PublicAgent).filter(PublicAgent.active.is_(True)).count()
    testimonials = db.query(PublicTestimonial).filter(PublicTestimonial.published.is_(True)).count()
    news = db.query(PublicNewsPost).filter(PublicNewsPost.status == "published").count()
    return {
        "data": {
            "portal_enabled": True,
            "active_properties": db.query(Property).filter(
                Property.is_active.is_(True),
                Property.status.in_([PropertyStatus.AVAILABLE, PropertyStatus.FOR_SALE, PropertyStatus.RESERVED]),
            ).count(),
            "agents": agents,
            "testimonials": testimonials,
            "news": news,
            "contact": {"phone": None, "whatsapp": None},
        }
    }


@router.get("/properties")
def public_properties(
    city: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_area: Optional[float] = None,
    rooms: Optional[int] = None,
    tags: Optional[str] = None,
    sort: str = "created_desc",
    page: int = Query(1, ge=1),
    limit: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = db.query(Property).filter(Property.is_active.is_(True))
    if city:
        q = q.filter(Property.city.ilike(f"%{city}%"))
    if type:
        q = q.filter(Property.type == type)
    if status:
        q = q.filter(Property.status == status)
    else:
        q = q.filter(Property.status.in_([PropertyStatus.AVAILABLE, PropertyStatus.FOR_SALE, PropertyStatus.RESERVED]))
    if min_price is not None or max_price is not None:
        price_filter = []
        if min_price is not None:
            price_filter.append(Property.rent_price >= min_price)
            price_filter.append(Property.sale_price >= min_price)
        if max_price is not None:
            price_filter.append(Property.rent_price <= max_price)
            price_filter.append(Property.sale_price <= max_price)
        q = q.filter(or_(*price_filter))
    if min_area is not None:
        q = q.filter(Property.living_area >= min_area)
    if rooms is not None:
        q = q.filter(Property.rooms >= rooms)
    if tags:
        for tag in [t.strip() for t in tags.split(",") if t.strip()]:
            from sqlalchemy import cast, String
            q = q.filter(cast(Property.tags, String).ilike(f"%{tag}%"))
    total = q.count()
    if sort == "price_asc":
        q = q.order_by(Property.rent_price.asc().nulls_last(), Property.sale_price.asc().nulls_last())
    elif sort == "price_desc":
        q = q.order_by(Property.rent_price.desc().nulls_last(), Property.sale_price.desc().nulls_last())
    elif sort == "area_desc":
        q = q.order_by(Property.living_area.desc().nulls_last())
    else:
        q = q.order_by(Property.created_at.desc())
    rows = q.offset((page - 1) * limit).limit(limit).all()
    return {"data": [_public_property(r) for r in rows], "total": total, "page": page}


@router.get("/properties/{property_id}")
def public_property_detail(property_id: str, db: Session = Depends(get_db)):
    row = _get_public_property(db, property_id)
    return {"data": _public_property(row, with_details=True)}


@router.get("/agents")
def public_agents(db: Session = Depends(get_db)):
    rows = db.query(PublicAgent).filter(PublicAgent.active.is_(True)).order_by(PublicAgent.order, PublicAgent.id).all()
    return {"data": [PublicAgentResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.get("/testimonials")
def public_testimonials(db: Session = Depends(get_db)):
    rows = db.query(PublicTestimonial).filter(PublicTestimonial.published.is_(True)).order_by(PublicTestimonial.created_at.desc()).all()
    return {"data": [PublicTestimonialResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.get("/pages")
def public_pages(db: Session = Depends(get_db)):
    rows = db.query(PublicPage).filter(PublicPage.status == "published").order_by(PublicPage.title).all()
    return {"data": [PublicPageResponse.model_validate(r).model_dump() for r in rows], "total": len(rows)}


@router.get("/pages/{slug}")
def public_page(slug: str, db: Session = Depends(get_db)):
    row = db.query(PublicPage).filter(PublicPage.slug == slug, PublicPage.status == "published").first()
    if not row:
        raise HTTPException(status_code=404, detail="Page publique introuvable")
    return {"data": PublicPageResponse.model_validate(row).model_dump()}


@router.get("/news")
def public_news(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    q = db.query(PublicNewsPost).filter(PublicNewsPost.status == "published")
    total = q.count()
    rows = q.order_by(PublicNewsPost.published_at.desc().nulls_last()).offset((page - 1) * limit).limit(limit).all()
    return {"data": [PublicNewsPostResponse.model_validate(r).model_dump() for r in rows], "total": total, "page": page}


@router.get("/news/{slug}")
def public_news_post(slug: str, db: Session = Depends(get_db)):
    row = db.query(PublicNewsPost).filter(PublicNewsPost.slug == slug, PublicNewsPost.status == "published").first()
    if not row:
        raise HTTPException(status_code=404, detail="Actualité publique introuvable")
    return {"data": PublicNewsPostResponse.model_validate(row).model_dump()}


@router.post("/leads")
def create_public_lead(data: PublicLeadCreate, db: Session = Depends(get_db)):
    if data.request_type not in ("contact", "visit", "estimate", "application"):
        raise HTTPException(status_code=422, detail="Type de demande invalide")
    if data.property_id:
        property_row = db.query(Property).filter(Property.id == data.property_id, Property.is_active.is_(True)).first()
        if not property_row:
            raise HTTPException(status_code=404, detail="Bien introuvable")
    reference = unique_reference(db, PublicLead, "PUB")
    token = generate_tracking_token()
    row = PublicLead(
        reference=reference,
        tracking_token=token,
        request_type=data.request_type,
        name=data.name,
        email=data.email,
        phone=data.phone,
        property_id=data.property_id,
        message=data.message,
        preferred_date=data.preferred_date,
        status=PublicLeadStatus.NEW,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "reference": row.reference,
        "tracking_token": token,
        "status": row.status.value,
        "message": "Demande enregistrée. Conservez votre référence et votre jeton pour suivre son traitement.",
    }


def _get_public_lead(db: Session, reference: str, token: Optional[str]) -> PublicLead:
    row = db.query(PublicLead).filter(PublicLead.reference == reference).first()
    if not row or not token or row.tracking_token != token:
        raise HTTPException(status_code=404, detail="Demande ou jeton de suivi invalide")
    return row


@router.get("/leads/{reference}")
def track_public_lead(reference: str, token: str = Query(...), db: Session = Depends(get_db)):
    row = _get_public_lead(db, reference, token)
    return {"data": PublicLeadPublicResponse.model_validate(row).model_dump()}


@router.post("/leads/{reference}/cancel")
def cancel_public_lead(reference: str, token: str = Query(...), db: Session = Depends(get_db)):
    row = _get_public_lead(db, reference, token)
    if row.status in (PublicLeadStatus.CONVERTED, PublicLeadStatus.ARCHIVED):
        raise HTTPException(status_code=409, detail="Cette demande ne peut plus être annulée")
    row.status = PublicLeadStatus.ARCHIVED
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return {"message": "Demande annulée", "reference": row.reference, "status": row.status.value}
