OC-SEAMS local contour endpoint observation

NOT FOR NAVIGATION. Outputs remain review_required, not seam acceptance.
Nothing is stitched, smoothed, transformed between datums or published.
Only synthetic fixtures were exercised; real admitted pairs are an operator
step after merge. No acquisition or live-segment run is authorized here.

Operator command, from repository root with the survey interpreter:

    python -m research.scripts.coast_mvp.coast_seams \
      --a C2_OUTPUT_A --b C2_OUTPUT_B --boundary SHARED_EDGE.geojson \
      --output NEW.json

Each C2 directory must have contours.geojson and manifest.json. Both manifests
must say status=review_required and agree on value_convention and contour_crs;
contour_crs must be EPSG:4326. No vertical-datum field is read or inferred.
Contours are FeatureCollections of LineStrings carrying depth_ft and positive
source_resolution_m. Boundary input is a GeoJSON LineString or Feature with
one, in lon/lat EPSG:4326, 2–1000 finite vertices, simple and nonzero length.
Explicit non-4326 GeoJSON CRS declarations are refused.

observe(a_dir, b_dir, boundary_path, *, band_m=None, match_m=None) writes
nothing. It uses WGS84 azimuthal equidistant metres centred on the boundary
midpoint. Default band_m is twice the coarsest source_resolution_m across
both sides; default match_m is three times it. CLI overrides: --band-m,
--match-m (finite nonnegative metres). Open-line endpoints within the band
are grouped by depth_ft. Closed lines contribute none. Candidate pairs at
the same depth are consumed by ascending distance, then lon/lat coordinates,
without reusing endpoints. This is greedy, not globally optimal matching.

shared_edge(bbox_a, bbox_b, *, match_m=0) accepts [west,south,east,north].
Its default requires exact touching because bboxes declare no resolution.
Pass the observation's match_m to permit overlap shallower than that many
metres. The edge lies midway through that shallow overlap, with positive
length on the other axis. Gaps, corner-only contacts and deep overlaps fail.

The coast-seam-observation-v1 report includes directory labels, input and
boundary byte SHA256s, distances, depth rows, endpoint/match totals and levels
present in only one input (even if that level has no endpoints in the band).
Per-level gap_m is {min,median,max}, or null with no matches. Fixed flags:
stitched=false, inputs_modified=false, review_required=true,
navigation="NOT FOR NAVIGATION", vertical_datum="undeclared".
No horizontal/vertical datum transform or reconciliation is performed;
endpoint proximity proves neither accuracy nor navigation fitness or rights.
Canonical sorted JSON has no timestamp: unchanged inputs repeat identically.
CLI output uses exclusive creation at mode 0600; existing paths are refused.

Acceptance (offline synthetic fixtures, no rasters):
    SKIPPERCAST_REQUIRE_GIS=1 python -m pytest research/tests/test_coast_mvp_seams.py tests/contract/test_test_layout.py -q
    git diff --check
