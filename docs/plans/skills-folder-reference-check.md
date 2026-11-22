# Skill folder reference check

| Check | What main shows |
| --- | --- |
| R1 — paths | 122 tracked files in 22 folders: 21 skill definitions and one shared library. Four distinct named repository paths are absent; the fleet skills already call them unbuilt. |
| R2 — flags | No undefined long option found in the scoped Python command examples after following parser dispatch and shared argument definitions. |
| R3 — skill names | One historical local skill is absent. One upstream skill is also absent here by design. Every existing folder is named somewhere in docs or tests. |
| R4 — follow-up | No buildable unit needed from this pass. |

**Audit base:** `eeae8953a17eb35871b1d9b59957746a10c72e8d`. Read locally on 2026-11-21. The main-branch push run at 21:54:55 UTC in `gh run list --repo Grahammmm/skippercast --branch main --event push --limit 6 --json headSha,createdAt,workflowName` reported this commit; the audit used a staged local Git tree, not a network checkout. All source line numbers below refer to this base.

The brief’s `34761911d5c44a903873867426f316c7f1e5911c` and the audit base have identical `skills/` and `docs/engineering/` trees. The contour builder changed in the newer tree, but only the explicit v3 path: `scripts/build_depth_contours.py:776,888` and `skills/skippercast-region-build/scripts/region_build.py:100` show that the documented wrapper uses the unchanged v1 default. Neither target nor relevant option names changed.

## R1. Which paths exist?

| Folder under `skills/` | Tracked files | Named paths | Present | Absent, with source line |
| --- | ---: | ---: | ---: | --- |
| `coast-campaign-shared` | 38 | 14 | 14 | — |
| `coast-local-screen` | 5 | 11 | 11 | — |
| `coast-segment-close` | 6 | 3 | 3 | — |
| `coast-sign-off` | 5 | 7 | 7 | — |
| `coast-verify` | 1 | 1 | 1 | — |
| `skippercast-add-region` | 1 | 13 | 13 | — |
| `skippercast-build-coastal-map` | 4 | 2 | 2 | — |
| `skippercast-discover-coastal-sources` | 15 | 29 | 29 | — |
| `skippercast-discover-data` | 2 | 6 | 6 | — |
| `skippercast-fleet-activity` | 2 | 12 | 9 | `docs/operations/agentorange.md` (`skills/skippercast-fleet-activity/SKILL.md:33`); `scripts/agentorange/check_host.sh` (`skills/skippercast-fleet-activity/SKILL.md:32`); `scripts/check_activity.py` (`skills/skippercast-fleet-activity/SKILL.md:34`) |
| `skippercast-fleet-registry` | 2 | 15 | 12 | `docs/operations/agentorange.md` (`skills/skippercast-fleet-registry/SKILL.md:36`); `scripts/agentorange/check_host.sh` (`skills/skippercast-fleet-registry/SKILL.md:35`); `scripts/check_registry.py` (`skills/skippercast-fleet-registry/SKILL.md:37`) |
| `skippercast-fleet-schedule-evidence` | 2 | 7 | 7 | — |
| `skippercast-ingest-data` | 1 | 7 | 7 | — |
| `skippercast-map-coast` | 17 | 40 | 40 | — |
| `skippercast-recent-intel` | 1 | 3 | 3 | — |
| `skippercast-region-build` | 3 | 14 | 14 | — |
| `skippercast-region-correct` | 2 | 5 | 5 | — |
| `skippercast-region-intake` | 2 | 2 | 2 | — |
| `skippercast-region-process` | 1 | 11 | 11 | — |
| `skippercast-region-publish` | 2 | 4 | 4 | — |
| `skippercast-region-review` | 5 | 5 | 5 | — |
| `skippercast-render-coast-3d` | 5 | 9 | 9 | — |

`coast-campaign-shared` is a library, not an installable skill (`skills/coast-campaign-shared/README.md:3–5`). The two fleet rows share the absent host-check script and operator doc. The other two absences are the activity and registry status scripts. Both skills list these as planned gaps, not commands to run (`skills/skippercast-fleet-activity/SKILL.md:29–34`; `skills/skippercast-fleet-registry/SKILL.md:32–38`; `docs/plans/charter-fleet/graph.md:121`).

The named fleet workflow files `fleet-ais.yml`, `fleet-ais-listener.yml`, `fleet-registry.yml` and `fleet-osint.yml` are also **not on this main**. The docs refer to the private ops repository, so they are not counted as broken local paths (`skills/skippercast-fleet-activity/SKILL.md:21–23,60–68`; `skills/skippercast-fleet-registry/SKILL.md:56–69`; private input inventory `tests/contract/test_fleet_skills.py:42–54`). Public `fleet-health.yml` is in the table's present count. No claim about the private repo's live contents.

**Counting rules.** `git ls-tree -r --name-only origin/main -- skills` counts all tracked entries below each folder; `git ls-tree -d --name-only origin/main:skills` lists folders. I read the 52 tracked prose files under `skills/`, including `SKILL.md`, README and reference files, not the code/schema internals as skill prose. The scratch pass collected backticked paths, Markdown link targets, rooted literal paths in prose, and paths in fenced or indented commands. It folded duplicate targets within a folder, not across folders. Link targets are relative to the source document, and `scripts/`/`references/` may be relative to the skill when the text gives that context. Known skill aliases and module entry points were resolved before lookup. I stripped link fragments; I did not check whether headings still match. A path is present if it is a blob or directory in the audited Git tree; it need not be usable or generated on a host. To recheck any row, use `git ls-tree origin/main -- <path>` at the pinned base and the listed source line.

I excluded external links and operator-local paths, generated run inputs/outputs, glob/region placeholders, package-external executables, and illustrative scripts. The Mapping reference named in `skills/skippercast-discover-coastal-sources/references/coastal-pipeline.md:192–194` belongs to the map skill, where it is linked at `skills/skippercast-map-coast/SKILL.md:30`. The bare `scripts/golden_compare.py` in `skills/skippercast-region-build/SKILL.md:63` is relative to the skill directory as specified at lines 36–37. These are not missing paths.

### Present targets and anchors

Each item is a normalized repository path followed by a representative source line. Within each folder, source paths are relative to that folder under `skills/`. Missing targets and their source lines are in the table above.

**`coast-campaign-shared`**

- `catalog/surveys.json` — `references/native-provenance.md:122`
- `skills/coast-campaign-shared/config/tier2-thresholds.json` — `references/contracts.md:60`
- `skills/coast-campaign-shared/references/admission-producers.md` — `references/contracts.md:3`
- `skills/coast-campaign-shared/references/native-provenance.md` — `references/contracts.md:5`
- `skills/coast-campaign-shared/scripts/coast_ledger.py` — `README.md:36`
- `skills/coast-campaign-shared/scripts/coast_raw.py` — `references/native-provenance.md:136`
- `skills/coast-campaign-shared/scripts/coast_receipt_versions.py` — `references/native-provenance.md:19`
- `skills/coast-campaign-shared/scripts/validate_coast_receipt.py` — `README.md:31`
- `src/skippercast/coastal/coordinator/bridge_run.py` — `references/admission-producers.md:24`
- `src/skippercast/coastal/prefetch.py` — `references/native-provenance.md:191`
- `tests/coast_contract_factory.py` — `README.md:86`
- `tests/contract/test_research_boundary.py` — `README.md:89`
- `tests/gis/test_coast_raw_provenance.py` — `references/native-provenance.md:208`
- `tests/unit/test_coast_contracts.py` — `README.md:89`

**`coast-local-screen`**

- `skills/coast-campaign-shared/config/tier2-thresholds.json` — `README.md:72`
- `skills/coast-campaign-shared/references/contracts.md` — `SKILL.md:14`
- `skills/coast-campaign-shared/references/directory-layout.md` — `SKILL.md:15`
- `skills/coast-local-screen/SKILL.md` — `README.md:3`
- `skills/coast-local-screen/prompts/text.md` — `README.md:75`
- `skills/coast-local-screen/prompts/vision.md` — `README.md:76`
- `skills/coast-local-screen/scripts/local_screen.py` — `SKILL.md:55`
- `skills/skippercast-discover-coastal-sources/SKILL.md` — `SKILL.md:12`
- `skills/skippercast-map-coast/SKILL.md` — `SKILL.md:13`
- `src/skippercast/coastal/coordinator/bridge_run.py` — `README.md:22`
- `tests/unit/test_coast_local_screen.py` — `README.md:104`

**`coast-segment-close`**

- `skills/coast-segment-close/scripts/archive_segment.py` — `SKILL.md:20`
- `skills/coast-segment-close/scripts/release_hot_cache.py` — `SKILL.md:21`
- `skills/coast-segment-close/scripts/verify_archive.py` — `SKILL.md:21`

**`coast-sign-off`**

- `skills/coast-campaign-shared/references/contracts.md` — `SKILL.md:15`
- `skills/coast-sign-off/SKILL.md` — `SKILL.md:159`
- `skills/coast-sign-off/scripts/open_packet.py` — `SKILL.md:77`
- `skills/coast-sign-off/scripts/prepare_round.py` — `SKILL.md:76`
- `skills/coast-sign-off/scripts/write_verdict.py` — `SKILL.md:78`
- `skills/skippercast-discover-coastal-sources/SKILL.md` — `SKILL.md:13`
- `skills/skippercast-map-coast/SKILL.md` — `SKILL.md:14`

**`coast-verify`**

- `skills/coast-sign-off/SKILL.md` — `SKILL.md:9`

**`skippercast-add-region`**

- `catalog/coastal-sectors.json` — `SKILL.md:14`
- `catalog/data-needs.json` — `SKILL.md:8`
- `catalog/primary-strategies.json` — `SKILL.md:24`
- `catalog/usgs-seafloor-sources.json` — `SKILL.md:16`
- `docs/archive/statewide-buildout.md` — `SKILL.md:14`
- `docs/production-operations.md` — `SKILL.md:32`
- `docs/region-pipeline.md` — `SKILL.md:10`
- `docs/regional-intelligence.md` — `SKILL.md:32`
- `docs/regions.md` — `SKILL.md:8`
- `docs/regulations.md` — `SKILL.md:22`
- `research/scripts/build_primary_strategies.py` — `SKILL.md:24`
- `research/scripts/import_usgs_seafloor_character.py` — `SKILL.md:16`
- `src/skippercast/platform/__main__.py` — `SKILL.md:26`

**`skippercast-build-coastal-map`**

- `skills/skippercast-build-coastal-map/scripts/model_trials.py` — `references/calibration.md:12`
- `skills/skippercast-render-coast-3d/SKILL.md` — `SKILL.md:10`

**`skippercast-discover-coastal-sources`**

- `packages/coast/src/bottom/loader.ts` — `references/coastal-pipeline.md:396`
- `research/receipts/coast-prod-02-installed-closure.json` — `references/coastal-pipeline.md:300`
- `research/tests/gis/test_check_terrain_acceptance_render.py` — `references/coastal-pipeline.md:302`
- `research/tests/test_coastal_snapshot_inventory.py` — `references/bounded-discovery.md:205`
- `skills` — `references/coastal-pipeline.md:189`
- `skills/skippercast-discover-coastal-sources` — `references/coastal-pipeline.md:10`
- `skills/skippercast-discover-coastal-sources/references/bounded-discovery.md` — `SKILL.md:38`
- `skills/skippercast-discover-coastal-sources/references/bounded-quality.md` — `SKILL.md:24`
- `skills/skippercast-discover-coastal-sources/references/coastal-pipeline.md` — `SKILL.md:12`
- `skills/skippercast-discover-coastal-sources/references/format-readers.md` — `SKILL.md:28`
- `skills/skippercast-discover-coastal-sources/references/gsf-resume.md` — `SKILL.md:30`
- `skills/skippercast-discover-coastal-sources/references/quality-receipt-v1.schema.json` — `references/bounded-quality.md:119`
- `skills/skippercast-discover-coastal-sources/references/source-manifest-v1.schema.json` — `references/bounded-discovery.md:174`
- `skills/skippercast-discover-coastal-sources/scripts/discover.py` — `references/bounded-discovery.md:3`
- `skills/skippercast-discover-coastal-sources/scripts/gsf_probe.c` — `references/format-readers.md:20`
- `skills/skippercast-discover-coastal-sources/scripts/gsf_resume.py` — `references/gsf-resume.md:45`
- `skills/skippercast-discover-coastal-sources/scripts/gsf_scan.c` — `references/gsf-resume.md:10`
- `skills/skippercast-discover-coastal-sources/scripts/quality.py` — `references/bounded-quality.md:87`
- `skills/skippercast-map-coast` — `references/coastal-pipeline.md:11`
- `skills/skippercast-map-coast/references/source-preparation-and-trials.md` — `references/coastal-pipeline.md:193`
- `skills/skippercast-map-coast/scripts/validate_handoff.py` — `references/coastal-pipeline.md:392`
- `skills/skippercast-render-coast-3d` — `references/coastal-pipeline.md:12`
- `src/skippercast/coastal/cli.py` — `references/coastal-pipeline.md:42`
- `src/skippercast/coastal/coordinator/source_free.py` — `references/coastal-pipeline.md:54`
- `src/skippercast/coastal/render/terrain_only.py` — `references/coastal-pipeline.md:479`
- `tests/coast/bottom-loader.test.ts` — `references/coastal-pipeline.md:396`
- `tests/gis/test_coastal_operations_cost_stop.py` — `references/coastal-pipeline.md:398`
- `tests/unit/test_coastal_cli.py` — `references/coastal-pipeline.md:299`
- `tests/unit/test_coastal_operations.py` — `references/coastal-pipeline.md:398`

**`skippercast-discover-data`**

- `catalog/data-needs.json` — `SKILL.md:8`
- `catalog/source-candidate.schema.json` — `SKILL.md:16`
- `catalog/sources.json` — `SKILL.md:8`
- `docs/regional-intelligence.md` — `SKILL.md:22`
- `skills/skippercast-discover-data/references/source-review.md` — `SKILL.md:14`
- `src/skippercast/platform/__main__.py` — `SKILL.md:10`

**`skippercast-fleet-activity`**

- `.github/workflows/fleet-health.yml` — `SKILL.md:23`
- `AGENTS.md` — `SKILL.md:12`
- `CONTRIBUTING.md` — `SKILL.md:13`
- `docs/operations/runbooks/fleet-ais-down.md` — `SKILL.md:21`
- `docs/operations/runbooks/fleet-labelling.md` — `SKILL.md:22`
- `docs/operations/runbooks/fleet-public-heat.md` — `SKILL.md:141`
- `docs/plans/charter-fleet/design.md` — `SKILL.md:14`
- `src/skippercast/fleet/__main__.py` — `SKILL.md:128`
- `src/skippercast/fleet/ais/__main__.py` — `SKILL.md:71`

**`skippercast-fleet-registry`**

- `.github/workflows/fleet-health.yml` — `SKILL.md:20`
- `AGENTS.md` — `SKILL.md:12`
- `CONTRIBUTING.md` — `SKILL.md:13`
- `docs/operations/runbooks/fleet-ais-down.md` — `SKILL.md:28`
- `docs/operations/runbooks/fleet-labelling.md` — `SKILL.md:54`
- `docs/operations/runbooks/fleet-osint.md` — `SKILL.md:27`
- `docs/operations/runbooks/fleet-registry.md` — `SKILL.md:26`
- `docs/plans/charter-fleet/README.md` — `SKILL.md:145`
- `docs/plans/charter-fleet/design.md` — `SKILL.md:13`
- `docs/plans/charter-fleet/open-questions.md` — `SKILL.md:86`
- `src/skippercast/fleet/__main__.py` — `SKILL.md:95`
- `src/skippercast/fleet/ais/__main__.py` — `SKILL.md:81`

**`skippercast-fleet-schedule-evidence`**

- `AGENTS.md` — `SKILL.md:10`
- `CONTRIBUTING.md` — `SKILL.md:10`
- `docs/operations/runbooks/fleet-schedule-evidence.md` — `SKILL.md:10`
- `docs/plans/charter-fleet/design.md` — `SKILL.md:10`
- `regions/CA/fleet.json` — `SKILL.md:14`
- `scripts/fleet/install_schedule_evidence.sh` — `SKILL.md:26`
- `scripts/fleet/schedule_evidence.py` — `SKILL.md:27`

**`skippercast-ingest-data`**

- `docs/data-contracts.md` — `SKILL.md:8`
- `docs/regional-intelligence.md` — `SKILL.md:28`
- `docs/regulations.md` — `SKILL.md:18`
- `docs/seabed-views.md` — `SKILL.md:24`
- `scripts/refresh_regions.py` — `SKILL.md:28`
- `src/skippercast/pipeline` — `SKILL.md:8`
- `src/skippercast/platform` — `SKILL.md:8`

**`skippercast-map-coast`**

- `.github/workflows/seafloor.yml` — `references/execution-and-release.md:86`
- `AGENTS.md` — `SKILL.md:24`
- `CHANGELOG.md` — `references/parallel-pilot.md:158`
- `CONTRIBUTING.md` — `SKILL.md:24`
- `catalog/classified-habitat-policy.json` — `references/habitat-expansion-preflight.md:67`
- `catalog/habitat-rules.json` — `references/execution-and-release.md:41`
- `catalog/seafloor-screen.json` — `references/execution-and-release.md:66`
- `catalog/surveys.json` — `references/source-recipes.md:55`
- `docs/archive/seafloor-csumb-release-contract-2026-09-30.md` — `references/source-recipes.md:353`
- `docs/archive/seafloor-tiled-habitat-2026-09-30.md` — `references/historical-blockers.md:55`
- `docs/engineering/classified-geometry.md` — `references/habitat-expansion-preflight.md:78`
- `docs/engineering/native-terrain-support.md` — `references/execution-and-release.md:76`
- `requirements-seafloor.txt` — `references/execution-and-release.md:7`
- `research/scripts/discover_noaa_multibeam_footprints.py` — `references/source-recipes.md:71`
- `research/scripts/inspect_native_grid_units.py` — `references/source-recipes.md:13`
- `research/scripts/inspect_point_bins.py` — `references/source-recipes.md:418`
- `research/scripts/prepare_multibeam_grid.py` — `references/source-recipes.md:205`
- `research/scripts/probe_classified_habitat.py` — `references/habitat-expansion-preflight.md:38`
- `research/scripts/triage_multibeam_beams.py` — `references/source-recipes.md:141`
- `skills/skippercast-discover-coastal-sources/SKILL.md` — `SKILL.md:39`
- `skills/skippercast-discover-coastal-sources/references/coastal-pipeline.md` — `SKILL.md:15`
- `skills/skippercast-map-coast/assets/render-handoff-v2.schema.json` — `references/render-handoff-contract.md:3`
- `skills/skippercast-map-coast/references/bounded-artifacts.md` — `SKILL.md:56`
- `skills/skippercast-map-coast/references/execution-and-release.md` — `SKILL.md:227`
- `skills/skippercast-map-coast/references/habitat-expansion-preflight.md` — `SKILL.md:140`
- `skills/skippercast-map-coast/references/historical-blockers.md` — `SKILL.md:317`
- `skills/skippercast-map-coast/references/improvement-loop.md` — `SKILL.md:103`
- `skills/skippercast-map-coast/references/overnight-contract.md` — `SKILL.md:120`
- `skills/skippercast-map-coast/references/parallel-pilot.md` — `SKILL.md:116`
- `skills/skippercast-map-coast/references/progress-control.md` — `SKILL.md:97`
- `skills/skippercast-map-coast/references/render-handoff-contract.md` — `SKILL.md:293`
- `skills/skippercast-map-coast/references/source-preparation-and-trials.md` — `SKILL.md:30`
- `skills/skippercast-map-coast/references/source-recipes.md` — `SKILL.md:192`
- `skills/skippercast-map-coast/references/source-review-checkpoints.md` — `SKILL.md:186`
- `skills/skippercast-map-coast/scripts/check_progress.py` — `references/bounded-artifacts.md:39`
- `skills/skippercast-map-coast/scripts/run_bounded.py` — `references/bounded-artifacts.md:36`
- `skills/skippercast-map-coast/scripts/validate_handoff.py` — `references/render-handoff-contract.md:4`
- `src/skippercast/seafloor/__main__.py` — `SKILL.md:127`
- `src/skippercast/seafloor/classified_habitat.py` — `references/habitat-expansion-preflight.md:70`
- `tests/gis/test_seafloor_habitat_tiles.py` — `references/historical-blockers.md:51`

**`skippercast-recent-intel`**

- `catalog/recent-intel-watchlist.json` — `SKILL.md:8`
- `docs/recent-intel.md` — `SKILL.md:8`
- `scripts/collect_recent_intel.py` — `SKILL.md:8`

**`skippercast-region-build`**

- `catalog` — `SKILL.md:50`
- `catalog/depth-contours/morro-bay.geojson` — `SKILL.md:63`
- `dist` — `SKILL.md:50`
- `docs/operations/coast-statewide-runsheet.md` — `SKILL.md:57`
- `requirements-survey.txt` — `SKILL.md:19`
- `scripts/build_depth_contours.py` — `SKILL.md:27`
- `scripts/preflight_native_grid.py` — `SKILL.md:27`
- `skills/skippercast-map-coast/SKILL.md` — `SKILL.md:58`
- `skills/skippercast-region-build` — `SKILL.md:36`
- `skills/skippercast-region-build/scripts/golden_compare.py` — `SKILL.md:37`
- `skills/skippercast-region-build/scripts/region_build.py` — `SKILL.md:26`
- `skills/skippercast-region-correct/scripts/region_correct.py` — `SKILL.md:28`
- `skills/skippercast-region-intake/scripts/region_intake.py` — `SKILL.md:25`
- `skills/skippercast-region-review/scripts/region_review.py` — `SKILL.md:35`

**`skippercast-region-correct`**

- `requirements-survey.txt` — `SKILL.md:19`
- `skills/skippercast-region-build/scripts/region_build.py` — `SKILL.md:35`
- `skills/skippercast-region-correct/scripts/region_correct.py` — `SKILL.md:26`
- `skills/skippercast-region-intake/scripts/region_intake.py` — `SKILL.md:25`
- `skills/skippercast-region-review/scripts/region_review.py` — `SKILL.md:60`

**`skippercast-region-intake`**

- `regions` — `SKILL.md:14`
- `skills/skippercast-region-intake/scripts/region_intake.py` — `SKILL.md:24`

**`skippercast-region-process`**

- `dist` — `SKILL.md:58`
- `regions` — `SKILL.md:13`
- `scripts/relief/region.py` — `SKILL.md:29`
- `skills/skippercast-region-build/scripts/region_build.py` — `SKILL.md:23`
- `skills/skippercast-region-correct/SKILL.md` — `SKILL.md:22`
- `skills/skippercast-region-correct/scripts/region_correct.py` — `SKILL.md:22`
- `skills/skippercast-region-intake/scripts/region_intake.py` — `SKILL.md:20`
- `skills/skippercast-region-publish/scripts/region_publish.py` — `SKILL.md:27`
- `skills/skippercast-region-review/PROMPT.md` — `SKILL.md:26`
- `skills/skippercast-region-review/scripts/phone_capture.mjs` — `SKILL.md:25`
- `skills/skippercast-region-review/scripts/region_review.py` — `SKILL.md:24`

**`skippercast-region-publish`**

- `dist` — `SKILL.md:23`
- `skills/skippercast-region-correct/scripts/region_correct.py` — `SKILL.md:19`
- `skills/skippercast-region-publish/scripts/region_publish.py` — `SKILL.md:18`
- `skills/skippercast-region-review/scripts/region_review.py` — `SKILL.md:17`

**`skippercast-region-review`**

- `skills/coast-sign-off` — `SKILL.md:26`
- `skills/skippercast-region-build/scripts/region_build.py` — `SKILL.md:22`
- `skills/skippercast-region-review/PROMPT.md` — `SKILL.md:24`
- `skills/skippercast-region-review/scripts/phone_capture.mjs` — `SKILL.md:15`
- `skills/skippercast-region-review/scripts/region_review.py` — `PROMPT.md:43`

**`skippercast-render-coast-3d`**

- `skills/skippercast-discover-coastal-sources/SKILL.md` — `references/mapping-handoff.md:3`
- `skills/skippercast-discover-coastal-sources/references/coastal-pipeline.md` — `SKILL.md:11`
- `skills/skippercast-map-coast/references/bounded-artifacts.md` — `SKILL.md:40`
- `skills/skippercast-map-coast/references/render-handoff-contract.md` — `references/mapping-handoff.md:15`
- `skills/skippercast-map-coast/scripts/run_bounded.py` — `SKILL.md:57`
- `skills/skippercast-map-coast/scripts/validate_handoff.py` — `references/mapping-handoff.md:16`
- `skills/skippercast-render-coast-3d/references/calibration.md` — `SKILL.md:71`
- `skills/skippercast-render-coast-3d/references/mapping-handoff.md` — `SKILL.md:29`
- `skills/skippercast-render-coast-3d/scripts/model_trials.py` — `references/calibration.md:12`

## R2. Which documented argparse options are absent?

**None found** in the checked Python examples. This is a source check, not a promise that an example runs successfully. It covers options written on the command or its continuation, including named local Python modules and the region builder's described downstream call. It excludes GitHub CLI inputs, shell and Node parser interfaces, third-party runners such as pytest, option values, availability of private inputs, and commands whose target was absent. No documented command or `--help` was executed. Re-read option declarations with `git grep -nE 'add_argument|add_parser|argparse' origin/main -- <entry-point>` and follow its parser helpers and subcommand dispatch.

| Examples that need more than a literal flag grep | Source of the option names |
| --- | --- |
| Fleet `report`, `coverage-status`, and AIS commands (`skills/skippercast-fleet-registry/SKILL.md:81,95,106,117,132–133`; `skills/skippercast-fleet-activity/SKILL.md:71,80,108,117,128`) | `src/skippercast/fleet/__main__.py:3` → `src/skippercast/fleet/cli.py:116–133`, `src/skippercast/fleet/report.py:340–346`, `src/skippercast/fleet/coverage.py:119–122`; AIS dispatch `src/skippercast/fleet/ais/__main__.py:35–40` → `gate.py:39`, `validate.py:488–493`, `schedule.py:302–305` (same AIS directory). |
| Bounded discovery and quality examples (`skills/skippercast-discover-coastal-sources/references/bounded-discovery.md:39–48,91–93`; `skills/skippercast-discover-coastal-sources/references/bounded-quality.md:37–40,87–91`) | `skills/skippercast-discover-coastal-sources/scripts/discover.py:727–760` and `skills/skippercast-discover-coastal-sources/scripts/quality.py:466–472,499–519`. The GSF limits are loop-added at `skills/skippercast-discover-coastal-sources/scripts/gsf_resume.py:179–183`. |
| Local screening, sign-off and archive helper examples (`skills/coast-local-screen/SKILL.md:55–58`; `skills/coast-sign-off/SKILL.md:76–78`; `skills/coast-segment-close/SKILL.md:54–59,86–89,100–104`) | The local screen selects the canonical parser at `skills/coast-local-screen/scripts/local_screen.py:1723–1727`; options are loop-added at lines 1657–1664. Shared options are in `skills/coast-sign-off/scripts/review_common.py:32–35` and `skills/coast-segment-close/scripts/close_common.py:50–54`. |
| Bounded runs and trial recording (`skills/skippercast-map-coast/references/bounded-artifacts.md:46–51`; the two `references/calibration.md` files at lines 15–19) | `skills/skippercast-map-coast/scripts/run_bounded.py:247–262`; `skills/skippercast-build-coastal-map/scripts/model_trials.py:21–31` and `skills/skippercast-render-coast-3d/scripts/model_trials.py:21–31`. `--` separates the child command in the bounded-run example. |
| Region correction and publishing (`skills/skippercast-region-correct/SKILL.md:26,31`; `skills/skippercast-region-publish/SKILL.md:18,24`; `skills/skippercast-region-build/SKILL.md:25–30`) | `skills/skippercast-region-correct/scripts/region_correct.py:215–220`; `skills/skippercast-region-publish/scripts/region_publish.py:238–245`; `scripts/build_depth_contours.py:774–792` for the downstream builder's options. |
| Seafloor and platform module commands (`skills/skippercast-map-coast/SKILL.md:127–129,223`; `skills/skippercast-map-coast/references/execution-and-release.md:15–36`; `skills/skippercast-add-region/SKILL.md:26`; `skills/skippercast-discover-data/SKILL.md:10,16`) | `src/skippercast/seafloor/__main__.py:13–71`; `src/skippercast/platform/__main__.py:9–19`. |

## R3. Which named skills are absent or unmentioned?

| Name | Status on main | Evidence |
| --- | --- | --- |
| `skills/hermes/skippercast-coastal` | Absent. An engineering audit describes the old adapter as a historical retirement candidate; it is not a current requirement to install it. | `docs/engineering/audits/coastal-snapshot-2026-10-20.md:29–39,100`; `docs/engineering/audits/coastal-snapshot-2026-10-20.json:831,843`. |
| `last30days` | Absent from this repository's `skills/`. Named as upstream, not an absent local dependency. | `docs/recent-intel.md:24`; `skills/skippercast-recent-intel/SKILL.md:8`. |
| Present folders no docs or tests name | None. All 22 top-level names have a literal `skills/<folder>` match in `docs/` or `tests/`. | Reproduce with the two commands below; compare the folder names after stripping `skills/` from the grep results. |

```sh
git ls-tree -d --name-only origin/main:skills
git grep -oEh 'skills/[a-z][a-z0-9-]+' origin/main -- docs tests | sort -u
```

I also checked bare names in skill links and the tests that construct a path from components. For example, `tests/contract/test_fleet_skills.py:24,57–58` names three skills without spelling out the full paths on those lines. `tests/contract/test_mapping_progress_control.py:9`, `tests/unit/test_coastal_skill_trials.py:9` and `tests/unit/test_region_build.py:93,184` read mapping, trial and region skill files. The retirement inventory names all three destinations (`docs/engineering/subsystem-retirement.manifest.json:8,11–12`); a name in that inventory is not proof a skill is installed, active or unused.

## R4. Follow-up

No buildable unit is needed from this pass. The missing repository paths are already identified as unbuilt in the fleet skills (R1), the absent skill names are historical or upstream (R3), and the static option check did not identify an undefined flag in scope (R2). This report does not propose adding a host tool, activating a skill, or changing any approval gate.
