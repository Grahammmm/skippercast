# Morro Bay bathymetry readiness gap — AUDINV-OLD-21

**Disposition: HOLD.** Merged error-correction code does not establish Morro Bay
bathymetry readiness. This is a missing-evidence assessment, not a release decision.

Assessed 2026-11-15 (PST), against main
`351e321dd8c7b3ef82b149d2bb9476fbe337e180`. Repository citations below are
`path:line` at that revision, not at an unpinned future main. Tests name existing
assertions, not new source qualification or live verification.
**CANDIDATE ONLY; UNINSTALLED; applied=false; REVIEW REQUIRED.**

## Recorded state and interpretation

- `regions/morro-bay/region.json:390` and `regions/morro-bay/region.json:391`
  retain partial bathymetry because original output datum and product uncertainty
  are unresolved. `dist/regions/morro-bay/coverage.json:1` reports zero qualified
  bottom views and false readiness for surveyed-bottom-targets,
  surveyed-bottom-images and fishing-exports. Its published coordinates/views
  are research material, not chart-depth-qualified fishing targets.
- `regions/morro-bay/region.json:508` explicitly withholds chart-depth
  qualification; `regions/morro-bay/region.json:509` records the September 27
  correction to unverified output datum, with geometry unchanged/research-only.
- The report-datum review (`research/receipts/usgs-morro-report-datum-review.json:1`)
  records an MLLW statement in the companion report, but **all three original
  TIFF output declarations remain null**, upper accuracy bounds null, per-cell
  product uncertainty absent and fishing-depth qualification false. A reported
  lower accuracy bound of 0.2 m is not an upper uncertainty bound.
- `research/receipts/usgs-depth-datum-ledger.json:1` retains
  unknown output datum and absent per-cell uncertainty for those three archives.
  `catalog/surveys.json:258`, `catalog/surveys.json:351` and
  `catalog/surveys.json:567` identify their inventory rows. Their `usable`
  native-processing status is not chart-depth, habitat, legal or release approval:
  `src/skippercast/seafloor/manifest.py:163` expressly limits that status.

## Readiness questions

HOLD means the readiness claim is NOT-PROVED; it does not mean the source is
unusable for every private research purpose. Each custodian below is a role to
supply missing evidence, not a newly assigned job or authorization to run one.

| Readiness question | Status | Evidence and applicable test | Missing evidence / custodian |
| --- | --- | --- | --- |
| Original output datum: usgs-morro-bay | HOLD | `regions/morro-bay/coast.json:27`; `catalog/sources.json:76`; report/ledger above; `tests/contract/test_seafloor_manifest.py::InventoryTests::test_native_resolution_wins_over_metadata_spacing` retains unknown datum despite 2 m spacing. | Hash-bound original output-datum evidence and independently reviewed relation to claimed chart depth; USGS source-evidence custodian and coastal qualification owner. |
| Original output datum: usgs-point-buchon | HOLD | `regions/morro-bay/coast.json:26`; `catalog/sources.json:37`; report/ledger above. | Same original-output declaration and qualified datum relation, not a nearby report's datum alone; USGS source-evidence custodian and coastal qualification owner. |
| Original output datum: usgs-point-estero | HOLD | `regions/morro-bay/coast.json:28`; `catalog/sources.json:115`; report/ledger above. | Same original-output declaration and qualified datum relation; USGS source-evidence custodian and coastal qualification owner. |
| Per-file NOAA datum/uncertainty in this region | HOLD | `regions/morro-bay/coast.json:29`; `catalog/sources.json:185` approves the family, not individual surveys; `catalog/depth-contours/morro-bay.geojson:1` lists noaa-bag in sources_omitted. | Exact local survey/file identity, measured footprint, native datum and uncertainty receipts; NOAA source-evidence custodian and coastal qualification owner. |
| Product uncertainty supports fishing-depth limits | HOLD | `regions/morro-bay/region.json:391`; report/ledger above; `src/skippercast/platform/qualified_scope.py:184` binds maximum product uncertainty to reviewed policy; `tests/integration/test_qualified_scope.py::QualifiedScopeTests::test_target_depth_resolution_datum_and_boolean_claims_fail_closed`. | Source/product upper uncertainty and applicable per-cell qualification, including any datum-conversion uncertainty and planning margin; coastal qualification owner with producer evidence. |
| Present targets and bottom views are chart-depth qualified | HOLD | `dist/regions/morro-bay/coverage.json:1`; `tests/contract/test_platform.py::ResearchOnlyPublication::test_research_only_targets_are_not_counted_as_qualified`; `tests/contract/test_platform.py::RegionalContracts::test_all_tiles_have_original_source_identity_and_measured_center`. | Reviewed, artifact-bound native-depth subset and matching views, or evidence for a broader scope; regional qualification/review owner. No promotion from coordinate count. |
| Morro Bay inputs passed EC0–EC9 end to end | HOLD | EC merge inventory below; `docs/seafloor-ec.md:69` places receipts outside the repo; `skills/skippercast-region-build/scripts/region_build.py:164` selects EC only when INTAKE-EC.csv exists; `tests/unit/test_region_build.py::test_ec_run_builds_from_corrected_grids_with_provenance`. | Retained regional INTAKE-EC.csv, per-source detect/apply/verify receipts, EC.json and build/output hash chain, plus independent review; existing region-run custodian. No tracked intake or regional EC receipt chain found. |
| Three USGS cuts constitute independent verification | HOLD | `docs/seafloor-ec.md:49` records one 2008 mosaic; Morro/Estero overlap repeats the same values and Buchon supplies no joint valid cells with Morro. | A genuinely independent acquisition and reviewed overlap receipt, not three filenames; source/EC review custodian. The recorded demo is not an accepted regional receipt chain. |
| Display contours establish corrected or chart-qualified depths | HOLD | `catalog/depth-contours/morro-bay.geojson:1`; `dist/regions/morro-bay/depth-contours.geojson:1`; `tests/test_depth_contours.mjs:51` requires the unverified label. | Artifact-bound EC provenance and datum/uncertainty qualification for the proposed claim; regional build/review owner. Existing display tests and labels alone do not supply them. |
| Publication/fishing export gates are satisfied | HOLD | `dist/regions/morro-bay/coverage.json:1`; `src/skippercast/platform/readiness.py:340` lists remaining promotion gates; `src/skippercast/platform/qualified_scope.py:390` preserves current legal review; `tests/integration/test_qualified_scope.py::QualifiedScopeTests::test_reviewed_partial_subset_does_not_claim_current_legal_clearance`. | Native depth/footprint, independent substrate, current whole-geometry exclusions, hazards/access, rules and scoped review/release authority; qualification/release owners and human/legal custodian where required. USGS commercial permission remains recorded separately at `catalog/sources.json:61`, not decided here. |

## EC0–EC9 implementation is merged, not regional acceptance

Rechecked using GitHub PR metadata during this assessment: all twelve are MERGED
on 2026-10-31 UTC. Stage order here is conceptual, not merge chronology.

| Stage | Merged PRs | What the implementation supplies |
| --- | --- | --- |
| EC0 | [#1070](https://github.com/Grahammmm/skippercast/pull/1070), [#1071](https://github.com/Grahammmm/skippercast/pull/1071) | Shared contract, nullable keys and finite receipt values |
| EC1 | [#1074](https://github.com/Grahammmm/skippercast/pull/1074), [#1075](https://github.com/Grahammmm/skippercast/pull/1075) | Native-grid detection, intrinsic validity and sidecar refusal |
| EC2 | [#1072](https://github.com/Grahammmm/skippercast/pull/1072) | Corrected grid and provenance raster |
| EC3 | [#1073](https://github.com/Grahammmm/skippercast/pull/1073) | Second-survey verification |
| EC4 | [#1079](https://github.com/Grahammmm/skippercast/pull/1079) | Region-correct driver and skill |
| EC5 | [#1077](https://github.com/Grahammmm/skippercast/pull/1077) | Provenance-aware contours |
| EC6 | [#1076](https://github.com/Grahammmm/skippercast/pull/1076) | Chart provenance/unresolved-area display |
| EC7 | [#1078](https://github.com/Grahammmm/skippercast/pull/1078) | INTAKE-EC.csv/build provenance integration |
| EC8 | [#1083](https://github.com/Grahammmm/skippercast/pull/1083) | EC review checks and PROMPT rows |
| EC9 | [#1085](https://github.com/Grahammmm/skippercast/pull/1085) | Conditional publication rule 6 and documentation |

Tracked-file inventory found no INTAKE-EC.csv. The recorded Morro Bay contour
artifact has 40 features, none carrying per-feature EC `provenance` and none
labelled unresolved-area; this is **absence of proof of EC use**, not proof no
private EC run ever occurred. Its metadata calls it averaged-block display
contours, not soundings/chart depths (`catalog/depth-contours/morro-bay.geojson:1`).
The stored contour test receipt (`research/receipts/morro-bay-depth-contours-test-2026-11-03.json:6`)
is a UI/data test, not an EC source receipt. Private run folders were not inspected.
The EC-DEMO overlap findings in `docs/seafloor-ec.md:49` are retained as recorded
evidence, not silently discarded or upgraded to full regional acceptance.
Thus no named input is proved here to have completed the accepted EC chain.

## Existing fail-closed assertions (gate implementation only)

These are testable software protections, not positive Morro Bay qualification:

- `src/skippercast/coastal/vertical.py:301` retains unobserved-datum holds.
  `tests/unit/test_coastal_vertical_deep_datums.py::test_undeclared_header_silent_raster_still_held`
  would fail if a silent raster self-admitted. Deep-class lane-S refusal is
  asserted by `tests/unit/test_coastal_vertical_deep_datums.py::test_deep_classes_refused_in_lane_s_windows`
  and `tests/gis/test_coastal_deep_datum_classes.py::test_unstated_class_held_in_lane_s_window`.
  The latter requires no normalized depth facts for the refused synthetic input.
- The G3 M/D exception is real: `src/skippercast/coastal/vertical.py:89`
  permits unbounded deep-datum uncertainty but fixes not-for-navigation and
  chart_datum=false; `tests/unit/test_coastal_vertical_deep_datums.py::test_deep_classes_admitted_with_uncertainty_metadata_in_lane_m_d`
  asserts those labels. It neither converts datum nor certifies shallow/chart depth.
- `tests/contract/test_platform.py::ResearchOnlyPublication::test_research_only_targets_are_not_counted_as_qualified`
  would fail if research-only targets yielded qualified views or ready exports.
  The neighboring tile-identity test requires unverified source datum/research-only.
- `src/skippercast/seafloor/manifest.py:93` checks receipt/manifest datum agreement;
  `tests/contract/test_seafloor_manifest.py::SchemaTests::test_usable_receipt_cannot_conflict_with_manifest`
  rejects conflicting datum or identity, not unknown datum itself. Native inventory
  validation is deliberately weaker than chart-depth qualification.
- `src/skippercast/platform/qualified_scope.py:180` requires native MLLW and complete
  geometry qualification. Its target-depth fail-closed test above rejects unknown
  native datum and invalid depth bounds even with freshly rehashed artifacts.
  Its positive subset test still requires complete_region_coverage=false and
  current_legal_clearance=false; a subset cannot certify the whole region.
- `skills/skippercast-region-publish/scripts/region_publish.py:104` preserves
  the no-EC legacy path. With EC, lines at
  `skills/skippercast-region-publish/scripts/region_publish.py:110` and
  `skills/skippercast-region-publish/scripts/region_publish.py:113` require matching
  EC identity and zero deepened cells.
  `tests/unit/test_region_publish.py::test_ec_rule_six_holds_with_its_reason_and_leaves_the_repo_untouched`
  asserts refusal for missing components, stale check output, hash mismatch and
  nonzero/boolean deepening. Its positive counterpart,
  `tests/unit/test_region_publish.py::test_ec_run_passes_rule_six_with_counts_and_a_run_without_ec_is_byte_identical`,
  proves conditional compatibility, not universal EC adoption or release authority.

## What would unblock (evidence requests only)

1. **Producer/source-evidence custodian:** supply original, hash-bound output datum
   and a defensible product upper-uncertainty record per USGS source; reconcile the
   report's MLLW language without overwriting null/unknown raster evidence.
2. **NOAA/local source custodian:** identify an actual regional file and retain its
   native footprint, datum, uncertainty and review; family approval is insufficient.
3. **Existing region-run custodian:** locate already-retained EC intake, receipts,
   corrected/provenance artifacts, immutable input/output identities and complete
   independent review. Record absent or refused stages explicitly; no rerun here.
4. **Qualification/release owners:** reconcile that scoped evidence with current
   chart-depth, substrate, exclusions, access and species/rules gates; obtain any
   substantive human/legal conclusion from its custodian, not from a passing test.
5. **Existing operator:** preserve Morro-Bay-first priority and the outputs-held-and-
   reviewed boundary. The admitted brief anchors these to G's 2026-10-20 and
   2026-10-30 decisions; priority is not readiness or permission to release.

No source download/run, EC rerun/rebuild, new region, live verification, install,
publication or readiness-data edit was performed. Retained signing, retire/delete,
source/live/privacy and human-acceptance holds are unchanged. Stop at this assessment.
`docs/README.md` is unchanged: the existing coastal-snapshot audit is not indexed
there, so this document follows that audit-directory convention.
