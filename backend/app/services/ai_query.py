"""AI Natural Language to PostGIS Query Service.

Uses Anthropic Claude API to translate plain English questions into
read-only PostGIS SQL queries, executes them, and returns GeoJSON results.
"""

import json
import logging
import re
import time
from typing import Any

import anthropic
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.schemas.ai import NLQueryResponse

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a PostGIS SQL expert for a geospatial infrastructure planning platform in India.
Convert natural language questions into valid PostGIS SQL queries.

Database schema:
- gis_layers(id UUID, name, slug, category, ministry_owner, status, metadata JSONB)
- layer_features(id BIGINT, layer_id UUID, geom geometry(Geometry,4326), properties JSONB)
- projects(id UUID, name, ministry, project_type, status, corridor_geom geometry(LineString,4326), buffer_m INT)
- conflict_reports(id UUID, project_id UUID, layer_id UUID, conflict_geom geometry, conflict_type, severity, area_sqm)
- gap_analyses(id UUID, analysis_type, geography geometry(Polygon,4326), population INT, required_count INT, existing_count INT, gap_count INT)

Key spatial functions:
- ST_DWithin(geom::geography, other::geography, meters) — distance filter using spatial index
- ST_Within(geom, polygon) — containment check
- ST_Intersects(geom, other) — overlap check
- ST_Buffer(geom::geography, meters)::geometry — buffer in meters
- ST_Distance(geom::geography, other::geography) — distance in meters
- ST_Area(geom::geography) — area in square meters
- ST_AsGeoJSON(geom) — output as GeoJSON

RULES:
1. Always use ST_DWithin for distance queries (exploits GIST spatial index)
2. Always cast to geography when distance/area must be in meters
3. Always add LIMIT 1000 unless the user specifies a different limit
4. Return ONLY the SQL query — no explanation, no markdown fences, no comments
5. NEVER use DROP, DELETE, UPDATE, INSERT, CREATE, ALTER, TRUNCATE — SELECT only
6. When returning geometry, always include ST_AsGeoJSON(geom)::json as geometry column
7. Use published layers: add WHERE gl.status = 'published' when querying layer_features via join"""


class AIQueryService:
    """Translates natural language to PostGIS SQL and executes it safely."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    async def query(
        self,
        question: str,
        context: dict[str, Any] | None = None,
    ) -> NLQueryResponse:
        """Translate a question to SQL, validate it, execute it, return results."""
        sql = await self._generate_sql(question, context)
        self._validate_sql(sql)

        start = time.perf_counter()
        rows, result_type, geojson = await self._execute_sql(sql)
        elapsed_ms = (time.perf_counter() - start) * 1000

        return NLQueryResponse(
            question=question,
            sql=sql,
            result_type=result_type,
            geojson=geojson,
            rows=rows if result_type == "table" else None,
            scalar=rows[0] if result_type == "scalar" and rows else None,
            row_count=len(rows) if rows else 0,
            execution_ms=round(elapsed_ms, 2),
        )

    async def _generate_sql(self, question: str, context: dict[str, Any] | None) -> str:
        """Call Claude API to generate a SQL query for the given question."""
        user_content = question
        if context:
            user_content += f"\n\nAdditional context: {json.dumps(context)}"

        message = self._client.messages.create(
            model=settings.anthropic_model,
            max_tokens=settings.anthropic_max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        sql = message.content[0].text.strip()
        # Strip markdown fences if Claude added them despite instructions
        sql = re.sub(r"^```(?:sql)?\n?", "", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\n?```$", "", sql)
        return sql.strip()

    @staticmethod
    def _validate_sql(sql: str) -> None:
        """Reject any SQL that is not a plain SELECT statement.

        This is the security gate preventing writes or DDL execution.
        """
        normalized = sql.strip().upper()
        if not normalized.startswith("SELECT"):
            raise ValueError("Only SELECT queries are permitted")
        dangerous = re.compile(
            r"\b(DROP|DELETE|UPDATE|INSERT|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE)\b",
            re.IGNORECASE,
        )
        if dangerous.search(sql):
            raise ValueError("Query contains disallowed SQL keywords")

    async def _execute_sql(
        self, sql: str
    ) -> tuple[list[dict[str, Any]], str, dict[str, Any] | None]:
        """Execute the validated SQL with a statement timeout.

        Returns (rows, result_type, optional_geojson).
        result_type is one of: 'geojson' | 'table' | 'scalar'
        """
        timeout_ms = settings.ai_sql_timeout_s * 1000
        set_timeout = text(f"SET LOCAL statement_timeout = {timeout_ms}")
        await self._db.execute(set_timeout)

        result = await self._db.execute(text(sql))
        columns = list(result.keys())
        raw_rows = result.fetchall()

        if not raw_rows:
            return [], "table", None

        rows = [dict(zip(columns, row)) for row in raw_rows]

        # Detect if any column contains GeoJSON geometry.
        # asyncpg may return ST_AsGeoJSON()::json as a string or a dict depending
        # on whether the json codec is registered — handle both.
        geo_col = None
        for col in columns:
            sample = rows[0].get(col)
            if isinstance(sample, str):
                try:
                    parsed = json.loads(sample)
                    if isinstance(parsed, dict) and "type" in parsed:
                        # Normalise all rows to dicts for this column
                        for row in rows:
                            raw = row.get(col)
                            if isinstance(raw, str):
                                row[col] = json.loads(raw)
                        geo_col = col
                        break
                except (json.JSONDecodeError, TypeError):
                    pass
            elif isinstance(sample, dict) and "type" in sample:
                geo_col = col
                break

        if geo_col:
            features = []
            for row in rows:
                geom = row.pop(geo_col, None)
                features.append({"type": "Feature", "geometry": geom, "properties": row})
            geojson: dict[str, Any] = {"type": "FeatureCollection", "features": features}
            return rows, "geojson", geojson

        if len(columns) == 1 and len(rows) == 1:
            return rows, "scalar", None

        return rows, "table", None
