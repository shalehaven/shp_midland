"""Discover and classify EIA shapefiles across the four input folders.

Each folder is a downloaded zip-extract from the EIA shale-play map series.
Filenames follow no single convention across vintages, so we classify by
keyword:

    structure  - 'elev', 'struct', 'top'        (subsea elevation in feet)
    isopach    - 'iso', 'thick'                  (thickness in feet)
    boundary   - 'boundary', 'extent', 'outline' (play boundary polygon)

The Wolfcamp folder additionally needs splitting into A/B/C/D sub-benches.
The function emits a discovery table on stdout for operator review.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


FORMATIONS_ORDERED = [
    "Upper Spraberry",
    "Middle Spraberry",
    "Lower Spraberry",
    "Wolfcamp A",
    "Wolfcamp B",
    "Wolfcamp C",
    "Wolfcamp D",
]


@dataclass(frozen=True)
class ShapefileEntry:
    formation: str        # display name e.g. "Wolfcamp A"
    layer: str            # 'structure' | 'isopach' | 'boundary'
    path: Path


def _list_shapefiles(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*.shp"))


def _classify_layer(name: str) -> str | None:
    n = name.lower()
    if any(k in n for k in ("isopach", "thick")):
        return "isopach"
    if any(k in n for k in ("elev", "struct", "_top_", "depth")):
        return "structure"
    if any(k in n for k in ("boundary", "extent", "outline", "play_")):
        return "boundary"
    return None


def _wolfcamp_bench(name: str) -> str | None:
    """Pull A/B/C/D out of a Wolfcamp filename. Robust to underscores, case,
    and the 'WC?' shorthand. Returns None if no bench token is found."""
    n = name.lower()
    # Direct token: "wolfcamp_a", "wolfcamp a", "wolfcampa"
    for letter in ("a", "b", "c", "d"):
        for tok in (f"wolfcamp_{letter}_", f"wolfcamp{letter}_",
                    f"wc_{letter}_", f"wc{letter}_"):
            if tok in n:
                return f"Wolfcamp {letter.upper()}"
    return None


def discover(
    *,
    wolfcamp_dir: Path,
    middle_dir: Path,
    lower_dir: Path,
    upper_dir: Path,
) -> list[ShapefileEntry]:
    """Walk the four input folders, classify each .shp, and return a flat list.

    Prints a per-folder summary table. Raises if any of the 7 formations is
    missing a structure or isopach layer.
    """
    entries: list[ShapefileEntry] = []
    spraberry_jobs = [
        ("Upper Spraberry", upper_dir),
        ("Middle Spraberry", middle_dir),
        ("Lower Spraberry", lower_dir),
    ]

    print("=" * 72)
    print("MIDLAND BASIN SHAPEFILE DISCOVERY")
    print("=" * 72)

    for fm, folder in spraberry_jobs:
        if not folder.exists():
            raise FileNotFoundError(f"Folder missing: {folder}")
        print(f"\n[{fm}]  {folder}")
        for shp in _list_shapefiles(folder):
            kind = _classify_layer(shp.name)
            print(f"  {kind or '?':<10} {shp.name}")
            if kind in ("structure", "isopach"):
                entries.append(ShapefileEntry(fm, kind, shp))

    if not wolfcamp_dir.exists():
        raise FileNotFoundError(f"Folder missing: {wolfcamp_dir}")
    print(f"\n[Wolfcamp A/B/C/D]  {wolfcamp_dir}")
    ambiguous: list[Path] = []
    for shp in _list_shapefiles(wolfcamp_dir):
        kind = _classify_layer(shp.name)
        bench = _wolfcamp_bench(shp.name)
        print(f"  {kind or '?':<10} {bench or '?':<12} {shp.name}")
        if kind in ("structure", "isopach"):
            if bench is None:
                ambiguous.append(shp)
                continue
            entries.append(ShapefileEntry(bench, kind, shp))

    if ambiguous:
        print("\nWolfcamp bench could not be resolved for:")
        for p in ambiguous:
            print(f"  {p}")
        raise RuntimeError("Wolfcamp bench classification ambiguous; rename "
                           "or add a token like '_A_' / '_B_' to the filename.")

    # Validate completeness
    print("\n" + "-" * 72)
    print("CLASSIFICATION SUMMARY")
    print("-" * 72)
    missing: list[tuple[str, str]] = []
    for fm in FORMATIONS_ORDERED:
        s = [e.path.name for e in entries if e.formation == fm and e.layer == "structure"]
        i = [e.path.name for e in entries if e.formation == fm and e.layer == "isopach"]
        s_str = s[0] if s else "MISSING"
        i_str = i[0] if i else "MISSING"
        print(f"  {fm:<18}  struct: {s_str}")
        print(f"  {' ':<18}  iso:    {i_str}")
        if not s:
            missing.append((fm, "structure"))
        if not i:
            missing.append((fm, "isopach"))

    if missing:
        msg = "; ".join(f"{fm} {layer}" for fm, layer in missing)
        raise RuntimeError(f"Missing layer(s): {msg}")

    print("\nAll 7 formations have both structure and isopach layers. Proceeding.\n")
    return entries
