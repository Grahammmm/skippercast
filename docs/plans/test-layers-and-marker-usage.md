# Python test layers, marks and skips

| Finding | At the audited main |
| --- | --- |
| Python collection | 16,319 items across six layers (R1). `tests/coast/`, `tests/fixtures/` and loose files are not additional Python layers (R3). |
| Custom marks | `gis` 4,066; `claims` 1,311; `network` 0; `host_archive` 6 (R1). An item can carry more than one mark. |
| Without GIS | Normal discovery omits both `gis/` directories before importing their modules. Outside them, explicit marks and import/skip guards matter too. The simulated no-survey collection with `-m 'not gis'` found 48 fewer items than the same filter with GIS installed (R2). |
| Without network | The network opt-in exists but no item uses it. Missing cached originals and host archive opt-in are separate conditions, not connectivity checks (R2). |

Source pin: staged `origin/main` at `34761911d5c44a903873867426f316c7f1e5911c`. File:line references below refer to that tree. Counts are from offline collection on 2026-11-21 (Linux, Python 3.12.3, pytest 9.1.1, existing survey/ocean/publish/test dependencies, archive/network opt-ins unset). Collection imports modules; it does not run test bodies or fixtures. The counts aren't pass, fail or runtime skip totals.

## R1. Marks and CI selection

| Mark | Declared / applied | Unit | Contract | Integration | GIS | Claims | Claims GIS | Total | CI marker filter |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `gis` | `pyproject.toml:86`; directory hook `tests/_support.py:90-91`; explicit marks also occur outside `gis/` | 559 | 0 | 0 | 2,991 | 41 | 475 | 4,066 | `check` deselects with `-m "not gis"` (`.github/workflows/ci.yml:312-326,344-359`). `survey-tests` uses paths, not `-m gis` (`:143-155`). |
| `claims` | `pyproject.toml:87`; `tests/_support.py:88-89`, `research/tests/conftest.py:14-15` | 0 | 0 | 0 | 0 | 836 | 475 | 1,311 | No filter by `claims`; `check` still excludes the subset also marked `gis`. |
| `network` | `pyproject.toml:88`; guard `tests/_support.py:92-93` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | No marker filter; no selected item to skip. |
| `host_archive` | `pyproject.toml:89`; six explicit marks listed in R2 | 6 | 0 | 0 | 0 | 0 | 0 | 6 | No marker filter; the root hook adds a skip by default (`conftest.py:74,87-95`). |
| `parametrize` | pytest built-in; e.g. `tests/contract/test_coastal_sectors_package_index.py:11` | 5,896 | 67 | 0 | 1,583 | 302 | 121 | 7,969 | None. |
| `filterwarnings` | pytest built-in; `tests/gis/test_coastal_derived_array_snapshot.py:187` | 0 | 0 | 0 | 10 | 0 | 0 | 10 | None. |
| `skip` | pytest built-in; actual items marked by `conftest.py:87-91` | 6 | 0 | 0 | 0 | 0 | 0 | 6 | None; this counts item marks, not `pytest.skip()` or `unittest` skips. |
| `skipif` | pytest built-in; four module marks listed in R2 | 63 | 0 | 0 | 5 | 0 | 0 | 68 | None; marked even on Linux, where the predicates are false. |
| `xfail` | pytest built-in; `tests/unit/test_f06_14_audit.py:72`, `test_f07_07_audit.py:72`, `test_f28_12_audit.py:75` in the same directory | 3 | 0 | 0 | 0 | 0 | 0 | 3 | None; expected failures, not skips (`scripts/pytest_report.py:10-13,91-95`). |
| All collected items (not the sum of mark rows) | Discovery: `pyproject.toml:78-84` | 11,295 | 572 | 150 | 2,991 | 836 | 475 | 16,319 | |

Workflow cross-check: `git grep -nE 'pytest|PYTEST_ADDOPTS|SKIPPERCAST_NETWORK|SC_ARCHIVE_TESTS|run_core_tests' -- .github/workflows .github/actions`. The `survey-tests` coast part uses just two files in `tests/gis/`; rest ignores those two and discovers both roots. Both set `SKIPPERCAST_REQUIRE_GIS=1` and use strict skip reporting (`.github/workflows/ci.yml:93-105,121-122,143-163`); `survey-science` is the rollup (`:65-92`). The basemap job runs a named file (`.github/workflows/basemap.yml:50`). Scheduled research jobs call `unittest` by module and do not apply pytest marker selection (e.g. `.github/workflows/research-fish-survey.yml:21,73` and `.github/workflows/research-substrate.yml:23,335`; `git grep -n 'python -m unittest' -- .github/workflows`).

To reproduce the item census, use `python -m pytest --collect-only -q -p no:cacheprovider` from the pinned root with the installed extras from `.github/workflows/ci.yml:121-122`; leave both opt-ins unset. The count pass used those arguments and a scratch `pytest_collection_finish(session)` hook: for each `item` in `session.items`, bucket by `item.path` and count each distinct `m.name` in `item.iter_markers()` once. Parametrized cases count separately; repeated GIS marks on one item count once. Registration is `pytest --markers`. Use `git grep -nE 'pytest\.mark\.|pytestmark|add_marker' -- tests research/tests conftest.py` to find source uses and distinguish actual marks from strings used as test data.

## R2. What does not run, and why

| Layer | Source | Condition and affected tests |
| --- | --- | --- |
| GIS and Claims GIS | `tests/conftest.py:10-15`, `research/tests/conftest.py:10-15`, `tests/_support.py:45-76` | Normal discovery ignores any `gis/` directory if any of `affine`, `h5py`, `laspy`, `lazrs`, `lerc`, `numpy`, `pyproj`, `pypdf`, `rasterio`, `scipy`, `shapefile` or `shapely` has no import spec (3,466 items in the full collection). Not a pytest skip. `SKIPPERCAST_REQUIRE_GIS=1` removes the discovery exclusion, not the individual guards below; missing unconditional imports can then fail collection. An explicit test-file argument can bypass the discovery exclusion. `jsonschema` is shared, not a GIS-discovery dependency. |
| Unit and Claims outside `gis/` | `tests/unit/test_coast_local_screen.py:358-735`, `tests/unit/test_f27_01_audit.py:46`, `research/tests/test_coast_mvp_contours.py:12`, `research/tests/test_coast_mvp_seams.py:6`; `.github/workflows/ci.yml:359` | `-m 'not gis'` also deselects explicitly marked items outside GIS directories, including individual parameter cases. This filter runs after imports. See R1 for the 559 Unit and 41 Claims items marked `gis` in the full collection. |
| Both trees | `tests/_support.py:54-55,79-93` | For an item with keyword `network`, add `skip` unless `SKIPPERCAST_NETWORK=1`. No test currently qualifies; there is no network reachability probe in the gate. |
| Unit | `conftest.py:74-95`; `tests/unit/test_coastal_four128_admission.py:365`, `test_coastal_four128_block_selection.py:227`, `test_coastal_four128_budget.py:292,516`, `test_coastal_four128_mask_topology.py:238`, `test_coastal_managed_output_overlap.py:166` (same directory) | Unless `SC_ARCHIVE_TESTS=1`, skip six archive cases: signed bytes/projection, candidate table, signed budget documents, attempt ledgers, original signed ledger, preserved overlap ledger. With opt-in the audit hook only permits archive access during a marked test's protocol, not during collection. |

**Collection comparison (2026-11-21).** With GIS installed, the `-m 'not gis'` probe returned `12253/16319 tests collected (4066 deselected)`. With GIS imports and lookup hidden, it returned `12205/12753 tests collected (548 deselected)` plus 14 module skips. This second arm simulates missing packages: before collecting, it makes `find_spec` return `None` and imports raise `ModuleNotFoundError` for the GIS list and `eccodes`, `netCDF4`, `cftime`; it does not modify repository files. Comparing node IDs, nine Unit modules account for the 48 additional omissions with the same filter: `test_f05_13_audit.py` (3), `test_f07_15_audit.py` (3), `test_f26_12_audit.py` (5), `test_f27_05_audit.py` (3), `test_f27_08_audit.py` (2), `test_f27_10_audit.py` (11), `test_f28_05_audit.py` (2), `test_f32_01_audit.py` (8), `test_perf_script_args.py` (11). The other five module skips were already excluded by the filter with GIS installed. Setup and test-body conditions below were read from source, not exercised.

### Dependency guards inside modules

`importorskip` rows name each import guard. “Module” means all cases in that file go missing at collection if that guard fires; otherwise the guard is reached only by the named test, helper or fixture. Source sweep: `git grep -niE 'skipif|skipunless|importorskip|skipTest|pytest\.skip|mark\.skip' -- 'tests/*.py' 'research/tests/*.py' conftest.py`. Strings testing the report/determinism scripts are not executable skip sites (`tests/unit/test_pytest_report.py:16-19,179-184`, `tests/unit/test_check_test_determinism.py:102-115`).

| Layer | Source | Missing dependency / scope |
| --- | --- | --- |
| Claims GIS | `research/tests/gis/test_check_terrain_acceptance_render.py:11-13` | Module: NumPy, Rasterio, jsonschema. |
| GIS | `tests/gis/test_build_depth_contours.py:43,53,171` | Rasterio in the standalone public refusal case and `_run_builder`; h5py in `_bag`. |
| GIS | `tests/gis/test_build_survey_zone.py:16-20` | NumPy, Rasterio, Shapely (`shapely.geometry` too) or pyproj in `region_inputs`; its five callers are at `:90-155`. |
| GIS | `tests/gis/test_coastal_netcdf_native.py:14-15` | Module: h5py, Rasterio. |
| GIS | `tests/gis/test_coastal_partial_support_mapping.py:14-16` | Module: affine, pyproj, Shapely. |
| GIS | `tests/gis/test_coastal_stage_terrain_horizon.py:2-3`, `tests/gis/test_coastal_terrain_dispatch_adoption_guards.py:2-3` | Both modules: NumPy, Rasterio. |
| GIS | `tests/gis/test_coastal_terrain_demo_acceptance_shape.py:2` | Module: NumPy. |
| GIS | `tests/gis/test_coastal_terrain_demo_duplicate_json.py:16-17`, `tests/gis/test_coastal_terrain_demo_json.py:18-19` | Both modules: NumPy, Rasterio. |
| GIS | `tests/gis/test_coastal_window_set_tiling.py:15-16,25` | Module: pyproj, Rasterio (checked twice). |
| GIS | `tests/gis/test_contained_uncertainty_metadata.py:9-12` | Module: affine, pyproj, Rasterio, Shapely. |
| GIS | `tests/gis/test_ec_verify.py:13`, `tests/gis/test_ec_verify_inputs.py:9` | Both modules: Rasterio. |
| GIS | `tests/gis/test_forecast_negative_scan.py:7` | Module: ecCodes GRIB decoder (not part of the GIS discovery list). |
| GIS | `tests/gis/test_nearshore_grid_orientation.py:24-25`, `tests/gis/test_preflight_native_grid.py:24-25` | NumPy/Rasterio in the orientation test and in the preflight `_tif` helper, respectively. |
| GIS | `tests/gis/test_relief_contours.py:18,809` | Rasterio in `builder` and the unreviewed-licence case. |
| GIS | `tests/gis/test_relief_render_tiles.py:27-29,74-76,118-120` | NumPy/Rasterio/SciPy in the seam, certified zoom and mosaic land-mask tests. |
| GIS | `tests/gis/test_relief_stage_adapters.py:37-40,196` | NumPy, Rasterio, `shapely.geometry`, jsonschema in `test_public_stage_chain`. |
| GIS | `tests/gis/test_search_plans_polygon_parts.py:5`, `tests/gis/test_terrain_resolution_admission.py:5`, `tests/gis/test_terrain_small_grids.py:7` | Modules: `shapely.geometry` in the first; SciPy in the last two. |
| GIS | `tests/gis/test_bottom_targets.py:11-17,80`; `tests/gis/test_search_plan_geometry.py:4-9`, `tests/gis/test_search_plans_inputs.py:6-15` | `unittest` class guards: failed GIS imports in `NativeQualificationTests`; failed Shapely `shape` import in `SearchGeometry` and `SearchPlanInputs`. |
| Unit | `tests/unit/test_coast_local_screen.py:360,397,409,420,436,447,461,473,487,496,519,529,547,559,581,594,606,622,688,699,708,724,735` | Rasterio in 23 individually marked test bodies at the cited lines. |
| Unit | `tests/unit/test_coastal_bridge_run.py:42-44`, `tests/unit/test_f11_16_audit.py:30-35`, `tests/unit/test_sc46_regression.py:38-53,71,104,109,128,145-146,157` | pyproj in `world`; Shapely/pyproj in the autouse `_survey_stack`; pyproj in `normalized_block` (used directly and via the `block` fixture). |
| Unit | `tests/unit/test_f05_09_audit.py:11-16`, `tests/unit/test_f05_13_audit.py:26-28`, `tests/unit/test_f07_15_audit.py:17-21` | Module guards respectively: `shapely.geometry` and pyproj; direct `pytest.skip` if NumPy has no spec (worker dependency); NumPy, Rasterio, pyproj, Shapely, `rasterio.transform`. |
| Unit | `tests/unit/test_f26_05_audit.py:7-9`, `tests/unit/test_f26_08_audit.py:7-10`, `tests/unit/test_f26_12_audit.py:10-12` | Module guards respectively: pyproj/Shapely; lerc/NumPy/pyproj; Rasterio/pyproj/Shapely. |
| Unit | `tests/unit/test_f27_05_audit.py:6-7`, `tests/unit/test_f27_08_audit.py:10-14`, `tests/unit/test_f27_10_audit.py:8-9` | Module guards respectively: Shapely/pyproj; NumPy/laspy/shapefile/pyproj/`shapely.geometry`; NumPy/Rasterio. |
| Unit | `tests/unit/test_f28_05_audit.py:8-13`, `tests/unit/test_f28_12_audit.py:16-17`, `tests/unit/test_f32_01_audit.py:8` | Module guards respectively: NumPy/Rasterio/pyproj/Shapely/`rasterio.io`/`rasterio.transform`; Shapely; Shapely. |
| Unit | `tests/unit/test_perf_script_args.py:11`, `tests/unit/test_protected_screen_verdicts.py:11-15` | Both modules: NumPy. |
| Unit | `tests/unit/test_region_review.py:253-257` | NumPy/Rasterio in `test_real_ec3_bag_acquisition_handoff`. |
| Unit | `tests/unit/test_sc163_worker_json.py:25,76`, `tests/unit/test_sca_050.py:20-21`, `tests/unit/test_wave_ensemble_latitudes.py:28`, `tests/unit/test_wave_ensemble_shapes.py:13,31,141`, `tests/unit/test_wave_ensemble_units.py:78,87,101` | `unittest` guards if NumPy is missing: worker JSON, forecast generation (also marked `gis`), wave latitudes, two wave-shape classes and three wave-unit methods. |
| Unit | `tests/unit/test_forecast_ensemble.py:111`, `tests/unit/test_forecast_ensemble_axes.py:39,69,129`, `tests/unit/test_forecast_ensemble_mask_values.py:39`, `tests/unit/test_pipeline_intelligence.py:48` | `unittest` guards if ecCodes is missing: GRIB build, axes/seams/publication, mask and pipeline-probability checks. |
| Contract | `tests/contract/test_fleet_region.py:42,111,149,164`, `tests/contract/test_region_contract.py:228,260`, `tests/contract/test_schemas.py:41,73,125,258`, `tests/contract/test_seafloor_manifest.py:152`, `tests/contract/test_shore_habitat.py:85,386,400` | jsonschema unavailable (seafloor checks for `Draft202012Validator`); guards apply to the decorated classes/methods and the fleet bad-source-list case. |
| Unit | `tests/unit/test_chart_files.py:60`, `tests/unit/test_f11_09_audit.py:33`, `tests/unit/test_fleet_agent.py:35-37,190`, `tests/unit/test_fleet_config.py:70`, `tests/unit/test_fleet_profile.py:220`, `tests/unit/test_validate_listing.py:19` | jsonschema unavailable: schema checks at the cited methods/classes. |
| Unit | `tests/unit/test_advisor_media_job.py:25-33,331,399,541,595`; `tests/unit/test_http.py:37-49` | Missing ffmpeg or ffprobe skips video-strip cases; missing Pillow or pillow-heif skips image/orientation/graphic cases; unavailable OpenSSL test certificates skip TLS fixture consumers (local loopback, not an internet failure). |
| GIS and Integration | `tests/gis/test_forecast_build.py:77`; `tests/integration/test_publish_branch_snapshot.py:16`, `tests/integration/test_publish_r2.py:98`, `tests/integration/test_r2_snapshots.py:281` | Missing Node skips sampler agreement; missing Git skips branch snapshots; missing moto or boto3 skips mocked R2 integration/SDK classes. |

### Platform, local files and history

| Layer | Source | Condition and affected scope |
| --- | --- | --- |
| GIS and Unit | `tests/gis/test_coastal_catalog_bridge_acquire.py:27`; `tests/unit/test_coastal_group_state_collision.py:50`, `tests/unit/test_coastal_operations.py:20`, `tests/unit/test_f06_05_audit.py:17` | `skipif` on platforms other than Linux: requires `/proc` for supervisors/coordinator; 5, 50, 8 and 5 collected items respectively. |
| Contract and Unit | `tests/contract/test_atlas_export_atomic.py:108`; `tests/unit/test_coastal_source_guard.py:81`, `tests/unit/test_fleet_install_script.py:39,127`, `tests/unit/test_fleet_file_import_read.py:108`, `tests/unit/test_noaa_survey_products_inputs.py:144`, `tests/unit/test_report_regulations_decode.py:96,114` | Respectively: `renameat2` unavailable; no `os.mkfifo`; missing Bash (or Bash/Git/non-POSIX for install-run class); root bypasses mode-000; user bypasses directory permissions; Python integer digit cap disabled. |
| GIS | `tests/gis/test_bottom_targets.py:125-126`, `tests/gis/test_seafloor_grid.py:84-85` | Missing compiled original BAG manifest or private reference grid. |
| Claims GIS | `research/tests/gis/test_claims_block02_camera_points_cannot_qualify_empty_cells.py:63,76`, `research/tests/gis/test_claims_block02_class_accuracy_is_not_rock_evidence.py:18`, `research/tests/gis/test_claims_block03_closure_screen_stays_private.py:37`, `research/tests/gis/test_claims_block03_datum_probe_stays_unqualified.py:17-18` | Missing cached originals for the camera and class checks; missing originals or fresh official snapshots for the closure replay; maintainer-only review blocks absent for the datum probe. |
| Claims GIS | `research/tests/gis/test_claims_point_buchon_block_a3_year_not_assigned_to_cells.py:26`, `research/tests/gis/test_point_buchon_2009_habitat_crosssurvey.py:27`, `research/tests/gis/test_point_buchon_original_pair.py:27,34` | Missing pinned originals staged by monthly jobs for the trackline/cross-survey checks; missing bathymetry or character metadata in the two original-pair tests. |
| Claims GIS | `research/tests/gis/test_claims_point_st_george_original_lead_stays_held.py:92`, `research/tests/gis/test_monterey_rov_research_overlap.py:11`, `research/tests/gis/test_nbs_hard_footprint_tiles.py:24`, `research/tests/gis/test_nbs_modeling_tile.py:61`, `research/tests/gis/test_point_conception_control_reports.py:14-15`, `research/tests/gis/test_point_estero_original_pair.py:27-28` | Respectively: private coordinate fixture absent; pinned original ROV release absent; NOAA scheme not cached; original NOAA assets not cached; NOAA PDFs not cached; original audit not built. These are local-input checks, not connectivity checks. |
| Claims | `research/tests/test_coastal_snapshot_inventory.py:232-236` | Retained coastal source snapshot absent; committed inventory checked separately. |
| Unit | `tests/unit/test_coastal_four128_block_selection.py:227-233`, `tests/unit/test_coastal_managed_output_overlap.py:166-172` | After archive opt-in, the historical pre-scan receipt or preserved attempt-5 ledger can still be absent. These two test/reason pairs are allowed by `scripts/pytest_report.py:54-61`. |
| Unit | `tests/unit/test_subsystem_retirement_manifest.py:201-212` | Frozen source commit unavailable to the `frozen_manifest` fixture: skip locally, fail instead if `CI` or `GITHUB_ACTIONS` is set. |

The core summary is not strict (`.github/workflows/ci.yml:359-365`); survey does not allow arbitrary missing-input or missing-dependency skips (`.github/workflows/ci.yml:156-163`, `scripts/pytest_report.py:23-61`). The allowlist includes some missing optional media tools, not just private inputs. A listed guard is not evidence that its skip reason is allowed or that a hosted job actually skipped it.

## R3. Registration and directory layout

- **Used but not in the project list:** `parametrize`, `filterwarnings`, `skip`, `skipif` and `xfail` are registered by pytest itself, so they are valid under `--strict-markers`. No unregistered custom mark was found (R1 collection and source sweep). The `usefixtures` hit in `tests/unit/test_check_test_determinism.py:115` is a string, not a marked item. **Declared but never used:** `network` only (`pyproject.toml:85-90`; R1).

| Path | Tracked files / `test_*.py` modules | Does the testing guide match? |
| --- | ---: | --- |
| `tests/unit/` | 768 / 766 | Directory matches (`docs/engineering/testing.md:54`); the blank marker column misses explicit `gis` and `host_archive` use (R1). |
| `tests/contract/` | 64 / 63 | Yes (`docs/engineering/testing.md:55`). |
| `tests/integration/` | 15 / 14 | Yes (`docs/engineering/testing.md:56`). |
| `tests/gis/` | 195 / 193 | Yes (`docs/engineering/testing.md:57`); the path-based survey split is not the `tests/coast/` folder. |
| `research/tests/` (direct files) | 106 / 103 | Yes for `claims`, but 41 items are also explicitly GIS-marked (R1; `docs/engineering/testing.md:58`). |
| `research/tests/gis/` | 114 / 113 | Yes; both marks (`docs/engineering/testing.md:59`). |
| `tests/coast/` | 19 / 0 | Not listed as a Python layer; the tracked files here are TypeScript tests and support assets. |
| `tests/fixtures/`, `research/tests/fixtures/`, `tests/helpers/` | 523 / 0; 6 / 0; 7 / 0 | Support, not Python layers. The guide covers fixture use (`docs/engineering/testing.md:132-139`), not every support directory. |
| Direct files under `tests/` | 991 / 0 | Not a Python layer. Includes Node tests (guide `:73,95-98`) and support such as `tests/coast_no_gis_probe.py:1-6`, a standalone probe rather than a `test_*.py` module. |

Reproduce file counts with `git ls-tree -r --name-only 34761911d5c44a903873867426f316c7f1e5911c -- tests research/tests`; bucket by directory as in the table (count direct entries only for the two direct-file rows), then count names matching `test_*.py`. The six actual Python paths match `tests/contract/test_test_layout.py:14-19,41-51`. The guide's statement that tests never declare layer marks (`docs/engineering/testing.md:50`) and that `not gis` selects the same set with and without GIS (`:61`) do not describe the observed explicit marks and collection difference in R1–R2.

## R4. Follow-up

No additional build is needed for this inventory. It documents the current behavior, including the guide discrepancies, without changing test selection, skip rules, or CI.
