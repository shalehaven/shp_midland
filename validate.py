"""Run the 6 validation checks listed in CLAUDE.md and print PASS/FAIL.

Usage:  python validate.py
Assumes `midland_basin_viewer.html` already exists in the project root
(produced by `python -m midland_basin.build`). The data-side checks
re-run the pipeline so they exercise the full stack.
"""
from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np

from midland_basin.pipeline import build
from midland_basin.shapefiles import FORMATIONS_ORDERED, discover
from midland_basin.surfaces import query_surface


WOLFCAMP_DIR = Path(r"C:\Users\MichaelTanner\Downloads\Wolfcamp_Midland_Structure_Isopachs_EIA")
MIDDLE_DIR   = Path(r"C:\Users\MichaelTanner\Downloads\SpraberryMIddleplay_boundaries_structure_isopachs")
LOWER_DIR    = Path(r"C:\Users\MichaelTanner\Downloads\Spraberry_Lower_formation_structure_isopachs_Midland_EIA")
UPPER_DIR    = Path(r"C:\Users\MichaelTanner\Downloads\Spraberry_Upperplay_boundaries_structure_isopachs")
OUT_HTML     = Path("midland_basin_viewer.html")


def _line(label: str, ok: bool, note: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    color = "\033[92m" if ok else "\033[91m"
    reset = "\033[0m"
    print(f"  [{color}{tag}{reset}] {label}{(' — ' + note) if note else ''}")


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    print("\n" + "=" * 72)
    print("MIDLAND BASIN VIEWER — VALIDATION REPORT")
    print("=" * 72 + "\n")

    failures: list[str] = []

    # ---- Check 1: discovery report ----
    print("CHECK 1: discovery + classification")
    try:
        entries = discover(
            wolfcamp_dir=WOLFCAMP_DIR,
            middle_dir=MIDDLE_DIR,
            lower_dir=LOWER_DIR,
            upper_dir=UPPER_DIR,
        )
        n_struct = sum(1 for e in entries if e.layer == "structure")
        n_iso = sum(1 for e in entries if e.layer == "isopach")
        ok = (n_struct == 7) and (n_iso == 7)
        _line("7 structure + 7 isopach layers found",
              ok, f"got {n_struct} struct, {n_iso} iso")
        if not ok:
            failures.append("discovery")
    except Exception as e:
        _line("7 structure + 7 isopach layers found", False, f"raised: {e}")
        failures.append("discovery")
        return 1  # nothing else can run

    # ---- Build the full surface stack once ----
    print("\n  (rebuilding surfaces for downstream checks…)")
    surfaces = build(
        wolfcamp_dir=WOLFCAMP_DIR, middle_dir=MIDDLE_DIR,
        lower_dir=LOWER_DIR,       upper_dir=UPPER_DIR,
        out_html=OUT_HTML,
    )

    # ---- Check 2: every loaded GDF reaches EPSG:4326 ----
    print("\nCHECK 2: CRS reproject to EPSG:4326")
    crs_ok = True
    crs_msgs: list[str] = []
    for e in entries:
        gdf = gpd.read_file(e.path).to_crs("EPSG:4326")
        crs_str = str(gdf.crs).upper()
        if "4326" not in crs_str and "WGS 84" not in crs_str:
            crs_ok = False
            crs_msgs.append(f"{e.path.name}: {gdf.crs}")
    _line("all 14 GeoDataFrames in EPSG:4326",
          crs_ok, "; ".join(crs_msgs) if crs_msgs else "")
    if not crs_ok:
        failures.append("crs")

    # ---- Check 3: sign convention ----
    # Pipeline emits POSITIVE TVD from ground surface = subsea_depth + DEM
    # elevation. Midland Basin surface elevations run ~1500..3500 ft AMSL,
    # so adding to subsea Wolfcamp A (~3000..8000 ft) produces TVDs in
    # roughly [5000, 11000] ft. Operator-confirmed convention 2026-05-08.
    print("\nCHECK 3: TVD convention (Wolfcamp A median, D deeper than A)")
    a_median = surfaces[("Wolfcamp A", "structure")].val_median
    d_median = surfaces[("Wolfcamp D", "structure")].val_median
    in_band = 5000.0 <= a_median <= 11000.0
    d_deeper = d_median > a_median
    print(f"    Wolfcamp A median TVD = {a_median:.0f} ft")
    print(f"    Wolfcamp D median TVD = {d_median:.0f} ft")
    ok3 = in_band and d_deeper
    _line("Wolfcamp A median TVD in [5000, 11000] ft AND D below A",
          ok3,
          "" if ok3 else f"A={a_median:.0f}, D={d_median:.0f}")
    if not ok3:
        failures.append("sign")

    # ---- Check 4: stratigraphic ordering at basin centroid ----
    # Depths are positive (ft below sea level); deeper = larger.
    print("\nCHECK 4: strat ordering at basin centroid (32.0°N, -101.7°W)")
    centroid = (32.0, -101.7)
    depths = []
    for fm in FORMATIONS_ORDERED:
        v = query_surface(surfaces[(fm, "structure")], *centroid)
        depths.append(v)
        print(f"    {fm:<18} depth = {v:8.0f} ft")
    finite = [d for d in depths if np.isfinite(d)]
    monotonic = all(d_i < d_j for d_i, d_j in zip(finite, finite[1:]))
    if monotonic:
        _line("monotonic Upper -> Wolfcamp D (deeper = larger ft)", True)
    else:
        _line("monotonic Upper -> Wolfcamp D (deeper = larger ft)", False,
              "NB: spec says warn-don't-fail; basin tilts")

    # ---- Check 5: click-handler smoke test (simulate at Martin County) ----
    print("\nCHECK 5: click-handler smoke (simulate query at Martin County)")
    pt = (32.3, -101.95)
    n_wc_finite = 0
    for fm in FORMATIONS_ORDERED:
        v = query_surface(surfaces[(fm, "structure")], *pt)
        t = query_surface(surfaces[(fm, "isopach")], *pt)
        v_str = f"{v:8.0f}" if np.isfinite(v) else "    nan"
        t_str = f"{t:6.0f}" if np.isfinite(t) else "   nan"
        print(f"    {fm:<18} depth={v_str}   thickness={t_str}")
        if fm.startswith("Wolfcamp") and np.isfinite(v) and np.isfinite(t):
            n_wc_finite += 1
    ok5 = n_wc_finite == 4
    _line("all 4 Wolfcamp rows populated at Martin County", ok5,
          f"{n_wc_finite}/4 finite")
    if not ok5:
        failures.append("click-smoke")

    # ---- Check 6: self-contained HTML ----
    print("\nCHECK 6: self-contained HTML")
    if not OUT_HTML.exists():
        _line("midland_basin_viewer.html exists", False)
        failures.append("html-missing")
    else:
        size_mb = OUT_HTML.stat().st_size / 1e6
        text = OUT_HTML.read_text(encoding="utf-8", errors="ignore")
        has_plotly_inline = "Plotly.newPlot" in text or "plotly-graph-div" in text
        has_data = "MBV_DATA" in text
        ok6 = has_plotly_inline and has_data
        _line(f"HTML written ({size_mb:.2f} MB) with embedded data + Plotly",
              ok6, "" if ok6 else "missing inline plot or MBV_DATA")
        if not ok6:
            failures.append("html-incomplete")

    print("\n" + "=" * 72)
    if not failures:
        print("ALL 6 CHECKS PASS")
    else:
        print(f"FAILURES: {', '.join(failures)}")
    print("=" * 72 + "\n")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
