"""Tâches périodiques déclenchées par un planificateur HTTP (Vercel Cron Jobs).

Pourquoi cette route existe
---------------------------
Sur une plateforme serverless, aucune tâche de fond ne survit : Vercel gèle
l'instance entre deux requêtes et la détruit après ~5 minutes d'inactivité. La
boucle ``asyncio`` de ``app/main.py`` (``_backup_scheduler``) n'y déclenche donc
jamais rien. Cette route remplace ce mécanisme par un point d'entrée HTTP que le
planificateur de la plateforme appelle à intervalle fixe.

Sécurité
--------
Vercel signe chaque appel de Cron Job avec ``Authorization: Bearer $CRON_SECRET``.
Sans ``CRON_SECRET`` configuré, la route répond 503 : un endpoint public qui
déclenche des copies de base et des écritures de loyers serait un risque
immédiat. La comparaison utilise ``hmac.compare_digest`` pour rester insensible
aux attaques par mesure de temps.

Idempotence
-----------
Chaque tâche sous-jacente l'est déjà (verrou transactionnel sur le créneau du
jour pour la sauvegarde, filtre ``next_run_at`` pour les rapports, statut
``SCHEDULED`` pour les révisions). Un double déclenchement — fréquent avec la
précision horaire du plan Hobby — ne produit donc pas de doublon.
"""

from __future__ import annotations

import hmac
import logging
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.admin_security_service import run_daily_backup_if_due
from app.services.reporting_service import run_due_schedules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cron", tags=["Tâches périodiques"])

# Acteur enregistré dans les journaux d'audit et les champs `created_by`.
CRON_ACTOR = "cron@gestimmo.local"


def _cron_actor() -> Any:
    """Objet minimal imitant l'utilisateur authentifié attendu par les handlers.

    Les tâches périodiques réutilisent les handlers de ``app.routes.leases``,
    qui n'exploitent de l'utilisateur courant que son adresse e-mail. Passer un
    porteur fictif évite de dupliquer ici la logique métier des révisions et des
    renouvellements — une seule source de vérité, testée par ailleurs.
    """
    return SimpleNamespace(email=CRON_ACTOR, is_superuser=True)


def _due_rent_revisions(db: Session) -> dict:
    from app.routes.leases import process_scheduled_revisions

    return process_scheduled_revisions(as_of=None, db=db, current_user=_cron_actor())


def _automatic_renewals(db: Session) -> dict:
    from app.routes.leases import process_automatic_renewals

    return process_automatic_renewals(as_of=None, db=db, current_user=_cron_actor())


def _daily_backup(db: Session) -> dict:
    return run_daily_backup_if_due(db, CRON_ACTOR)


# Ordre volontaire : la sauvegarde d'abord, pour que l'état du jour soit figé
# avant les écritures automatiques de loyers et de renouvellements.
DAILY_TASKS: tuple[tuple[str, Callable[[Session], Any]], ...] = (
    ("daily_backup", _daily_backup),
    ("report_schedules", run_due_schedules),
    ("rent_revisions", _due_rent_revisions),
    ("automatic_renewals", _automatic_renewals),
)


def _verify_cron_secret(request: Request) -> None:
    """Vérifie le jeton signé par le planificateur de la plateforme."""
    expected = (settings.CRON_SECRET or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "CRON_SECRET n'est pas configuré : les tâches périodiques sont "
                "désactivées. Définissez la variable dans le projet Vercel puis "
                "redéployez."
            ),
        )

    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        provided = header[7:].strip()
    else:
        # Toléré pour un déclenchement manuel (curl, GitHub Actions, cron externe).
        provided = request.headers.get("x-cron-secret", "") or request.query_params.get("secret", "")

    if not hmac.compare_digest(provided, expected):
        logger.warning("Appel de /api/cron refusé : jeton invalide ou absent")
        raise HTTPException(status_code=401, detail="Jeton de tâche périodique invalide")


@router.get("/daily")
def daily_maintenance(request: Request, db: Session = Depends(get_db)) -> dict:
    """Exécute les tâches quotidiennes échues, une par une, sans solidarité.

    Chaque tâche est isolée : une exception est journalisée, la session est
    remise en état, et les suivantes s'exécutent quand même. Le planificateur
    reçoit un rapport exploitable (``failed`` liste les tâches en erreur) plutôt
    qu'un 500 global qui masquerait ce qui a réussi.
    """
    _verify_cron_secret(request)

    started = datetime.now(timezone.utc)
    results: dict[str, Any] = {}
    failed: list[str] = []

    for name, task in DAILY_TASKS:
        try:
            results[name] = {"ok": True, "result": _jsonable(task(db))}
        except HTTPException as exc:
            db.rollback()
            failed.append(name)
            results[name] = {"ok": False, "error": exc.detail}
            logger.exception("Tâche périodique « %s » refusée (%s)", name, exc.status_code)
        except Exception as exc:  # noqa: BLE001 — isolement volontaire des tâches
            db.rollback()
            failed.append(name)
            results[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            logger.exception("Tâche périodique « %s » en échec", name)

    finished = datetime.now(timezone.utc)
    return {
        "ran_at": started.isoformat(),
        "as_of": date.today().isoformat(),
        "duration_ms": int((finished - started).total_seconds() * 1000),
        "tasks": results,
        "failed": failed,
        "status": "partial" if failed else "ok",
    }


@router.get("/status")
def cron_status(request: Request) -> dict:
    """Diagnostic sans effet de bord : le planificateur est-il correctement armé ?"""
    _verify_cron_secret(request)
    return {
        "secret_configured": bool(settings.CRON_SECRET),
        "tasks": [name for name, _ in DAILY_TASKS],
        "backup_scheduler_internal": settings.BACKUP_SCHEDULER_ENABLED,
        "storage": _storage_state(),
        "hint": (
            "Sur le plan Hobby, Vercel limite les Cron Jobs à une exécution "
            "quotidienne, déclenchée à ±59 min : planifiez l'appel après "
            "BACKUP_DAILY_HOUR_UTC."
        ),
    }


def _storage_state() -> dict:
    from app.services import file_storage

    return file_storage.describe_backend()


def _jsonable(value: Any) -> Any:
    """Filtre les objets non sérialisables renvoyés par les services métier."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)
