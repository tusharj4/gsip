"""Route Optimizer — multi-path corridor alignment scoring.

Strategy (Phase 3):
  Generates N alternative alignments by laterally offsetting the proposed
  corridor using ST_OffsetCurve in EPSG:3857 (WebMercator, meter-accurate
  at India's latitude within ~10% error — acceptable for planning).

  Each alternative is independently scored on:
    - Total corridor length (metres)
    - Forest/protected-area intersection area (sq m)
    - Settlement intersection area (sq m)
    - CRZ overlap area (sq m)

  Alternatives are ranked by composite weighted score (lower = better).

  Full pgRouting network-based multi-path is available when the
  road_network layer (slug='road_network') is loaded AND the pgrouting
  extension is present (Phase 6 upgrade path).
"""

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routing import AlignmentScore, RouteOptimizeResponse

logger = logging.getLogger(__name__)

# Composite score weights (lower total score = better alignment)
SCORE_WEIGHTS: dict[str, float] = {
    "length_m": 0.0001,             # per metre — distance penalty
    "forest_overlap_sqm": 0.05,     # per sq m — blocker-class penalty
    "settlement_overlap_sqm": 0.02,  # per sq m — high-class penalty
    "crz_overlap_sqm": 0.03,        # per sq m — CRZ penalty
}

# Lateral offsets generated for alternatives (metres, EPSG:3857-accurate)
# 0 = proposed corridor; positive = right/north; negative = left/south
_OFFSET_METRES: list[float] = [0.0, 20_000.0, -20_000.0, 40_000.0, -40_000.0]


class RouteOptimizer:
    """Generates and scores alternative corridor alignments."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def optimize(
        self,
        proposed_corridor_geojson: dict[str, Any],
        project_type: str,
        buffer_m: int = 500,
        n_alternatives: int = 3,
    ) -> RouteOptimizeResponse:
        """Score the proposed corridor and generate laterally-offset alternatives.

        Returns up to *n_alternatives* alternatives sorted by composite score.
        The proposed corridor is always included as one of the candidates.
        """
        n = min(n_alternatives, len(_OFFSET_METRES))
        offsets = _OFFSET_METRES[:n]

        candidates: list[AlignmentScore] = []

        for i, offset_m in enumerate(offsets):
            geojson, length_m = await self._generate_corridor(
                proposed_corridor_geojson, offset_m
            )
            if geojson is None:
                logger.warning("Could not generate corridor at offset %.0fm — skipping", offset_m)
                continue

            forest_sqm, settlement_sqm, crz_sqm = await self._score_corridor(
                geojson, buffer_m
            )

            score = (
                length_m * SCORE_WEIGHTS["length_m"]
                + forest_sqm * SCORE_WEIGHTS["forest_overlap_sqm"]
                + settlement_sqm * SCORE_WEIGHTS["settlement_overlap_sqm"]
                + crz_sqm * SCORE_WEIGHTS["crz_overlap_sqm"]
            )

            candidates.append(
                AlignmentScore(
                    rank=i + 1,  # re-ranked after sort below
                    corridor_geojson=geojson,
                    length_m=length_m,
                    forest_overlap_sqm=forest_sqm,
                    settlement_overlap_sqm=settlement_sqm,
                    crz_overlap_sqm=crz_sqm,
                    estimated_cost_crore=self._estimate_cost(length_m, project_type),
                    score=round(score, 4),
                )
            )

        # Sort by score ascending, re-assign ranks
        candidates.sort(key=lambda a: a.score)
        for rank, alt in enumerate(candidates, start=1):
            alt.rank = rank

        logger.info(
            "Route optimization: %d alternatives scored (buffer=%dm, project_type=%s)",
            len(candidates),
            buffer_m,
            project_type,
        )

        return RouteOptimizeResponse(
            alternatives=candidates,
            optimization_parameters={
                "buffer_m": buffer_m,
                "project_type": project_type,
                "n_requested": n_alternatives,
                "n_generated": len(candidates),
                "offsets_m": offsets,
                "weights": SCORE_WEIGHTS,
                "method": "ST_OffsetCurve (EPSG:3857 lateral shift)",
                "upgrade_path": (
                    "Full pgRouting pgr_dijkstra multi-path available when "
                    "road_network layer is loaded and pgrouting extension is installed"
                ),
            },
        )

    async def _generate_corridor(
        self,
        base_geojson: dict[str, Any],
        offset_m: float,
    ) -> tuple[dict[str, Any] | None, float]:
        """Return (geojson, length_m) for the corridor, optionally laterally offset.

        Uses EPSG:3857 for metre-accurate offset, then reprojects to 4326.
        Returns (None, 0) if ST_OffsetCurve fails (e.g. degenerate geometry).
        """
        geojson_str = json.dumps(base_geojson)

        if offset_m == 0.0:
            # Proposed corridor — no transformation needed
            sql = text("""
                SELECT
                    ST_AsGeoJSON(ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326))::json AS geojson,
                    ST_Length(ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326)::geography) AS length_m
            """)
            row = (await self._db.execute(sql, {"geojson": geojson_str})).fetchone()
        else:
            # Offset: project to 3857 (metres), offset, reproject to 4326
            sql = text("""
                WITH base AS (
                    SELECT ST_Transform(
                        ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326),
                        3857
                    ) AS geom
                ),
                offset_geom AS (
                    SELECT ST_OffsetCurve(geom, :offset_m) AS geom FROM base
                )
                SELECT
                    CASE WHEN (SELECT geom FROM offset_geom) IS NULL THEN NULL
                    ELSE ST_AsGeoJSON(
                        ST_Transform((SELECT geom FROM offset_geom), 4326)
                    )::json END AS geojson,
                    CASE WHEN (SELECT geom FROM offset_geom) IS NULL THEN 0
                    ELSE ST_Length(
                        ST_Transform((SELECT geom FROM offset_geom), 4326)::geography
                    ) END AS length_m
            """)
            row = (await self._db.execute(sql, {"geojson": geojson_str, "offset_m": offset_m})).fetchone()

        if row is None or row.geojson is None:
            return None, 0.0

        geojson = row.geojson if isinstance(row.geojson, dict) else json.loads(row.geojson)
        return geojson, float(row.length_m or 0)

    async def _score_corridor(
        self,
        corridor_geojson: dict[str, Any],
        buffer_m: int,
    ) -> tuple[float, float, float]:
        """Return (forest_sqm, settlement_sqm, crz_sqm) for overlap with published layers.

        Buffers the corridor in geography (metre-accurate) then intersects
        published regulatory/environmental features.
        """
        geojson_str = json.dumps(corridor_geojson)

        score_sql = text("""
            WITH corridor AS (
                SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326) AS geom
            ),
            buffered AS (
                SELECT ST_Buffer(geom::geography, :buffer_m)::geometry AS geom
                FROM corridor
            ),
            forest_overlap AS (
                SELECT COALESCE(SUM(
                    ST_Area(ST_Intersection(lf.geom::geography, b.geom::geography))
                ), 0) AS area_sqm
                FROM layer_features lf
                JOIN gis_layers gl ON gl.id = lf.layer_id
                CROSS JOIN buffered b
                WHERE gl.status = 'published'
                  AND lf.properties->>'conflict_type' IN (
                      'protected_forest', 'national_park', 'wildlife_sanctuary'
                  )
                  AND ST_Intersects(lf.geom, b.geom)
            ),
            settlement_overlap AS (
                SELECT COALESCE(SUM(
                    ST_Area(ST_Intersection(lf.geom::geography, b.geom::geography))
                ), 0) AS area_sqm
                FROM layer_features lf
                JOIN gis_layers gl ON gl.id = lf.layer_id
                CROSS JOIN buffered b
                WHERE gl.status = 'published'
                  AND lf.properties->>'conflict_type' = 'habitation_buffer'
                  AND ST_Intersects(lf.geom, b.geom)
            ),
            crz_overlap AS (
                SELECT COALESCE(SUM(
                    ST_Area(ST_Intersection(lf.geom::geography, b.geom::geography))
                ), 0) AS area_sqm
                FROM layer_features lf
                JOIN gis_layers gl ON gl.id = lf.layer_id
                CROSS JOIN buffered b
                WHERE gl.status = 'published'
                  AND lf.properties->>'conflict_type' LIKE 'crz%%'
                  AND ST_Intersects(lf.geom, b.geom)
            )
            SELECT
                (SELECT area_sqm FROM forest_overlap) AS forest_sqm,
                (SELECT area_sqm FROM settlement_overlap) AS settlement_sqm,
                (SELECT area_sqm FROM crz_overlap) AS crz_sqm
        """)

        result = await self._db.execute(
            score_sql, {"geojson": geojson_str, "buffer_m": buffer_m}
        )
        row = result.fetchone()
        if row is None:
            return 0.0, 0.0, 0.0

        return (
            float(row.forest_sqm or 0),
            float(row.settlement_sqm or 0),
            float(row.crz_sqm or 0),
        )

    @staticmethod
    def _estimate_cost(length_m: float, project_type: str) -> float | None:
        """Rough per-km cost estimate in crore INR based on project type.

        Sources: MoRTH 2023 average costs; NITI Aayog infra reports.
        These are planning-level estimates only.
        """
        cost_per_km_crore: dict[str, float] = {
            "road": 12.5,        # NH 4-lane: ~₹12.5 Cr/km
            "railway": 45.0,     # New line: ~₹45 Cr/km
            "pipeline": 5.0,     # Natural gas: ~₹5 Cr/km
            "power": 3.0,        # Transmission line: ~₹3 Cr/km
            "telecom": 1.5,      # OFC: ~₹1.5 Cr/km
        }
        rate = cost_per_km_crore.get(project_type)
        if rate is None:
            return None
        return round((length_m / 1000) * rate, 2)
