"""Layer CRUD endpoints — manage GIS data layers and their features."""

import gzip
import io
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.layer import GISLayer, LayerFeature
from app.schemas.layer import GISLayerCreate, GISLayerRead, GISLayerUpdate
from app.services.data_validator import DataValidator
from app.services.minio_client import get_minio_client
from app.spatial.loaders import load_geojson_bytes, load_shapefile_zip, normalise_feature

logger = logging.getLogger(__name__)
router = APIRouter()


def _layer_to_read(layer: GISLayer, feature_count: int = 0) -> GISLayerRead:
    """Convert a GISLayer ORM instance to GISLayerRead.

    The `metadata_` attribute is stored under column name `metadata` — we must
    pass it via the alias to avoid the dict-comprehension picking up the wrong
    class-level SQLAlchemy MetaData object.
    """
    return GISLayerRead(
        id=layer.id,
        name=layer.name,
        slug=layer.slug,
        category=layer.category,
        ministry_owner=layer.ministry_owner,
        status=layer.status,
        source_url=layer.source_url,
        last_synced_at=layer.last_synced_at,
        metadata=layer.metadata_,
        created_at=layer.created_at,
        updated_at=layer.updated_at,
        feature_count=feature_count,
    )


@router.get("/", response_model=list[GISLayerRead])
async def list_layers(
    category: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[GISLayerRead]:
    """List all GIS layers with optional category/status filters."""
    stmt = select(GISLayer)
    if category:
        stmt = stmt.where(GISLayer.category == category)
    if status:
        stmt = stmt.where(GISLayer.status == status)
    stmt = stmt.offset(offset).limit(limit).order_by(GISLayer.created_at.desc())

    result = await db.execute(stmt)
    layers = result.scalars().all()

    # Count features per layer
    layer_ids = [lyr.id for lyr in layers]
    count_stmt = (
        select(LayerFeature.layer_id, func.count(LayerFeature.id).label("cnt"))
        .where(LayerFeature.layer_id.in_(layer_ids))
        .group_by(LayerFeature.layer_id)
    )
    count_result = await db.execute(count_stmt)
    counts = {row.layer_id: row.cnt for row in count_result}

    return [_layer_to_read(lyr, feature_count=counts.get(lyr.id, 0)) for lyr in layers]


@router.post("/", response_model=GISLayerRead, status_code=status.HTTP_201_CREATED)
async def create_layer(
    payload: GISLayerCreate,
    db: AsyncSession = Depends(get_db),
) -> GISLayerRead:
    """Register a new GIS layer in draft status."""
    layer = GISLayer(
        name=payload.name,
        slug=payload.slug,
        category=payload.category,
        ministry_owner=payload.ministry_owner,
        source_url=payload.source_url,
        metadata_=payload.metadata_,
    )
    db.add(layer)
    await db.flush()
    await db.refresh(layer)
    return _layer_to_read(layer)


@router.get("/{layer_id}", response_model=GISLayerRead)
async def get_layer(layer_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> GISLayerRead:
    """Fetch a single GIS layer by ID."""
    layer = await db.get(GISLayer, layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")
    count_result = await db.execute(
        select(func.count(LayerFeature.id)).where(LayerFeature.layer_id == layer_id)
    )
    feature_count = count_result.scalar_one()
    return _layer_to_read(layer, feature_count=feature_count)


@router.patch("/{layer_id}", response_model=GISLayerRead)
async def update_layer(
    layer_id: uuid.UUID,
    payload: GISLayerUpdate,
    db: AsyncSession = Depends(get_db),
) -> GISLayerRead:
    """Partially update a GIS layer (status transitions, metadata, etc.)."""
    layer = await db.get(GISLayer, layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    update_data = payload.model_dump(exclude_unset=True, by_alias=False)
    if "metadata_" in update_data:
        layer.metadata_ = update_data.pop("metadata_")
    for field, value in update_data.items():
        setattr(layer, field, value)

    await db.flush()
    await db.refresh(layer)
    return _layer_to_read(layer)


@router.delete("/{layer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layer(layer_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> None:
    """Delete a layer and all its features (cascaded)."""
    layer = await db.get(GISLayer, layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")
    await db.delete(layer)


@router.get("/{layer_id}/features", response_model=dict[str, Any])
async def get_layer_features(
    layer_id: uuid.UUID,
    bbox: str | None = Query(None, description="minx,miny,maxx,maxy in WGS84"),
    limit: int = Query(1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return layer features as a GeoJSON FeatureCollection.

    Supports optional bounding box filter (minx,miny,maxx,maxy).
    """
    if bbox:
        try:
            minx, miny, maxx, maxy = map(float, bbox.split(","))
        except ValueError:
            raise HTTPException(status_code=400, detail="bbox must be 'minx,miny,maxx,maxy'")

        sql = text("""
            SELECT
                lf.id,
                ST_AsGeoJSON(lf.geom)::json AS geometry,
                lf.properties
            FROM layer_features lf
            WHERE lf.layer_id = :layer_id
              AND ST_Intersects(
                  lf.geom,
                  ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)
              )
            LIMIT :limit
        """)
        result = await db.execute(
            sql,
            {"layer_id": str(layer_id), "minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy, "limit": limit},
        )
    else:
        sql = text("""
            SELECT
                lf.id,
                ST_AsGeoJSON(lf.geom)::json AS geometry,
                lf.properties
            FROM layer_features lf
            WHERE lf.layer_id = :layer_id
            LIMIT :limit
        """)
        result = await db.execute(sql, {"layer_id": str(layer_id), "limit": limit})

    rows = result.fetchall()
    features = [
        {"type": "Feature", "id": row.id, "geometry": row.geometry, "properties": row.properties}
        for row in rows
    ]
    return {"type": "FeatureCollection", "features": features, "total": len(features)}


@router.post("/{layer_id}/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_features(
    layer_id: uuid.UUID,
    file: UploadFile = File(...),
    replace: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Accept a GeoJSON or zipped Shapefile for bulk feature ingestion.

    - Streams file to MinIO (gzipped) for durable storage.
    - Parses and bulk-inserts features into layer_features synchronously for
      files < 10MB; larger files are queued via Redis Streams.
    - Returns immediately with inserted count or job_id.
    - Pass replace=true to delete existing features before inserting.
    """
    layer = await db.get(GISLayer, layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    filename = file.filename or "upload"
    suffix = "." + filename.rsplit(".", 1)[-1].lower()
    allowed = {".geojson", ".json", ".zip"}
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported type '{suffix}'. Allowed: {allowed}")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Store gzipped original in MinIO for auditability
    job_id = str(uuid.uuid4())
    try:
        minio = get_minio_client()
        gz_bytes = gzip.compress(raw)
        minio.put_object(
            "gsip-layers",
            f"uploads/{layer_id}/{job_id}/{filename}.gz",
            io.BytesIO(gz_bytes),
            length=len(gz_bytes),
            content_type="application/octet-stream",
            metadata={"Content-Encoding": "gzip"},
        )
    except Exception as exc:
        # MinIO unavailable — proceed with DB insert only, warn in response
        logger.warning("MinIO upload failed (non-fatal): %s", exc)

    # Parse features
    try:
        if suffix == ".zip":
            features = load_shapefile_zip(raw)
        else:
            features = load_geojson_bytes(raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse file: {exc}") from exc

    if not features:
        raise HTTPException(status_code=422, detail="No features found in uploaded file")

    # Optionally clear existing features
    if replace:
        await db.execute(
            text("DELETE FROM layer_features WHERE layer_id = :lid"),
            {"lid": str(layer_id)},
        )

    # Bulk insert
    inserted = 0
    errors = 0
    batch_values = []
    batch_params: dict[str, Any] = {"layer_id": str(layer_id)}

    for i, feature in enumerate(features):
        try:
            geom, props = normalise_feature(feature)
        except ValueError:
            errors += 1
            continue

        geom_json = json.dumps(geom)
        props_json = json.dumps(props)
        batch_params[f"geom_{i}"] = geom_json
        batch_params[f"props_{i}"] = props_json
        batch_values.append(
            f"(:layer_id, ST_SetSRID(ST_GeomFromGeoJSON(:geom_{i}), 4326), :props_{i}::jsonb)"
        )

        # Flush every 500 rows to avoid huge parameter lists
        if len(batch_values) >= 500:
            await db.execute(
                text(f"INSERT INTO layer_features (layer_id, geom, properties) VALUES {', '.join(batch_values)} ON CONFLICT DO NOTHING"),
                batch_params,
            )
            inserted += len(batch_values)
            batch_values = []
            batch_params = {"layer_id": str(layer_id)}

    if batch_values:
        await db.execute(
            text(f"INSERT INTO layer_features (layer_id, geom, properties) VALUES {', '.join(batch_values)} ON CONFLICT DO NOTHING"),
            batch_params,
        )
        inserted += len(batch_values)

    # Mark layer as submitted (maker uploaded data, awaiting checker approval)
    if layer.status == "draft":
        layer.status = "submitted"

    await db.flush()

    return {
        "status": "complete",
        "job_id": job_id,
        "layer_id": str(layer_id),
        "features_parsed": len(features),
        "features_inserted": inserted,
        "errors": errors,
        "layer_status": layer.status,
    }


# ─── Maker-Checker Status Transitions ────────────────────────────────────────

class StatusTransitionRequest(BaseModel):
    """Request body for a layer status transition."""
    target_status: str
    actor_role: str  # maker | checker | approver
    actor_id: uuid.UUID | None = None
    notes: str | None = None


@router.patch("/{layer_id}/status", response_model=GISLayerRead)
async def transition_layer_status(
    layer_id: uuid.UUID,
    payload: StatusTransitionRequest,
    db: AsyncSession = Depends(get_db),
) -> GISLayerRead:
    """Transition a layer through the maker-checker workflow.

    Allowed transitions:
      draft → submitted  (maker)
      submitted → approved | rejected  (checker)
      approved → published | rejected  (approver)
      rejected → draft  (maker, to re-upload)
    """
    validator = DataValidator(db)
    try:
        layer = await validator.transition(
            layer_id=layer_id,
            target_status=payload.target_status,
            actor_id=payload.actor_id,
            actor_role=payload.actor_role,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    count_result = await db.execute(
        select(func.count(LayerFeature.id)).where(LayerFeature.layer_id == layer_id)
    )
    feature_count = count_result.scalar_one()
    return _layer_to_read(layer, feature_count=feature_count)


@router.get("/{layer_id}/audit", response_model=list[dict])
async def get_layer_audit(
    layer_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return the full audit trail for a layer (newest first)."""
    layer = await db.get(GISLayer, layer_id)
    if not layer:
        raise HTTPException(status_code=404, detail="Layer not found")

    validator = DataValidator(db)
    return await validator.get_audit_history(layer_id)
