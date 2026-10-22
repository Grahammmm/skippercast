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

Terrain encoding (version 2): elevation_m = -10000 + (R*65536 + G*256 + B)*0.1.
Alpha is the only support signal: alpha=255 supported, alpha=0 unsupported.
Version 1 wrote RGB=0 under alpha=0, which a decoder that ignores alpha reads as
-10000 m (a false cliff at every support edge). Version 2 fills RGB under alpha=0
with the nearest supported cell in the same tile, so alpha-blind readers see a
plausible, flat edge. That fill is a display device, not data; a tile with no
supported cell is not written. Supported cells and alpha are unchanged from
version 1, so alpha-aware readers need no change. manifest.json keeps
schema_version 1 and adds terrain_encoding_version and terrain_decode (formula,
support rule, fill rule) as the decode contract; terrain_tiles counts tiles written
and terrain_tiles_without_support those skipped. Terrain uses nearest source
sampling to avoid inventing interpolation across contributor boundaries;
RGB precision is 0.1 metre, not a statement of source accuracy. Transparent
pixels must not be interpreted as measured elevation. PNG georeferencing is
provided by XYZ placement, not an embedded GeoTIFF transform.

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

Hold merge for the one batched C1-C5 independent review. No publication.
