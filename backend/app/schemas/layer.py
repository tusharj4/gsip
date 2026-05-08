"""Pydantic schemas for GIS layer and feature endpoints."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GISLayerCreate(BaseModel):
    """Payload for creating a new GIS layer."""

    name: str = Field(..., max_length=255)
    slug: str = Field(..., max_length=255, pattern=r"^[a-z0-9_-]+$")
    category: str = Field(..., pattern=r"^(infrastructure|regulatory|socioeconomic|natural)$")
    ministry_owner: str | None = None
    source_url: str | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")

    model_config = ConfigDict(populate_by_name=True)


class GISLayerUpdate(BaseModel):
    """Payload for updating an existing GIS layer (all fields optional)."""

    name: str | None = Field(None, max_length=255)
    category: str | None = None
    ministry_owner: str | None = None
    source_url: str | None = None
    status: str | None = Field(None, pattern=r"^(draft|submitted|approved|published)$")
    metadata_: dict[str, Any] | None = Field(None, alias="metadata")

    model_config = ConfigDict(populate_by_name=True)


class GISLayerRead(BaseModel):
    """Response schema for a GIS layer."""

    id: uuid.UUID
    name: str
    slug: str
    category: str
    ministry_owner: str | None
    status: str
    source_url: str | None
    last_synced_at: datetime | None
    metadata_: dict[str, Any] = Field(alias="metadata")
    created_at: datetime
    updated_at: datetime
    feature_count: int = 0

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LayerFeatureRead(BaseModel):
    """GeoJSON-like representation of a single layer feature."""

    id: int
    layer_id: uuid.UUID
    # geom returned as GeoJSON geometry dict
    geometry: dict[str, Any]
    properties: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
