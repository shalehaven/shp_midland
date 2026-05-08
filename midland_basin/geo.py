"""Texas county overlay for the Midland Basin viewer.

Loads the public Plotly counties GeoJSON, filters to TX FIPS whose bbox
intersects the data grid extent, and emits per-county polygon ring lines
plus centroid label points for the Plotly figure.

The GeoJSON is cached under `data/us-counties.json` so subsequent builds
don't hit the network. Fetch failures degrade silently — the viewer just
renders without the overlay.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path


URL_COUNTIES = "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json"
CACHE_PATH = Path("data") / "us-counties.json"


def _fetch_or_load() -> dict | None:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    try:
        req = urllib.request.Request(URL_COUNTIES,
                                     headers={"User-Agent": "midland-basin-builder/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode("utf-8")
        data = json.loads(raw)
    except Exception as e:
        print(f"WARNING: could not fetch {URL_COUNTIES}: {e}")
        return None
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")
    return data


def _iter_rings(geom: dict):
    gtype = geom.get("type")
    if gtype == "Polygon":
        for ring in geom["coordinates"]:
            yield ring
    elif gtype == "MultiPolygon":
        for poly in geom["coordinates"]:
            for ring in poly:
                yield ring


def _ring_bounds(ring: list) -> tuple[float, float, float, float]:
    xs = [pt[0] for pt in ring]
    ys = [pt[1] for pt in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_overlap(a: tuple[float, float, float, float],
                  b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def get_tx_county_lines(
    lat_range: tuple[float, float],
    lon_range: tuple[float, float],
) -> list[dict]:
    """Return [{name, fips, lons, lats}] for every TX county touching the bbox.

    Each county can contribute multiple rings (one per polygon part); they
    are emitted as separate dict entries sharing the same fips/name. The
    feature ID convention in the source GeoJSON is the 5-digit FIPS code
    (e.g. "48329" for Midland County, TX).
    """
    data = _fetch_or_load()
    if not data:
        return []
    bbox = (lon_range[0], lat_range[0], lon_range[1], lat_range[1])
    out: list[dict] = []
    for feat in data.get("features", []):
        fid = feat.get("id") or feat.get("properties", {}).get("GEOID")
        if not fid or not str(fid).startswith("48"):  # TX state FIPS = 48
            continue
        props = feat.get("properties", {})
        name = props.get("NAME") or props.get("name") or "?"
        rings_for_county: list[list] = list(_iter_rings(feat.get("geometry", {})))
        if not rings_for_county:
            continue
        # Skip the county entirely if no ring overlaps the bbox
        if not any(_bbox_overlap(_ring_bounds(r), bbox) for r in rings_for_county):
            continue
        for ring in rings_for_county:
            lons = [pt[0] for pt in ring]
            lats = [pt[1] for pt in ring]
            out.append({"name": name, "fips": str(fid), "lons": lons, "lats": lats})
    return out


def county_label_points(counties: list[dict]) -> list[dict]:
    """One label per county at the centroid of its largest ring."""
    by_fips: dict[str, list[dict]] = {}
    for c in counties:
        by_fips.setdefault(c["fips"], []).append(c)
    out: list[dict] = []
    for fips, rings in by_fips.items():
        biggest = max(rings, key=lambda r: len(r["lons"]))
        cx = sum(biggest["lons"]) / len(biggest["lons"])
        cy = sum(biggest["lats"]) / len(biggest["lats"])
        out.append({"name": rings[0]["name"], "fips": fips, "lon": cx, "lat": cy})
    return out
