"""Infrastructure project management endpoints."""

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter()


def _row_to_read(project: Project, corridor_geojson: dict | None = None) -> ProjectRead:
    """Convert an ORM Project to its read schema."""
    return ProjectRead(
        id=project.id,
        name=project.name,
        ministry=project.ministry,
        project_type=project.project_type,
        status=project.status,
        corridor_geojson=corridor_geojson,
        buffer_m=project.buffer_m,
        cost_crore=project.cost_crore,
        metadata=project.metadata_,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


@router.get("/", response_model=list[ProjectRead])
async def list_projects(
    project_type: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectRead]:
    """List infrastructure projects with optional type/status filters."""
    stmt = select(Project)
    if project_type:
        stmt = stmt.where(Project.project_type == project_type)
    if status_filter:
        stmt = stmt.where(Project.status == status_filter)
    stmt = stmt.offset(offset).limit(limit).order_by(Project.created_at.desc())

    result = await db.execute(stmt)
    projects = result.scalars().all()

    # Fetch GeoJSON for corridors — use ORM in_() to avoid asyncpg array binding issues
    if projects:
        project_ids = [p.id for p in projects]
        geo_stmt = select(
            Project.id,
            func.ST_AsGeoJSON(Project.corridor_geom).label("geojson"),
        ).where(
            Project.id.in_(project_ids),
            Project.corridor_geom.is_not(None),
        )
        geo_result = await db.execute(geo_stmt)
        geojson_map = {
            str(row.id): json.loads(row.geojson)
            for row in geo_result
            if row.geojson
        }
    else:
        geojson_map = {}

    return [_row_to_read(p, geojson_map.get(str(p.id))) for p in projects]


@router.post("/", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    """Create a new infrastructure project."""
    project = Project(
        name=payload.name,
        ministry=payload.ministry,
        project_type=payload.project_type,
        buffer_m=payload.buffer_m,
        cost_crore=payload.cost_crore,
        metadata_=payload.metadata_,
    )

    if payload.corridor_geojson:
        import json
        geojson_str = json.dumps(payload.corridor_geojson)
        set_geom = text(
            "UPDATE projects SET corridor_geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) WHERE id = :id"
        )
        db.add(project)
        await db.flush()
        await db.execute(set_geom, {"g": geojson_str, "id": str(project.id)})
    else:
        db.add(project)
        await db.flush()

    await db.refresh(project)
    corridor_geojson = payload.corridor_geojson
    return _row_to_read(project, corridor_geojson)


@router.get("/{project_id}", response_model=ProjectRead)
async def get_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ProjectRead:
    """Fetch a single project by ID including its corridor geometry."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    geojson_sql = text("""
        SELECT ST_AsGeoJSON(corridor_geom)::json AS geojson
        FROM projects WHERE id = :id AND corridor_geom IS NOT NULL
    """)
    geo_result = await db.execute(geojson_sql, {"id": str(project_id)})
    row = geo_result.fetchone()
    return _row_to_read(project, row.geojson if row else None)


@router.patch("/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
) -> ProjectRead:
    """Partially update a project (status, corridor, metadata, etc.)."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    update_data = payload.model_dump(exclude_unset=True, by_alias=False)
    corridor_geojson = update_data.pop("corridor_geojson", None)
    if "metadata_" in update_data:
        project.metadata_ = update_data.pop("metadata_")

    for field, value in update_data.items():
        setattr(project, field, value)

    if corridor_geojson:
        import json
        set_geom = text(
            "UPDATE projects SET corridor_geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326) WHERE id = :id"
        )
        await db.execute(set_geom, {"g": json.dumps(corridor_geojson), "id": str(project_id)})

    await db.flush()
    await db.refresh(project)
    return _row_to_read(project, corridor_geojson)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a project and all its conflict reports (cascaded)."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)
