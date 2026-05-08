"""Tests for the ConflictDetector service with known geometries."""

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _seed_regulatory_layer(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a minimal regulatory layer and one polygon feature for testing."""
    layer_result = await db.execute(
        text("""
            INSERT INTO gis_layers (id, name, slug, category, status, metadata)
            VALUES (:id, 'Test Forest', 'test_forest', 'regulatory', 'published', '{}'::jsonb)
            RETURNING id
        """),
        {"id": str(uuid.uuid4())},
    )
    layer_id = layer_result.scalar_one()

    # Small polygon near Mumbai (Thane forest area approximation)
    await db.execute(
        text("""
            INSERT INTO layer_features (layer_id, geom, properties)
            VALUES (
                :lid,
                ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326),
                :props
            )
        """),
        {
            "lid": str(layer_id),
            "geom": json.dumps({
                "type": "Polygon",
                "coordinates": [[[72.9, 19.2], [73.1, 19.2], [73.1, 19.4], [72.9, 19.4], [72.9, 19.2]]]
            }),
            "props": json.dumps({"conflict_type": "protected_forest"}),
        },
    )

    project_result = await db.execute(
        text("""
            INSERT INTO projects (id, name, project_type, status, buffer_m, metadata, corridor_geom)
            VALUES (
                :id, 'Test NH Project', 'road', 'draft', 500, '{}'::jsonb,
                ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)
            )
            RETURNING id
        """),
        {
            "id": str(uuid.uuid4()),
            "geom": json.dumps({
                "type": "LineString",
                "coordinates": [[72.8, 19.1], [73.0, 19.3], [73.2, 19.5]]
            }),
        },
    )
    project_id = project_result.scalar_one()
    return layer_id, project_id


@pytest.mark.asyncio
async def test_conflict_detector_finds_forest(db: AsyncSession) -> None:
    """ConflictDetector should find the forest polygon intersecting the corridor."""
    from app.services.conflict_detector import ConflictDetector

    _layer_id, project_id = await _seed_regulatory_layer(db)

    detector = ConflictDetector(db)
    conflicts = await detector.detect(project_id=project_id, buffer_m=500)

    assert len(conflicts) >= 1
    conflict = conflicts[0]
    assert conflict.conflict_type == "protected_forest"
    assert conflict.severity == "blocker"
    assert conflict.area_sqm is not None and conflict.area_sqm > 0


@pytest.mark.asyncio
async def test_conflict_detector_no_corridor_raises(db: AsyncSession) -> None:
    """ConflictDetector should raise ValueError for a project with no corridor."""
    from app.services.conflict_detector import ConflictDetector

    project_result = await db.execute(
        text("""
            INSERT INTO projects (id, name, project_type, status, buffer_m, metadata)
            VALUES (:id, 'Bare Project', 'road', 'draft', 500, '{}'::jsonb)
            RETURNING id
        """),
        {"id": str(uuid.uuid4())},
    )
    project_id = project_result.scalar_one()

    detector = ConflictDetector(db)
    with pytest.raises(ValueError, match="No corridor geometry"):
        await detector.detect(project_id=project_id, buffer_m=500)
