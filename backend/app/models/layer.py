"""ORM models for GIS layer registry and spatial features."""

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class GISLayer(Base):
    """Registry of all GIS data layers available on the platform."""

    __tablename__ = "gis_layers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # infrastructure | regulatory | socioeconomic | natural
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    ministry_owner: Mapped[str | None] = mapped_column(String(255))
    # draft → submitted → approved → published
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    features: Mapped[list["LayerFeature"]] = relationship(
        "LayerFeature", back_populates="layer", cascade="all, delete-orphan"
    )


class LayerFeature(Base):
    """Individual spatial features belonging to a GIS layer."""

    __tablename__ = "layer_features"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    layer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gis_layers.id", ondelete="CASCADE"), nullable=False
    )
    # geometry(Geometry, 4326) — all data stored in WGS84.
    # spatial_index=False: we define the GIST index explicitly in __table_args__
    # to avoid GeoAlchemy2 creating a duplicate with the same name.
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False), nullable=False
    )
    properties: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    layer: Mapped["GISLayer"] = relationship("GISLayer", back_populates="features")

    __table_args__ = (
        Index("idx_layer_features_geom", "geom", postgresql_using="gist"),
        Index("idx_layer_features_layer_id", "layer_id"),
    )
