# BSS reach spatial-release review — September 30, 2026

Extend the existing permanent planning screen to Big Sur r02/r03/r05/r06 and
South Big Sur r01/r02/r03. All whole reference-cell envelopes are within the
already-reviewed regional restriction-layer extent (-122.1, 34.4, -120.45,
36.62). The added envelopes span 35.613590953–36.236736744 N. No security-zone
coordinates, datum handling, exclusion margin or habitat threshold changes.

The [Monterey Bay danger-zone rule](https://www.ecfr.gov/current/title-33/part-334/section-334.1150)
places the Fort Ord shore boundary at 36°37′47″ N, with its seaward bearing
extending northwest; these added envelopes are entirely south, including the
existing conservative allowance. The Navy mining area lies farther north.
Diablo Canyon and Vandenberg stationary exclusions already in the screen lie
south of this batch. Moving-vessel restrictions, temporary closures, season,
gear and notices remain trip-time checks; this is not current fishing permission.

The official [CDFW Central Coast MPA network](https://wildlife.ca.gov/Conservation/Marine/MPAs/Network/Central-California)
is represented by the complete CDFW polygon layer, including restricted-area
components and holes. Every candidate is checked as a whole polygon, never only
its centroid. All MPA polygons are excluded conservatively. NOAA conservation
polygons and the existing security geometries are also checked.

The shared refresh succeeded at 2026-09-30T22:05:35.186558Z. The dated eCFR
API sections remain byte-checked against reviewed coordinates; Title 33's
available edition is up to date as of September 28. This is publisher currency,
not the retrieval timestamp. A changed section or failed layer holds publication.
Exact source URLs, hashes, counts and issue/currency metadata are retained in
the private snapshot/source receipts. Web-rendered eCFR pages may show an older
crawled edition; the direct versioned API refresh is the release input.

## Private screen result, before publication

| Reach | Physical candidates | Passed | Held |
| --- | ---: | ---: | ---: |
| Big Sur r02 | 0 | 0 | 0 |
| Big Sur r03 | 0 | 0 | 0 |
| Big Sur r05 | 19 | 13 | 6 |
| Big Sur r06 | 95 | 81 | 14 |
| South Big Sur r01 | 19 | 9 | 10 |
| South Big Sur r02 | 592 | 543 | 49 |
| South Big Sur r03 | 60 | 51 | 9 |
| Total | 785 | 697 | 88 |

Passed candidate habitat totals 13.17296546 km². All 88 held candidates lack
sufficient habitat metric support; they are excluded from export/publication.
These numbers are from direct screening of checked private outputs, not a
committed public ledger or a verified live publication. Source qualification
is a separate dependency (#154); map/export credits are already merged (#151).
The existing ledger remains unchanged by this scope-review PR.

Validation: successful fresh official-layer refresh, whole-reference envelope
assessment, offline screen/security regressions (including polygon boundary
touches, holes, changed sources and expiry), repository/web/diff checks. Use
the normal runner and publication verifier after source qualification; preserve
existing destination caches during reconciliation. This does not add fish
presence evidence or survey coverage outside the six inspected originals.
