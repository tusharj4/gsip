"""Service Gap Analyser.

Identifies underserved areas for hospitals, schools, anganwadis, and water
facilities based on population data and existing facility locations.

Service criteria from PM GatiShakti deck:
- Anganwadi:  800 pop/unit, 90sqm land, 1km service radius
- Hospital:   50,000 pop/unit, 10km service radius
- School:     1,000 pop/unit, 2km radius, 20% school-age cohort
"""

import json
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import GapAnalysis
from app.schemas.analysis import GapAnalysisRead

logger = logging.getLogger(__name__)

SERVICE_CRITERIA: dict[str, dict[str, Any]] = {
    "anganwadi": {
        "population_per_unit": 800,
        "land_area_sqm": 90,
        "ownership": "government",
        "min_dist_railway_m": 500,
        "min_dist_water_body_m": 100,
        "min_dist_crematorium_m": 500,
        "buffer_service_radius_m": 1000,
    },
    "hospital": {
        "population_per_unit": 50000,
        "buffer_service_radius_m": 10000,
        "check_layers": ["road_nh", "road_sh", "railway", "airport"],
    },
    "school": {
        "population_per_unit": 1000,
        "buffer_service_radius_m": 2000,
        "age_cohort_fraction": 0.20,
    },
    "water": {
        "population_per_unit": 5000,
        "buffer_service_radius_m": 500,
    },
}


class GapAnalyser:
    """Runs service gap analysis for a geographic study area."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def analyse(
        self,
        geography_geojson: dict[str, Any],
        analysis_type: str,
        population: int | None = None,
        service_radius_m: int | None = None,
    ) -> GapAnalysisRead:
        """Identify service gaps for the given facility type in the study area.

        Workflow:
        1. Count existing facilities (from layer_features) within the area
        2. Calculate required count from population / population_per_unit
        3. Build uncovered zones using ST_Difference on service buffers
        4. Identify candidate sites (government land, appropriate distance from exclusion zones)
        """
        criteria = SERVICE_CRITERIA[analysis_type]
        radius_m = service_radius_m or criteria["buffer_service_radius_m"]
        geo_str = json.dumps(geography_geojson)

        # Count existing facilities of this type within the geography
        existing_sql = text("""
            SELECT COUNT(*) AS cnt
            FROM layer_features lf
            JOIN gis_layers gl ON gl.id = lf.layer_id
            WHERE gl.slug = :slug
              AND gl.status = 'published'
              AND ST_Within(
                  lf.geom,
                  ST_SetSRID(ST_GeomFromGeoJSON(:geo), 4326)
              )
        """)
        existing_result = await self._db.execute(
            existing_sql, {"slug": analysis_type, "geo": geo_str}
        )
        existing_count = existing_result.scalar_one() or 0

        # Calculate required count
        pop = population or 0
        pop_per_unit = criteria["population_per_unit"]
        # Adjust for school-age cohort
        if analysis_type == "school" and pop:
            pop = int(pop * criteria.get("age_cohort_fraction", 1.0))
        required_count = max(0, -(-pop // pop_per_unit))  # ceiling division
        gap_count = max(0, required_count - existing_count)

        # Build uncovered area: study geography minus union of service buffers around existing facilities
        uncovered_sql = text("""
            WITH study_area AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geo), 4326) AS geom
            ),
            facility_buffers AS (
                SELECT ST_Union(
                    ST_Buffer(lf.geom::geography, :radius_m)::geometry
                ) AS geom
                FROM layer_features lf
                JOIN gis_layers gl ON gl.id = lf.layer_id
                WHERE gl.slug = :slug
                  AND gl.status = 'published'
                  AND ST_Within(lf.geom, (SELECT geom FROM study_area))
            )
            SELECT
                CASE
                    WHEN (SELECT geom FROM facility_buffers) IS NULL
                        THEN ST_AsGeoJSON((SELECT geom FROM study_area))::json
                    ELSE ST_AsGeoJSON(
                        ST_Difference(
                            (SELECT geom FROM study_area),
                            (SELECT geom FROM facility_buffers)
                        )
                    )::json
                END AS uncovered_geojson
        """)
        uncovered_result = await self._db.execute(
            uncovered_sql, {"geo": geo_str, "radius_m": radius_m, "slug": analysis_type}
        )
        uncovered_row = uncovered_result.fetchone()
        uncovered_geojson = uncovered_row.uncovered_geojson if uncovered_row else None

        # Persist analysis result
        analysis = GapAnalysis(
            analysis_type=analysis_type,
            population=population,
            required_count=required_count,
            existing_count=existing_count,
            gap_count=gap_count,
            candidate_sites=None,
            parameters={
                "service_radius_m": radius_m,
                "population_per_unit": pop_per_unit,
                **{k: v for k, v in criteria.items() if isinstance(v, (int, float, str))},
            },
        )
        self._db.add(analysis)
        await self._db.flush()

        # Set spatial columns via raw SQL
        set_geo_sql = text("""
            UPDATE gap_analyses
            SET geography = ST_SetSRID(ST_GeomFromGeoJSON(:geo), 4326)
            WHERE id = :id
        """)
        await self._db.execute(set_geo_sql, {"geo": geo_str, "id": str(analysis.id)})

        if uncovered_geojson:
            set_uncovered_sql = text("""
                UPDATE gap_analyses
                SET uncovered_geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)
                WHERE id = :id
            """)
            await self._db.execute(
                set_uncovered_sql, {"g": json.dumps(uncovered_geojson), "id": str(analysis.id)}
            )

        await self._db.refresh(analysis)

        logger.info(
            "Gap analysis '%s': existing=%d required=%d gap=%d",
            analysis_type,
            existing_count,
            required_count,
            gap_count,
        )

        return GapAnalysisRead(
            id=analysis.id,
            analysis_type=analysis_type,
            geography_geojson=geography_geojson,
            population=population,
            required_count=required_count,
            existing_count=existing_count,
            gap_count=gap_count,
            uncovered_geojson=uncovered_geojson,
            candidate_sites=None,
            parameters=analysis.parameters,
            created_at=analysis.created_at,
        )
