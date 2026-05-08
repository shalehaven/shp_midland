"""End-to-end build pipeline: shapefiles → control points → 200x200 grids → HTML."""
from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

from .dem import build_dem_grid
from .shapefiles import FORMATIONS_ORDERED, ShapefileEntry, discover
from .surfaces import GRID_N, Surface, grid_surface

log = logging.getLogger(__name__)


# UTM zone 14N covers the whole Midland Basin (Texas, lon ~-102 to -100).
# Used as a metric CRS for arc-length sampling of contour polylines.
UTM_MIDLAND = "EPSG:32614"


# Keyword preferences for resolving the value column. Tried in order.
_STRUCTURE_KEYWORDS = ("elev", "subsea", "depth", "ztop", "top", "_z", "struct")
_ISOPACH_KEYWORDS   = ("thick", "iso", "isopach", "h_ft", "_h_")


def _resolve_value_column(gdf: gpd.GeoDataFrame, layer: str) -> str:
    """Pick the column that holds the contour value.

    Strategy:
      1. Try keyword-matched names (case-insensitive substring on column name).
      2. Failing that, pick the numeric column whose value distribution matches
         the layer signature (structure: median <= 0 or |median| > 1000;
         isopach: all-positive, median in 0..3000).
    """
    cols = [c for c in gdf.columns if c != "geometry"]
    keywords = _STRUCTURE_KEYWORDS if layer == "structure" else _ISOPACH_KEYWORDS

    # Pass 1: keyword match
    for kw in keywords:
        for c in cols:
            if kw in c.lower():
                if np.issubdtype(gdf[c].dtype, np.number):
                    return c

    # Pass 2: heuristic on numeric columns. Skip 'index'/'shape_leng' housekeeping.
    skip = {"index", "shape_leng", "shape_area", "fid", "objectid"}
    candidates: list[tuple[str, float]] = []
    for c in cols:
        if c.lower() in skip:
            continue
        if not np.issubdtype(gdf[c].dtype, np.number):
            continue
        s = gdf[c].dropna()
        if len(s) == 0:
            continue
        med = float(np.median(s))
        rng = float(s.max() - s.min())
        if layer == "structure":
            # subsea elevation: typically negative, |median| in thousands
            if abs(med) > 500 and rng > 100:
                candidates.append((c, abs(med)))
        else:  # isopach
            if (s >= 0).all() and 0 < med < 5000 and rng > 10:
                candidates.append((c, med))

    if candidates:
        # Pick column with the largest characteristic value -- empirically the
        # one carrying the contour magnitude rather than any auxiliary id field.
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    raise RuntimeError(
        f"Cannot resolve value column for layer={layer!r}; columns={cols}"
    )


def _sample_contours(
    gdf_4326: gpd.GeoDataFrame,
    value_col: str,
    spacing_m: float = 500.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Densify each contour polyline to (lon, lat, value) points.

    Reprojects to UTM 14N to compute arc length in meters, samples at
    `spacing_m` along each line, then back-projects sample coordinates to
    EPSG:4326. Both LineString and MultiLineString geometries are handled.
    """
    if len(gdf_4326) == 0:
        return np.empty(0), np.empty(0), np.empty(0)
    gdf_utm = gdf_4326.to_crs(UTM_MIDLAND)
    pts_xy: list[tuple[float, float]] = []
    pts_val: list[float] = []
    for geom, val in zip(gdf_utm.geometry, gdf_utm[value_col]):
        if geom is None or val is None:
            continue
        if not np.isfinite(val):
            continue
        if geom.is_empty:
            continue
        if geom.geom_type == "LineString":
            parts = [geom]
        elif geom.geom_type == "MultiLineString":
            parts = list(geom.geoms)
        else:
            continue
        for line in parts:
            L = line.length
            if L <= 0:
                continue
            n_steps = max(2, int(np.ceil(L / spacing_m)) + 1)
            for i in range(n_steps):
                d = min(i * spacing_m, L)
                p = line.interpolate(d)
                pts_xy.append((p.x, p.y))
                pts_val.append(float(val))

    if not pts_xy:
        return np.empty(0), np.empty(0), np.empty(0)

    series = gpd.GeoSeries([Point(x, y) for x, y in pts_xy], crs=UTM_MIDLAND).to_crs("EPSG:4326")
    lons = np.asarray(series.x.values, dtype=float)
    lats = np.asarray(series.y.values, dtype=float)
    vals = np.asarray(pts_val, dtype=float)
    return lons, lats, vals


def _to_positive_depth(values: np.ndarray, formation: str) -> np.ndarray:
    """Force structure values to positive 'depth below sea level' convention.

    EIA Midland shapefiles author surfaces as subsea elevation (negative ft).
    Operators usually prefer positive depths, so the pipeline negates values
    when the median is negative. Already-positive inputs are passed through
    unchanged. Output is positive: shallowest formations have the smallest
    values; deepest formations have the largest.
    """
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return values
    med = float(np.median(finite))
    if med < 0:
        log.info("flipping sign for %s structure (median=%.0f -> positive depth)", formation, med)
        return -values
    return values


def _grid_extent(all_lons: list[np.ndarray], all_lats: list[np.ndarray], pad_deg: float = 0.1) -> tuple[float, float, float, float]:
    """Union bbox of every input point set, padded by `pad_deg`."""
    lo = np.concatenate([a for a in all_lons if a.size])
    la = np.concatenate([a for a in all_lats if a.size])
    return (
        float(la.min()) - pad_deg, float(la.max()) + pad_deg,
        float(lo.min()) - pad_deg, float(lo.max()) + pad_deg,
    )


def build(
    *,
    wolfcamp_dir: Path,
    middle_dir: Path,
    lower_dir: Path,
    upper_dir: Path,
    out_html: str | Path,
) -> dict[tuple[str, str], Surface]:
    """End-to-end: discover → load → sample → grid → write HTML.

    Returns the dict of surfaces keyed by (formation, layer).
    """
    entries = discover(
        wolfcamp_dir=wolfcamp_dir,
        middle_dir=middle_dir,
        lower_dir=lower_dir,
        upper_dir=upper_dir,
    )

    # Phase A: load every shapefile, resolve column, sample contours
    samples: dict[tuple[str, str], tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for e in entries:
        log.info("loading %s %s : %s", e.formation, e.layer, e.path.name)
        gdf = gpd.read_file(e.path)
        if gdf.crs is None:
            raise RuntimeError(f"{e.path} has no CRS defined")
        gdf = gdf.to_crs("EPSG:4326")
        assert str(gdf.crs).upper() in ("EPSG:4326", "WGS 84"), f"reprojection failed: {gdf.crs}"
        # Drop empty/None geometries
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].reset_index(drop=True)
        col = _resolve_value_column(gdf, e.layer)
        lons, lats, vals = _sample_contours(gdf, col)
        if e.layer == "structure":
            vals = _to_positive_depth(vals, e.formation)
        log.info("  col=%s  n_pts=%d  range=[%.0f, %.0f]", col, len(vals),
                 float(np.nanmin(vals)) if vals.size else float("nan"),
                 float(np.nanmax(vals)) if vals.size else float("nan"))
        samples[(e.formation, e.layer)] = (lons, lats, vals)

    # Phase B: shared grid extent (union of all sampled points + 0.1° pad)
    lat_min, lat_max, lon_min, lon_max = _grid_extent(
        [v[0] for v in samples.values()],
        [v[1] for v in samples.values()],
    )
    log.info("shared grid: lat=[%.3f, %.3f], lon=[%.3f, %.3f], N=%d",
             lat_min, lat_max, lon_min, lon_max, GRID_N)

    lat_axis = np.linspace(lat_min, lat_max, GRID_N)
    lon_axis = np.linspace(lon_min, lon_max, GRID_N)

    # Phase C: grid each surface
    surfaces: dict[tuple[str, str], Surface] = {}
    for fm in FORMATIONS_ORDERED:
        for layer in ("structure", "isopach"):
            lons, lats, vals = samples[(fm, layer)]
            s = grid_surface(
                formation=fm, layer=layer,
                lons=lons, lats=lats, values=vals,
                lon_axis=lon_axis, lat_axis=lat_axis,
            )
            if s is None:
                raise RuntimeError(f"grid_surface returned None for {fm} {layer}")
            log.info("gridded %-18s %-9s n_ctrl=%5d  median=%9.1f  range=[%9.1f, %9.1f]",
                     fm, layer, s.n_control, s.val_median, s.val_min, s.val_max)
            surfaces[(fm, layer)] = s

    # Phase C2: convert structure surfaces from "depth below sea level" to
    # TVD from ground surface by adding the SRTM DEM elevation. Each cell:
    #     TVD = subsea_depth + ground_elevation_ft
    # NaN cells in either grid stay NaN. Isopach surfaces are unaffected.
    elev_ft = build_dem_grid(lat_axis, lon_axis)
    for fm in FORMATIONS_ORDERED:
        s = surfaces[(fm, "structure")]
        tvd = s.values + elev_ft
        finite = tvd[np.isfinite(tvd)]
        s.values = tvd
        if finite.size:
            s.val_min = float(finite.min())
            s.val_max = float(finite.max())
            s.val_median = float(np.median(finite))
        log.info("TVD-shifted %-18s median=%9.1f  range=[%9.1f, %9.1f]",
                 fm, s.val_median, s.val_min, s.val_max)

    # Phase D: render HTML (lazy import — avoids plotly overhead during data-only runs)
    from .viewer import build_html
    out_html = Path(out_html)
    log.info("rendering HTML to %s", out_html)
    build_html(surfaces, out_html, lat_axis=lat_axis, lon_axis=lon_axis)

    return surfaces
