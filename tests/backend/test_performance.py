"""Performance benchmark tests for GSIP analysis engines.

These tests assert timing SLAs under realistic conditions:
  - Conflict detection for a 500km corridor: < 3 seconds
  - Buffer query across all published layers: < 2 seconds
  - Gap analysis computation: < 2 seconds
  - Route scoring: < 3 seconds

Tests seed their own data so they are self-contained and idempotent.
Run individually with: docker compose run --rm backend pytest tests/backend/test_performance.py -v
"""

import json
import time
import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ─── Seed helpers ─────────────────────────────────────────────────────────────

async def _seed_large_regulatory_dataset(db: AsyncSession, n_polygons: int = 200) -> str:
    """Seed N small polygons across Gujarat to simulate a realistic regulatory layer.

    Returns the layer_id as a string.
    """
    row = await db.execute(
        text("""
            INSERT INTO gis_layers (id, name, slug, category, status, metadata)
            VALUES (:id, 'Perf Forest Layer', :slug, 'regulatory', 'published', '{}'::jsonb)
            RETURNING id
        """),
        {"id": str(uuid.uuid4()), "slug": f"perf_forest_{uuid.uuid4().hex[:8]}"},
    )
    layer_id = str(row.scalar_one())

    # Insert N 0.1° × 0.1° polygons scattered across Gujarat (68–74°E, 20–24°N)
    lat_step = 4.0 / (n_polygons ** 0.5)
    lon_step = 6.0 / (n_polygons ** 0.5)

    batch_sql = text("""
        INSERT INTO layer_features (layer_id, geom, properties)
        SELECT
            :layer_id,
            ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326),
            CAST(:props AS jsonb)
        FROM (SELECT 1) t
    """)

    lat = 20.0
    lon = 68.0
    inserted = 0
    while inserted < n_polygons:
        geom = {
            "type": "Polygon",
            "coordinates": [[
                [round(lon, 4), round(lat, 4)],
                [round(lon + 0.1, 4), round(lat, 4)],
                [round(lon + 0.1, 4), round(lat + 0.1, 4)],
                [round(lon, 4), round(lat + 0.1, 4)],
                [round(lon, 4), round(lat, 4)],
            ]],
        }
        await db.execute(batch_sql, {
            "layer_id": layer_id,
            "geom": json.dumps(geom),
            "props": json.dumps({"conflict_type": "protected_forest"}),
        })
        lon += lon_step
        if lon > 74.0:
            lon = 68.0
            lat += lat_step
        inserted += 1

    return layer_id


async def _seed_500km_corridor_project(db: AsyncSession) -> str:
    """Create a project with a ~500km corridor across Gujarat."""
    # Mumbai (72.87, 19.07) → Ahmedabad (72.58, 23.02): ~440km by air
    # Extended to Kandla (70.22, 23.00): ~570km total — approximately 500km
    row = await db.execute(
        text("""
            INSERT INTO projects (id, name, project_type, status, buffer_m, metadata, corridor_geom)
            VALUES (
                :id, 'Perf Test NH48', 'road', 'draft', 500, '{}'::jsonb,
                ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)
            )
            RETURNING id
        """),
        {
            "id": str(uuid.uuid4()),
            "geom": json.dumps({
                "type": "LineString",
                "coordinates": [
                    [72.87, 19.07],   # Mumbai
                    [72.60, 20.50],   # Surat
                    [72.58, 21.80],   # Vadodara
                    [72.58, 23.02],   # Ahmedabad
                    [71.50, 23.02],   # Rajkot
                    [70.22, 23.00],   # Kandla/Gandhidham
                ],
            }),
        },
    )
    return str(row.scalar_one())


# ─── Conflict detection benchmark ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_conflict_detection_under_3s(db: AsyncSession) -> None:
    """Conflict detection for a ~500km corridor must complete in < 3 seconds.

    This is the core latency SLA from CLAUDE.md.
    Seeds 200 polygons to approximate a realistic regulatory dataset.
    """
    from app.services.conflict_detector import ConflictDetector

    await _seed_large_regulatory_dataset(db, n_polygons=200)
    project_id = await _seed_500km_corridor_project(db)

    detector = ConflictDetector(db)

    start = time.perf_counter()
    conflicts = await detector.detect(
        project_id=uuid.UUID(project_id),
        buffer_m=500,
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 3.0, (
        f"Conflict detection took {elapsed:.2f}s — SLA is < 3s. "
        "Consider ST_Subdivide on large polygons or adding partial indexes."
    )
    # Verify it actually found some conflicts (our polygon grid intersects the corridor)
    assert len(conflicts) >= 1, "Expected at least one conflict from seeded data"
    assert all(c.severity in {"blocker", "high", "medium", "low"} for c in conflicts)


@pytest.mark.asyncio
async def test_conflict_detection_severity_ordering(db: AsyncSession) -> None:
    """Conflicts must be returned with blockers before high, high before medium."""
    from app.services.conflict_detector import ConflictDetector
    from app.services.conflict_detector import SEVERITY_ORDER

    await _seed_large_regulatory_dataset(db, n_polygons=10)
    project_id = await _seed_500km_corridor_project(db)

    detector = ConflictDetector(db)
    conflicts = await detector.detect(project_id=uuid.UUID(project_id), buffer_m=500)

    # Verify severity is monotonically non-decreasing (better → worse allowed, never reversed)
    orders = [SEVERITY_ORDER.get(c.severity or "low", 3) for c in conflicts]
    assert orders == sorted(orders), (
        f"Conflicts not sorted by severity: {[c.severity for c in conflicts]}"
    )


# ─── Gap analysis benchmark ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gap_analysis_under_2s(db: AsyncSession) -> None:
    """Gap analysis for a district-sized area must complete in < 2 seconds."""
    from app.services.gap_analyser import GapAnalyser

    surendranagar_bbox = {
        "type": "Polygon",
        "coordinates": [[[71.2, 22.5], [72.5, 22.5], [72.5, 23.5], [71.2, 23.5], [71.2, 22.5]]],
    }

    analyser = GapAnalyser(db)

    start = time.perf_counter()
    result = await analyser.analyse(
        geography_geojson=surendranagar_bbox,
        analysis_type="anganwadi",
        population=459_200,
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"Gap analysis took {elapsed:.2f}s — SLA is < 2s"
    assert result.required_count == 574  # 459200 / 800 = 574
    assert result.gap_count == 574       # No existing anganwadis in test DB


# ─── Buffer query benchmark ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_buffer_query_under_2s(db: AsyncSession) -> None:
    """Buffer query with 500km radius must return in < 2 seconds."""
    from app.spatial.operations import buffer_intersect

    # Seed 100 published infrastructure features
    row = await db.execute(
        text("""
            INSERT INTO gis_layers (id, name, slug, category, status, metadata)
            VALUES (:id, 'Perf Roads', :slug, 'infrastructure', 'published', '{}'::jsonb)
            RETURNING id
        """),
        {"id": str(uuid.uuid4()), "slug": f"perf_roads_{uuid.uuid4().hex[:8]}"},
    )
    layer_id = str(row.scalar_one())

    for i in range(100):
        lon = 68.0 + (i % 10) * 0.5
        lat = 20.0 + (i // 10) * 0.3
        await db.execute(
            text("""
                INSERT INTO layer_features (layer_id, geom, properties)
                VALUES (:lid, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), '{}'::jsonb)
            """),
            {"lid": layer_id, "lon": round(lon, 4), "lat": round(lat, 4)},
        )

    start = time.perf_counter()
    features = await buffer_intersect(
        db=db,
        geometry_geojson={"type": "Point", "coordinates": [72.58, 23.02]},
        buffer_m=500_000,  # 500km
        categories=["infrastructure"],
        limit=1000,
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"Buffer query took {elapsed:.2f}s — SLA is < 2s"
    assert isinstance(features, list)


# ─── Route scoring benchmark ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_route_optimizer_under_3s(db: AsyncSession) -> None:
    """Route optimizer scoring for a ~500km corridor must complete in < 3 seconds."""
    from app.services.route_optimizer import RouteOptimizer

    corridor_geojson = {
        "type": "LineString",
        "coordinates": [
            [72.87, 19.07],
            [72.60, 20.50],
            [72.58, 21.80],
            [72.58, 23.02],
            [71.50, 23.02],
            [70.22, 23.00],
        ],
    }

    optimizer = RouteOptimizer(db)

    start = time.perf_counter()
    result = await optimizer.optimize(
        proposed_corridor_geojson=corridor_geojson,
        project_type="road",
        buffer_m=500,
        n_alternatives=3,
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 3.0, f"Route optimizer took {elapsed:.2f}s — SLA is < 3s"
    assert len(result.alternatives) >= 1
    assert result.alternatives[0].length_m > 0


@pytest.mark.asyncio
async def test_route_optimizer_returns_alternatives(db: AsyncSession) -> None:
    """Route optimizer must return at least 1 alternative (up to n_alternatives)."""
    from app.services.route_optimizer import RouteOptimizer

    corridor_geojson = {
        "type": "LineString",
        "coordinates": [[72.87, 19.07], [73.5, 20.5], [74.0, 22.0]],
    }

    optimizer = RouteOptimizer(db)
    result = await optimizer.optimize(
        proposed_corridor_geojson=corridor_geojson,
        project_type="railway",
        buffer_m=1000,
        n_alternatives=3,
    )

    assert 1 <= len(result.alternatives) <= 3
    # Alternatives must be sorted by score ascending (lower score = better)
    scores = [a.score for a in result.alternatives]
    assert scores == sorted(scores), f"Alternatives not sorted by score: {scores}"
    # Each must have a valid geometry
    for alt in result.alternatives:
        assert alt.corridor_geojson["type"] == "LineString"
        assert len(alt.corridor_geojson["coordinates"]) >= 2
