# Region directory completeness

| Question | Result | Evidence |
| --- | --- | --- |
| Required source files | All 22 coastal packages have `region.json`; both fleet folders have `fleet.json`. Southern California also has its conditionally required reviewed bottom-source file. No required in-folder file is missing. | R1 |
| Fewer than three files | Six coastal drafts have two files and omit the optional `render.json`; two fleet folders have one file each and follow a different contract. | R2 |
| Index mismatches | No indexed coastal ID lacks a folder. The six drafts and two fleet folders appear in none of the published, feed or jurisdiction review lists checked. | R3 |

Source snapshot: local `origin/main` at `34761911d5c44a903873867426f316c7f1e5911c`, read offline on 2026-11-21 UTC. All line references use that commit; the two feed snapshots are pinned separately in R3.

## R1. Every folder and file

`docs/region-pipeline.md:34–40`, `docs/regions.md:7–12` and `schemas/region.schema.json:4–12` name `region.json` as the coastal source file; the schema's required keys are inside that file, not a list of sibling files. `src/skippercast/platform/build.py:90–101,115–129,169–176` distinguishes source configs from generated and referenced assets under `dist/`. The fleet contract instead names `fleet.json` (`schemas/fleet-region.schema.json:4–12`; `src/skippercast/fleet/config.py:466`). Southern California's `assets.target_qualification` (`regions/southern-california/region.json:848`) is the only populated binding of its kind in this inventory, so `bottom-sources.reviewed.json` is required there by `src/skippercast/platform/qualified_scope.py:281–296,317–325`. The coast recipe and render recipe have their own schemas, not universal requirements for `region.json` packages (`schemas/coast-recipe-v1.schema.json:4–8`; `tests/unit/test_coast_recipe_statewide.py:72–83`; `src/skippercast/relief/render_config.py:16–25`). “Extra” below means present beyond required files, not invalid or safe to remove.

Reproduce the file list with `git ls-tree -r --name-only 34761911d5c44a903873867426f316c7f1e5911c regions`. Validation read on 2026-11-21 UTC: **61 schema passes, four JSON parse passes with no matching schema, zero errors**. The offline probe parsed each file and used `next(_validator(kind, root / 'schemas').iter_errors(document), None)` from `src/skippercast/validate.py:127–141`, with installed `jsonschema` 4.26.0. File-to-kind mapping: `coast.json` → `coast-recipe-v1`, `region.json` → `region`, `render.json` → `sc-render-v1`, `fleet.json` → `fleet-region` (`src/skippercast/validate.py:40–63`). “Pass” means shape only, not semantic, coverage or release validation (`schemas/region.schema.json:5`; `schemas/fleet-region.schema.json:5`). The four `parse pass` cells have no matching registered JSON Schema; their separate consumers or writer are `src/skippercast/platform/qualified_scope.py:317–325`, `research/scripts/build_socal_habitat.py:29,460`, and `research/scripts/build_reef_context.mjs:26`.

| Folder under `regions/` | Files present and validation per file | Required here | Missing required | Extra |
| --- | --- | --- | --- | --- |
| `CA` | `fleet.json` pass | `fleet.json` | None | None |
| `OR` | `fleet.json` pass | `fleet.json` | None | None |
| `big-sur-coast` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `bodega-point-reyes` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `cambria-san-simeon` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `channel-islands-north` | `coast.json` pass; `region.json` pass | `region.json` | None | `coast.json` |
| `crescent-city` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `fort-bragg-point-arena` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `humboldt-bay-cape-mendocino` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `monterey-point-sur` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `morro-bay` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `outer-islands-borderland` | `coast.json` pass; `region.json` pass | `region.json` | None | `coast.json` |
| `point-arena-bodega` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `point-arguello-conception` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `point-reyes-pigeon` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `san-diego` | `coast.json` pass; `region.json` pass | `region.json` | None | `coast.json` |
| `san-pedro-orange-county` | `coast.json` pass; `region.json` pass | `region.json` | None | `coast.json` |
| `santa-barbara-channel` | `coast.json` pass; `region.json` pass | `region.json` | None | `coast.json` |
| `santa-cruz-monterey-bay` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `santa-monica-palos-verdes` | `coast.json` pass; `region.json` pass | `region.json` | None | `coast.json` |
| `shelter-cove-north-mendocino` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `south-big-sur-san-simeon` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |
| `southern-california` | `bottom-sources.reviewed.json` parse pass; `habitat-receipts.json` parse pass; `habitat-sources.json` parse pass; `reef-records.json` parse pass; `region.json` pass; `render.json` pass | `region.json`, `bottom-sources.reviewed.json` | None | `habitat-receipts.json`, `habitat-sources.json`, `reef-records.json`, `render.json` |
| `trinidad-klamath` | `coast.json` pass; `region.json` pass; `render.json` pass | `region.json` | None | `coast.json`, `render.json` |

## R2. Fewer than the majority

The R1 tree count is 15 folders with three files, six with two, two with one, and one with six. `channel-islands-north`, `outer-islands-borderland`, `san-diego`, `san-pedro-orange-county`, `santa-barbara-channel` and `santa-monica-palos-verdes` have the usual `coast.json` and `region.json` but no `render.json`. For that exact path, the loader handles `except FileNotFoundError: return None` (`src/skippercast/relief/render_config.py:20–24`, two lines quoted together). It uses the default style when no render config is present (`:35–38`). `CA` and `OR` are also below three, but `schemas/fleet-region.schema.json:5` expressly describes “`regions/<STATE>/fleet.json`: a state-level charter fleet region”. Southern California has more than three files despite having no `coast.json`; that is not a coastal package contract failure (R1).

## R3. Index and jurisdiction cross-check

Let **D** be the six coastal draft folders named in R2 plus the two fleet folders `CA` and `OR`. Draft status can be reproduced with `git grep -n '"status": "draft"' 34761911d5c44a903873867426f316c7f1e5911c -- 'regions/*/region.json'`. On 2026-11-21 UTC, the offline set comparison against the R1 folder names returned:

| Source and field read | Distinct coastal IDs | Indexed IDs without a folder | Folders absent from this list |
| --- | ---: | --- | --- |
| `dist/regions/index.json:1` — `regions[].id` and `default_region` | 16 | None | D |
| Local `origin/data` snapshot `c8a042402dab5933d8e8921fe6150e166bb98c71:regions/index.json` — `regions[].region_id` | 16 | None | D |
| Local `origin/conditions` snapshot `4e87cb158b4462d2c333659573653d8584bb3f6e:regions/index.json` — `regions[].region_id` | 16 | None | D |
| `jurisdictions/reviews/*.json` — union of `reviewed_regions[].id` | 13 | None | D plus `bodega-point-reyes`, `point-arena-bodega`, `point-reyes-pigeon` |
| `dist/` regulation assets named by `jurisdictions/*.json` — union of `reviewed_regions[].id` | 16 | None | D |

**Folders no checked index lists: D.** The published, two feed and regulation-asset sets are identical; the three San Francisco packages absent from the separate review-record list are present in `dist/data/regulations-san-francisco.json:30–50`. Read the feed snapshots from an existing local object store with `git show <feed-sha>:regions/index.json`; they are not live claims or the main-branch test fixture (`schemas/regions-index.schema.json:5,18–30`; `schemas/published-regions.schema.json:5,10–23`). Normal build and refresh discovery skip drafts (`src/skippercast/platform/build.py:90–95`; `scripts/refresh_regions.py:146–159`), and fleet IDs are in a separate namespace (`schemas/fleet-region.schema.json:12`).

The five top-level jurisdiction `id` values (`california-central`, `california-mendocino`, `california-northern`, `california-san-francisco`, `california-southern`) are jurisdiction IDs, not missing region folders. Read `jurisdictions/*.json` for `id` and `regulations_asset`, and compare each coastal `region.json`'s `jurisdiction_id`: all 22 bindings resolve to those five files (offline read, 2026-11-21 UTC; `schemas/region.schema.json:26–27`; `schemas/jurisdiction.schema.json:5–11`; `src/skippercast/platform/build.py:39–43`). For reverse listings, check only `reviewed_regions[].id`, not the jurisdiction filenames or unrelated IDs (`src/skippercast/pipeline/regulations.py:105`). Drafts can bind a jurisdiction without appearing in its review list.

## R4. Follow-up

None needed for directory completeness. R1 found no missing required source file, R2's shorter folders match their loaders, and R3 found no orphan indexed ID in the snapshots checked. This does not make a coverage, rights, review or publication determination.
