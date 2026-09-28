# Map engine test: MapLibre + PMTiles vs Leaflet + GeoJSON

A side-by-side test of one layer drawn two ways. It does not change the main
map; it decides whether moving to MapLibre is worth it before any real work.

| Page | Engine | How the layer loads |
| --- | --- | --- |
| `/map-test.html` | MapLibre GL 5.24.0 (CSP build) + PMTiles 4.5.0 | Vector tiles read by HTTP range from `/feeds/tiles/<name>.pmtiles` (R2 once connected, the site's own files until then) |
| `/map-test-leaflet.html` | Leaflet (today's app) | Whole GeoJSON downloaded, one polygon per feature |

Both pages show the same view, OpenStreetMap and NOAA chart bases, and reef
style. Add `?layer=socal` to either page to switch from Morro Bay reef outlines
(107 polygons) to the Southern California survey habitat (410 polygons, 228,612
vertices, 6.4 MB GeoJSON), the densest layer in the app.

## Results

Simulated phone (390×844 at 2× density, CPU slowed 4×), median of three runs,
base-map tiles replaced by a blank tile so only the engine and the layer count.
Headless Chromium draws WebGL in software, which penalizes MapLibre, so frame
timings are not representative of a real phone GPU.

| Layer | Engine | First view ready | Library | Layer data, first view / after panning | 12 pans + 5 zooms |
| --- | --- | --- | --- | --- | --- |
| Morro Bay (107) | Leaflet | 0.8 s | 47 KB | 137 KB / 137 KB | 25.6 s |
| Morro Bay (107) | MapLibre | 1.8 s | 269 KB | 27 KB / 58 KB (14 range requests) | 27.2 s |
| SoCal (410, dense) | Leaflet | 2.2 s | 47 KB | 1,490 KB / 1,490 KB | 858 s (~50 s per move) |
| SoCal (410, dense) | MapLibre | 2.0 s | 269 KB | 30 KB / 58 KB (19 range requests) | 25.2 s |

**Reading:** at Morro Bay scale Leaflet is fine and a little faster to first
view, because MapLibre's library is larger. At coastwide density Leaflet with
GeoJSON breaks down, while MapLibre with PMTiles stays flat: the phone only
downloads the tiles on screen, and cost does not grow with the size of the
layer. Growing toward complete California subsea mapping means the main map
will need vector tiles.

Still to check by hand: smoothness on a real phone (open both pages, pan and
pinch; try `?layer=socal`).

## Rebuild and rerun

```bash
# Tiles (tippecanoe 2.82+). Output is deterministic; commit it with its hash in
# scripts/web-vendor-sha256.json.
TIPPECANOE=/path/to/tippecanoe python scripts/build_map_tiles.py [morro-bay-reef-outlines socal-survey-habitat]

# Measurements (needs playwright and Chromium) against a local or deployed site.
pnpm build && npx wrangler dev   # serves http://localhost:8787
node scripts/measure_map_test.mjs http://localhost:8787 3
node scripts/measure_map_test.mjs http://localhost:8787 3 layer=socal
```

`tests/test_map_tiles.py` checks that the committed archives are PMTiles v3
with one `reefs` layer, zooms 8–15, bounds on the right coast, and no temp
paths in their metadata.

The GeoJSON stays the source of truth; the tiles are only a delivery format.
Reef outlines remain partial, research-only habitat footprints, not complete
reefs or fishing spots.
