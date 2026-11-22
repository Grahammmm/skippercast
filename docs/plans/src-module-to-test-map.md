# SkipperCast Python module-to-test map

## R1. Summary by package

| Package or group | Python modules | Directly imported by a test | No direct test import |
| --- | --- | --- | --- |
| `atlas` | 3 | 3 | 0 |
| `coastal` | 61 | 56 | 5 |
| `fleet` | 56 | 55 | 1 |
| `forecast` | 6 | 6 | 0 |
| `pipeline` | 47 | 47 | 0 |
| `platform` | 18 | 17 | 1 |
| `relief` | 37 | 35 | 2 |
| `seafloor` | 54 | 52 | 2 |
| `skippercast (root)` | 8 | 8 | 0 |
| `style` | 2 | 2 | 0 |
| `util` | 4 | 4 | 0 |
| **Total** | 296 | 285 | 11 |

Baseline: local `origin/main` at `34761911d5c44a903873867426f316c7f1e5911c`, read offline on 2026-11-21 (PST). The tables below are the read-only AST scan results at that commit. **No direct test import does not mean no test coverage.**

### What counts

- Source: tracked `.py` files under `src/skippercast/`, including `__init__.py`, `__main__.py` and private modules. Subpackages roll into their top-level package. Standalone modules and entry points at the top level share the root row. Line counts are physical lines, including blanks and comments; an empty file has zero.
- Tests: tracked `tests/**/test_*.py` (including loose `tests/test_*.py`), matching the filename rule in `pyproject.toml:82`. This is a source inventory, not a pytest collection run. `tests/conftest.py:10–15` applies GIS collection and layer markings; `docs/engineering/testing.md:48–61` describes the layers. `research/tests/`, test helpers and fixtures are not credited as tests.
- Count explicit absolute `import` and `from` statements anywhere in the file, including local and conditional imports. Credit the exact named module; `from skippercast.pkg import leaf` credits `pkg` and `pkg.leaf` only if the latter is a tracked module. Importing a package does not credit all its children, and importing a dotted leaf does not credit implicit parent loads. Also count `importlib.import_module` (including imported aliases) and `__import__` with a literal name or a simple module-level string constant.
- No transitive imports, test execution, string-based mock targets, computed module names, file-path loaders, subprocess entry points or non-Python tests count toward the Python import map. See R3 for examples of tests that exercise Python without a counted import.

Inventory commands (from the repository root; use the pinned SHA for `origin/main` if the ref has moved):

```sh
git ls-tree -r --name-only origin/main -- src/skippercast tests
git grep -nE '^(from|import) skippercast' origin/main -- tests
```

The grep is a cross-check, not the counting rule: it misses indented imports and dynamic calls. The 2026-11-21 scan read the pinned Git blobs, parsed all 1,036 matching test files (63 contract, 193 GIS, 14 integration, 766 unit), and counted 296 Python source files. The card's folder counts include some files that are not Python modules or Python test files. For example, `git ls-tree -r --name-only origin/main -- tests/coast` shows TypeScript tests and a JSON fixture, not Python tests. The scratch scan was not added to the repository.

### Modules with no direct test import

#### `atlas`

None.

#### `coastal`

| Path (relative to `src/skippercast/`) | Lines |
| --- | --- |
| `coastal/_runner_bootstrap.py` | 17 |
| `coastal/authenticated_v1/bootstrap.py` | 15 |
| `coastal/authenticated_v1/metadata_bag.py` | 28 |
| `coastal/client_policy.py` | 12 |
| `coastal/native_guard_v2.py` | 9 |

#### `fleet`

| Path (relative to `src/skippercast/`) | Lines |
| --- | --- |
| `fleet/__main__.py` | 5 |

#### `forecast`

None.

#### `pipeline`

None.

#### `platform`

| Path (relative to `src/skippercast/`) | Lines |
| --- | --- |
| `platform/__main__.py` | 34 |

#### `relief`

| Path (relative to `src/skippercast/`) | Lines |
| --- | --- |
| `relief/enc.py` | 221 |
| `relief/habitat_context.py` | 300 |

#### `seafloor`

| Path (relative to `src/skippercast/`) | Lines |
| --- | --- |
| `seafloor/sample_units.py` | 18 |
| `seafloor/scoped_processing.py` | 135 |

#### `skippercast (root)`

None.

#### `style`

None.

#### `util`

None.

## R2. Fifteen largest modules with no direct test import

There are only 11 gaps by this rule, so all are shown. Ranked by line count, then path. “First public function” means the first top-level `def` or `async def` whose name does not start with `_`; class methods and imports do not count. A sibling shares the exact parent package. The nearest test is a source-navigation hint: prefer one that tests a sibling used by the missing module or exercises the same feature, then use a same-package fallback. The anchors show sibling imports; they do not establish coverage of the missing module.

| Module | Lines | First public function | Nearest sibling test (import line) |
| --- | --- | --- | --- |
| `src/skippercast/relief/habitat_context.py` | 300 | `add_arguments` at `src/skippercast/relief/habitat_context.py:41` | `tests/unit/test_relief_receipts.py:14` → `skippercast.relief.receipts`, imported by `src/skippercast/relief/habitat_context.py:25` |
| `src/skippercast/relief/enc.py` | 221 | `main` at `src/skippercast/relief/enc.py:191` | `tests/gis/test_relief_enc.py:9` → `skippercast.relief.receipts`; the ENC stage is called through a subprocess at line 79 |
| `src/skippercast/seafloor/scoped_processing.py` | 135 | `load_context` at `src/skippercast/seafloor/scoped_processing.py:45` | `tests/gis/test_seafloor_scope_paths.py:14` → `skippercast.seafloor.run`, which imports `load_context` at `src/skippercast/seafloor/run.py:113` |
| `src/skippercast/platform/__main__.py` | 34 | `main` at `src/skippercast/platform/__main__.py:9` | `tests/contract/test_platform.py:7–8` → `skippercast.platform.contracts` and `candidate`, both used at `src/skippercast/platform/__main__.py:5–6` |
| `src/skippercast/coastal/authenticated_v1/metadata_bag.py` | 28 | `inspect_metadata` at `src/skippercast/coastal/authenticated_v1/metadata_bag.py:10` | `tests/gis/test_authenticated_bag_cell_ids.py:9` → `skippercast.coastal.authenticated_v1.adapter_bag` |
| `src/skippercast/seafloor/sample_units.py` | 18 | `require_unpacked_metre_elevation` at `src/skippercast/seafloor/sample_units.py:7` | `tests/gis/test_seafloor_adapters.py:143` → `skippercast.seafloor.source_ingest`, which imports the guard at `src/skippercast/seafloor/source_ingest.py:56` |
| `src/skippercast/coastal/_runner_bootstrap.py` | 17 | None | `tests/unit/test_coastal_operations.py:17` → `skippercast.coastal.runner`, which launches the bootstrap at `src/skippercast/coastal/runner.py:454` |
| `src/skippercast/coastal/authenticated_v1/bootstrap.py` | 15 | None | `tests/unit/test_f05_13_audit.py:30` → `skippercast.coastal.authenticated_v1.worker`, invoked by `src/skippercast/coastal/authenticated_v1/bootstrap.py:14–15` |
| `src/skippercast/coastal/client_policy.py` | 12 | `heartbeat_detail` at `src/skippercast/coastal/client_policy.py:8` | `tests/unit/test_coastal_operations.py:51` exercises the coordinator loop that calls the policy (`src/skippercast/coastal/coordinator/loop.py:15`); its exact-parent sibling import is `skippercast.coastal.runner` at line 17 |
| `src/skippercast/coastal/native_guard_v2.py` | 9 | `check` at `src/skippercast/coastal/native_guard_v2.py:5` | `tests/gis/test_coastal_mapping_observation.py:123` → `skippercast.coastal.bag_v2`, which imports the guard at `src/skippercast/coastal/bag_v2.py:7` |
| `src/skippercast/fleet/__main__.py` | 5 | None | `tests/contract/test_fleet_region.py:19` → `skippercast.fleet.cli`, used at `src/skippercast/fleet/__main__.py:3` |

## R3. Stale targets and tests without a direct import

No stale module targets found by the scan. A `from` member that does not match a source file may be a function, class, constant or re-export; the base module is checked, but a member is not automatically treated as a missing module.

**324 of 1,036 Python test files** have no counted SkipperCast import. This includes tests of scripts and static contracts. A direct-import miss can still run SkipperCast (for example, computed imports in `tests/unit/test_rebuild_plan_cli.py:121` or the habitat-context CLI subprocess at `tests/gis/test_habitat_context.py:101`). Node and TypeScript tests are outside both the denominator and the list; `tests/test_fleet_sink_parity.mjs:111` is an example of a Node test with an embedded Python import.

### `tests/contract/` (33)

```text
test_advisor_media_workflow.py
test_bodega_draft.py
test_capability_receipts.py
test_changelog_section.py
test_changelog_section_edges.py
test_changelog_section_fences.py
test_coast_assets_workflow.py
test_commercial_sources.py
test_daily_stage_summary.py
test_fleet_capability_receipt.py
test_home_ports.py
test_map_tiles.py
test_mapping_progress_control.py
test_ops_report.py
test_ops_report_future_push.py
test_ops_report_mask.py
test_ops_report_numbers.py
test_ops_report_shapes.py
test_primary_strategies.py
test_r2_lifecycle.py
test_receipt_manifest.py
test_region_wording.py
test_research_boundary.py
test_seafloor_documentation.py
test_seafloor_key_files.py
test_seafloor_regional_workflow.py
test_shore_habitat_inputs.py
test_shore_reread_digest_tokens.py
test_shore_reread_dossier.py
test_station_failover_evidence.py
test_test_layout.py
test_trip_check_loop.py
test_workflow_pins.py
```

### `tests/gis/` (30)

```text
test_bathy_background_validity.py
test_build_bathy_tiles.py
test_build_chlorophyll_layer.py
test_build_survey_zone.py
test_build_tide_layer.py
test_central_habitat_context.py
test_check_relief_budget.py
test_coast_archive_reserve.py
test_coast_close_raw_closure.py
test_coast_manifest_edge_roles.py
test_coast_mosaic_seams.py
test_coast_prefetch_scheme.py
test_coast_segment_close.py
test_coast_sign_off_graph.py
test_coastal_four128_mask_topology_scan.py
test_coastal_four128_review_home_paths.py
test_ec_bbox_contract.py
test_ec_detect.py
test_ec_verify.py
test_ec_verify_inputs.py
test_habitat_context.py
test_maplayer_wind.py
test_multibeam_beam_triage.py
test_point_bins.py
test_preflight_native_grid.py
test_relief_select_twin_shape.py
test_search_plan_geometry.py
test_search_plans_inputs.py
test_search_plans_polygon_parts.py
test_shelter_cove_region.py
```

### `tests/integration/` (9)

```text
test_deploy_controller.py
test_deploy_order.py
test_deploy_source.py
test_habitat_publication.py
test_live_loop.py
test_publish_branch_snapshot.py
test_publish_r2.py
test_r2_snapshots.py
test_recent_intel.py
```

### `tests/unit/` (252)

```text
test_advisor_media_job.py
test_advisor_probe_timeout.py
test_basemap_detail.py
test_basemap_detail_decode.py
test_basemap_regions.py
test_basemap_regions_inputs.py
test_basemap_saved_overview.py
test_budget_drift.py
test_build_glyphs.py
test_build_glyphs_write.py
test_build_map_tiles_cli.py
test_build_station_locations.py
test_build_station_locations_bounds.py
test_build_station_locations_shapes.py
test_check_dco.py
test_check_dco_escape.py
test_check_dco_input.py
test_check_repository.py
test_check_test_determinism.py
test_ci_select_gate.py
test_ci_select_map.py
test_coast_asset_content_range.py
test_coast_assets.py
test_coast_contracts.py
test_coast_coverage.py
test_coast_local_screen_canonical.py
test_coast_native_contracts.py
test_coast_projection_portability.py
test_coast_recipe.py
test_coast_recipe_statewide.py
test_coast_sample_inputs.py
test_coast_sign_off.py
test_coastal_four128_budget.py
test_coastal_four128_home_paths.py
test_coastal_four128_launch_allowance.py
test_coastal_four128_launch_receipt.py
test_coastal_four128_mask_topology.py
test_coastal_four128_mask_topology_boundary.py
test_coastal_four128_run_tag.py
test_coastal_skill_trials.py
test_collect_cdfw_mpas.py
test_collect_charter_reports.py
test_cusp_gzip_completeness.py
test_cusp_import_cli.py
test_cusp_import_inputs.py
test_draft_health_omitted_failures.py
test_draft_region_health_duplicate_keys.py
test_draft_region_health_inputs.py
test_draft_region_health_region_id.py
test_draft_region_health_report.py
test_f04_12_audit.py
test_f05_08_audit.py
test_f07_12_audit.py
test_f19_05_audit.py
test_f19_08_audit.py
test_f19_11_audit.py
test_f19_16_audit.py
test_f20_01_audit.py
test_f20_02_audit.py
test_f20_04_audit.py
test_f20_08_audit.py
test_f20_09_audit.py
test_f20_11_audit.py
test_f20_12_audit.py
test_f20_13_audit.py
test_f20_14_audit.py
test_f21_01_audit.py
test_f21_02_audit.py
test_f21_04_audit.py
test_f21_05_audit.py
test_f21_07_audit.py
test_f21_08_audit.py
test_f21_09_audit.py
test_f21_10_audit.py
test_f21_11_audit.py
test_f21_14_audit.py
test_f21_16_audit.py
test_f21_19_audit.py
test_f23_03_audit.py
test_f23_07_audit.py
test_f23_10_audit.py
test_f23_11_audit.py
test_f26_01_audit.py
test_f26_03_audit.py
test_f26_04_audit.py
test_f26_05_audit.py
test_f26_06_audit.py
test_f26_07_audit.py
test_f26_08_audit.py
test_f26_09_audit.py
test_f26_10_audit.py
test_f26_11_audit.py
test_f26_12_audit.py
test_f27_01_audit.py
test_f27_03_audit.py
test_f27_04_audit.py
test_f27_05_audit.py
test_f27_06_audit.py
test_f27_07_audit.py
test_f27_08_audit.py
test_f28_02_audit.py
test_f28_03_audit.py
test_f28_05_audit.py
test_f28_06_audit.py
test_f28_07_audit.py
test_f28_08_audit.py
test_f28_09_audit.py
test_f28_12_audit.py
test_f28_13_audit.py
test_f29_02_audit.py
test_f29_03_audit.py
test_f29_04_audit.py
test_f29_05_audit.py
test_f29_08_audit.py
test_f29_09_audit.py
test_f29_10_audit.py
test_f29_11_audit.py
test_f29_13_audit.py
test_f29_14_audit.py
test_f29_15_audit.py
test_f29_16_audit.py
test_f30_02_audit.py
test_f30_04_audit.py
test_f30_08_audit.py
test_f30_11_audit.py
test_f31_02_audit.py
test_f31_03_audit.py
test_f31_04_audit.py
test_f31_05_audit.py
test_f31_06_audit.py
test_f31_07_audit.py
test_f31_08_audit.py
test_f31_09_audit.py
test_f32_01_audit.py
test_f32_02_audit.py
test_f32_04_audit.py
test_f32_06_audit.py
test_f32_09_audit.py
test_f32_10_audit.py
test_f32_11_audit.py
test_f32_12_audit.py
test_f32_13_audit.py
test_f33_02_audit.py
test_f33_03_audit.py
test_f33_06_audit.py
test_f33_07_audit.py
test_f33_08_audit.py
test_f33_09_audit.py
test_f33_10_audit.py
test_feed_freshness.py
test_feed_freshness_backups.py
test_feed_freshness_future.py
test_feed_freshness_grouping.py
test_feed_freshness_limits.py
test_feed_stale_alert.py
test_feed_stale_alert_depth.py
test_feed_stale_alert_shapes.py
test_fleet_install_script.py
test_fleet_run_osint_limits.py
test_fleet_schedule_evidence.py
test_habitat_catalog_bounds.py
test_label_lint.py
test_live_sweep.py
test_map_tiles_join_magic.py
test_maplayer_sst.py
test_mapping_claim_guard.py
test_noaa_groundfish_areas.py
test_noaa_groundfish_layer_ids.py
test_noaa_groundfish_previous.py
test_noaa_groundfish_shapes.py
test_noaa_retained_copy.py
test_noaa_survey_discovery.py
test_noaa_survey_discovery_previous.py
test_noaa_survey_products.py
test_noaa_survey_products_inputs.py
test_pc9_receipt_versions.py
test_perf_budget.py
test_perf_budget_reason_types.py
test_perf_script_args.py
test_pointer_diff.py
test_prune_habitat_manifest_links.py
test_prune_habitat_tiles.py
test_publish_r2_delete_errors.py
test_pytest_report.py
test_pytest_report_inputs.py
test_pytest_report_junit_root.py
test_readiness_regular_counts.py
test_recent_intel_previous.py
test_recent_intel_results.py
test_recipe_anchor_identity.py
test_recipe_delta_signed_zero.py
test_recipe_nested_input.py
test_region_build.py
test_region_golden_compare.py
test_region_input_readiness_cohort.py
test_region_intake.py
test_region_intake_io.py
test_region_links.py
test_region_publish.py
test_region_publish_links.py
test_region_publish_order.py
test_region_review.py
test_relief_digest_footprint.py
test_relief_selection_summary.py
test_report_conditions_annotations.py
test_report_conditions_inputs.py
test_report_regulations.py
test_report_regulations_decode.py
test_report_regulations_ids.py
test_report_regulations_validity.py
test_rights_coverage_duplicate_members.py
test_rights_coverage_output.py
test_rollback_rehearsal.py
test_run_region.py
test_sc142_prefetch_metadata_binding.py
test_sc155_prepare_ingress.py
test_sc15a_packet_copy.py
test_sc176_scope_catalog_ids.py
test_sc_recipe_delta.py
test_sc_recipe_delta_io.py
test_sc_recipe_offline.py
test_sc_rights_delta_io.py
test_sc_rights_delta_parse.py
test_sc_sample_audit.py
test_sc_sample_zero_write.py
test_sc_schema_closure.py
test_sc_segment_delta.py
test_sc_segment_delta_io.py
test_sca_042.py
test_sca_045.py
test_sca_085.py
test_sca_087.py
test_sca_090.py
test_sca_092.py
test_sca_093.py
test_sca_102.py
test_sca_108.py
test_schedule_elapsed_duration.py
test_segment_receipt.py
test_showcase.py
test_showcase_inputs.py
test_site_uptime_alert.py
test_site_uptime_body_limit.py
test_site_uptime_json_depth.py
test_style_preview_plan.py
test_subsystem_retirement_manifest.py
test_trip_check_loop_timing.py
test_units_guard.py
test_verify_published_feed.py
test_verify_published_feed_arguments.py
test_verify_published_feed_attempts.py
test_web_runtime_references.py
```

## R4. Buildable follow-up

None proposed from this inventory alone. A direct-import gap is not a demonstrated missing behavior check. R2 can help locate nearby tests when a specific behavior needs verification.
