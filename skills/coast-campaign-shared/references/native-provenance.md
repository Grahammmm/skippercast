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
Rights evidence is an explicit closed `coast-native-rights-evidence-v1` statement
receipt with the common runtime header and synthetic flag, not a rewrite or
semantic approval of a legacy legal document. Existing other evidence contracts
remain held until independently reconciled; do not relabel existing bytes.

Segments support both canonical segment() records (no inverse bbox) and the
from_bbox() records (inverse bbox checked). mapping_input.bind_segment's inline
boundary-policy/halo/intersection/outside-support fields are explicitly admitted.
Admission still requires the full campaign-generated inverse-bbox record.

## Precisely held provenance (never silently dropped)

* Any nonnull source_row (inline or Ref) or native-facts source_lineage.source_row:
  `held: retained source-row adapter not yet admitted`. Original BAG/source-row
  provenance is NOT claimed covered by the GeoTIFF fixture.
* Schema-less raw-manifest rows/snapshots and non-workflow JSONL snapshots are
  NOT supported by the workflow-ledger JSONL parser. Unknown structured schemas
  refuse. A live append-growing manifest is not an immutable input. Do not rename
  JSON/JSONL to opaque text or omit it; B1d must hold that graph until the exact
  source-row/snapshot adapter is admitted.
* Cached derived inputs requiring external derivation receipts (including
  VR-BAG-derived GTiff) are HELD. Adding derivation/raw_manifest_snapshot slots to
  a native manifest refuses as unknown producer fields; unknown derivation
  schemas refuse when reached through a workflow Ref. A hash-matched GTiff alone
  is not a claim that its upstream derivation/raw closure is complete.
* Authenticated/source-free/managed-output Store lanes, discover/render jobs,
  nonempty execution params, renderer handoffs/thumbnails and new native output
  schemas require separate adapters and currently refuse. No executable intent,
  scratch, live SQLite or lease document is automatically trusted.

These holds mean this pin is NOT universal archive closure for the real coast.
B1d must retain the admitted complete subgraph and refuse any held provenance,
not report an archive success that silently omits it. Archives, raw-equivalence,
lineage snapshot generation and release gates remain B1d's responsibility.

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
