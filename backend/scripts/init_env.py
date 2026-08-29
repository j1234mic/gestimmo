#!/usr/bin/env python3
"""Prépare ``backend/.env`` : clés stables + hôte de base de données cohérent.

Résout les deux avertissements classiques du démarrage hors Docker :

1. « SECURE_ID_KEY non configurée : une clé éphémère est générée… »
   → génère une clé Fernet stable, écrite une fois pour toutes dans ``.env``.
   Sans elle, chaque redémarrage rend les ``secure_id`` déjà stockés en base
   illisibles (ils sont chiffrés avec une clé jetable).

2. « DATABASE_URL cible l'hôte Docker « postgres »… »
   → ``--db-host`` choisit l'hôte selon le mode de lancement :
   ``postgres`` (dans Docker) ou ``localhost`` (uvicorn lancé directement).

Usage (depuis ``backend/``) ::

    python scripts/init_env.py                       # complète .env, génère les clés manquantes
    python scripts/init_env.py --db-host localhost   # + base jointe sur localhost (API hors Docker)
    python scripts/init_env.py --db-host postgres    # + base jointe via le réseau Docker
    python scripts/init_env.py --check               # diagnostic seul, n'écrit rien

Le script est idempotent : relancé, il ne modifie que ce qui manque et ne
réaffiche jamais les valeurs existantes.
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

BACKEND_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACKEND_DIR / ".env"
EXAMPLE_FILE = BACKEND_DIR / ".env.example"

# Mêmes hôtes compose-only que app/config.py (copie volontaire : ce script
# doit rester exécutable sans dépendance applicative).
COMPOSE_ONLY_HOSTS = {"postgres", "db"}

SECRET_KEY_PLACEHOLDERS = {
    "changez-cette-cle-secrete-minimum-32-caracteres",
    "change-this-secret-before-production",
    "ma-cle-secrete-2024",
}


def generate_fernet_key() -> str:
    """Clé Fernet (44 caractères base64 url-safe) ; secours si cryptography absent."""
    try:
        from cryptography.fernet import Fernet

        return Fernet.generate_key().decode()
    except Exception:
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def running_inside_docker() -> bool:
    return Path("/.dockerenv").exists() or bool(os.getenv("KUBERNETES_SERVICE_HOST"))


def parse_env_line(line: str) -> tuple[str, str] | None:
    """Retourne (clé, valeur) pour une ligne ``KEY=VALUE``, sinon None.

    Gère le préfixe ``export`` et coupe la valeur à un commentaire `` #``
    non quoté (sémantique python-dotenv).
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith("export "):
        stripped = stripped[len("export "):]
    if "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    key = key.strip()
    if not key or not (key[0].isalpha() or key[0] == "_"):
        return None
    return key, value


def split_inline_comment(value: str) -> tuple[str, str]:
    """Sépare la valeur de son commentaire inline `` # ...`` (hors quotes)."""
    in_single = in_double = False
    for i, char in enumerate(value):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double and i > 0 and value[i - 1] in " \t":
            return value[:i].rstrip(), value[i:]
    return value, ""


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def db_host_of(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


def replace_db_host(url: str, new_host: str) -> str:
    """Remplace uniquement l'hôte de l'URL, en conservant identifiants/port/base."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    netloc = parts.netloc
    userinfo, sep, hostport = netloc.rpartition("@")
    if not sep:
        userinfo, hostport = "", netloc
    old_host = parts.hostname or ""
    if old_host and hostport.lower().startswith(old_host.lower()):
        hostport = new_host + hostport[len(old_host):]
    netloc = f"{userinfo}@{hostport}" if userinfo else hostport
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def load_env_lines() -> list[str]:
    if ENV_FILE.exists():
        return ENV_FILE.read_text(encoding="utf-8").splitlines()
    if EXAMPLE_FILE.exists():
        return EXAMPLE_FILE.read_text(encoding="utf-8").splitlines()
    return [
        "# backend/.env — généré par scripts/init_env.py",
        "ENVIRONMENT=development",
        "DEBUG=true",
        "AUTO_CREATE_TABLES=true",
        "ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:8000",
        "LOG_LEVEL=INFO",
        "LOG_FILE=logs/app.log",
    ]


def changes_needed(lines: list[str], db_host: str | None) -> list[str]:
    """Liste des actions que le script s'apprête à faire (mode --check inclus)."""
    actions: list[str] = []
    values: dict[str, str] = {}
    for line in lines:
        parsed = parse_env_line(line)
        if parsed:
            values[parsed[0]] = unquote(parsed[1]).split(" #")[0].strip()

    secret = values.get("SECRET_KEY", "")
    if not secret or secret in SECRET_KEY_PLACEHOLDERS or len(secret) < 32:
        actions.append("générer SECRET_KEY (stable, ≥ 32 caractères)")

    if not values.get("SECURE_ID_KEY", "").strip():
        actions.append("générer SECURE_ID_KEY (chiffrement des secure_id, stable entre redémarrages)")

    if db_host:
        current = values.get("DATABASE_URL", "")
        if current and db_host_of(current).lower() != db_host.lower():
            actions.append(f"réécrire l'hôte de DATABASE_URL vers « {db_host} »")
    return actions


def apply(lines: list[str], db_host: str | None) -> tuple[list[str], dict[str, str]]:
    """Applique les corrections et retourne (nouvelles lignes, clés→résumé de valeur)."""
    result: list[str] = []
    touched: dict[str, str] = {}
    seen: set[str] = set()

    for line in lines:
        parsed = parse_env_line(line)
        if not parsed:
            result.append(line)
            continue
        key, raw_value = parsed
        value, comment = split_inline_comment(raw_value)
        plain = unquote(value).split(" #")[0].strip()
        seen.add(key)

        if key == "SECRET_KEY" and (not plain or plain in SECRET_KEY_PLACEHOLDERS or len(plain) < 32):
            generated = secrets.token_urlsafe(48)
            quoted = f'"{generated}"' if value.startswith('"') else generated
            result.append(f"{key}={quoted}{(' ' + comment) if comment else ''}")
            touched[key] = f"{generated[:6]}… ({len(generated)} caractères)"
            continue

        if key == "SECURE_ID_KEY" and not plain:
            generated = generate_fernet_key()
            result.append(f"{key}={generated}")
            touched[key] = f"{generated[:6]}… (clé Fernet, {len(generated)} caractères)"
            continue

        if key == "DATABASE_URL" and db_host and db_host_of(plain).lower() != db_host.lower():
            new_url = replace_db_host(plain, db_host)
            result.append(f"{key}={new_url}")
            touched[key] = new_url
            continue

        result.append(line)

    # Clés attendues totalement absentes du fichier : on les ajoute à la fin.
    additions: list[str] = []
    if "SECRET_KEY" not in seen:
        generated = secrets.token_urlsafe(48)
        additions.append(f"SECRET_KEY={generated}")
        touched["SECRET_KEY"] = f"{generated[:6]}… ({len(generated)} caractères)"
    if "SECURE_ID_KEY" not in seen:
        generated = generate_fernet_key()
        additions.append(f"SECURE_ID_KEY={generated}")
        touched["SECURE_ID_KEY"] = f"{generated[:6]}… (clé Fernet, {len(generated)} caractères)"
    if additions:
        if result and result[-1].strip():
            additions.insert(0, "")
        additions.insert(0, "# Clés générées automatiquement par scripts/init_env.py — conservez-les stables.")
        result.extend(additions)

    return result, touched


def write_env(lines: list[str]) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=str(ENV_FILE.parent), prefix=".env.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).rstrip("\n") + "\n")
        os.replace(tmp_name, ENV_FILE)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    try:
        os.chmod(ENV_FILE, 0o600)  # le fichier contient des secrets : lecture restreinte
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prépare backend/.env : génère SECRET_KEY / SECURE_ID_KEY et aligne l'hôte de DATABASE_URL.",
    )
    parser.add_argument(
        "--db-host",
        choices=sorted(COMPOSE_ONLY_HOSTS | {"localhost", "127.0.0.1"}),
        default=None,
        help="hôte à écrire dans DATABASE_URL (localhost si l'API tourne hors Docker, postgres sinon) ; "
        "par défaut : hôte inchangé",
    )
    parser.add_argument("--check", action="store_true", help="affiche les actions nécessaires sans écrire")
    args = parser.parse_args(argv)

    db_host = args.db_host
    if db_host is None and not running_inside_docker():
        # Simple suggestion : on n'impose pas le remappage, config.py le fait déjà au runtime.
        lines_probe = load_env_lines()
        values = {
            k: v
            for k, v in (
                (p[0], unquote(split_inline_comment(p[1])[0]))
                for p in map(parse_env_line, lines_probe)
                if p
            )
        }
        url = values.get("DATABASE_URL", "")
        if db_host_of(url).lower() in COMPOSE_ONLY_HOSTS:
            print(
                f"NOTE : DATABASE_URL pointe vers « {db_host_of(url)} » (hôte docker-compose) alors que "
                "l'API semble tourner hors Docker. Relancez avec --db-host localhost pour figer ce choix "
                "dans .env, ou démarrez la base : docker compose up -d postgres"
            )

    lines = load_env_lines()
    actions = changes_needed(lines, db_host)

    if args.check:
        if actions:
            print("Actions nécessaires :")
            for action in actions:
                print(f"  - {action}")
            return 1
        print("backend/.env est complet : SECRET_KEY, SECURE_ID_KEY et l'hôte DATABASE_URL sont cohérents.")
        return 0

    if not actions:
        print(f"Rien à faire : {ENV_FILE} contient déjà des clés stables et un hôte DATABASE_URL cohérent.")
        return 0

    new_lines, touched = apply(lines, db_host)
    write_env(new_lines)

    print(f"✓ {ENV_FILE} mis à jour :")
    for key, summary in touched.items():
        print(f"  - {key} = {summary}")
    print("\nProchaines étapes :")
    url_values = {
        k: v
        for k, v in ((p[0], unquote(p[1])) for p in map(parse_env_line, new_lines) if p)
    }
    url = url_values.get("DATABASE_URL", "")
    host = db_host_of(url) or "localhost"
    if host in COMPOSE_ONLY_HOSTS or host == "localhost":
        print("  1) Démarrer la base si besoin :  docker compose up -d postgres")
        print("     (publie localhost:5432 ; identifiants par défaut : immo_user / immo_password_2024 / immo_db)")
    print("  2) Relancer l'API :  uvicorn app.main:app --reload")
    print("Les clés générées sont stables : ne les régénérez pas, sinon les secure_id existants deviennent illisibles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
