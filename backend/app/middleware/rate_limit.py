from fastapi import Request, HTTPException, status
from collections import defaultdict
import time

class RateLimiter:
    def __init__(self):
        self.requests = defaultdict(list)
        self.max_requests = 100
        self.window = 60

    async def __call__(self, request: Request):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window]
        if len(self.requests[ip]) >= self.max_requests:
            raise HTTPException(status_code=429, detail="Trop de requêtes")
        self.requests[ip].append(now)




