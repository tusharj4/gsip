"""Pydantic schemas for conflict detection and gap analysis endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConflictDetectRequest(BaseModel):
    """Request body for running conflict detection on a corridor."""

    project_id: uuid.UUID
    buffer_m: int = Field(default=500, ge=50, le=50000)
    # Optional list of layer slugs to check; defaults to all published regulatory/environmental
    layer_slugs: list[str] | None = None


class ConflictReportRead(BaseModel):
    """Response schema for a single conflict record."""

    id: uuid.UUID
    project_id: uuid.UUID
    layer_id: uuid.UUID | None
    conflict_geojson: dict[str, Any] | None = None
    conflict_type: str | None
    severity: str | None
    area_sqm: float | None
    description: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GapAnalysisRequest(BaseModel):
    """Request body for running a service gap analysis."""

    # GeoJSON Polygon defining the study area
    geography_geojson: dict[str, Any]
    analysis_type: str = Field(..., pattern=r"^(hospital|school|anganwadi|water)$")
    population: int | None = Field(None, ge=0)
    # Override default service radius (metres)
    service_radius_m: int | None = Field(None, ge=100, le=100000)


class GapAnalysisRead(BaseModel):
    """Response schema for a completed gap analysis."""

    id: uuid.UUID
    analysis_type: str | None
    geography_geojson: dict[str, Any] | None = None
    population: int | None
    required_count: int | None
    existing_count: int | None
    gap_count: int | None
    uncovered_geojson: dict[str, Any] | None = None
    candidate_sites: dict[str, Any] | None
    parameters: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BufferQueryRequest(BaseModel):
    """Request body for a generic buffer intersection query."""

    # GeoJSON geometry (any type) to buffer
    geometry_geojson: dict[str, Any]
    buffer_m: int = Field(default=1000, ge=0, le=200000)
    # Layer categories to intersect against
    categories: list[str] = Field(
        default=["infrastructure", "regulatory", "socioeconomic", "natural"]
    )
    limit: int = Field(default=500, ge=1, le=5000)


class BufferQueryResponse(BaseModel):
    """GeoJSON FeatureCollection of features within the buffer."""

    type: str = "FeatureCollection"
    features: list[dict[str, Any]]
    total: int
    buffer_m: int
