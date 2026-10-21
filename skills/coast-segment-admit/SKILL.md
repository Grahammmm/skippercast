---
name: coast-segment-admit
description: Stage hash-verified cached sources and freeze one real lattice-owner bridge plan with a fully validated, review-required admission; never download or enqueue.
---

# Purpose

Draft bounded campaign admission under the governing
[discovery contract](../skippercast-discover-coastal-sources/SKILL.md),
[mapping contract](../skippercast-map-coast/SKILL.md), and
[shared receipt contracts](../coast-campaign-shared/references/contracts.md).
Metadata admission is not scientific acceptance, source qualification or execution
permission. Campaign labels never become Store segment IDs.

# Runs on

AgentOrange, from the card-pinned SC_REPO checkout cwd with its existing shared
SC_PY interpreter. Confirm the checkout commit and interpreter against the card.
Use PYTHONPATH=src for producer modules. No new venv, installed skill or profile
changes. Lead judgement uses the admitted runtime; bounded staging may use an
explicitly admitted worker, never a silent model-route substitution.

HELD for live use until this draft and its shared producer dependencies are merged
and independently reviewed. The shipped adapter is single-selected-v1 only:
1–4 distinct sources, one selected window each, <=2 GiB total, <=262144 cells per
window, <=3600 seconds/job, requests=0. PC-6 multi-window/global-tiling adaptation,
repeated tiles from one source and N=16/64 remain HELD; no fields or caps are guessed.

# Inputs

All shell variables are absolute operator/card bindings, not values inferred from
receipt paths: SC_REPO, SC_PY, C (shared campaign queue), D (unique discovery
attempt), P=C/plans/<safe-plan-id>, ROOTS, SELECTION, RAW_RECEIPT,
CACHE_STAGE_RECEIPT and LEDGER_SNAPSHOT. Source IDs are data, not path components.
Outputs are write-once; partial attempts remain evidence and require a new attempt.
Exclusive/quiescent staging is a prerequisite; these offline tools are not a
concurrent admission reservation service. Never create per-plan Stores to reset
campaign budgets.

C/campaign.json is canonical coast-campaign-v1, including full intended window
inventory. Select only a declared subset; remaining/held inventory stays frozen in
that campaign. Selection is card-authored coast-selection-v1 JSON with:

- campaign_sha256 (canonical campaign file bytes); actual author_profile,
  author_model, card_id, code_commit, skill_commit; allowed_root_ids independently
  admitting exactly ROOTS keys (queue:<campaign>, raw:campaign and any explicitly
  needed disjoint roots); catalog and discovery typed Refs; ledger_snapshot Ref;
- max_total_bytes and native bridge budget {requests:0,bytes,wall_s,memory_bytes};
  preconditions {exclusive_writer:true,attested_by:<actual operator attestation>};
  optional replacement_plan_of typed Ref, never an inferred previous attempt;
- windows[], each with source_id, pixel_window=[col,row,width,height], input Ref,
  raw_provenance Refs (raw:campaign), retained_inputs Refs, reader=native-raster-v1,
  vertical (native producer contract, or null), rights (native rights object),
  rights_summary and datum (explicit strings, unknown stays unknown);
- each window's reviewed grid_definition exactly as
  [admission-producers.md](../coast-campaign-shared/references/admission-producers.md):
  source_sha256, raster_crs, affine_transform=[a,b,c,d,e,f], width,height,
  tile_width,tile_height,tiling_version=single-selected-v1,pixel_window.
  make_plan reads cached raster metadata and refuses disagreement. It reads no
  raster pixels, resamples nothing and preserves crossing-window footprints.

RAW_RECEIPT is the bounded coast-raw-selection-v1 snapshot prepared from the
card-admitted raw receipts, not a rewritten/faked native download receipt. It has
campaign_sha256 and sources[] with each selected source_id,input,raw_provenance,
retained_inputs exactly matching selection. Retain original raw manifest row and
source-manifest snapshot bytes as provenance Refs. Only supported JSON producer
schemas may enter the shared graph; an unsupported manifest/derivation schema
HOLDS pending its own reviewed adapter. Do not disguise JSON as text. Derived
inputs require a supported retained derivation binding both original raw and
output hashes; never claim a derived GTiff is byte-identical to its BAG. Catalog
SHA256/size must explicitly match the input being staged; original-only metadata
cannot silently certify different derived bytes.

ROOTS maps the independently admitted IDs to absolute disjoint no-symlink roots.
No root is guessed from a ref suffix. Staging verifies all hashes and caps before
copying; regular, non-hardlinked sources only. Unbound TIFF sidecars and BAG
external/virtual storage refuse before native metadata access; auxiliary-dependent
sources need an explicit reviewed adapter, never silently dropped masks/metadata.
Copy errors leave partial evidence,
not reusable output. Missing cache/raw input is a prefetch dependency HOLD, never
permission to download here.

LEDGER_SNAPSHOT is an independently pinned coast-budget-snapshot-v1 JSON:
campaign_sha256, coordinator_segment_id, attested_by, campaign_usage_before,
segment_usage_before, campaign_limits, segment_limits. Each usage/limit is exactly
{requests,bytes,wall_s}. It is a card-supplied quiescent reservation snapshot,
not a live Store query. Admission reserves full selected source bytes (no reporting
deduplication) and all per-job wall budgets against BOTH scopes. Concurrent or
outdated snapshots require operator reconciliation, not reuse. Snapshot, selection,
raw receipt and cache-stage receipt remain immutable local intermediate evidence;
the admission carries validated producer/raw/derived refs and the usage values,
not a false claim that these intermediates are shared producer schemas.

# Exact commands

Execute from SC_REPO. Every file/directory argument below expands to an absolute
path; --root does not resolve producer --catalog/--plan/--out arguments.

```sh
"$SC_PY" skills/coast-segment-admit/scripts/stage_cache.py --roots "$ROOTS" --campaign "$C/campaign.json" --selection "$SELECTION" --raw-receipt "$RAW_RECEIPT" --out "$CACHE_STAGE_RECEIPT"
"$SC_PY" skills/coast-segment-admit/scripts/make_plan.py --root "$C" --campaign "$C/campaign.json" --catalog "$D/run/catalog.json" --selection "$SELECTION" --cache-receipt "$CACHE_STAGE_RECEIPT" --out-dir "$P"
PYTHONPATH=src "$SC_PY" -m skippercast.coastal.coordinator.catalog_bridge dry-run --root "$C" --catalog "$D/run/catalog.json" --plan "$P/plan.json" --out "$P/dry"
"$SC_PY" skills/coast-segment-admit/scripts/write_admission.py --roots "$ROOTS" --campaign "$C/campaign.json" --plan-dir "$P" --selection "$SELECTION" --cache-receipt "$CACHE_STAGE_RECEIPT" --ledger-snapshot "$LEDGER_SNAPSHOT" --out "$P/admission.json"
```

# Acceptance checks

make_plan freezes the complete real segments.from_bbox record into segment.json,
including exact projected lattice and producer bbox_crs84; plan.segment binds that
record, never the campaign label. Centre ownership uses floor(x/5000)*5000 and
floor(y/5000)*5000, including negative coordinates and half-open boundaries.
Multiple owner groups refuse before output and print every owner/key partition;
create separately admitted plans explicitly, never drop or duplicate windows.

Each key is source_id#grid_sha256#0, with producer object digest excluding newline;
window_dir is the full SHA256 of that key. Source grids and intended inventory are
unique. Actual densified footprint and overlapping records are retained intact;
scheduling ownership is not clipped support or a coverage claim. Owner must exist
in campaign records, with positive campaign and owner overlap.

Admission rehashes provenance/cache, regenerates geometry, binds frozen catalog,
segment, plan and dry-run bytes, checks both budget scopes, and invokes the shared
full-graph validator before write. would_enqueue is a LIST; would_enqueue_count
is its length, not all windows. All held windows remain in admission.windows.
holds=[] means metadata admission only, never map acceptance. Discovery is an
explicit coast-discovery-evidence-v1 envelope pinning original catalog/evidence;
native discovery receipt graphs are HELD until their adapter is admitted.

# Failure modes

Exit 3 prints HOLD with the bounded reason: cache miss, hash/size/cap mismatch,
symlink/hardlink, absent/unknown reader/CRS, changed grid, unsupported provenance,
wrong lattice/bbox, duplicate inventory, multi-owner selection or current dry-run
mismatch. No download fallback, automatic retry, overwrite or queue mutation.
A successfully serialized held admission remains held. New content requires a new
plan identity, with explicit replacement_plan_of and original inventory preserved.

# Metrics emitted

Stage receipt: measured staging_bytes, staging_wall_s and network_requests=0,
with the common actual-author/card/commit header and campaign/selection hashes.
make_plan stdout: owner,
window keys, full grids and remaining inventory. Admission: would_enqueue_count,
selected/held IDs, holds, per-window footprints, usage_before and conservative
reservation usage_delta. Wall reservations are not measured runtime. Lead minutes
are externally measured, unavailable if not recorded; no invented timings.

# Never

Never download sources, add hosts, modify catalog, install skills, enqueue/tick,
loosen caps, choose an unreviewed reader, infer adjacency between independent
single-selected grids, accept evidence scientifically, publish or send email.
