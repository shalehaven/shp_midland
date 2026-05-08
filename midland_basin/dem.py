"""Surface elevation DEM (SRTM 1 arc-sec) for TVD conversion.

The EIA structure shapefiles publish formation tops as subsea elevation
(positive ft below sea level after `pipeline._to_positive_depth`). Adding
the ground-surface elevation gives TVD from surface — what an operator
sees on a directional plan.

This module downloads SRTM 1 arc-second .hgt tiles from the public
Mapzen/AWS mirror, decompresses them in-memory, and bilinearly samples
them onto the viewer's 200x200 lat/lon grid. The resulting elevation
grid (in feet) is cached at `data/midland_dem.npz` so the network fetch
runs once.

No GDAL / rasterio required — HGT is just a 3601×3601 int16 big-endian
raster of meters AMSL with no header.
"""
from __future__ import annotations

import gzip
import logging
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

CACHE_NPZ = Path("data") / "midland_dem.npz"
SRTM_URL_FMT = (
    "https://elevation-tiles-prod.s3.amazonaws.com/skadi/"
    "{ns}{lat:02d}/{ns}{lat:02d}{ew}{lon:03d}.hgt.gz"
)
HGT_DIM = 3601           # 1 arc-sec resolution: 3601x3601 cells per 1°×1° tile
HGT_NODATA = -32768
M_TO_FT = 3.28084


def _tile_url(lat_sw: int, lon_sw: int) -> str:
    ns = "N" if lat_sw >= 0 else "S"
    ew = "E" if lon_sw >= 0 else "W"
    return SRTM_URL_FMT.format(ns=ns, lat=abs(lat_sw), ew=ew, lon=abs(lon_sw))


def _tile_indices(lat_min: float, lat_max: float,
                  lon_min: float, lon_max: float):
    """Yield SW-corner integer (lat, lon) for every 1°×1° tile that
    overlaps the bbox."""
    lat_lo = int(np.floor(lat_min))
    lat_hi = int(np.floor(lat_max))
    lon_lo = int(np.floor(lon_min))
    lon_hi = int(np.floor(lon_max))
    for la in range(lat_lo, lat_hi + 1):
        for lo in range(lon_lo, lon_hi + 1):
            yield la, lo


def _read_tile(lat_sw: int, lon_sw: int) -> np.ndarray | None:
    """Fetch and decompress one tile. Returns 3601x3601 int32 array of
    meters AMSL (NaN-safe int dtype kept by promoting to int32, with
    -32768 left in place for the no-data marker). None on 404."""
    url = _tile_url(lat_sw, lon_sw)
    log.info("fetching SRTM tile %s", url)
    try:
        with urllib.request.urlopen(url, timeout=180) as r:
            compressed = r.read()
    except urllib.error.HTTPError as e:
        log.warning("tile %s missing (%s); leaving as no-data", url, e)
        return None
    raw = gzip.decompress(compressed)
    if len(raw) != HGT_DIM * HGT_DIM * 2:
        log.warning("tile %s wrong size (%d bytes); skipping", url, len(raw))
        return None
    return np.frombuffer(raw, dtype=">i2").reshape(HGT_DIM, HGT_DIM).astype(np.int32)


def _sample_tile(tile: np.ndarray,
                 lat_query: np.ndarray, lon_query: np.ndarray,
                 tile_lat_sw: int, tile_lon_sw: int) -> np.ndarray:
    """Bilinear sample a 1°×1° tile.

    Convention: tile row 0 is the northernmost row (lat = lat_sw + 1),
    row HGT_DIM-1 is the southernmost (lat = lat_sw); col 0 is the
    westernmost (lon = lon_sw), col HGT_DIM-1 is the easternmost
    (lon = lon_sw + 1).

    Out-of-tile and no-data samples come back as NaN.
    """
    fx = (lon_query - tile_lon_sw) * (HGT_DIM - 1)
    fy = ((tile_lat_sw + 1) - lat_query) * (HGT_DIM - 1)
    out = np.full(lat_query.shape, np.nan, dtype=np.float64)
    in_tile = (fx >= 0) & (fx <= HGT_DIM - 1) & (fy >= 0) & (fy <= HGT_DIM - 1)
    if not in_tile.any():
        return out
    fx_in = fx[in_tile]
    fy_in = fy[in_tile]
    ix = np.clip(np.floor(fx_in).astype(int), 0, HGT_DIM - 2)
    iy = np.clip(np.floor(fy_in).astype(int), 0, HGT_DIM - 2)
    tx = fx_in - ix
    ty = fy_in - iy
    v00 = tile[iy,     ix    ]
    v01 = tile[iy,     ix + 1]
    v10 = tile[iy + 1, ix    ]
    v11 = tile[iy + 1, ix + 1]
    no_data = ((v00 == HGT_NODATA) | (v01 == HGT_NODATA) |
               (v10 == HGT_NODATA) | (v11 == HGT_NODATA))
    samp = ((1 - ty) * ((1 - tx) * v00 + tx * v01) +
            ty       * ((1 - tx) * v10 + tx * v11)).astype(np.float64)
    samp[no_data] = np.nan
    out[in_tile] = samp
    return out


def build_dem_grid(lat_axis: np.ndarray, lon_axis: np.ndarray,
                   force_refresh: bool = False) -> np.ndarray:
    """Return surface elevation in FEET on the (lat_axis × lon_axis) grid.

    Cached to `data/midland_dem.npz`; cache is invalidated automatically
    if the requested grid axes don't match the saved ones.
    """
    if CACHE_NPZ.exists() and not force_refresh:
        try:
            with np.load(CACHE_NPZ) as z:
                if (z["lats"].shape == lat_axis.shape and
                    z["lons"].shape == lon_axis.shape and
                    np.allclose(z["lats"], lat_axis) and
                    np.allclose(z["lons"], lon_axis)):
                    log.info("DEM cache hit: %s", CACHE_NPZ)
                    return z["elev_ft"].copy()
        except Exception as e:
            log.warning("DEM cache invalid (%s); refetching", e)

    log.info("building DEM grid from SRTM tiles ...")
    LON, LAT = np.meshgrid(lon_axis, lat_axis)
    elev_m = np.full(LAT.shape, np.nan)
    tiles = list(_tile_indices(lat_axis.min(), lat_axis.max(),
                                 lon_axis.min(), lon_axis.max()))
    for la, lo in tiles:
        tile = _read_tile(la, lo)
        if tile is None:
            continue
        samp = _sample_tile(tile, LAT.ravel(), LON.ravel(), la, lo)
        samp = samp.reshape(LAT.shape)
        # Fill any cell that doesn't have an elevation yet
        mask = ~np.isnan(samp) & np.isnan(elev_m)
        elev_m[mask] = samp[mask]
    elev_ft = elev_m * M_TO_FT
    coverage = 100.0 * np.isfinite(elev_ft).mean()
    log.info("DEM coverage = %.1f%%, range = %.0f..%.0f ft",
             coverage,
             float(np.nanmin(elev_ft)) if coverage > 0 else float("nan"),
             float(np.nanmax(elev_ft)) if coverage > 0 else float("nan"))
    CACHE_NPZ.parent.mkdir(parents=True, exist_ok=True)
    np.savez(CACHE_NPZ, lats=lat_axis, lons=lon_axis, elev_ft=elev_ft)
    log.info("DEM cache written: %s", CACHE_NPZ)
    return elev_ft
