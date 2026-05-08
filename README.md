# Midland Basin Landing-Zone Viewer

Builds a single self-contained interactive HTML file (`midland_basin_viewer.html`)
showing structure (TVD from surface) and isopach (thickness) maps for the seven
Spraberry/Wolfcamp landing zones in the Midland Basin. Source data are EIA's
published shale-play structure & isopach shapefiles, with ground-surface
elevation pulled from public SRTM 1 arc-second tiles to convert from subsea
elevation to TVD.

UX mirrors the sibling `delaware_basin_viewer.html`: pick a formation from the
dropdown, see structure on the left and isopach on the right, click any point
on either map to read out lat/lon and the depth/thickness for **all seven
formations** at that location. Texas county boundaries are overlaid on both
maps for orientation.

## Formations

In stratigraphic order, top to bottom:

1. Upper Spraberry
2. Middle Spraberry
3. Lower Spraberry
4. Wolfcamp A
5. Wolfcamp B
6. Wolfcamp C
7. Wolfcamp D

## Quick start

```powershell
# Default folder paths point at C:\Users\MichaelTanner\Downloads\* — see build.py
python -m midland_basin.build

# Explicit paths
python -m midland_basin.build `
  --wolfcamp "C:\path\to\Wolfcamp_Midland_Structure_Isopachs_EIA" `
  --middle   "C:\path\to\SpraberryMIddleplay_boundaries_structure_isopachs" `
  --lower    "C:\path\to\Spraberry_Lower_formation_structure_isopachs_Midland_EIA" `
  --upper    "C:\path\to\Spraberry_Upperplay_boundaries_structure_isopachs" `
  --out      midland_basin_viewer.html
```

The first run downloads ~70 MB of SRTM tiles from the public Mapzen/AWS mirror
(`elevation-tiles-prod.s3.amazonaws.com`) and caches the resampled DEM as
`data/midland_dem.npz` (~330 KB). The TX county GeoJSON is cached at
`data/us-counties.json`. Subsequent builds are offline.

## Validation

```powershell
python validate.py
```

Runs all six spec checks (discovery, CRS, sign convention, strat ordering,
click-handler smoke test, self-contained HTML). Should print `ALL 6 CHECKS PASS`.

## Repository layout

```
midland_basin/
├── __init__.py
├── shapefiles.py      # discovery + classification of EIA .shp files
├── surfaces.py        # Surface dataclass, griddata + Delaunay-hull mask
├── dem.py             # SRTM 1-arc-sec DEM fetch/cache for TVD conversion
├── geo.py             # TX county GeoJSON loader (bbox-filtered)
├── pipeline.py        # load → reproject → sample contours → grid → TVD shift
├── viewer.py          # Plotly figure assembly + click-handler JS
└── build.py           # CLI entrypoint
data/
├── us-counties.json   # cached county polygons
└── midland_dem.npz    # cached SRTM elevations on the viewer grid
validate.py            # 6-check validation report
midland_basin_viewer.html  # build artifact (~17 MB, fully self-contained)
```

## Conventions

- **Depths are TVD from ground surface in feet** (positive; deeper = larger).
  Internally the EIA shapefiles publish subsea elevation; the pipeline negates
  the sign and adds the SRTM-sampled ground elevation.
- **All grids share a single 200×200 lat/lon extent** spanning the union of
  the four input shapefile bboxes plus a 0.1° pad, so the click handler can
  index every formation with identical axes.
- **Cells outside each formation's data convex hull display "outside coverage"**
  rather than extrapolating — relevant at the basin margins, especially for
  Spraberry plays which don't extend as far south/east as the Wolfcamp benches.

## Dependencies

```
geopandas >= 1.1
shapely   >= 2.0
scipy     >= 1.13
numpy     >= 1.26
plotly    >= 5.20
```

No GDAL/rasterio required — the DEM module parses HGT files directly with
NumPy. `geopandas` already pulls in everything it needs for shapefile I/O via
its bundled GDAL wheels on Windows.

## Data sources

- **EIA shale-play maps** — structure and isopach polylines for each formation,
  authored by EIA from operator well tops.
- **SRTM 1 arc-second** (Mapzen Terrain Tiles, public AWS mirror) — ground
  surface elevation for TVD conversion. ~30 m horizontal resolution.
- **Plotly counties GeoJSON** — TX county boundaries for orientation.
