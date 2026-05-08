"""OSM Data Loader — pulls real Indian GIS data via osmnx into PostGIS.

Supports:
- Road networks (NH, SH, all driveable roads)
- Railways
- Hospitals, schools, anganwadis
- Forests and protected areas
- Water bodies

Usage:
    python -m app.tasks.ingest_osm --place "Maharashtra, India" --tags roads,railways,hospitals
    python -m app.tasks.ingest_osm --place "Gujarat, India" --tags all

Idempotent: uses ON CONFLICT DO NOTHING on layer slug + geometry hash.
All geometries reprojected to EPSG:4326 at load time.
"""

import argparse
import asyncio
import hashlib
import json
import logging
from typing import Any

import geopandas as gpd
import osmnx as ox
from shapely.geometry import mapping
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.spatial.projections import to_wgs84

logger = logging.getLogger(__name__)

# Map OSM tag sets to GSIP layer slugs and categories
OSM_DATASETS: dict[str, dict[str, Any]] = {
    "roads": {
        "slug": "road_nh",
        "name": "National & State Highways (OSM)",
        "category": "infrastructure",
        "ministry_owner": "Ministry of Road Transport and Highways",
        "osmnx_tags": {"highway": ["motorway", "trunk", "primary", "secondary"]},
        "osmnx_type": "features",
        "conflict_type": None,
    },
    "railways": {
        "slug": "railway",
        "name": "Railway Network (OSM)",
        "category": "infrastructure",
        "ministry_owner": "Ministry of Railways",
        "osmnx_tags": {"railway": "rail"},
        "osmnx_type": "features",
        "conflict_type": None,
    },
    "hospitals": {
        "slug": "hospital",
        "name": "Hospitals and Health Centres (OSM)",
        "category": "socioeconomic",
        "ministry_owner": "Ministry of Health and Family Welfare",
        "osmnx_tags": {"amenity": ["hospital", "clinic", "health_post", "doctors"]},
        "osmnx_type": "features",
        "conflict_type": None,
    },
    "schools": {
        "slug": "school",
        "name": "Schools (OSM)",
        "category": "socioeconomic",
        "ministry_owner": "Ministry of Education",
        "osmnx_tags": {"amenity": ["school", "college", "university"]},
        "osmnx_type": "features",
        "conflict_type": None,
    },
    "forests": {
        "slug": "protected_forest",
        "name": "Forest and Protected Areas (OSM)",
        "category": "regulatory",
        "ministry_owner": "Ministry of Environment, Forest and Climate Change",
        "osmnx_tags": {"landuse": ["forest", "conservation"], "boundary": "protected_area"},
        "osmnx_type": "features",
        "conflict_type": "protected_forest",
    },
    "water": {
        "slug": "water_body",
        "name": "Rivers and Water Bodies (OSM)",
        "category": "natural",
        "ministry_owner": "Ministry of Jal Shakti",
        "osmnx_tags": {"natural": ["water", "wetland"], "waterway": ["river", "canal"]},
        "osmnx_type": "features",
        "conflict_type": "river",
    },
    "anganwadis": {
        "slug": "anganwadi",
        "name": "Anganwadi Centres (OSM)",
        "category": "socioeconomic",
        "ministry_owner": "Ministry of Women and Child Development",
        "osmnx_tags": {"amenity": "social_facility", "social_facility": "day_care"},
        "osmnx_type": "features",
        "conflict_type": None,
    },
}


async def ensure_layer(db: AsyncSession, dataset: dict[str, Any]) -> str:
    """Upsert a gis_layers row and return its UUID."""
    result = await db.execute(
        text("""
            INSERT INTO gis_layers (name, slug, category, ministry_owner, status)
            VALUES (:name, :slug, :category, :ministry_owner, 'published')
            ON CONFLICT (slug) DO UPDATE
                SET name = EXCLUDED.name,
                    status = 'published',
                    last_synced_at = NOW()
            RETURNING id
        """),
        {
            "name": dataset["name"],
            "slug": dataset["slug"],
            "category": dataset["category"],
            "ministry_owner": dataset.get("ministry_owner", ""),
        },
    )
    return str(result.scalar_one())


def _geom_hash(geom_dict: dict[str, Any]) -> str:
    """Deterministic hash of a GeoJSON geometry for upsert dedup."""
    canonical = json.dumps(geom_dict, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _pull_osm_features(place: str, tags: dict[str, Any]) -> gpd.GeoDataFrame:
    """Download OSM features for a place using osmnx."""
    ox.settings.log_console = False
    ox.settings.use_cache = True
    ox.settings.cache_folder = "/tmp/osmnx_cache"

    try:
        gdf = ox.features_from_place(place, tags=tags)
    except Exception as exc:
        logger.warning("osmnx fetch failed for place=%r tags=%s: %s", place, tags, exc)
        return gpd.GeoDataFrame()

    if gdf.empty:
        return gdf

    # Reproject to WGS84 if needed
    if gdf.crs and str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    # Keep only valid, non-empty geometries
    gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty].copy()
    return gdf


def _build_properties(row: Any, conflict_type: str | None) -> dict[str, Any]:
    """Extract a clean JSON-serialisable properties dict from an OSM row."""
    keep_cols = [
        "name", "name:en", "amenity", "highway", "railway",
        "landuse", "boundary", "natural", "waterway",
        "operator", "addr:city", "addr:state", "osm_id",
    ]
    props: dict[str, Any] = {}
    for col in keep_cols:
        val = getattr(row, col, None)
        if val is not None and str(val) not in ("nan", "None", ""):
            props[col] = str(val)

    if conflict_type:
        props["conflict_type"] = conflict_type

    return props


async def bulk_insert_features(
    db: AsyncSession,
    layer_id: str,
    gdf: gpd.GeoDataFrame,
    conflict_type: str | None,
    batch_size: int = 500,
) -> int:
    """Bulk-insert GeoDataFrame rows into layer_features.

    Uses parameterised INSERT … ON CONFLICT DO NOTHING for idempotency.
    Returns the count of rows actually inserted.
    """
    inserted = 0
    rows = list(gdf.iterrows())
    total = len(rows)

    for batch_start in range(0, total, batch_size):
        batch = rows[batch_start : batch_start + batch_size]
        values = []
        params: dict[str, Any] = {"layer_id": layer_id}

        for i, (_, row) in enumerate(batch):
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            geom_dict = mapping(geom)
            geom_json = json.dumps(geom_dict)
            props = _build_properties(row, conflict_type)
            props_json = json.dumps(props)

            params[f"geom_{i}"] = geom_json
            params[f"props_{i}"] = props_json
            values.append(
                f"(:layer_id, ST_SetSRID(ST_GeomFromGeoJSON(:geom_{i}), 4326), :props_{i}::jsonb)"
            )

        if not values:
            continue

        sql = text(f"""
            INSERT INTO layer_features (layer_id, geom, properties)
            VALUES {", ".join(values)}
            ON CONFLICT DO NOTHING
        """)
        result = await db.execute(sql, params)
        inserted += result.rowcount or len(values)
        await db.commit()
        logger.info(
            "  Batch %d–%d: %d rows inserted",
            batch_start,
            batch_start + len(batch),
            result.rowcount or len(values),
        )

    return inserted


async def ingest_dataset(
    db: AsyncSession,
    place: str,
    dataset_key: str,
) -> int:
    """Ingest a single OSM dataset for the given place. Returns rows inserted."""
    dataset = OSM_DATASETS[dataset_key]
    logger.info("Ingesting '%s' for '%s'...", dataset_key, place)

    gdf = _pull_osm_features(place, dataset["osmnx_tags"])
    if gdf.empty:
        logger.info("  No features found — skipping")
        return 0

    logger.info("  Fetched %d features from OSM", len(gdf))
    layer_id = await ensure_layer(db, dataset)
    count = await bulk_insert_features(db, layer_id, gdf, dataset.get("conflict_type"))
    logger.info("  Done: %d features inserted for layer '%s'", count, dataset["slug"])
    return count


async def run_ingestion(place: str, datasets: list[str]) -> None:
    """Entry point: ingest all requested datasets for a place."""
    async with AsyncSessionLocal() as db:
        total = 0
        for key in datasets:
            if key not in OSM_DATASETS:
                logger.warning("Unknown dataset key '%s' — skipping. Valid: %s", key, list(OSM_DATASETS))
                continue
            count = await ingest_dataset(db, place, key)
            total += count
        logger.info("Ingestion complete: %d features total across %d datasets", total, len(datasets))


def main() -> None:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
    )
    parser = argparse.ArgumentParser(description="Ingest OSM data into GSIP PostGIS database")
    parser.add_argument(
        "--place",
        default="Gujarat, India",
        help="Place name passed to osmnx (e.g. 'Maharashtra, India')",
    )
    parser.add_argument(
        "--tags",
        default="roads,railways,hospitals,schools,forests,water",
        help="Comma-separated dataset keys. Use 'all' for everything.",
    )
    args = parser.parse_args()

    keys = list(OSM_DATASETS.keys()) if args.tags == "all" else args.tags.split(",")
    asyncio.run(run_ingestion(args.place, keys))


if __name__ == "__main__":
    main()
