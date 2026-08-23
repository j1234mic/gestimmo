from collections import defaultdict
import time

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

_EXEMPT_PATHS = {"/health", "/", "/docs", "/redoc", "/openapi.json"}
_EXEMPT_HOSTS = {"testclient"}


class RateLimiter:
    def __init__(self, max_requests: int | None = None, window: int | None = None):
        self.requests = defaultdict(list)
        self.max_requests = max_requests if max_requests is not None else settings.RATE_LIMIT_REQUESTS
        self.window = window if window is not None else settings.RATE_LIMIT_WINDOW

    def is_limited(self, ip: str) -> bool:
        now = time.time()
        self.requests[ip] = [stamp for stamp in self.requests[ip] if now - stamp < self.window]
        if len(self.requests[ip]) >= self.max_requests:
            return True
        self.requests[ip].append(now)
        return False

    async def __call__(self, request: Request):
        ip = request.client.host if request.client else "unknown"
        if self.is_limited(ip):
            raise HTTPException(status_code=429, detail="Trop de requêtes")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Limite globale par IP, paramétrée par RATE_LIMIT_REQUESTS / RATE_LIMIT_WINDOW."""

    def __init__(self, app):
        super().__init__(app)
        self.limiter = RateLimiter()

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)
        if request.url.path in _EXEMPT_PATHS:
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        if ip in _EXEMPT_HOSTS:
            return await call_next(request)
        if self.limiter.is_limited(ip):
            return JSONResponse(status_code=429, content={"detail": "Trop de requêtes"})
        return await call_next(request)
