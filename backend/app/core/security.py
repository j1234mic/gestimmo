# backend/app/core/security.py
"""Sécurité : dépendances d'authentification et middlewares réexportés.

Ce module sert de point d'entrée unique pour la sécurité de l'application :
- `SecurityHeadersMiddleware` et `RequestSanitizer` (implémentés dans app/middleware/security)
- `get_current_owner` : dépendance FastAPI pour les routes du portail propriétaire
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.middleware.security import RequestSanitizer, SecurityHeadersMiddleware
from app.models.owner import Owner

__all__ = [
    "SecurityHeadersMiddleware",
    "RequestSanitizer",
    "get_current_owner",
]


async def get_current_owner(
    request: Request,
    db: Session = Depends(get_db),
) -> Owner:
    """Retourne le propriétaire (Owner) associé au compte authentifié.

    Repose sur l'authentification JWT existante (`app.auth.get_current_user`),
    puis résout l'enregistrement `Owner` en base à partir de l'email du compte.
    """
    user = await get_current_user(request, db)

    owner = db.query(Owner).filter(Owner.email == user.email).first()
    if owner is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Aucun propriétaire associé à ce compte",
        )
    return owner
