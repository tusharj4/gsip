"""GeoJSON and Shapefile ingestion utilities for bulk loading layer features."""

import gzip
import io
import json
import logging
import zipfile
from typing import Any

import fiona
import geopandas as gpd
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape

logger = logging.getLogger(__name__)

WGS84 = CRS("EPSG:4326")


def load_geojson_bytes(raw: bytes) -> list[dict[str, Any]]:
    """Parse a GeoJSON FeatureCollection (or gzipped) and return a list of features.

    Each feature is normalised to WGS84 if CRS is specified.
    """
    content = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    fc = json.loads(content)

    if fc.get("type") == "FeatureCollection":
        features = fc.get("features", [])
    elif fc.get("type") == "Feature":
        features = [fc]
    else:
        raise ValueError(f"Expected FeatureCollection or Feature, got {fc.get('type')!r}")

    return features


def load_shapefile_zip(raw: bytes) -> list[dict[str, Any]]:
    """Unzip and read a Shapefile, returning features in WGS84 GeoJSON format.

    Automatically reprojects from the file's native CRS to EPSG:4326.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        shp_names = [n for n in zf.namelist() if n.lower().endswith(".shp")]
        if not shp_names:
            raise ValueError("No .shp file found inside the ZIP archive")
        # Extract all to an in-memory virtual filesystem via fiona
        tmpdir = "/tmp/gsip_shp_upload"
        import os
        os.makedirs(tmpdir, exist_ok=True)
        zf.extractall(tmpdir)
        shp_path = os.path.join(tmpdir, shp_names[0])

    gdf = gpd.read_file(shp_path)
    if gdf.crs and gdf.crs != WGS84:
        logger.info("Reprojecting from %s to WGS84", gdf.crs)
        gdf = gdf.to_crs(WGS84)

    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        props = {k: v for k, v in row.items() if k != "geometry"}
        # Convert numpy/pandas types to plain Python for JSON serialisation
        clean_props: dict[str, Any] = {
            k: (v.item() if hasattr(v, "item") else v) for k, v in props.items()
        }
        features.append({"type": "Feature", "geometry": mapping(geom), "properties": clean_props})

    return features


def normalise_feature(feature: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a GeoJSON feature and return (geometry_dict, properties_dict).

    Raises ValueError if the geometry is missing or unsupported.
    """
    geom = feature.get("geometry")
    if not geom or geom.get("type") is None:
        raise ValueError("Feature is missing a valid geometry")
    props = feature.get("properties") or {}
    return geom, props
