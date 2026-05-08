"""ORM model for infrastructure projects."""

import uuid
from datetime import datetime
from decimal import Decimal

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Project(Base):
    """A proposed or active infrastructure project with a corridor alignment."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    ministry: Mapped[str | None] = mapped_column(String(255))
    # road | railway | pipeline | power | telecom
    project_type: Mapped[str | None] = mapped_column(String(100))
    # draft | submitted | approved | active | completed
    status: Mapped[str] = mapped_column(String(50), default="draft", nullable=False)
    # Proposed corridor as LineString in WGS84
    corridor_geom: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False)
    )
    # Analysis buffer radius in meters
    buffer_m: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    cost_crore: Mapped[Decimal | None] = mapped_column(Numeric(15, 2))
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

    conflicts: Mapped[list["ConflictReport"]] = relationship(  # type: ignore[name-defined]
        "ConflictReport", back_populates="project", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_projects_corridor", "corridor_geom", postgresql_using="gist"),
    )
