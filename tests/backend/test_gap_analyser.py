"""Tests for the GapAnalyser service."""

import json
import pytest
from sqlalchemy.ext.asyncio import AsyncSession


# Surendranagar district approximate bounding polygon (Gujarat, India)
SURENDRANAGAR_BBOX = {
    "type": "Polygon",
    "coordinates": [[[71.2, 22.5], [72.5, 22.5], [72.5, 23.5], [71.2, 23.5], [71.2, 22.5]]],
}


@pytest.mark.asyncio
async def test_gap_analyser_anganwadi_no_existing(db: AsyncSession) -> None:
    """With 0 existing anganwadis and 459,200 population, gap should be 574."""
    from app.services.gap_analyser import GapAnalyser

    # 459,200 / 800 = 574 exactly
    analyser = GapAnalyser(db)
    result = await analyser.analyse(
        geography_geojson=SURENDRANAGAR_BBOX,
        analysis_type="anganwadi",
        population=459_200,
    )

    assert result.required_count == 574
    assert result.existing_count == 0
    assert result.gap_count == 574


@pytest.mark.asyncio
async def test_gap_analyser_hospital_calculates_correctly(db: AsyncSession) -> None:
    """With 100,000 population, hospital gap should be 2 (50k per unit)."""
    from app.services.gap_analyser import GapAnalyser

    analyser = GapAnalyser(db)
    result = await analyser.analyse(
        geography_geojson=SURENDRANAGAR_BBOX,
        analysis_type="hospital",
        population=100_000,
    )

    assert result.required_count == 2
    assert result.gap_count == 2


@pytest.mark.asyncio
async def test_gap_analyser_school_age_cohort(db: AsyncSession) -> None:
    """School analysis uses 20% age cohort: 10,000 pop → 1000 school-age → 1 school needed."""
    from app.services.gap_analyser import GapAnalyser

    analyser = GapAnalyser(db)
    result = await analyser.analyse(
        geography_geojson=SURENDRANAGAR_BBOX,
        analysis_type="school",
        population=10_000,
    )

    # 10,000 * 0.20 = 2,000 / 1,000 per school = 2 schools
    assert result.required_count == 2
    assert result.gap_count == 2


@pytest.mark.asyncio
async def test_gap_analyser_persists_result(db: AsyncSession) -> None:
    """GapAnalyser should persist the result to gap_analyses table."""
    from app.services.gap_analyser import GapAnalyser
    from sqlalchemy import text

    analyser = GapAnalyser(db)
    result = await analyser.analyse(
        geography_geojson=SURENDRANAGAR_BBOX,
        analysis_type="water",
        population=5_000,
    )

    row = await db.execute(
        text("SELECT gap_count FROM gap_analyses WHERE id = :id"),
        {"id": str(result.id)},
    )
    db_row = row.fetchone()
    assert db_row is not None
    assert db_row.gap_count == result.gap_count
