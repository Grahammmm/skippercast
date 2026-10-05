# Classified habitat map representation

`native-classified-geometry-v1` retains each valid original EPSG:3310 polygon,
including its holes, in a private hash-bound `classified-native.geojson` inventory.
The stage and publisher validate that inventory, ordered feature identities,
canonical WGS84 representation and original area claims independently. Native
boundaries supply the whole-polygon restriction screen and area accounting.
Invalid native evidence remains rejected.

The versioned representation uses Shapely's shell/hole-aware `structure` method
with `keep_collapsed=False` only when a coordinate transform creates invalid
geometry. It never rounds, buffers, smooths or simplifies the native polygon.
Each WGS84 polygon must remain valid after conversion to EPSG:3310 and EPSG:3857.
Returning those representations to the original frame may differ by at most
0.002 square metres per feature; the complete EPSG:3310 union may differ by at
most 0.01 square metres. These fixed floating representation bounds are not
survey accuracy or additional measured coverage. Unsupported differences fail
closed. Runtime versions and implementation hashes bind the classified receipt;
old receipts need a classified restage, without changing graded terrain caches.

PMTiles encode clipped, quantized cartographic shapes. Their display edges are
not authoritative native geometry or precise fishing coordinates. Source depth,
area, IDs and the unranked/nonexportable interpretation remain unchanged. Current
source rights and whole-polygon screening still decide release eligibility.

The committed `tests/fixtures/seafloor/classified-point-contact.pmtiles` is a
synthetic 100 m square at arbitrary EPSG:3310 coordinates with a triangular hole
meeting its shell at one point. `touching_hole()` in
`tests/gis/test_classified_geometry.py` defines it. It was represented with this
module and built with the production `seafloor.publish` Tippecanoe flags at
zooms 12–15, using official felt/tippecanoe commit
`4f2621186acfec33b63ddf636f665623c0fef2dd` (v2.82.0). The browser regression reads
actual tiles with the vendored PMTiles decoder; Python fixtures separately test
native fidelity, holes, invalid originals and the rejection of default linework
area inflation. The binary contains no survey data.
