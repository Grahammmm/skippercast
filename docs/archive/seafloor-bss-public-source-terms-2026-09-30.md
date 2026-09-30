# Reviewed original BSS publication terms — September 30, 2026

This batch qualifies six already-inspected CSUMB SFML originals for public
noncommercial use. It changes no depth values, native spacing, bounds, datum,
interpolation evidence, acquisition lineage or source ordering. Existing private
measured results are retained. Qualification is not spatial clearance and does
not itself add fishing locations to the live map.

## Original-producer policy and lineage

The [official CSUMB SFML library policy](https://csumb.edu/undersea/sfml-data-library/)
allows public use/display, asks for producer acknowledgment and requires express
permission for for-profit use. The legacy download library is offline, but the
reviewed NOAA acquisition archive preserves these original producer grids.
NOAA distribution does not grant federal public-domain rights to CSUMB data.
The producer's non-navigation restriction remains in the source-use notice.
The dated review is bound to each original archive SHA; no commercial permission
has been obtained or inferred. Mixed-source releases retain every source's terms.

| Original | Native spacing | Recorded source year | Review result |
| --- | --- | --- | --- |
| BSS01 | 2 m | 2011 | Noncommercial producer profile |
| BSS02 | 2 m | Unknown | Same profile; acquisition year remains unknown |
| BSS03 | 2 m | 2011 | Noncommercial producer profile |
| BSS08 | 2 m | 2011 | Noncommercial producer profile |
| BSS12 | 2 m | 2011 | Noncommercial producer profile |
| BSS13 | 5 m | 2011 | Same profile; zero valid requested reference overlap in two inspected reaches |

Each exact original URL, native adapter proof, archive SHA, nominal shallow-water
pixel count, rights review and normalized raster identity is in
`catalog/surveys.json`. This is the same six-original batch reviewed in
[the first private batch](seafloor-bss-private-batch-2026-09-30.md) and
[the adjacent batch](seafloor-bss-adjacent-batch-2026-09-30.md).
Their overlapping results are not independent evidence or additive area.

## Validation and release sequence

Native reinspection confirms all six normalized COG hashes are unchanged.
All scientific metadata outside release status/terms/notes is identical.
Schema and source-rights validation pass. The public planner selects three
bounded new reach jobs from the reviewed native windows; these are scheduling
estimates, not measured new coverage. BSS13's envelope does not create area.

Publisher terms are implemented by #150; map/GPX/offline consumers by #151.
The six saved originals cover 67.568532254 km² of selected valid private
footprint with 785 physical candidates, 697 supported ranks and 88 unknowns.
These totals include overlaps already reconciled across the batch; they are
not a new public coverage delta from this qualification.

Before release: reuse checked private physics where safe (#153), reconcile
three existing destination caches without discarding previous results, apply
the current whole-polygon spatial screen, then verify the production manifest,
features, source credits and exports. Unknown screen scope keeps habitat held.
The public ledger and live locations are unchanged by this source-only PR.
