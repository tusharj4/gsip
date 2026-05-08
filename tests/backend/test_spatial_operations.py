"""Tests for spatial query helpers in app.spatial.operations.

Uses a real test PostGIS database seeded with known geometries.
All assertions are made against exact, known geometry inputs so failures
are unambiguous rather than data-dependent.
"""

import json
import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _seed_published_layer(db: AsyncSession, slug: str, category: str) -> str:
    """Insert a published GIS layer and one Point feature at Mumbai."""
    layer_id = str(uuid.uuid4())
    row = await db.execute(
        text("""
            INSERT INTO gis_layers (id, name, slug, category, status, metadata)
            VALUES (:id, :name, :slug, :cat, 'published', '{}'::jsonb)
            RETURNING id
        """),
        {"id": layer_id, "name": f"Test {slug}", "slug": slug, "cat": category},
    )
    layer_id = str(row.scalar_one())

    await db.execute(
        text("""
            INSERT INTO layer_features (layer_id, geom, properties)
            VALUES (
                :lid,
                ST_SetSRID(ST_MakePoint(72.87, 19.07), 4326),
                '{"source": "test"}'::jsonb
            )
        """),
        {"lid": layer_id},
    )
    return layer_id


# ─── buffer_intersect ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_buffer_intersect_finds_nearby_feature(db: AsyncSession) -> None:
    """A feature at Mumbai should appear within 1000m of a Mumbai point."""
    from app.spatial.operations import buffer_intersect

    await _seed_published_layer(db, "infra_road_test", "infrastructure")

    # Querying from a point 500m from Mumbai — inside the 1000m buffer
    features = await buffer_intersect(
        db=db,
        geometry_geojson={"type": "Point", "coordinates": [72.870, 19.074]},
        buffer_m=1_000,
        categories=["infrastructure"],
        limit=50,
    )
    assert len(features) >= 1
    f = features[0]
    assert f["type"] == "Feature"
    assert f["geometry"]["type"] == "Point"
    assert f["properties"]["layer_slug"] == "infra_road_test"


@pytest.mark.asyncio
async def test_buffer_intersect_excludes_far_features(db: AsyncSession) -> None:
    """A feature at Mumbai should NOT appear within 1m of Kolkata."""
    from app.spatial.operations import buffer_intersect

    await _seed_published_layer(db, "infra_power_test", "infrastructure")

    features = await buffer_intersect(
        db=db,
        geometry_geojson={"type": "Point", "coordinates": [88.36, 22.57]},  # Kolkata
        buffer_m=1,
        categories=["infrastructure"],
        limit=100,
    )
    # No features from Mumbai should appear within 1m of Kolkata
    slugs = [f["properties"]["layer_slug"] for f in features]
    assert "infra_power_test" not in slugs


@pytest.mark.asyncio
async def test_buffer_intersect_respects_category_filter(db: AsyncSession) -> None:
    """buffer_intersect should only return features from the requested categories."""
    from app.spatial.operations import buffer_intersect

    await _seed_published_layer(db, "reg_forest_test", "regulatory")

    features = await buffer_intersect(
        db=db,
        geometry_geojson={"type": "Point", "coordinates": [72.87, 19.07]},
        buffer_m=10_000,
        categories=["infrastructure"],  # regulatory excluded
        limit=100,
    )
    regulatory_hits = [f for f in features if f["properties"]["category"] == "regulatory"]
    assert len(regulatory_hits) == 0


@pytest.mark.asyncio
async def test_buffer_intersect_unpublished_excluded(db: AsyncSession) -> None:
    """Draft layers should not appear in buffer_intersect results."""
    from app.spatial.operations import buffer_intersect

    # Insert a DRAFT layer at the same Mumbai point
    row = await db.execute(
        text("""
            INSERT INTO gis_layers (id, name, slug, category, status, metadata)
            VALUES (:id, 'Draft Layer', 'draft_test_xyz', 'infrastructure', 'draft', '{}'::jsonb)
            RETURNING id
        """),
        {"id": str(uuid.uuid4())},
    )
    layer_id = str(row.scalar_one())
    await db.execute(
        text("""
            INSERT INTO layer_features (layer_id, geom, properties)
            VALUES (:lid, ST_SetSRID(ST_MakePoint(72.87, 19.07), 4326), '{}'::jsonb)
        """),
        {"lid": layer_id},
    )

    features = await buffer_intersect(
        db=db,
        geometry_geojson={"type": "Point", "coordinates": [72.87, 19.07]},
        buffer_m=100,
        categories=["infrastructure"],
        limit=100,
    )
    slugs = [f["properties"]["layer_slug"] for f in features]
    assert "draft_test_xyz" not in slugs


@pytest.mark.asyncio
async def test_buffer_intersect_returns_list_type(db: AsyncSession) -> None:
    """buffer_intersect should return a list even when no features match."""
    from app.spatial.operations import buffer_intersect

    features = await buffer_intersect(
        db=db,
        geometry_geojson={"type": "Point", "coordinates": [0.0, 0.0]},  # Gulf of Guinea
        buffer_m=1,
        categories=["infrastructure"],
        limit=100,
    )
    assert isinstance(features, list)
    assert len(features) == 0


# ─── ensure_srid ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ensure_srid_point(db: AsyncSession) -> None:
    """ensure_srid converts a Point GeoJSON to WKT with correct coordinates."""
    from app.spatial.operations import ensure_srid

    wkt = await ensure_srid(db, {"type": "Point", "coordinates": [72.87, 19.07]})
    assert "POINT" in wkt.upper()
    assert "72.87" in wkt
    assert "19.07" in wkt


@pytest.mark.asyncio
async def test_ensure_srid_linestring(db: AsyncSession) -> None:
    """ensure_srid handles a LineString geometry."""
    from app.spatial.operations import ensure_srid

    wkt = await ensure_srid(db, {
        "type": "LineString",
        "coordinates": [[72.87, 19.07], [73.0, 19.5], [73.2, 20.0]],
    })
    assert "LINESTRING" in wkt.upper()


@pytest.mark.asyncio
async def test_ensure_srid_polygon(db: AsyncSession) -> None:
    """ensure_srid handles a Polygon geometry."""
    from app.spatial.operations import ensure_srid

    wkt = await ensure_srid(db, {
        "type": "Polygon",
        "coordinates": [[[72.8, 19.0], [73.1, 19.0], [73.1, 19.4], [72.8, 19.4], [72.8, 19.0]]],
    })
    assert "POLYGON" in wkt.upper()


@pytest.mark.asyncio
async def test_ensure_srid_invalid_geometry(db: AsyncSession) -> None:
    """ensure_srid should raise ValueError for an unrecognised geometry type."""
    from app.spatial.operations import ensure_srid

    with pytest.raises(ValueError, match="Invalid GeoJSON"):
        await ensure_srid(db, {"type": "NotAGeometry", "coordinates": []})


@pytest.mark.asyncio
async def test_ensure_srid_empty_coordinates(db: AsyncSession) -> None:
    """ensure_srid raises ValueError for a Point with empty coordinates."""
    from app.spatial.operations import ensure_srid

    with pytest.raises(ValueError):
        await ensure_srid(db, {"type": "Point", "coordinates": []})


# ─── get_corridor_wkt ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_corridor_wkt_returns_wkt(db: AsyncSession) -> None:
    """get_corridor_wkt should return a WKT string for a project with a corridor."""
    from app.spatial.operations import get_corridor_wkt

    row = await db.execute(
        text("""
            INSERT INTO projects (id, name, project_type, status, buffer_m, metadata, corridor_geom)
            VALUES (
                :id, 'Test Corridor', 'road', 'draft', 500, '{}'::jsonb,
                ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)
            )
            RETURNING id
        """),
        {
            "id": str(uuid.uuid4()),
            "geom": json.dumps({
                "type": "LineString",
                "coordinates": [[72.8, 19.0], [73.0, 19.3], [73.2, 19.6]],
            }),
        },
    )
    project_id = str(row.scalar_one())

    wkt = await get_corridor_wkt(db, project_id)
    assert wkt is not None
    assert "LINESTRING" in wkt.upper()


@pytest.mark.asyncio
async def test_get_corridor_wkt_returns_none_for_missing(db: AsyncSession) -> None:
    """get_corridor_wkt should return None for a project without a corridor."""
    from app.spatial.operations import get_corridor_wkt

    row = await db.execute(
        text("""
            INSERT INTO projects (id, name, project_type, status, buffer_m, metadata)
            VALUES (:id, 'No Corridor', 'road', 'draft', 500, '{}'::jsonb)
            RETURNING id
        """),
        {"id": str(uuid.uuid4())},
    )
    project_id = str(row.scalar_one())

    wkt = await get_corridor_wkt(db, project_id)
    assert wkt is None


@pytest.mark.asyncio
async def test_get_corridor_wkt_returns_none_for_bad_id(db: AsyncSession) -> None:
    """get_corridor_wkt should return None for a non-existent project ID."""
    from app.spatial.operations import get_corridor_wkt
    import uuid

    wkt = await get_corridor_wkt(db, str(uuid.uuid4()))
    assert wkt is None


# ─── PostGIS sanity checks ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_postgis_extension_available(db: AsyncSession) -> None:
    """Verify PostGIS is installed and ST_Buffer is callable."""
    result = await db.execute(text("SELECT ST_Buffer(ST_Point(0, 0)::geography, 1000)::text"))
    row = result.fetchone()
    assert row is not None
    assert row[0]


@pytest.mark.asyncio
async def test_st_within_basic(db: AsyncSession) -> None:
    """ST_Within should correctly report a point inside a bounding polygon."""
    result = await db.execute(text("""
        SELECT ST_Within(
            ST_SetSRID(ST_MakePoint(72.87, 19.07), 4326),
            ST_MakeEnvelope(72.0, 18.0, 74.0, 20.0, 4326)
        ) AS inside
    """))
    row = result.fetchone()
    assert row is not None
    assert row.inside is True


@pytest.mark.asyncio
async def test_st_dwithin_distance(db: AsyncSession) -> None:
    """ST_DWithin with geography cast should report two points within 100km."""
    result = await db.execute(text("""
        SELECT ST_DWithin(
            ST_SetSRID(ST_MakePoint(72.87, 19.07), 4326)::geography,
            ST_SetSRID(ST_MakePoint(72.97, 19.17), 4326)::geography,
            100000  -- 100km
        ) AS nearby
    """))
    row = result.fetchone()
    assert row is not None
    assert row.nearby is True


@pytest.mark.asyncio
async def test_gist_index_exists(db: AsyncSession) -> None:
    """Verify the GIST index on layer_features.geom exists."""
    result = await db.execute(text("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'layer_features'
          AND indexdef ILIKE '%gist%'
    """))
    indexes = [row.indexname for row in result]
    assert len(indexes) >= 1, "No GIST index found on layer_features"
