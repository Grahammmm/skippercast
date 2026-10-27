# Retained native provenance adapter (B1d prerequisite)

This is a shared-contract reconciliation, not an archive, verification, release,
runner, acquisition or scientific-acceptance implementation.

## Compatible ancestry

The task branch merges exact reviewed correction #820
`01712188c4161200135971c16feb5c9d6dee1bd4` with exact sign-off #822
`c99d7587d976f99681962cdf2efc9b8acf9552a7` at merge commit
`abd7e3df0` (resolve shared add/add files to #820; retain #822 sign-off helpers).
The PR head, posted on the task, is the compatible pin. Do not use either old
head alone or change either author's branch. No producer or existing SKILL.md
changes are included.

The current integration also merges main `622dc9616813e06473cbe9d78ca7c0da2d6ff46a`
(reviewed #816) without rebasing the #827/#832 ancestry. PC9-native v1 receipts
remain unchanged; shared enqueue/run edges require the hash-bound v2 adapters in
`coast_receipt_versions.py`. #806 window-set admission and per-window v2 cells
records remain supported. This is not a PC9 window-set execution qualification.

## Trusted selection for unchanged schema-less job.json

An ordinary Store/Coordinator job descriptor has NO schema. It remains unchanged.
A caller MUST supply `GraphValidator.reference(job_ref,
contract='coastal-store-job-v1')`, or use the strict workflow receipt
`coast-native-execution-v1` whose `job` edge selects that contract. The wrapper
has the common workflow author/runtime header plus `job`, `result`, and exactly
two `logs` Refs. Pin the wrapper in workflow evidence; do not overwrite job.json,
rename it to text, add a schema to its bytes or infer its type from its filename.
A plain generic Ref to schema-less JSON remains refused. Contract selection is
an edge assertion, not proof of authenticity: the independently admitted caller
must pin the wrapper or pass the exact expected Ref, as with other workflow inputs.

The adapter requires EVERY field actually serialized by ordinary Store.claim +
Coordinator.tick: job_id, stage, segment_id, code_sha, deps_sha, params_sha,
input_manifest_sha, input_manifest, params, budget, lease_token, region, root,
segment, deadline_utc. Extra fields refuse. It verifies the complete Store job ID
algorithm, exact input/parameter digests, bounded budget, segment/region identity,
and the exact `var/coastal/jobs/job-<id>/<lease>/job.json` location. Acquire/qualify
input contracts are coastal-native-job-v1; map uses private-mapping-input-v2.
A manifest Ref can lack contract because the Store stage selects it; an explicit
wrong contract refuses. Native root_id overrides refuse, even for a bound root.

`root` is the ONLY admitted absolute producer string in this adapter: it is a
record of the original queue spelling, never a file to open. It must equal the
operator's original queue binding. For retained resolution, a B1d resolver may
supply `original_queue_roots` (original queue ID -> original absolute spelling)
separately from retained read bindings. It MUST NOT learn that mapping from the
job bytes. All nested native Refs keep the ORIGINAL queue namespace even when a
resolver returns archived bytes. Absent independent origin binding refuses.

The execution wrapper checks job/result identities, owned result/log paths,
primary output type/count, input-to-output identities, and successor inputs in
artifacts. It does not assert current leases, successful review or release.

## Current native slot audit

The exact allowlists live in `NATIVE_FIELDS` in validate_coast_receipt.py; native
producer top-level fields are closed in coast_native.py. Nested unknown path/ref
objects and *_path/*_ref/*_file fields refuse. Unknown embedded schema documents
refuse, except explicitly enumerated inline vertical-v1 and
vertical-observation-v1 metadata; these still receive the same path-field scan.

| Producer | Traversed byte edges / inline records |
| --- | --- |
| Store descriptor | input_manifest; inline geographic segment; root is an independently compared origin scalar |
| coastal-native-job-v1 | source, review, rights.evidence[]; catalog_lineage is metadata/URL only; nonnull source_row is HELD |
| coastal-cached-observation-v1 | source, facts.source, facts.source_auxiliary[], facts.rights.evidence[]; exact facts digest; inline source_lineage, vertical, geographic support |
| private-mapping-input-v2 | source, review, valid_support, segment (Ref or inline), rights.evidence[], native_facts.source/source_auxiliary[]/rights.evidence[]; exact facts digest; nonnull source_row is HELD |
| coastal-mapping-run-v1 | source, outputs.terrain/mask/cells, segment (Ref or inline), inline mapping_input recursively under its own contract |
| coastal-terrain-summary-v1 | segment (Ref or inline); support/statistics are preserved inline producer facts, not derived measurements |
| coastal-stage-result-v1 | artifacts[] and next_job.input_manifest, enumerated separately for acquire/qualify/map; successor parameters currently empty only |
| coastal-private-input-review-v2 | closed review metadata, no file edges |
| bridge plan/receipts, segment/catalog | #820 enumerated adapters preserved; no source acquisition |

Native raster/auxiliary/terrain/support contracts are explicitly binary leaves,
not arbitrary JSON acceptance. Known structured contracts parse regardless of
extension. Native edges with no known contract refuse (except enumerated slots
whose producer contract selects it). Binary contracts cannot label .json/.jsonl
files. The source adapter is structural and hash-validating, not a raster science
verifier; real native readers were exercised only on synthetic fixtures.
Rights slots preserve #816's exact `coastal-rights-evidence-v1` producer leaf
(required source id/URL/title/hash/bytes, review/validity fields, closed field
set, optional string support_policy). The nearest declaring source_row must
bind that identity; absent identities never match. `synthetic-fixture-evidence-v1`
is only `{"synthetic":true}` on a synthetic producer. The existing #827 workflow
`coast-native-rights-evidence-v1` statement keeps its common runtime header and
is likewise restricted to synthetic evidence on a synthetic producer. These
are distinct contracts, not alternate labels for rewritten bytes. Successful
rights leaves are included in the retained verification set. Native source-row
lineage still additionally requires its registered raw envelope, even when a
rights leaf passes. No legal or scientific acceptance is implied.

Standalone geographic segments require the full inverse-bbox record under
#816, with the measured two-ULP inverse-projection check. Synthetic fixtures
materialize that field before producer execution. mapping_input.bind_segment's
inline native_facts.segment is a separate exact shape: boundary policy, zero
halo and intersection/outside-support fields, without bbox_crs84. It is checked
by the bound-segment adapter, not confused with a standalone geographic record.

## Precisely held provenance (never silently dropped)

* A nonnull source_row (inline or Ref) or native-facts source_lineage.source_row
  is admitted ONLY when the document's exact Ref is registered by a supplied
  coast-raw-provenance-v1 envelope (below); otherwise it still refuses with
  `held: retained source-row adapter not yet admitted` / `held: unregistered
  native lineage`. Ref-valued source_row variants remain held.
* Raw-manifest rows/snapshots are admitted ONLY through the envelope's edge-scoped
  `coastal-prefetch-row-v1` / `coastal-prefetch-snapshot-v1` adapters. A `.jsonl`
  Ref pinned anywhere else still falls into the workflow-ledger branch and refuses
  (`workflow receipt needs a schema`); it is never hashed as opaque text. A live
  append-growing manifest is not an immutable input.
* Cached derived inputs are admitted ONLY for the unchanged
  `coastal-vr-refinement-receipt-v1` selected by an envelope's `derivation` edge.
  Other derivation schemas, and any derivation/raw_manifest_snapshot slot added to
  a native manifest, still refuse as unknown producer fields/schemas.
* Authenticated/source-free/managed-output Store lanes, discover/render jobs,
  nonempty execution params, renderer handoffs/thumbnails and new native output
  schemas require separate adapters and currently refuse. No executable intent,
  scratch, live SQLite or lease document is automatically trusted.
* Canonical catalog/surveys.json BAG records, `evidence[]`/`field_evidence{}`
  path-bearing strings, cross-round catalog corrections (supersession) and
  snapshots over the 32 MiB structured bound remain HELD (addendum v2 line 67-69,
  v3 L2); the inventory lane is synthetic-only until separately widened.

These holds mean this pin is NOT universal archive closure for the real coast.
B1d must retain the admitted complete subgraph and refuse any held provenance,
not report an archive success that silently omits it. Archives, raw-equivalence,
lineage snapshot generation and release gates remain B1d's responsibility.

## Retained raw and derived provenance (addendum v2 + v3, t_f9cfca4f)

Governing design: coast-raw-provenance-addendum-v2.md (SHA256 50211c22...0d2db)
and the v3 plan-anchor delta (SHA256 d832b406...ae93), both independently
approved. Adapters live in `coast_raw.py`; the validator only dispatches.

**API.** `GraphValidator(resolver, *, raw_provenance=())` and
`validate(value, resolver, root_id=..., raw_provenance=())`. `raw_provenance` is
an explicit finite sequence of four-key envelope Refs (root `queue:*`, path
`.json`) collected by walking `coast-admission-v1 sources[*].raw_provenance[*]`
and taking only non-`raw:campaign` items. No glob, filename, "latest" or
receipt-shape discovery exists. CLI: `--raw-provenance ENVELOPES.json` plus
`--original-raw-roots /abs/origins.json` (requires card-admitted
`--allowed-root-id raw:campaign`). The resolver attribute
`original_raw_roots == {'raw:campaign': ORIGINAL_ABSOLUTE_POSIX_ROOT}` is
deployment metadata supplied by the caller, never learned from a receipt; it is
a lexical identity (no open/realpath) and must not equal, contain or be contained
by any queue/repo origin.

**Lifecycle (v3 L0-L4).** Identical Ref tuples collapse; every distinct envelope
is fully validated BEFORE any root walk (an otherwise-unused envelope still
refuses on any defect); only after all pass are the registries published:
R-PLAN `(plan Ref, source_id) -> envelope Ref` (a header-only re-emission of the
same plan selection is a second envelope tuple and REFUSES), R-RAW `raw Ref ->
(inventory_row, metadata_sha256, originals set)` and R-NAT `native/derivation
Ref -> (inventory_row, metadata_sha256, bound source Ref)`; equal values from
different plans coexist, unequal values refuse in every order. During the root
walk an envelope reached by traversal must already be registered, may be pinned
only under `sources[k].raw_provenance[]`, must have `source_id ==
sources[k].source_id`, `plan == admission.plan_file` verbatim, and every
`selections[].raw` must also appear verbatim in the same `raw_provenance[]`.
Observation: between individually valid envelopes an R-NAT conflict is
unreachable, because a native document's own bytes pin its identity tuple; the
registry rule is still enforced and tested directly.

**Envelope `coast-raw-provenance-v1`** (closed; rev4 common header exactly, no
self-hash): `source_id`, `plan` (Ref, same queue root, `.json`, validated via
`reference(plan, contract=bridge.PLAN)`; exactly one plan selection with that
`source_id`; its `source_row` must equal every `inventory_row`; a present
`metadata_sha256` must agree; its native `source` must equal one `originals` Ref
or one derivation `outputs[].artifact`), `snapshot` (Ref, same root, `.jsonl`),
`selections[]` strictly increasing by `line` with unique `row` Ref and `raw`
path: `line`, `row` (Ref `.jsonl`; bytes must equal exactly snapshot line
`line` including LF), `raw` (Ref `raw:campaign`; `row.path ==
origin + '/' + raw.path` byte for byte, `row.sha256/bytes == raw`), `inventory_row`
(closed 8-field synthetic subset `id title kind format url sha256 horizontal_crs
vertical_datum`, kind=bathymetry, format=bag, no `unknown`, `url == row.url`,
`sha256 == raw.sha256`), `metadata_sha256` (BAG XML identity, not a file hash),
`originals[]` (queue Refs, each hash/bytes equal to raw, read with the
structured-bytes guard), `derivation` (null or the unchanged VR receipt: closed
producer field set, source in originals, source_row == inventory_row,
metadata agreement, source + ALL outputs[].artifact + supergrid_table read as
binary leaves, nested metadata walked for smuggled path fields) and
`native_documents[]` (native-job, cached-observation, mapping-input, mapping-run
or the selected VR receipt; every audited `source_row`/`source_lineage.source_row`
occurrence must equal `inventory_row`, every metadata identity must agree, and the
typed input source must equal an originals Ref (BAG) or a derivation output
(GTiff); each is then traversed under its own native contract).

**Snapshot/row grammar** (producer-exact, `prefetch.py` at d79f245e): LF-only
JSONL with final LF, no blank/CRLF lines; each line an object with exactly `url
final_url bytes sha256 etag last_modified fetched_at licence segments path
review_required verification`; `fetched_at` equals the `stamp()` grammar
(`+00:00`, optional six-digit fraction, round-trips through `fromisoformat`;
`Z` refuses); `segments == sorted(set(segments), key=SEGMENTS.index)` with
members in `SEGMENTS`; `path` a normalized absolute POSIX scalar (checked on
every row; only selected rows must match the independent origin); each line must
equal `json.dumps(row, sort_keys=True) + '\n'`; URLs strictly increasing; the
row file is exactly one such line. Unselected rows are preserved diagnostic
metadata: fully parsed, never opened, no payload claimed.

**Binary guard.** `Resolver.read(ref, reject_structured=True)` refuses payloads
whose first non-whitespace byte is `{`, `[` or a UTF-8 BOM; it is applied to
raw/original/VR/native binary edges only. Existing schema-less opaque `.txt`
identity leaves are unchanged baseline behavior, not newly admitted provenance.

**Evidence.** tests/gis/test_coast_raw_provenance.py builds the graph from REAL
`prefetch.load_plan`/`stamp`/`Prefetch.flush_manifest`, REAL
`vr_refinements.emit` on an owned synthetic BAG (three non-identical GeoTIFF
outputs plus the supergrid table and a GDAL `.aux.xml`), REAL
`catalog_bridge.native_job`/`dry_run` and REAL Store/Coordinator acquire ->
qualify -> map, then a real producer admission that pins the envelope (P6 BAG
branch; the execution graph exercises the GTiff branch). Non-GIS grammar tests
live in tests/unit/test_coast_raw_grammar.py. Exit 0 remains REVIEW REQUIRED.

## Evidence and fixture compatibility

The native GIS test runs real synthetic GeoTIFF observation/qualification/mapping
algorithms and real Store/Coordinator claim+job serialization for three stages.
Its in-process dispatcher is not a qualified subprocess supervisor, and its empty
stdout/stderr fixtures are explicitly synthetic. No network/source download,
real queue/cache/raw writes, model endpoint or publication occurs. Generic shared
validation traverses this graph, plus actual campaign/admission producer JSON.
Missing/changed input, wrong contract, extra path, cross-root Ref, result identity,
normal historical corruption and renamed unsupported JSON all refuse.

#822's old sign-off fixtures dropped raw root bindings and mutated corrected
admission grids into unreleased pre-#820 shapes. They now use real 1..4-source
catalog_bridge plans/dry receipts and preserve raw bindings. No-GIS core CI
collects them and skips the native integration without pyproj. The six 0/1/4/16
sampling populations remain tested directly in shared sampler tests; sixteen
jobs in a single MAX_JOBS=4 producer plan are NOT manufactured. Four-source
sign-off integration tests retain sample tampering, r1/r2 immutability, corrective
verdicts, metrics and ledger checks without loosening the producer cap.

Exit 0 always means structurally self-consistent/review-required, NEVER semantic
acceptance, raw/derived equivalence, archive verification or release permission.
