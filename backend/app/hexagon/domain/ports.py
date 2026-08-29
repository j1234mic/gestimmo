"""Ports (interfaces) du domaine.

Ces interfaces définissent les contrats dont le domaine a besoin, sans
préjuger de l'implémentation (SQLAlchemy, in-memory, …). Les adaptateurs
de l'infrastructure les implémentent ; les cas d'usage de la couche
``application`` ne dépendent que de ces abstractions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.hexagon.domain.owner import Owner, OwnerListItem
from app.hexagon.domain.property import (
    Property,
    PropertyFilter,
    PropertyListItem,
    PropertyStatistics,
)


class PropertyRepository(ABC):
    """Port de sortie : persistance des biens."""

    @abstractmethod
    def save(self, property: Property) -> Property:
        """Persiste (crée ou met à jour) un bien et renvoie l'entité."""

    @abstractmethod
    def find_by_id(self, property_id) -> Optional[Property]:
        """Résout un bien par id entier OU par secure_id (chaîne)."""

    @abstractmethod
    def find_by_reference(self, reference: str) -> Optional[Property]:
        ...

    @abstractmethod
    def search(self, filters: PropertyFilter, skip: int = 0, limit: int = 100):
        """Renvoie (PropertyListItem[], total)."""

    @abstractmethod
    def statistics(self) -> PropertyStatistics:
        ...

    @abstractmethod
    def delete(self, property_id) -> Optional[Property]:
        """Suppression logique ; renvoie l'entité supprimée ou None."""


class OwnerRepository(ABC):
    """Port de sortie : persistance des propriétaires."""

    @abstractmethod
    def save(self, owner: Owner) -> Owner:
        ...

    @abstractmethod
    def find_by_id(self, owner_id) -> Optional[Owner]:
        ...

    @abstractmethod
    def search(self, skip: int = 0, limit: int = 100, search: Optional[str] = None,
               owner_type: Optional[str] = None):
        """Renvoie (OwnerListItem[], total)."""

    @abstractmethod
    def delete(self, owner_id) -> Optional[Owner]:
        ...
