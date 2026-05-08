"""AI natural language query endpoint — converts plain English to PostGIS SQL."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas.ai import NLQueryRequest, NLQueryResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/query", response_model=NLQueryResponse)
async def nl_query(
    payload: NLQueryRequest,
    db: AsyncSession = Depends(get_db),
) -> NLQueryResponse:
    """Translate a natural language question to PostGIS SQL and execute it.

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

    from app.services.ai_query import AIQueryService

    service = AIQueryService(db)
    try:
        return await service.query(payload.question, payload.context)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("AI query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Query execution failed. Please rephrase your question.") from exc
