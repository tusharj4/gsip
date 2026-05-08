"""CRS transformation utilities — all data must be stored in EPSG:4326."""

import logging

from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

logger = logging.getLogger(__name__)

WGS84 = CRS("EPSG:4326")


def to_wgs84(geometry: BaseGeometry, source_crs: str | int) -> BaseGeometry:
    """Reproject a Shapely geometry from source_crs to EPSG:4326.

    Args:
        geometry: A Shapely geometry object in source_crs coordinates.
        source_crs: EPSG code (int or 'EPSG:XXXX' string) of the input geometry.

    Returns:
        The same geometry reprojected to WGS84.
    """
    src = CRS(source_crs) if isinstance(source_crs, str) else CRS.from_epsg(source_crs)
    if src == WGS84:
        return geometry

    transformer = Transformer.from_crs(src, WGS84, always_xy=True)
    return transform(transformer.transform, geometry)


def validate_wgs84_bounds(geometry: BaseGeometry) -> None:
    """Assert that a geometry falls within valid WGS84 bounds.

    Raises ValueError if coordinates are outside [-180,-90,180,90].
    """
    minx, miny, maxx, maxy = geometry.bounds
    if not (-180 <= minx <= 180 and -180 <= maxx <= 180):
        raise ValueError(f"Longitude out of WGS84 range: minx={minx}, maxx={maxx}")
    if not (-90 <= miny <= 90 and -90 <= maxy <= 90):
        raise ValueError(f"Latitude out of WGS84 range: miny={miny}, maxy={maxy}")
