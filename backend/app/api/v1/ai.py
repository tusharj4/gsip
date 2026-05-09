"""AI natural language query endpoint — converts plain English to PostGIS SQL.

Rate limiting:
  - Applied at both nginx (10 req/min per IP via limit_req_zone) and application
    layer (slowapi, Redis-backed) for defence in depth.
  - When ENABLE_RATE_LIMIT=false the decorator is a no-op — useful in tests.

Auth:
  - When ENABLE_AUTH=true, requires a valid Bearer token (any role).
  - In dev mode (ENABLE_AUTH=false) the user dependency returns a synthetic
    admin so the endpoint works without Supabase.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth import AuthUser, get_current_user
from app.schemas.ai import NLQueryRequest, NLQueryResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# Lazily import the limiter from main.py state to avoid circular imports.
# slowapi reads app.state.limiter via the Request object at call time.
_RATE_LIMIT = f"{settings.ai_query_rate_limit}/minute"


@router.post("/query", response_model=NLQueryResponse)
async def nl_query(
    request: Request,
    payload: NLQueryRequest,
    db: AsyncSession = Depends(get_db),
    user: AuthUser = Depends(get_current_user),
) -> NLQueryResponse:
    """Translate a natural language question to PostGIS SQL and execute it.

    - Requires authentication when ENABLE_AUTH=true (any role).
    - Rate-limited to {ai_query_rate_limit} requests/minute per IP.
    - Uses Claude API to generate a SELECT-only SQL query.
    - Validates the query (SELECT prefix, no DDL/DML).
    - Executes with a 10-second statement timeout.
    - Returns results as GeoJSON FeatureCollection when geometry columns are present.
    - Never exposes raw SQL errors to the client.
    """
    if not settings.enable_ai_query:
        raise HTTPException(status_code=503, detail="AI query feature is disabled")
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="Anthropic API key not configured")

    # Application-layer rate limiting (complements nginx rate limiting)
    if settings.enable_rate_limit:
        limiter = getattr(request.app.state, "limiter", None)
        if limiter is not None:
            await _apply_rate_limit(limiter, request)

    from app.services.ai_query import AIQueryService

    service = AIQueryService(db)
    try:
        result = await service.query(payload.question, payload.context)
        logger.info(
            "AI query by user=%s rows=%d type=%s",
            user.user_id, result.row_count, result.result_type,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("AI query failed for user=%s: %s", user.user_id, exc)
        raise HTTPException(
            status_code=500,
            detail="Query execution failed. Please rephrase your question.",
        ) from exc


async def _apply_rate_limit(limiter: object, request: Request) -> None:
    """Check the rate limit programmatically (without the decorator).

    Using the programmatic API lets us conditionally skip rate limiting when
    ENABLE_RATE_LIMIT=false without importing slowapi at module level.
    """
    try:
        from slowapi.errors import RateLimitExceeded
        from slowapi.util import get_remote_address

        key = get_remote_address(request)
        # slowapi stores limits in the Limiter's _default_limits or per-route
        # We call the underlying limits backend directly for a simple check.
        if hasattr(limiter, "_limiter"):
            from limits import parse as parse_limit
            limit_item = parse_limit(_RATE_LIMIT)
            backend = limiter._limiter  # type: ignore[union-attr]
            if not backend.hit(limit_item, "ai_query", key):
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded: max {settings.ai_query_rate_limit} AI queries/minute per IP",
                    headers={"Retry-After": "60"},
                )
    except HTTPException:
        raise
    except Exception as exc:
        # Never block a request because of a rate-limit backend failure
        logger.warning("Rate limit check failed (Redis down?): %s", exc)
