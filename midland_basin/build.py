"""CLI entrypoint to build the Midland Basin landing-zone HTML viewer."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .pipeline import build


DEFAULTS = {
    "wolfcamp": Path(r"C:\Users\MichaelTanner\Downloads\Wolfcamp_Midland_Structure_Isopachs_EIA"),
    "middle":   Path(r"C:\Users\MichaelTanner\Downloads\SpraberryMIddleplay_boundaries_structure_isopachs"),
    "lower":    Path(r"C:\Users\MichaelTanner\Downloads\Spraberry_Lower_formation_structure_isopachs_Midland_EIA"),
    "upper":    Path(r"C:\Users\MichaelTanner\Downloads\Spraberry_Upperplay_boundaries_structure_isopachs"),
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the Midland Basin landing-zone HTML viewer.")
    p.add_argument("--wolfcamp", type=Path, default=DEFAULTS["wolfcamp"],
                   help="Folder containing Wolfcamp A/B/C/D Elevation+Isopach .shp files")
    p.add_argument("--middle",   type=Path, default=DEFAULTS["middle"],
                   help="Folder containing Middle Spraberry Structure+Thickness .shp files")
    p.add_argument("--lower",    type=Path, default=DEFAULTS["lower"],
                   help="Folder containing Lower Spraberry Elevation+Isopach .shp files")
    p.add_argument("--upper",    type=Path, default=DEFAULTS["upper"],
                   help="Folder containing Upper Spraberry Structure+Thickness .shp files")
    p.add_argument("--out", default="midland_basin_viewer.html",
                   help="Output HTML path (default: midland_basin_viewer.html in cwd)")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    build(
        wolfcamp_dir=args.wolfcamp,
        middle_dir=args.middle,
        lower_dir=args.lower,
        upper_dir=args.upper,
        out_html=args.out,
    )
    out_path = Path(args.out).resolve()
    print(f"Wrote {out_path}  ({out_path.stat().st_size/1e6:.2f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
