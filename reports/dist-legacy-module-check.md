# dist legacy module check (AUDINV-OLD-30)

Report only: nothing is removed. Built from main at `0991fc70d` with `pnpm install --frozen-lockfile && pnpm build && node scripts/check_client.mjs`.

`dist/*.js` is authored source (vite.config.mjs header), not build output. Manifest = `dist/client/.vite/manifest.json` (139 entries); a module counts as bundled when its path appears as a manifest key or `src` (keys look like `account.js`, relative to `dist/`).

Classes: bundled / service-worker / test-only / unreferenced. Consumers are from relative or `/x.js` import specifiers and html `<script src>` in tracked files (script gen.py, scratch).

| module | manifest key/src | in a built chunk (sourcemap) | imported by (prod: web/server/packages/dist) | imported by (tests/e2e/scripts) | class |
|---|---|---|---|---|---|
| dist/account.js | yes | yes | dist/boat-profile.js<br>web/account.ts<br>web/app/TripAlerts.tsx | tests/test_account_coordinates.mjs<br>tests/test_account_create_notice.mjs<br>tests/test_account_dialog_keyboard.mjs<br>tests/test_account_i18n.mjs (+8 more) | bundled |
| dist/bite-evidence.js | no | yes | dist/charter-grounds.js<br>web/reports.ts | tests/test_advisor_tools.mjs<br>tests/test_copy_lint.mjs<br>tests/test_evidence.mjs<br>tests/test_station_label.mjs | bundled |
| dist/boat-handling.js | yes | yes | dist/boat-profile.js<br>dist/first-run.js<br>dist/morning-outlook.js<br>dist/tomorrow.js (+9 more) | tests/test_boat.mjs<br>tests/test_boat_range.mjs<br>tests/test_first_run.mjs<br>tests/test_hourly_table.mjs (+1 more) | bundled |
| dist/boat-profile.js | yes | yes | web/account.ts | - | bundled |
| dist/browser-storage.js | no | yes | dist/first-run.js<br>web/planner.ts<br>web/trip.ts | tests/test_trip_storage.mjs | bundled |
| dist/chart-map.js | no | yes | dist/offline-pack.js | tests/test_coasts.mjs | bundled |
| dist/charter-grounds.js | no | yes | web/reports.ts | tests/test_charters.mjs | bundled |
| dist/coast-targets.js | no | yes | dist/region.js | tests/test_coast_targets.mjs | bundled |
| dist/coastal-offline-core.js | yes | yes | web/trip-runtime.ts | tests/test_coastal_offline.mjs<br>tests/test_sp82_snapshot_length.mjs<br>tests/test_sw.mjs | bundled |
| dist/coasts.js | no | yes | dist/region.js<br>web/reports.ts | tests/test_coasts.mjs<br>tests/test_map_response.mjs | bundled |
| dist/coordinates.js | no | yes | dist/account.js<br>dist/trip-export.js<br>web/app/MarkCard.tsx<br>web/app/Planner.tsx (+1 more) | tests/test_account_coordinates.mjs<br>tests/test_coordinates.mjs<br>tests/test_mark_copy_position.mjs | bundled |
| dist/coverage-map.js | no | yes | dist/coverage.html | tests/test_coverage_map.mjs | bundled |
| dist/daily-feed.js | no | yes | dist/protected-areas.js | tests/test_map_startup.mjs<br>tests/test_mark_screen.mjs | bundled |
| dist/feeds.js | no | yes | dist/coasts.js<br>dist/region.js<br>web/map/marks.ts | tests/test_feeds.mjs<br>tests/test_security_headers.mjs | bundled |
| dist/first-run.js | yes | yes | web/account.ts | tests/test_first_run.mjs<br>tests/test_trip_storage.mjs | bundled |
| dist/fleet-activity.js | yes | yes | web/map/fleet.ts | tests/test_evidence_ladder.mjs<br>tests/test_fleet_layers.mjs<br>tests/test_fleet_layers_v2.mjs<br>tests/test_fleet_view.mjs | bundled |
| dist/forecast.js | no | yes | dist/live-conditions.js<br>dist/marine-charts.js<br>dist/marine-data.js<br>dist/morning-outlook.js (+2 more) | tests/test_first_run.mjs<br>tests/test_morning.mjs<br>tests/test_tomorrow.mjs<br>tests/test_web.mjs | bundled |
| dist/geo-screen.js | yes | yes | dist/account.js<br>dist/protected-areas.js<br>dist/reef-trip-data.js<br>dist/trip-export.js (+16 more) | scripts/protected_screen_oracle.mjs<br>scripts/reef_slim_parity.mjs<br>tests/test_closure_every_output.mjs<br>tests/test_closures_everywhere.mjs (+27 more) | bundled |
| dist/gpx.js | no | yes | dist/reef-trip-data.js<br>dist/trip-export.js<br>web/protected-route.ts | tests/test_closures_everywhere.mjs<br>tests/test_gpx_coordinate_decimals.mjs<br>tests/test_gpx_handoff.mjs<br>tests/test_gpx_names_clean.mjs (+5 more) | bundled |
| dist/home-port.js | no | yes | web/planner.ts | tests/test_accounts.mjs<br>tests/test_home_port.mjs<br>tests/test_planner_retry.mjs<br>tests/test_ports.mjs (+1 more) | bundled |
| dist/legal-pack.js | yes | yes | web/trip-runtime.ts<br>web/trip.ts | tests/test_legal_pack.mjs | bundled |
| dist/live-conditions.js | no | yes | web/confidence.ts | tests/test_confidence.mjs<br>tests/test_live_conditions.mjs<br>tests/test_station_label.mjs<br>tests/test_units.mjs | bundled |
| dist/live-mpa.js | no | yes | dist/protected-areas.js<br>web/map/marks.ts | tests/test_live_mpa.mjs<br>tests/test_live_mpa_screens.mjs | bundled |
| dist/map-response.js | no | yes | dist/protected-areas.js | tests/test_map_response.mjs | bundled |
| dist/marine-charts.js | no | yes | dist/bite-evidence.js<br>dist/fleet-activity.js<br>dist/live-conditions.js<br>dist/marine-data.js (+3 more) | tests/test_marine.mjs<br>tests/test_marine_startup.mjs | bundled |
| dist/marine-data.js | yes | yes | dist/bite-evidence.js<br>dist/morning-outlook.js<br>dist/offline-pack.js<br>dist/tomorrow.js | tests/test_map_startup.mjs<br>tests/test_marine.mjs<br>tests/test_pack_forecast_end.mjs<br>tests/test_southern_region.mjs (+2 more) | bundled |
| dist/morning-outlook.js | no | no | dist/tomorrow.js | tests/test_boat.mjs<br>tests/test_morning.mjs<br>tests/test_score.mjs<br>tests/test_southern_species.mjs | test-only |
| dist/offline-core.js | yes | yes | dist/daily-feed.js<br>dist/legal-pack.js<br>dist/offline-pack.js<br>web/app/Trip.tsx (+5 more) | tests/test_daily_brief_part.mjs<br>tests/test_early_reads.mjs<br>tests/test_offline.mjs<br>tests/test_offline_commit_boundary.mjs (+4 more) | bundled |
| dist/offline-pack.js | yes | yes | web/trip-runtime.ts | tests/test_offline.mjs<br>tests/test_offline_commit_boundary.mjs<br>tests/test_pack_forecast_end.mjs<br>tests/test_trip_pack_files.mjs | bundled |
| dist/protected-areas.js | yes | yes | dist/account.js<br>web/trip.ts | scripts/protected_screen_bench.mjs<br>scripts/protected_screen_oracle.mjs<br>scripts/reef_slim_parity.mjs<br>tests/test_account_i18n.mjs (+16 more) | bundled |
| dist/recent-discussions.js | no | yes | web/reports.ts | tests/test_recent_discussions.mjs | bundled |
| dist/reef-trip-data.js | no | yes | web/map/coast-ranking.js<br>web/planner.ts | scripts/protected_screen_bench.mjs<br>scripts/reef_slim_parity.mjs<br>tests/test_reef_slim.mjs<br>tests/test_spot_ranking.mjs | bundled |
| dist/region-default.js | no | yes | dist/region.js | - | bundled |
| dist/region.js | yes | yes | dist/account.js<br>dist/bite-evidence.js<br>dist/charter-grounds.js<br>dist/daily-feed.js (+10 more) | tests/test_account_i18n.mjs<br>tests/test_closure_every_output.mjs<br>tests/test_export_caveats.mjs<br>tests/test_fish_entry.mjs (+22 more) | bundled |
| dist/seafloor-data.js | no | yes | dist/reef-trip-data.js<br>web/map/coast-ranking.js<br>web/map/ranked.ts<br>web/map/seafloor.ts (+3 more) | scripts/check_region_promotion.mjs<br>tests/test_map_style.mjs<br>tests/test_seafloor_data.mjs<br>tests/test_seafloor_layer.mjs | bundled |
| dist/skill-page.js | no | yes | dist/skill.html | tests/test_skill_scorecard.mjs | bundled |
| dist/species-fit.js | no | yes | web/map/habitat.ts<br>web/ranking.ts | tests/test_central_rank_inventory.mjs<br>tests/test_marks_layer.mjs<br>tests/test_species_fit.mjs | bundled |
| dist/spot-ranking.js | no | yes | dist/gpx.js<br>dist/reef-trip-data.js<br>web/mark-distance.ts<br>web/planner-alerts.ts (+4 more) | tests/test_home_origin.mjs<br>tests/test_i18n.mjs<br>tests/test_land_water.mjs<br>tests/test_mark_distance.mjs (+14 more) | bundled |
| dist/status-names.js | no | yes | dist/status-page.js | tests/test_status_coast_feeds.mjs<br>tests/test_status_page.mjs | bundled |
| dist/status-page.js | no | yes | dist/status.html | tests/test_status_coast_feeds.mjs<br>tests/test_status_index_shape.mjs<br>tests/test_status_page.mjs | bundled |
| dist/sw.js | no | no | - | - | service-worker |
| dist/target-groups.js | no | yes | dist/bite-evidence.js<br>dist/charter-grounds.js<br>web/map/charter-grounds.ts<br>web/reports.ts | - | bundled |
| dist/tomorrow.js | no | yes | dist/first-run.js | tests/test_hazard_verdict.mjs<br>tests/test_score.mjs<br>tests/test_tomorrow.mjs | bundled |
| dist/trip-export.js | yes | yes | dist/account.js<br>web/app/Planner.tsx<br>web/planner-copy.ts<br>web/planner.ts | tests/test_closure_every_output.mjs<br>tests/test_copy_lint.mjs<br>tests/test_float_plan.mjs<br>tests/test_habitat_place.mjs (+12 more) | bundled |

Totals: 44 files; bundled 42, service-worker 1, test-only 1.

## Findings

- Total: 44 `dist/*.js` files = 42 `bundled` + 1 `service-worker` (`sw.js`) + 1 `test-only` (`morning-outlook.js`). **0 `unreferenced`.**
- "Bundled" is proved from a scratch rebuild with `sourcemap: true` (the committed `vite.config.mjs` has `sourcemap: false`; the edit was reverted, never committed): a module counts as bundled when `dist/<name>.js` appears in the `sources` of a built chunk map. The manifest alone lists only entry and dynamic-import chunks (139 entries, of which only a minority are `dist/*.js` modules such as `account.js`, `fleet-activity.js`, `boat-handling.js`), so statically imported modules are inlined and have no manifest key; the "manifest key/src" column is shown for completeness.
- **Disagreement with the static scan (43 reachable + `sw.js`)**: the built output has 42. `dist/morning-outlook.js` is reachable by import (`dist/tomorrow.js:6` imports `rateHour`, and `dist/tomorrow.js` is bundled via `dist/first-run.js`), but it contributes no code to any built chunk: its only use in `tomorrow.js` is the default argument of `planDay`/`planTomorrow` (lines 86, 128), which the bundle tree-shakes because the bundled `first-run.js` uses only `latestTomorrow`/`clock`. So it is classified `test-only`: it is imported by `tests/test_boat.mjs`, `test_morning.mjs`, `test_score.mjs`, `test_southern_species.mjs`. The `vite.config.mjs` header says tests import `dist/*.js` directly, so it is **not removable on this evidence**; it is also still imported by `dist/tomorrow.js`, so removal would break the build input (`UNRESOLVED_IMPORT`, as in the control below).
- `sw.js` is classified `service-worker` (`scripts/build-worker.mjs` stamps and copies it; outside the module graph).

## Commands run (clean main, fresh clone)

```console
$ pnpm install --frozen-lockfile        # exit 0, 108 packages
$ pnpm build                            # exit 0, "Built shared regional Worker and public assets (build 391fd2209a)."
$ node scripts/check_client.mjs
Client check passed: 140 hashed assets, 16 pages, 82 page references and 828 script references resolve, 44 precached for build 391fd2209a. Budgets: app.html js 375416 B, css 14489 B gzipped; landing.html js 100353 B, css 6332 B gzipped; precache install 660237 B, pack shell 3520870 B raw.
```

## Negative control (scratch only, restored)

`mv dist/recent-discussions.js dist/recent-discussions.js.bak` (imported by `web/reports.ts`), then `pnpm build` exited 1:

```console
[UNRESOLVED_IMPORT] Could not resolve '../dist/recent-discussions.js' in web/reports.ts
 ELIFECYCLE  Command failed with exit code 1.
```

Restored the file; rebuild passed again (build 391fd2209a); no tracked file changed.

## Closing line

No module is unreferenced; nothing to remove. (`morning-outlook.js` is the only module that adds no code to the shipped bundle, and it is kept alive by tests and the `tomorrow.js` import; any change to it belongs in a separate unit under the retire/delete HOLD.)
