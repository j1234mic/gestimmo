"""Dépendances FastAPI exposant les repositories hexagonalisés.

Utilisées par les routeurs de la couche ``web``. Le ``Depends(get_db)``
fournit la session SQLAlchemy ; on l'enveloppe dans le repository adaptateur.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.hexagon.container import (
    get_owner_repository,
    get_property_repository,
)
from app.hexagon.domain.ports import OwnerRepository, PropertyRepository


def property_repository_dep(
    db: Session = Depends(get_db),
) -> PropertyRepository:
    return get_property_repository(db)


def owner_repository_dep(
    db: Session = Depends(get_db),
) -> OwnerRepository:
    return get_owner_repository(db)
