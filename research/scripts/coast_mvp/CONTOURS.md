C2 local contour and tile preview

NOT FOR NAVIGATION. Outputs remain review_required. This is a fixture-tested
research tool, not regional seam, vertical-datum, rights or visual acceptance.
No source acquisition, live service, viewer wiring or publication occurs here.

Run with the survey Python interpreter from repository root:

    python -m research.scripts.coast_mvp.coast_contours \
      --elevation PATH/elevation.tif --contributor PATH/contributor.tif \
      --manifest PATH/manifest.json --output NEW_DIRECTORY --zoom 14

Input contract matches C1: aligned projected-metre GeoTIFF grids, elevation in
metres positive up, contributor codes 0=unsupported, and manifest sources with
code, id and resolution_m. Source resolution is native source resolution, not
the mosaic cell size. No source hashes or original survey caches are reread.
An existing output directory is refused. The default 4-million-cell and
64-terrain-tile caps deliberately limit this to a preview. Large regional runs
need explicit caps and separate admission; none was run for this slice.

GDAL's contour engine is called through its public C API (GDALContourGenerate),
so gdal_contour need not be installed. Fixed elevations are sorted ascending
as required by GDAL, corresponding to 10-foot depths through 600 feet and
100-foot depths below 600 feet. Only levels within the supported depth range
are requested. Lines are intersected per contributor, simplified at half the
smaller grid-cell dimension, then clipped again to avoid crossing holes.
Non-simple lines or open endpoints away from a contributor boundary fail.
Depth and resolution attributes survive into GeoJSON and MVT. GeoJSON is
EPSG:4326; MVT uses GDALVectorTranslate (ogr2ogr API), one zoom per invocation.

Output:
    contours.geojson              labelled lines in longitude/latitude
    vector/{z}/{x}/{y}.pbf         XYZ MVT, layer contours, uncompressed
    vector/metadata.json          GDAL MVT metadata
    terrain/{z}/{x}/{y}.png        XYZ 256x256 RGBA terrain-RGB
    manifest.json                 templates, encoding, counts, limitations

Terrain encoding: elevation_m = -10000 + (R*65536 + G*256 + B)*0.1.
Alpha=0 is unsupported; alpha=255 is supported. Terrain uses nearest source
sampling to avoid inventing interpolation across contributor boundaries;
RGB precision is 0.1 metre, not a statement of source accuracy. Transparent
pixels must not be interpreted as measured elevation. PNG georeferencing is
provided by XYZ placement, not an embedded GeoTIFF transform.
Alpha-0 pixels encode manifest unsupported_fill_m (the lowest supported C1
elevation), never RGB=0 (-10000 m); a viewer must still treat them as absent.

Synthetic fixtures are analytical descriptions at
research/tests/fixtures/coast_mvp/contours/synthetic.json. Tests generate tiny
64x64 gradient, hole, boundary and closed-bowl rasters in temporary directories.
They never use survey data, private assets or network access. The module is
marked gis with lazy GIS imports so normal non-GIS CI excludes it while the
survey-science job runs it.

Acceptance command (survey interpreter):
    python -m pytest tests/contract/test_test_layout.py research/tests/test_coast_mvp_contours.py -q
    git diff --check

Observed: 18 passed, 8 subtests passed. Rasterio emits Affine deprecation and
expected non-georeferenced-PNG warnings. GDAL interpolates at nodata edges;
analytical gradient displacement is checked within the half-cell bound, not
claimed exact there. Regional hillshade/seam assessment and viewer inspection
are deliberately not performed by this synthetic-only card.

Real-data correction (2026-10-22, t_ac49d46e)

The first full cached-C1 run exposed two defects that tiny fixtures missed:
individually simplified depth bands could intersect one another, and GDAL's
approximate warp selected some adjacent pixels instead of the exact nearest
source cell. The corrected producer simplifies each contour with topology
preservation, then keeps a line's simplification only if no other line in the
contributor (original or simplified) touches or lies inside any area its
simplification chords sweep across; otherwise the line reverts to its
unsimplified geometry. Each chord replaces a run of the line's own vertices,
so the run closed by the chord (or its convex hull if that ring
self-intersects) is the swept area, tested with an exact edge-level STRtree.
This keeps crossings out and also keeps nesting: a chord cannot jump a line
past a small enclosed contour. A final edge-contact pass remains as a guard,
before the final mask clip.
(One GEOS call over a contributor's whole MultiLineString gave the same
guarantee but did not finish on Cal DIG I's ~250k components within the run
cap.)
It also inverse-projects every XYZ pixel centre and samples the containing
source pixel exactly, preserving unsupported-cell transparency. Neither change
alters the half-cell bound, contour intervals, source masks or depth labels.
The tests include negative controls exercising both previous algorithms.

The explicitly admitted real run overrides only the cell cap to 130452268;
the default remains 4000000 and the 64-tile cap is unchanged. Outputs and the
full comparison/checksum report remain private under the task's data directory.
Zoom 10 is a preview: MVT quantization and GDAL tiling/generalization are not
full-resolution contour equivalence, and tile readability is not visual or
navigation acceptance. All C1 datum/rights caveats still apply.

Hold merge for independent review. No publication.
