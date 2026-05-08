"""Analysis endpoints — conflict detection, gap analysis, buffer queries."""

import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project
from app.schemas.analysis import (
    BufferQueryRequest,
    BufferQueryResponse,
    ConflictDetectRequest,
    ConflictReportRead,
    GapAnalysisRequest,
    GapAnalysisRead,
)

router = APIRouter()


@router.post("/conflicts", response_model=list[ConflictReportRead])
async def detect_conflicts(
    payload: ConflictDetectRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> list[ConflictReportRead]:
    """Run conflict detection for a project corridor against all published layers.

    Returns a ranked list of conflicts sorted by severity then area.
    Target latency: < 3 seconds for a 500km corridor.

    Response header `X-Detection-Ms` reports wall-clock execution time in milliseconds.
    """
    from app.services.conflict_detector import ConflictDetector

    project = await db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.corridor_geom is None:
        raise HTTPException(status_code=400, detail="Project has no corridor geometry")

    detector = ConflictDetector(db)
    t0 = time.perf_counter()
    conflicts = await detector.detect(
        project_id=payload.project_id,
        buffer_m=payload.buffer_m,
        layer_slugs=payload.layer_slugs,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    response.headers["X-Detection-Ms"] = f"{elapsed_ms:.1f}"
    response.headers["X-Conflict-Count"] = str(len(conflicts))
    return conflicts


@router.get("/conflicts/{project_id}", response_model=list[ConflictReportRead])
async def get_conflicts(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[ConflictReportRead]:
    """Retrieve previously computed conflicts for a project."""
    from sqlalchemy import select, text
    from app.models.analysis import ConflictReport

    result = await db.execute(
        select(ConflictReport).where(ConflictReport.project_id == project_id)
    )
    reports = result.scalars().all()
    if not reports:
        return []

    geojson_sql = text("""
        SELECT id, ST_AsGeoJSON(conflict_geom)::json AS geojson
        FROM conflict_reports WHERE project_id = :pid AND conflict_geom IS NOT NULL
    """)
    geo_result = await db.execute(geojson_sql, {"pid": str(project_id)})
    geojson_map = {row.id: row.geojson for row in geo_result}

    return [
        ConflictReportRead(
            id=r.id,
            project_id=r.project_id,
            layer_id=r.layer_id,
            conflict_geojson=geojson_map.get(r.id),
            conflict_type=r.conflict_type,
            severity=r.severity,
            area_sqm=float(r.area_sqm) if r.area_sqm else None,
            description=r.description,
            created_at=r.created_at,
        )
        for r in reports
    ]


@router.post("/gaps", response_model=GapAnalysisRead)
async def run_gap_analysis(
    payload: GapAnalysisRequest,
    db: AsyncSession = Depends(get_db),
) -> GapAnalysisRead:
    """Identify service gaps for hospitals, schools, or anganwadis in a geographic area."""
    from app.services.gap_analyser import GapAnalyser

    analyser = GapAnalyser(db)
    result = await analyser.analyse(
        geography_geojson=payload.geography_geojson,
        analysis_type=payload.analysis_type,
        population=payload.population,
        service_radius_m=payload.service_radius_m,
    )
    return result


@router.post("/buffer", response_model=BufferQueryResponse)
async def buffer_query(
    payload: BufferQueryRequest,
    db: AsyncSession = Depends(get_db),
) -> BufferQueryResponse:
    """Return all GIS features within a buffer distance of a given geometry."""
    from app.spatial.operations import buffer_intersect

    features = await buffer_intersect(
        db=db,
        geometry_geojson=payload.geometry_geojson,
        buffer_m=payload.buffer_m,
        categories=payload.categories,
        limit=payload.limit,
    )
    return BufferQueryResponse(
        features=features,
        total=len(features),
        buffer_m=payload.buffer_m,
    )


@router.get("/conflicts/{project_id}/benchmark", response_model=dict)
async def benchmark_conflict_detection(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Run EXPLAIN ANALYZE on the conflict detection query and return timing plan.

    Development/debug endpoint. Returns the raw PostgreSQL query plan with
    timing information to diagnose slow queries and identify missing indexes.
    """
    from app.spatial.operations import get_corridor_wkt

    corridor_wkt = await get_corridor_wkt(db, str(project_id))
    if not corridor_wkt:
        raise HTTPException(status_code=404, detail="Project has no corridor geometry")

    explain_sql = text("""
        EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)
        WITH buffered_corridor AS (
            SELECT ST_Buffer(
                ST_GeomFromText(:corridor_wkt, 4326)::geography,
                500
            )::geometry AS geom
        )
        SELECT
            lf.layer_id,
            ST_Area(
                ST_Intersection(lf.geom::geography, bc.geom::geography)
            ) AS area_sqm
        FROM layer_features lf
        JOIN gis_layers gl ON gl.id = lf.layer_id
        CROSS JOIN buffered_corridor bc
        WHERE gl.category IN ('regulatory', 'environmental')
          AND gl.status = 'published'
          AND ST_Intersects(lf.geom, bc.geom)
    """)

    t0 = time.perf_counter()
    result = await db.execute(explain_sql, {"corridor_wkt": corridor_wkt})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    plan = result.fetchone()

    return {
        "project_id": str(project_id),
        "explain_ms": round(elapsed_ms, 2),
        "plan": plan[0] if plan else None,
    }
