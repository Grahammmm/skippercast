# SC-4: coastal snapshot port-or-retire inventory

Date: 2026-10-20. Task: `t_583cd0cf`. Status: proposed dispositions,
**review required**; no runtime code ported, removed, or executed.

## Scope and evidence

The source is the retained `work/source-reuse-admission-20261011` checkout,
located through the T08-FIX task `t_e210296e`, not an assumed Git tag. Its
uncommitted source bytes are the authority for this comparison. The comparison
baseline is main at `bde9c6dff45dfdf7b813ee217f0bfde058d4b274`; a later merge
requires a new comparison, not a silent change of this baseline.
During review rework, main advanced to `10ea2783f93099bb487d77f4cdfea9db084696e6`
(Grahammmm/skippercast#734 merged). A second source census at that revision
matched the pinned inventory exactly apart from `main_revision`; the historical
baseline remains unchanged. Main-only additions are not snapshot-only paths.

This implements Fable audit S1 / Part 2 SC-4 (audit SHA256
`41fdd644cefe0138ecd6fdb6cc734b56054bf3cc0d488c3e927a40f84595e842`).
The audit's approximate “17–25” is resolved here into explicitly scoped counts,
not a claim that the whole snapshot contains only 17 absent Python files.
The coastal package census recursively compares `src/skippercast/coastal/**/*.py`,
including initializers, against the pinned Git tree: **68 files, comprising
17 absent paths, 31 byte-identical paths, and 20 differing existing paths**.
SC-4 does not inventory function-level drift within those 20 existing paths;
they are not ports authorized here.

A supplemental absent-path census scans Python files under `src/`, `scripts/`,
`skills/`, `research/`, and `tests/`, excluding `.git`, `.venv`, `__pycache__`,
`node_modules`, and `var` directories. It finds **3 additional non-test modules,
78 test/fixture files under tests/, and 1 research test**: **99 snapshot-only
Python files** across the admitted scopes. It does not scan arbitrary snapshot
root directories or count C/JSON resources as Python modules.

[Machine-readable evidence](coastal-snapshot-2026-10-20.json) records all 68
paths, byte counts and full SHA256s on both sides, the sorted snapshot-source
manifest digest, six existing skill-script counterparts, and separate path,
byte-count and SHA256 lists for all 3 supplemental modules, all 79 test/fixture
files, the Hermes adapter's `SKILL.md`, and snapshot-only packaged resources.
The resource list is dependency context, not an instruction to copy them.
Resources are assumed flat; a missing directory, nested directory or symlink
fails closed rather than silently omitting dependencies. The snapshot path
label alone is not an integrity pin; the per-file hashes are. Only source,
test, documentation and resource files were read: no
survey bytes, mission databases, canonical ledgers, or live receipts.

Definitions:

- **needed-by-stage**: retain a capability/consolidation candidate for the named
  stage. This is not a mandate to copy the snapshot implementation. Reconcile
  with the existing owner and implementation first; conditional GSF work is
  not a prerequisite for a BAG-only mission.
- **retire**: remove this *snapshot source path* from the phase-4 port queue.
  Preserve the snapshot, historical receipts and existing skill helpers. This
  does not delete code or declare unrelated broader-source/browser use cases
  complete; explicit future scope may reopen a row.
- All dispositions are proposals for independent review, not scientific,
  installed-runtime, execution, or publication acceptance.

## Coastal package disposition table

Snapshot anchors below are relative to `src/skippercast/coastal/` in the
hash-pinned snapshot. Main anchors refer to the baseline above. Each absent
module appears exactly once.

| Snapshot module | Disposition | Stage / reason and main alternative or follow-up |
| --- | --- | --- |
| `asset_selection.py` | retire | Discover → acquire: preserve `select` (100–160) as SC-3 design evidence for exact asset, coverage and resolution screening, not a second selection service. Its v1 handoff explicitly sets `historical_only=True` and `current_pipeline_ready=False` (217–224); its v2 verifier delegates to main `handoff/mapping_input.py` (227–233). SC-3 must implement the frozen-catalog bridge; retirement does **not** claim that bridge exists. |
| `bottom_float32.py` | retire | Map → browser export: optional schema-2 bottom encoding, not the private terrain renderer. The authenticated lineage requires all `side²` pairs valid, zero invalid pairs (71–101), and `valid.all()` (198–200); do not port it as a solution for SC-5 holes. Main `render/terrain_only.py` consumes retained mask/terrain packets. Re-admit a separately tested browser exporter only if requested; no browser equivalence claimed. |
| `coordinator/authenticated_cli.py` | retire | Acquire / qualify orchestration: `policy_for` (26–36) already has an explicit port in main `research/scripts/coastal_four128_runtime.py:29–43`; execution uses the ordered controller and dedicated launchers, not this parallel prepare/phase1/phase2 CLI. Preserve original driver identity for historical receipts. |
| `discover.py` | needed-by-stage | Discover: finite network acquisition and frozen catalog capability, not covered by main's metadata-only `governed_discovery.py:73–105`. Reconcile with SC-2 / Grahammmm/skippercast#734, then SC-3, rather than opening a competing discovery port. Main already tracks an older skill `scripts/discover.py`; snapshot `finalize` (649–687) binds quality attachments and keeps mapping unaccepted. Missing package path is not absence of all discovery code. |
| `formats.py` | needed-by-stage | Acquire / sample observation, **conditional GSF/gzip lane**: pinned reader and bounded expansion (`preflight`, 23–41; `inflate`, 44–62; `inspect_gsf`, 65–101). Reconcile with the tracked discovery skill helper: main expects `gsf-reader-v1` / `gsf_probe.c` at 21–28, snapshot uses v2/resume and pinned `gsf_scan.c` at 28–36. Not required for the authenticated BAG path; native units/datum/support remain separate evidence. |
| `gsf_resume.py` | needed-by-stage | Acquire / sample observation, **conditional GSF continuation**: durable replay/byte reservations and stopped-process recovery (119–189). `finalize` explicitly leaves source qualification unaccepted and render blocked (193–205). Reconcile the existing skill helper, `formats.py`, `holds.py` and packaged reader/schema resources together only when a GSF source is admitted. Not a BAG or SC-5 dependency. |
| `hermes_client.py` | retire | Optional agent-facing enqueue/sign-review client (395–450), not a required pipeline stage. Main `cli.py:1–5` deliberately exposes inspection without mission execution; use existing dedicated source-free/authenticated launchers and review gates. A claimed review or queue mutation must not be restored merely by porting an unused client. |
| `hermes_preflight.py` | retire | Optional host/gateway qualification: `collect` reports isolated worker readiness false and external return unverified (130–219). The main shared contract explicitly excludes this absent command (coastal-pipeline reference, 78–85). Main inspection and SC-6 installed-closure evidence are the current routes; neither establishes actual gateway qualification. |
| `holds.py` | needed-by-stage | Qualify/sample observation, **conditional GSF helper only**: nine-line classifier differentiates no pings, partial/eof navigation selection and invalid depths; imports are from snapshot `formats.py` and `gsf_resume.py`. Port/reconcile only with that pair to avoid inconsistent hold semantics. No geography or whole-survey quality claim. |
| `legacy_cache.py` | retire | Historical v1 seafloor-cache lookup (`legacy_inputs`, 16–28; `legacy_cached`, 36–85), not current authenticated qualification. It keys old implementation hashes and verifies old COGs without running the adapter. Keep historical bytes; main retained-input recovery/source-free registration is not replaced with a v1 fallback. Reopen only for an explicitly admitted legacy-cache migration. |
| `native_raster_v2.py` | retire | Acquire / normalize, companion to `native_v2.py`: bounds/chunks/native window helper (28–97), not imported by the main BAG worker. Keep for a future separately admitted original-raster adapter review; main `authenticated_v1/adapter_bag.py` plus mapping/vertical contracts own the bounded BAG lane. Do not interpret this as qualification of arbitrary GeoTIFF/ArcGrid sources. |
| `native_v2.py` | retire | Acquire / normalize: parallel source-fetch → `vertical-v2` COG cache writer (27–38, 73–93), not the sealed authenticated worker. ArcGrid is explicitly held (37–38). Preserve as a future non-BAG adapter candidate, but do not port another fetch/cache path to prove the existing BAG chain. Main `authenticated_v1/worker.py` / `adapter_bag.py` remain the native route. |
| `quality.py` | needed-by-stage | Discover → sample observation: source/hash/expiry-bound quality attachments (349–384) and supervised finite inspection (387–489). Reconcile the tracked discovery skill helper and `discover.py`; do not replace accepted mapping-input verification with sample observations. `inspect_native` supports local GeoTIFF and explicitly holds BAG (181–228); GSF uses `formats.py`. Thus this is not missing BAG science acceptance. |
| `render_batch.py` | retire | Render orchestration: older four-core derived-batch wrapper (14–35) with optional retention (43–50). Main `render/governed.py:427–486` already validates completed source-free derived batches and exact reviewed inputs; `render/terrain_only.py` and the terrain-acceptance research checker own preview evidence. The missing rerun render-handoff manifest remains an integration gap, not a reason to restore a second batch orchestrator. |
| `run_bounded.py` | retire | Cross-stage checkpoint CLI forwarding arbitrary argv to `runner.run_bounded` (127–165). Main has `runner.py`, fixed `coordinator/stages.py:92–95` dispatch, and an existing map skill helper at `scripts/run_bounded.py`. Reconcile helper drift separately if needed; do not restore generic argv execution into the fixed stage lane. |
| `validate_handoff.py` | retire | Optional paired website-display v2 consumer, not the terrain-only SC-5 gate: requires imagery and website-display review (109–135). The tracked map skill `scripts/validate_handoff.py` already implements this legacy consumer; main also has distinct `handoff/render.py` verification. Do not equate those different contracts or port a duplicate solely because this package path is absent. |
| `validate_terrain_display_handoff.py` | retire | Render → website, outside private preview: requires `terrain-display-handoff-v1` schema (22–23) and display rights/loader/accessibility/performance review (197–210); that schema is absent from main package resources. Preserve this candidate with its schema for a separately specified website consumer. Main terrain-only science/render acceptance is not public display acceptance. |

Package totals: **5 needed-by-stage candidates, 12 scoped retirements; 17/17
absent package paths covered** (not function-level coverage).
The five candidates form discovery/sample-observation consolidation work;
three (`formats`, `gsf_resume`, `holds`) are conditional on admitting GSF.
There is no recommendation to copy all five to complete a BAG-only chain.

## Outside the coastal package

These anchors are relative to the snapshot root, not the coastal package.
The supplemental JSON scope reproduces these three missing non-test paths.

| Snapshot module | Disposition | Stage / reason and main alternative or follow-up |
| --- | --- | --- |
| `scripts/build_schema_resources.py` | needed-by-stage | SC-6 installed closure: `build` (12–26) mirrors canonical schemas into package resources; `--check` (29–40) detects drift without writes. Retain as a build-time reconciliation candidate, not proof that main's wheel is closed. Reconcile current schema/resource ownership before any port; carry `tests/contract/test_coastal_package.py:27–57` for byte-exact registry and no-mutation checks. No schema copied or builder executed here. |
| `skills/hermes/skippercast-coastal/tool.py` | retire | Optional Hermes adapter, together with its hash-recorded `SKILL.md`: lines 4–7 call `coastal.cli.main` with `--client`, which pinned main's inspection-only CLI does not expose. Retire alongside `hermes_client.py` and `hermes_preflight.py`, rather than installing a broken adapter or restoring queue/review writes. The skill's lines 8–12 explicitly say uninstalled and require separate access authorization. Preserve both historical files; no profile or gateway changes. |
| `skills/skippercast-discover-coastal-sources/scripts/asset_selection.py` | retire | Compatibility shim (2–6), importing the absent `coastal.asset_selection.main`. Retire together with the package row, not as an independent missing selection capability. SC-3 keeps ownership of the frozen-catalog bridge; retain the shim as historical invocation evidence without claiming its historical handoff is pipeline-ready. |

Non-test totals across both tables: **6 needed-by-stage, 14 retire; 20/20
snapshot-only non-test Python paths covered**. This adds one SC-6 build-time
candidate, not a sixth discovery-family candidate or a new SC-5 prerequisite.

## Test and fixture handoff

The JSON's `snapshot_only_tests` records **78 tests/fixture Python files under
tests/ plus 1 research test**, each with its relative path, bytes and SHA256.
They are retained as source evidence, not copied or run. Many exercise modules
already on main; missing tests are not evidence that their subjects are missing.
The 12 package retirements (14 with the supplemental shims) create no automatic
test-port requirement. They do not authorize deleting any historical tests.

For each of the five package candidates, the following tests must travel with
the capability during reconciliation (port or adapt with equivalent coverage,
not blindly restore obsolete interfaces). Paths are snapshot-root relative.

| Candidate | Required test files | Shared fixture / closure dependencies |
| --- | --- | --- |
| `discover.py` | `tests/unit/test_coastal_source_discovery.py`; `tests/unit/test_coastal_source_quality.py`; `tests/gis/test_coastal_source_formats_native.py`; `tests/gis/test_quality_vertical.py` | `tests/coastal_support.py`; `tests/gis/coastal_native_support.py`; `tests/contract/test_coastal_package.py` |
| `formats.py` | `tests/unit/test_coastal_source_formats.py`; `tests/gis/test_coastal_source_formats_native.py` | `tests/coastal_support.py`; `tests/gis/coastal_native_support.py`; `tests/contract/test_coastal_package.py` |
| `gsf_resume.py` | `tests/unit/test_gsf_resume.py`; `tests/integration/test_coastal_gsf_recovery.py` | `tests/coastal_gsf_support.py`; `tests/contract/test_coastal_package.py` |
| `holds.py` | `tests/unit/test_coastal_source_formats.py`; `tests/unit/test_gsf_resume.py`; `tests/integration/test_coastal_gsf_recovery.py` | `tests/coastal_support.py`; `tests/coastal_gsf_support.py`; `tests/contract/test_coastal_package.py` |
| `quality.py` | `tests/unit/test_coastal_source_quality.py`; `tests/gis/test_coastal_source_quality_native.py`; `tests/gis/test_coastal_source_formats_native.py`; `tests/unit/test_coastal_source_formats.py`; `tests/gis/test_quality_vertical.py` | `tests/coastal_support.py`; `tests/gis/coastal_native_support.py`; `tests/contract/test_coastal_package.py` |

In particular, `test_coastal_source_formats.py:90–121` exercises the shared hold
classifier without native decoding; `test_gsf_resume.py:97–101` exercises its
continuation result. `test_coastal_gsf_recovery.py:16–80` covers parent-loss
recovery without renewing reservations or deadlines. The shared package test
mixes retained and retired CLI cases: preserve applicable resource/CLI checks,
but do not reinstate retired paths just to satisfy its old module list.
`test_quality_vertical.py:8–46` covers unknown vertical sign, conflicting
declared elevation versus a compound depth axis, and recording scale/offset
without applying them. It exercises both discovery and quality and must remain
in both candidates' handoffs; negative values alone do not establish sign.
Also reconcile the existing `tests/_support.py` helpers (`ROOT`, `FakeClock`),
test configuration, versioned schemas, and pinned optional reader dependencies.
Passing an optional-reader absence branch is not evidence of native GSF coverage.

The supplemental `research/tests/test_coastal_four128_runtime.py` is
**needed-by-stage (bounded execution/runtime regression)**: it covers clocks,
finite resource argv, read-only interrupted SQLite evidence and review bindings
(25–134) for `research/scripts/coastal_four128_runtime.py`, already on main.
Retain/reconcile these tests with the current runtime owner rather than treating
them as a missing runtime port or executing the historical harness. This is the
one research-test entry in the JSON, separate from the 20 non-test dispositions.

## Dependency and ownership handoff

1. **SC-2 / SC-3, not a new discovery implementation:** Grahammmm/skippercast#734
   was OPEN at observed head `0b9f0d8869c7e6187f59f353863e2760855c6807` during
   the initial audit and has since merged at the revision noted above; it is
   not evidence in the historical pinned-main census. SC-2 owns the
   governed live discovery route; SC-3 owns the catalog-to-coordinator bridge.
   Use the discovery-family rows to reconcile equivalent capabilities and
   explicitly defer unsupported source formats, not to enlarge their tasks
   silently. `asset_selection.select` is useful design evidence for SC-3,
   whereas its historical v1 handoff is not current readiness.
2. **Port dependency closure matters:** snapshot discovery and quality reference
   each other; formats references discovery, quality and holds; GSF resume
   references formats and holds. The evidence JSON separately lists absent
   packaged schemas/readers. A Python-file-only port could pass a syntax check
   and still fail at runtime. Existing skill assets are not proof of packaged
   resources or installed closure; that evidence belongs to SC-6.
3. **SC-5 immediate BAG scope:** none of these absent package paths is a port
   prerequisite identified by this static audit. Current native, mapping and
   terrain-render modules already exist, but that does **not** prove a
   hole-bearing run can pass. The strict all-pair native profile and its
   admission/policy checks must be assessed by the SC-5 owner; no relaxation is
   authorized here. `bottom_float32`'s all-valid requirements make it unsuitable
   for carrying holes unchanged. SC-5 still needs a separately admitted window,
   valid masks/lineage, independent review and real `--require-holes` evidence.
4. **Phase-4 exit stays open:** no literal clean discover → acquire → qualify →
   map → render rerun was performed here. Retiring duplicate/optional paths
   supplies neither the SC-3 bridge nor the missing render-handoff manifest.
   The shared contract's lines 332–339 retain those gaps. No source acquisition,
   launch, retry, budget renewal, installation or publication is authorized.
5. **Preservation:** the four128 runtime's historical code-root default still
   names this snapshot (`coastal_four128_runtime.py:10–17`). Never delete or
   rewrite it to enact “retire.” Do not rewrite old receipts or silently point
   historical commands at another implementation.

## Reproduction and verification

Run only the source census, not any snapshot module. Set `SNAPSHOT` to the
retained `work/source-reuse-admission-20261011` source checkout:

```sh
python3 -B research/scripts/audit_coastal_snapshot_inventory.py \
  --snapshot "$SNAPSHOT" \
  --main-ref bde9c6dff45dfdf7b813ee217f0bfde058d4b274 \
  --check docs/engineering/audits/coastal-snapshot-2026-10-20.json
```

Expected output:

```text
PASS: source inventory matches; {"different": 20, "identical": 31, "snapshot-only": 17}
Snapshot-only scopes: {"coastal_modules": 17, "outside_package_modules": 3, "python_total": 99, "research_tests": 1, "tests": 78}
```

The script compares actual source bytes with Git objects and emits stable,
host-path-free metadata. The JSON can be reproduced without network access;
the local snapshot is required and absence is an explicit error. Its digest
is an integrity check, not semantic acceptance of the dispositions. Acceptance
also checks unique table coverage against the 20 absent non-test paths, all 79
test/fixture identities, the five candidates' test handoff, counterparty paths
at the baseline, and a documentation/research-only Git diff. Product/GIS
execution and the full app build are not evidence required for this inventory.
