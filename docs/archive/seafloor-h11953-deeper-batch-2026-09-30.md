# H11953 deeper-water batch — September 30, 2026

Reconciles the remaining 4 m and 8 m products proposed in #97 against current
main. Original checksummed BAGs were already cached: no repeated download.
The same August 29–September 5, 2008 NOAA acquisition underlies both bands and
the already qualified 2 m product. Native spacing, MLLW datum, productUncert,
unknown interpolation mask and same-acquisition lineage are preserved.
The [review receipt](../../research/receipts/seafloor-h11953-deeper-native-review.json)
records original metadata, identities, rights, counts and before/after outputs.

## Measured result

Against merged #127, Tier 1 planning cells increase 518.531875 → 585.875625 km²;
selected valid native footprint increases 507.011262 → 572.720159 km².
These are different measures, not summed. New selected native area is
65.708897 km² across Conception r06/r07. r05 was checked and contains no valid
pixels in this source window despite estimated bounding-box overlap; it remains
unmapped, not complete.

r06 grows from 359 to 1,281 physical candidates and r07 from 296 to 813.
1,959 now have supported species rankings; 135 have insufficient metrics and
remain unranked/held. Lingcod fit is mainly 2, with one fit-3 area in r07;
rockfish fit includes 24 fit-1 areas. These are habitat suitability, not fish
presence. Native 8 m grids support broad terrain rather than small rock piles.
Unknown substrate prevents upgrading terrain candidates to confirmed hard bottom.

After whole-polygon screening, r06 has 548 passing polygons / 6.543352 km²,
up from 73 / 0.820715 km². That is 475 additional screened candidates.
r07 remains private pending coherent local spatial review. Physical source
processing proceeds independently of that hold. No live publication is claimed
until the main production workflow and public bytes are verified.

## Commands and verification

Use the pinned seafloor runtime and `PYTHONPATH=src:.`:

- `python -m skippercast.seafloor promote-survey --draft var/seafloor/drafts/SOURCE.json --rights-url https://nauticalcharts.noaa.gov/data/data-licensing.html`
- `python -m skippercast.seafloor run --reach point-arguello-conception-r05 --physical-only --fetch`
- `python -m skippercast.seafloor run --reach point-arguello-conception-r06 --fetch`
- `python -m skippercast.seafloor run --reach point-arguello-conception-r07 --physical-only --fetch`
- `python -m research.lib.receipts`

Every physical polygon was checked for nominal depth bounds within 0–300 ft,
actual native spacing of 2/4/8 m, and private/nonexportable physical status.
The source inventory explicitly includes the review receipt before validation.
Focused GIS/contract tests, product regeneration, repository and web checks run
before the PR; current-head Linux CI is the merge gate.

## Remaining geographic work

Whole Monterey–Point Conception goal is active. Next finish the shared
Conception r07/r08 screen, verify the public layers, and expose screened habitat
for reef targets in the map. Then prioritize original survey gaps around
Carmel/Big Sur and northern Arguello, not repeat already-empty NOAA queries.
Review Monterey 334.1150 and applicable mobile zones before public publication.
Do not label a zero-data reach complete or turn coarser bathymetry into invented
small-pile detail. Private results remain in `var/seafloor/reaches/`.
