# Bounded source quality and usefulness

Use only for an owner-assigned acquisition/quality iteration. The parent mission
still has one fixed UTC start, 25-minute discovery/inspection cutoff and
30-minute deadline, with the original 250,000,000-byte transfer ceiling. No new
clock or catalog allowance is created by local inspection, a reviewer or a
plan transition. Start only after offline checks and the assigned engineering
review; use the owner's external cgroup supervisor around requests/inspection.
Never launch another trial or alter a closed trial's receipts to resolve a hold.

## Reuse source facts across an explicitly assigned plan

Use the prior finalized source manifest and verify region/bbox, source/policy/
discovery-method identities, original response hashes and expiry. Do not repeat
catalog requests just because this mission's bounded acquisition plan differs.
`reuse --scope-import FILE` accepts an explicit transition receipt:

```json
{
  "manifest_sha256": "CANONICAL_OLD_MANIFEST_DIGEST",
  "new_plan_sha256": "NEW_CHECKPOINT_INITIAL_PLAN_DIGEST",
  "source_ids": ["original-catalog:stable-survey-id"],
  "reason": "Owner-assigned narrower acquisition and sample-quality iteration"
}
```

Use `discover.digest` for canonical JSON digests. Scope must already be authorized
by the owner; a receipt cannot grant permission. Import all relevant valid leads
and original aliases, including unknown-native-CRS footprints. The original
provenance/check date/expiry remain unchanged. Rejected geometry stays rejected;
a metadata lead is not automatically terrain-usable. The new checkpoint retains
its own plan, request log, byte counter and fixed clock; none are replayed or
inherited from the previous mission. Stale quality attachments are retained as
`stale_quality` evidence with a reason, not as current findings.

```bash
python <skill>/scripts/discover.py /private/new.json reuse \
  --manifest /private/old-manifest.json --scope-import /private/scope-import.json
python <skill>/scripts/discover.py /private/new.json add-query \
  --evidence-manifest /private/old-manifest.json --response N \
  --url EXACT_SAVED_LINK --purpose sample --max-bytes 25000000
```

Saved-response links can seed a finite new query only after that exact manifest
passed import. The existing host, catalog, query and body-byte ceilings apply;
source links never authorize a new host. The query receipt pins the old manifest
and response hashes. Request the sample with the ordinary `request` command.

## Bind the native sample to its actual source

The inspector accepts only a successful `purpose:sample` request from the active
mission, its exact saved local body and SHA256. A matching source `access_url`
binds directly. When access_url is a landing page, supply `--binding FILE`:

```json
{
  "source_id": "original-catalog:stable-survey-id",
  "asset_url": "https://official.example/native/sample.tif",
  "sample_request_id": 3,
  "sample_sha256": "EXACT_SAVED_SAMPLE_SHA256",
  "source_metadata_sha256": "QUALITY_SOURCE_DIGEST",
  "parent_evidence": {
    "url": "https://official.example/catalog/page",
    "path": "/private/saved-parent.body",
    "sha256": "EXACT_SAVED_PARENT_SHA256"
  },
  "lineage_confirmed_by": "Actual operator or reviewer identity",
  "lineage_reason": "Specific evidence tying the asset and survey identity"
}
```

`quality.source_digest(candidate)` derives the metadata identity; a metadata-only
receipt also reports it. The binding checks all identities and that the exact
asset is a literal/resolved link in the hash-verified parent evidence. The
already-supported explicit HTTP-to-HTTPS normalization also works when its
original href, saved response hash and exact upgraded URL match the mission's
`added_queries` provenance; the same host/path/query/credential rules apply.
The
operator/reviewer must actually confirm survey lineage, version and processing
state; sharing a host is not enough. Preserve conflicting collection/asset
versions or preliminary QA notices as explicit holds. Do not manufacture a
lineage receipt from file naming alone.

## Inspect one bounded native window

```bash
python <skill>/scripts/quality.py /private/new.json metadata --source SOURCE_ID
python <skill>/scripts/quality.py /private/new.json inspect \
  --source SOURCE_ID --sample-request N --binding /private/binding.json \
  --seconds 45 --max-pixels 1000000 --max-file-bytes 64000000
python <skill>/scripts/quality.py /private/new.json validate --source SOURCE_ID
```

Control and HTTP remain standard library; local GeoTIFF observations use the
existing repository rasterio/numpy/pyproj/jsonschema runtime. No dependency
installation is implied. Default native support is a self-contained, north-up
local GeoTIFF. GSF/MB121 additionally requires the pinned, tested upstream GSF
reader and explicit preflight described in [format-readers.md](format-readers.md),
including its bounded gzip path. BAG/HDF5 and netCDF remain untested. VRT,
remote references, subdatasets, sidecars and other archive containers are
refused. No network, warp, resampling, mapping or generated terrain occurs.

Fixed ceilings: 64,000,000 input bytes, 256,000,000 declared decompressed bytes,
four bands, four million selected pixels, 1 GiB child address space, 48 file
descriptors, five MB output files, at most sixty seconds per inspection and
eight metadata/native attempts per mission. Default native window is one
million pixels. Oversized overlap selects one centered smaller **native**
integer window and records the unexamined remainder; it never downsamples.
Both parent monotonic timeout and independent child alarm are bounded by the
same discovery cutoff. The parent kills/reaps only its own live child group.
Use the external supervisor for hard cgroup bounds and parent/host failure.

The write-ahead `quality_runs` intent persists before launch. An unchanged
source+sample+method+bbox fingerprint cannot start another inspection: consume
the existing receipt. A crash leaves a held intent; inspect/stop the verified
owned process and use the existing `recover` protocol without renewing clocks,
attempts or bytes. Metadata-only review consumes no native quality claim.

The [quality receipt schema](quality-receipt-v1.schema.json) pins source identity,
metadata response and candidate digest, exact sample bytes/hash/request/URL,
binding evidence, selected native window, quality method and applicable policy.
Expiry is no later than the source expiry or one day after inspection. A changed
source, policy, sample hash, metadata digest or method invalidates attachment.
Use `validate` before relying on an attached receipt.

Record native CRS, angular/projected units and resolution; do not convert degrees
to claimed metres. Keep native band units, metadata units and vertical datum
separate. Unknown datum/units/rights remain unknown. Stats cover raw stored first
band values (scale/offset reported, not applied), finite/masked/NoData counts,
valid fraction in the selected window, range, median, adjacent-step and a
disclosed robust outlier rule. Outliers are observations, not noise diagnoses;
valid fractions and bbox overlap never establish whole-survey measured support.
Age uses only parseable declared dates, never filesystem mtime. `age_basis`
identifies acquisition_date versus source_date; a source-date age must not be
described as survey acquisition age. Unknown/unparseable acquisition age stays
explicit. PROJ network access is disabled in the inspection child and reader.

Quality method `local-geotiff-observation-v2` also reads a declared acquisition
interval `{start, end}` only when both endpoints parse and satisfy
`start <= end <= checked_at`. Original metadata is retained. `age_range_days`
reports youngest age from the end and oldest age from the start; `age_days`
stays null rather than inventing a midpoint. Date-only endpoints use UTC
midnight, stated in `age_basis`. Reversed, future, malformed or incomplete
intervals stay unknown. A scalar acquisition date keeps its scalar age; a
source-date fallback is labeled separately and used only when acquisition date
is absent/unknown, not to hide a malformed interval. Unknown labels are
idempotent across repeated observations.

This changed date interpretation increments the quality method, not the source
discovery method. Historical trial receipts remain immutable evidence. Old
quality-method receipts are not current v2 attachments even before their
ordinary expiry; scoped reuse preserves their source leads and records the old
attachment as stale. Do not silently rewrite, refresh or reacquire the closed
trial to migrate it. New assessment requires its own authorized scope.

Usefulness remains separate: `acquisition_lead`, exact `reader_blocked`,
`inspection_blocked`/`nonoverlap`, or a
`bounded_window_candidate_for_qualification`. Habitat remains unassessed and
rendering blocked. Neither a quality receipt nor agent advice is a completed
v2 mapping handoff, display clearance or whole-source certification. Imagery
absence does not erase useful private-terrain evidence.

## One compact independent evidence review

Run deterministic checks first. If interpretation remains ambiguous and the
owner assigned agent assessment, use at most **one** available small supported
reviewer for the compact packet, not a worker per page/file. Use an available
`gpt-6.1-sol` medium as the normal bounded reviewer; a lower-cost setting is
appropriate only after comparable fixtures establish it preserves sample,
unknown and acceptance distinctions. Record unavailable settings or incomplete
calibration explicitly; do not turn routine review into an Astra fallback.
The owner's Astra/high engineering and final review are
separate from this routine assessment; do not change global model settings.

Brief at most 250 words, at most five relevant paths and 64 KB combined textual
input: assigned source/task, one compact quality receipt, decisive metadata and
lineage evidence, exact uncertainty, limits and allowed output. Do not send raw
pixels, entire HTML archives or full conversation history. One response at
most 1,200 words or an equivalently compact JSON review; no network/tools that
reacquire or inspect additional files. Record requested model/effort, observed
model/effort and raw input/cached/output tokens; use null with a reason if the
host does not expose them. Never infer cost or calibration from a simulation.

Save an independent review sidecar binding the exact quality receipt SHA256,
source/sample hashes, reviewer identity, requested/observed model+effort,
usage, evidence used, bounded sample scope, observations/unknowns, usefulness
advice and exact next action. Keep the deterministic receipt immutable. Review
cannot invent missing units/rights, relax reader/resource holds, certify a whole
source, accept habitat or create v2 render acceptance. Absent model access or
time leaves the review unknown; it does not trigger a stronger-model farm.

Finalize the new manifest with `lead_source_ids`, metadata-usable IDs and
`sample_observed_source_ids` separated, quality attachments/holds, exact elapsed
time and request/inspection counters. Preserve partial useful results. One
explicitly authorized post-trial correction may follow evidence review; that
does not authorize another live run.
