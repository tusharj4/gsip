"""Seed script — populate the database with sample layers and a demo project.

Run via: make seed (docker compose run --rm backend python -m app.tasks.seed_data)
Idempotent: uses ON CONFLICT DO NOTHING so re-running is safe.
"""

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

SAMPLE_LAYERS = [
    {
        "name": "National Highways",
        "slug": "road_nh",
        "category": "infrastructure",
        "ministry_owner": "Ministry of Road Transport and Highways",
    },
    {
        "name": "Indian Railways Network",
        "slug": "railway",
        "category": "infrastructure",
        "ministry_owner": "Ministry of Railways",
    },
    {
        "name": "Protected Forest Areas",
        "slug": "protected_forest",
        "category": "regulatory",
        "ministry_owner": "Ministry of Environment, Forest and Climate Change",
    },
    {
        "name": "Wildlife Sanctuaries",
        "slug": "wildlife_sanctuary",
        "category": "regulatory",
        "ministry_owner": "Ministry of Environment, Forest and Climate Change",
    },
    {
        "name": "Coastal Regulation Zone",
        "slug": "crz",
        "category": "regulatory",
        "ministry_owner": "Ministry of Environment, Forest and Climate Change",
    },
    {
        "name": "Hospitals and Health Centres",
        "slug": "hospital",
        "category": "socioeconomic",
        "ministry_owner": "Ministry of Health and Family Welfare",
    },
    {
        "name": "Anganwadi Centres",
        "slug": "anganwadi",
        "category": "socioeconomic",
        "ministry_owner": "Ministry of Women and Child Development",
    },
    {
        "name": "Primary and Secondary Schools",
        "slug": "school",
        "category": "socioeconomic",
        "ministry_owner": "Ministry of Education",
    },
    {
        "name": "Rivers and Water Bodies",
        "slug": "water_body",
        "category": "natural",
        "ministry_owner": "Ministry of Jal Shakti",
    },
    {
        "name": "District Boundaries (India)",
        "slug": "admin_district",
        "category": "socioeconomic",
        "ministry_owner": "Ministry of Home Affairs",
    },
]

DEMO_PROJECT = {
    "name": "NH-48 Widening — Mumbai to Pune",
    "ministry": "Ministry of Road Transport and Highways",
    "project_type": "road",
    "buffer_m": 500,
}


async def seed(db: AsyncSession) -> None:
    """Insert sample layers and a demo project."""
    logger.info("Seeding sample GIS layers...")
    for layer in SAMPLE_LAYERS:
        await db.execute(
            text("""
                INSERT INTO gis_layers (name, slug, category, ministry_owner, status)
                VALUES (:name, :slug, :category, :ministry_owner, 'published')
                ON CONFLICT (slug) DO NOTHING
            """),
            layer,
        )

    logger.info("Seeding demo project...")
    await db.execute(
        text("""
            INSERT INTO projects (name, ministry, project_type, buffer_m, status)
            VALUES (:name, :ministry, :project_type, :buffer_m, 'draft')
            ON CONFLICT DO NOTHING
        """),
        DEMO_PROJECT,
    )

    await db.commit()
    logger.info("Seed complete: %d layers inserted/skipped, 1 demo project", len(SAMPLE_LAYERS))


async def main() -> None:
    """Entry point for seed script."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    async with AsyncSessionLocal() as db:
        await seed(db)


if __name__ == "__main__":
    asyncio.run(main())
