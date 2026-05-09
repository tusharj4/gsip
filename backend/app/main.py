"""FastAPI application factory for GSIP backend."""

import logging
import time
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.router import api_router

# Rate limiting (slowapi — Redis-backed, gracefully degraded if unavailable)
try:
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address
    _SLOWAPI_AVAILABLE = True
except ImportError:
    _SLOWAPI_AVAILABLE = False

# Prometheus metrics (optional — gracefully degraded if package missing)
try:
    from prometheus_fastapi_instrumentator import Instrumentator as _Instrumentator
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    logger.info(
        "GSIP backend starting up — env=%s auth=%s rate_limit=%s",
        settings.app_env,
        settings.enable_auth,
        settings.enable_rate_limit,
    )
    yield
    logger.info("GSIP backend shutting down")


# Build the global rate limiter (no-op if slowapi not installed or rate limiting disabled)
if _SLOWAPI_AVAILABLE and settings.enable_rate_limit:
    _limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=settings.redis_url,
        default_limits=[],  # only apply limits where decorated
    )
else:
    _limiter = None  # type: ignore[assignment]

app = FastAPI(
    title="GatiShakti Intelligence Platform API",
    description=(
        "Geospatial decision support system for infrastructure planning. "
        "Conflict detection, gap analysis, route optimization, and AI-assisted queries."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# Attach the limiter to app state so @limiter.limit() can find it
if _limiter is not None:
    app.state.limiter = _limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# CORS — allow frontend dev server and any configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_timing(request: Request, call_next: object) -> Response:
    """Attach X-Process-Time header to every response for monitoring."""
    start = time.perf_counter()
    response: Response = await call_next(request)  # type: ignore[operator]
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"
    return response


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, str]:
    """Liveness probe endpoint — returns 200 when the service is running."""
    return {"status": "ok", "env": settings.app_env}


@app.get("/ready", tags=["system"])
async def readiness_check() -> dict[str, str]:
    """Readiness probe — verifies database connectivity before accepting traffic."""
    from sqlalchemy import text
    from app.database import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:
        logger.error("Readiness check failed: %s", exc)
        return JSONResponse(status_code=503, content={"status": "not ready", "detail": str(exc)})  # type: ignore[return-value]


# Mount versioned API router
app.include_router(api_router, prefix="/api")

# Prometheus metrics — exposes /metrics for Grafana/Prometheus scraping
if _PROMETHEUS_AVAILABLE:
    _Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=True,
        env_var_name="ENABLE_METRICS",
        excluded_handlers=["/health", "/ready", "/metrics"],
    ).instrument(app).expose(app, include_in_schema=False, tags=["system"])
