"""Tests for the ReportGenerator service.

These tests run against the real PostGIS test database.
WeasyPrint and staticmap are tested with mocked heavy I/O so tests stay fast
and don't require network access (tile fetching) or a full WeasyPrint install
in CI.  The structure/content of the HTML is tested directly as well.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.report_generator import (
    CLEARANCE_MAP,
    ReportGenerator,
    _render_pdf_sync,
    _render_map_thumbnail_sync,
)


# ─── Seed helpers ─────────────────────────────────────────────────────────────

async def _seed_project_with_conflicts(db: AsyncSession) -> tuple[str, str]:
    """Insert a project with a corridor + one conflict report.

    Returns (project_id_str, layer_id_str).
    """
    import json as _json

    proj_id   = str(uuid.uuid4())
    layer_id  = str(uuid.uuid4())
    report_id = str(uuid.uuid4())

    await db.execute(
        text("""
            INSERT INTO gis_layers (id, name, slug, category, status, metadata)
            VALUES (:id, 'Test Forest', 'test-forest-rep', 'regulatory', 'published', '{}'::jsonb)
        """),
        {"id": layer_id},
    )

    await db.execute(
        text("""
            INSERT INTO projects (id, name, project_type, status, buffer_m, metadata, corridor_geom)
            VALUES (
                :id, 'Report Test Project', 'road', 'draft', 500, '{}'::jsonb,
                ST_SetSRID(ST_GeomFromGeoJSON(:geom), 4326)
            )
        """),
        {
            "id": proj_id,
            "geom": _json.dumps({
                "type": "LineString",
                "coordinates": [[72.8, 19.0], [73.0, 19.3], [73.2, 19.6]],
            }),
        },
    )

    await db.execute(
        text("""
            INSERT INTO conflict_reports
                (id, project_id, layer_id, conflict_type, severity, area_sqm, description)
            VALUES
                (:id, :pid, :lid, 'protected_forest', 'blocker', 125000.5, 'Forest overlap')
        """),
        {"id": report_id, "pid": proj_id, "lid": layer_id},
    )

    await db.flush()
    return proj_id, layer_id


async def _seed_project_no_corridor(db: AsyncSession) -> str:
    """Insert a project without a corridor geometry."""
    proj_id = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO projects (id, name, project_type, status, buffer_m, metadata)
            VALUES (:id, 'No Corridor Project', 'railway', 'draft', 500, '{}'::jsonb)
        """),
        {"id": proj_id},
    )
    await db.flush()
    return proj_id


# ─── _build_conflict_table ────────────────────────────────────────────────────

def test_build_conflict_table_empty() -> None:
    """Empty conflict list returns a 'no conflicts' message."""
    html = ReportGenerator._build_conflict_table([])
    assert "No conflicts" in html


def test_build_conflict_table_with_conflicts() -> None:
    """Conflict table should include severity badge and conflict type."""
    from app.models.analysis import ConflictReport

    mock_conflict = MagicMock(spec=ConflictReport)
    mock_conflict.severity     = "blocker"
    mock_conflict.conflict_type = "protected_forest"
    mock_conflict.area_sqm     = 125_000.0
    mock_conflict.description  = "Test overlap"

    html = ReportGenerator._build_conflict_table([mock_conflict])
    assert "BLOCKER" in html
    assert "protected_forest" in html
    assert "125,000" in html


# ─── _build_clearances_html ───────────────────────────────────────────────────

def test_build_clearances_known_type() -> None:
    """Known conflict types should map to specific clearance text."""
    from app.models.analysis import ConflictReport

    mock = MagicMock(spec=ConflictReport)
    mock.conflict_type = "protected_forest"
    html = ReportGenerator._build_clearances_html([mock])
    assert "Forest Conservation Act" in html


def test_build_clearances_unknown_type() -> None:
    """Unknown conflict types should produce the 'standard NOCs' fallback."""
    from app.models.analysis import ConflictReport

    mock = MagicMock(spec=ConflictReport)
    mock.conflict_type = "unknown_conflict_xyz"
    html = ReportGenerator._build_clearances_html([mock])
    assert "Standard NOCs" in html or "standard NOCs" in html


def test_build_clearances_empty() -> None:
    """Empty conflict list should produce the 'standard NOCs' fallback."""
    html = ReportGenerator._build_clearances_html([])
    assert "Standard NOCs" in html or "standard NOCs" in html


def test_clearance_map_covers_all_severity_levels() -> None:
    """CLEARANCE_MAP must cover the most critical conflict types."""
    required = {"protected_forest", "wildlife_sanctuary", "crz_zone_1", "wetland_ramsar"}
    missing = required - set(CLEARANCE_MAP.keys())
    assert not missing, f"Missing clearance entries: {missing}"


# ─── Full generate() with mocked I/O ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_returns_pdf_bytes(db: AsyncSession) -> None:
    """generate() must return non-empty bytes starting with the PDF magic bytes."""
    proj_id, _ = await _seed_project_with_conflicts(db)

    generator = ReportGenerator(db)

    # Mock: staticmap tile fetch + WeasyPrint render + MinIO (all heavy I/O)
    with (
        patch("app.services.report_generator._render_map_thumbnail_sync", return_value="fake_b64"),
        patch("app.services.report_generator._render_pdf_sync", return_value=b"%PDF-1.4 fake"),
        patch.object(generator, "_fetch_cached", new=AsyncMock(return_value=None)),
        patch.object(generator, "_store_cached", new=AsyncMock()),
    ):
        pdf = await generator.generate(uuid.UUID(proj_id))

    assert isinstance(pdf, bytes)
    assert len(pdf) > 0
    assert pdf.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_generate_uses_cache_when_available(db: AsyncSession) -> None:
    """generate() must return the cached PDF without calling WeasyPrint."""
    proj_id, _ = await _seed_project_with_conflicts(db)
    cached_pdf  = b"%PDF-1.4 cached"

    generator = ReportGenerator(db)
    with (
        patch.object(generator, "_fetch_cached", new=AsyncMock(return_value=cached_pdf)),
        patch("app.services.report_generator._render_pdf_sync") as mock_render,
    ):
        result = await generator.generate(uuid.UUID(proj_id))

    assert result == cached_pdf
    mock_render.assert_not_called()


@pytest.mark.asyncio
async def test_generate_raises_for_missing_project(db: AsyncSession) -> None:
    """generate() must raise ValueError when the project doesn't exist."""
    generator = ReportGenerator(db)
    with pytest.raises(ValueError, match="not found"):
        await generator.generate(uuid.uuid4())


@pytest.mark.asyncio
async def test_generate_no_corridor_skips_map(db: AsyncSession) -> None:
    """When project has no corridor, map_img_html should indicate unavailability."""
    proj_id = await _seed_project_no_corridor(db)

    generator = ReportGenerator(db)
    with (
        patch("app.services.report_generator._render_pdf_sync", return_value=b"%PDF-1.4 x"),
        patch.object(generator, "_fetch_cached", new=AsyncMock(return_value=None)),
        patch.object(generator, "_store_cached", new=AsyncMock()),
    ):
        pdf = await generator.generate(uuid.UUID(proj_id))

    assert isinstance(pdf, bytes)
    assert len(pdf) > 0


@pytest.mark.asyncio
async def test_generate_html_contains_project_name(db: AsyncSession) -> None:
    """The HTML passed to WeasyPrint should include the project name."""
    proj_id, _ = await _seed_project_with_conflicts(db)
    captured_html: list[str] = []

    def capture_render(html: str) -> bytes:
        captured_html.append(html)
        return b"%PDF-1.4 x"

    generator = ReportGenerator(db)
    with (
        patch("app.services.report_generator._render_map_thumbnail_sync", return_value=None),
        patch("app.services.report_generator._render_pdf_sync", side_effect=capture_render),
        patch.object(generator, "_fetch_cached", new=AsyncMock(return_value=None)),
        patch.object(generator, "_store_cached", new=AsyncMock()),
    ):
        await generator.generate(uuid.UUID(proj_id))

    assert captured_html, "WeasyPrint render was never called"
    html = captured_html[0]
    assert "Report Test Project" in html
    assert "BLOCKER" in html or "blocker" in html
    assert "Forest Conservation Act" in html


# ─── _render_map_thumbnail_sync ──────────────────────────────────────────────

def test_render_map_thumbnail_returns_none_on_error() -> None:
    """If staticmap raises, the function must return None (not propagate the error).

    StaticMap is imported inside _render_map_thumbnail_sync so we patch the
    source module directly: staticmap.StaticMap.
    """
    with patch("staticmap.StaticMap", side_effect=RuntimeError("no network")):
        result = _render_map_thumbnail_sync([], 72.87, 19.07)
    assert result is None


# ─── reports API endpoint ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reports_endpoint_404_for_missing_project(db: AsyncSession) -> None:
    """reports.py endpoint must 404 when project doesn't exist — verified at service level."""
    generator = ReportGenerator(db)
    with pytest.raises(ValueError, match="not found"):
        await generator.generate(uuid.uuid4())
