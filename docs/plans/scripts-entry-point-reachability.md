# Script entry-point reachability

| Finding | Files |
| --- | ---: |
| Tracked under `scripts/` | 158 |
| At least one workflow, package script, test or other code consumer | 152 |
| Referenced only by docs or skills | 3 |
| Of those, referenced only by docs | 2 |
| No counted callers or named docs/skill references | 3 |

Static read on 2026-11-21 of staged `origin/main` at `34761911d5c44a903873867426f316c7f1e5911c` (the supplied baseline). The tree contains 95 Python files, 45 JavaScript modules, 10 shell files, 7 JSON files and 1 systemd unit. No scripts were run to discover their callers. Rows below describe the checked-in tree, not installed jobs or execution frequency.

## R1. Every tracked file

Counts are **distinct caller files per class** (distinct named commands for the root `package.json` scripts block). A test counts if it loads, runs, reads, pins or asserts a specific path or invocation; that is not necessarily runtime coverage. An other-script count means a direct run, import, config read/write, or explicit file binding such as a source pin; it includes callers under `src/`, not only under `scripts/`. JSON and the service unit are consumed, not executed as standalone scripts. Doc and skill columns count named references, including plans and runbooks, not proof that someone follows them. Skill-owned code stays in the skill column. First anchor prefers workflow, package, test, other script, skill, then doc; within each class it is the first sorted path and earliest qualifying line.

Workflow counts exclude comments, trigger-only path filters and indirect calls through a package command or another script. For example, `.github/workflows/seafloor.yml:30` is a path filter, not a direct call; `src/skippercast/seafloor/publish.py:218` imports the builder. The two budget JSON rows count the workflow that explicitly stages those files (`.github/workflows/budget-drift.yml:71–72`). The DCO workflow runs a copy read from the base, not the PR file (`.github/workflows/dco.yml:79,89–91`).

Reproduce the inventory and search candidates from the repo root, with the pinned revision below. Search exact basenames as well as the full path (some callers use a sibling path or join segments); for Python also search `scripts.<module>`, `from scripts[.<subdirectory>] import …`, and the bare stem passed to a loader. Deduplicate by source file, exclude self-references, comments/docstrings in code, fixture copies and files in `workspace/`, and inspect ambiguous hits before assigning a caller class. Docs are tracked Markdown/reStructuredText plus the checked-in showcase page and configuration. Scope includes `tests/`, `research/tests/`, `e2e/`, test entry/config files, and other tracked source (not generated `dist/`). A generic scan, fixture that only repeats a name, or historical manifest does not count as a direct caller.

```sh
base=34761911d5c44a903873867426f316c7f1e5911c
git ls-tree -r --name-only "$base" -- scripts
git grep -n 'scripts/' "$base" -- .github docs tests package.json pyproject.toml skills CONTRIBUTING.md
git grep -nF -e 'build_depth_contours.py' -e 'scripts.build_depth_contours' -e 'import build_depth_contours' "$base" -- '*.py' '*.mjs' '*.ts' '*.sh' '*.yml' '*.md' package.json pyproject.toml
git grep -nE 'sp_map_now_regression_setup|kit_layers_parity|kit_parity|protected_screen_bench|run_core_tests' "$base" -- .github docs reports tests e2e scripts src skills package.json pyproject.toml CONTRIBUTING.md
git show "$base:package.json"
git show "$base:scripts/check_repository.py"
```

Two calls that a literal path search misses: `scripts/style/export_layer_case.mjs:11–13,33` builds the module filename for the JS case; `scripts/style/kit_layers_parity.py:170–175,216` finds the corresponding Python adapter. The showcase JSON names a setup module and a preparation command; the readers are `scripts/showcase_capture.mjs:128,159` and `scripts/showcase.py:139–141`. `tests/unit/test_perf_script_args.py:16–21,40` likewise loads two scripts by stem. Directory-wide scans are not named calls (`scripts/check_repository.py:151–193`; `tests/contract/test_research_boundary.py:36–43`). Off-repo operator commands, untracked code and unresolved dynamic paths are not observable here.

| File | Type | Workflow | Package | Doc | Test | Other script | Skill | First caller |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `scripts/advisor/backfill-drafts.mjs` | JS module | 0 | 0 | 3 | 2 | 0 | 0 | `tests/test_advisor_social_drafts.mjs:41` |
| `scripts/advisor/eval.mjs` | JS module | 0 | 0 | 5 | 1 | 0 | 0 | `tests/test_advisor_eval.mjs:10` |
| `scripts/advisor/grant-admin.mjs` | JS module | 0 | 0 | 6 | 1 | 0 | 0 | `tests/test_advisor_contacts.mjs:209` |
| `scripts/advisor/import-rules.mjs` | JS module | 0 | 0 | 7 | 6 | 0 | 0 | `tests/test_advisor_admin_rules.mjs:34` |
| `scripts/advisor/make-contact-icon.mjs` | JS module | 0 | 0 | 1 | 1 | 0 | 0 | `tests/test_advisor_contact_card.mjs:73` |
| `scripts/advisor/make-fixture-images.mjs` | JS module | 0 | 0 | 2 | 1 | 0 | 0 | `tests/test_advisor_vision.mjs:26` |
| `scripts/advisor/media_job.py` | Python | 1 | 0 | 8 | 4 | 0 | 0 | `.github/workflows/advisor-media.yml:54` |
| `scripts/advisor/meta-token.mjs` | JS module | 0 | 0 | 7 | 3 | 0 | 0 | `tests/test_advisor_meta.mjs:23` |
| `scripts/advisor/preflight.mjs` | JS module | 0 | 0 | 6 | 3 | 0 | 0 | `tests/test_advisor_launch_status.mjs:11` |
| `scripts/advisor/rekey-phones.mjs` | JS module | 0 | 0 | 4 | 1 | 0 | 0 | `tests/test_advisor_rekey.mjs:11` |
| `scripts/advisor/relay-check.mjs` | JS module | 0 | 0 | 9 | 2 | 0 | 0 | `tests/test_advisor_bluebubbles.mjs:498` |
| `scripts/advisor/relay-cleanup.sh` | Shell | 0 | 0 | 4 | 1 | 0 | 0 | `tests/test_advisor_relay_cleanup.mjs:15` |
| `scripts/advisor/vision-conformance.mjs` | JS module | 0 | 0 | 4 | 2 | 0 | 0 | `tests/test_advisor_vision_conformance.mjs:15` |
| `scripts/audit_noaa_survey_products.py` | Python | 1 | 0 | 1 | 5 | 0 | 0 | `.github/workflows/daily-data.yml:112` |
| `scripts/basemap/build_basemap.sh` | Shell | 1 | 0 | 4 | 1 | 0 | 0 | `.github/workflows/basemap.yml:58` |
| `scripts/basemap/build_glyphs.py` | Python | 0 | 0 | 3 | 2 | 0 | 0 | `tests/unit/test_build_glyphs.py:9` |
| `scripts/basemap/check_detail.py` | Python | 0 | 0 | 2 | 3 | 1 | 0 | `tests/test_f19_15_audit.mjs:24` |
| `scripts/basemap/regions.py` | Python | 1 | 0 | 4 | 4 | 2 | 0 | `.github/workflows/basemap.yml:66` |
| `scripts/budget_drift.py` | Python | 2 | 0 | 1 | 1 | 0 | 0 | `.github/workflows/budget-drift.yml:43` |
| `scripts/build-revision.mjs` | JS module | 0 | 0 | 1 | 1 | 1 | 0 | `tests/test_build_revision.mjs:9` |
| `scripts/build-worker.mjs` | JS module | 0 | 1 | 15 | 3 | 0 | 0 | `package.json:10` |
| `scripts/build_bathy_tiles.py` | Python | 0 | 0 | 3 | 10 | 3 | 0 | `tests/gis/test_bathy_background_validity.py:9` |
| `scripts/build_chlorophyll_layer.py` | Python | 0 | 0 | 0 | 2 | 0 | 0 | `tests/gis/test_build_chlorophyll_layer.py:13` |
| `scripts/build_depth_contours.py` | Python | 0 | 0 | 2 | 4 | 1 | 2 | `tests/gis/test_build_depth_contours.py:13` |
| `scripts/build_landing_shoreline.mjs` | JS module | 0 | 0 | 2 | 3 | 0 | 0 | `tests/test_landing.mjs:17` |
| `scripts/build_landing_strings.mjs` | JS module | 0 | 0 | 8 | 4 | 1 | 0 | `tests/test_i18n_catalogue_loading.mjs:15` |
| `scripts/build_map_tiles.py` | Python | 0 | 0 | 2 | 3 | 1 | 0 | `tests/contract/test_map_tiles.py:44` |
| `scripts/build_search_plans.py` | Python | 1 | 0 | 9 | 2 | 0 | 0 | `.github/workflows/ci.yml:126` |
| `scripts/build_sources_register.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_sources_register.py:13` |
| `scripts/build_station_locations.py` | Python | 0 | 0 | 0 | 3 | 0 | 0 | `tests/unit/test_build_station_locations.py:8` |
| `scripts/build_survey_zone.py` | Python | 0 | 0 | 0 | 3 | 1 | 0 | `tests/gis/test_build_survey_zone.py:70` |
| `scripts/build_tide_layer.py` | Python | 0 | 0 | 2 | 2 | 0 | 0 | `tests/gis/test_build_tide_layer.py:10` |
| `scripts/build_trip_calendar_regions.mjs` | JS module | 0 | 0 | 1 | 1 | 0 | 0 | `tests/test_trip_ics.mjs:11` |
| `scripts/changelog_section.py` | Python | 1 | 0 | 1 | 4 | 0 | 0 | `.github/workflows/release.yml:31` |
| `scripts/check_client.mjs` | JS module | 3 | 0 | 20 | 5 | 0 | 0 | `.github/workflows/budget-drift.yml:51` |
| `scripts/check_coast_report_source.mjs` | JS module | 0 | 0 | 1 | 1 | 0 | 0 | `tests/test_check_coast_report_source.mjs:3` |
| `scripts/check_contrast.mjs` | JS module | 0 | 0 | 6 | 19 | 0 | 0 | `e2e/p04-catch-contrast.spec.ts:33` |
| `scripts/check_copy.mjs` | JS module | 1 | 0 | 28 | 11 | 0 | 0 | `.github/workflows/ci.yml:455` |
| `scripts/check_d1_restore.mjs` | JS module | 1 | 0 | 3 | 1 | 0 | 0 | `.github/workflows/ci.yml:410` |
| `scripts/check_dco.py` | Python | 1 | 0 | 1 | 4 | 0 | 0 | `.github/workflows/dco.yml:89` |
| `scripts/check_deploy_source.py` | Python | 1 | 0 | 1 | 3 | 1 | 0 | `.github/workflows/deploy-cloudflare.yml:252` |
| `scripts/check_e2e_pins.py` | Python | 1 | 0 | 3 | 0 | 0 | 0 | `.github/workflows/ci.yml:343` |
| `scripts/check_feed_freshness.py` | Python | 1 | 0 | 8 | 9 | 0 | 0 | `.github/workflows/feed-freshness.yml:45` |
| `scripts/check_perf_budget.py` | Python | 1 | 0 | 3 | 3 | 1 | 0 | `.github/workflows/ci.yml:429` |
| `scripts/check_region_promotion.mjs` | JS module | 0 | 0 | 9 | 1 | 0 | 0 | `tests/test_region_promotion.mjs:6` |
| `scripts/check_relief_budget.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/gis/test_check_relief_budget.py:8` |
| `scripts/check_repository.py` | Python | 1 | 0 | 34 | 2 | 0 | 0 | `.github/workflows/ci.yml:386` |
| `scripts/check_saved_trips.py` | Python | 0 | 0 | 7 | 0 | 2 | 0 | `scripts/live_cycle.sh:86` |
| `scripts/check_shore_reread_dossier.py` | Python | 0 | 0 | 1 | 1 | 0 | 0 | `tests/contract/test_shore_reread_dossier.py:19` |
| `scripts/check_test_determinism.py` | Python | 1 | 0 | 2 | 1 | 0 | 0 | `.github/workflows/ci.yml:396` |
| `scripts/check_tokens.mjs` | JS module | 1 | 1 | 7 | 8 | 0 | 0 | `.github/workflows/ci.yml:469` |
| `scripts/check_web.py` | Python | 1 | 0 | 20 | 2 | 0 | 0 | `.github/workflows/ci.yml:474` |
| `scripts/ci_affected.json` | JSON | 0 | 0 | 1 | 0 | 1 | 0 | `scripts/ci_select.py:16` |
| `scripts/ci_select.py` | Python | 1 | 0 | 2 | 2 | 0 | 0 | `.github/workflows/ci.yml:55` |
| `scripts/client-build.mjs` | JS module | 0 | 0 | 9 | 7 | 2 | 0 | `tests/test_advisor_pages.mjs:27` |
| `scripts/cloudflare_deploy.sh` | Shell | 1 | 0 | 11 | 8 | 0 | 0 | `.github/workflows/deploy-cloudflare.yml:404` |
| `scripts/coast/publish_assets.py` | Python | 1 | 0 | 3 | 4 | 0 | 0 | `.github/workflows/coast-assets.yml:48` |
| `scripts/coast_diagnostics/recipe_delta.py` | Python | 0 | 0 | 0 | 3 | 0 | 0 | `tests/unit/test_recipe_delta_signed_zero.py:8` |
| `scripts/coast_diagnostics/region_input_readiness.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_region_input_readiness_cohort.py:10` |
| `scripts/coast_diagnostics/relief_digest_footprint.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_relief_digest_footprint.py:10` |
| `scripts/coast_diagnostics/relief_look_status.mjs` | JS module | 0 | 0 | 0 | 1 | 0 | 0 | `tests/test_relief_look_status.mjs:9` |
| `scripts/coast_diagnostics/relief_rollout_status.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_relief_rollout_status.py:8` |
| `scripts/coast_diagnostics/relief_selection_summary.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_relief_selection_summary.py:10` |
| `scripts/coast_diagnostics/relief_shots_preflight.mjs` | JS module | 0 | 0 | 0 | 1 | 0 | 0 | `tests/test_relief_shots_preflight.mjs:8` |
| `scripts/coast_diagnostics/rights_coverage.py` | Python | 0 | 0 | 1 | 3 | 0 | 0 | `tests/unit/test_n3_rights_coverage.py:12` |
| `scripts/coast_diagnostics/rights_delta.py` | Python | 0 | 0 | 1 | 3 | 0 | 0 | `tests/unit/test_sc_rights_delta.py:17` |
| `scripts/coast_diagnostics/sample_coverage.py` | Python | 0 | 0 | 1 | 1 | 0 | 0 | `tests/unit/test_sc_sample_audit.py:22` |
| `scripts/coast_diagnostics/schema_closure.py` | Python | 0 | 0 | 1 | 1 | 0 | 0 | `tests/unit/test_sc_schema_closure.py:28` |
| `scripts/coast_diagnostics/segment_receipt_delta.py` | Python | 0 | 0 | 1 | 2 | 0 | 0 | `tests/unit/test_sc_segment_delta.py:27` |
| `scripts/collect_cdfw_mpas.py` | Python | 0 | 0 | 2 | 1 | 1 | 0 | `tests/unit/test_collect_cdfw_mpas.py:7` |
| `scripts/collect_noaa_groundfish_areas.py` | Python | 3 | 0 | 4 | 6 | 1 | 0 | `.github/workflows/daily-data.yml:104` |
| `scripts/collect_recent_intel.py` | Python | 1 | 0 | 1 | 5 | 0 | 1 | `.github/workflows/daily-data.yml:87` |
| `scripts/collect_shore_habitat.py` | Python | 0 | 0 | 7 | 3 | 0 | 0 | `tests/contract/test_shore_habitat.py:24` |
| `scripts/copy-lint-baseline.json` | JSON | 0 | 0 | 3 | 0 | 1 | 0 | `scripts/check_copy.mjs:37` |
| `scripts/daily_stage_summary.py` | Python | 1 | 0 | 0 | 1 | 0 | 0 | `.github/workflows/daily-data.yml:313` |
| `scripts/discover_noaa_surveys.py` | Python | 1 | 0 | 1 | 6 | 3 | 0 | `.github/workflows/daily-data.yml:108` |
| `scripts/draft_region_health_report.py` | Python | 1 | 0 | 0 | 3 | 0 | 0 | `.github/workflows/draft-region-health.yml:59` |
| `scripts/e2e-flakes.mjs` | JS module | 1 | 0 | 0 | 2 | 0 | 0 | `.github/workflows/ci.yml:297` |
| `scripts/ec_apply.py` | Python | 0 | 0 | 1 | 4 | 0 | 1 | `tests/gis/test_ec_apply.py:19` |
| `scripts/ec_detect.py` | Python | 0 | 0 | 1 | 4 | 1 | 1 | `tests/gis/test_ec_bbox_contract.py:37` |
| `scripts/ec_verify.py` | Python | 0 | 0 | 1 | 3 | 0 | 1 | `tests/gis/test_ec_verify.py:18` |
| `scripts/feed_stale_alert.py` | Python | 1 | 0 | 2 | 3 | 1 | 0 | `.github/workflows/feed-freshness.yml:113` |
| `scripts/fleet/install_listener.sh` | Shell | 0 | 0 | 4 | 1 | 0 | 0 | `tests/unit/test_fleet_install_script.py:21` |
| `scripts/fleet/install_schedule_evidence.sh` | Shell | 0 | 0 | 1 | 0 | 0 | 1 | `skills/skippercast-fleet-schedule-evidence/SKILL.md:26` |
| `scripts/fleet/nais_presence.py` | Python | 0 | 0 | 1 | 2 | 0 | 0 | `tests/unit/test_f21_16_audit.py:14` |
| `scripts/fleet/run_osint.py` | Python | 0 | 0 | 6 | 2 | 0 | 0 | `tests/unit/test_fleet_run_osint.py:34` |
| `scripts/fleet/schedule_evidence.py` | Python | 0 | 0 | 1 | 3 | 1 | 1 | `tests/contract/test_fleet_skills.py:25` |
| `scripts/fleet/skippercast-fleet-ais@.service` | systemd | 0 | 0 | 4 | 1 | 1 | 0 | `tests/unit/test_fleet_install_script.py:22` |
| `scripts/live_cycle.sh` | Shell | 0 | 0 | 7 | 4 | 1 | 0 | `tests/integration/test_publish_branch_snapshot.py:217` |
| `scripts/live_loop.py` | Python | 1 | 0 | 6 | 3 | 0 | 0 | `.github/workflows/live-conditions.yml:58` |
| `scripts/measure_startup.mjs` | JS module | 0 | 0 | 5 | 14 | 0 | 0 | `e2e/reef-lazy.spec.ts:9` |
| `scripts/model_api.mjs` | JS module | 0 | 0 | 3 | 1 | 1 | 0 | `tests/test_model_api.mjs:90` |
| `scripts/ops_report.py` | Python | 1 | 0 | 6 | 7 | 0 | 0 | `.github/workflows/ops-report.yml:36` |
| `scripts/perf-budget.json` | JSON | 1 | 0 | 4 | 1 | 2 | 0 | `.github/workflows/budget-drift.yml:71` |
| `scripts/precache.mjs` | JS module | 0 | 0 | 5 | 7 | 3 | 0 | `tests/test_check_client_budget_values.mjs:9` |
| `scripts/preflight_native_grid.py` | Python | 0 | 0 | 1 | 3 | 5 | 2 | `tests/gis/test_preflight_native_grid.py:12` |
| `scripts/protected_screen_bench.mjs` | JS module | 0 | 0 | 1 | 0 | 0 | 0 | `reports/dist-legacy-module-check.md:40` |
| `scripts/protected_screen_oracle.mjs` | JS module | 0 | 0 | 1 | 1 | 1 | 0 | `tests/unit/test_f21_14_audit.py:86` |
| `scripts/protected_screen_parity.py` | Python | 0 | 0 | 0 | 2 | 0 | 0 | `tests/unit/test_f21_14_audit.py:61` |
| `scripts/prune_habitat_tiles.py` | Python | 0 | 0 | 0 | 3 | 1 | 0 | `tests/integration/test_habitat_publication.py:8` |
| `scripts/publish_branch_r2.sh` | Shell | 2 | 0 | 3 | 3 | 2 | 0 | `.github/workflows/buoy-history.yml:86` |
| `scripts/publish_branch_snapshot.sh` | Shell | 3 | 0 | 2 | 3 | 2 | 0 | `.github/workflows/buoy-history.yml:56` |
| `scripts/publish_forecast_skill.py` | Python | 0 | 0 | 1 | 1 | 0 | 0 | `tests/test_skill_scorecard.mjs:134` |
| `scripts/publish_forecasts.sh` | Shell | 1 | 0 | 4 | 3 | 1 | 0 | `.github/workflows/forecast-tiles.yml:44` |
| `scripts/publish_r2.py` | Python | 0 | 0 | 13 | 6 | 4 | 0 | `tests/integration/test_publish_r2.py:12` |
| `scripts/pytest_report.py` | Python | 1 | 0 | 5 | 4 | 0 | 0 | `.github/workflows/ci.yml:163` |
| `scripts/r2_lifecycle.py` | Python | 0 | 0 | 3 | 2 | 1 | 0 | `tests/contract/test_r2_lifecycle.py:10` |
| `scripts/reef_slim_browser.mjs` | JS module | 0 | 0 | 0 | 1 | 0 | 0 | `tests/test_f21_18_audit.mjs:7` |
| `scripts/reef_slim_build.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_perf_script_args.py:40` |
| `scripts/reef_slim_parity.mjs` | JS module | 0 | 0 | 1 | 1 | 0 | 0 | `tests/test_f21_06_audit.mjs:40` |
| `scripts/refresh_regions.py` | Python | 3 | 0 | 16 | 7 | 1 | 1 | `.github/workflows/daily-data.yml:82` |
| `scripts/relief/coast_coverage.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_coast_coverage.py:12` |
| `scripts/relief/label_lint.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_label_lint.py:7` |
| `scripts/relief/live_sweep.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_live_sweep.py:10` |
| `scripts/relief/pointer_diff.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_pointer_diff.py:8` |
| `scripts/relief/qa_shots.mjs` | JS module | 0 | 0 | 0 | 1 | 1 | 0 | `tests/gis/test_relief_qa.py:203` |
| `scripts/relief/r8_packet.py` | Python | 0 | 0 | 0 | 1 | 1 | 0 | `tests/unit/test_r8_packet.py:9` |
| `scripts/relief/rebuild_plan.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_rebuild_plan_cli.py:10` |
| `scripts/relief/region.py` | Python | 0 | 0 | 2 | 26 | 3 | 1 | `tests/gis/test_habitat_context.py:101` |
| `scripts/relief/release_history.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_release_history.py:13` |
| `scripts/relief/review_supplement.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_review_supplement.py:9` |
| `scripts/relief/rollback_rehearsal.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_rollback_rehearsal.py:11` |
| `scripts/relief/run_region.py` | Python | 0 | 0 | 0 | 4 | 2 | 0 | `tests/gis/test_relief_depth_coverage_cli.py:11` |
| `scripts/relief/stage_release.py` | Python | 1 | 0 | 0 | 3 | 0 | 0 | `.github/workflows/deploy-cloudflare.yml:527` |
| `scripts/relief/style_diff.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_style_diff.py:11` |
| `scripts/relief/style_preview_plan.py` | Python | 0 | 0 | 0 | 1 | 0 | 0 | `tests/unit/test_style_preview_plan.py:13` |
| `scripts/report_conditions.py` | Python | 0 | 0 | 1 | 5 | 1 | 0 | `tests/integration/test_live_loop.py:9` |
| `scripts/report_regulations.py` | Python | 1 | 0 | 1 | 4 | 0 | 0 | `.github/workflows/daily-data.yml:251` |
| `scripts/report_rights_readiness.mjs` | JS module | 0 | 0 | 0 | 1 | 0 | 0 | `tests/test_report_rights_readiness.mjs:5` |
| `scripts/rules_status_probe.mjs` | JS module | 1 | 0 | 2 | 2 | 0 | 0 | `.github/workflows/feed-freshness.yml:164` |
| `scripts/run_core_tests.py` | Python | 0 | 0 | 2 | 0 | 0 | 0 | `docs/engineering/testing.md:27` |
| `scripts/shoreline/import_cusp.py` | Python | 0 | 0 | 5 | 6 | 1 | 0 | `tests/gis/test_relief_water_stage.py:12` |
| `scripts/showcase.py` | Python | 0 | 0 | 1 | 3 | 0 | 0 | `tests/unit/test_f21_02_audit.py:11` |
| `scripts/showcase_capture.mjs` | JS module | 0 | 0 | 2 | 2 | 1 | 0 | `e2e/showcase-capture.spec.ts:40` |
| `scripts/showcase_skippercast.mjs` | JS module | 0 | 0 | 1 | 1 | 1 | 0 | `tests/test_showcase_units.mjs:9` |
| `scripts/showcase_skippercast_server.mjs` | JS module | 0 | 0 | 1 | 1 | 1 | 0 | `tests/test_showcase_server.mjs:9` |
| `scripts/site_uptime_alert.py` | Python | 1 | 0 | 2 | 3 | 0 | 0 | `.github/workflows/feed-freshness.yml:122` |
| `scripts/smoke_test.sh` | Shell | 1 | 0 | 6 | 1 | 0 | 0 | `.github/workflows/deploy-cloudflare.yml:412` |
| `scripts/sp_map_now_regression_setup.mjs` | JS module | 0 | 0 | 0 | 0 | 0 | 0 | — |
| `scripts/startup-budget.json` | JSON | 1 | 0 | 10 | 4 | 2 | 0 | `.github/workflows/budget-drift.yml:72` |
| `scripts/style/export_cases/01-sst-fill.mjs` | JS module | 0 | 0 | 0 | 0 | 1 | 0 | `scripts/style/export_layer_case.mjs:33` |
| `scripts/style/export_layer_case.mjs` | JS module | 0 | 0 | 0 | 0 | 1 | 0 | `scripts/style/kit_layers_parity.py:128` |
| `scripts/style/gen_style.py` | Python | 0 | 0 | 2 | 5 | 0 | 0 | `tests/gis/test_relief_contours.py:704` |
| `scripts/style/kit_cases/01-sst-fill.py` | Python | 0 | 0 | 0 | 0 | 1 | 0 | `scripts/style/kit_layers_parity.py:173` |
| `scripts/style/kit_layers_parity.py` | Python | 0 | 0 | 0 | 0 | 0 | 0 | — |
| `scripts/style/kit_parity.py` | Python | 0 | 0 | 0 | 0 | 0 | 0 | — |
| `scripts/style/layers_fragment.py` | Python | 0 | 0 | 0 | 1 | 1 | 0 | `tests/unit/test_nearshore_style.py:154` |
| `scripts/style/make_synthetic_goldens.py` | Python | 0 | 0 | 0 | 2 | 0 | 0 | `tests/gis/test_nearshore_engine.py:27` |
| `scripts/style/png8.py` | Python | 0 | 0 | 0 | 0 | 2 | 0 | `scripts/style/kit_parity.py:46` |
| `scripts/token-lint-baseline.json` | JSON | 0 | 0 | 1 | 0 | 1 | 0 | `scripts/check_tokens.mjs:25` |
| `scripts/token-lint-coast-baseline.json` | JSON | 0 | 0 | 5 | 0 | 1 | 0 | `scripts/check_tokens.mjs:28` |
| `scripts/trip_check_loop.py` | Python | 1 | 0 | 2 | 3 | 0 | 0 | `.github/workflows/live-conditions.yml:118` |
| `scripts/validate_coast_receipt.py` | Python | 0 | 0 | 1 | 5 | 1 | 0 | `tests/gis/test_coast_contract_graphs.py:213` |
| `scripts/verify_legal_review_artifact.py` | Python | 1 | 0 | 2 | 5 | 0 | 0 | `.github/workflows/regional-legal-review.yml:64` |
| `scripts/verify_published_feed.py` | Python | 1 | 0 | 3 | 4 | 1 | 0 | `.github/workflows/daily-data.yml:161` |
| `scripts/web-vendor-sha256.json` | JSON | 0 | 0 | 11 | 2 | 5 | 0 | `tests/test_passkey_lazy_load.mjs:69` |
| `scripts/worker_versions.mjs` | JS module | 1 | 0 | 2 | 3 | 1 | 0 | `.github/workflows/deploy-cloudflare.yml:296` |
| `scripts/wrangler_config.mjs` | JS module | 1 | 0 | 17 | 11 | 1 | 0 | `.github/workflows/deploy-cloudflare.yml:293` |

## R2. Zero callers and docs-only

**Zero in all six columns.** Dates are the committer dates of the latest path-changing commit visible from the pinned base, not file modification times. Reproduce with `git log -1 --format="%cs %h" "$base" -- <path>`. A zero is not deletion or rename approval.

| File | Last change | Commit |
| --- | --- | --- |
| `scripts/sp_map_now_regression_setup.mjs` | 2026-11-10 | `65624df97` |
| `scripts/style/kit_layers_parity.py` | 2026-11-20 | `fb85457e6` |
| `scripts/style/kit_parity.py` | 2026-11-19 | `20c39efae` |

`scripts/style/kit_layers_parity.py:128,173` has outgoing calls even though it has no incoming caller here. `src/skippercast/style/parity.py:3` describes the output of `kit_parity.py`, but does not invoke that tool. The frozen path list in `docs/engineering/subsystem-retirement.manifest.json:8` is not an invocation of `sp_map_now_regression_setup.mjs`.

**Docs only.** No named automated consumer was found in the counted classes. A rename would still need the cited docs updated; directory-wide checks and off-repo usage are outside this conclusion.

| File | First doc reference |
| --- | --- |
| `scripts/protected_screen_bench.mjs` | `reports/dist-legacy-module-check.md:40` |
| `scripts/run_core_tests.py` | `docs/engineering/testing.md:27` |

## R3. Deprecated, legacy or one-off labels

No tracked filename or opening header labels the file itself deprecated, legacy or one-off. Two headers say **legacy** about behavior or data, not about retiring the script:

| File | Header evidence | Still called? |
| --- | --- | --- |
| `scripts/check_contrast.mjs` | Preserves older checks (`scripts/check_contrast.mjs:4`) | Yes: `e2e/p04-catch-contrast.spec.ts:33`; see R1 |
| `scripts/publish_r2.py` | Keeps older stable keys and describes a legacy mirror (`scripts/publish_r2.py:12`, `scripts/publish_r2.py:14`) | Yes: `tests/integration/test_publish_r2.py:12`; see R1 |

Header means the Python module docstring or leading comment block, not a body comment, status value or filename mentioned in the prose. Recheck the candidates with `git grep -niE 'deprecated|legacy|one[-_ ]off' "$base" -- scripts`, then read the headers at the same revision.

## R4. Follow-up

No buildable unit is needed for this report. In particular, a zero in R2 is a prompt to check off-repo use before a rename or removal, not enough evidence to authorize either. No scripts, data, or automation changed.
