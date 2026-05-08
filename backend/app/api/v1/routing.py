"""Route optimization endpoint — find best infrastructure corridor alignments."""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db

router = APIRouter()


class RouteOptimizeRequest(BaseModel):
    """Request body for corridor alignment optimization."""

    # GeoJSON LineString of the proposed alignment
    proposed_corridor_geojson: dict[str, Any]
    project_type: str = Field(..., pattern=r"^(road|railway|pipeline|power|telecom)$")
    buffer_m: int = Field(default=500, ge=50, le=50000)
    # Number of alternative alignments to return
    n_alternatives: int = Field(default=3, ge=1, le=5)


class AlignmentScore(BaseModel):
    """Scored alignment alternative."""

    rank: int
    corridor_geojson: dict[str, Any]
    length_m: float
    forest_overlap_sqm: float
    settlement_overlap_sqm: float
    crz_overlap_sqm: float
    estimated_cost_crore: float | None
    score: float  # Lower is better


class RouteOptimizeResponse(BaseModel):
    """Response containing ranked corridor alternatives."""

    alternatives: list[AlignmentScore]
    optimization_parameters: dict[str, Any]


@router.post("/optimize", response_model=RouteOptimizeResponse)
async def optimize_corridor(
    payload: RouteOptimizeRequest,
    db: AsyncSession = Depends(get_db),
) -> RouteOptimizeResponse:
    """Generate and score alternative corridor alignments.

    Uses pgRouting pgr_dijkstra on the road/terrain network.
    Scores each path on: distance, forest/settlement/CRZ overlap, cost.
    Returns top N alternatives ranked by composite score.
    """
    from app.services.route_optimizer import RouteOptimizer

    optimizer = RouteOptimizer(db)
    return await optimizer.optimize(
        proposed_corridor_geojson=payload.proposed_corridor_geojson,
        project_type=payload.project_type,
        buffer_m=payload.buffer_m,
        n_alternatives=payload.n_alternatives,
    )
