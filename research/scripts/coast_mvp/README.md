# Whole-segment coast mosaic (private research preview)

Run with survey Python (rasterio + numpy; h5py for BAG):

    python research/scripts/coast_mvp/coast_mosaic.py --region regions/morro-bay/region.json --sources /path/to/sources.json --output ~/skippercast-data/coast/new-run

No downloads. Cached originals read-only. Existing output directories refused.
Default reserve 250 GiB, cap 250 million cells. Estimated temporary bytes include
materialized source grids and COGs/overviews. Reserve is a preflight, not protection
against concurrent unrelated writers. Failed runs remain for diagnosis.

## Source/offset table

JSON: schema_version=1, sources=[...]. Each source requires id (unique safe name),
path (local TIFF/regular BAG), sha256, resolution_m, units="m", value_convention
("elevation_positive_up"/"depth_positive_down"), vertical_datum
(MLLW/NAVD88/MSL/EGM2008/unstated/instantaneous_sea_level), vertical_offset_m,
citation, rights, attribution, offset_note. Extra fields pass into the manifest.

Normalization: elevation = source * sign + vertical_offset_m. Supply evidenced
constants, never guess. Unstated datum requires zero and remains flagged. Constants
are NOT geodetic datum conversions. Projected metre sources only; declared spacing
must match native grid. Implicit scale/offset and variable-resolution BAG refused.

Finest-first priority, lexical ID ties. GDAL BuildVRT receives reverse order since
last valid wins. Warp whole sources to EPSG:3310, 10 m, nearest, exact transformer
(-et 0). Materialize before stacking: lazy warped-VRT chunk-dependent sampling can
otherwise disagree with contributor reads. Delivered pixel spacing is not effective
survey resolution (Point Buchon includes resampled 5 m data in its 2 m grid).

## Outputs and gates

Self-contained elevation.tif (metres, positive up; depth is its negative),
contributor.tif (uint16 code; zero=no support), support_count.tif (uint16 source
count), all COGs with nearest overviews. manifest.json records full source hashes,
citations, offsets, contributor code counts, output hashes, geometry, valid/hole/
overlap counts and extrema. Every elevation block is checked against independently
selected finest-source values. Holes include land and unsurveyed water; no water mask.

NOT FOR NAVIGATION. review_required is not semantic, datum or rights acceptance.
C4 owns regional QA; C5 owns rights/attribution. No viewer, upload, runtime, canonical
store or #816 changes. Opus batch review of C1-C5 required before merge.

## Exercised cached C1 run

Three whole 2 m CSMP rasters (Morro/Buchon/Estero) plus original 10 m Cal DIG I,
using committed morro-bay region bounds. All four datums conservatively unresolved;
all offsets zero. c1-acceptance.json contains source/output hashes. Restore each
sources[].path to a local cached original to reproduce. No large data committed.

    python -m pytest research/tests/gis/test_coast_mvp_mosaic.py -q

11 offline controls cover real GDAL priority, sign, offsets, nodata, holes,
overlaps, COGs, hash pins, URI refusal, invalid units/resolution/datum offsets,
caps, duplicate IDs and overwrite refusal. Real C1 run checks every output block.
