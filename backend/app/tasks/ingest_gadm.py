"""GADM Administrative Boundaries Loader.

Downloads and loads India's state and district boundaries from GADM
(https://gadm.org/download_country.html) into PostGIS.

GADM level 1 = States (36 states/UTs)
GADM level 2 = Districts (~700+)
GADM level 3 = Sub-districts / Tehsils

Usage:
    python -m app.tasks.ingest_gadm --level 1 --shapefile /data/gadm/gadm41_IND_1.shp
    python -m app.tasks.ingest_gadm --level 2 --shapefile /data/gadm/gadm41_IND_2.shp

Or auto-download (requires internet, ~50MB for level 2):
    python -m app.tasks.ingest_gadm --level 2 --download

Idempotent: ON CONFLICT DO NOTHING on geometry.
"""

import argparse
import asyncio
import io
import json
import logging
import os
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
import requests
from shapely.geometry import mapping
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

GADM_DOWNLOAD_URLS = {
    1: "https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_IND_1.zip",
    2: "https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_IND_2.zip",
    3: "https://geodata.ucdavis.edu/gadm/gadm4.1/shp/gadm41_IND_3.zip",
}

GADM_LAYER_CONFIG = {
    1: {
        "slug": "admin_state",
        "name": "India State Boundaries (GADM 4.1)",
        "category": "socioeconomic",
        "name_col": "NAME_1",
        "code_col": "GID_1",
    },
    2: {
        "slug": "admin_district",
        "name": "India District Boundaries (GADM 4.1)",
        "category": "socioeconomic",
        "name_col": "NAME_2",
        "code_col": "GID_2",
        "parent_col": "NAME_1",
    },
    3: {
        "slug": "admin_subdistrict",
        "name": "India Sub-district Boundaries (GADM 4.1)",
        "category": "socioeconomic",
        "name_col": "NAME_3",
        "code_col": "GID_3",
        "parent_col": "NAME_2",
    },
}


def download_gadm(level: int, cache_dir: str = "/tmp/gadm_cache") -> str:
    """Download and unzip a GADM shapefile. Returns path to the .shp file."""
    os.makedirs(cache_dir, exist_ok=True)
    shp_path = os.path.join(cache_dir, f"gadm41_IND_{level}.shp")
    if os.path.exists(shp_path):
        logger.info("Using cached GADM level %d from %s", level, shp_path)
        return shp_path

    url = GADM_DOWNLOAD_URLS[level]
    logger.info("Downloading GADM level %d from %s ...", level, url)
    resp = requests.get(url, timeout=300, stream=True)
    resp.raise_for_status()

    zip_bytes = io.BytesIO(resp.content)
    with zipfile.ZipFile(zip_bytes) as zf:
        zf.extractall(cache_dir)

    if not os.path.exists(shp_path):
        # Find whatever .shp was extracted
        shps = list(Path(cache_dir).glob("*.shp"))
        if shps:
            shp_path = str(shps[0])
        else:
            raise FileNotFoundError(f"No .shp found after extracting GADM ZIP from {url}")

    logger.info("GADM level %d extracted to %s", level, shp_path)
    return shp_path


async def ensure_layer(db: AsyncSession, config: dict[str, Any]) -> str:
    """Upsert the gis_layers row for this GADM level and return its UUID."""
    result = await db.execute(
        text("""
            INSERT INTO gis_layers (name, slug, category, ministry_owner, status)
            VALUES (:name, :slug, :category, 'Ministry of Home Affairs', 'published')
            ON CONFLICT (slug) DO UPDATE
                SET name = EXCLUDED.name,
                    status = 'published',
                    last_synced_at = NOW()
            RETURNING id
        """),
        {"name": config["name"], "slug": config["slug"], "category": config["category"]},
    )
    return str(result.scalar_one())


async def load_gadm_shapefile(
    db: AsyncSession,
    shp_path: str,
    level: int,
    batch_size: int = 200,
) -> int:
    """Load a GADM shapefile into layer_features. Returns inserted count."""
    config = GADM_LAYER_CONFIG[level]
    logger.info("Reading shapefile: %s", shp_path)

    gdf = gpd.read_file(shp_path)
    if gdf.crs and str(gdf.crs) != "EPSG:4326":
        gdf = gdf.to_crs("EPSG:4326")

    gdf = gdf[gdf.geometry.notnull() & ~gdf.geometry.is_empty].copy()
    logger.info("Loaded %d valid features from GADM level %d", len(gdf), level)

    layer_id = await ensure_layer(db, config)

    # Clear existing features for this layer before reload (full refresh)
    await db.execute(
        text("DELETE FROM layer_features WHERE layer_id = :lid"),
        {"lid": layer_id},
    )
    await db.commit()

    inserted = 0
    rows = list(gdf.iterrows())

    for batch_start in range(0, len(rows), batch_size):
        batch = rows[batch_start : batch_start + batch_size]
        values = []
        params: dict[str, Any] = {"layer_id": layer_id}

        for i, (_, row) in enumerate(batch):
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue

            props: dict[str, Any] = {
                "name": str(getattr(row, config["name_col"], "") or ""),
                "code": str(getattr(row, config["code_col"], "") or ""),
                "admin_level": level,
            }
            if "parent_col" in config:
                props["parent"] = str(getattr(row, config["parent_col"], "") or "")
            # Add ENGTYPE columns if present
            for col in ["ENGTYPE_1", "ENGTYPE_2", "TYPE_1", "TYPE_2", "VARNAME_1", "VARNAME_2"]:
                val = getattr(row, col, None)
                if val is not None and str(val) not in ("nan", "None", ""):
                    props[col.lower()] = str(val)

            geom_json = json.dumps(mapping(geom))
            params[f"geom_{i}"] = geom_json
            params[f"props_{i}"] = json.dumps(props)
            values.append(
                f"(:layer_id, ST_SetSRID(ST_GeomFromGeoJSON(:geom_{i}), 4326), :props_{i}::jsonb)"
            )

        if not values:
            continue

        await db.execute(
            text(f"INSERT INTO layer_features (layer_id, geom, properties) VALUES {', '.join(values)}"),
            params,
        )
        await db.commit()
        inserted += len(values)
        logger.info("  Inserted batch %d–%d (%d total)", batch_start, batch_start + len(batch), inserted)

    logger.info("GADM level %d done: %d features loaded", level, inserted)
    return inserted


async def run(level: int, shp_path: str | None, download: bool) -> None:
    """Orchestrate download (if needed) and load."""
    if shp_path is None or not os.path.exists(shp_path or ""):
        if download:
            shp_path = download_gadm(level)
        else:
            raise FileNotFoundError(
                f"Shapefile not found. Pass --shapefile or --download to auto-fetch."
            )

    async with AsyncSessionLocal() as db:
        await load_gadm_shapefile(db, shp_path, level)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s — %(message)s")
    parser = argparse.ArgumentParser(description="Load GADM administrative boundaries into GSIP")
    parser.add_argument("--level", type=int, choices=[1, 2, 3], default=2, help="GADM level (1=state, 2=district, 3=subdistrict)")
    parser.add_argument("--shapefile", default=None, help="Path to local .shp file")
    parser.add_argument("--download", action="store_true", help="Auto-download from GADM if shapefile not found")
    args = parser.parse_args()
    asyncio.run(run(args.level, args.shapefile, args.download))


if __name__ == "__main__":
    main()
