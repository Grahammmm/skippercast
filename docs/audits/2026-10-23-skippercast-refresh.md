# SkipperCast audit refresh (2026-10-23)

- **Scope:** `main` at `0d670db` (after #847). The audit covers two things:
  - it re-checks every finding from the 2026-10-22 audits (branches `claude/audit-skippercast` and `claude/adversarial-coast`);
  - it looks for new defects in code merged since 2026-10-20: #800, #804, #806, #818, #847, 64da6a1, b3ae879, #795, 6686e33 and 5df20cc.
- **Method:** I read the code by hand, and three independent reviewers each took one area. Every finding has a test that fails on current `main`. I re-ran each failing test myself and checked that it fails on its assertion, not during setup.
- **Data:** synthetic only (tiny numpy arrays, GeoTIFFs and HDF5 files written to `tmp_path`). No network, no real or private data.
- **Not for merge:** the tests fail on purpose. They skip unless `SKIPPERCAST_AUDIT_CLOUD=1`, so the normal suite stays green. Move each test into the normal suite together with its fix.
- **Production code:** unchanged.

```bash
SKIPPERCAST_AUDIT_CLOUD=1 python -m pytest tests/test_audit_cloud_*.py -p no:cacheprovider -q   # needs [test,survey]
```

## Counts

| Set | Failing (findings) | Passing guards |
| --- | --- | --- |
| Earlier findings, re-checked (`test_audit_cloud_prior_*`) | 24 of 24 still present | 54 |
| New: window-set bridge (`test_audit_cloud_bridge.py`) | 3 | 1 |
| New: VR BAG reader (`test_audit_cloud_vertical_vr.py`) | 2 | 0 |
| New: prefetch, contours, local screen (`test_audit_cloud_prefetch_contours.py`) | 9 | 4 |
| **Total** | **38 failing tests: 24 old findings + 14 new** | **59** |

There are no Critical findings. I found nothing in the new code that is fail-open on queue writes or publication.

## Held area (SC#1): report only, no merge proposal

The owner holds native raster ingestion units, sign and scale. These findings are still open. They are listed here and in the tables below marked **HELD**, with no fix proposed for merge:

- `src/skippercast/seafloor/raster.py:56-58`: feet are read as metres, packed scale is ignored, and positive-down data is negated (3 tests, `prior_opus_native_raster_vertical`).
- `scripts/build_depth_contours.py:84`: feet are read as metres and scale/offset is ignored (2 tests, `prior_adv_contour_builder`). The other contour-builder tests (int16, south-up, lattice size) are separate defects and are not held.

## 1. Earlier findings: all still present

Every repro from both earlier reports still fails on `main` at `0d670db`, for the same reason as before. No fix has landed.

| Earlier # | Severity | Where | Still failing test |
| --- | --- | --- | --- |
| Opus 1 | High (**HELD**) | `seafloor/raster.py:56-58` | `prior_opus_native_raster_vertical` (3) |
| Opus 2 | Medium | `coastal/render/terrain_only.py:360-396, 476-480` | `prior_opus_render_deep_datum_disclaimer` |
| Opus 3 | Medium | `coastal/render/terrain_only.py:191-196`, `render/mesh.py:82-88` | `prior_opus_render_terrain_triangulation` (2) |
| Opus 4 | Medium | `seafloor/publish.py:66-91` | `prior_opus_cache_publish_stale_checkpoint` |
| Opus 5 | Medium | `seafloor/publish.py:203-232, 280` | `prior_opus_cache_publish_cell_attribution` |
| Opus 6 | Medium | `research/scripts/mapping_claim_guard.py:207-212` | `prior_opus_research_mapping_claim_guard` (2) |
| Opus 7 | Medium (Low in practice) | `research/scripts/coastal_four128_admission.py:194` | `prior_opus_research_four128_admission_evidence` (2) |
| Opus 8 | Low-Medium | `coastal/cached_inventory.py:235, 260, 266` | `prior_opus_cache_inventory_empty_rights` |
| Opus 9 | Low-Medium | `seafloor/rights.py:24-29` | `prior_opus_rights_public_domain_label` |
| Opus 10 | Low | `coastal/render/terrain_only.py:302-303` | `prior_opus_render_terrain_bands` |
| Opus 11 | Low | `research/scripts/coastal_four128_artifact_review.py` | `prior_opus_research_artifact_review_asserts` |
| Adv 1-2 | Medium (**HELD**) | `scripts/build_depth_contours.py:84` | `prior_adv_contour_builder` feet, packed |
| Adv 3 | Low (fails closed) | `build_depth_contours.py:84` | `..._integer_grid_does_not_crash_the_reader` |
| Adv 4 | Low (fails closed) | `build_depth_contours.py:48-58, 99-112` | `..._south_up_grid_matches_its_north_up_twin` |
| Adv 5 | Low (OOM) | `build_depth_contours.py:76-77, 99-112` | `..._lattice_for_refuses_absurd_extent` |
| Adv 6 | Low | `platform/depth_contours.py:137-139` | `..._trace_treats_nan_as_invalid_like_none` |
| Adv 7 | Low | `coastal/vertical.py:349` | `prior_adv_vertical_and_reference` float32 nodata |
| Adv 8 | Low | `seafloor/grid.py:54` | `prior_adv_vertical_and_reference` NaN centre |

The fixes proposed in the 2026-10-22 reports still apply unchanged.

## 2. New findings, ranked

| # | Severity | Where | One line |
| --- | --- | --- | --- |
| N1 | High | `coastal/prefetch.py:384-388, 475-477` | A weak ETag is dropped, so a file that changes mid-transfer is stitched from two versions and receipted as verified |
| N2 | Medium | `coastal/coordinator/bridge_run.py:264-273` | Window-set `tiling.cell`/`anchor` are never bound to `affine_transform`, so a plan can drop tiles and still be admitted as complete |
| N3 | Medium | `coastal/handoff/vr_refinements.py:216-218` | VR cells with a valid depth but nodata/NaN uncertainty count as native support; the regular-BAG path drops them |
| N4 | Medium | `coastal/prefetch.py:357-368` | A missing primary manifest overwrites the mirror with an empty file, erasing the only other copy of the receipts |
| N5 | Medium | `scripts/build_depth_contours.py:85, 162-163` | A supplied grid that contributes zero blocks is skipped silently, so the output looks complete |
| N6 | Medium | `skills/coast-local-screen/scripts/local_screen.py:337-366, 594-603` | A window marked `map_done` whose map stage failed screens as `pass` |
| N7 | Medium | `local_screen.py` `cmd_assemble` (~1001-1011) | An empty plan reports a clean screen (exit 0, no flags) |
| N8 | Medium (fails closed) | `coordinator/catalog_bridge.py:159-164, 225-228` against `bridge_run.py:285-290` | A source whose tiles cross a segment edge has no admissible window-set plan; the two rules contradict each other |
| N9 | Low-Medium | `coastal/prefetch.py:509-519` | The verified receipt is written before the rename, so a failed rename leaves a lasting receipt for a file that does not exist |
| N10 | Low-Medium | `local_screen.py` `normalize()` (~243-249) | An admission without a catalog ref silently turns off `DEPTH_RANGE_OUT` |
| N11 | Low | `bridge_run.py:675` | Bounded runs execute windows in string order (0, 1, 10, 11, 2, ...), not admission order |
| N12 | Low | `vr_refinements.py:177-181` | The refinement null comes from the overview fill value; a non-standard fill turns the BAG 1e6 null into a +1,000,000 m sounding |
| N13 | Low | `build_depth_contours.py:160`; `platform/depth_contours.py:4-5` | `native_cell_m` is copied from the catalog, not checked against the grid; the docstring says "checked by SHA-256" but the hash is only recorded |
| N14 | Low | `local_screen.py` `load_thresholds` (:552-560) | Unknown keys and non-numeric thresholds silently fall back to the defaults, while `stats.json` names the file as the source |

### N1. High: a file mixing two versions can be receipted as verified
- **Defect:** `validator()` throws away a weak ETag and falls back to Last-Modified, which has 1-second resolution. If both are missing, nothing is checked. Ranges are appended as long as that value matches.
- **Scenario:**
  - HEAD returns `W/"v1"`.
  - The file is replaced (`W/"v2"`, same Last-Modified) after the first range.
  - The plan row has no publisher SHA, so the run exits 0 and promotes `AAAABBBBBB` as `http-size-and-local-sha256`.
- **Reachable:** yes, for hosts that send weak ETags (common on CDNs) when the row has `sha256: null`.
- **Fix:** record the raw ETag, weak or strong, and hold on any change. Never stitch ranges on Last-Modified alone or with no validator; fetch with one full GET instead.
- **Test:** `test_prefetch_weak_etag_change_mid_transfer_is_concatenated`

### N2. Medium: tiling geometry is not bound to the affine
- **Defect:** `tiling.anchor` and `tiling.cell` decide which tiles are required, but `affine_transform` decides ownership and footprint. Both sit in the same hashed grid definition, and nothing checks that they agree. `validate_coast_receipt.py:724-733` has the same gap.
- **Scenario:** a 1024×1024 raster with all 4 tiles in the segment, but `cell=[1.0, 1.0]` declared instead of `1e-5`. This yields a "complete" 1-tile set, and `_context` admits it, so 3/4 of the coverage is dropped silently.
- **Fix:** in `_bind_window` and the validator, require `anchor == affine·origin`, `cell == (a, -e)` and `b == d == 0`.
- **Test:** `test_window_set_tiling_geometry_not_bound_to_affine`

### N3. Medium: VR support ignores the uncertainty band
- **Defect:** `_valid` checks elevation only. The emitted GeoTIFF is read by `mapping_input.observe` (band 1 only), so a cell with uncertainty 1e6 or NaN counts as support. The regular-BAG path requires both bands to be valid.
- **Scenario:** 48 cells are counted where 46 are valid.
- **Reachable:** yes; this is the `vr.emit` → `observe` path.
- **Fix:** write the elevation as nodata wherever the uncertainty is nodata or non-finite (in `_fill`, `emit` and `verify`).
- **Test:** `test_vr_output_admits_cells_whose_uncertainty_is_nodata`

### N4. Medium: a missing primary manifest erases the mirror
- **Defect:** `manifest()` loads nothing when `manifest.jsonl` is absent, then "repairs" the mirror with that empty set.
- **Fix:** hold when the primary is missing and the mirror is not empty, or when the mirror has URLs the primary lacks.
- **Test:** `test_prefetch_missing_primary_manifest_wipes_mirror_receipts`

### N5. Medium: a supplied grid can contribute nothing without warning
- **Defect:** only values below 0 count as water. A positive-down grid, or the same file passed under two IDs, gets `supported_blocks: 0`, and the build succeeds (`{'usgs-a': 64, 'usgs-b': 0}`). `check_contours` does not catch it.
- **Fix:** fail when any supplied grid has zero blocks or no negative values, or when two grids share a SHA-256.
- **Test:** `test_contours_supplied_grid_with_no_water_is_silently_skipped`

### N6. Medium: a failed map stage can pass the screen
- **Defect:** the screen trusts the window-level `state == "map_done"` and never checks `stages.map.state`. `coast_receipt_versions.py:83` does check it.
- **Fix:** flag `STATE_INCONSISTENT` unless the acquire, qualify and map stages are all `done`.
- **Test:** `test_local_screen_failed_map_stage_passes`

### N7. Medium: an empty plan screens clean
- **Fix:** add an `EMPTY_POPULATION` plan flag, or refuse the plan.
- **Test:** `test_local_screen_empty_population_reports_clean`

### N8. Medium (fails closed): edge-straddling sources cannot be planned
- **Defect:** `catalog_bridge` requires every tile that intersects the CRS84 envelope. `_bind_window` refuses any tile whose pixel centre falls in another segment. So the full set is refused for its owner, and the owned subset is refused as "not the deterministic tiling".
- **Impact:** only sources wholly inside one segment can be bridged.
- **Fix:** tile by the same EPSG:3310 pixel-centre ownership rule in both places.
- **Test:** `test_edge_straddling_window_set_has_no_admissible_plan`

### N9. Low-Medium: receipt written before the rename
- **Fix:** write a `pending` record, and mark it verified only after `os.replace` succeeds.
- **Test:** `test_prefetch_receipt_before_rename_leaves_stale_verified_record`

### N10. Low-Medium: a dropped catalog ref turns off the depth check
- **Fix:** for the PC-9 receipt shape, treat a missing catalog ref as a plan integrity problem.
- **Test:** `test_local_screen_dropped_catalog_ref_disables_depth_check_silently`. The guard `test_guard_local_screen_depth_range_out_with_catalog` shows the same window is flagged when the ref is present.

### N11. Low: windows run out of order
- **Defect:** `window_key` ends in a decimal string, so `sorted` runs 0, 1, 10, 11, 2, ...
- **Scenario:** a 12-window run with `max_ticks=9` finishes windows 0, 1 and 10 but leaves 2 unfinished.
- **Fix:** sort by position in `receipt["jobs"]`.
- **Test:** `test_run_executes_windows_in_admission_index_order`

### N12. Low: BAG 1e6 null can become valid
- **Reachable:** only with a non-standard BAG; NOAA BAGs use 1e6. The GDAL probe agrees with the reader, so it does not catch this.
- **Fix:** require `nodata == 1e6` in `_read_source`, or always treat 1e6 as invalid.
- **Test:** `test_vr_refinement_null_1e6_counted_valid_when_overview_fill_differs`

### N13. Low: resolution and hash claims are not checked
- **Fix:** require `grid.res == native_resolution_m`, and either pin and verify the SHA-256 or reword the docstring to "recorded".
- **Test:** `test_contours_native_resolution_not_checked_against_catalog`

### N14. Low: bad threshold values are ignored
- **Fix:** refuse unknown keys and any value that is not a finite, non-bool number.
- **Test:** `test_local_screen_thresholds_file_bad_values_silently_ignored`

## Lower items without a test

- **Contour expiry off by one:**
  - `platform/depth_contours.py:224` says contours are withheld *from* `review_expires`.
  - `web/map/depth-contours.ts:112` uses `today > expires`, so they still draw on that day, and `tests/test_depth_contours.mjs:56` expects that.
  - The owner must decide which is intended.
- **Duplicate `--grid`:** in `build_depth_contours.py:139`, when two `--grid` flags share an ID, the last one wins silently.
- **`window` and `windows` together:** `catalog_bridge.check_plan` (:136-141) accepts a selection with both keys; `windows` wins and `window` is ignored but still hashed. It should refuse.
- **Missing run summary:** in `bridge_run.run`, the idle branch calls `_lineage` outside try/except, so an integrity error there can escape without writing a run summary.
- **Leftover directories:** `catalog_bridge.dry_run`/`run` create the output directory before `_freeze`, so a NaN in an echoed field leaves an empty directory that can never be reused.
- **Unchecked deep-datum path:** `coastal/authenticated_v1/observer.py:128` copies `mapping_input.observe` but was not updated for deep datums in #795 (NaN depths are not trimmed from support). It looks BAG-only, since BAG requires MLLW, so it is probably unreachable. Not tested.
- **Datum statement hash:** `datum_statement` hashes are only format-checked, never compared with the source metadata.

## Checked and sound

- **Window tiling** (`catalog_bridge`):
  - full coverage with no gaps or overlaps, and edge tiles clipped;
  - `[col, row, w, h]` used consistently with rasterio, `observe` and the store gate;
  - caps (64 per source, `MAX_JOBS` 256, the 262,144-cell gate from #800) are exact.
- **Bridge integrity:**
  - held sources are refused;
  - empty job lists are refused;
  - an integrity error replaces windows with "unfinished" placeholders and never reuses a clean snapshot;
  - manifests and receipts are re-derived and compared byte for byte.
- **VR geolocation:**
  - `vr_transform` uses half-cell origins, flips rows from south-up to north-up, and is cross-checked against GDAL;
  - refinement index checks are contiguous, start at 0 and stay within the record count;
  - the output hash covers both bands.
- **Deep-datum admission (#795):**
  - admitted in lanes M and D only, with exact case matching;
  - the 91.44 m floor is inclusive and computed in metres after any feet conversion;
  - support and the depth hash are trimmed after the floor.
- **Prefetch:**
  - range math and `Content-Range` checks are correct;
  - a resumed prefix is SHA-256 checked and then truncated;
  - redirect changes and encoded responses are refused;
  - `safe_path` refuses symlinks and `..`.
- **Contours:**
  - levels are 30 ft multiples, and depth = −elevation in feet;
  - lon/lat order uses `always_xy`;
  - nodata becomes NaN, never 0 m;
  - there are no seams.
- **Local screen:** hash mismatches and holds override model verdicts, and model errors count as flags.
- **Receipt validator:** the inverse-projection tolerance (18815f4) is two ULPs per coordinate. Projected fields stay exact.

## Not verified

- **Real data:** none was used, so this report does not show whether any real source triggers N1, N3, N5 or the held raster findings.
- **AgentOrange:** not reachable from this cloud session. The work used the session's own checkout.
- **Client and Worker display of notices:** outside this pass, apart from the contour expiry note above.
