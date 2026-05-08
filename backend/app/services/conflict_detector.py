"""Conflict Detection Engine.

Given a proposed project corridor (LineString), buffers it by the specified
distance and intersects against all regulatory/environmental layers.

Severity rules:
  blocker → Forest (protected), Wildlife Sanctuary, National Park, CRZ Zone 1
  high    → Eco-sensitive zone, Wetland RAMSAR, Heritage monument buffer
  medium  → River/water body, Mining zone, Habitation buffer
  low     → CRZ Zone 2/3, SEZ overlap, Common land (Gochar)
"""

import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import ConflictReport
from app.schemas.analysis import ConflictReportRead
from app.spatial.operations import get_corridor_wkt

logger = logging.getLogger(__name__)

SEVERITY_MAP: dict[str, str] = {
    "protected_forest": "blocker",
    "wildlife_sanctuary": "blocker",
    "national_park": "blocker",
    "crz_zone_1": "blocker",
    "eco_sensitive": "high",
    "wetland_ramsar": "high",
    "heritage_buffer": "high",
    "river": "medium",
    "water_body": "medium",
    "mining_zone": "medium",
    "habitation_buffer": "medium",
    "crz_zone_2": "low",
    "crz_zone_3": "low",
    "sez": "low",
    "gochar": "low",
}

SEVERITY_ORDER = {"blocker": 0, "high": 1, "medium": 2, "low": 3}


class ConflictDetector:
    """Runs spatial conflict detection for a project corridor."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def detect(
        self,
        project_id: uuid.UUID,
        buffer_m: int = 500,
        layer_slugs: list[str] | None = None,
    ) -> list[ConflictReportRead]:
        """Buffer the corridor and intersect against published regulatory layers.

        Persists results to conflict_reports and returns them ranked by severity.
        Must complete in < 3 seconds for a 500km corridor (uses GIST index).
        """
        corridor_wkt = await get_corridor_wkt(self._db, str(project_id))
        if not corridor_wkt:
            raise ValueError(f"No corridor geometry found for project {project_id}")

        params: dict[str, Any] = {
            "corridor_wkt": corridor_wkt,
            "buffer_m": buffer_m,
            "project_id": str(project_id),
        }
        # Build slug filter using individual placeholders to avoid asyncpg array binding issues
        slug_filter = ""
        if layer_slugs:
            placeholders = ", ".join(f":slug_{i}" for i in range(len(layer_slugs)))
            slug_filter = f"AND gl.slug IN ({placeholders})"
            for i, slug in enumerate(layer_slugs):
                params[f"slug_{i}"] = slug

        sql = text(f"""
            WITH buffered_corridor AS (
                SELECT ST_Buffer(
                    ST_GeomFromText(:corridor_wkt, 4326)::geography,
                    :buffer_m
                )::geometry AS geom
            ),
            conflicts AS (
                SELECT
                    lf.layer_id,
                    gl.name            AS layer_name,
                    gl.category,
                    gl.slug            AS layer_slug,
                    lf.properties->>'conflict_type' AS conflict_type,
                    ST_Intersection(lf.geom, bc.geom) AS conflict_geom,
                    ST_Area(
                        ST_Intersection(
                            lf.geom::geography,
                            bc.geom::geography
                        )
                    ) AS area_sqm
                FROM layer_features lf
                JOIN gis_layers gl ON gl.id = lf.layer_id
                CROSS JOIN buffered_corridor bc
                WHERE gl.category IN ('regulatory', 'environmental')
                  AND gl.status = 'published'
                  {slug_filter}
                  AND ST_Intersects(lf.geom, bc.geom)
            )
            SELECT
                layer_id,
                layer_name,
                conflict_type,
                ST_AsGeoJSON(conflict_geom)::json AS conflict_geojson,
                area_sqm
            FROM conflicts
            ORDER BY area_sqm DESC
            LIMIT 500
        """)

        result = await self._db.execute(sql, params)
        rows = result.fetchall()

        reports = []
        for row in rows:
            conflict_type = row.conflict_type or "unknown"
            severity = SEVERITY_MAP.get(conflict_type, "low")

            report = ConflictReport(
                project_id=project_id,
                layer_id=row.layer_id,
                conflict_type=conflict_type,
                severity=severity,
                area_sqm=row.area_sqm,
                description=f"{row.layer_name}: {conflict_type} ({severity} severity)",
            )
            # Set conflict_geom via raw SQL to avoid ORM geometry round-trip
            self._db.add(report)
            await self._db.flush()

            if row.conflict_geojson:
                await self._db.execute(
                    text("UPDATE conflict_reports SET conflict_geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) WHERE id = :id"),
                    {"g": str(row.conflict_geojson), "id": str(report.id)},
                )

            reports.append(
                ConflictReportRead(
                    id=report.id,
                    project_id=project_id,
                    layer_id=row.layer_id,
                    conflict_geojson=row.conflict_geojson,
                    conflict_type=conflict_type,
                    severity=severity,
                    area_sqm=float(row.area_sqm) if row.area_sqm else None,
                    description=report.description,
                    created_at=report.created_at,
                )
            )

        # Sort by severity (blocker first), then area descending
        reports.sort(key=lambda r: (SEVERITY_ORDER.get(r.severity or "low", 3), -(r.area_sqm or 0)))
        logger.info(
            "Conflict detection for project %s: %d conflicts found (buffer=%dm)",
            project_id,
            len(reports),
            buffer_m,
        )
        return reports
