"""Tests unitaires — domaine et cas d'usage (sans base de données).

Les cas d'usage sont exercés contre un faux (fake) repository en mémoire,
prouvant que la couche application ne dépend que du port et non de
SQLAlchemy.
"""

import os
import tempfile
import unittest

os.environ.setdefault("SECURE_ID_KEY", "QKv_PYSNfbjeDsnZjKuISHB-uSnplMhWIjjn-JOfJwo=")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/x.db")

from app.hexagon.application.dto import (  # noqa: E402
    OwnerCreateDTO,
    OwnerTypeDTO,
    PropertyCreateDTO,
    PropertyStatusDTO,
    PropertyTypeDTO,
    PropertyUpdateDTO,
)
from app.hexagon.application.use_cases import (  # noqa: E402
    NotFoundError,
    create_owner,
    create_property,
    delete_property,
    get_property,
    list_properties,
    update_property,
)
from app.hexagon.domain.owner import Owner, OwnerType  # noqa: E402
from app.hexagon.domain.ports import OwnerRepository, PropertyRepository  # noqa: E402
from app.hexagon.domain.property import Property, PropertyFilter, PropertyStatus, PropertyType  # noqa: E402
from app.hexagon.infrastructure.security.id_cipher import encrypt_id  # noqa: E402


class FakePropertyRepository(PropertyRepository):
    def __init__(self):
        self._store = {}
        self._counter = 0
        self._refs = set()

    def save(self, property: Property) -> Property:
        self._counter += 1
        property.id = self._counter
        property.secure_id = encrypt_id(property.id)
        self._store[property.id] = property
        return property

    def find_by_id(self, property_id):
        if isinstance(property_id, str) and not str(property_id).isdigit():
            for p in self._store.values():
                if p.secure_id == property_id:
                    return p if p.is_active else None
            return None
        pid = int(property_id)
        p = self._store.get(pid)
        return p if (p and p.is_active) else None

    def find_by_reference(self, reference: str):
        for p in self._store.values():
            if p.reference == reference:
                return p
        return None

    def search(self, filters: PropertyFilter, skip: int = 0, limit: int = 100):
        items = [p for p in self._store.values() if p.is_active]
        if filters.search:
            term = filters.search.lower()
            items = [p for p in items if term in (p.title or "").lower() or term in (p.city or "").lower()]
        if filters.status:
            items = [p for p in items if p.status.value in [s.value if hasattr(s, "value") else s for s in filters.status]]
        total = len(items)
        return items[skip:skip + limit], total

    def statistics(self):
        return None

    def delete(self, property_id):
        p = self.find_by_id(property_id)
        if p is None:
            return None
        p.soft_delete()
        return p


class FakeOwnerRepository(OwnerRepository):
    def __init__(self):
        self._store = {}
        self._counter = 0

    def save(self, owner: Owner) -> Owner:
        self._counter += 1
        owner.id = self._counter
        owner.secure_id = encrypt_id(owner.id)
        self._store[owner.id] = owner
        return owner

    def find_by_id(self, owner_id):
        if isinstance(owner_id, str) and not str(owner_id).isdigit():
            for o in self._store.values():
                if o.secure_id == owner_id:
                    return o if o.is_active else None
            return None
        oid = int(owner_id)
        o = self._store.get(oid)
        return o if (o and o.is_active) else None

    def search(self, skip: int = 0, limit: int = 100, search=None, owner_type=None):
        return list(self._store.values()), len(self._store)

    def delete(self, owner_id):
        o = self.find_by_id(owner_id)
        if o is None:
            return None
        o.soft_delete()
        return o


class DomainUnitTest(unittest.TestCase):
    def test_property_soft_delete_sets_withdrawn(self):
        p = Property(reference="PROP-1", type=PropertyType.APARTMENT, status=PropertyStatus.AVAILABLE,
                     title="T", address="a", postal_code="1", city="c")
        self.assertTrue(p.is_publicly_visible())
        p.soft_delete()
        self.assertFalse(p.is_active)
        self.assertEqual(p.status, PropertyStatus.WITHDRAWN)

    def test_owner_display_name(self):
        o = Owner(reference="OWN-1", owner_type=OwnerType.COMPANY, company_name="SCI Test")
        self.assertEqual(o.display_name, "SCI Test")
        o2 = Owner(reference="OWN-2", owner_type=OwnerType.INDIVIDUAL, first_name="Jean", last_name="Dupont")
        self.assertEqual(o2.display_name, "Jean Dupont")


class PropertyUseCaseUnitTest(unittest.TestCase):
    def setUp(self):
        self.repo = FakePropertyRepository()

    def test_create_and_get_by_numeric_and_secure_id(self):
        created = create_property(self.repo, PropertyCreateDTO(
            type=PropertyTypeDTO.APARTMENT, title="Appart", address="1 rue", postal_code="75001", city="Paris"))
        self.assertIsNotNone(created.id)
        self.assertIsNotNone(created.secure_id)

        # Résolution par id entier
        by_int = get_property(self.repo, created.id)
        self.assertEqual(by_int.id, created.id)
        # Résolution par secure_id (chaîne)
        by_secure = get_property(self.repo, created.secure_id)
        self.assertEqual(by_secure.id, created.id)

    def test_update_property(self):
        created = create_property(self.repo, PropertyCreateDTO(
            type=PropertyTypeDTO.APARTMENT, title="Appart", address="1 rue", postal_code="75001", city="Paris"))
        updated = update_property(self.repo, created.id, PropertyUpdateDTO(title="Nouveau titre", rent_price=1200))
        self.assertEqual(updated.title, "Nouveau titre")
        self.assertEqual(updated.rent_price, 1200)

    def test_delete_property_is_soft(self):
        created = create_property(self.repo, PropertyCreateDTO(
            type=PropertyTypeDTO.APARTMENT, title="Appart", address="1 rue", postal_code="75001", city="Paris"))
        delete_property(self.repo, created.id)
        with self.assertRaises(NotFoundError):
            get_property(self.repo, created.id)

    def test_get_unknown_raises_not_found(self):
        with self.assertRaises(NotFoundError):
            get_property(self.repo, 999999)

    def test_list_properties_filter(self):
        create_property(self.repo, PropertyCreateDTO(
            type=PropertyTypeDTO.APARTMENT, title="Maison Paris", address="1", postal_code="1", city="Paris"))
        create_property(self.repo, PropertyCreateDTO(
            type=PropertyTypeDTO.HOUSE, title="Villa Lyon", address="2", postal_code="2", city="Lyon"))
        items, total = list_properties(self.repo, PropertyFilter(search="Paris"))
        self.assertEqual(total, 1)
        self.assertEqual(items[0].city, "Paris")


class OwnerUseCaseUnitTest(unittest.TestCase):
    def setUp(self):
        self.repo = FakeOwnerRepository()

    def test_create_and_resolve_by_secure_id(self):
        created = create_owner(self.repo, OwnerCreateDTO(
            owner_type=OwnerTypeDTO.INDIVIDUAL, first_name="Jean", last_name="Dupont"))
        self.assertIsNotNone(created.secure_id)
        resolved = self.repo.find_by_id(created.secure_id)
        self.assertEqual(resolved.id, created.id)

    def test_delete_owner(self):
        created = create_owner(self.repo, OwnerCreateDTO(first_name="A", last_name="B"))
        self.repo.delete(created.id)
        self.assertIsNone(self.repo.find_by_id(created.id))


if __name__ == "__main__":
    unittest.main()
