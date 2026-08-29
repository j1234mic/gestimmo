# Audit des 17 modules — état réel du dépôt

Audit réalisé le 2026-08-29 sur la branche `arena/01a04bdf-gestimmo`
(commit de base `dd222bd`).

## Périmètre vérifié

| Mesure | Valeur |
|---|---|
| Contenu du dépôt | `README.md` + `backend/` uniquement |
| Lignes Python applicatives | 39 219 (`backend/app`) |
| Lignes de tests | 4 385 (`backend/tests`) |
| Modèles SQLAlchemy | 209 |
| Routes HTTP exposées | 670 |
| Tests d'intégration | **64 — tous verts** (`python -m unittest discover -s tests`) |

**Point structurant : le dépôt ne contient aucun frontend.** Aucun fichier
`.tsx`/`.vue`/`package.json`, aucun projet mobile natif
(`AndroidManifest.xml`, `pubspec.yaml`, `.swift`, `.kt`). Tout ce qui est livré
est une API FastAPI. Les modules « application mobile », « portail
propriétaire/locataire », « vue liste/grille/carte » et « widgets drag & drop »
existent donc **côté API uniquement** : les données et les endpoints sont là,
les écrans ne le sont pas.

## Verdict par module

| # | Module | État | Tests |
|---|---|---|---|
| 1 | Biens immobiliers | 🟠 ~75 % | ❌ aucun |
| 2 | Propriétaires | 🟠 ~85 % | ❌ aucun |
| 3 | Locataires | 🟢 complet | ✅ |
| 4 | Baux et contrats | 🟢 complet | ✅ |
| 5 | Finance et comptabilité | 🟢 complet (1 défaut corrigé) | ✅ |
| 6 | Maintenance et travaux | 🟢 complet | ✅ |
| 7 | Copropriété | 🟢 complet | ✅ |
| 8 | CRM et commercial | 🟢 complet | ✅ |
| 9 | Dashboard et reporting | 🟢 complet | ✅ |
| 10 | Communication et notifications | 🟢 complet | ✅ |
| 11 | GED | 🟢 complet | ✅ |
| 12 | Administration et sécurité | 🟢 complet | ✅ |
| 13 | Géolocalisation | 🟢 complet | ✅ |
| 14 | Application mobile | 🔴 ~20 % (socle API) | ❌ aucun |
| 15 | Assurances et sinistres | 🔴 ~30 % (socle API) | ❌ aucun |
| 16 | IA et automatisation | 🟢 complet (1 défaut corrigé) | ✅ |
| 17 | Intégrations et API | 🟢 complet | ✅ |

**Réponse courte : non, les 17 modules ne sont pas tous finis.** 13 sont
complets et couverts par des tests d'intégration ; les modules 1, 2, 14 et 15
sont inachevés et sont précisément les quatre seuls à n'avoir **aucun test**.

---

## Module 1 — Biens immobiliers 🟠

**Livré et vérifié** : CRUD complet, les 12 types de biens du cahier des
charges (`apartment`, `house`, `studio`, `villa`, `office`, `commercial`,
`warehouse`, `land_agricultural`, `land_buildable`, `parking`, `garage`,
`building`), les 6 statuts (`available`, `rented`, `for_sale`,
`under_renovation`, `reserved`, `withdrawn`), référence auto-générée
(`PROP-XXXXXXXX`), géolocalisation, surfaces, pièces, étages, année,
chauffage, DPE/GES, équipements, description, tags, galerie photos avec
compression Pillow (redimensionnement 1920 px) et photo principale, documents
typés (titre de propriété, plans, diagnostics, certificat de conformité,
règlement de copropriété…), évaluations.

**Manques confirmés par exécution** :

| Manque | Preuve |
|---|---|
| **Aucune vidéo dans la galerie** | `POST /api/properties/{id}/photos` avec un `.mp4` → `400 {"detail": "Extension non autorisée: mp4"}`. `settings.ALLOWED_EXTENSIONS = ["jpg","jpeg","png","webp","gif"]`. Plafond de 10 photos. |
| **Visite virtuelle 360° non fonctionnelle** | `PropertyPhoto.is_360` et `PropertyPhoto.virtual_tour_url` existent dans le modèle et le schéma mais **ne sont écrits nulle part** dans `app/` (grep exhaustif). Aucun endpoint ne permet de renseigner le lien. |
| **Pas de recherches favorites** | Aucune route contenant `saved`/`favorite` dans les 670 routes. |
| **Filtres de recherche incomplets** | `GET /api/properties/` n'expose que `search, type, status, city, min_price, max_price, min_area, max_area, min_rooms, entity_id, agency_id, portfolio_id, page, limit`. Manquent : **propriétaire**, **gestionnaire assigné**, **date de disponibilité** et **tags** — pourtant déjà présents dans `PropertyFilter` mais jamais branchés sur la route. |
| **Pas d'export CSV des biens** | Seuls `/api/export/properties/pdf` et `/api/export/properties/excel` existent. |
| **Pas de rapport d'évaluation PDF** | Aucune route `evaluation` + `pdf`/`report`. |
| **Historique du bien non consolidé** | `add_history_entry` est appelé automatiquement à la création, à chaque champ modifié, à la suppression et à chaque évaluation. En revanche **locataires, loyers et travaux ne remontent pas** dans `GET /api/properties/{id}/history/` : ils restent silotés dans les modules baux, paiements et maintenance. |

## Module 2 — Propriétaires 🟠

**Livré et vérifié** : fiche complète (personne physique/morale, état civil,
coordonnées, IBAN/BIC, pièces d'identité, régime fiscal, SIRET, TVA),
portefeuille de biens, mandats (gestion/vente/recherche, durée, honoraires,
renouvellement automatique, préavis, `GET /api/owners/mandates/expiring`),
comptabilité propriétaire (solde, résumé mensuel, relevé
mensuel/trimestriel/annuel avec export PDF), portail propriétaire JWT
(dashboard avec taux d'occupation, transactions, documents, messagerie,
déclaration fiscale).

**Manques confirmés** :

- **La « signature électronique » du mandat est un marqueur, pas une
  signature.** `PUT /api/owners/{id}/mandates/{mid}/sign` se contente de
  `mandate.signed_date = date.today()` et `mandate.status = "signed"`
  (`app/routes/owners.py:317-320`). Pas de consentement, pas d'empreinte
  SHA-256, pas de dossier de preuve — contrairement à la signature de bail du
  module 4 qui, elle, est réelle.
- **Pas de synthèse financière *par bien*.** `/api/accounting/owners/{id}/summary`
  est un résumé mensuel global au propriétaire ; aucune ventilation par bien.
- **Aucun test** sur tout le module (fiche, mandat, comptabilité, portail).

## Modules 3 à 13, 16, 17 🟢

Chacun est documenté dans le `README.md`, implémenté en
modèles + schémas + services + routes, et couvert par au moins un test
d'intégration qui traverse l'API de bout en bout. Répartition des 64 tests :

- `test_tenant_module.py` (4) → modules 3 et 4
- `test_finance_maintenance_module.py` (5) → modules 5 et 6
- `test_condo_module.py` (6) → module 7 + compléments module 6
- `test_crm_module.py` (12) → module 8
- `test_reporting_module.py` (11) → module 9
- `test_communication_ged_module.py` (7) → modules 10 et 11
- `test_modules_12_13.py` (5) → modules 12 et 13
- `test_modules_16_17.py` (6) → modules 16 et 17
- `test_config.py` (8) → configuration et rate limiting

Vérifications ponctuelles effectuées : exports du module 9 disponibles en
`pdf`/`excel`/`csv`/`word` (`app/services/reporting_service.py:1455-1470`) ;
2FA (`/api/auth/2fa/*`) et SSO SAML/OAuth2 (`/api/auth/sso/{slug}/*`) présents ;
canal courrier postal réellement journalisé (`PostalShipment`,
`communication_service.py:860`) ; API v1 avec clés API, OAuth2
`client_credentials`, rate limiting et webhooks HMAC.

## Module 14 — Application mobile 🔴

3 routes : `GET /api/mobile/dashboard`, `POST/GET /api/mobile/sync`,
`POST /api/mobile/media`, plus `PUT /api/leases/{id}/inspections/{iid}/mobile-sync`.
`GET /api/mobile/dashboard` renvoie une **liste de fonctionnalités déclarées**
(`["properties_map","contacts","calendar",…]`) — c'est une liste de chaînes,
pas des endpoints dédiés.

Le cahier des charges demande **quatre applications distinctes**
(gestionnaire, locataire, propriétaire, technicien). Il n'existe **aucune
application** dans le dépôt : pas de code mobile, pas de frontend. Le mode
hors-ligne se limite à une table `SyncOperation` idempotente qui enregistre les
opérations sans les rejouer sur les entités métier.

## Module 15 — Assurances et sinistres 🔴

4 ressources dans un fichier de 69 lignes
(`app/routes/mobile_insurance.py`) : `POST/GET /api/insurance/contracts`,
`POST /api/insurance/attestations`, `POST/GET /api/insurance/claims`,
`GET /api/insurance/reporting`.

Manques :

- **Aucune mise à jour ni détail d'un sinistre** : aucune route
  `/api/insurance/claims/{id}` (vérifié sur les 670 routes). Impossible de
  renseigner l'expert assigné, les dates clés ou l'indemnisation après
  création, alors que les colonnes existent dans le modèle.
- **Aucun suivi des attestations** : pas de relance automatique, pas de
  contrôle de validité, pas de stockage numérisé — l'endpoint crée une ligne
  et s'arrête là.
- **Pas de CRUD sur les contrats** (ni `PUT`, ni `DELETE`, ni détail).
- Requêtes sans pagination ni cloisonnement par société/agence, et
  sérialisation brute des modèles via un helper `obj()`.

---

## Deux défauts corrigés pendant l'audit

### 1. L'assistant gestionnaire répondait une phrase générique à « Bonjour »

`python -m unittest discover -s tests` échouait **avant** toute modification :

```
FAIL: test_manager_assistant_answers_each_intent_from_real_data
AssertionError: 'greeting' != 'manager_help'
Ran 63 tests in 154.271s — FAILED (failures=1)
```

Cause : `_conversational_turn`
(`app/services/ai_automation_service.py`) interceptait toute salutation de
3 mots ou moins et renvoyait l'intention `greeting` **avant** que
`_resolve_manager_intent` ne route vers `_manager_help(..., greeting=True)`.
Les deux résolveurs (gestionnaire et locataire) géraient déjà correctement les
salutations : la couche conversationnelle les doublait en les écrasant.

Correctif : suppression de cette branche de salutation dans
`_conversational_turn`, qui conserve la gestion des remerciements, prises de
congé et acquiescements.

### 2. Le périmètre « propriétaire » des exports comptables n'était pas appliqué

Dans `export_accounting` (`app/services/finance_service.py`), la variable
`owner_tx` était calculée puis **jamais utilisée** — code mort. Conséquence
mesurée avant correctif : un export demandé pour le propriétaire inexistant
`9999` renvoyait exactement le même nombre d'écritures qu'un export global.

Correctif : nouvelle fonction `_apply_export_scope` qui filtre réellement par
bien (`property_id`) ou par propriétaire (biens détenus via `PropertyOwner`),
et renvoie un export vide pour un propriétaire sans bien.

Vérification après correctif (2 écritures, 1 par bien ; le propriétaire ne
détient que le bien A) :

```
global            -> 4 lignes
property (bien A) -> 2 lignes  | contient « bien A » : True  | « bien B » : False
property (bien B) -> 2 lignes  | contient « bien A » : False | « bien B » : True
owner (possède A) -> 2 lignes  | contient « bien A » : True  | « bien B » : False
owner inexistant  -> 0 lignes
```

Un test de non-régression `test_module5_export_scope_owner_and_property` a été
ajouté à `backend/tests/test_finance_maintenance_module.py`.

**Suite finale : `Ran 64 tests in 182.297s — OK`.**

---

## Restes à faire, par ordre d'impact

1. **Modules 1 et 2 : écrire des tests.** Ce sont les deux modules les plus
   utilisés d'un logiciel de gestion immobilière et les seuls, avec 14 et 15, à
   n'avoir aucune couverture.
2. **Module 1 : brancher les filtres déjà présents** dans `PropertyFilter`
   (`available_from`, `tags`) sur la route, ajouter `owner_id` et
   `manager_id`, et rendre `virtual_tour_url`/`is_360` accessibles en écriture.
3. **Module 15 : ajouter le cycle de vie du sinistre** (`GET`/`PUT`
   `/api/insurance/claims/{id}`, expert, indemnisation, travaux de remise en
   état) et le suivi des attestations.
4. **Module 2 : aligner la signature de mandat** sur le dossier de preuve du
   module 4.
5. **Module 1 : ajouter l'export CSV, le rapport d'évaluation PDF, les
   recherches favorites et l'upload vidéo.**
6. **Module 14 : décider.** Soit le socle API actuel suffit et le cahier des
   charges doit être amendé, soit les quatre applications restent à construire
   — elles n'existent pas.
