# JSON Schemas: where they are used

| Class | Files | What the class means in this report |
| --- | ---: | --- |
| Runtime-validated | 18 | A specific non-test workflow applies the schema to data, directly or through a `$ref`. Includes explicit, purpose-built tools, not just scheduled jobs. |
| Test-only | 11 | Tests load it; no specific non-test workflow was found applying it to data. The general-purpose CLI is still available. |
| Documented-only | 0 | Mentioned but neither applied at runtime nor loaded by tests. |
| Unreferenced | 0 | No consumer or documentation reference found. |
| **Total** | **29** | One row per tracked file in `schemas/`. |

Snapshot: SkipperCast main `0fed7b9f909834f04e5460567718af491d80316b` (main push workflow recorded 2026-11-21 21:53 UTC, `gh run list -R Grahammmm/skippercast --branch main --limit 3 --json headSha,createdAt,event`; tree staged from a local Git store). The card's earlier snapshot `34761911d5c44a903873867426f316c7f1e5911c` has identical `schemas/`, `src/skippercast/validate.py`, `pyproject.toml`, `docs/data-contracts.md` and `docs/engineering/testing.md` at these two commits (`git diff --stat <earlier> <snapshot> --` followed by those paths).

## R1. Consumers and coverage

**Reading is not enforcement.** `src/skippercast/validate.py:40–71,82–88,127–141` reads all 29 files into a local reference registry, then loads the chosen root schema separately. The general CLI dispatch at `src/skippercast/__main__.py:18–20` and `src/skippercast/validate.py:273–295` lets an operator validate data against any of the 28 registered kinds; `common` is a reference library, not a CLI kind. Neither the registry read nor CLI availability proves that a particular workflow actually validates its data. The coastal CLI also reads bundled resources for hashes, not instance validation (`src/skippercast/coastal/cli.py:37–43`; `git ls-tree origin/main src/skippercast/coastal/resources/` lists the tracked symlinks). The manifest-driven closure tool can read these files to check their IDs and references, not to validate data (`scripts/coast_diagnostics/schema_closure.py:697–741,903–925`).

**When checks run.** `pyproject.toml:36–44` declares the optional dependencies. `src/skippercast/validate.py:163–188` makes `check()` skip with a warning when dependencies are absent or `SKIPPERCAST_VALIDATE` is off. Writers using `atomic_json(kind=...)` call it before writing (`src/skippercast/platform/contracts.py:71–81`). Direct validators shown below need not use that switch. This is a source audit, not an observation of live process configuration. The distinction between shape and semantic checks is documented at `docs/data-contracts.md:15–17`; the contract test layer is described at `docs/engineering/testing.md:55`.

**Shared test evidence for every row:** `tests/contract/test_schemas.py:41–53` reads and metaschema-checks all 29, then checks their IDs and kind registration. Lines 55–70 construct validators and look up the references for every registered kind. `tests/contract/test_packaging.py:141–148` reads canonical bytes to test packaging; `tests/unit/test_sc_schema_closure.py:356–398` pins and checks the schema family and its references with the manifest-driven diagnostic CLI. These tests do not prove a representative data instance was checked for every kind. In the table, **S** means `tests/contract/test_schemas.py`; additional tests are named where they directly load a schema or exercise a relevant boundary, rather than listing every integration test that happens to populate the registry. Each row's `$id` is `https://skippercast.com/schemas/` plus the exact filename, declared at line 3 of that file unless another line is shown.

| File under `schemas/` | Code applying or otherwise specifically loading the file (in addition to the shared paths above) | Tests beyond shared loading | Class |
| --- | --- | --- | --- |
| `coast-recipe-v1.schema.json` | `validate_recipe.py:281–306,320–329,381–399` applies the schema in the dedicated offline tool; `scripts/coast_diagnostics/recipe_delta.py:262–294` calls it against staged metadata. | `tests/unit/test_sc_recipe_offline.py:165–176`, `tests/unit/test_sc_recipe_delta.py:195,275`, `tests/unit/test_coast_recipe.py:50`, `tests/unit/test_coast_recipe_statewide.py:75`, `tests/unit/test_recipe_anchor_identity.py:50`, `tests/unit/test_f11_17_audit.py:25` | Runtime-validated |
| `coastal-discovery-lead-v1.schema.json` (`$id`:386) | `src/skippercast/coastal/cached_inventory.py:150–168` applies the packaged schema to held leads. | `tests/unit/test_coastal_cached_intake.py:50–56` (inventory and packaged bytes) | Runtime-validated |
| `coastal-terrain-only-input-v1.schema.json` | `src/skippercast/coastal/coordinator/stages.py:53–66` checks readiness; `src/skippercast/coastal/render/terrain_only.py:118–128` checks input. | `tests/gis/test_coastal_stage_terrain_horizon.py:76` calls the real verifier; `tests/gis/test_coastal_terrain_style_integers.py:143` goes through preview. | Runtime-validated |
| `coastal-terrain-only-render-v1.schema.json` | Read for digest binding, not applied to the receipt: `src/skippercast/coastal/render/terrain_only.py:461–472,503–523` and `src/skippercast/coastal/render/governed.py:118–122`. Receipt checks in `src/skippercast/coastal/render/terrain_demo.py:155–170` are hand-written. | `tests/gis/test_coastal_terrain_demo_json.py:104` and `tests/gis/test_coastal_terrain_demo_duplicate_json.py:58` load it indirectly for the preview digest; no dedicated instance-schema check found. | Test-only |
| `coastal-terrain-only-science-review-v1.schema.json` | `src/skippercast/coastal/render/terrain_only.py:129–137` checks the review document. | `tests/gis/test_coastal_stage_terrain_horizon.py:76`; `tests/gis/test_coastal_terrain_style_integers.py:68–72,143` | Runtime-validated |
| `common.schema.json` | Applied through `$ref`, e.g. the daily writer → `daily-feed.schema.json:12,15–16` → shared publication/timestamp definitions; see R2. | S:55–70 resolves dependencies; S:107–112,145–156 applies them through feed instances. | Runtime-validated |
| `coverage.schema.json` | `src/skippercast/platform/build.py:169` checks on write. | S:95–105; `tests/unit/test_f10_05_audit.py:101` | Runtime-validated |
| `daily-feed.schema.json` | `scripts/refresh_regions.py:108–116` and `src/skippercast/pipeline/__main__.py:40` check before write. Scheduled daily caller: `.github/workflows/daily-data.yml:55,82`. | S:107–112,135–166,259–266; `tests/contract/test_region_contract.py:267–303` | Runtime-validated |
| `data-needs.schema.json` | No specific schema caller found. `src/skippercast/platform/contracts.py:152–185` loads the catalog and does hand-written checks. | S:85–87 | Test-only |
| `fleet-profile.schema.json` | `src/skippercast/fleet/profile.py:395–404` applies schema and policy; called by `src/skippercast/fleet/ingest.py:325` and `scripts/fleet/run_osint.py:319`. `src/skippercast/fleet/agent.py:49` names the prompt input, not the enforcing boundary. | `tests/unit/test_fleet_profile.py:223–252` | Runtime-validated |
| `fleet-region.schema.json` | `src/skippercast/fleet/config.py:254–259,457–477` applies it when validation is available. | `tests/contract/test_fleet_region.py:45,149–155`; `tests/unit/test_fleet_config.py:246–274` exercises the loader. | Runtime-validated |
| `forecast-index.schema.json` | No specific schema caller found. `src/skippercast/forecast/build.py:374–406` writes the index without invoking it. | S:107–112,223–235 | Test-only |
| `forecast-manifest.schema.json` | No specific schema caller found, including no runtime `$ref` use (its two incoming references are from the forecast index and tile). `src/skippercast/forecast/build.py:341–361` writes the model manifest without invoking it. | S:107–112,135–143,223–226 | Test-only |
| `forecast-tile.schema.json` | No specific schema caller found. `src/skippercast/forecast/build.py:280` writes tiles without invoking it. | S:107–112,135–143,227–231. S:114–122 separately checks packed data lengths. | Test-only |
| `intelligence-feed.schema.json` | `src/skippercast/pipeline/intelligence.py:213–217` validates before writing the verification archive or latest feed; also used in part from the index (R2). | S:95–112,135–143; `tests/contract/test_region_contract.py:305–308` pins write ordering by inspecting source. | Runtime-validated |
| `jurisdiction.schema.json` | No specific schema caller found. Binding checks are separate (`src/skippercast/pipeline/regulations.py:36,102`; `docs/data-contracts.md:15`). | S:89–93 | Test-only |
| `launch-points.schema.json` | `src/skippercast/platform/launch_points.py:96–99` checks before output. | `tests/contract/test_launch_points.py:77–81` | Runtime-validated |
| `live-feed.schema.json` | `scripts/refresh_regions.py:108–116` checks on write; `scripts/live_cycle.sh:34` calls that path. | S:107–112,135–143,158–166,259–263; `tests/contract/test_region_contract.py:267–271` | Runtime-validated |
| `private-mapping-input-v2.schema.json` (`$id`:174) | No specific JSON Schema check found. `src/skippercast/coastal/handoff/mapping_input.py:208–250` verifies the handoff with Python rules. | Shared tests only for this file; handoff behavior tests are not schema loads. | Test-only |
| `published-regions.schema.json` | `src/skippercast/platform/build.py:176` checks `dist/regions/index.json` on write. | S:95–99 | Runtime-validated |
| `region-manifest.schema.json` | `src/skippercast/platform/build.py:172` checks the package manifest on write. | S:95–103 | Runtime-validated |
| `region.schema.json` | `src/skippercast/platform/contracts.py:187–195,284–301` checks shape when available and otherwise runs a fallback; `src/skippercast/platform/build.py:170` also checks on write. | S:79–83,95–101,207–221; `tests/contract/test_region_contract.py:230–257`; `tests/unit/test_chart_files.py:63–67` and `tests/test_chart_files_manifest_validation.mjs:36` | Runtime-validated |
| `regions-index.schema.json` | `scripts/refresh_regions.py:177` checks the feed index on write (distinct from `dist/regions/index.json`). | S:107–112,168–176 | Runtime-validated |
| `render-handoff-v2.1.schema.json` (`$id`:282) | No specific JSON Schema check found. `src/skippercast/coastal/handoff/render.py:105–143` verifies the receipt with Python rules. | Shared tests only for this file; the packaged `render-handoff-v2.schema.json` is a different file. | Test-only |
| `sc-render-v1.schema.json` | `src/skippercast/relief/render_config.py:16–25` validates `regions/<id>/render.json` on read, e.g. for `src/skippercast/relief/contours.py:173`. | `tests/unit/test_relief_render_config.py:29–38,44–57`; `tests/unit/test_render_configs_central.py:29` and `tests/unit/test_render_configs_north_south.py:34` | Runtime-validated |
| `shore-habitat.schema.json` | `scripts/collect_shore_habitat.py:505` checks collection output; `src/skippercast/platform/build.py:56–64` checks assets. Browser comment `web/brief/shore.ts:27` is not a schema load. | `tests/contract/test_shore_habitat.py:87,398–419` | Runtime-validated |
| `source.schema.json` | No specific runtime schema caller found. Applied through `sources-catalog` in tests (R2) and available as a CLI kind. | S:85–87,178–205 | Test-only |
| `sources-catalog.schema.json` | No specific schema caller found. Catalog loader checks fields in Python (`src/skippercast/platform/contracts.py:152–185`); the different `dist/data/source-catalog.json` projection is written without `kind=` (`src/skippercast/platform/build.py:181`). | S:85–87 | Test-only |
| `vertical-v1.schema.json` (`$id`:220) | No specific JSON Schema check found. `src/skippercast/coastal/vertical.py:224–272` uses hand-written rules. | Shared tests only for this file; tests of the Python rules do not by themselves load the schema. | Test-only |

To reproduce the inventory and find literal and indirect candidate consumers, run from the pinned tree. Substitute each table filename for `forecast-index.schema.json` in the second command; registration and comments are leads, not proof of validation. Follow aliases, kind constants, `atomic_json` call sites, and package-resource symlinks before classifying. The tests column does not count JSON fixtures that merely contain a schema name.

```sh
git ls-tree -r --name-only origin/main schemas
git grep -nF 'forecast-index.schema.json' origin/main -- src scripts tests server web packages .github docs skills validate_recipe.py
git grep -nE 'schemas/|\.schema\.json|atomic_json\(|validate\.(check|errors|validator)\(|Draft202012Validator' origin/main -- src scripts tests server web packages .github validate_recipe.py
```

## R2. Cross-file `$ref` graph

One line per distinct directed file pair; numbers are source lines under `schemas/`. Multiple references to one file are grouped in that edge. The read on 2026-11-21 found 315 `$ref` occurrences, 153 cross-file and 162 within their own file. No missing files or fragments were found: resolve each `$ref` against the source file's `$id`, match that URI to a local `$id`, and follow the JSON Pointer (or use the existing offline resolver test below). The JSON Schema dialect URL in `$schema` is not a `$ref`.

```text
coverage.schema.json:14,22,25,26,28,40 -> common.schema.json
daily-feed.schema.json:12,15,16,28,30,31,36,37,41,49,69,70,107,112 -> common.schema.json
data-needs.schema.json:18,21,27 -> common.schema.json
fleet-region.schema.json:52,99,102,103,114,116,118,126,130,141,142,249,256 -> common.schema.json
forecast-index.schema.json:10,31,32 -> common.schema.json
forecast-index.schema.json:22 -> forecast-manifest.schema.json
forecast-manifest.schema.json:18,19,34 -> common.schema.json
forecast-tile.schema.json:10,12,13 -> forecast-manifest.schema.json
intelligence-feed.schema.json:8,11,12,13,14,17,24,33,65,66 -> common.schema.json
jurisdiction.schema.json:10,15,21,23,51 -> common.schema.json
live-feed.schema.json:8,11,12,13,22,26,33,49 -> common.schema.json
published-regions.schema.json:10,18,21,22,24 -> common.schema.json
region-manifest.schema.json:10,18 -> common.schema.json
region.schema.json:20,24,25,27,54,55,69,111,115,122,130,136,145,146,153,155,166,168,169,178,186,206,207,213,214,235,236,237,238,239,244,245,256,269,282,284 -> common.schema.json
regions-index.schema.json:16,30,33,38,47,50 -> common.schema.json
regions-index.schema.json:55 -> intelligence-feed.schema.json
shore-habitat.schema.json:13,14,21,22,23,53,64,65,66,75,76,87,99,117,120,124,129,143,149,152,155 -> common.schema.json
source.schema.json:12,18,20,23,31,53,58,71,73 -> common.schema.json
sources-catalog.schema.json:11 -> source.schema.json
```

```sh
git grep -nF '"$ref"' origin/main -- schemas
python -m pytest -q tests/contract/test_schemas.py::SchemaFiles
```

The test requires the optional JSON Schema dependencies. The separate closure test pins and inspects schema bytes and resolves references; it is not a data-validator test (`tests/unit/test_sc_schema_closure.py:356–389`).

## R3. Unbound labels and directories without a matching schema

The 2026-11-21 read screened tracked `.json` and `.geojson` objects for top-level string `$schema` and `schema` fields, excluding schema definitions. No parsed data object had a top-level string `$schema`. A `schema` string is often a version tag rather than a file path. For example `regions/morro-bay/render.json:2` says `sc-render/1`, which **does** have a schema (`schemas/sc-render-v1.schema.json:9` and the loader above). Likewise, `tests/fixtures/relief/pointer-style/v1.json:1` says `sc-relief-pointer/1`, defined outside the 29 at `catalog/relief/pointer.schema.json:8`. Numeric `schema_version` alone is not a file claim.

Below are bounded examples, prioritized for the map/region pipeline. “No matching schema” means no dedicated checked-in JSON Schema found for that tag or the named data family; it does not mean no checks exist, and does not recommend adding schemas to every directory. Ignored files, remote feed branches and external schemas were not read. Repeat the search with the tag or path in the table; check any non-matching filename via the schema's `properties.schema` or the reader, as with the two controls above.

| Data or directory | What was found |
| --- | --- |
| `catalog/competitor-matrix.json:2` | `skippercast.competitor-matrix/1` tag; no matching schema file found. |
| `src/skippercast/coastal/coordinator/policy.json:2` | `coastal-coordinator-policy-v1` tag; no matching schema file found. A reader loads JSON directly (`src/skippercast/coastal/coordinator/bridge_run.py:199–200`). |
| `tests/fixtures/coast/queue/discovery/d01/catalog.json:83` | `coastal-frozen-discovery-catalog-v1` tag; no matching schema file found. This is a fixture, not a live input. |
| `tests/fixtures/coast/queue/plans/plan01/plan.json:1` | `coastal-catalog-acquire-bridge-plan-v1` tag; no matching schema file found. Fixture only. |
| `catalog/ecology/` | No dedicated schema found for ecology dossiers. `src/skippercast/platform/build.py:114` writes an ecology projection with no schema kind. |
| `catalog/shoreline/` | No dedicated SkipperCast schema found for these shoreline GeoJSON inputs. Not the `shore-habitat` contract. See `catalog/shoreline/morro-bay.geojson:1` and `src/skippercast/platform/shoreline.py:119` for a separate writer. |
| `atlas/avila-point-estero-2026-09-20/data/` | The directory has `atlas.json` and no schema file; no matching atlas schema found by the schema inventory below. |

```sh
git grep -lE '"\$schema"[[:space:]]*:|"schema"[[:space:]]*:' origin/main -- '*.json' '*.geojson' ':!*.schema.json'
git ls-files ':(glob)**/*.schema.json'
git ls-tree -r --name-only origin/main -- catalog/ecology catalog/shoreline atlas/avila-point-estero-2026-09-20/data
git grep -nF 'coastal-coordinator-policy-v1' origin/main -- '*.schema.json'
```

## R4. One possible follow-up, not implemented

**Check the forecast index before writing it (estimate: 60–90 minutes).** In `src/skippercast/forecast/build.py`, use the existing `check` path for the assembled index immediately before line 406; leave the manifest, tiles and publication workflow unchanged. Add `tests/unit/test_forecast_index_write_contract.py` with a fixed clock and stubbed per-model build outcomes: a valid index is written, and an invalid assembled row is rejected without replacing an existing index. Existing fixture coverage checks an index against the schema but does not reach that write boundary (`tests/contract/test_schemas.py:107–112,232–235`). Proposed offline acceptance with the test extra installed: `python -m pytest -q tests/unit/test_forecast_index_write_contract.py tests/contract/test_schemas.py`. No provider fetch, map run or publication is needed for that test.
