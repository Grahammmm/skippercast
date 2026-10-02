# Avila and SCC16 native release

Qualify the two existing [2 m Avila grids](https://www.ngdc.noaa.gov/ships/ventresca/PGE_AvilaBay_mb.html) and existing [SCC16 2 m grid](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block16_mb.html) in place. Original rasters, windows, valid masks and source ordering are unchanged. These are existing private measurements: **new measured geography is zero**. Source-only receipts retain NOAA distribution, CSUMB producer attribution and [credited noncommercial terms](https://csumb.edu/undersea/sfml-data-library/); navigation and unapproved for-profit use remain excluded.

Avila Block I retains its 2009 acquisition and NAVD88 Geoid03 datum. Block J's embedded metadata does not establish acquisition year or vertical datum; both remain unknown. SCC16's original metadata supports a latest acquisition year of 2011 from 2010/2011 observations, replacing the old unknown year; it retains NAVD88 Geoid09. This supported metadata correction and changed eligible source set require normal processing. No private-physics adoption or threshold changes are used. Native spacing is not total positional accuracy, and unresolved interpolation/uncertainty remain explicit.

## Physical results and comparison

Run Morro r09/r10 and northern Arguello r01 as the three-reach batch. Refresh already processed Morro r08 separately because Avila touches that boundary. Preserve the original current-parent runs, then apply the same final current screen to their original physical candidates for a comparable source-only baseline.

| Reach | Selected eligible km² before → after | Physical before → after | Passing with same screen before → after | Habitat km² with same screen before → after |
| --- | --- | --- | --- | --- |
| morro-bay-r08 | 53.610140 → 60.959923 | 1026 → 1011 | 997 → 973 | 7.124017 → 7.875941 |
| morro-bay-r09 | 0 → 31.704285 | 0 → 196 | 0 → 194 | 0 → 5.739438 |
| morro-bay-r10 | 0 → 35.428616 | 0 → 1042 | 0 → 965 | 0 → 8.955659 |
| point-arguello-conception-r01 | 9.007900 → 39.202650 | 325 → 915 | 301 → 849 | 1.922382 → 10.373022 |

Source eligibility changes add 104.677435 km² of selected support from already held measurements, 1,813 physical candidates, 1,683 passing areas and 23.897662 km² of passing habitat under the same screen. Tier 1 planning-cell area increases 109.4925 km²; that is a different measure from surveyed support. The original Arguello run held all 325 physical candidates for unreviewed scope; the scope review alone would release 301 of them and 1.922382 km². Consequently the total passing increase over original as-run outputs is 1,984, of which 301 is scope release, not source-derived gain.

Final four-reach output: **3,164 physical, 2,981 passing and 183 held**, covering 32.944060 km² of habitat. Morro r08 has fewer polygons after replacement but more habitat area. All passing polygons satisfy whole-polygon exclusions, depth and 1–3 habitat-fit contracts. These are habitat suitability candidates; local processing is not public deployment or fish presence.

## Complete-envelope scope review

The physical batch first ran with its original scope hold. The final screen reuses all three new-reach physical caches; it does not repeat terrain computation or remove exclusion geometry. Only the three reviewed reach IDs and scope rationale are added to the policy.

| Reach | Complete reference cells | West/east longitude | South/north latitude |
| --- | --- | --- | --- |
| morro-bay-r09 | 646 | -120.730681 / -120.642466 | 35.087216 / 35.177371 |
| morro-bay-r10 | 1053 | -120.757031 / -120.628229 | 35.049415 / 35.135014 |
| point-arguello-conception-r01 | 1986 | -120.811556 / -120.630698 | 34.959290 / 35.055696 |

Every full cell polygon lies inside the unchanged reviewed coastal bounds. Their envelopes are south of the existing [Diablo Canyon security area](https://www.ecfr.gov/current/title-33/section-165.1155) and north of [Vandenberg's Point Sal northern limit](https://www.ecfr.gov/current/title-33/chapter-II/part-334/section-334.1130), 34°54′08″ N. Existing complete CDFW MPA, NOAA conservation-area and fixed security geometries still screen every candidate. NOAA's [Chumash Heritage FAQ](https://sanctuaries.noaa.gov/chumash-heritage/faqs.html) confirms that sanctuary designation did not introduce regulations directly affecting lawful fishing; that does not waive other restrictions or boating obligations.

Official feeds were refreshed at October 2 06:59 UTC. Screen SHA256 `136533985530db00fa9b45c897a8b87c296f8ec861f1e6bee4b10876530c7fa3` passed and every released polygon has zero exclusion intersections or boundary touches. Current notices, harbor conditions, mobile-vessel restrictions and species/season/depth/gear rules remain trip-time checks. No launch-day or general fishing permission is inferred.

## Validation and publication

Private receipts retain exact handoffs, raw/normalized hashes, cell envelopes, physical-first holds, current-parent runs, comparable-screen results, final run receipts and independent whole-polygon verification. Preserve original as-run counts alongside the comparable baseline. The production workflow performs a fresh screen and owns ledger/PMTiles publication; no generated public totals are edited in this source PR. Independent review and exact-head CI precede merge, and public endpoints must be verified before reporting these candidates live.

Local validation: 72 tests and 3,602 subtests passed; platform regeneration, 2,331-file repository/privacy checks and website checks passed. Private final-screen receipts confirm physical reuse for r09/r10/Arguello r01; r08 required normal processing because its source set changed.
