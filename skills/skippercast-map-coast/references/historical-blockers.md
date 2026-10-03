# Historical Blockers

Historical evidence only. Reconcile current main and receipts before applying any old backlog or baseline. Do not read this during ordinary execution unless a specific prior failure needs comparison.

## Evidence and audit baseline: September 29, 2026

Recompute this baseline; do not preserve these numbers as current truth. At
main `026ab3d77`, the catalog had 385 records (3 usable, 381 candidate, 1 hold),
46 Central Coast reaches and a provisional 3,307.514375 km² reference band.
Mapped cell area was 100.713125 km²; selected valid native footprint was
98.151960 km²; screened habitat was 16.611763 km² / 1,006 polygons. These measures
are distinct: Tier 1 classifies planning cells at the 25% support threshold;
selected valid footprint measures surveyed intersections; Tier 2 is habitat,
not all surveyed bottom. Three Morro Bay reaches were on main, 43 unassessed.

The source catalog preserves the earlier surveys and metadata receipts. Earlier
research also produced hundreds of scripts and a stricter datum qualification
workflow. Its research outputs are leads, not additional published coverage.
Do not redo that corpus or impose navigation-grade datum conversion on Tier 2.

Observed causes and the concrete response:

| Cause / evidence | Response and remaining work |
| --- | --- |
| `jobs.select` formerly selected only processed reaches | `plan` schedules intersections of usable native windows with new reference reaches. Catalog promotion now unlocks work without a hand-edited ledger PR per reach. |
| Legal snapshot was included in the terrain cache key | `physical.json` hashes source/rule outputs separately. Snapshot changes rescreen saved candidates. `run --physical-only` deliberately defers the legal step. |
| A worker failure skipped the entire publication job | Per-batch private receipts identify completed, coverage-only and failed work. Aggregation runs after failures; other complete regions can publish. Missing/interrupted receipts never count as current success. |
| A >20-million-pixel habitat window lost already computed coverage ([#95](https://github.com/Grahammmm/skippercast/issues/95)) | A checked coverage checkpoint survives and is reported as `terrain-pending`. Large native windows now use bounded owned tiles, derivative halos, reach-wide thresholds, and joined components. Run the tiled/untiled parity tests and retain processing pixel/read bounds; insufficient scratch space still preserves the coverage checkpoint. |
| [Run 36500826580](https://github.com/Grahammmm/skippercast/actions/runs/36500826580) failed in all three workers | Logs show missing `jsonschema`. Main now installs the combined seafloor requirements and validates before writes. Do not diagnose this old run as an MPA failure. |
| [Run 36617058494](https://github.com/Grahammmm/skippercast/actions/runs/36617058494) failed during normalized-source verification | Logs show a reviewed COG hash mismatch. Preserve byte verification; investigate normalization/runtime differences rather than accepting arbitrary new bytes. Later runs passed. |
| [Run 36629238770](https://github.com/Grahammmm/skippercast/actions/runs/36629238770) published and verified tiles but failed opening the ledger PR | GitHub Actions lacked PR-creation permission. Later runs passed; #107 added explicit CI dispatch for bot-created PRs. Distinguish data publication from bookkeeping failure. |
| #91/#92/#94/#97/#104/#110 edit shared catalog, ledger or screens | Reconcile source/code dependencies once, rerun from current main, and let the scheduled job generate one ledger-refresh PR. Never cherry-pick an older whole ledger over newer reach results. |
| Many catalog products remain candidates | Batch original sources by format and geographic footprint; native inspection plus rights review is still required. Metadata counts are not mapped area. |
| Grades had two inconsistent ledger fields | New summaries populate `habitat_by_grade` and legacy `polygons_by_grade` consistently. |

Five later seafloor runs through [36658855204](https://github.com/Grahammmm/skippercast/actions/runs/36658855204)
succeeded. A green refresh alone is not geographic expansion: inspect the area
and candidate-count delta and the public manifest.


## Execute the remaining backlog in this order

1. **Reconcile existing work.** #91 adds southern Morro; #92 fixes deep Point
   Estero effective resolution; #94 adds southern Cambria; #97 and #104 add
   Conception NOAA depth; #110 supplies part of the Vandenberg screen. Check
   current status. This rollout includes the #92 resolution correction; reconcile its
   existing PR instead of applying it twice. Rebuild shared output after merging, never add PR totals.
2. **Use bounded native processing (#95).** `build_candidates` selects the
   disk-backed tile path above 20 million pixels; do not split accepted reach
   ownership or change resolution to avoid the guard. Verify
   `tests/gis/test_seafloor_habitat_tiles.py`, then retain the run receipt and
   `candidates.geojson` processing metadata. Budget scratch space for the native
   window, sample vectors and labels; resource failures retain coverage and
   must be investigated instead of repeated blindly. See the
   [r01 proof and handoff](../../../docs/archive/seafloor-tiled-habitat-2026-09-30.md).
3. **Finish the inspected Monterey product.** Reuse the original DS781 2 m ZIP
   and private draft if present; verify bytes and mixed 1998–2012/2009–2010 input
   dates. Qualify the native window, then run all intersecting reaches. It is
   not completed just because the archive was downloaded.
4. **Batch adjacent originals.** Work north through Monterey/Aptos/Santa Cruz and
   south through remaining Morro/Buchon/Conception windows. For Big Sur and
   San Simeon, prioritize NOAA native shelf products and original contributors;
   a USGS program footprint is not proof of local coverage.
5. **Legal release sweep.** Screen completed physical outputs in regional batches.
   Where security evidence needs specialist review, leave that scope held and
   release other reviewed regions. MPA review never restarts acquisition.
6. **Audit the map from the visitor's perspective.** For reef/lingcod, check each
   released region's manifest, archive and map filtering. A public archive alone
   does not prove the UI selected it. Report data-feed and UI failures separately.
7. **Expand the reference scope only after the Central Coast loop is proven.**
   Add regional packages and explicit boundaries to the scope catalog, rebuild
   the reference with a migration of accepted reach IDs/ownership, review new
   sources and legal scope, then use the same planner/runner. Current scope is
   seven regions; this feature does not magically create statewide coverage.

