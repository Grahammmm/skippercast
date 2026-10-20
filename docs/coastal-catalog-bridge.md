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
- `width`, `height`: the valid grid's dimensions in native cells;
- `anchor`: the CRS84 `[west, north]` corner of the source's north-west valid
  cell;
- `cell`: the CRS84 cell size in degrees as `[east, south]` (both positive for
  a north-up raster).

The bridge re-derives the deterministic tiling from that geometry (row-major
from the anchor, with the source-edge tiles clipped when the grid is not a
multiple of 512), restricts it to the tiles whose CRS84 footprint intersects
the segment's `bbox_crs84`, and requires the plan's `windows` to be exactly
that set in row-major order. So a non-canonical shape, an out-of-bounds,
duplicated or out-of-order window, and any tile outside the segment bbox, all
refuse the plan before any write. A missing or malformed `tiling` is refused,
never silently accepted. The anchor and cell size are owner-supplied native
geometry from the frozen catalog; the bridge never opens or reprojects the
raster itself.

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
