"""Composition root (racine de composition).

Point unique de câblage de l'architecture hexagonale : il relie les ports
aux adaptateurs concrets (SQLAlchemy). Les adaptateurs HTTP (FastAPI) et
les tests n'utilisent que ``get_property_repository`` / ``get_owner_repository``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.hexagon.domain.ports import OwnerRepository, PropertyRepository
from app.hexagon.infrastructure.persistence.repositories import (
    SqlAlchemyOwnerRepository,
    SqlAlchemyPropertyRepository,
)


def get_property_repository(db: Session) -> PropertyRepository:
    return SqlAlchemyPropertyRepository(db)


def get_owner_repository(db: Session) -> OwnerRepository:
    return SqlAlchemyOwnerRepository(db)
