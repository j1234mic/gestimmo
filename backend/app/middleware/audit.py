"""Traçabilité transversale des requêtes mutatives.

Les services métier peuvent ajouter une entrée plus riche (avant/après). Ce
middleware garantit qu'aucune mutation HTTP ne reste totalement invisible,
y compris dans les modules historiques.
"""

from starlette.middleware.base import BaseHTTPMiddleware


class AuditTrailMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"} or response.status_code >= 500:
            return response
        try:
            from app.auth import decode_token, _module_from_path
            from app.database import SessionLocal
            from app.models.admin_security import AuditLog

            email = "anonymous"
            user_id = None
            authorization = request.headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                try:
                    payload = decode_token(authorization.split(" ", 1)[1])
                    email = payload.get("sub") or email
                    user_id = payload.get("uid")
                except Exception:
                    pass
            parts = [part for part in request.url.path.split("/") if part]
            resource_type = parts[2] if len(parts) > 2 else (parts[-1] if parts else "root")
            resource_id = next((part for part in reversed(parts) if part.isdigit()), None)
            db = SessionLocal()
            try:
                db.add(AuditLog(
                    actor_user_id=int(user_id) if user_id else None,
                    actor_email=email,
                    action=request.method.lower(),
                    module=_module_from_path(request.url.path),
                    resource_type=resource_type,
                    resource_id=resource_id,
                    description=f"{request.method} {request.url.path} → {response.status_code}",
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                ))
                db.commit()
            finally:
                db.close()
        except Exception:
            # L'audit ne doit pas rendre une réponse métier indisponible (p. ex.
            # pendant une migration où la table n'existe pas encore).
            pass
        return response
