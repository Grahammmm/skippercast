S-020 cached synthetic segment driver

This bounded implementation invokes the real C1 mosaic, C2 contours/XYZ preview,
C4 QA and C5 rights APIs. source-pins.json records unchanged dependency bytes and
parent heads. These copies are not a new stage implementation or an independent
approval of the inherited stage material. The separately held integration launcher,
contract population, C3 viewer and terrain gate are NOT run or released here.

Only frozen s020-synthetic-cached-plan-v1 plans with synthetic_only=true and
fetch=false are supported. A plan binds recipe_sha256 and ordered source rows:
source_id (coordinator identity), catalog_id (recipe identity), exact typed cache
Ref, datum, resolution_m, source_url and the C5 rights object. Nothing discovers,
fetches or downloads sources. A missing cache is reported by dry-run and refuses
execution. Real operations require a later admitted root and source/runtime gate.
No production default cap is changed. reserve_gib defaults to C1's 250 GiB; tests
explicitly pass zero only inside the bounded synthetic candidate root.

API: run_segment(input_root, workspace=..., admitted_root=...,
recipe_sha256=..., plan_sha256=..., run_sha256=..., code_commit=...,
dry_run=False, reserve_gib=250). All control hashes are caller-supplied pins.
The CLI exposes those pins and --dry-run; it has no fetch or reserve-reduction
switch. CLI commands are file-based, for example:
  .venv/bin/python research/scripts/coast_mvp/coast_segment.py --help

Fixtures use synthetic COPIES of the real recipe/catalog/region interfaces and
existing coordinator run/admission schemas. The small analytical grid is NOT a
Central coast measurement. Held coordinator window states are retained verbatim;
composition does not promote those windows to map_done. The source code commit
and exact driver/stage byte hashes are bound in the resulting open receipt.
Every result is REVIEW REQUIRED, closed=false, semantic_approval=false. Screening
and archive remain with S-023 and S-024. Rights rendering is not
legal permission. Unknown datum remains unknown, without a geodetic transform.

S-026 resume and manifests
Stages run in order: inputs, c1, c2, c4, c5, receipt. Each writes a sealed
stages/<stage>.json (schema coast-segment-stage-v1). The receipt is written in full
and fsynced under stages/.pending/, then renamed to a name that does not yet exist.
It binds the recipe/plan/run/code pins, measured tool bytes (driver, stage module,
helpers, rasterio/GDAL/numpy versions), exact input refs (frozen input bytes, or
all upstream stage outputs) and output refs. resume_segment()/--resume reuses a
stage only if its sealed binding matches and every output still hashes equal.
A changed recipe, input or tool means stale, and a changed or missing output means
tampered. Both are refused before that stage writes anything: no rerun, no overwrite.
An empty, truncated or unsealed receipt, or leftover outputs without a sealed
receipt, mean incomplete. That residue is renamed into quarantine/<attempt>/ and
the stage runs again. Nothing is deleted. segment_status()/--status is read-only
and reports complete, stale, tampered, incomplete, pending or blocked for each
stage. run_segment() still requires a fresh workspace, and resume requires the
workspace marker. A no-op resume does zero stage work and keeps the receipt digest.

manifests/archive-candidates-<sha>.json lists the stage receipts, outputs and
cache copies for the existing skills/coast-segment-close owner. It records
archived=false, closed=false and cache_release "not performed". The local viewer
manifest is written only with viewer=True/--viewer. It is local-only, not for
publication, and mask_qualified=false: the terrain-mask gate stays HELD. Each
successful invocation appends a hash-chained row to manifests/history.jsonl. A
damaged history is refused and needs attended reconciliation.
The disk reserve is enforced on execution but is not part of stage bindings.

COG verification independently opens each analytic C1 GeoTIFF through the public
GDAL C API and checks LAYOUT, tile geometry, TIFF IFD offsets, block byte bounds
and COG overview/block ordering. No osgeo/gdal CLI is installed in this runtime;
the supported bundled GDAL API is used rather than inferring COG from a suffix.
C2 terrain PNGs and C4 hillshade PNGs are presentation rasters, not analytic COGs.
Tests mutate a successful producer's TIFF into a plain TIFF and prove only the
independent verifier is the deciding rejection gate. The disabled-gate control
is diagnostic synthetic output, never product acceptance.

The content receipt excludes the volatile C1 envelope from content products,
but retains that envelope for audit. QA consumes a root-relative copy of its
manifest; exact analytic outputs, source bytes, recipe and plan hashes, tool
bytes, QA support/denominator/config and presentation artifacts remain bound.
Digest equality is asserted across distinct fresh output roots.

Local acceptance (all writes under the admitted candidate):
  .venv/bin/pytest research/tests/test_coast_segment.py -q
Candidate-pinned compatibility is run by the durable out/run2458-tools runner;
it preserves complete raw logs and JUnit results. Do not mistake these focused
and compatibility populations for full CI. The operator still owes the COMPLETE
exact-head ci.yml population: Python core matrices + survey + research, generated
contracts/search plans, web tests/typecheck/tokens/build, separate e2e, repository,
copy/client checks, lint and audit. No push, merge or publication occurs here.
