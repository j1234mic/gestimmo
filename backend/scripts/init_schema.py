#!/usr/bin/env python3
"""Initialisation unique du schéma, hors du démarrage de l'API.

Sur une plateforme serverless (Vercel), ``AUTO_CREATE_TABLES=true`` fait tourner
``create_all`` sur ~248 tables à *chaque* cold start : le démarrage s'allonge de
plusieurs secondes et deux instances qui démarrent ensemble peuvent se
concurrencer sur les DDL additifs. Ce script permet d'initialiser la base une
fois, puis de déployer avec ``AUTO_CREATE_TABLES=false``.

Le script est idempotent : ``create_all`` ne crée que les tables absentes, les
helpers ``_add_column_if_missing`` vérifient l'inspecteur avant chaque ALTER et
``bootstrap_security`` n'écrase aucune configuration existante.

Exemples :
    cd backend
    python scripts/init_schema.py
    python scripts/init_schema.py --database-url sqlite:///./test.db
    python scripts/init_schema.py --skip-bootstrap

Après exécution, renseignez dans le projet Vercel :
    AUTO_CREATE_TABLES=false
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# Permet d'exécuter le script depuis la racine du dépôt ou depuis backend/.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crée les tables absentes et amorce la configuration de sécurité."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="URL de base à initialiser (défaut : DATABASE_URL de l'environnement ou de backend/.env).",
    )
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Ne pas créer les profils et comptes d'amorçage (utile si vous les gérez vous-même).",
    )
    parser.add_argument(
        "--list-tables",
        action="store_true",
        help="Afficher les tables présentes après initialisation puis quitter.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.database_url:
        # Doit être posé AVANT l'import de app.config : les réglages sont lus à
        # l'import du module.
        os.environ["DATABASE_URL"] = args.database_url

    from sqlalchemy import inspect

    from app.database import engine, init_db

    masked = engine.url.set(password="***") if engine.url.password else engine.url
    print(f"Base cible : {masked}")
    print(f"Moteur     : {engine.url.get_backend_name()}")

    if args.skip_bootstrap:
        # init_db() appelle bootstrap_security() en fin de parcours : on reproduit
        # ses étapes sans l'amorçage des comptes.
        from app.database import (
            Base,
            _backfill_secure_ids,
            _ensure_insurance_scope_columns,
            _ensure_mandate_signature_columns,
            _ensure_module_12_13_columns,
            _ensure_property_completion_columns,
        )
        from app.models import (  # noqa: F401  — enregistrement des métadonnées
            accounting, admin_security, ai_automation, communication, condo, crm,
            extension, finance, ged, geolocation, integration, insurance,
            lease_contract, maintenance, message, notification, owner, property,
            report, reporting, subscription, tenant,
        )

        Base.metadata.create_all(bind=engine)
        _ensure_module_12_13_columns()
        _ensure_property_completion_columns()
        _ensure_mandate_signature_columns()
        _ensure_insurance_scope_columns()
        _backfill_secure_ids()
        print("Schéma créé (amorçage de sécurité ignoré).")
    else:
        init_db()
        print("Schéma créé et configuration de sécurité amorcée.")

    if args.list_tables:
        tables = sorted(inspect(engine).get_table_names())
        print(f"\n{len(tables)} tables :")
        for name in tables:
            print(f"  - {name}")

    print("\n✅ Initialisation terminée.")
    print(
        "   Pensez à poser AUTO_CREATE_TABLES=false dans le projet Vercel pour\n"
        "   ne plus payer ce travail à chaque cold start."
    )
    if not args.skip_bootstrap:
        print(
            "\n⚠️  bootstrap_security() crée des comptes de démonstration aux mots de\n"
            "   passe connus (admin@immogest.com / Admin@2024!). Changez-les ou\n"
            "   supprimez-les avant toute exposition publique de l'API."
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — message court plutôt qu'une pile brute
        print(f"\n❌ Échec de l'initialisation : {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
