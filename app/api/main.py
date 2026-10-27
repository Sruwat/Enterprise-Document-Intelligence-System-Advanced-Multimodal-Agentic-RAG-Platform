from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.rate_limit import InMemoryRateLimitMiddleware
from app.api.routes.audit import router as audit_router
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.browser import router as browser_router
from app.api.routes.data_vault import router as data_vault_router
from app.api.routes.documents import router as documents_router
from app.api.routes.eval import router as eval_router
from app.api.routes.health import router as health_router
from app.api.routes.industry_packs import router as industry_packs_router
from app.api.routes.ingest import public_router as public_ingest_router
from app.api.routes.ingest import router as ingest_router
from app.api.routes.metrics import router as metrics_router
from app.api.routes.observability import router as observability_router
from app.api.routes.query import router as query_router
from app.api.routes.workspaces import router as workspaces_router
from app.api.routes.worker import router as worker_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.api.startup import validate_startup

settings = get_settings()
configure_logging(settings.log_dir)


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_startup()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    InMemoryRateLimitMiddleware,
    enabled=settings.enable_rate_limit,
    requests=settings.rate_limit_requests,
    window_seconds=settings.rate_limit_window_seconds,
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    if settings.enable_security_headers:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if settings.app_env.lower() == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
app.include_router(auth_router)
app.include_router(browser_router)
app.include_router(data_vault_router)
app.include_router(health_router)
app.include_router(industry_packs_router)
app.include_router(ingest_router)
app.include_router(public_ingest_router)
app.include_router(workspaces_router)
app.include_router(worker_router)
app.include_router(documents_router)
app.include_router(query_router)
app.include_router(eval_router)
app.include_router(metrics_router)
app.include_router(observability_router)
app.include_router(admin_router)
app.include_router(audit_router)
