# Statewide coast recipe runsheet (OC-STATE)

Preparation only, frozen against main `a805ee9bc0a9fdc95fdc88afa8e71a513cc103a9`.
G's 2026-10-29 admission expands recipes, not execution. A valid recipe is not a
run, statewide completion, a datum qualification or source-use permission.
Candidate, restricted and unknown catalog values remain unchanged. The six SoCal
draft regions remain draft; adding a recipe publishes nothing. Not for navigation.

## Future order: Central → SoCal → NorCal

Finish and sign off each stage before advancing. At most two segments run at once.
Pause the whole loop on any regression. Each segment needs its own approved
sign-off through [`skills/coast-sign-off`](../../skills/coast-sign-off/SKILL.md).
A failed run gets a card; otherwise no new cards are created. This document
creates no timer, automatic job, downloads, prefetch or segment execution.

The table covers the 17 added recipes, in execution order. The four existing
recipes (morro-bay, cambria-san-simeon, south-big-sur-san-simeon and
santa-cruz-monterey-bay) retain the same gates and also need real Central QA.
`southern-california` is an excluded umbrella, not a missing recipe: its southern
edge 32.5 is below discovery coverage 32.5343 and it overlaps the SoCal regions.

| Stage | Recipe / future segment | Receipt / sign-off | Hole-% / VR BAG decision |
| --- | --- | --- | --- |
| Central | big-sur-coast | NOT RUN / pending | UNDETERMINED |
| Central | monterey-point-sur | NOT RUN / pending | UNDETERMINED |
| Central | point-arguello-conception | NOT RUN / pending | UNDETERMINED |
| SoCal | santa-barbara-channel | NOT RUN / pending | UNDETERMINED |
| SoCal | channel-islands-north | NOT RUN / pending | UNDETERMINED |
| SoCal | santa-monica-palos-verdes | NOT RUN / pending | UNDETERMINED |
| SoCal | san-pedro-orange-county | NOT RUN / pending | UNDETERMINED |
| SoCal | san-diego | NOT RUN / pending | UNDETERMINED |
| SoCal | outer-islands-borderland | NOT RUN / pending | UNDETERMINED |
| NorCal | point-reyes-pigeon | NOT RUN / pending | UNDETERMINED |
| NorCal | bodega-point-reyes | NOT RUN / pending | UNDETERMINED |
| NorCal | point-arena-bodega | NOT RUN / pending | UNDETERMINED |
| NorCal | fort-bragg-point-arena | NOT RUN / pending | UNDETERMINED |
| NorCal | shelter-cove-north-mendocino | NOT RUN / pending | UNDETERMINED |
| NorCal | humboldt-bay-cape-mendocino | NOT RUN / pending | UNDETERMINED |
| NorCal | trinidad-klamath | NOT RUN / pending | UNDETERMINED |
| NorCal | crescent-city | NOT RUN / pending | UNDETERMINED |

## Preconditions for every future run (all required)

1. S-030 admission recorded on **t_acd1b120**. A done recipe card, machine-valid
   recipe or green CI cannot replace that attended admission.
2. The hot-cache ceiling and reserve are available, including preflight for the
   actual segment. The recipe cap remains 25,000,000,000 bytes; no cap increase.
3. `prefetch_receipts_check.py` passes on the admitted inputs, with all retained
   source, host, size and receipt holds respected.
4. The receipt validates against run admission with `validate_coast_receipt.py`.
   Missing, synthetic, unclosed or invalid receipts are not completed runs.
5. Each segment has approved sign-off via `skills/coast-sign-off`; any regression
   pauses the entire loop for correction, not an automatic retry.

No new RUNNABLE checker is introduced: the existing receipt validation and
S-030 gate retain ownership. No writes to `~/skippercast-data/coast/segments/`
are authorized by this preparation PR.

## Per-segment hole-% line / OC-BAG1

After each future closed real run, replace its UNDETERMINED cell with a line:
`<segment>: <receipt identity>; hole_numerator=N; coverage_denominator=D regular
 grid cells; holes=100*N/D%; qa.flags=<recorded flags>; sign-off=<identity>`.
Use the entire rectangular regular grid denominator, not surveyed-only cells.
Missing/zero denominator or missing, unclosed or invalid evidence stays
UNDETERMINED; no synthetic percentage is recorded here.

OC-BAG1 reopens only after at least four closed, receipt-valid **real Central**
segment receipts exist. The operator reads each receipt's `qa.hole_numerator`,
`qa.coverage_denominator`, `qa.threshold_config` and `qa.flags`. Any
`holes_above_10_percent` (strictly >10%, not >=10%) means admit S-034
(t_7c30d2e8) with its own build spec; none means "VR BAG not needed now".
A missing, unclosed or invalid segment means UNDETERMINED, never "not needed".
S-034 stays parked until that real-QA precondition holds. This is a read of
existing receipts, not a new decision packet, checker or reader.

## Retained holds (verbatim)

The OC-STATE build spec retains these boundaries:

> S-030 bulk downloads and live runs stay held
> (t_acd1b120), so this card prepares only.

> S-032 deep sources and the S-034 VR BAG reader.

OC-BAG1 retains:

> Any download, prefetch or live segment run (S-030/S-031 holds stand).

The existing [coast-prefetch runbook](coast-prefetch.md) retains:

> GEBCO reviewed-host subset, Borderland and Gridimage TIFF holds remain explicit.

> Missing sizes and conflicting committed pins
> remain explicit holds; without this flag NOS file sizes need later preflight.

> Migration is not permission to start the campaign or clear source holds.

> These candidates need a reviewed downloadable bounded
> representation or independently established exact size before the full campaign
> can run; do not substitute a whole-volume/global file or expand hosts.

All human/legal/scientific acceptance, source/live, publication and navigation
holds remain in force. No source status or datum is upgraded, and no private
preview becomes a published data product through this runsheet.
