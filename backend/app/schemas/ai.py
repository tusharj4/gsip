"""Pydantic schemas for the AI natural language query endpoint."""

from typing import Any

from pydantic import BaseModel, Field


class NLQueryRequest(BaseModel):
    """Natural language question to translate to PostGIS SQL and execute."""

    question: str = Field(..., min_length=5, max_length=1000)
    # Optional: restrict query to specific layers or geography
    context: dict[str, Any] | None = None


class NLQueryResponse(BaseModel):
    """Response containing the generated SQL and its results as GeoJSON."""

    question: str
    sql: str
    result_type: str  # "geojson" | "table" | "scalar"
    # GeoJSON FeatureCollection when spatial results are returned
    geojson: dict[str, Any] | None = None
    # Tabular results for non-spatial queries
    rows: list[dict[str, Any]] | None = None
    scalar: Any | None = None
    row_count: int = 0
    execution_ms: float = 0.0
