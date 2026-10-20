from collections import defaultdict
import time

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

_EXEMPT_PATHS = {"/health", "/", "/docs", "/redoc", "/openapi.json"}
_EXEMPT_HOSTS = {"testclient"}


def client_ip(request: Request) -> str:
    """IP du client réel, en tenant compte du proxy de la plateforme.

    Derrière Vercel (ou Caddy, Render, Railway), ``request.client.host`` est
    l'adresse du proxy : tous les visiteurs partagent alors le même seau de
    limitation et l'API renvoie 429 au bout de ``RATE_LIMIT_REQUESTS`` requêtes
    *au total*. Les plateformes réécrivent ``X-Forwarded-For`` — l'ignorer
    rendrait la limitation à la fois inefficace et dangereuse.

    L'en-tête n'est cru que si ``TRUST_PROXY_HEADERS`` est vrai (auto-détecté sur
    Vercel/Railway/Render/Fly) : en exposition directe, un client pourrait
    sinon forger l'en-tête pour contourner la limite. On retient le premier saut
    de ``X-Forwarded-For``, qui est le client d'origine.
    """
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        real_ip = (request.headers.get("x-real-ip") or "").strip()
        if real_ip:
            return real_ip
    return request.client.host if request.client else "unknown"


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
        if self.is_limited(client_ip(request)):
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
        ip = client_ip(request)
        if ip in _EXEMPT_HOSTS:
            return await call_next(request)
        if self.limiter.is_limited(ip):
            return JSONResponse(status_code=429, content={
                "detail": "Trop de requêtes",
                # La limite est par instance : sur une plateforme serverless,
                # elle ne remplace pas un compteur partagé (Redis/Upstash).
                "scope": "instance",
            })
        return await call_next(request)
