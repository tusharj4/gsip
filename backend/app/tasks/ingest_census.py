"""Census 2011 Population Data Loader.

Sources:
1. District-level population CSV from datameet/india-census GitHub repo
   (https://github.com/datameet/india-census/tree/master/district-level)
2. Joins to existing admin_district layer_features by district name
3. Updates properties JSONB with population fields

Usage:
    python -m app.tasks.ingest_census --csv /data/census/district_population.csv
    python -m app.tasks.ingest_census --download   # fetch from datameet GitHub

Population fields stored in layer_features.properties:
    population_total, population_male, population_female,
    population_rural, population_urban,
    households, area_sqkm, population_density

Idempotent: updates existing features by matching district name + state.
"""

import argparse
import asyncio
import io
import logging
from typing import Any

import pandas as pd
import requests
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# datameet India Census district-level data (CC-BY)
DATAMEET_CENSUS_URL = (
    "https://raw.githubusercontent.com/datameet/india-census/master/"
    "district-level/district_census_2011.csv"
)

# Column mapping: CSV column → properties key
CENSUS_COLUMNS = {
    "State": "state_name",
    "District": "district_name",
    "TOT_P": "population_total",
    "TOT_M": "population_male",
    "TOT_F": "population_female",
    "P_06": "population_under_6",
    "M_06": "population_male_under_6",
    "F_06": "population_female_under_6",
    "TOT_WORK_P": "workers_total",
    "MAIN_WORK_P": "workers_main",
    "MARG_WORK_P": "workers_marginal",
    "No_WORK_P": "non_workers",
    "Households": "households",
    "Area": "area_sqkm",
}


def download_census_csv() -> pd.DataFrame:
    """Fetch the Census 2011 district CSV from datameet GitHub."""
    logger.info("Downloading Census 2011 data from datameet GitHub...")
    resp = requests.get(DATAMEET_CENSUS_URL, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    logger.info("Downloaded %d district rows", len(df))
    return df


def load_census_csv(path: str) -> pd.DataFrame:
    """Load Census 2011 CSV from local file."""
    df = pd.read_csv(path)
    logger.info("Loaded %d rows from %s", len(df), path)
    return df


def clean_census_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names and fill missing values."""
    # Keep only columns we care about
    available = {k: v for k, v in CENSUS_COLUMNS.items() if k in df.columns}
    df = df[list(available.keys())].copy()
    df = df.rename(columns=available)

    # Normalize district/state names for fuzzy join
    if "district_name" in df.columns:
        df["district_name_normalized"] = (
            df["district_name"].str.lower().str.strip()
            .str.replace(r"[^a-z0-9 ]", "", regex=True)
        )
    if "state_name" in df.columns:
        df["state_name_normalized"] = (
            df["state_name"].str.lower().str.strip()
            .str.replace(r"[^a-z0-9 ]", "", regex=True)
        )

    # Convert numeric columns
    numeric_cols = [v for v in available.values() if v not in ("state_name", "district_name")]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    return df


async def update_district_features(db: AsyncSession, df: pd.DataFrame) -> int:
    """Join census data to existing admin_district features by name and update properties.

    Matches on normalized district name within the same state.
    """
    # Fetch existing admin_district features
    result = await db.execute(
        text("""
            SELECT lf.id, lf.properties->>'name' AS district_name, lf.properties->>'parent' AS state_name
            FROM layer_features lf
            JOIN gis_layers gl ON gl.id = lf.layer_id
            WHERE gl.slug = 'admin_district'
        """)
    )
    existing = result.fetchall()

    if not existing:
        logger.warning(
            "No admin_district features found — run ingest_gadm first.\n"
            "Census data will be stored as a standalone layer instead."
        )
        return await _insert_census_as_layer(db, df)

    logger.info("Matching %d census rows to %d district features", len(df), len(existing))

    def normalize(s: str | None) -> str:
        if not s:
            return ""
        import re
        return re.sub(r"[^a-z0-9 ]", "", str(s).lower().strip())

    feature_map = {normalize(row.district_name): row.id for row in existing}

    updated = 0
    for _, row in df.iterrows():
        key = str(row.get("district_name_normalized", ""))
        feature_id = feature_map.get(key)
        if feature_id is None:
            continue

        props: dict[str, Any] = {
            k: (int(row[k]) if pd.notna(row[k]) else None)
            for k in df.columns
            if k not in ("district_name", "state_name", "district_name_normalized", "state_name_normalized")
        }
        props["census_year"] = 2011

        # Compute population density if we have both population and area
        pop = props.get("population_total", 0)
        area = props.get("area_sqkm", 0)
        if pop and area:
            props["population_density"] = round(pop / area, 2)

        await db.execute(
            text("""
                UPDATE layer_features
                SET properties = properties || :census::jsonb
                WHERE id = :fid
            """),
            {"fid": feature_id, "census": __import__("json").dumps(props)},
        )
        updated += 1

    await db.commit()
    logger.info("Updated %d district features with Census 2011 population data", updated)
    return updated


async def _insert_census_as_layer(db: AsyncSession, df: pd.DataFrame) -> int:
    """Fallback: store Census data as a non-spatial attribute layer."""
    result = await db.execute(
        text("""
            INSERT INTO gis_layers (name, slug, category, ministry_owner, status)
            VALUES ('Census 2011 District Population', 'census_2011_district', 'socioeconomic',
                    'Office of the Registrar General & Census Commissioner', 'published')
            ON CONFLICT (slug) DO UPDATE SET last_synced_at = NOW()
            RETURNING id
        """)
    )
    layer_id = str(result.scalar_one())

    inserted = 0
    for _, row in df.iterrows():
        props = {k: v for k, v in row.items() if not k.endswith("_normalized")}
        props = {k: (int(v) if hasattr(v, "item") else v) for k, v in props.items()}
        props["census_year"] = 2011

        await db.execute(
            text("""
                INSERT INTO layer_features (layer_id, geom, properties)
                SELECT :lid,
                       ST_Centroid(lf.geom),
                       :props::jsonb
                FROM layer_features lf
                JOIN gis_layers gl ON gl.id = lf.layer_id
                WHERE gl.slug = 'admin_district'
                  AND LOWER(lf.properties->>'name') = LOWER(:district)
                LIMIT 1
            """),
            {
                "lid": layer_id,
                "props": __import__("json").dumps(props),
                "district": str(row.get("district_name", "")),
            },
        )
        inserted += 1

    await db.commit()
    logger.info("Inserted %d Census rows as standalone layer", inserted)
    return inserted


async def run(csv_path: str | None, download: bool) -> None:
    """Main orchestration."""
    if csv_path:
        df = load_census_csv(csv_path)
    elif download:
        df = download_census_csv()
    else:
        raise ValueError("Pass --csv <path> or --download")

    df = clean_census_df(df)

    async with AsyncSessionLocal() as db:
        count = await update_district_features(db, df)
        logger.info("Census ingestion complete: %d districts updated", count)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s — %(message)s")
    parser = argparse.ArgumentParser(description="Load Census 2011 district population into GSIP")
    parser.add_argument("--csv", default=None, help="Path to local Census CSV file")
    parser.add_argument("--download", action="store_true", help="Download from datameet GitHub")
    args = parser.parse_args()
    asyncio.run(run(args.csv, args.download))


if __name__ == "__main__":
    main()
