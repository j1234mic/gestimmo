#!/usr/bin/env python3
"""Jeu de démonstration : 50 biens immobiliers à Madagascar avec photos réelles.

Le script est idempotent : il crée ou met à jour les biens référencés
``MDG-TEST-001`` à ``MDG-TEST-050`` et réinitialise leurs photos de galerie.
Les photos sont des URL publiques de photographies réelles (Unsplash), non
stockées dans le dépôt afin d'éviter d'ajouter des fichiers lourds.

Exemples :
    cd backend
    python scripts/seed_madagascar_properties.py
    python scripts/seed_madagascar_properties.py --database-url sqlite:///./test.db
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path


# Permet d'exécuter le script depuis la racine du dépôt ou depuis backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@dataclass(frozen=True)
class Location:
    city: str
    postal_code: str
    district: str
    address: str
    latitude: float
    longitude: float


LOCATIONS: list[Location] = [
    Location("Antananarivo", "101", "Ivandry", "Lot II M 45, route d'Ivandry", -18.8792, 47.5079),
    Location("Antananarivo", "101", "Ambatobe", "Lot AB 12, rue des Orchidées", -18.8675, 47.5486),
    Location("Antananarivo", "101", "Isoraka", "18 rue Rainitovo", -18.9144, 47.5201),
    Location("Antananarivo", "101", "Analakely", "6 avenue de l'Indépendance", -18.9080, 47.5254),
    Location("Antananarivo", "101", "Ankorondrano", "Immeuble Horizon, boulevard de l'Europe", -18.8798, 47.5207),
    Location("Antananarivo", "101", "Ambohijatovo", "Lot AV 33, montée d'Ambohijatovo", -18.9108, 47.5310),
    Location("Antananarivo", "102", "Talatamaty", "Lot TLM 88, route de l'aéroport", -18.8267, 47.4561),
    Location("Antananarivo", "102", "Itaosy", "Lot IT 17, quartier Fiadanana", -18.9319, 47.4719),
    Location("Toamasina", "501", "Tanamakoa", "24 boulevard Joffre", -18.1492, 49.4023),
    Location("Toamasina", "501", "Anjoma", "Lot TM 9, rue du Commerce", -18.1605, 49.4076),
    Location("Toamasina", "501", "Mangabe", "Villa Mangabe, route du Port", -18.1378, 49.3849),
    Location("Antsirabe", "110", "Avaratsena", "12 avenue de la Gare", -19.8659, 47.0333),
    Location("Antsirabe", "110", "Andranomanelatra", "Lot AS 71, route des thermes", -19.7870, 47.0636),
    Location("Fianarantsoa", "301", "Ambatomena", "Lot FI 14, vieille ville", -21.4536, 47.0850),
    Location("Fianarantsoa", "301", "Isaha", "7 rue des Écoles", -21.4619, 47.0940),
    Location("Mahajanga", "401", "Amborovy", "Villa Baobab, route d'Amborovy", -15.6708, 46.3515),
    Location("Mahajanga", "401", "Mangarivotra", "Lot MJ 22, boulevard Marcoz", -15.7167, 46.3167),
    Location("Toliara", "601", "Anketa", "Lot TU 8, avenue de France", -23.3516, 43.6855),
    Location("Toliara", "601", "Ifaty", "Résidence Dunes, route d'Ifaty", -23.1463, 43.6118),
    Location("Antsiranana", "201", "Ramena", "Villa Diego, route de Ramena", -12.2753, 49.2917),
    Location("Antsiranana", "201", "Centre-ville", "5 rue Colbert", -12.2787, 49.2917),
    Location("Nosy Be", "207", "Ambatoloaka", "Bungalow Vanille, plage d'Ambatoloaka", -13.3972, 48.2074),
    Location("Nosy Be", "207", "Hell-Ville", "Lot NB 11, avenue de la Libération", -13.4000, 48.2667),
    Location("Morondava", "619", "Nosy Kely", "Villa Menabe, front de mer", -20.2887, 44.3178),
    Location("Morondava", "619", "Centre", "Lot MDV 6, rue du Marché", -20.2833, 44.2833),
    Location("Sainte-Marie", "515", "Ambodifotatra", "Maison Cocotier, baie d'Ambodifotatra", -17.0080, 49.8382),
    Location("Sainte-Marie", "515", "Vohilava", "Bungalow Lagon, route de Vohilava", -17.0634, 49.8520),
    Location("Ambanja", "203", "Centre", "Lot AJ 3, avenue des Cacaoyers", -13.6833, 48.4500),
    Location("Sambava", "208", "Ampandrozonana", "Maison Vanille, route de l'aéroport", -14.2667, 50.1667),
    Location("Sambava", "208", "Centre", "Lot SBV 4, rue du Port", -14.2694, 50.1678),
    Location("Taolagnaro", "614", "Libanona", "Villa Libanona, chemin de la plage", -25.0319, 46.9997),
    Location("Taolagnaro", "614", "Ampasikabo", "Lot FT 18, route de Sainte-Luce", -25.0389, 46.9934),
    Location("Manakara", "316", "Tanambao", "Maison Canal, avenue du Canal", -22.1486, 48.0106),
    Location("Manakara", "316", "Centre", "Lot MNK 9, rue de la Gare", -22.1434, 48.0061),
    Location("Ambositra", "306", "Centre", "Immeuble Zafimaniry, rue du Bois", -20.5300, 47.2450),
    Location("Miarinarivo", "117", "Centre", "Lot MR 5, route nationale 1", -18.9589, 46.9053),
    Location("Antalaha", "206", "Ampahana", "Maison Girofle, route de la baie", -14.9003, 50.2788),
    Location("Antalaha", "206", "Centre", "Lot ATH 16, rue du Marché", -14.8833, 50.2833),
    Location("Moramanga", "514", "Centre", "Lot MMG 12, avenue de la Gare", -18.9500, 48.2333),
    Location("Andasibe", "514", "Mantadia", "Écolodge Mantadia, route du parc", -18.9333, 48.4167),
    Location("Antananarivo", "103", "Ambohidratrimo", "Villa Rova, colline d'Ambohidratrimo", -18.8157, 47.4378),
    Location("Antananarivo", "101", "Lac Anosy", "Appartement Anosy, rue Ralaimongo", -18.9169, 47.5221),
    Location("Toamasina", "501", "Salazamay", "Lot SZ 10, route de l'université", -18.1200, 49.3920),
    Location("Antsirabe", "110", "Mahazoarivo", "Villa Thermale, rue des Bains", -19.8745, 47.0342),
    Location("Fianarantsoa", "301", "Talatamaty", "Lot FNR 30, route de Sahambavy", -21.4409, 47.1117),
    Location("Mahajanga", "401", "Petite Plage", "Résidence Corail, bord de mer", -15.6920, 46.3210),
    Location("Toliara", "601", "Miary", "Terrain Miary, route de Saint-Augustin", -23.3849, 43.6745),
    Location("Antsiranana", "201", "Joffreville", "Maison Montagne d'Ambre, route de Joffreville", -12.4939, 49.2092),
    Location("Nosy Be", "207", "Andilana", "Villa Andilana, baie d'Andilana", -13.2566, 48.1846),
    Location("Morondava", "619", "Allée des Baobabs", "Terrain Baobab, piste de Belo", -20.2500, 44.4167),
]

OWNER_FIXTURES = [
    {"reference": "MDG-OWN-001", "owner_type": "individual", "first_name": "Rivo", "last_name": "Rakotoarisoa", "email": "rivo.rakotoarisoa@example.mg", "phone": "+261340100001", "address": "Lot II M 45 Ivandry", "postal_code": "101", "city": "Antananarivo"},
    {"reference": "MDG-OWN-002", "owner_type": "individual", "first_name": "Mialy", "last_name": "Rabe", "email": "mialy.rabe@example.mg", "phone": "+261340100002", "address": "Lot AB 12 Ambatobe", "postal_code": "101", "city": "Antananarivo"},
    {"reference": "MDG-OWN-003", "owner_type": "individual", "first_name": "Hery", "last_name": "Rasolofonirina", "email": "hery.rasolofonirina@example.mg", "phone": "+261340100003", "address": "24 boulevard Joffre", "postal_code": "501", "city": "Toamasina"},
    {"reference": "MDG-OWN-004", "owner_type": "individual", "first_name": "Soa", "last_name": "Andriamihaja", "email": "soa.andriamihaja@example.mg", "phone": "+261340100004", "address": "12 avenue de la Gare", "postal_code": "110", "city": "Antsirabe"},
    {"reference": "MDG-OWN-005", "owner_type": "company", "company_name": "Immo Mada Invest", "email": "contact@immo-mada.example.mg", "phone": "+261340100005", "address": "Immeuble Horizon Ankorondrano", "postal_code": "101", "city": "Antananarivo", "siret": "00000000000005"},
    {"reference": "MDG-OWN-006", "owner_type": "sci", "company_name": "SCI Vanille Bourbon", "email": "contact@sci-vanille.example.mg", "phone": "+261340100006", "address": "Lot NB 11 Hell-Ville", "postal_code": "207", "city": "Nosy Be", "siret": "00000000000006"},
    {"reference": "MDG-OWN-007", "owner_type": "company", "company_name": "Baobab Properties SARL", "email": "contact@baobab-properties.example.mg", "phone": "+261340100007", "address": "Villa Menabe Nosy Kely", "postal_code": "619", "city": "Morondava", "siret": "00000000000007"},
    {"reference": "MDG-OWN-008", "owner_type": "individual", "first_name": "Tahina", "last_name": "Razafindrakoto", "email": "tahina.razafindrakoto@example.mg", "phone": "+261340100008", "address": "Villa Libanona", "postal_code": "614", "city": "Taolagnaro"},
    {"reference": "MDG-OWN-009", "owner_type": "individual", "first_name": "Lova", "last_name": "Randrianarisoa", "email": "lova.randrianarisoa@example.mg", "phone": "+261340100009", "address": "Lot ATH 16", "postal_code": "206", "city": "Antalaha"},
    {"reference": "MDG-OWN-010", "owner_type": "company", "company_name": "Patrimoine Océan Indien", "email": "contact@patrimoine-oi.example.mg", "phone": "+261340100010", "address": "Résidence Corail", "postal_code": "401", "city": "Mahajanga", "siret": "00000000000010"},
]

# Photographies réelles d'intérieurs/extérieurs immobiliers (Unsplash CDN).
PHOTO_LIBRARY = [
    "https://images.unsplash.com/photo-1564013799919-ab600027ffc6?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600566753190-17f0baa2a6c3?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600607687644-c7171b42498b?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600566752355-35792bedcfea?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600210492493-0946911123ea?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600210491369-e753d80a41f3?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600210492486-724fe5c67fb0?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600607688969-a5bfcd646154?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600047509807-ba8f99d2cdde?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1598928506311-c55ded91a20c?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1600585154526-990dced4db0d?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1560448204-e02f11c3d0e2?auto=format&fit=crop&w=1400&q=80",
    "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=1400&q=80",
]

TITLE_PREFIXES = [
    "Villa familiale", "Appartement lumineux", "Maison traditionnelle rénovée", "Studio meublé",
    "Bureau moderne", "Local commercial", "Terrain constructible", "Résidence avec jardin",
    "Duplex standing", "Bungalow touristique",
]

PROPERTY_TYPES = [
    "villa", "apartment", "house", "studio", "office", "commercial", "land_buildable",
    "house", "apartment", "villa",
]

STATUSES = ["available", "rented", "for_sale", "available", "reserved", "under_renovation"]
HEATING_TYPES = ["electric", "solar", "electric", "wood", "heat_pump"]
ENERGY_CLASSES = ["A", "B", "C", "D", "E"]


def ariary(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " Ar"


def build_property_payload(index: int) -> dict:
    loc = LOCATIONS[index - 1]
    type_value = PROPERTY_TYPES[(index - 1) % len(PROPERTY_TYPES)]
    status = STATUSES[(index - 1) % len(STATUSES)]
    title = f"{TITLE_PREFIXES[(index - 1) % len(TITLE_PREFIXES)]} à {loc.district}"

    rooms = 1 + (index % 7)
    bedrooms = max(0, min(rooms - 1, 5))
    bathrooms = 1 + (index % 3 == 0) + (index % 11 == 0)
    living_area = 28 + (index * 9 % 190)
    land_area = None if type_value in {"apartment", "studio", "office", "commercial"} else 180 + (index * 73 % 2200)
    rent_price = None if status == "for_sale" else 650_000 + index * 85_000
    sale_price = 95_000_000 + index * 18_500_000 if status == "for_sale" else None

    if type_value == "land_buildable":
        title = f"Terrain constructible titré à {loc.district}"
        rooms = bedrooms = bathrooms = 0
        living_area = 0
        land_area = 450 + (index * 97 % 3500)
        rent_price = None
        sale_price = 70_000_000 + index * 12_000_000

    operation = "vente" if sale_price else "location"
    price = ariary(int(sale_price or rent_price or 0))
    description = (
        f"Jeu de test Madagascar : {title.lower()} situé à {loc.city}, quartier {loc.district}. "
        f"Adresse fictive mais géolocalisée pour tester recherche, carte, filtres et portail public. "
        f"Prix indicatif en ariary malgache pour la {operation} : {price}. "
        "Photos de démonstration liées à de vraies photographies immobilières publiques."
    )

    equipment = {
        "elevator": type_value in {"apartment", "office"} and index % 2 == 0,
        "parking": index % 2 == 0,
        "cellar": index % 5 == 0,
        "balcony": type_value in {"apartment", "studio"} and index % 3 != 0,
        "terrace": type_value in {"villa", "house"} or index % 4 == 0,
        "garden": type_value in {"villa", "house"} and index % 2 == 1,
        "swimming_pool": type_value in {"villa", "house"} and index % 7 == 0,
        "air_conditioning": loc.city in {"Toamasina", "Mahajanga", "Toliara", "Antsiranana", "Nosy Be", "Morondava", "Sainte-Marie", "Taolagnaro"},
        "alarm": index % 4 == 0,
        "intercom": type_value in {"apartment", "office", "commercial"},
        "fiber_optic": loc.city in {"Antananarivo", "Toamasina", "Antsirabe", "Mahajanga"},
        "disabled_access": type_value in {"office", "commercial"},
        "caretaker": type_value in {"apartment", "office"} and index % 6 == 0,
        "bike_storage": index % 3 == 0,
        "laundry_room": type_value in {"villa", "house", "apartment"},
    }

    return {
        "reference": f"MDG-TEST-{index:03d}",
        "type": type_value,
        "status": status,
        "title": title,
        "description": description,
        "address": loc.address,
        "address_complement": loc.district,
        "postal_code": loc.postal_code,
        "city": loc.city,
        "country": "Madagascar",
        "latitude": round(loc.latitude + ((index % 5) - 2) * 0.002, 6),
        "longitude": round(loc.longitude + ((index % 7) - 3) * 0.002, 6),
        "entity_id": 1,
        "agency_id": 10 + (index % 4),
        "portfolio_id": 100 + (index % 6),
        "manager_id": 200 + (index % 5),
        "available_from": date.today() + timedelta(days=index % 45),
        "living_area": float(living_area),
        "total_area": float((living_area or 0) + (land_area or 0)),
        "land_area": float(land_area) if land_area is not None else None,
        "rooms": rooms,
        "bedrooms": bedrooms,
        "bathrooms": int(bathrooms),
        "toilets": int(max(1, bathrooms)) if rooms else 0,
        "floor": None if type_value in {"villa", "house", "land_buildable"} else index % 8,
        "total_floors": None if type_value in {"villa", "house", "land_buildable"} else 2 + (index % 8),
        "construction_year": 1985 + (index % 38),
        "renovation_year": 2010 + (index % 15) if index % 3 == 0 else None,
        "heating_type": HEATING_TYPES[(index - 1) % len(HEATING_TYPES)] if type_value != "land_buildable" else None,
        "energy_class": ENERGY_CLASSES[(index - 1) % len(ENERGY_CLASSES)] if type_value != "land_buildable" else None,
        "ges_class": ENERGY_CLASSES[index % len(ENERGY_CLASSES)] if type_value != "land_buildable" else None,
        "equipment": equipment,
        "rent_price": float(rent_price) if rent_price is not None else None,
        "charges": float(80_000 + index * 7_500) if rent_price else None,
        "deposit": float((rent_price or 0) * 2) if rent_price else None,
        "sale_price": float(sale_price) if sale_price is not None else None,
        "property_tax": float(250_000 + index * 35_000),
        "tags": ["madagascar", "jeu-test", loc.city.lower().replace(" ", "-"), loc.district.lower().replace(" ", "-"), operation],
        "virtual_tour_url": f"https://example.mg/visites-360/mdg-test-{index:03d}",
        "is_360_available": index % 8 == 0,
        "is_active": True,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ajoute 50 biens de test à Madagascar avec photos réelles.")
    parser.add_argument(
        "--database-url",
        help="Surcharge DATABASE_URL (ex. sqlite:///./test.db). À fournir avant l'import de l'application.",
    )
    parser.add_argument(
        "--photos-per-property",
        type=int,
        default=3,
        choices=range(1, 6),
        metavar="1-5",
        help="Nombre de photos par bien (défaut: 3).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from app.database import SessionLocal, init_db
    from app.hexagon.infrastructure.security.id_cipher import encrypt_id
    from app.models.owner import Owner, OwnerType, PropertyOwner, TaxRegime
    from app.models.property import (
        EnergyClass,
        HeatingType,
        Property,
        PropertyHistory,
        PropertyPhoto,
        PropertyStatus,
        PropertyType,
    )

    init_db()
    db = SessionLocal()
    created_properties = 0
    updated_properties = 0

    try:
        owners: list[Owner] = []
        for fixture in OWNER_FIXTURES:
            owner = db.query(Owner).filter(Owner.reference == fixture["reference"]).first()
            owner_payload = dict(fixture)
            owner_payload["owner_type"] = OwnerType(owner_payload["owner_type"])
            owner_payload.setdefault("country", "Madagascar")
            owner_payload.setdefault("nationality", "Malgache")
            owner_payload.setdefault("tax_regime", TaxRegime.REEL if owner_payload["owner_type"] == OwnerType.INDIVIDUAL else TaxRegime.BIC)
            owner_payload.setdefault("tags", ["madagascar", "jeu-test"])
            owner_payload.setdefault("notes", "Propriétaire créé pour le jeu de test Madagascar.")

            if owner is None:
                owner = Owner(**owner_payload)
                db.add(owner)
                db.flush()
                owner.secure_id = encrypt_id(owner.id)
            else:
                for key, value in owner_payload.items():
                    setattr(owner, key, value)
                if not owner.secure_id:
                    owner.secure_id = encrypt_id(owner.id)
            owners.append(owner)

        db.commit()

        for index in range(1, 51):
            payload = build_property_payload(index)
            reference = payload.pop("reference")
            prop = db.query(Property).filter(Property.reference == reference).first()

            payload["type"] = PropertyType(payload["type"])
            payload["status"] = PropertyStatus(payload["status"])
            payload["heating_type"] = HeatingType(payload["heating_type"]) if payload.get("heating_type") else None
            payload["energy_class"] = EnergyClass(payload["energy_class"]) if payload.get("energy_class") else None
            payload["ges_class"] = EnergyClass(payload["ges_class"]) if payload.get("ges_class") else None

            if prop is None:
                prop = Property(reference=reference, **payload)
                db.add(prop)
                db.flush()
                prop.secure_id = encrypt_id(prop.id)
                db.add(PropertyHistory(
                    property_id=prop.id,
                    event_type="seed_created",
                    description="Bien de test Madagascar créé par scripts/seed_madagascar_properties.py",
                    date=date.today(),
                    details={"seed": "madagascar", "reference": reference},
                ))
                created_properties += 1
            else:
                for key, value in payload.items():
                    setattr(prop, key, value)
                if not prop.secure_id:
                    prop.secure_id = encrypt_id(prop.id)
                updated_properties += 1

            owner = owners[(index - 1) % len(owners)]
            db.query(PropertyOwner).filter(PropertyOwner.property_id == prop.id).delete(synchronize_session=False)
            db.add(PropertyOwner(
                property_id=prop.id,
                owner_id=owner.id,
                ownership_percentage=100.0,
                is_main_owner=True,
                acquisition_date=date(2018 + (index % 6), (index % 12) + 1, min(28, (index % 27) + 1)),
                acquisition_price=prop.sale_price or (prop.rent_price or 0) * 96,
            ))

            db.query(PropertyPhoto).filter(PropertyPhoto.property_id == prop.id).delete(synchronize_session=False)
            for order in range(args.photos_per_property):
                photo_url = PHOTO_LIBRARY[(index + order - 1) % len(PHOTO_LIBRARY)]
                db.add(PropertyPhoto(
                    property_id=prop.id,
                    url=photo_url,
                    filename=f"{reference.lower()}-{order + 1}.jpg",
                    media_type="image",
                    is_main=(order == 0),
                    is_360=False,
                    virtual_tour_url=prop.virtual_tour_url if order == 0 and prop.is_360_available else None,
                    order=order,
                ))

        db.commit()
    finally:
        db.close()

    print(
        f"Jeu Madagascar prêt : {created_properties} biens créés, "
        f"{updated_properties} biens mis à jour, 50 biens au total, "
        f"{50 * args.photos_per_property} photos réelles liées."
    )


if __name__ == "__main__":
    main()
