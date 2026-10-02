# Point Sal–Purisima release batch — October 1, 2026

Qualify nine existing original SCC17–25 native 2 m survey records for credited
noncommercial publication and extend the permanent spatial planning screen to
Point Arguello–Conception r02/r03/r04. This is the first overnight batch tracked
in [coordination issue #180](https://github.com/Grahammmm/skippercast/issues/180).
It changes source rights and reviewed scope; no terrain algorithm, ranking
threshold, source window, native pixel, datum or source ordering changes.

## Original sources and rights

The original NOAA acquisition reports identify CSU Monterey Bay Seafloor Mapping
Lab as producer: [SCC17](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block17_mb.html),
[SCC18](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block18_mb.html),
[SCC19](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block19_mb.html),
[SCC20](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block20_mb.html),
[SCC21](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block21_mb.html),
[SCC22](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block22_mb.html),
[SCC23](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block23_mb.html),
[SCC24](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block24_mb.html), and
[SCC25](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block25_mb.html).
All nine returned HTTP 200 during this review. Each catalog row retains its
original archive/member, SHA-256, reviewed native window and normalized identity.

The [producer policy](https://csumb.edu/undersea/sfml-data-library/) permits
credited public use and requires express permission for for-profit use. This
batch uses the existing `csumb-public-use-noncommercial` contract and current
noncommercial deployment profile. It does not grant for-profit permission.
Producer credits and the paid-deployment gate remain mandatory. NOAA hosting
does not make these CSUMB originals US-government public-domain data.

The grids retain nominal NAVD88 depths and native 2 m spacing. Per-cell
uncertainty and interpolation masks remain unknown. Suitable terrain is ranked
habitat, not an observation of fish or a navigation-grade depth guarantee.

## Scope and fresh spatial screen

Whole reference-cell envelopes, rather than point centers, were reviewed:

| Reach | West | South | East | North |
| --- | ---: | ---: | ---: | ---: |
| r02 | -120.800243 | 34.812118 | -120.640444 | 34.992239 |
| r03 | -120.721987 | 34.806320 | -120.609899 | 34.889594 |
| r04 | -120.836312 | 34.685891 | -120.611769 | 34.826076 |

Fresh original eCFR title 33 parts 165 and 334 were retrieved through the existing
gzip-aware transport after an initial plain request returned HTTP 406. The
current title was up to date through September 30, 2026; all existing reviewed
section hashes matched. The complete current CDFW inventory (155 features),
NOAA conservation inventory (29 features) and three security exclusions were
refreshed at 2026-10-02 03:20 UTC.

[33 CFR 334.1130](https://www.ecfr.gov/current/title-33/section-334.1130)
allows fishing subject to its restrictions. Vandenberg Zones 1–3 can close for
launches; those announcements require trip-time notices and radio/harbor checks.
Zone 4 remains conservatively excluded, including its boundary overlap with
r04. No launch-day opening is inferred. Diablo Canyon and Morro entrance rules
remain checked but lie north of these reach envelopes. Fort Ord is farther
north and San Miguel is south. The full-part review identified no additional
fixed local exclusion for this batch. Mobile escorted-vessel security under
[165.11731](https://www.ecfr.gov/current/title-33/section-165.11731), seasonal
fishing rules, gear and live notices remain trip-time requirements.

All CDFW MPA and NOAA conservation polygons remain excluded in full, even where
a fishery-specific permission might exist. This is a permanent spatial planning
screen, not current fishing permission.

## Local result, awaiting production verification

| Reach | Selected valid survey km² | Physical candidates | Screened areas | Screened habitat km² | Held |
| --- | ---: | ---: | ---: | ---: | ---: |
| r02 | 72.671627 | 964 | 881 | 12.986266 | 83 |
| r03 | 41.445755 | 554 | 518 | 7.259022 | 36 |
| r04 | 69.353978 | 100 | 72 | 11.224147 | 28 |
| Total | 183.471359 | 1,618 | 1,471 | 31.469435 | 147 |

These measurements and physical candidates existed privately before the
overnight baseline. Rights qualification and screening add **zero newly computed
survey area**; they prepare previously held habitat for release. Held candidates
include incomplete metric support and whole-polygon MPA overlaps. Each passing
polygon was independently tested against each projected exclusion-layer union:
zero intersections or boundary touches.

The existing numeric-cache dry run found no migration necessary. All three
`adopt-private-physics` checks passed; ordinary `run --reach` reused physical
results and applied the new screen. Source and science comparisons passed, with
original catalog ordering preserved. No forced terrain rebuild or archive
download was needed. Private proof remains under
`var/seafloor/overnight-20261002/`; the automatic ledger workflow owns the public
ledger update after production execution.

## Validation and release

The manifest, source-rights, rollout, screen and publication tests passed:
58 tests and 3,445 subtests. Current-head CI and independent review are required
before normal protected merge. The existing seafloor workflow then processes
the batch and publishes complete regions. A local result or green CI is not a
live claim: verify the ready manifest, exact archive bytes and HTTP Range
behavior after production finishes.

Next batch: import the worker-qualified original H11952 1 m source, whose
deduplicated shallow-footprint evidence remains separate from this rights-only
release, then continue eligible cached coastal reaches.
