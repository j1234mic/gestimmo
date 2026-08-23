"""Calculs géospatiaux internes du module 13.

Les distances/temps internes sont des estimations à vol d'oiseau, clairement
marquées comme telles dans l'API. Un fournisseur routier peut être branché
ultérieurement sans présenter ces estimations comme du guidage routier réel.
"""

import math
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.geolocation import (
    GeographicZone,
    PlannedVisit,
    PointOfInterest,
    PropertyLocationProfile,
    RoutePlan,
)
from app.models.property import Property

EARTH_RADIUS_KM = 6371.0088
DEFAULT_SPEEDS = {"driving": 35.0, "walking": 4.8, "cycling": 15.0, "transit": 25.0}
CATEGORY_LABELS = {
    "transport": "Transports en commun",
    "school": "Écoles",
    "shop": "Commerces",
    "hospital": "Hôpitaux",
    "park": "Parcs",
}
CATEGORY_WEIGHTS = {"transport": 25, "school": 20, "shop": 20, "hospital": 15, "park": 20}
IDEAL_DISTANCE_M = {"transport": 500, "school": 1000, "shop": 700, "hospital": 2500, "park": 1000}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    value = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def estimated_minutes(distance_km: float, mode: str, speed: Optional[float] = None) -> int:
    kmh = speed or DEFAULT_SPEEDS.get(mode, DEFAULT_SPEEDS["driving"])
    # Facteur de détour moyen entre distance orthodromique et réseau réel.
    network_factor = 1.25 if mode in {"driving", "cycling", "walking"} else 1.35
    return max(1, math.ceil(distance_km * network_factor / kmh * 60))


def property_feature(property_obj: Property) -> dict:
    return {
        "type": "Feature",
        "id": property_obj.id,
        "geometry": {"type": "Point", "coordinates": [property_obj.longitude, property_obj.latitude]},
        "properties": {
            "id": property_obj.id,
            "reference": property_obj.reference,
            "title": property_obj.title,
            "property_type": property_obj.type.value if hasattr(property_obj.type, "value") else property_obj.type,
            "status": property_obj.status.value if hasattr(property_obj.status, "value") else property_obj.status,
            "address": property_obj.address,
            "postal_code": property_obj.postal_code,
            "city": property_obj.city,
            "rent_price": property_obj.rent_price,
            "sale_price": property_obj.sale_price,
            "living_area": property_obj.living_area,
            "rooms": property_obj.rooms,
            "entity_id": property_obj.entity_id,
            "agency_id": property_obj.agency_id,
            "portfolio_id": property_obj.portfolio_id,
        },
    }


def map_properties(
    db: Session, *, status=None, property_type=None, city=None, entity_id=None,
    agency_id=None, portfolio_id=None, min_price=None, max_price=None,
    north=None, south=None, east=None, west=None,
) -> list[Property]:
    query = db.query(Property).filter(
        Property.is_active == True, Property.latitude.isnot(None), Property.longitude.isnot(None)
    )
    if status:
        query = query.filter(Property.status == status)
    if property_type:
        query = query.filter(Property.type == property_type)
    if city:
        query = query.filter(Property.city.ilike(f"%{city}%"))
    if entity_id is not None:
        query = query.filter(Property.entity_id == entity_id)
    if agency_id is not None:
        query = query.filter(Property.agency_id == agency_id)
    if portfolio_id is not None:
        query = query.filter(Property.portfolio_id == portfolio_id)
    if min_price is not None:
        query = query.filter(or_(Property.rent_price >= min_price, Property.sale_price >= min_price))
    if max_price is not None:
        query = query.filter(or_(Property.rent_price <= max_price, Property.sale_price <= max_price))
    if north is not None:
        query = query.filter(Property.latitude <= north)
    if south is not None:
        query = query.filter(Property.latitude >= south)
    if east is not None:
        query = query.filter(Property.longitude <= east)
    if west is not None:
        query = query.filter(Property.longitude >= west)
    return query.order_by(Property.id).all()


def cluster_properties(properties: list[Property], zoom: int) -> list[dict]:
    """Regroupe les marqueurs dans une grille dépendante du zoom."""
    if zoom >= 17:
        return [{"cluster": False, "point_count": 1, "property_ids": [p.id], "latitude": p.latitude, "longitude": p.longitude} for p in properties]
    cell_degrees = max(0.0005, 360.0 / (2 ** (zoom + 5)))
    cells: dict[tuple[int, int], list[Property]] = {}
    for prop in properties:
        key = (math.floor((prop.latitude + 90) / cell_degrees), math.floor((prop.longitude + 180) / cell_degrees))
        cells.setdefault(key, []).append(prop)
    clusters = []
    for points in cells.values():
        clusters.append({
            "cluster": len(points) > 1,
            "point_count": len(points),
            "property_ids": [point.id for point in points],
            "latitude": round(sum(point.latitude for point in points) / len(points), 7),
            "longitude": round(sum(point.longitude for point in points) / len(points), 7),
        })
    return clusters


def nearby_pois(
    db: Session, latitude: float, longitude: float, radius_m: int = 2000,
    categories: Optional[list[str]] = None, entity_id: Optional[int] = None,
) -> list[dict]:
    lat_delta = radius_m / 111_320
    lon_divisor = max(0.1, math.cos(math.radians(latitude)))
    lon_delta = radius_m / (111_320 * lon_divisor)
    query = db.query(PointOfInterest).filter(
        PointOfInterest.is_active == True,
        PointOfInterest.latitude.between(latitude - lat_delta, latitude + lat_delta),
        PointOfInterest.longitude.between(longitude - lon_delta, longitude + lon_delta),
    )
    if categories:
        query = query.filter(PointOfInterest.category.in_(categories))
    if entity_id is not None:
        query = query.filter(or_(PointOfInterest.entity_id == entity_id, PointOfInterest.entity_id.is_(None)))
    results = []
    for poi in query.all():
        distance_m = round(haversine_km(latitude, longitude, poi.latitude, poi.longitude) * 1000)
        if distance_m <= radius_m:
            results.append({
                "id": poi.id, "name": poi.name, "category": poi.category,
                "category_label": CATEGORY_LABELS.get(poi.category, poi.category),
                "subcategory": poi.subcategory, "address": poi.address,
                "latitude": poi.latitude, "longitude": poi.longitude,
                "distance_m": distance_m, "provider": poi.provider,
                "metadata": poi.metadata_json or {},
            })
    return sorted(results, key=lambda item: item["distance_m"])


def calculate_location_score(db: Session, prop: Property, radius_m: int = 3000) -> dict:
    if prop.latitude is None or prop.longitude is None:
        raise ValueError("Le bien n'est pas géolocalisé")
    pois = nearby_pois(db, prop.latitude, prop.longitude, radius_m, entity_id=prop.entity_id)
    details = {}
    total = 0.0
    for category, weight in CATEGORY_WEIGHTS.items():
        candidates = [poi for poi in pois if poi["category"] == category]
        nearest = candidates[0] if candidates else None
        if nearest:
            ratio = max(0.0, 1.0 - nearest["distance_m"] / (IDEAL_DISTANCE_M[category] * 3))
            category_points = round(weight * ratio, 2)
        else:
            category_points = 0.0
        total += category_points
        details[category] = {
            "label": CATEGORY_LABELS[category], "weight": weight,
            "points": category_points,
            "nearest_distance_m": nearest["distance_m"] if nearest else None,
            "nearest_name": nearest["name"] if nearest else None,
            "count_in_radius": len(candidates),
        }
    score = round(min(100.0, total), 1)
    profile = db.query(PropertyLocationProfile).filter(PropertyLocationProfile.property_id == prop.id).first()
    if not profile:
        profile = PropertyLocationProfile(property_id=prop.id)
        db.add(profile)
    profile.location_score = score
    profile.score_details = details
    profile.poi_radius_m = radius_m
    profile.last_scored_at = datetime.utcnow()
    db.commit()
    return {
        "property_id": prop.id, "score": score, "maximum": 100,
        "details": details, "method": "weighted_nearest_poi_v1", "radius_m": radius_m,
        "poi_dataset_count": len(pois),
    }


def point_in_polygon(latitude: float, longitude: float, polygon: dict) -> bool:
    """Ray casting sur l'anneau extérieur GeoJSON [longitude, latitude]."""
    ring = polygon.get("coordinates", [[]])[0]
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        intersects = ((yi > latitude) != (yj > latitude)) and (
            longitude < (xj - xi) * (latitude - yi) / ((yj - yi) or 1e-15) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def polygon_center(polygon: dict) -> tuple[float, float]:
    ring = polygon["coordinates"][0]
    points = ring[:-1] if ring[0] == ring[-1] else ring
    return (
        sum(position[1] for position in points) / len(points),
        sum(position[0] for position in points) / len(points),
    )


def assign_properties_to_zones(db: Session, entity_id: Optional[int] = None) -> dict:
    zone_query = db.query(GeographicZone).filter(GeographicZone.is_active == True)
    prop_query = db.query(Property).filter(
        Property.is_active == True, Property.latitude.isnot(None), Property.longitude.isnot(None)
    )
    if entity_id is not None:
        zone_query = zone_query.filter(GeographicZone.entity_id == entity_id)
        prop_query = prop_query.filter(Property.entity_id == entity_id)
    zones = zone_query.all()
    assigned = 0
    unassigned = 0
    for prop in prop_query.all():
        zone = next((
            z for z in zones
            if (z.agency_id is None or z.agency_id == prop.agency_id)
            and point_in_polygon(prop.latitude, prop.longitude, z.polygon)
        ), None)
        profile = db.query(PropertyLocationProfile).filter(PropertyLocationProfile.property_id == prop.id).first()
        if not profile:
            profile = PropertyLocationProfile(property_id=prop.id)
            db.add(profile)
        profile.zone_id = zone.id if zone else None
        assigned += bool(zone)
        unassigned += not bool(zone)
    db.commit()
    return {"assigned": assigned, "unassigned": unassigned, "zones_checked": len(zones)}


def zone_statistics(db: Session, zone: GeographicZone) -> dict:
    query = db.query(Property).filter(
        Property.is_active == True, Property.latitude.isnot(None), Property.longitude.isnot(None)
    )
    if zone.entity_id is not None:
        query = query.filter(Property.entity_id == zone.entity_id)
    if zone.agency_id is not None:
        query = query.filter(Property.agency_id == zone.agency_id)
    properties = query.all()
    inside = [prop for prop in properties if point_in_polygon(prop.latitude, prop.longitude, zone.polygon)]
    by_status = {}
    by_type = {}
    rent_values = []
    sale_values = []
    for prop in inside:
        status = prop.status.value if hasattr(prop.status, "value") else str(prop.status)
        prop_type = prop.type.value if hasattr(prop.type, "value") else str(prop.type)
        by_status[status] = by_status.get(status, 0) + 1
        by_type[prop_type] = by_type.get(prop_type, 0) + 1
        if prop.rent_price is not None:
            rent_values.append(prop.rent_price)
        if prop.sale_price is not None:
            sale_values.append(prop.sale_price)
    return {
        "zone_id": zone.id, "zone": zone.name, "property_count": len(inside),
        "property_ids": [prop.id for prop in inside], "by_status": by_status, "by_type": by_type,
        "average_rent": round(sum(rent_values) / len(rent_values), 2) if rent_values else None,
        "average_sale_price": round(sum(sale_values) / len(sale_values), 2) if sale_values else None,
        "total_monthly_rent": round(sum(rent_values), 2),
    }


def optimize_route(
    db: Session, visits: list[PlannedVisit], start: dict, end: Optional[dict],
    mode: str, return_to_start: bool,
) -> dict:
    enriched = []
    for visit in visits:
        prop = db.query(Property).filter(Property.id == visit.property_id, Property.is_active == True).first()
        if not prop:
            raise ValueError(f"Bien de la visite {visit.id} introuvable")
        if prop.latitude is None or prop.longitude is None:
            raise ValueError(f"Le bien {prop.id} n'est pas géolocalisé")
        enriched.append((visit, prop))
    current = (start["latitude"], start["longitude"])
    remaining = enriched[:]
    ordered = []
    total_distance = 0.0
    total_minutes = 0
    current_time = min((visit.starts_at.replace(tzinfo=None) for visit, _ in enriched), default=datetime.utcnow())
    while remaining:
        visit, prop = min(
            remaining,
            key=lambda pair: haversine_km(current[0], current[1], pair[1].latitude, pair[1].longitude),
        )
        remaining.remove((visit, prop))
        distance = haversine_km(current[0], current[1], prop.latitude, prop.longitude)
        travel = estimated_minutes(distance, mode)
        arrival = current_time + timedelta(minutes=travel)
        scheduled = visit.starts_at.replace(tzinfo=None)
        wait = max(0, math.ceil((scheduled - arrival).total_seconds() / 60))
        delay = max(0, math.ceil((arrival - scheduled).total_seconds() / 60))
        if wait:
            arrival += timedelta(minutes=wait)
        departure = arrival + timedelta(minutes=visit.duration_minutes)
        ordered.append({
            "order": len(ordered) + 1, "visit_id": visit.id, "property_id": prop.id,
            "property_reference": prop.reference, "title": prop.title, "address": prop.address,
            "latitude": prop.latitude, "longitude": prop.longitude,
            "distance_from_previous_km": round(distance, 2), "travel_minutes": travel,
            "estimated_arrival": arrival.isoformat(), "estimated_departure": departure.isoformat(),
            "scheduled_at": scheduled.isoformat(), "wait_minutes": wait, "estimated_delay_minutes": delay,
        })
        total_distance += distance
        total_minutes += travel
        current = (prop.latitude, prop.longitude)
        current_time = departure
    destination = start if return_to_start else end
    if destination:
        distance = haversine_km(current[0], current[1], destination["latitude"], destination["longitude"])
        total_distance += distance
        total_minutes += estimated_minutes(distance, mode)
    return {
        "ordered_stops": ordered,
        "total_distance_km": round(total_distance, 2),
        "total_travel_minutes": total_minutes,
        "total_visit_minutes": sum(visit.duration_minutes for visit in visits),
        "estimated_total_minutes": total_minutes + sum(visit.duration_minutes for visit in visits),
        "optimization_method": "nearest_neighbor_haversine",
        "provider": "internal_estimate",
        "disclaimer": "Distances à vol d'oiseau avec facteur de détour ; elles ne remplacent pas un moteur routier.",
    }
