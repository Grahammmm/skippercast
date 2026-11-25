# Catalog file families and their readers

| Folder | Tracked files | What the files share | Where they are read |
| --- | ---: | --- | --- |
| `catalog/candidates/` | 47 | 46 JSON records pass the source-candidate schema; none pass the separate discovery-lead schema. One Markdown review. | Readiness build, diagnostic, CLI and tests read JSON; no reader found for the review. |
| `catalog/advisor/` | 13 | 13 JSON objects, several different shapes, no checked-in JSON Schema found for them. | Worker imports, fleet tooling, media job and repository check. |
| `catalog/app/` | 2 | Two different JSON objects, no checked-in JSON Schema found for them. | String-table generator and copy lint; coverage UI imports its evidence directly. |
| `catalog/ecology/` | 4 | Four profile dossiers, no checked-in JSON Schema found for them. | Region contract checks, regional package build and search-plan tooling. |
| Directly in `catalog/` | 56 | 54 data files and 2 schema definitions; 50 data files have no identified JSON Schema. | Product, build, research and test reads are separated in R3. |

Read-only audit, 2026-11-21, at staged `origin/main` `34761911d5c44a903873867426f316c7f1e5911c`. All anchors refer to that tree. The tables report repository reads, not deployment status or decisions on any source.

## R1. `catalog/candidates/`

Every JSON file has these 16 base keys (**B**): `access_status`, `access_url`, `documentation_url`, `evidence`, `id`, `limitations`, `name`, `need_ids`, `producer`, `provenance`, `rights`, `schema_version`, `spatial`, `temporal`, `units`, `variables`. **R** = `region_ids`, **S** = `sector_ids`. Counts and keys are from the dated check below. Patterns are disjoint; `NN` means two digits.

| Filename pattern | Files | Common top-level keys (differences) | Source-candidate pass/fail | Discovery-lead pass/fail | Readers |
| --- | ---: | --- | ---: | ---: | --- |
| `cdfw-*.json` | 4 | B + S | 4/0 | 0/4 | C; research reads the 2016 ROV record (`research/scripts/build_central_300_qualification_plan.py:149`). |
| `cnra-*.json` | 1 | B + S | 1/0 | 0/1 | C |
| `csumb-blockNN.json` | 3 | B + R | 3/0 | 0/3 | C, T |
| `csumb-bss-blockNN.json` | 6 | B + S | 6/0 | 0/6 | C, T |
| Other `csumb-*.json` | 2 | B + R + S | 2/0 | 0/2 | C, T; named reads in `research/tests/gis/test_bigcreek_original_grids.py:13` and `research/tests/test_lopez_backscatter_source.py:25`. |
| `gebco-*.json` | 2 | B + R | 2/0 | 0/2 | C; research inventory also reads `gebco-2026-grid` (`research/scripts/inventory_coast_seafloor.py:65,312`). |
| `noaa-*.json` | 14 | B (3 R only, 9 S only, 2 both) | 14/0 | 0/14 | C; named test reads in `research/tests/test_claims_source_rights_do_not_qualify_camera_points.py:13`, `research/tests/test_mendocino_camera_relevance.py:12` and `research/tests/test_noaa_bathymetry_gap.py:17`. |
| `seascapes.json` | 1 | B + R | 1/0 | 0/1 | C |
| `tnc-*.json` | 1 | B + S | 1/0 | 0/1 | C; `research/scripts/build_central_300_qualification_plan.py:148`. |
| `usgs-*.json` | 10 | B (2 R only, 6 S only, 2 both) | 10/0 | 0/10 | C; named reads of `usgs-point-buchon-cmecs` (`research/scripts/build_central_300_qualification_plan.py:183`), `usgs-monterey-1998-em300-original` and `usgs-caldig-v2` (`research/scripts/inventory_coast_seafloor.py:63–64,312`), and `usgs-offshore-aptos-original-grids` (`tests/contract/test_platform.py:210`). |
| `viirs-*.json` | 2 | B + R | 2/0 | 0/2 | C |
| `noaa-acspo-l3s-leo-daily-review.md` | 1 | Not JSON | N/A | N/A | None found; JSON globs skip it. |

**C** (all 46 JSON files): `src/skippercast/platform/readiness.py:93–94` reads the directory for the readiness report; `scripts/coast_diagnostics/rights_coverage.py:80–86` scans it for the rights diagnostic; `tests/contract/test_platform.py:215–217` checks all its JSON using the Python validator. `src/skippercast/platform/__main__.py:22` reads an explicitly named candidate and applies the Python checks (`src/skippercast/platform/candidate.py:17–22`), not a runtime load of the JSON Schema. **T** is the additional CSUMB test glob (`research/tests/test_csumb_source_policy.py:17`). A cache-key hash (`.github/workflows/research-substrate.yml`, search for `csumb-bigcreek-lopez-original-grids.json`) is not a JSON consumer.

The 46 discovery-lead failures are a *comparison against a different contract*, not 46 invalid catalog records. The source-candidate schema requires `schema_version` and at least one location list (`catalog/source-candidate.schema.json:6,317–318`). The discovery-lead schema requires a `schema` discriminator and a different set of fields (`schemas/coastal-discovery-lead-v1.schema.json:3–6,373–386`); the cached inventory reads the lead from a plan descriptor, not from a directory scan (`src/skippercast/coastal/cached_inventory.py:157–168`; `docs/coastal-discovery-intake.md:9–25`). The bridge reads a frozen discovery catalog (`docs/coastal-catalog-bridge.md:4–9,310–311`), and `schemas/sources-catalog.schema.json:7–11` describes the separate `sources.json` register. Neither is the candidate-file contract.

## R2. `catalog/advisor/`, `catalog/app/`, and `catalog/ecology/`

**N/A** means no applicable checked-in JSON Schema identified, so no schema pass/fail count (not a failure or a claim of no validation). All 19 files parsed as JSON objects in the dated key check. The reader column gives direct consumers; examples of test consumers are called out separately where useful.

| Folder and filename pattern | Files | Common top-level keys | Schema pass/fail | Readers |
| --- | ---: | --- | --- | --- |
| `advisor/calendar.json` | 1 | `lead_hours`, `method`, `reviewed_at`, `schema_version`, `slots` | N/A | `server/advisor/social/calendar.ts:20` |
| `advisor/fixture-handles.json` | 1 | `_source`, `fictional`, `own`, `placeholders` | N/A | Repository check, with inline checks: `scripts/check_repository.py:39,90–103`. |
| `advisor/graphics.json` | 1 | `colors`, `daily`, `fonts`, `footer`, `method`, `public`, `reviewed_at`, `roundup`, `schema_version`, `story`, `thumb` | N/A | Media-job input: `scripts/advisor/media_job.py:64,226–227`. |
| `advisor/hashtags.json` | 1 | `angler`, `brand`, `max`, `method`, `regions`, `reviewed_at`, `schema_version`, `species` | N/A | `server/advisor/social/drafts.ts:26` |
| `advisor/keywords.json` | 1 | `description`, `keywords`, `schema_version`, `text_source` | N/A | `server/advisor/social/inbox.ts:27` |
| `advisor/lookalikes.json` | 1 | `method`, `reviewed_at`, `schema_version`, `species` | N/A | `server/advisor/pages/species.ts:10`, `server/advisor/tools/get_species.ts:11`, `server/advisor/vision/species.ts:10` |
| `advisor/port-aliases.json` | 1 | `method`, `ports`, `reviewed_at`, `schema_version` | N/A | `server/advisor/answers/resolve.ts:9`, `server/advisor/pages/port.ts:12`, `server/fleet/pairing.ts:27`, `src/skippercast/fleet/ais/schedule.py:134` |
| `advisor/protected.json` | 1 | `method`, `reviewed_at`, `schema_version`, `species` | N/A | `server/advisor/vision/species.ts:11` |
| `advisor/public-grounds.json` | 1 | `method`, `regions`, `reviewed_at`, `schema_version` | N/A | `server/advisor/answers/advice.ts:14` |
| `advisor/species-extra.json` | 1 | `method`, `reviewed_at`, `schema_version`, `species` | N/A | `scripts/advisor/import-rules.mjs:40`, `server/advisor/admin/rules.ts:27`, `server/advisor/answers/advice.ts:15`, `server/advisor/answers/resolve.ts:12`, `server/advisor/answers/rules.ts:10`, `server/advisor/tools/get_species.ts:10`, `server/advisor/vision/species.ts:9` |
| `advisor/species-pages.json` | 1 | `method`, `reviewed_at`, `schema_version`, `species` | N/A | `server/advisor/pages/port.ts:11`, `server/advisor/pages/species.ts:9` |
| `advisor/species-synonyms.json` | 1 | `method`, `reviewed_at`, `schema_version`, `species` | N/A | `server/advisor/answers/fishid.ts:27`, `server/advisor/answers/resolve.ts:10` |
| `advisor/strings.json` | 1 | `description`, `schema_version`, `strings` | N/A | `server/advisor/strings.ts:10` |
| `app/region-coverage.json` | 1 | `audit`, `audit_csv_sha256`, `checked_at`, `columns`, `regions`, `source_revision` | N/A | `web/region-coverage.ts:2`; test: `tests/test_region_coverage.mjs:5`. |
| `app/strings.json` | 1 | `description`, `schema_version`, `strings` | N/A | Generator `scripts/build_landing_strings.mjs:44–45`, called by `scripts/client-build.mjs:197`; lint `scripts/check_copy.mjs:259,291–296`. The app reads the generated tables (`web/i18n.ts:2–4`), not the source JSON directly. |
| `ecology/california-{central,northern,san-francisco}.json` | 3 | `bounds`, `id`, `interpretation`, `jurisdictions`, `profiles`, `reviewed_at`, `schema_version` | N/A | E; example bindings at `regions/morro-bay/region.json:555`, `regions/bodega-point-reyes/region.json:352`, `regions/point-reyes-pigeon/region.json:335`. |
| `ecology/california-southern.json` | 1 | Same seven keys plus `source_review` | N/A | E; `regions/san-diego/region.json:437`; test: `tests/test_southern_species.mjs:18`. |

**E** = selected by `ecology_profile`: `src/skippercast/platform/contracts.py:62–65,319–326` checks the selected profile, `src/skippercast/platform/build.py:102–104` loads it for the package build, and `scripts/build_search_plans.py:58–60` reads its `profiles`. `schemas/region.schema.json:239,256` checks the selector ID, not the dossier. The five Advisor files with the same `species` envelope are not interchangeable: for example the extra-species reader expects rows and the lookalike reader uses a lookup by species key (`server/advisor/vision/species.ts:9–11,92–96`).

## R3. Direct files missing a reader or schema

Direct children of `catalog/` only. IDs below are filenames without `.json`; no record bodies are quoted. “No reader found” means no file-specific code consumer found in the tracked tree after checking names, split paths and the relevant globs; a reference in prose is not a read. Test-only, generated-output comparisons and research reads are identified rather than counted as production readers. “No schema found” refers to a checked-in JSON Schema applicable to the data, not to inline validation or tests.

| IDs | Count | Reason |
| --- | ---: | --- |
| `competitor-matrix`, `usgs-monterey-geology` | 2 | No schema or reader found. `competitor-matrix` has a prose reference (`reports/SKIPPERCAST-COMPETITIVE-MATRIX.md:3`); filename probe below for both. |
| `coast-seafloor-inventory` | 1 | No schema found; generator output, read only for a staleness comparison (`research/scripts/inventory_coast_seafloor.py:39,1127,1133`). |
| `layer-inventory`, `station-failover` | 2 | No schema found; test readers (`tests/test_layer_freshness.mjs:52`, `tests/contract/test_station_failover_evidence.py:13,31`). `web/map/freshness.ts:2,18` cites the former, not an import. |
| `csumb-bss-deeper-native-sources`, `csumb-bss-native-sources`, `csumb-bss-remaining-native-sources`, `csumb-morro-avila-native-sources`, `csumb-scc-adjacent-native-sources`, `csumb-scc-coast-gap-native-sources`, `csumb-scc-conception-native-sources`, `csumb-scc-estero-native-sources`, `csumb-scc-gap-native-sources`, `csumb-scc-midcoast-native-sources`, `csumb-scc-native-sources`, `csumb-scc-outer-shelf-native-sources`, `csumb-scc-shelf-next-native-sources`, `csumb-scc-south-native-sources`, `csumb-slate-scc-native-sources` | 15 | No schema found; research inventory reads by glob (`research/scripts/inventory_coast_seafloor.py:68,338–340`). |
| `monterey-original-bag-overlap-bindings`, `noaa-central-deepwater-source-screen`, `pigeon-w00614-original-class-binding` | 3 | No schema found; research reads in `research/scripts/build_central_source_queue.py:160,337` and `research/scripts/screen_noaa_vr_source_depth.py:131,147`. |
| `usgs-central-sediment-source`, `usgs-context-holds`, `usgs-ofr0385-san-miguel`, `usgs-sansimeon-geology`, `usgs-seafloor-sources` | 5 | No schema found; research inputs (`research/scripts/build_central_sediment_context.py:235`, `research/scripts/build_usgs_doi_context.py:116`, `research/scripts/audit_san_miguel_original_habitat.py:135`, `research/scripts/audit_sansimeon_bedrock_overlap.py:170`, `research/scripts/import_usgs_seafloor_character.py:104`). |
| `csumb-bss-source-leads`, `csumb-scc-source-leads`, `noaa-survey-lead-holds`, `usgs-ds781-metadata-review`, `usgs-ds781-source-leads` | 5 | No schema found; readiness build input, including a constructed CSUMB filename (`src/skippercast/platform/readiness.py:67–80`). |
| `bluetopo-sample` | 1 | No schema found; research prefetch input (`research/scripts/build_coast_prefetch_plan.py`, search for `bluetopo-sample.json`); seafloor restore also references the path (`src/skippercast/seafloor/restore.py:87`). |
| `classified-habitat-policy`, `habitat-rules`, `reaches`, `seafloor-rough-first`, `seafloor-scope`, `seafloor-screen` | 6 | No schema found; seafloor tooling uses these (look up basenames below in `src/skippercast/seafloor/`; see `classified_habitat.py:41,327`, `adopt.py:45`, `rough_first.py:42`, `scope_paths.py:10`, `screen.py:74` there). |
| `coastal-sectors`, `coasts`, `feed-health`, `home-ports`, `primary-strategies`, `recent-intel-watchlist`, `search-methods`, `species`, `station-locations`, `targets` | 10 | No schema found; product/build/tool references, respectively: `src/skippercast/platform/candidate.py:48`, `src/skippercast/platform/coasts.py:38`, `server/watchdog.ts:27`, `src/skippercast/fleet/config.py:313`, `server/advisor/answers/advice.ts:10`, `scripts/collect_recent_intel.py:17`, `scripts/build_search_plans.py` (`search-methods.json`), `server/advisor/vision/species.ts:7`, `web/map/stations.ts:4`, `server/advisor/vision/species.ts:8`. The fleet-region schema's home-port reference is not a schema for `home-ports` (`schemas/fleet-region.schema.json:5,102`). |
| `source-candidate.schema` | 1 | Schema definition, not a data document. No production/test loader found for the schema file itself; the candidate CLI uses inline validation (`src/skippercast/platform/__main__.py:22`; `src/skippercast/platform/candidate.py:17–22`). Read explicitly for the R1 audit. |

The other five direct files are not missing a schema or a reader: `sources`, `data-needs`, `launch-points` and `surveys` have corresponding schema files and file-specific reads (`tests/contract/test_schemas.py:86–87`, `src/skippercast/platform/launch_points.py:62–64`, `schemas/launch-points.schema.json:2–7`, `src/skippercast/seafloor/manifest.py:10–11,47–61`). For `surveys`, the local schema validates individual rows; `survey.schema` is the schema definition that loader reads.

## R4. Follow-up

None needed for this report. The checks distinguish the two candidate contracts and locate the current readers without requiring a migration, reader change, or catalogue decision.

## Reproduce the inventory

Run from the repository root with `origin/main` at the pinned SHA above (or substitute that SHA for the ref). These are reads only:

```sh
git ls-tree -r --name-only origin/main catalog/candidates catalog/advisor catalog/app catalog/ecology
git ls-tree origin/main:catalog
git ls-tree -r --name-only origin/main schemas src/skippercast/coastal/resources catalog
git grep -nE 'catalog/(candidates|advisor|app|ecology)|GRAPHICS|FIXTURE_HANDLES|CSUMB_GLOB' origin/main -- src scripts tests server web research .github
git grep -n -F -e '<basename>.json' origin/main -- src scripts tests server web research .github reports
git grep -n -E 'ecology_profile.*california' origin/main -- 'regions/*/region.json'
```

For the 2026-11-21 key and validation read, parse each tracked `.json` blob from `git show origin/main:<path>` with `json.loads`, sort its top-level keys and intersect keys within each row group. The dated read returned 46/46 candidate objects with B and at least one location list, 13/13 Advisor objects, 2/2 app objects and 4/4 ecology objects. For each candidate object, run `jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).is_valid(object)` separately with `catalog/source-candidate.schema.json` and `schemas/coastal-discovery-lead-v1.schema.json`; the dated read returned 46 pass / 0 fail and 0 pass / 46 fail, respectively. Exclude the Markdown file from both denominators. No network or source discovery run was used.
