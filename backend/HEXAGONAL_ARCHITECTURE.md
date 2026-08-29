# Architecture hexagonale — GestImmo (backend)

Ce document décrit la refonte en **architecture hexagonale** (ports & adapters)
du backend GestImmo. Elle a été introduite de façon **incrémentale** : le code
existant (`app.routes.*`, `app.services.*`) continue de fonctionner, et deux
contextes métier (Properties, Owners) sont désormais pilotés par des cas
d'usage découplés de l'infrastructure.

> Objectif : isoler la logique métier des détails techniques (SQLAlchemy,
> FastAPI, JWT…) pour la rendre testable et évolutive, **sans changer la
> logique fonctionnelle ni les contrats d'API existants**.

---

## 1. Structure des couches

```
app/hexagon/
├── domain/                      # Entités pures + ports (interfaces)
│   ├── property.py              #   Entité Property, PropertyFilter, PropertyListItem…
│   ├── owner.py                 #   Entité Owner, OwnerListItem
│   └── ports.py                 #   PropertyRepository, OwnerRepository (ABC)
│
├── application/                 # Cas d'usage (use cases) + DTO
│   ├── dto.py                   #   DTO d'entrée (PropertyCreateDTO, …)
│   └── use_cases.py             #   create_property, get_property, list_properties, …
│                               #   (dépend uniquement des PORTS, pas de SQLAlchemy)
│
├── infrastructure/              # Adaptateurs techniques
│   ├── persistence/
│   │   ├── mappers.py           #   SQLAlchemy ⇄ entités du domaine
│   │   └── repositories.py     #   SqlAlchemyPropertyRepository / OwnerRepository
│   └── security/
│       └── id_cipher.py        #   Chiffrement des identifiants (secure_id)
│
├── web/                         # Adaptateur HTTP (FastAPI)
│   ├── property_router.py       #   Routeur /api/v2/properties
│   └── owner_router.py          #   Routeur /api/v2/owners
│
├── dependencies.py              #  Injecte les repositories dans FastAPI (Depends)
└── container.py                 #  Composition root (câblage ports → adaptateurs)
```

### Flux d'une requête (couche web → domaine → infrastructure)

```
HTTP (/api/v2/properties) → property_router
        → use_cases.create_property(repo, dto)
        → repo (Port) → SqlAlchemyPropertyRepository (Adaptateur)
        → mappers → modèle SQLAlchemy → base de données
```

La route **ne contient aucune requête SQL** : elle délègue au cas d'usage,
qui ne connaît que le `Port` (`PropertyRepository`). L'implémentation concrète
est injectée via `Depends(property_repository_dep)` dans `dependencies.py`.

---

## 2. Identifiants chiffrés (sécurisation des ids)

Les identifiants entiers internes (`properties.id`, `owners.id`) sont
sensibles : les exposer dans les URLs/API permet l'énumération. Un nouvel
identifiant public **`secure_id`** (chiffré, non déterministe) est donc stocké
en base et exposé à la place de l'id entier.

### Mécanisme (`app/hexagon/infrastructure/security/id_cipher.py`)

- Chiffrement **Fernet** (AES-128-CBC + HMAC-SHA256) de l'entier `id`.
- `encrypt_id(123) -> "gAAAAA…"` (chaîne base64 url-safe).
- `decrypt_id("gAAAAA…") -> 123` (réversible).
- `is_secure_id(value)` distingue un entier d'un secure_id.
- La clé provient de `SECURE_ID_KEY` (variable d'environnement). **À configurer
  en production** ; sinon une clé de session éphémère est générée (les
  secure_id existants ne seraient alors plus déchiffrables après redémarrage).

### Stockage et rétro-compatibilité

- Colonne `secure_id VARCHAR(255)` **nullable** ajoutée à `properties` et
  `owners` (`app/models/property.py`, `app/models/owner.py`).
- Migration idempotente `_backfill_secure_ids()` dans `app/database.py` :
  - ajoute la colonne si elle manque (PostgreSQL & SQLite),
  - chiffre tous les ids existants dont `secure_id IS NULL`.
- À la création, `secure_id` est renseigné immédiatement (services historiques
  `property_service` / `owner_service` **et** repository hexagonal).
- **API additif** (non cassant) : les schémas `PropertyResponse` /
  `OwnerResponse` exposent désormais `secure_id` **en plus de** `id`. Les
  routes v2 acceptent un id entier **ou** un secure_id dans l'URL.

Exemple :

```json
GET /api/v2/properties/gAAAAABk…  →  { "id": 1, "secure_id": "gAAAAABk…", "title": "…" }
GET /api/v2/properties/1          →  (équivalent, rétro-compatibilité)
```

---

## 3. Tests

Trois niveaux exigés, tous situés sous `tests/hexagonal/` :

| Niveau | Fichier | Cible | Base de données |
|--------|---------|-------|-----------------|
| **Unitaires** | `test_id_cipher.py` | Chiffrement (roundtrip, rejet jeton altéré) | aucune |
| | `test_domain_and_use_cases.py` | Entités + cas d'usage via **faux repository** en mémoire | aucune |
| **Intégration** | `test_integration_repository.py` | Vrais repositories SQLAlchemy + mappers + chiffrement | SQLite |
| **End-to-end** | `test_e2e_api.py` | Cycle de vie complet via `TestClient` (auth, v2, secure_id) | SQLite |

Lancer les tests hexagonaux :

```bash
cd backend
export SECURE_ID_KEY="<clé Fernet 44 caractères>"   # ex. générée via: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
.venv/bin/python -m pytest tests/hexagonal/ -q
```

Lancer toute la suite (existante + hexagonale) :

```bash
export SECURE_ID_KEY="<clé>"
.venv/bin/python -m pytest tests/ -q
```

---

## 4. Extension (prochains contextes)

Pour hexagonaliser un nouveau contexte (ex. `Tenant`, `Lease`) :

1. `domain/<ctx>.py` : entité pure + `Port` (ABC).
2. `application/use_cases.py` : cas d'usage (dépend du port).
3. `infrastructure/persistence/repositories.py` : adaptateur SQLAlchemy.
4. `web/<ctx>_router.py` : routeur `/api/v2/<ctx>` (délègue aux use cases).
5. Ajouter le routeur dans `app/main.py` et, si besoin, la colonne `secure_id`.

Aucune modification des routes historiques n'est requise : elles coexistent
avec les routes v2.
