# Shared coastal pipeline contract

The implementation is `skippercast.coastal`. Use the reviewed package and existing approved environment under the repository dependency policy. Skill scripts are compatibility entry points, not separate scientific implementations. Package resources include schemas and the pinned whole-ping GSF adapter. Do not install services or change isolation, access, credentials or model routing as part of a run.

## Canonical source and installed mirrors

The reviewed GitHub repository `Grahammmm/skippercast` is the single development
source for these skills:

- `skills/skippercast-discover-coastal-sources/`
- `skills/skippercast-map-coast/`
- `skills/skippercast-render-coast-3d/`

Develop changes in an isolated repository branch, using the existing coordinator
backlog and exact file ownership. Obtain independent review and use the designated
publisher for normal protected-branch integration. A local installation, newer
file timestamp, unmerged branch or stale host checkout is not a replacement for
the approved source revision. All three skills share this contract; do not create
another implementation or tracker for an installed copy.

Installed directories such as `~/.codex/skills/<skill-name>/` are execution
mirrors. Before a run, bind their actual file hashes to the selected reviewed
commit, tree and repository paths. Record the runtime/package identity separately;
matching skill text alone does not establish native or rendering acceptance.
If local content differs, preserve it and reconcile useful changes through the
same repository review flow before synchronization. Do not overwrite unreviewed
customizations or treat them as accepted source.

The assigned installer records a new, immutable installation manifest with the
approved commit/tree, source paths and hashes, installed destination, exact
preimages/postimages and per-file metadata. Preserve observed permissions,
ownership and relevant platform metadata, and verify unchanged unowned files.
Keep backups and earlier receipts; do not rerun an old installer against new
inputs. A successful synchronization means the installed bytes match that
approved revision, with any preserved metadata differences explicit.

## Evidence and stages

The host coordinator stores geographic EPSG:3310 segments in SQLite, with fenced leases and input/code/dependency/parameter identities. Asset hashes identify bytes, not geographic segments. A bounded invocation is a command, not a persistent service:

```sh
python -m skippercast.coastal.cli --root REPO --db var/coastal/coordinator.sqlite status
python -m skippercast.coastal.cli --root REPO identity
```

These inspection commands do not create a queue, enqueue, recover or dispatch
workers. Identity reports actual imported code and packaged schema bytes,
distribution metadata when present and dependency versions when available. It
does not certify an installed wheel, native-library usability or real output.
Keep its machine-local paths in the private run receipt. A source-checkout
invocation is not installed-package acceptance.

The coordinator's existing dedicated source-free launcher is
`python -m skippercast.coastal.coordinator.source_free`; its command syntax and
preconditions are described in the [private terrain runbook below](#private-terrain-runbook).
The generic `coastal.cli enqueue` and `coastal.cli run` examples formerly shown
here had no matching module and are not execution routes. Use a reviewed,
bounded run specification and the current policy before enqueueing. Preserve the
mission allowance across retries. The fixed stage dispatcher accepts
authenticated job files; never introduce caller-supplied executable commands.
An expired lease is not proof that its process stopped. Resolve uncertain
process identity before retrying.

The initial coordinator lane is `discover -> acquire -> qualify -> map -> render`. Here discovery inspects a supplied frozen local catalog; acquisition verifies existing cached bytes. Receipts must say that no external request or transfer occurred. External finite discovery/acquisition use the existing host-side bounded discovery procedure and approved endpoints; the isolated worker remains network-restricted. Do not label cache reuse as a new public search or imply all catalogs were examined.

A mapping-input v2 producer reopens native data and binds the bounded window, geographic support, metadata, rights, implementation and dependencies. Its verifier recomputes facts. Independent review is a separate byte-bound attestation with identity and expiry; it is not cryptographic proof of independence and cannot override a scientific hold. Never author factual observations merely to make readiness pass.

Source sign, units, datum and scale/offset are explicit. BAG elevation storage is positive-up even when a depth coordinate axis is down. Normalized terrain is positive-down metres with scale/offset already applied; do not negate it again. Unknown or conflicting semantics stay held. Preserve nodata and unsupported holes. BAG node footprints do not demonstrate continuous measurements between nodes. Derivatives require supported native spacing and geometry.

Render v2.1 distinguishes private-preview readiness from website acceptance. It requires supported terrain, rights-cleared imagery, numeric alignment with source-bound independent correspondence evidence, and separate review. Coordinate transforms alone do not prove image alignment. Geometry and texture must preserve unsupported regions; interpolation between observed nodes is visualization, not newly measured terrain. Missing imagery holds this paired-imagery lane. A separately assigned data-only
terrain preview follows its reviewed terrain-only contract and keeps imagery,
habitat and website acceptance separate.

## Runtime and preflight

Use the shared bounded runner: an independent supervisor, process identity and actual cleanup enforce deadlines. An environment variable or written deadline alone is insufficient. Keep unavailable model usage unknown and accounting conservative when receipts are incomplete. Preserve immutable bounds and stop on uncertainty instead of resetting reservations.

The historical `skippercast.coastal.hermes_preflight` example has no module in
the accepted source tree. Do not invoke it or treat a substitute command as a
passed preflight. An optional agent gateway is not required for the standalone
source-free route. Host imports, fixture reads, cancellation and artifact
roundtrips establish only host evidence. Actual protected gateway invocation and
external artifact return, when requested, need evidence from that runtime and
the applicable explicit approval. Keep the durable coordinator outside a
temporary gateway. A caller-provided context label cannot establish readiness.

## Trial and audit

Finish implementation, independent correctness/science review and any
applicable explicitly requested security review before a timed trial. Do not
start an optional security workflow merely because a private terrain task exists. First run a synthetic dataset through discovery, mapping and actual rendering, retaining deliberate mask holes and known alignment offsets. Label synthetic review packets and fixtures; never reuse them for a real source. Check every prerequisite for each authorized bounded real stage. If a gate is missing, save the hold and stop that dependent stage; do not replace evidence with a manually written receipt.

Record exact head, source/dependency identities, stage attempts, effective bounds, actual/unknown usage, outputs, independent review, cleanup and next action. Keep private receipts and bulky data outside version control. Private preview does not authorize merge, public upload, website integration or deployment. Skill corrections belong in a separate reviewed implementation revision, not in a running timed mission.


## Operating modes and bounded trial lessons

Choose a mode from the owner's requested output, and retain all its real gates:

| Mode | Required evidence | Separate downstream scope |
| --- | --- | --- |
| Private data-only terrain | Exact source/window, valid paired support, resolved storage/normalization semantics, geographic checks, private-use rights and independent science/artifact review | Imagery, habitat interpretation, rankings, fishing export and publication are optional only when requested |
| Paired terrain/imagery | Reviewed terrain plus imagery rights, independent numeric correspondence and the paired contract's review | Coordinate transforms alone cannot establish alignment or website acceptance |
| Habitat or publication | Requested interpretation/ranking and the applicable source, screening, rights and release contract | Terrain alone establishes neither habitat/substrate nor public permission |

Nominal MLLW with unknown realization stays explicitly nominal; do not invent a
realization, uncertainty calibration, VDatum transform or navigation claim.
Unknown datum realization differs from unresolved sign/units/scale semantics,
which must still hold normalization. Source positive-up BAG elevation and
normalized positive-down depth are different fields; never apply the sign twice.

**Check geometry before source admission.** A historical interest/hard-bottom
polygon is a study constraint, not NOAA's exhaustive bathymetry coverage. Its
failure to cover a proposed square does not prove source nodata. Use retained
actual affine, grid dimensions, native cell outer bounds and full or independently
reviewed conservative geometry (including holes) to test every window and margin
without reopening source arrays. Compare proposed area to the study polygon's
capacity before promising a contiguous square. If a different contained or
disjoint configuration is authorized, pin it as a distinct finite profile; never
relax a geofence, substitute its bounding box or relocate windows silently.

**Admit the complete stage, then launch.** Preparation must return success and
validate exact packet count/order/window membership, producer references,
independent reviews, code/dependency pins and the stage's resource envelope.
Failed preparation means do not launch, even when a downstream count guard would
refuse it safely. The reviewed strict bounded BAG profile requires every
side-squared raw/mask/source/normalized pair and its depth/uncertainty criteria;
missing one pair remains a factual hold. Synthetic tests and metadata alone do
not establish actual support. Independent review of registered observations and
qualified arrays remains separate from worker completion.

**Keep resource scopes distinct.** Preserve the old charged ledger and all
original receipts. An explicitly new source-volume grant is not a refund or a
physical-I/O quota. Record original source bytes streamed/hashed, sealed-copy
hashes, logical pair visits and retained regular output bytes separately, with
unknown physical I/O/disk-quota measurements left unknown. A 64 MiB output cap
cannot stand in for a source-read allowance. Reserve the complete retained stage
tree before dispatch and audit it before result commitment. A 60-minute stage or
combined acquisition/qualification ceiling is not padding: use its original
immutable mission clock, stop when the finite batch ends and authorize no extra
phases merely because time or allowance remains. Report service-unit elapsed time,
worker-supervised time and review/coordination elapsed separately.

**Measure from existing artifacts.** Verify prior/current support hashes and
compute native-grid or consistently projected mask unions without new source
acquisition or a code change solely to claim growth. Deduplicate old/new windows;
prove zero overlap rather than assuming it. Report nominal native-cell area and
equal-area projected area with their method/tolerance. Disjoint measured cores
supply neither the area of their bounding box nor continuous seam/context support.
A schema fix, pretty image or successful job adds no measurement by itself.

**Preserve provenance through source-free recovery.** Validate the original full
BoundCRS source/target/operation first, then canonicalize the physical projected
CRS of derived acceptance packets when needed by the consumer. Preserve the
original CRS, hashes and unchanged rasters; do not infer a vertical transformation
from a representation fix. Archive immutable failed plan/unit/output receipts
before a distinct bounded recovery using retained qualified artifacts. Do not
edit the frozen native export, reset native charges or reopen the source to repair
a derived metadata/preparation error.

**Name the next actual milestone.** A local catalog stage proves local inspection,
not live official discovery. A private native/map/render trial proves only its
selected artifacts. The next coordinator/producer milestone needs a real bounded
registered handoff and durable recovery evidence; the next map-loader milestone
needs actual support-hole/disjoint-core preservation; the next browser milestone
needs interaction, camera and performance evidence beyond static PNG inspection.
Continue independent authorized source-free work through an unrelated optional
habitat/imagery hold, and stop the dependent stage at a genuine missing gate.
Authenticated native execution can deliberately forbid automatic successors;
separately launched mapping/render controls do not prove an integrated coordinator
pipeline. Audit legacy native adapters for their own sign/datum behavior rather
than inferring they inherit authenticated-worker normalization.

These lessons come from completed bounded real-data and source-free recovery
receipts. Keep their exact paths, hashes, dates, failed-attempt evidence and scope
in the private self-audit/run receipt; examples do not grant current execution,
installation, deployment or publication authority.

## Contributor handoff and production acceptance

The intended experience is a useful, reproducible private terrain preview from
reviewed source cells: choose a finite region, retain the source's real spacing
and holes, qualify depth and uncertainty, map only accepted support, then inspect
the rendered cores at a fixed camera. Discovery leads do not become measured
terrain automatically. Terrain does not establish habitat or paired imagery.
Public fishing layers, interactive website behavior and publication retain their
own contracts.

All three definitions already live under `skills/`:
`skippercast-discover-coastal-sources`, `skippercast-map-coast` and
`skippercast-render-coast-3d`. Reuse their existing references and helpers rather
than creating a second skill bundle. The versioned Mapping definition also
links `references/source-preparation-and-trials.md`; qualify that reference when
comparing an installed skill to the repository.

```mermaid
flowchart LR
  A[Finite source inventory and rights] --> B[Native window and masks]
  B --> C[Independent science acceptance]
  C --> D[Registered source-free mapping]
  D --> E[Private terrain-only preview]
  E --> F[Independent output review]
  Q[SQLite identities, leases, charges and recovery] --- B
  Q --- D
  Q --- E
```

The host owns durable state; the fixed dispatcher runs bounded workers. An
accepted native producer can supply a registered retained qualification to the
source-free bridge. That bridge must preserve original-source isolation and
science/review lineage. This is architecture, not evidence that an integrated
production mission has run.

### Current proof and missing evidence

At historical source `1a450b9866081a17be54aea5673b2f1de53f019f`, the prior
[PR657](https://github.com/Grahammmm/skippercast/pull/657) integration and
[PR660](https://github.com/Grahammmm/skippercast/pull/660) terrain-only admission
repair are reusable. Their retained reports describe 54 tests/65 subtests and
32 synthetic/admission cases respectively. Those reports do not establish the
current installed package. New private evidence below records an immutable
real-data handoff and completed terrain-only previews, not production acceptance.
[PR738](https://github.com/Grahammmm/skippercast/pull/738) merged as
`050b242f410f53152ba8da2dfeaab2ade22e7d9a`; site CI/deployment and installed
runtime equivalence remain separate evidence.

Evidence snapshot: 2026-10-20. All real-data records below are PRIVATE,
`publication_prohibited`; pending-science map outputs remain pending-science
unless a separately cited science review accepts the exact packet. Paths beginning
`outputs/` are relative private-store locators, not files shipped in Git. Hashes
are SHA256 prefixes (12 hex), recomputed from the retained bytes for this update.
Machine-valid output remains review-required, not semantic acceptance.

- Six four128 attempts on H11952: attempts 1-5 failed/held with preserved receipts
  and no refunds; attempt 6 completed acquire/qualify/map at `ed28dc69` with four
  pending-science cores. Receipt: `outputs/t08-four128-20261019/receipt.json`
  (`5df6526c28c5`, t_41de4cd3); independent private map validation:
  `outputs/t08-four128-20261019/validation/receipt.json` (`2796e40d8b30`,
  t_b40d52c8), verdict `PASS_PRIVATE_MAP_HANDOFF_PENDING_SCIENCE`.
- Two clean-state acquire/qualify/map reruns completed: run tag `20261020r1`,
  head `292cb0aa`, `outputs/t15-four128-rerun1-20261020/receipt.json`
  (`fad41b67c39a`, t_187849bc); run tag `20261020r2`, head `16418f92`,
  `outputs/t15-four128-rerun2-20261020/receipt.json` (`ddc6845b8158`, t_2e07206c).
  Each charged 294,060,544 source bytes with zero fresh downloads; these outputs
  stop at map, pending-science, not render. Budget chain v2..v6: signed amendments,
  private; preserved failed charges are not renewed allowances.
- Independent rerun validation: `outputs/t15-clean-reruns-20261020/validation/receipt.json`
  (`f3510f03f431`, t_c49a9aa8), verdict `INDEPENDENT_PASS`, 1,154 checks.
  Its per-file determinism results are reproduced below, not flattened to an
  all-files-identical claim.
- T15c-b report: `outputs/t15-clean-reruns-20261020/COAST-PROD-report.json`
  (`490b27d73fc6`) and `outputs/t15-clean-reruns-20261020/COAST-PROD-report.md`
  (`2ef8b989969c`), t_02003ddc (replacement for t_2fd4cbf6). Driver exit 1,
  `NOT_PASS`; dry-run exit 0. Verbatim plan/driver statuses: `01 PASS, 02 PASS,
  03 FAIL, 04 PASS, 05 PASS, 06 PASS`. The report was independently approved for
  accuracy, NOT overall production acceptance.

The plan/report numbers are NOT the same criteria as this skill table: plan 01
is package/import inspection (skill 01); plan 02 is receipt recovery (skill 03),
not installed closure (skill 02); plan 03 is private handoff (skill 04); plan 04
is terrain preview (skill 05); plan 05 is operations tests (partial skill 06);
plan 06 is an archived legacy software-browser view, not integrated operations.
Do not transfer PASS between differently named criteria. Plan 03 remains FAIL:
the driver requires top-level verdict exactly `PASS`, but the two validation
receipts above say `PASS_PRIVATE_MAP_HANDOFF_PENDING_SCIENCE` and
`INDEPENDENT_PASS`. Their qualifiers and citations are preserved, not rewritten
or dropped to obtain PASS.

The acceptance requirements are unchanged: inspection must retain held attempts
and charges and reject absent/corrupt/escaping inputs without worker launch;
installed closure needs canonical/declared-root positive and traversal, symlink,
hash and byte-cap negative consumer evidence. Recovery retains original
window/affine/CRS and raw/normalized lineage. Independent handoff review must cover
support, sign/scale/units, nominal datum, geography, uncertainty and the requested
context/horizon; imagery is optional only for the terrain-only scope. Real
hole/disjoint-core preservation remains an unmet preview requirement, not waived
by these fully supported windows. Integrated operations still needs idempotent
resume, interrupted-worker recovery, child cleanup, artifact return, observable
held/failed states and complete cost/usage bounds for the same mission. Preserve
uncertain processes and terminal failures; no evidence row grants new execution,
account access, retry allowance or public/paired website acceptance.

| Dependency task | Deliverable and inputs | Acceptance and authority |
| --- | --- | --- |
| COAST-PROD-01: inspection interface | `coastal.cli` status/identity and `tests/unit/test_coastal_cli.py`, existing queue/schema/code identity contracts | PRIVATE evidence: plan 01 PASS for staged source-tree checks at `050b242f`, 12 tests per pass; no worker launch, not installed acceptance. No historical T02 JSON receipt: not demonstrated / unknown. Fresh receipts: `outputs/t15-clean-reruns-20261020/driver/run-20261020-t02003ddc/pass-1/receipts/package-check.json` (`153daf7b1b46`) and `outputs/t15-clean-reruns-20261020/driver/run-20261020-t02003ddc/pass-2/receipts/package-check.json` (`f1551501c589`), t_02003ddc. Real-data lane remains publication_prohibited. |
| COAST-PROD-02: installed closure | Actual package/wheel/build, dependency and skill hashes, packaged resources and launcher identity; positive and negative consumer checks | PRIVATE evidence: installed closure not demonstrated / unknown; actual installed-consumer/wheel equivalence receipt missing. Plan 02 PASS is receipt recovery, NOT this criterion. Report citation: `outputs/t15-clean-reruns-20261020/COAST-PROD-report.json` (`490b27d73fc6`, t_02003ddc). Source-tree package tests cannot certify installation; no install is authorized. Real-data lane remains publication_prohibited. |
| COAST-PROD-03: recover retained real inputs | Original mission/checkpoint, windows, masks, raw/normalized pairs, rights, derived outputs and complete charged ledger; separate independent science attestation | PRIVATE, publication_prohibited, pending-science recovery evidence: plan 02 PASS for 18 intake tests and 8 operations tests per pass plus 43 receipt checks and 8+8 settled admissions. No historical T04/T12 JSON receipts: not demonstrated / unknown. Fresh intake receipts: `outputs/t15-clean-reruns-20261020/driver/run-20261020-t02003ddc/pass-1/receipts/t04-intake-tests.json` (`90dd447bb883`) and `outputs/t15-clean-reruns-20261020/driver/run-20261020-t02003ddc/pass-2/receipts/t04-intake-tests.json` (`70691d70674f`); verification receipts: `outputs/t15-clean-reruns-20261020/driver/run-20261020-t02003ddc/pass-1/receipts/rerun-receipt-verification.json` and `outputs/t15-clean-reruns-20261020/driver/run-20261020-t02003ddc/pass-2/receipts/rerun-receipt-verification.json` (both `3c49b8024223`), t_02003ddc. Operations pins are below. Retained real-input/ledger validation: `outputs/t15-clean-reruns-20261020/validation/receipt.json` (`f3510f03f431`, t_c49a9aa8). No source reopening to reconstruct missing evidence; machine checks do not supply science acceptance. |
| COAST-PROD-04: private handoff | Native/result identity and exact source-free plan, registered arrays, terrain-only input and independent science/artifact review | PRIVATE, publication_prohibited: original pending-science validation `outputs/t08-four128-20261019/validation/receipt.json` (`2796e40d8b30`, t_b40d52c8), verdict `PASS_PRIVATE_MAP_HANDOFF_PENDING_SCIENCE`; plan 03 FAIL remains as explained above. Separately accepted T13 packets/reviews are pinned below (t_d433a9bc), not a retroactive relabeling of the original handoff. terrain acceptance PASS on 128x128 four128 output; holes N/A on these windows; live hole/disjoint-core preservation NOT demonstrated (0 unsupported cells by the 2026-10-19 21:10 window selection); demonstrated only on the synthetic cores of research/tests/gis/test_check_terrain_acceptance_render.py at #739 da55d1e88. |
| COAST-PROD-05: real preview | Accepted T13 terrain bytes, pinned loader/renderer, finite private reservation and independent fixed-camera inspection | PRIVATE, publication_prohibited: `outputs/t13-four128-terrain-acceptance-20261020/t13-receipt.json` (`d80ecebab980`, t_189fbd03), PASS, 4 cores, 0 held, generated `2026-10-20T07:18:22Z`, renderer `ed28dc69`, checker from #739. Opus vision review completed/approved on t_189fbd03: all four full-resolution previews and read-only depth/seam/georeference probes found no defects. terrain acceptance PASS on 128x128 four128 output; holes N/A on these windows; live hole/disjoint-core preservation NOT demonstrated (0 unsupported cells by the 2026-10-19 21:10 window selection); demonstrated only on the synthetic cores of research/tests/gis/test_check_terrain_acceptance_render.py at #739 da55d1e88. Not habitat, imagery, website or renewed execution acceptance. |
| COAST-PROD-06: integrated operations | Same mission/queue, accepted outputs, original charges, supervisor, resume/recovery/cleanup/artifact-return and cost-stop evidence | PRIVATE, publication_prohibited, rerun outputs pending-science: literal integrated pipeline not demonstrated / unknown; runnable discover bridge and rerun render-handoff manifest missing. Bounded plan 05 PASS: 8 operations tests, 0 skipped per pass; `outputs/t15-clean-reruns-20261020/driver/run-20261020-t02003ddc/pass-1/receipts/t12-operations-tests.json` (`77dce430a316`) and `outputs/t15-clean-reruns-20261020/driver/run-20261020-t02003ddc/pass-2/receipts/t12-operations-tests.json` (`1209f15224fb`), t_02003ddc. No T12 CI JSON receipt: not demonstrated / unknown; these are test runs, not CI-run proof. Rerun receipts `outputs/t15-four128-rerun1-20261020/receipt.json` (`fad41b67c39a`, t_187849bc) and `outputs/t15-four128-rerun2-20261020/receipt.json` (`ddc6845b8158`, t_2e07206c), independent validation `outputs/t15-clean-reruns-20261020/validation/receipt.json` (`f3510f03f431`, t_c49a9aa8), and report `outputs/t15-clean-reruns-20261020/COAST-PROD-report.json` (`490b27d73fc6`, t_02003ddc) document the limits and determinism below. |

T13b-2 science acceptance (t_d433a9bc) is limited to these H11952 windows,
each 128x128: A `[3762,3488]`, B `[3890,3488]`, C `[3762,3360]`, D `[3890,3360]`.
Source/renderer lineage is `ed28dc69`; review ran at `292cb0aa` with relevant
terrain code verified unchanged. All packets are PRIVATE, `publication_prohibited`;
each review expires on 2026-10-22 at approximately 07:09:43Z. These historical
acceptances do not grant a future execution/review horizon.

| Core | Acceptance path and SHA256 prefix | Science-review path and SHA256 prefix |
| --- | --- | --- |
| A | `outputs/t13-four128-terrain-acceptance-20261020/core-A/acceptance.json` (`b0541830a9f0`) | `outputs/t13-four128-terrain-acceptance-20261020/core-A/science-review.json` (`86a567766fbb`) |
| B | `outputs/t13-four128-terrain-acceptance-20261020/core-B/acceptance.json` (`ff2b98370be0`) | `outputs/t13-four128-terrain-acceptance-20261020/core-B/science-review.json` (`c457b57b4bf6`) |
| C | `outputs/t13-four128-terrain-acceptance-20261020/core-C/acceptance.json` (`ec482896f6d3`) | `outputs/t13-four128-terrain-acceptance-20261020/core-C/science-review.json` (`7bbb3935aaef`) |
| D | `outputs/t13-four128-terrain-acceptance-20261020/core-D/acceptance.json` (`b833919c882a`) | `outputs/t13-four128-terrain-acceptance-20261020/core-D/science-review.json` (`cbe28006e727`) |

Rerun 1 vs rerun 2 determinism, exactly as T15-VAL-b (t_c49a9aa8) reports:
12 equal, 4 different of 16. The 12 GeoTIFFs are byte-identical. Each of the four
`acceptance-pending-review.json(facts)` comparisons differs only in
`provenance.upstream_receipt_sha256` (per-run binding, not terrain content).

| Window (x, y, width, height) | mask.tif | terrain.tif | uncertainty.tif | acceptance-pending-review.json(facts) |
| --- | --- | --- | --- | --- |
| [3762,3488,128,128] | equal | equal | equal | different: provenance.upstream_receipt_sha256 |
| [3890,3488,128,128] | equal | equal | equal | different: provenance.upstream_receipt_sha256 |
| [3762,3360,128,128] | equal | equal | equal | different: provenance.upstream_receipt_sha256 |
| [3890,3360,128,128] | equal | equal | equal | different: provenance.upstream_receipt_sha256 |

Remaining gaps: discover is a zero-network dry-run from unmerged #734, not a
runnable discover-to-coordinator bridge at any cited head (T15a t_2da6ffcf).
The side=32 native chain is snapshot-only, not exercised on main. Both four128
reruns stop at map; no render-handoff manifest exists. T13 independently rendered
separately prepared attempt-6 cores; T15c only re-verified those renders read-only,
not rerendered the rerun outputs. Literal discover -> acquire -> qualify -> map ->
render from clean state twice is NOT demonstrated. Plan 06 PASS covers only the
approved legacy software-render browser archive (t_fe397592), not current-main
browser/GPU acceptance; GPU qualification remains HELD. A live hole-bearing
window run is future separately admitted work, not covered by these receipts.

Use these task IDs in contributor issues and PR descriptions. They are dependency
labels, not already-open issue numbers or assigned authorizations. Existing
reviewers and publisher serialize exact scopes; this document grants neither
account access nor a new retry allowance.

### Private terrain runbook

1. Recover original immutable receipts before any run. Match the native producer,
   source-free mapping plan and independently accepted terrain-only packet to the
   same window/support identities. Keep actual storage paths and precise private
   geometry outside Git. Do not infer support from a survey envelope or sum
   overlapping windows.
2. Inspect code/package identity and the existing queue using the commands above
   in the already-qualified environment. `metadata_found: false`, missing native
   dependencies or a mismatched skill/entrypoint remains a qualification gap.
   Record source-checked, packaged, installed and runtime-accepted separately.
3. For a separately admitted retained source-free mission, the existing launcher
   accepts `--root ROOT --database ROOT_RELATIVE_DB status`; its `import`
   operation requires `--source-root`, `--source-db`, `--plan` and
   `--deadline-epoch`; `enqueue` requires `--manifest` and `--index`; `run`
   requires `--deadline-epoch` and an explicit finite `--max-jobs` of at most
   three. These are syntax references, not instructions to launch a held mission.
   Do not point a new command at an old exhausted queue to create fresh attempts.
4. Keep the accepted original database/output receipts closed and recoverable.
   The existing source-free import/recovery contracts reject unresolved WAL or
   journal state and require producer/result and stopped-process proof. An
   uncertain worker is not retried merely because its lease expired.
5. Preserve masks, raw/normalized lineage, uncertainty semantics and nominal
   datum limitations. Render only the explicitly accepted slices. Record the
   preview and independent review; a PNG alone does not prove interaction,
   cgroup containment, reboot recovery or installed equivalence.
   The existing private preview module is
   `python -m skippercast.coastal.render.terrain_only`, with required `--root`,
   `--acceptance` (the independently accepted JSON packet) and `--output-dir`
   arguments. Its optional `--context-only` only prints a review context; it
   neither approves science nor renders. Prepare the exact packet and review
   horizon before any separately authorized preview. A standalone map followed
   by a standalone preview is not an integrated coordinator acceptance run.
6. Retain original charges and immutable failed receipts. Roll back a proposed
   source change by omitting/reverting that reviewed delta, never deleting source
   originals or resetting a terminal mission. Review current state before any
   supported recovery. Do not deploy a data preview as a public map.

### Reproducible synthetic inspection checks

In the existing approved Python 3.11+ test environment, the focused suite is:

```sh
python -m unittest -f tests.unit.test_coastal_cli
```

It uses only temporary synthetic queues, existing package resources and module
inspection. It never dispatches native, mapping or rendering jobs. It also
checks the module entrypoint from an artifact directory. Running it against a
source checkout proves that mode only; it does not build/install a wheel or
establish native rendering. The normal PR suite still applies. No dependency
installation or new CI workflow is introduced here.

### Public evidence manifest and source retrieval

Publish code, synthetic fixtures, evidence summaries and public PR/run links.
For a real-data handoff, record source identifier and official retrieval URL,
retrieval date, reviewed rights, expected byte count/hash, producer code and
dependency pins, window/support identity, normalized output hashes, review
identity/context/validity and original charge totals. Separate reported values
from locally byte-verified values. Never commit credentials, exact private cache
locations, restricted datasets or sensitive operational details.

For example, the retained public-source assertion for NOAA H13323 identifies
`H13323_MB_VR_MLLW.bag` at
`https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H12001-H14000/H13323/BAG/H13323_MB_VR_MLLW.bag`,
with reported source SHA256
`a7a10f65bed5ad18d06711ec30f935d373a3ec7c8a0d09f24e177721d36ba96c`.
This is a retrieval/hash reference, not a download instruction, a current rights
review or an independently verified window/output. Large source bytes stay in
the approved private artifact store; authorized contributors obtain them through
the owner-approved retrieval route. Missing receipt fields remain missing.

The following source-preparation manifest binds the focused synthetic check only.
Its source hashes can be compared with the owning PR; it contains no private run
locators and makes no real-data acceptance claim.

```json
{
  "schema": "coastal-source-preparation-evidence-v1",
  "date_utc": "2026-10-18",
  "accepted_base": "1a450b9866081a17be54aea5673b2f1de53f019f",
  "source_files": {
    "src/skippercast/coastal/cli.py": "8e18b824d98568b858722eef45eb292883f8c0d5ae5f274ca58c476f9e95fe2e",
    "tests/unit/test_coastal_cli.py": "ceffc584a478f092f03e856bc8b2fb083a5aa55eb9220693a9a1c2e5dc331d95"
  },
  "focused_check": {
    "command": "python -m unittest -f tests.unit.test_coastal_cli",
    "python": "3.11.16",
    "mode": "source-checkout; not an installed distribution",
    "tests": 12,
    "result": "PASS",
    "worker_dispatches": 0
  },
  "installed_package_acceptance": "UNVERIFIED",
  "native_acceptance": "NOT_RUN",
  "render_acceptance": "NOT_RUN",
  "authority": "source preparation and synthetic checks only; no exhausted cycle renewed"
}
```
