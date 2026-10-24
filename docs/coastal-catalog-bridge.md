# Frozen catalog to coordinator acquire bridge

`python -m skippercast.coastal.coordinator.catalog_bridge` connects governed
live discovery to the coordinator. Live discovery (#734, documented in its
`docs/coastal-live-discovery.md`) freezes a
`coastal-frozen-discovery-catalog-v1`. The bridge reads that catalog together
with an owner bridge plan. For each selected lead it writes the acquire
stage's existing input, `coastal-native-job-v1`. The coordinator's ordinary
`Store.enqueue` then queues that input at the `acquire` stage. The bridge
changes nothing in the coordinator, the stage CLI or the discovery step.

## Source-free and offline

- The bridge reads only JSON metadata: the catalog and the plan, each at most
  4 MiB. It checks a cached native source with `lstat` alone: the file must be
  a regular file under the queue root, with no symlink in its path, and its
  size must match the ref. The bridge never opens, hashes or downloads source
  bytes. The acquire stage checks the bytes against the ref's SHA-256 when it
  runs.
- The bridge makes no network request and imports no network client. A test
  enforces both.
- The bridge accepts a catalog only when the `catalog_id` still matches its
  content, `review_required` is `true`, and `mapping_accepted` and
  `execution_authorized` are both `false`. The plan pins the catalog's
  `catalog_id` and the SHA-256 of its file.

## Gates per selected candidate

A candidate is selected only if every check below passes. Any other candidate
is held, and the receipt records the reasons:

- it is in the catalog's `usable_source_ids`, has no `rejection_reasons`, and
  its terrain status is `candidate_for_qualification`;
- its `access_url` uses HTTPS with no credentials and no port, on a host that
  is an exact member of `skippercast.http.default_allowlist()`. A suffix
  wildcard never admits a host, and the bridge never adds one. A URL that
  cannot be parsed is held as `access_url_malformed`;
- its catalog `extent.bbox` (CRS84) overlaps the segment's `bbox_crs84`, and
  its `expires_at` is a UTC stamp in the future;
- its cached ref passes the `lstat` checks above. When the catalog states a
  size, the ref must match it. When the catalog states a SHA-256, the ref must
  match that too. Any other hash is recorded as `unknown`, not trusted;
- its native window is a list of four integers with at most 262,144 cells,
  the acquire stage's own bound (`mapping_input.MAX_CELLS`, enforced by
  `mapping_input.observe`). The Store's acquire dispatch gate uses the same
  constant, so a window the acquire stage would refuse is never queued: a
  well-formed window above the bound refuses the whole plan before any write
  (`native_window_bound`), and the dispatch gate holds such a job as
  `native_window_bound`. The acquire bound is not raised to meet the bridge.

## Caps

These caps are fixed and checked before anything is written:

- 1 to 4 distinct sources (`MAX_SOURCES`);
- at most `MAX_JOBS` acquire jobs, with at most 64 windows per source
  (`MAX_WINDOWS`), so a plan enqueues at most N x sources = 256 jobs;
- `max_total_bytes` of selected cached sources, at most 2 GiB
  (`MAX_TOTAL_BYTES`, the acquire stage's default per-job ceiling; a cached
  source is counted once no matter how many windows it tiles);
- an acquire budget with exactly `wall_s` (at most 3,600), `memory_bytes`,
  `bytes` (at most the bridge cap, and at least the size of each selected
  source) and `requests` set to `0`.

## Window-set plans (G5)

A selection may carry a `windows` list instead of a single `window`: the
deterministic 512 x 512 tiling of one source, listed row-major from the
source's north-west valid cell. Each window becomes one acquire job, so a
window-set plan enqueues one job per window through the ordinary
`Store.enqueue`, and `enqueue` returns the job ids in that index order. The
receipt lists every window with its `window_index`, its `window` and the
`sha256` of its native-job manifest.

A window-set selection must also declare the source's native geometry as
`tiling`, so the bridge can prove the tiling without opening the raster:

- `tile`: the canonical tile size, fixed at `512` native cells;
- `width`, `height`: the full original raster's dimensions in native cells,
  not a cropped valid-region size (each at most 32,768);
- `origin`: required native `[column, row]` of the north-west valid cell in
  that original raster. Both must be integers inside the full source bounds;
  even a zero-origin source must declare `[0, 0]` explicitly;
- `anchor`: the CRS84 `[west, north]` corner of the cell at `origin`;
- `cell`: the CRS84 cell size in degrees as `[east, south]` (both positive for
  a north-up raster).

The bridge re-derives the deterministic tiling from that geometry (row-major
from `origin`, with tiles clipped at the original raster's right/bottom bounds),
restricts it to the tiles whose CRS84 footprint intersects
the segment's `bbox_crs84`, and requires the plan's `windows` to be exactly
that set in row-major order. So a non-canonical shape, an out-of-bounds,
duplicated or out-of-order window, and any tile outside the segment bbox, all
refuse the plan before any write. A missing or malformed `tiling` is refused,
never silently accepted. Manifest windows retain original source-native offsets:
for `origin=[128,256]`, the first full tile is `[128,256,512,512]`, never
`[0,0,512,512]`. Footprints subtract `origin` before applying the geographic
`anchor` and `cell` spacing. Geometry is owner-supplied, plan-hash-bound metadata
associated with the selection's source SHA-256; the bridge checks its internal
consistency, not its truth against raster bytes or nodata. It never opens or
reprojects the raster. The owner must establish the north-west valid cell;
interior nodata remains subject to the existing acquire/qualification gates.

Each window is still held to the acquire stage's own bound of 262,144 cells
(the per-job cap is unchanged), a window set is capped at `MAX_WINDOWS` (64)
per source, and the whole plan at `MAX_JOBS` (N x sources). A 65th window is
refused as `window_set_size` and an over-cap window as `native_window_bound`,
both before any write.

A single-window selection (today's shape) is unchanged: its receipt stays
byte-identical to today's, caps block included. The raised job cap (`N x
sources`) and the `max_sources` / `max_windows_per_source` keys appear only on
window-set receipts.

## Commands

```sh
python -m skippercast.coastal.coordinator.catalog_bridge dry-run \
  --root QUEUE_ROOT --catalog catalog.json --plan PLAN.json --out NEW_DIR
python -m skippercast.coastal.coordinator.catalog_bridge run \
  --root QUEUE_ROOT --catalog catalog.json --plan PLAN.json --out QUEUE_ROOT/NEW_DIR
```

`dry-run` writes only `bridge-dry-run-receipt.json`
(`coastal-catalog-acquire-bridge-dry-run-v1`). The receipt lists the decision
for every candidate, the caps and the jobs the bridge `would_enqueue`.

`run` writes one read-only `native-job-NN.json` per window inside the queue
root (one per selected lead for a single-window plan, one per window for a
window set), plus `bridge-receipt.json`
(`coastal-catalog-acquire-bridge-receipt-v1`). Each job carries
`catalog_lineage`: the catalog ID and hash, the `source_id`, the access URL and
the hash binding. `catalog_bridge.enqueue(store, receipt_ref, code_sha=...,
deps_sha=...)` then queues each job at `acquire` through `Store.enqueue`. Before
that, `enqueue` checks that the Store's segment has the same `bbox_crs84` as
the bridged one. Neither command reuses an output directory. `--root` and
`--out` may be relative: the bridge resolves the output's parent before it
checks containment or writes, so every recorded ref stays relative to the
resolved queue root.

## Running bridged jobs

The host driver `skippercast.coastal.coordinator.bridge_run` runs one admitted
plan through acquire, qualify and map, never render. It uses the campaign's
existing shared Store at `var/coastal/coordinator.sqlite`; there is no per-plan
database or policy override. This is bounded execution evidence, not scientific
acceptance or publication authority. The survey stack is needed to authenticate
the genuine EPSG:3310 lattice record and native pixel-centre ownership.

Bind `SC_PY` to the checkout's existing shared venv interpreter, `C` to an
absolute campaign queue root, `P` to its absolute `plans/<plan-id>` directory,
and `RUN` to the new absolute `P/runs/run-00.json`. The parent output directories
must already exist. `MAX_TICKS` and `UNTIL_EPOCH` are the card's explicit integer
tick limit and finite epoch deadline. Every file argument is absolute. Set the
runtime provenance environment explicitly: `COAST_AUTHOR_PROFILE`,
`COAST_AUTHOR_MODEL` (the actual runtime, not an alias), `COAST_CARD_ID`,
`COAST_CODE_COMMIT`, and `COAST_SKILL_COMMIT`. None is inferred from a profile.

Before either writing command the operator must establish exclusive queue
ownership and export `COAST_EXCLUSIVE_WRITER="$C"` for that invocation. The
admission also records `preconditions.exclusive_writer=true` and a nonempty
`preconditions.attested_by`. This is an operator assertion, not a security
boundary: flock cannot exclude arbitrary writers ignoring the controller lock.
If ownership is not established, execution refuses; never start another Store
to work around contamination.

```sh
PYTHONPATH=src "$SC_PY" -m skippercast.coastal.coordinator.bridge_run enqueue \
  --root "$C" --bridge-receipt "$P/bridge/bridge-receipt.json" \
  --segment "$P/segment.json" --admission "$P/admission.json" \
  --out "$P/bridge/enqueue-receipt.json"
PYTHONPATH=src "$SC_PY" -m skippercast.coastal.coordinator.bridge_run run \
  --root "$C" --enqueue-receipt "$P/bridge/enqueue-receipt.json" \
  --stop-after map --max-ticks "$MAX_TICKS" --until "$UNTIL_EPOCH" --out "$RUN"
PYTHONPATH=src "$SC_PY" -m skippercast.coastal.coordinator.bridge_run status --root "$C"
```

The local admission adapter consumes `coast-admission-v1`: campaign and
coordinator IDs, plan label and canonical `plan_sha256`; typed queue-root Refs
for `campaign`, `plan_file`, `segment_record`, `catalog` and `dry_run`; `holds=[]`;
the ownership preconditions above; `grids[]` with `grid_sha256` and `definition`;
and `windows[]` with `source_id`, `grid_sha256`, `idx`, `pixel_window`,
`owner_segment_id`, `window_key` and `window_dir`. Refs carry `root_id`, `path`,
`sha256`, `bytes`, with `root_id="queue:"+campaign_segment_id`. The full segment
record must match `segments.from_bbox(campaign.bbox_crs84, region=campaign ID)`
and the pinned plan. Campaign labels are never Store segment IDs.

Each single-window selection uses an admitted `single-selected-v1` grid at
`idx=0`, with `source_id` and `cols=rows=total=1` on its grid entry. Its definition
contains `source_sha256`, `raster_crs`, `affine_transform` (six coefficients
a,b,c,d,e,f), raster `width`/`height`, `tile_width`/`tile_height`, `tiling_version`
and the exact `pixel_window`. Its canonical digest is `grid_sha256`.
`window_key=source_id+'#'+grid_sha256+'#'+str(idx)` and `window_dir` is its UTF-8
SHA-256. A `window-set-v1` selection instead binds one grid to all of its
windows, in plan-selection order then native-window order. Its definition
pins the exact selection `tiling`, full raster dimensions and tile dimensions;
the grid entry records the distinct column/row origins and window count.
Every bridge job, native manifest and admission window is bound to that
ordered expansion before any Store, enqueue intent or receipt is created.
`idx` is selection-local, matching the merged shared validator. Distinct
selected source IDs are still reported once, not once per window; existing
job/source/window/byte caps are unchanged.

This qualifies only single-plan geographic window sets. Projected-CRS
window sets remain unqualified, and multi-plan window-set campaigns over
one source remain held pending the shared-contract global-index resolution.
Code/dependency identities remain the actual `loop.implementation_hashes`
values; changed driver bytes require a new implementation identity.

Enqueue authenticates all native manifests before writing a durable O_EXCL
intent at `var/coastal/enqueue-intents/<bridge-file-sha256>.json`, before the
first Store insertion. An existing intent refuses even if a crash prevented the
final enqueue receipt. Reconciliation is separate operator work, not a retry.
The receipt preserves actual acquire IDs in bridge index order; `new_row`
compares the root-ID sets before/after, not SQLite's last event insertion.

Under the normal controller lock, read-only whole-Store preflight precedes
enqueue and every normal `reconcile=True` tick. All rows, including foreign
terminal/render rows, must have the current code/deps identity, a known generic
contract and safe state; no leases, even expired ones, may exist. Foreign
source-free/authenticated mission authorities refuse too. Refusal occurs before
constructing Store, invalidation, expiry, claim, events or charges. A run writes
only its new external refusal summary. No recovery or gate disabling occurs.

Lineage follows only SHA-verified committed results and their exact
`next_job.input_manifest` identities inside the predecessor's recorded lease
output directory. A similarly prefixed path is not lineage. Every tick selects
one queued lineage ID deterministically by window key, stage order and ID;
foreign jobs and render successors are not claimed. Foreign job rows, events,
leases and charges are compared after every tick. A change is uncertainty, not
success. Global tick/semantic-progress telemetry is not foreign-job evidence.

The immutable `coast-run-summary-v1` partitions all admission windows into
`map_done`, `held`, `failed_terminal`, `failed_uncertain`, `stale`, `cancelled`,
or `unfinished`. Missing stages have reasons, not success. It pins stage
results/products, qualify support and mask SHA, and copies the producer's map
`native_valid_count` and complete `depth_m` verbatim (including `unknown`; no
invented median). Usage comes from durable charges; unique-source byte reporting
does not reduce bridge/Store accounting. `store_status` is the read-only
`coastal.cli.queue_status` snapshot unchanged.

Stop reasons are `terminal`, `deadline`, `max_ticks`, `not_claimable`,
`preflight_refused`, `integrity_error`, or `failed_uncertain`. Only the first
three bounded unfinished reasons (`deadline`, `max_ticks`, `not_claimable`)
permit ordinary continuation. Use the run command again with
`--continuation-of "$PREVIOUS_RUN"` and a new `RUN` ending in `run-01.json`
(then 02, etc.). It pins the previous file's full-byte hash, increments sequence,
and preserves all root IDs. Never call bridge/enqueue again. Legitimate
qualify/map/render successors may increase the total row count. Stale identities
need replacement admission; uncertain work needs operator recovery. Neither is
a successful empty frontier. CLI exit 3 means a written refusal/integrity/
uncertainty summary; malformed inputs or existing outputs exit 2. Status neither
creates nor migrates a Store.

## Boundaries

A bridged job is input for the coordinator's existing gates. It is not
accepted for anything. The acquire stage still verifies the source bytes and
records zero requests. Qualification, vertical semantics, rights, mapping
review and rendering keep their own holds. For example, if a plan declares no
vertical contract, the acquire stage holds on `vertical_*` instead of
guessing one.

Deep-band datums (G3, 2026-10-20): a plan may declare `depth_lane` `M`
(300-600 ft) or `D` (>600 ft) in its vertical contract. Only then does
`coastal.vertical` admit the `EGM2008`, `instantaneous-sea-level` and
`unstated` datum classes. `unstated` needs a raster header that names no
datum. A named class needs either a header that states it or a
`datum_statement` that cites the source metadata by hash; a null, empty or
malformed statement is held, never read as an absent one. The block then
carries a fixed `deep_datum` record: no uncertainty bound is required, the
output is not for navigation, the datum is not a chart datum and no datum
transform is applied. Cells shallower than the lane floor (91.44 m for M,
182.88 m for D) are dropped from depth and native support. A contract with no
`depth_lane` is lane S, which keeps MLLW, MSL, NAVD88 and ellipsoid:WGS84 and
holds a deep class on `vertical_datum_deep_lane_only`.

The bridge depends only on the catalog file's schema, not on the discovery
module. Integration with live discovery waits for #734 to merge.
