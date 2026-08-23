"""Modèles du module 13 : géolocalisation et cartographie."""

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class PointOfInterest(Base):
    __tablename__ = "geo_points_of_interest"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(150), index=True)
    provider = Column(String(40), default="manual")
    name = Column(String(255), nullable=False)
    category = Column(String(30), nullable=False, index=True)  # transport | school | shop | hospital | park
    subcategory = Column(String(80))
    address = Column(String(500))
    city = Column(String(120), index=True)
    latitude = Column(Float, nullable=False, index=True)
    longitude = Column(Float, nullable=False, index=True)
    metadata_json = Column("metadata", JSON, default=dict)
    entity_id = Column(Integer, index=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class GeographicZone(Base):
    __tablename__ = "geo_zones"

    id = Column(Integer, primary_key=True, index=True)
    entity_id = Column(Integer, index=True)
    agency_id = Column(Integer, index=True)
    name = Column(String(255), nullable=False)
    code = Column(String(50), index=True)
    description = Column(Text)
    color = Column(String(20), default="#1f6feb")
    polygon = Column(JSON, nullable=False)  # GeoJSON Polygon: [[[lon, lat], ...]]
    center_latitude = Column(Float)
    center_longitude = Column(Float)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class ZoneAgentAssignment(Base):
    __tablename__ = "geo_zone_agents"
    __table_args__ = (UniqueConstraint("zone_id", "user_id", name="uq_geo_zone_agent"),)

    id = Column(Integer, primary_key=True)
    zone_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    assigned_by = Column(String(255))


class PropertyLocationProfile(Base):
    """Cache du score et préférences de mobilité d'un bien."""

    __tablename__ = "geo_property_profiles"
    __table_args__ = (UniqueConstraint("property_id", name="uq_geo_property_profile"),)

    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, nullable=False, index=True)
    zone_id = Column(Integer, index=True)
    location_score = Column(Float)
    score_details = Column(JSON, default=dict)
    poi_radius_m = Column(Integer, default=2000)
    last_scored_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PlannedVisit(Base):
    __tablename__ = "geo_planned_visits"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, nullable=False, index=True)
    agent_user_id = Column(Integer, index=True)
    visitor_name = Column(String(255))
    visitor_phone = Column(String(40))
    starts_at = Column(DateTime(timezone=True), nullable=False, index=True)
    duration_minutes = Column(Integer, default=30, nullable=False)
    status = Column(String(30), default="planned", nullable=False, index=True)
    notes = Column(Text)
    entity_id = Column(Integer, index=True)
    agency_id = Column(Integer, index=True)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class RoutePlan(Base):
    __tablename__ = "geo_route_plans"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    agent_user_id = Column(Integer, index=True)
    route_date = Column(String(10), nullable=False, index=True)
    travel_mode = Column(String(20), default="driving")
    start_point = Column(JSON, nullable=False)
    end_point = Column(JSON)
    ordered_stops = Column(JSON, default=list)
    total_distance_km = Column(Float, default=0)
    total_travel_minutes = Column(Integer, default=0)
    optimization_method = Column(String(50), default="nearest_neighbor_haversine")
    provider = Column(String(50), default="internal_estimate")
    entity_id = Column(Integer, index=True)
    agency_id = Column(Integer, index=True)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
