# SC-4: coastal snapshot port-or-retire inventory

Date: 2026-10-20. Task: `t_583cd0cf`. Status: proposed dispositions,
**review required**; no runtime code ported, removed, or executed.

## Scope and evidence

The source is the retained `work/source-reuse-admission-20261011` checkout,
located through the T08-FIX task `t_e210296e`, not an assumed Git tag. Its
uncommitted source bytes are the authority for this comparison. The comparison
baseline is main at `bde9c6dff45dfdf7b813ee217f0bfde058d4b274`; a later merge
requires a new comparison, not a silent change of this baseline.

This implements Fable audit S1 / Part 2 SC-4 (audit SHA256
`41fdd644cefe0138ecd6fdb6cc734b56054bf3cc0d488c3e927a40f84595e842`).
The exact census replaces the audit's approximate “17–25”: recursively compare
all Python source paths in `src/skippercast/coastal/`, including package
initializers, against the pinned Git tree. There are **68 snapshot Python
files: 17 absent paths, 31 byte-identical paths, and 20 differing existing
paths**. The latter are not missing modules and are not ports authorized here.
Skill helpers, C readers, JSON schemas, tests, and research harnesses are not
additional Python modules in this census.

[Machine-readable evidence](coastal-snapshot-2026-10-20.json) records all 68
paths, byte counts and full SHA256s on both sides, the sorted snapshot-source
manifest digest, six existing skill-script counterparts, and separately the
snapshot-only packaged resources. The resource list is dependency context, not
an instruction to copy them. The snapshot path label alone is not an integrity
pin; the per-file hashes are. Only source and resource files were read: no
survey bytes, mission databases, canonical ledgers, or live receipts.

Definitions:

- **needed-by-stage**: retain a capability/consolidation candidate for the named
  stage. This is not a mandate to copy the snapshot implementation. Reconcile
  with the existing owner and implementation first; conditional GSF work is
  not a prerequisite for a BAG-only mission.
- **retire**: remove this *snapshot package path* from the phase-4 port queue.
  Preserve the snapshot, historical receipts and existing skill helpers. This
  does not delete code or declare unrelated broader-source/browser use cases
  complete; explicit future scope may reopen a row.
- All dispositions are proposals for independent review, not scientific,
  installed-runtime, execution, or publication acceptance.

## Complete disposition table

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

Totals: **5 needed-by-stage candidates, 12 scoped retirements; 17/17 covered**.
The five candidates form discovery/sample-observation consolidation work;
three (`formats`, `gsf_resume`, `holds`) are conditional on admitting GSF.
There is no recommendation to copy all five to complete a BAG-only chain.

## Dependency and ownership handoff

1. **SC-2 / SC-3, not a new discovery implementation:** Grahammmm/skippercast#734
   was OPEN at observed head `0b9f0d8869c7e6187f59f353863e2760855c6807` during
   this audit; it is not evidence in the pinned main census. SC-2 owns the
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
```

The script compares actual source bytes with Git objects and emits stable,
host-path-free metadata. The JSON can be reproduced without network access;
the local snapshot is required and absence is an explicit error. Its digest
is an integrity check, not semantic acceptance of the dispositions. Acceptance
also checks unique table coverage against the 17 absent paths, counterparty
paths at the baseline, and a documentation/research-only Git diff. Product/GIS
execution and the full app build are not evidence required for this inventory.
