"""ORM models for conflict detection and gap analysis results."""

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ConflictReport(Base):
    """Records a single spatial conflict between a project corridor and a GIS layer."""

    __tablename__ = "conflict_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    layer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gis_layers.id")
    )
    conflict_geom: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False)
    )
    # forest | crz | wildlife | water_body | settlement
    conflict_type: Mapped[str | None] = mapped_column(String(100))
    # blocker | high | medium | low
    severity: Mapped[str | None] = mapped_column(String(20))
    area_sqm: Mapped[float | None] = mapped_column(Numeric(20, 4))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship("Project", back_populates="conflicts")  # type: ignore[name-defined]

    __table_args__ = (
        Index("idx_conflicts_project", "project_id"),
        Index("idx_conflicts_geom", "conflict_geom", postgresql_using="gist"),
    )


class GapAnalysis(Base):
    """Records a service gap analysis for a geographic area."""

    __tablename__ = "gap_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # hospital | school | anganwadi | water
    analysis_type: Mapped[str | None] = mapped_column(String(100))
    geography: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POLYGON", srid=4326, spatial_index=False)
    )
    population: Mapped[int | None] = mapped_column(Integer)
    required_count: Mapped[int | None] = mapped_column(Integer)
    existing_count: Mapped[int | None] = mapped_column(Integer)
    gap_count: Mapped[int | None] = mapped_column(Integer)
    uncovered_geom: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False)
    )
    # Array of viable land parcel GeoJSON features
    candidate_sites: Mapped[dict | None] = mapped_column(JSONB)
    # Threshold, buffer radius, criteria used for this run
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_gaps_geography", "geography", postgresql_using="gist"),
    )
