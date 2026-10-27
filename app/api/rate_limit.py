from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import get_settings
from app.services.redis_client import RedisService


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    """Simple process-local limiter for the free SaaS profile.

    This is intentionally lightweight. A production deployment should replace
    it with Redis/gateway-backed limits, but this still protects local and
    single-instance deployments from obvious bursts.
    """

    PROTECTED_PREFIXES = ("/auth", "/chat", "/query", "/workspaces", "/ingest")

    def __init__(self, app, requests: int, window_seconds: int, enabled: bool = True) -> None:
        super().__init__(app)
        self.enabled = enabled
        self.requests = requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        settings = get_settings()
        self.settings = settings
        self.backend = getattr(settings, "rate_limit_backend", "memory")
        self.redis = RedisService(settings.redis_url, enabled=settings.enable_redis) if self.backend == "redis" else None

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled or not request.url.path.startswith(self.PROTECTED_PREFIXES):
            return await call_next(request)
        key = self._key(request)
        if self.redis is not None:
            status = self.redis.status()
            if status.get("status") != "ok" and self.settings.app_env.lower() == "production":
                return JSONResponse(
                    status_code=503,
                    content={"detail": "Redis rate limit backend is unavailable."},
                )
            if status.get("status") == "ok":
                allowed, _remaining = self.redis.rate_limit(f"rl:{key}:{request.url.path}", self.requests, self.window_seconds)
                if not allowed:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Rate limit exceeded. Please slow down and try again shortly."},
                        headers={"Retry-After": str(self.window_seconds)},
                    )
                return await call_next(request)
        now = time.monotonic()
        bucket = self._buckets[key]
        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please slow down and try again shortly."},
                headers={"Retry-After": str(self.window_seconds)},
            )
        bucket.append(now)
        return await call_next(request)

    @staticmethod
    def _key(request: Request) -> str:
        authorization = request.headers.get("authorization")
        if authorization:
            return f"auth:{authorization[-32:]}"
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
        client = request.client.host if request.client else "unknown"
        return f"ip:{client}"
