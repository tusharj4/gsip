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

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    logger.info("GSIP backend starting up — env=%s", settings.app_env)
    yield
    logger.info("GSIP backend shutting down")


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
