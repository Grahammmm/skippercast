# Claims pins and research tests

Every module here pins a statement the app, the docs or a receipt makes to the
committed evidence behind it (`research/receipts/`, research outputs under
`dist/data/`, `research/catalog/`), or tests the research script that produced
that evidence. pytest marks everything in this folder `claims`; modules under
`gis/` also need the survey stack and are marked `gis`. See
[docs/engineering/testing.md](../../docs/engineering/testing.md).

- **Run:** `python -m pytest -m claims` (all), `python -m pytest research/tests --ignore=research/tests/gis`
  (without GIS packages, as CI's `check` job does via `-m "not gis"`), or one module with
  `python -m unittest research.tests.gis.test_<name>` as the research workflows do.
- **Paths:** import `ROOT` from `research.lib.paths` and receipts through
  `research.lib.receipts.RECEIPTS`/`locate()`; never from `__file__` or `sys.path`.
- **Changing a pin** means the evidence changed: update the receipt and the pin in
  the same PR and explain it under **Claims and data**.
- **Private caches.** A test that re-derives a receipt from gitignored originals
  (`var/`, original survey archives) skips when they are absent; its exact reason
  must be allow-listed in `scripts/pytest_report.py`, and a committed-output twin
  must still run in CI.

## Renamed by claim

Modules once named after an opaque survey or product id are named by the claim they
pin (engineering audit P2-09). The old names are kept here so an id still leads to its
test; receipts and research scripts keep their id-based names. Other modules already
said what they pin and kept their names when they moved from `tests/`.

| Old module (`tests/`) | Module now (`research/tests/`) | Id | Claim pinned |
| --- | --- | --- | --- |
| `test_bss02_accuracy_provenance.py` | [`gis/test_claims_block02_class_accuracy_is_not_rock_evidence.py`](gis/test_claims_block02_class_accuracy_is_not_rock_evidence.py) | CSUMB Block 02 | A circular terrain-class accuracy check is not independent rock ground truth. |
| `test_bss02_video_grid_overlap.py` | [`gis/test_claims_block02_camera_points_cannot_qualify_empty_cells.py`](gis/test_claims_block02_camera_points_cannot_qualify_empty_cells.py) | CSUMB Block 02 | Camera observations cannot qualify unpopulated bathymetry cells. |
| `test_bss03_access_blocks.py` | [`gis/test_claims_block03_closure_screen_stays_private.py`](gis/test_claims_block03_closure_screen_stays_private.py) | CSUMB Block 03 | The partial closure screen stays private and fail-closed; the receipt holds no geometry or mark. |
| `test_bss03_datum_acquisition.py` | [`gis/test_claims_block03_datum_probe_stays_unqualified.py`](gis/test_claims_block03_datum_probe_stays_unqualified.py) | CSUMB Block 03 | Datum/acquisition diagnostics never promote private camera blocks to fish marks. |
| `test_bss03_caris_tpe_member.py` | [`test_claims_block03_caris_member_needs_hdcs_identity.py`](test_claims_block03_caris_member_needs_hdcs_identity.py) | CSUMB Block 03 | A CARIS uncertainty member counts only when complete and identified as HDCS. |
| `test_bss03_vessel_settings.py` | [`test_claims_block03_vessel_settings_not_product_uncertainty.py`](test_claims_block03_vessel_settings_not_product_uncertainty.py) | CSUMB Block 03 | Vessel configuration inputs are not product uncertainty; a missing config fails closed. |
| `test_ds781_native_character.py` | [`gis/test_claims_statewide_original_character_is_source_review_only.py`](gis/test_claims_statewide_original_character_is_source_review_only.py) | USGS DS 781 | The statewide original seafloor-character pass stays a source review. |
| `test_usgs_ds781_catalogs.py` | [`test_claims_usgs_catalog_links_stay_research_leads.py`](test_claims_usgs_catalog_links_stay_research_leads.py) | USGS DS 781 | Official catalog links stay research leads, including a shared-DOI mismatch. |
| `test_usgs_ds781_metadata.py` | [`test_claims_usgs_metadata_is_not_a_depth_or_reuse_decision.py`](test_claims_usgs_metadata_is_not_a_depth_or_reuse_decision.py) | USGS DS 781 | FGDC metadata cannot become a fishing-depth or reuse decision. |
| `test_usgs_ds552_san_pedro.py` | [`gis/test_claims_san_pedro_rock_classes_need_reviewed_grid.py`](gis/test_claims_san_pedro_rock_classes_need_reviewed_grid.py) | USGS DS 552 | San Pedro rock classes are read only on the reviewed UTM grid and class codes. |
| `test_usgs_caldig_v2.py` | [`gis/test_claims_caldig_deepwater_has_no_200_300ft_candidates.py`](gis/test_claims_caldig_deepwater_has_no_200_300ft_candidates.py) | USGS Cal DIG I v2 | The exact original scan has no 200 or 300 ft candidates; a changed archive cannot be used silently. |
| `test_cal_dig_shallow_300_gap.py` | [`test_claims_caldig_deep_rov_points_do_not_support_shallow_spots.py`](test_claims_caldig_deep_rov_points_do_not_support_shallow_spots.py) | USGS Cal DIG I | Deep ROV annotations do not support ≤300 ft spots. |
| `test_h11730_cdfw_substrate_overlap.py` | [`gis/test_claims_point_arena_camera_needs_verified_cdfw_substrate.py`](gis/test_claims_point_arena_camera_needs_verified_cdfw_substrate.py) | NOAA H11730 | Point Arena camera positions are sampled only after the CDFW substrate tile audit passes. |
| `test_h11971_source_rights.py` | [`test_claims_source_rights_do_not_qualify_camera_points.py`](test_claims_source_rights_do_not_qualify_camera_points.py) | NOAA H11971 | Reviewed source rights do not qualify historical camera points as targets. |
| `test_h11983_original_lead.py` | [`gis/test_claims_point_st_george_original_lead_stays_held.py`](gis/test_claims_point_st_george_original_lead_stays_held.py) | NOAA H11983 | The Point St. George original-survey lead stays held and coordinate-free. |
| `test_pigeon_w00614_original_class.py` | [`gis/test_claims_pigeon_point_nodata_is_not_hard_flat.py`](gis/test_claims_pigeon_point_nodata_is_not_hard_flat.py) | NOAA W00614 | Nodata never becomes hard flat; zero overlap keeps the source on hold. |
| `test_w00614_usgs_video_gap.py` | [`gis/test_claims_pigeon_point_usgs_video_needs_exact_cell_review.py`](gis/test_claims_pigeon_point_usgs_video_needs_exact_cell_review.py) | NOAA W00614 | USGS video near a measured cell needs an exact cell review; distant points cannot support it. |
| `test_w00614_noaa_sh1809_observations.py` | [`test_claims_pigeon_point_coral_records_stay_research_only.py`](test_claims_pigeon_point_coral_records_stay_research_only.py) | NOAA W00614, SH-18-09 | Coral-database records outside measured cells stay research-only. |
| `test_point_buchon_a3_trackline_lineage.py` | [`gis/test_claims_point_buchon_block_a3_year_not_assigned_to_cells.py`](gis/test_claims_point_buchon_block_a3_year_not_assigned_to_cells.py) | Point Buchon Block A3 | Conflicting delivery/trackline years are never assigned to candidate cells. |
| `test_em300_monterey_original_overlap.py` | [`test_claims_monterey_1998_multibeam_overlap_is_not_a_spot.py`](test_claims_monterey_1998_multibeam_overlap_is_not_a_spot.py) | Monterey 1998 EM300 | Original EM300 overlap cannot satisfy an unknown-datum depth gate. |
| `test_mont95_monterey_original_overlap.py` | [`test_claims_monterey_1995_overlap_stays_research_only.py`](test_claims_monterey_1995_overlap_stays_research_only.py) | Monterey 1995 multibeam | A historical cross-survey overlap stays research-only; deeper gates stay closed. |
| `test_monterey_noaa2612_acoustic_points.py` | [`test_claims_monterey_acoustic_points_keep_depth_unqualified.py`](test_claims_monterey_acoustic_points_keep_depth_unqualified.py) | NOAA 2612 | Acoustic point support keeps chart depth and rank unqualified. |
