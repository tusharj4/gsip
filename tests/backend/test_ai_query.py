"""Tests for the AIQueryService — SQL generation, validation, and execution.

The Anthropic API call is mocked so these tests run without a real API key
and without network access.  The DB execution tests run against the real
PostGIS test database (same fixture as the other backend tests).
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_query import AIQueryService


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_service_with_mock_sql(db: AsyncSession, sql: str) -> AIQueryService:
    """Return an AIQueryService whose _generate_sql always returns `sql`."""
    service = AIQueryService(db)
    service._generate_sql = AsyncMock(return_value=sql)  # type: ignore[method-assign]
    return service


# ─── SQL validation ───────────────────────────────────────────────────────────

def test_validate_sql_accepts_select() -> None:
    """Pure SELECT must pass validation without error."""
    AIQueryService._validate_sql("SELECT count(*) FROM gis_layers")


def test_validate_sql_rejects_non_select() -> None:
    """Any statement that does not start with SELECT must be rejected."""
    with pytest.raises(ValueError, match="Only SELECT"):
        AIQueryService._validate_sql("INSERT INTO gis_layers (name) VALUES ('x')")


def test_validate_sql_rejects_delete() -> None:
    """DELETE inside a SELECT (e.g. CTE abuse) must be rejected."""
    with pytest.raises(ValueError, match="disallowed SQL keywords"):
        AIQueryService._validate_sql(
            "SELECT 1; DELETE FROM gis_layers WHERE 1=1"
        )


def test_validate_sql_rejects_drop() -> None:
    with pytest.raises(ValueError, match="disallowed SQL keywords"):
        AIQueryService._validate_sql("SELECT * FROM gis_layers; DROP TABLE gis_layers")


def test_validate_sql_rejects_update() -> None:
    with pytest.raises(ValueError, match="disallowed SQL keywords"):
        AIQueryService._validate_sql("SELECT id FROM projects WHERE UPDATE")


def test_validate_sql_rejects_create() -> None:
    """CREATE does not start with SELECT — caught by the prefix check."""
    with pytest.raises(ValueError, match="Only SELECT"):
        AIQueryService._validate_sql("CREATE TABLE evil AS SELECT 1")


def test_validate_sql_rejects_insert_in_with() -> None:
    """WITH-clause INSERT: starts with WITH, not SELECT — caught by prefix check."""
    with pytest.raises(ValueError, match="Only SELECT"):
        AIQueryService._validate_sql(
            "WITH x AS (INSERT INTO gis_layers DEFAULT VALUES) SELECT 1"
        )


# ─── _execute_sql on real DB ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_returns_scalar(db: AsyncSession) -> None:
    """A single-column single-row query should be classified as 'scalar'."""
    service = _make_service_with_mock_sql(db, "SELECT 42 AS answer")
    rows, result_type, geojson = await service._execute_sql("SELECT 42 AS answer")
    assert result_type == "scalar"
    assert geojson is None
    assert rows[0]["answer"] == 42


@pytest.mark.asyncio
async def test_execute_returns_table(db: AsyncSession) -> None:
    """A multi-column query should be classified as 'table'."""
    sql = "SELECT 1 AS a, 'hello' AS b"
    service = _make_service_with_mock_sql(db, sql)
    rows, result_type, geojson = await service._execute_sql(sql)
    assert result_type == "table"
    assert geojson is None
    assert rows[0]["a"] == 1
    assert rows[0]["b"] == "hello"


@pytest.mark.asyncio
async def test_execute_returns_empty_table(db: AsyncSession) -> None:
    """No-row result must return empty list with type 'table'."""
    sql = "SELECT 1 WHERE false"
    service = _make_service_with_mock_sql(db, sql)
    rows, result_type, geojson = await service._execute_sql(sql)
    assert result_type == "table"
    assert rows == []
    assert geojson is None


@pytest.mark.asyncio
async def test_execute_detects_geojson_column(db: AsyncSession) -> None:
    """ST_AsGeoJSON() column should trigger 'geojson' result type with FeatureCollection."""
    sql = """
        SELECT
            ST_AsGeoJSON(ST_MakePoint(72.87, 19.07))::json AS geometry,
            'Mumbai' AS city
    """
    service = _make_service_with_mock_sql(db, sql)
    rows, result_type, geojson = await service._execute_sql(sql)
    assert result_type == "geojson"
    assert geojson is not None
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 1
    feat = geojson["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] == "Point"
    assert feat["properties"]["city"] == "Mumbai"


@pytest.mark.asyncio
async def test_execute_statement_timeout_applied(db: AsyncSession) -> None:
    """statement_timeout SET LOCAL must be issued before the query."""
    issued: list[str] = []
    original_execute = db.execute

    async def capturing_execute(stmt: object, *args: object, **kwargs: object) -> object:
        issued.append(str(stmt))
        return await original_execute(stmt, *args, **kwargs)

    db.execute = capturing_execute  # type: ignore[method-assign]
    service = _make_service_with_mock_sql(db, "SELECT 1")
    await service._execute_sql("SELECT 1")

    timeout_cmds = [s for s in issued if "statement_timeout" in s.lower()]
    assert len(timeout_cmds) >= 1, "Expected SET LOCAL statement_timeout to be issued"


# ─── Full query() pipeline with mocked Claude ─────────────────────────────────

@pytest.mark.asyncio
async def test_query_end_to_end_scalar(db: AsyncSession) -> None:
    """Full query() call with mocked Claude returns a valid NLQueryResponse."""
    service = AIQueryService(db)

    # Mock the async Anthropic client
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="SELECT count(*) FROM gis_layers")]
    service._client.messages.create = AsyncMock(return_value=mock_message)

    result = await service.query("How many GIS layers are there?")

    assert result.question == "How many GIS layers are there?"
    assert "SELECT" in result.sql.upper()
    assert result.result_type in {"scalar", "table"}
    assert result.execution_ms >= 0


@pytest.mark.asyncio
async def test_query_strips_markdown_fences(db: AsyncSession) -> None:
    """Claude sometimes wraps SQL in markdown fences — they must be stripped."""
    service = AIQueryService(db)

    fenced_sql = "```sql\nSELECT 1 AS ok\n```"
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=fenced_sql)]
    service._client.messages.create = AsyncMock(return_value=mock_message)

    result = await service.query("test")
    assert result.sql == "SELECT 1 AS ok"
    assert result.result_type == "scalar"


@pytest.mark.asyncio
async def test_query_raises_on_invalid_sql(db: AsyncSession) -> None:
    """query() must raise ValueError when Claude generates non-SELECT SQL."""
    service = AIQueryService(db)

    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="DROP TABLE gis_layers")]
    service._client.messages.create = AsyncMock(return_value=mock_message)

    with pytest.raises(ValueError, match="Only SELECT"):
        await service.query("delete everything")


@pytest.mark.asyncio
async def test_query_geojson_result(db: AsyncSession) -> None:
    """query() must return geojson result_type when geometry is present."""
    service = AIQueryService(db)

    sql = "SELECT ST_AsGeoJSON(ST_MakePoint(78.9, 20.5))::json AS geometry, 'test' AS name"
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text=sql)]
    service._client.messages.create = AsyncMock(return_value=mock_message)

    result = await service.query("Show me a point in central India")
    assert result.result_type == "geojson"
    assert result.geojson is not None
    assert result.geojson["type"] == "FeatureCollection"
    assert result.row_count == 1
