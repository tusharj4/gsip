"""Pydantic schemas for infrastructure project endpoints."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    """Payload for creating a new infrastructure project."""

    name: str = Field(..., max_length=500)
    ministry: str | None = None
    project_type: str | None = Field(
        None, pattern=r"^(road|railway|pipeline|power|telecom)$"
    )
    # GeoJSON LineString geometry dict
    corridor_geojson: dict[str, Any] | None = None
    buffer_m: int = Field(default=500, ge=50, le=50000)
    cost_crore: Decimal | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")

    model_config = ConfigDict(populate_by_name=True)


class ProjectUpdate(BaseModel):
    """Payload for partial project updates."""

    name: str | None = Field(None, max_length=500)
    ministry: str | None = None
    project_type: str | None = None
    corridor_geojson: dict[str, Any] | None = None
    buffer_m: int | None = Field(None, ge=50, le=50000)
    status: str | None = Field(
        None, pattern=r"^(draft|submitted|approved|active|completed)$"
    )
    cost_crore: Decimal | None = None
    metadata_: dict[str, Any] | None = Field(None, alias="metadata")

    model_config = ConfigDict(populate_by_name=True)


class ProjectRead(BaseModel):
    """Response schema for an infrastructure project."""

    id: uuid.UUID
    name: str
    ministry: str | None
    project_type: str | None
    status: str
    corridor_geojson: dict[str, Any] | None = None
    buffer_m: int
    cost_crore: Decimal | None
    metadata_: dict[str, Any] = Field(alias="metadata")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)
