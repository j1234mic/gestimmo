"""API du module 13 : carte, proximité, zones et tournées."""

from datetime import date, datetime, time, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth import GranularPermissionChecker
from app.database import get_db
from app.models.admin_security import AdminUser
from app.models.geolocation import (
    GeographicZone,
    PlannedVisit,
    PointOfInterest,
    PropertyLocationProfile,
    RoutePlan,
    ZoneAgentAssignment,
)
from app.models.property import Property
from app.schemas.geolocation import (
    AgentAssignment,
    POICreate,
    PropertyGeocodeUpdate,
    RouteOptimizeRequest,
    TravelTimeRequest,
    VisitCreate,
    VisitUpdate,
    ZoneCreate,
    ZoneUpdate,
)
from app.services import admin_security_service, geolocation_service as service

router = APIRouter(prefix="/api/geolocation", tags=["Géolocalisation et cartographie"])
geo_read = GranularPermissionChecker("geolocation", "read")
geo_create = GranularPermissionChecker("geolocation", "create")
geo_update = GranularPermissionChecker("geolocation", "update")
geo_delete = GranularPermissionChecker("geolocation", "delete")


def _property(db: Session, property_id: int) -> Property:
    row = db.query(Property).filter(Property.id == property_id, Property.is_active == True).first()
    if not row:
        raise HTTPException(status_code=404, detail="Bien introuvable")
    return row


def _zone(db: Session, zone_id: int) -> GeographicZone:
    row = db.query(GeographicZone).filter(GeographicZone.id == zone_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Zone introuvable")
    return row


def _unrestricted(user) -> bool:
    return user.is_superuser or any(
        permission.get("module") in {"*", "geolocation"} and permission.get("scope_type") == "all"
        for permission in user.granular_permissions
    )


def _scope_allowed(user, entity_id: Optional[int], agency_id: Optional[int]) -> bool:
    if _unrestricted(user):
        return True
    if entity_id is not None and entity_id not in user.organization_ids:
        return False
    if (
        agency_id is not None
        and entity_id not in user.organization_wide_ids
        and agency_id not in user.agency_ids
    ):
        return False
    return entity_id is not None or agency_id is not None


def _filter_scoped_properties(properties: list[Property], user) -> list[Property]:
    if _unrestricted(user):
        return properties
    return [
        prop for prop in properties
        if any(
            prop.entity_id == scope["organization_id"]
            and (scope["agency_id"] is None or prop.agency_id == scope["agency_id"])
            and (not scope["portfolio_ids"] or prop.portfolio_id in scope["portfolio_ids"])
            for scope in user.data_scopes
        )
    ]


def _zone_view(zone: GeographicZone, db: Session, with_agents: bool = False) -> dict:
    data = admin_security_service.model_dict(zone)
    data["geojson"] = {"type": "Feature", "id": zone.id, "geometry": zone.polygon, "properties": {
        "name": zone.name, "code": zone.code, "color": zone.color,
    }}
    if with_agents:
        assignments = db.query(ZoneAgentAssignment).filter(ZoneAgentAssignment.zone_id == zone.id).all()
        data["agents"] = []
        for assignment in assignments:
            user = db.query(AdminUser).filter(AdminUser.id == assignment.user_id).first()
            data["agents"].append({
                "assignment_id": assignment.id, "user_id": assignment.user_id,
                "name": user.full_name if user else None, "email": user.email if user else None,
                "is_primary": assignment.is_primary,
            })
    return data


# ---------------------------------------------------------------------------
# Carte interactive et filtres dynamiques
# ---------------------------------------------------------------------------
@router.get("/map/config")
def map_config(current_user=Depends(geo_read)):
    return {
        "default_view": "plan",
        "layers": {
            "plan": {
                "name": "OpenStreetMap",
                "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                "attribution": "© OpenStreetMap contributors",
            },
            "satellite": {
                "name": "Esri World Imagery",
                "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                "attribution": "Tiles © Esri",
            },
        },
        "supports_clustering": True,
        "coordinate_system": "WGS84 / EPSG:4326",
    }


@router.get("/map/properties")
def property_map(
    status: Optional[str] = None, property_type: Optional[str] = None, city: Optional[str] = None,
    entity_id: Optional[int] = None, agency_id: Optional[int] = None, portfolio_id: Optional[int] = None,
    min_price: Optional[float] = None, max_price: Optional[float] = None,
    north: Optional[float] = Query(None, ge=-90, le=90), south: Optional[float] = Query(None, ge=-90, le=90),
    east: Optional[float] = Query(None, ge=-180, le=180), west: Optional[float] = Query(None, ge=-180, le=180),
    cluster: bool = True, zoom: int = Query(12, ge=1, le=22),
    db: Session = Depends(get_db), current_user=Depends(geo_read),
):
    if entity_id is not None and not _scope_allowed(current_user, entity_id, agency_id):
        raise HTTPException(status_code=403, detail="Périmètre société/agence non autorisé")
    properties = service.map_properties(
        db, status=status, property_type=property_type, city=city, entity_id=entity_id,
        agency_id=agency_id, portfolio_id=portfolio_id, min_price=min_price, max_price=max_price,
        north=north, south=south, east=east, west=west,
    )
    properties = _filter_scoped_properties(properties, current_user)
    features = [service.property_feature(prop) for prop in properties]
    result = {
        "type": "FeatureCollection", "features": features, "count": len(features),
        "filters_applied": {
            "status": status, "property_type": property_type, "city": city,
            "entity_id": entity_id, "agency_id": agency_id, "portfolio_id": portfolio_id,
            "min_price": min_price, "max_price": max_price,
        },
    }
    if cluster:
        result["clusters"] = service.cluster_properties(properties, zoom)
        result["zoom"] = zoom
    return result


@router.put("/properties/{property_id}/coordinates")
def update_coordinates(
    property_id: int, data: PropertyGeocodeUpdate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(geo_update),
):
    prop = _property(db, property_id)
    if not _scope_allowed(current_user, prop.entity_id, prop.agency_id):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")
    before = {"latitude": prop.latitude, "longitude": prop.longitude}
    prop.latitude = data.latitude
    prop.longitude = data.longitude
    admin_security_service.log_audit(
        db, actor=current_user, action="geolocate", module="geolocation", resource_type="property",
        resource_id=prop.id, before=before,
        after={"latitude": prop.latitude, "longitude": prop.longitude, "source": data.source},
        request=request, organization_id=prop.entity_id, agency_id=prop.agency_id,
    )
    db.commit()
    return service.property_feature(prop)


# ---------------------------------------------------------------------------
# Fiche bien : POI, temps de trajet et score
# ---------------------------------------------------------------------------
@router.post("/points-of-interest", status_code=201)
def create_poi(data: POICreate, db: Session = Depends(get_db), current_user=Depends(geo_create)):
    if data.entity_id is not None and not _scope_allowed(current_user, data.entity_id, None):
        raise HTTPException(status_code=403, detail="Société hors périmètre")
    values = data.model_dump(exclude={"metadata"})
    poi = PointOfInterest(**values, metadata_json=data.metadata)
    db.add(poi)
    db.commit()
    db.refresh(poi)
    return admin_security_service.model_dict(poi)


@router.post("/points-of-interest/batch", status_code=201)
def create_poi_batch(
    data: List[POICreate], db: Session = Depends(get_db), current_user=Depends(geo_create)
):
    if len(data) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 points par lot")
    if any(item.entity_id is not None and not _scope_allowed(current_user, item.entity_id, None) for item in data):
        raise HTTPException(status_code=403, detail="Un point d'intérêt est hors périmètre")
    rows = []
    for item in data:
        values = item.model_dump(exclude={"metadata"})
        row = PointOfInterest(**values, metadata_json=item.metadata)
        db.add(row)
        rows.append(row)
    db.commit()
    return {"created": len(rows), "ids": [row.id for row in rows]}


@router.get("/points-of-interest")
def list_pois(
    category: Optional[str] = None, city: Optional[str] = None, entity_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db), current_user=Depends(geo_read),
):
    query = db.query(PointOfInterest).filter(PointOfInterest.is_active == True)
    if not _unrestricted(current_user):
        query = query.filter(or_(
            PointOfInterest.entity_id.in_(current_user.organization_ids),
            PointOfInterest.entity_id.is_(None),
        ))
    if category:
        query = query.filter(PointOfInterest.category == category)
    if city:
        query = query.filter(PointOfInterest.city.ilike(f"%{city}%"))
    if entity_id is not None:
        if not _scope_allowed(current_user, entity_id, None):
            raise HTTPException(status_code=403, detail="Société hors périmètre")
        query = query.filter(PointOfInterest.entity_id == entity_id)
    rows = query.order_by(PointOfInterest.name).limit(limit).all()
    return {"data": [admin_security_service.model_dict(row) for row in rows], "count": len(rows)}


@router.get("/properties/{property_id}/location")
def property_location(
    property_id: int, radius_m: int = Query(2000, ge=100, le=20000),
    categories: Optional[str] = None,
    db: Session = Depends(get_db), current_user=Depends(geo_read),
):
    prop = _property(db, property_id)
    if not _scope_allowed(current_user, prop.entity_id, prop.agency_id):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")
    if prop.latitude is None or prop.longitude is None:
        raise HTTPException(status_code=422, detail="Le bien n'est pas géolocalisé")
    category_list = [value.strip() for value in categories.split(",")] if categories else None
    pois = service.nearby_pois(
        db, prop.latitude, prop.longitude, radius_m, category_list, prop.entity_id
    )
    profile = db.query(PropertyLocationProfile).filter(PropertyLocationProfile.property_id == prop.id).first()
    grouped = {key: [] for key in service.CATEGORY_LABELS}
    for poi in pois:
        grouped.setdefault(poi["category"], []).append(poi)
    return {
        "property": service.property_feature(prop), "radius_m": radius_m,
        "points_of_interest": pois, "by_category": grouped,
        "location_score": profile.location_score if profile else None,
        "score_details": profile.score_details if profile else None,
        "zone_id": profile.zone_id if profile else None,
    }


@router.post("/properties/{property_id}/location-score")
def location_score(
    property_id: int, radius_m: int = Query(3000, ge=500, le=20000),
    db: Session = Depends(get_db), current_user=Depends(geo_update),
):
    prop = _property(db, property_id)
    if not _scope_allowed(current_user, prop.entity_id, prop.agency_id):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")
    try:
        return service.calculate_location_score(db, prop, radius_m)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/properties/{property_id}/travel-time")
def travel_time(
    property_id: int, data: TravelTimeRequest,
    db: Session = Depends(get_db), current_user=Depends(geo_read),
):
    prop = _property(db, property_id)
    if not _scope_allowed(current_user, prop.entity_id, prop.agency_id):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")
    if prop.latitude is None or prop.longitude is None:
        raise HTTPException(status_code=422, detail="Le bien n'est pas géolocalisé")
    distance = service.haversine_km(
        prop.latitude, prop.longitude, data.destination.latitude, data.destination.longitude
    )
    return {
        "property_id": prop.id, "travel_mode": data.travel_mode,
        "distance_km": round(distance, 2),
        "estimated_minutes": service.estimated_minutes(distance, data.travel_mode, data.average_speed_kmh),
        "provider": "internal_estimate", "route_geometry": {
            "type": "LineString",
            "coordinates": [[prop.longitude, prop.latitude], [data.destination.longitude, data.destination.latitude]],
        },
        "disclaimer": "Estimation à vol d'oiseau avec facteur de détour, sans trafic temps réel.",
    }


# ---------------------------------------------------------------------------
# Zones et agents
# ---------------------------------------------------------------------------
@router.post("/zones", status_code=201)
def create_zone(
    data: ZoneCreate, request: Request, db: Session = Depends(get_db), current_user=Depends(geo_create)
):
    if not _scope_allowed(current_user, data.entity_id, data.agency_id):
        raise HTTPException(status_code=403, detail="Périmètre société/agence non autorisé")
    latitude, longitude = service.polygon_center(data.polygon)
    zone = GeographicZone(
        **data.model_dump(exclude={"polygon"}), polygon=data.polygon,
        center_latitude=latitude, center_longitude=longitude,
    )
    db.add(zone)
    db.flush()
    admin_security_service.log_audit(
        db, actor=current_user, action="create", module="geolocation", resource_type="zone",
        resource_id=zone.id, after=admin_security_service.model_dict(zone), request=request,
        organization_id=zone.entity_id, agency_id=zone.agency_id,
    )
    db.commit()
    return _zone_view(zone, db, True)


@router.get("/zones")
def list_zones(
    entity_id: Optional[int] = None, agency_id: Optional[int] = None, active_only: bool = True,
    db: Session = Depends(get_db), current_user=Depends(geo_read),
):
    query = db.query(GeographicZone)
    if entity_id is not None:
        query = query.filter(GeographicZone.entity_id == entity_id)
    if agency_id is not None:
        query = query.filter(GeographicZone.agency_id == agency_id)
    if active_only:
        query = query.filter(GeographicZone.is_active == True)
    rows = query.order_by(GeographicZone.name).all()
    if not _unrestricted(current_user):
        rows = [zone for zone in rows if _scope_allowed(current_user, zone.entity_id, zone.agency_id)]
    return {
        "type": "FeatureCollection", "features": [_zone_view(zone, db)["geojson"] for zone in rows],
        "data": [_zone_view(zone, db, True) for zone in rows], "count": len(rows),
    }


@router.get("/zones/{zone_id}")
def get_zone(zone_id: int, db: Session = Depends(get_db), current_user=Depends(geo_read)):
    zone = _zone(db, zone_id)
    if not _scope_allowed(current_user, zone.entity_id, zone.agency_id):
        raise HTTPException(status_code=403, detail="Zone hors périmètre")
    result = _zone_view(zone, db, True)
    result["statistics"] = service.zone_statistics(db, zone)
    return result


@router.put("/zones/{zone_id}")
def update_zone(
    zone_id: int, data: ZoneUpdate, request: Request,
    db: Session = Depends(get_db), current_user=Depends(geo_update),
):
    zone = _zone(db, zone_id)
    if not _scope_allowed(current_user, zone.entity_id, zone.agency_id):
        raise HTTPException(status_code=403, detail="Zone hors périmètre")
    before = admin_security_service.model_dict(zone)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(zone, field, value)
    if data.polygon is not None:
        zone.center_latitude, zone.center_longitude = service.polygon_center(data.polygon)
    db.flush()
    admin_security_service.log_audit(
        db, actor=current_user, action="update", module="geolocation", resource_type="zone",
        resource_id=zone.id, before=before, after=admin_security_service.model_dict(zone), request=request,
        organization_id=zone.entity_id, agency_id=zone.agency_id,
    )
    db.commit()
    return _zone_view(zone, db, True)


@router.delete("/zones/{zone_id}")
def delete_zone(
    zone_id: int, request: Request, db: Session = Depends(get_db), current_user=Depends(geo_delete)
):
    zone = _zone(db, zone_id)
    if not _scope_allowed(current_user, zone.entity_id, zone.agency_id):
        raise HTTPException(status_code=403, detail="Zone hors périmètre")
    zone.is_active = False
    admin_security_service.log_audit(
        db, actor=current_user, action="delete", module="geolocation", resource_type="zone",
        resource_id=zone.id, request=request, organization_id=zone.entity_id, agency_id=zone.agency_id,
    )
    db.commit()
    return {"deleted": True, "id": zone.id}


@router.post("/zones/{zone_id}/agents", status_code=201)
def assign_agent(
    zone_id: int, data: AgentAssignment, db: Session = Depends(get_db), current_user=Depends(geo_update)
):
    zone = _zone(db, zone_id)
    if not _scope_allowed(current_user, zone.entity_id, zone.agency_id):
        raise HTTPException(status_code=403, detail="Zone hors périmètre")
    agent = db.query(AdminUser).filter(AdminUser.id == data.user_id, AdminUser.is_active == True).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent introuvable")
    if zone.entity_id is not None and not agent.is_superuser and not any(
        scope.organization_id == zone.entity_id
        and (scope.agency_id is None or zone.agency_id is None or scope.agency_id == zone.agency_id)
        for scope in agent.scopes
    ):
        raise HTTPException(status_code=400, detail="L'agent n'a pas accès au périmètre de la zone")
    existing = db.query(ZoneAgentAssignment).filter(
        ZoneAgentAssignment.zone_id == zone_id, ZoneAgentAssignment.user_id == data.user_id
    ).first()
    if existing:
        existing.is_primary = data.is_primary
        assignment = existing
    else:
        assignment = ZoneAgentAssignment(
            zone_id=zone_id, user_id=data.user_id, is_primary=data.is_primary,
            assigned_by=current_user.email,
        )
        db.add(assignment)
    if data.is_primary:
        db.query(ZoneAgentAssignment).filter(
            ZoneAgentAssignment.zone_id == zone_id,
            ZoneAgentAssignment.user_id != data.user_id,
        ).update({"is_primary": False}, synchronize_session=False)
    db.commit()
    db.refresh(assignment)
    return admin_security_service.model_dict(assignment)


@router.delete("/zones/{zone_id}/agents/{user_id}")
def unassign_agent(
    zone_id: int, user_id: int, db: Session = Depends(get_db), current_user=Depends(geo_update)
):
    zone = _zone(db, zone_id)
    if not _scope_allowed(current_user, zone.entity_id, zone.agency_id):
        raise HTTPException(status_code=403, detail="Zone hors périmètre")
    deleted = db.query(ZoneAgentAssignment).filter(
        ZoneAgentAssignment.zone_id == zone_id, ZoneAgentAssignment.user_id == user_id
    ).delete(synchronize_session=False)
    db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Affectation introuvable")
    return {"deleted": True}


@router.get("/zones/{zone_id}/statistics")
def zone_statistics(zone_id: int, db: Session = Depends(get_db), current_user=Depends(geo_read)):
    zone = _zone(db, zone_id)
    if not _scope_allowed(current_user, zone.entity_id, zone.agency_id):
        raise HTTPException(status_code=403, detail="Zone hors périmètre")
    return service.zone_statistics(db, zone)


@router.post("/zones/assign-properties")
def recalculate_zone_assignments(
    entity_id: Optional[int] = None, db: Session = Depends(get_db), current_user=Depends(geo_update)
):
    if entity_id is not None and not _scope_allowed(current_user, entity_id, None):
        raise HTTPException(status_code=403, detail="Société hors périmètre")
    if entity_id is not None or _unrestricted(current_user):
        return service.assign_properties_to_zones(db, entity_id)
    results = [service.assign_properties_to_zones(db, allowed_id) for allowed_id in current_user.organization_ids]
    return {
        "assigned": sum(item["assigned"] for item in results),
        "unassigned": sum(item["unassigned"] for item in results),
        "zones_checked": sum(item["zones_checked"] for item in results),
        "entities": len(results),
    }


# ---------------------------------------------------------------------------
# Planification des visites et optimisation des tournées
# ---------------------------------------------------------------------------
@router.post("/visits", status_code=201)
def create_visit(data: VisitCreate, db: Session = Depends(get_db), current_user=Depends(geo_create)):
    prop = _property(db, data.property_id)
    entity_id = data.entity_id if data.entity_id is not None else prop.entity_id
    agency_id = data.agency_id if data.agency_id is not None else prop.agency_id
    if not _scope_allowed(current_user, entity_id, agency_id):
        raise HTTPException(status_code=403, detail="Bien hors périmètre")
    if data.agent_user_id and not db.query(AdminUser).filter(
        AdminUser.id == data.agent_user_id, AdminUser.is_active == True
    ).first():
        raise HTTPException(status_code=404, detail="Agent introuvable")
    visit = PlannedVisit(
        **data.model_dump(exclude={"entity_id", "agency_id"}),
        entity_id=entity_id, agency_id=agency_id, created_by=current_user.email,
    )
    db.add(visit)
    db.commit()
    db.refresh(visit)
    return admin_security_service.model_dict(visit)


@router.get("/visits")
def list_visits(
    day: Optional[date] = None, agent_user_id: Optional[int] = None,
    status: Optional[str] = None, entity_id: Optional[int] = None, agency_id: Optional[int] = None,
    db: Session = Depends(get_db), current_user=Depends(geo_read),
):
    query = db.query(PlannedVisit)
    if day:
        start_of_day = datetime.combine(day, time.min)
        query = query.filter(
            PlannedVisit.starts_at >= start_of_day,
            PlannedVisit.starts_at < start_of_day + timedelta(days=1),
        )
    if agent_user_id is not None:
        query = query.filter(PlannedVisit.agent_user_id == agent_user_id)
    if status:
        query = query.filter(PlannedVisit.status == status)
    if entity_id is not None:
        query = query.filter(PlannedVisit.entity_id == entity_id)
    if agency_id is not None:
        query = query.filter(PlannedVisit.agency_id == agency_id)
    rows = query.order_by(PlannedVisit.starts_at).all()
    if not _unrestricted(current_user):
        rows = [row for row in rows if _scope_allowed(current_user, row.entity_id, row.agency_id)]
    data = []
    for row in rows:
        item = admin_security_service.model_dict(row)
        prop = db.query(Property).filter(Property.id == row.property_id).first()
        item["property"] = service.property_feature(prop) if prop and prop.latitude is not None and prop.longitude is not None else None
        data.append(item)
    return {"data": data, "count": len(data)}


@router.put("/visits/{visit_id}")
def update_visit(
    visit_id: int, data: VisitUpdate, db: Session = Depends(get_db), current_user=Depends(geo_update)
):
    visit = db.query(PlannedVisit).filter(PlannedVisit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visite introuvable")
    if not _scope_allowed(current_user, visit.entity_id, visit.agency_id):
        raise HTTPException(status_code=403, detail="Visite hors périmètre")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(visit, field, value)
    db.commit()
    return admin_security_service.model_dict(visit)


@router.post("/routes/optimize", status_code=201)
def optimize_route(
    data: RouteOptimizeRequest, db: Session = Depends(get_db), current_user=Depends(geo_create)
):
    visits = db.query(PlannedVisit).filter(PlannedVisit.id.in_(data.visit_ids)).all()
    if len(visits) != len(set(data.visit_ids)):
        raise HTTPException(status_code=404, detail="Une ou plusieurs visites sont introuvables")
    if any(not _scope_allowed(current_user, visit.entity_id, visit.agency_id) for visit in visits):
        raise HTTPException(status_code=403, detail="Une visite est hors périmètre")
    try:
        result = service.optimize_route(
            db, visits, data.start.model_dump(), data.end.model_dump() if data.end else None,
            data.travel_mode, data.return_to_start,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    first = visits[0]
    route = RoutePlan(
        name=data.name, agent_user_id=data.agent_user_id,
        route_date=data.route_date or min(visit.starts_at for visit in visits).date().isoformat(),
        travel_mode=data.travel_mode, start_point=data.start.model_dump(),
        end_point=data.end.model_dump() if data.end else (data.start.model_dump() if data.return_to_start else None),
        ordered_stops=result["ordered_stops"], total_distance_km=result["total_distance_km"],
        total_travel_minutes=result["total_travel_minutes"],
        optimization_method=result["optimization_method"], provider=result["provider"],
        entity_id=first.entity_id, agency_id=first.agency_id, created_by=current_user.email,
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    return {**admin_security_service.model_dict(route), **result}


@router.get("/routes")
def list_routes(
    route_date: Optional[str] = None, agent_user_id: Optional[int] = None,
    db: Session = Depends(get_db), current_user=Depends(geo_read),
):
    query = db.query(RoutePlan)
    if route_date:
        query = query.filter(RoutePlan.route_date == route_date)
    if agent_user_id is not None:
        query = query.filter(RoutePlan.agent_user_id == agent_user_id)
    rows = query.order_by(RoutePlan.route_date.desc(), RoutePlan.id.desc()).all()
    if not _unrestricted(current_user):
        rows = [row for row in rows if _scope_allowed(current_user, row.entity_id, row.agency_id)]
    return {"data": [admin_security_service.model_dict(row) for row in rows], "count": len(rows)}


@router.get("/routes/{route_id}")
def get_route(route_id: int, db: Session = Depends(get_db), current_user=Depends(geo_read)):
    row = db.query(RoutePlan).filter(RoutePlan.id == route_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tournée introuvable")
    if not _scope_allowed(current_user, row.entity_id, row.agency_id):
        raise HTTPException(status_code=403, detail="Tournée hors périmètre")
    return admin_security_service.model_dict(row)
