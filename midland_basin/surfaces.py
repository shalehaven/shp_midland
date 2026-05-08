"""Grid sampled contour points onto a shared lat/lon grid.

The EIA shapefiles encode each surface as labeled contour polylines. We
densify each polyline to scattered (lon, lat, value) control points
(`pipeline.sample_contours`) and then `grid_surface` linearly interpolates
those scattered points onto a regular 200x200 grid that is shared across
all 7 formations so the click-handler can index into every layer with
identical axes.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import griddata
from scipy.spatial import Delaunay


GRID_N = 200


@dataclass
class Surface:
    formation: str        # "Wolfcamp A"
    layer: str            # "structure" | "isopach"
    lats: np.ndarray      # shape (GRID_N,) — shared across all surfaces
    lons: np.ndarray      # shape (GRID_N,) — shared across all surfaces
    values: np.ndarray    # shape (GRID_N, GRID_N); NaN outside hull
    val_min: float
    val_max: float
    val_median: float
    n_control: int


def grid_surface(
    *,
    formation: str,
    layer: str,
    lons: np.ndarray,
    lats: np.ndarray,
    values: np.ndarray,
    lon_axis: np.ndarray,
    lat_axis: np.ndarray,
    rng_seed: int = 42,
    max_pts: int = 20000,
) -> Surface | None:
    if len(lons) < 4:
        return None

    # Drop duplicate (lon, lat) pairs that would confuse the triangulation
    pts = np.column_stack([lons, lats])
    _, idx = np.unique(pts, axis=0, return_index=True)
    idx = np.sort(idx)
    pts = pts[idx]
    vals = values[idx]
    if len(pts) < 4:
        return None

    if len(pts) > max_pts:
        rng = np.random.RandomState(rng_seed)
        sel = rng.choice(len(pts), max_pts, replace=False)
        pts = pts[sel]
        vals = vals[sel]

    LON, LAT = np.meshgrid(lon_axis, lat_axis)
    grid = griddata(pts, vals, (LON, LAT), method="linear")

    # Mask cells outside the convex hull of the input points
    tri = Delaunay(pts)
    flat = np.column_stack([LON.ravel(), LAT.ravel()])
    inside = tri.find_simplex(flat) >= 0
    g = grid.ravel()
    g[~inside] = np.nan
    grid = g.reshape(LAT.shape)

    finite = grid[np.isfinite(grid)]
    if finite.size == 0:
        return None

    return Surface(
        formation=formation,
        layer=layer,
        lats=lat_axis,
        lons=lon_axis,
        values=grid,
        val_min=float(finite.min()),
        val_max=float(finite.max()),
        val_median=float(np.median(finite)),
        n_control=int(len(pts)),
    )


def query_surface(s: Surface, lat: float, lon: float) -> float:
    """Bilinear interpolation at a single (lat, lon). NaN if out of grid/hull."""
    lats, lons = s.lats, s.lons
    if lat < lats[0] or lat > lats[-1] or lon < lons[0] or lon > lons[-1]:
        return float("nan")
    iy = max(0, min(np.searchsorted(lats, lat) - 1, len(lats) - 2))
    ix = max(0, min(np.searchsorted(lons, lon) - 1, len(lons) - 2))
    fy = (lat - lats[iy]) / (lats[iy + 1] - lats[iy])
    fx = (lon - lons[ix]) / (lons[ix + 1] - lons[ix])
    v00 = s.values[iy, ix]
    v01 = s.values[iy, ix + 1]
    v10 = s.values[iy + 1, ix]
    v11 = s.values[iy + 1, ix + 1]
    if any(not np.isfinite(v) for v in (v00, v01, v10, v11)):
        return float("nan")
    return float(
        (1 - fy) * ((1 - fx) * v00 + fx * v01)
        + fy * ((1 - fx) * v10 + fx * v11)
    )
