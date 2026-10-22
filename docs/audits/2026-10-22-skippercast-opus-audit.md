# SkipperCast coastal and bathymetry audit (2026-10-22)

- **Scope:** `main` at `8a1c2c7`. Coastal and seafloor code in `src/skippercast/`, research GIS tooling, rights logic, caches and receipts, and preview rendering.
- **Method:** I read the code by hand, and three independent sub-reviewers each covered one area. Every finding below has a test under `tests/audit_repro/` that fails on current `main` and uses synthetic data only. 16 tests fail, and 1 baseline test passes. I re-ran every test and re-read every cited line myself.
- **Not for merge:** the repro tests fail on purpose. Each one should move into the normal suite with its fix.

Run them with `python -m pytest tests/audit_repro -p no:cacheprovider`. This needs the `[test,survey]` extras.

## Summary

There are no Critical findings. I found no wrong datum offset, no flipped sign and no nodata-to-zero bug in the coastal `vertical.py` path that reaches published output. The real risks are:

- a second raster reader that ignores vertical metadata;
- one render path that drops "not for navigation";
- several gates that check labels or file names instead of contents.

| # | Severity | Where | One line | Confidence |
| --- | --- | --- | --- | --- |
| 1 | High | `src/skippercast/seafloor/raster.py:56-58` | Native ingest ignores units, sign and scale: feet are read as metres, depth rasters are negated, packed values are not scaled | High (code); low that a current usable source is affected |
| 2 | Medium | `src/skippercast/coastal/render/terrain_only.py:360-396, 476-480` | Preview legend and receipt drop NOT FOR NAVIGATION and the tide caveat for deep-band datums | High |
| 3 | Medium | `src/skippercast/coastal/render/terrain_only.py:191-196`, `render/mesh.py:82-88` | Fixed-diagonal triangulation hides supported soundings, so a 2 m shoal vanishes from the preview | High |
| 4 | Medium | `src/skippercast/seafloor/publish.py:66-91` | Pending-reach coverage is republished after coverage code changes, because `physical_input_hash` is never compared | High |
| 5 | Medium | `src/skippercast/seafloor/publish.py:203-232, 280` | Surveys in the coverage-cell layer are never rights-checked or credited (CSUMB credit can be missing) | Medium |
| 6 | Medium | `research/scripts/mapping_claim_guard.py:207-212` | Publication receipts are matched by file name only: one failed file satisfies all three roles, and "company" matches "mpa" | High |
| 7 | Medium (Low in practice) | `research/scripts/coastal_four128_admission.py:194` | Admission ignores `holds_added` when `holds` exists, and accepts a `REFUSED_*` status | High |
| 8 | Low-Medium | `src/skippercast/coastal/cached_inventory.py:235, 260, 266` | An empty `{}` rights, scope or header document silently clears every hold | High |
| 9 | Low-Medium | `src/skippercast/seafloor/rights.py:24-29` | `public-domain-us-gov` is trusted by label alone, even for a CSUMB SFML archive URL and publisher | High |
| 10 | Low | `src/skippercast/coastal/render/terrain_only.py:302-303` | `depth_bands=N` paints N-1 colours; with N=2 all depths are one colour | High |
| 11 | Low | `research/scripts/coastal_four128_artifact_review.py` (about 60 `assert`s) | Under `python -O`, every MLLW, sign and hash check vanishes and the review prints ACCEPTED | High (code); low (reachable) |

## Findings

### 1. High: native ingest ignores vertical metadata
`read_native` always returns `-raw` as metres of positive-down depth. It never reads band units, scale/offset or a positive-down sign. `coastal/vertical.to_depth` does all three, but the seafloor `ingest.py` path does not use it.

- **Impact:**
  - A feet raster at -100 is stored as 100 m deep, when it is 30.48 m.
  - A packed int16 raster at -2000 with scale 0.01 is stored as 2000 m deep, when it is 20 m.
  - A positive-down depth raster at 25 becomes -25.
  - The COG is still labelled `depth_m_positive_down`, and the 0-300 ft band counts are wrong.
  - Today only per-source human review stands in the way. 98 sources are `usable`, and 11 of them have datum `unknown`.
- **Fix:** Build a vertical block from `coastal.vertical.from_raster` and the catalog row, require `resolve` to pass, and use `to_depth`. At minimum, refuse non-metre units, scale ≠ 1, offset ≠ 0, and any sign tag other than up.
- **Repro:** `test_native_raster_vertical.py`

### 2. Medium: deep-datum preview drops NOT FOR NAVIGATION
`vertical.py` admits EGM2008, instantaneous-sea-level and unstated datums only in lanes M and D, with a fixed `navigation: not-for-navigation` record. `build_terrain` accepts that terrain. The PNG legend then says only "NOMINAL DATUM INSTANTANEOUS-SEA-LEVEL", and the receipt has no deep-datum limitation. `mesh.build_mesh` refuses these datums.

- **Fix:** When `deep_datum` is present, add a "NOT FOR NAVIGATION" legend row with the note and a matching limitation, or refuse the datum like `mesh.py` does.
- **Repro:** `test_render_deep_datum_disclaimer.py`

### 3. Medium: supported soundings missing from the mesh
Each 2×2 cell group is always split along the same diagonal, and a face needs all three of its corners valid. With three valid corners and the lower-left one missing, both faces are dropped. The top-left sounding is then in no triangle. In the test, a 2 m shoal in a 20 m area disappears, but the receipts still count it as supported. `terrain_demo.py:223-228` repeats the same rule, so its check agrees with the bug.

- **Fix:** When exactly three corners are valid, emit that triangle. Report the number of soundings left out of the mesh. Change `mesh.py`, `terrain_only.py` and the demo check together.
- **Repro:** `test_render_terrain_triangulation.py`

### 4. Medium: stale coverage checkpoint is republished
For `terrain-pending` reaches, `region_layers` checks only the catalog, rules and reference hashes. It never compares the checkpoint's `physical_input_hash` (which covers coverage code, requirements and source rows), and `run()` is skipped for these reaches.

- **Fix:** Recompute the physical identity, and refuse or rerun when it differs.
- **Repro:** `test_cache_publish_stale_checkpoint.py`

### 5. Medium: coverage-cell sources skip rights and credit
Attribution and `source_attribution` come only from habitat features, but the `cells` layer carries survey `source_id`s that never pass through `feature_rights`. A ready region can ship CSUMB-derived cells without the CSUMB credit. A for-profit profile would not refuse them either.

- **Fix:** Collect the cell `source_id`s, run them through `feature_rights(..., use=deployment_use(root))`, and merge the credits.
- **Repro:** `test_cache_publish_cell_attribution.py`

### 6. Medium: claim guard trusts file names
`_require_publication_receipts` checks substrings of file names. One `rights-mpa-live-readback-FAILED.json` satisfies all three roles, and `company-logo.json` counts as the MPA receipt.

- **Fix:** Require one file per role, then parse each one and check its schema, pass status, job ID and pinned hash.
- **Repro:** `test_research_mapping_claim_guard.py`

### 7. Medium (Low in practice): four128 admission accepts held or refused evidence
`doc.get('holds', doc.get('holds_added', []))` ignores `holds_added` whenever a `holds` key exists, even an empty one. The status check only rejects the substring "HOLD". The admission record then says `execution_authorized=True`. The coordinator re-checks later (`coordinator/authenticated.py:431-438`), so execution still stops.

- **Fix:** Require both lists to be empty, and require an explicit accepted decision for each role.
- **Repro:** `test_research_four128_admission_evidence.py`

### 8. Low-Medium: empty documents clear inventory holds
The `if header:`, `if scope and …` and `if rights and …` checks treat a hash-pinned `{}` as absent. The rights and scope holds are never added, and the source is reported `usable_for_acquisition_request=True`. Download authorisation is still separate.

- **Fix:** Test `role in item`, and require a non-empty, typed document for each role.
- **Repro:** `test_cache_inventory_empty_rights.py`

### 9. Low-Medium: public-domain label trusted alone
The module rule is "distributor hosting grants no new rights", yet a row labelled public-domain with a CSUMB SFML NCEI archive URL and a CSUMB publisher is cleared for for-profit use. `source_scope.government_row` uses the same label, so one catalog typo would move noncommercial data into the government/for-profit path.

- **Fix:** In the public-domain branch, refuse URLs in `CSUMB_ARCHIVES`/`CSUMB_EXACT_ARCHIVES` and CSUMB publishers, and require a dated rights review.
- **Repro:** `test_rights_public_domain_label.py`

### 10. Low: one depth band too few
- **Fix:** `t = np.minimum(np.floor(t*N), N-1)/(N-1)`.
- **Repro:** `test_render_terrain_bands.py`

### 11. Low: asserts used as gates
- **Fix:** Replace each `assert` with an explicit `raise`. The governed launcher (`-I -B` under systemd-run) blocks `PYTHONOPTIMIZE`, so only a manual `-O` run is exposed.
- **Repro:** `test_research_artifact_review_asserts.py`

## Verified sound

**`coastal/vertical.py`**
- Datum detection is right for EPSG 5866, 5714, 5715, 5703 and 3855. MHW and instantaneous water level resolve to unknown.
- A feet axis must have a factor of exactly 0.3048, so the US survey foot is refused.
- Scale/offset is applied before the feet conversion, and the nodata comparison happens on raw values.
- Deep-lane floors are 91.44 m and 182.88 m. A review cannot clear unknown or conflict holds.
- BAG XML and GDAL agreement is checked.

**Units**
- Every ft↔m constant in the seafloor, coastal and platform code is consistent.
- `qualified_scope` margin units are correct.
- `bottom_targets` qualification signs are correct.

**`seafloor/grid.py`**
- Reach ownership uses half-open intervals with no double counting.
- Reference mosaic priority is right: coarse first, fine overwrites, and newer wins at equal resolution.
- Class-0 nodata is never painted. The receipt reuse key is complete.

**`raster.bounds_window` / `chunks`:** there is no off-by-one, and edge chunks are clipped.

**Downloads and receipts**
- `fetch.py` checks hash and size before rename and removes partial files.
- `prefetch.py` checks the hash of a resumed prefix, pins redirects and refuses gzip responses.
- `state_cache` and `source_reuse` refuse symlinks and copy through sealed files.
- `receipts.py` writes are atomic.

**Render geometry**
- Vertices sit at pixel centres, and the camera basis is right-handed.
- The depth sign is z = -depth, and masked cells become NaN, never 0.
- Every reuse path re-verifies before returning cached output.

**Research tooling**
- `prepare_multibeam_grid`: sign, binning and row flip are correct.
- `regular_bag_window` and `qualify_regular_bag_hard`: BAG 1e6 nodata is excluded.
- VR supergrid affine, `check_terrain_acceptance` and the Estero VDatum sign are correct.

**Rights and publishing**
- CSUMB rights fail closed when a review field is missing or wrong.
- A missing deployment profile defaults to for-profit, which is the stricter setting.
- The environment cannot weaken production's `source_use`.
- Seafloor publish features carry the "Not a navigation chart" notice.

## Not verified

- **Real data:** whether any current `usable` source is in feet, packed or positive-down (finding 1). That needs the private cache on AgentOrange, which this session cannot reach.
- **San Pedro RCA side test:** it needs a hash-pinned NOAA archive.
- **Client and Worker display of notices:** `web/` and `server/` were outside this pass.
