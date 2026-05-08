"""Reusable PostGIS query helpers used across multiple services."""

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def buffer_intersect(
    db: AsyncSession,
    geometry_geojson: dict[str, Any],
    buffer_m: float,
    categories: list[str],
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """Return all layer features that intersect a buffered geometry.

    Uses ST_DWithin on geography for accurate meter-based distance filtering.
    Requires GIST index on layer_features.geom (present by schema definition).
    """
    geojson_str = json.dumps(geometry_geojson)
    cat_placeholders = ", ".join(f":cat{i}" for i in range(len(categories)))
    cat_params = {f"cat{i}": cat for i, cat in enumerate(categories)}

    sql = text(f"""
        SELECT
            lf.id,
            gl.name AS layer_name,
            gl.category,
            gl.slug AS layer_slug,
            ST_AsGeoJSON(lf.geom)::json AS geometry,
            lf.properties
        FROM layer_features lf
        JOIN gis_layers gl ON gl.id = lf.layer_id
        WHERE gl.status = 'published'
          AND gl.category IN ({cat_placeholders})
          AND ST_DWithin(
              lf.geom::geography,
              ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326)::geography,
              :buffer_m
          )
        LIMIT :limit
    """)

    result = await db.execute(
        sql,
        {
            "geojson": geojson_str,
            "buffer_m": buffer_m,
            "limit": limit,
            **cat_params,
        },
    )
    rows = result.fetchall()

    return [
        {
            "type": "Feature",
            "id": row.id,
            "geometry": row.geometry,
            "properties": {
                **row.properties,
                "layer_name": row.layer_name,
                "layer_slug": row.layer_slug,
                "category": row.category,
            },
        }
        for row in rows
    ]


async def get_corridor_wkt(db: AsyncSession, project_id: str) -> str | None:
    """Retrieve a project corridor as WKT text for use in spatial queries."""
    sql = text(
        "SELECT ST_AsText(corridor_geom) AS wkt FROM projects WHERE id = :pid AND corridor_geom IS NOT NULL"
    )
    result = await db.execute(sql, {"pid": project_id})
    row = result.fetchone()
    return row.wkt if row else None


async def ensure_srid(db: AsyncSession, geojson: dict[str, Any]) -> str:
    """Convert a GeoJSON geometry to WKT with SRID 4326.

    Validates that the geometry is parseable before returning.
    Raises ValueError if the geometry is invalid or has empty coordinates.
    """
    geo_type = geojson.get("type", "")
    valid_types = {
        "Point", "MultiPoint", "LineString", "MultiLineString",
        "Polygon", "MultiPolygon", "GeometryCollection",
    }
    if geo_type not in valid_types:
        raise ValueError(f"Invalid GeoJSON geometry type: {geo_type!r}")

    # Reject empty coordinates before hitting PostGIS — ST_GeomFromGeoJSON
    # silently accepts [] and returns POINT EMPTY, which is degenerate.
    coords = geojson.get("coordinates")
    if geo_type != "GeometryCollection" and isinstance(coords, list) and len(coords) == 0:
        raise ValueError(f"Invalid GeoJSON geometry: empty coordinates for type {geo_type!r}")

    geojson_str = json.dumps(geojson)
    sql = text("""
        SELECT ST_AsText(ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326)) AS wkt
    """)
    try:
        result = await db.execute(sql, {"g": geojson_str})
        row = result.fetchone()
        if not row or not row.wkt:
            raise ValueError("Could not parse geometry")
        return row.wkt
    except Exception as exc:
        raise ValueError(f"Invalid GeoJSON geometry: {exc}") from exc
