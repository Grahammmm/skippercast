# Cambria–San Simeon native-grid release — October 1, 2026

Qualify the existing original SCC01–08 2 m grids and SCC03/04/05/07/08 5 m
grids under the credited noncommercial CSUMB contract. Preserve source ordering,
original and normalized hashes, native windows, nominal NAVD88 depths and the
unchanged habitat rules. Per-cell uncertainty and interpolation remain unknown.
Same-acquisition bands are not independent evidence.

The original acquisition reports identify CSU Monterey Bay Seafloor Mapping Lab:
[SCC01](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block01_mb.html),
[SCC02](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block02_mb.html),
[SCC03](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block03_mb.html),
[SCC04](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block04_mb.html),
[SCC05](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block05_mb.html),
[SCC06](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block06_mb.html),
[SCC07](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block07_mb.html), and
[SCC08](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block08_mb.html).
All eight reports returned HTTP 200 during this review. Each native product was
reopened through the existing adapter and its original/normalized bytes verified.
The [producer policy](https://csumb.edu/undersea/sfml-data-library/) requires
credit and express permission for for-profit use. The noncommercial deployment
gate, notices and no-navigation restriction remain in place; NOAA hosting is not
public-domain permission for these originals.

## Reusable-cache failure and fix

Cambria r02 initially failed `migrate-numeric-cache` with `Substrate inputs
changed`. The sole difference was the existing Point Estero categorical row's
resolution: legacy JSON integer `2`, normalized manifest float `2.0`. Native
bytes, classes, review, datum and lineage were unchanged. Normalize only the
same schema-declared measurement fields already normalized for depth rows,
compare every remaining binding field, verify source bytes, preserve the complete
old receipt and require a fresh screen. Genuine resolution or evidence changes
still fail. No numerical processing implementation or scientific threshold changed.

An offline native-raster fixture reproduces the legacy categorical receipt.
It verifies an untouched dry run, full recovery, unchanged candidate bytes,
refusal of actual resolution/date/evidence changes, a held transitional state,
and ordinary runner reuse with coverage and terrain recomputation made fatal.
The real Cambria r02 cache then passed the same dry run and migration. Southern
Big Sur r03 needed the existing depth-row numeric migration; Cambria r01 needed
none. All three rights-only adoptions and subsequent normal runs reused physics.

## Spatial screen

Add Cambria r01's whole reference-cell envelope, W -121.284710, S 35.567163,
E -121.160464, N 35.663462, to the existing reviewed coastal scope. It is south
of Fort Ord and north of Diablo Canyon and Vandenberg. The original title 33
parts 165/334 review from this release session remains applicable; no new fixed
exclusion coordinates were introduced. Existing Cambria r02 and southern Big
Sur r03 were already reviewed.

The new snapshot was fetched at **2026-10-02 04:03 UTC**. All CDFW MPA polygons,
NOAA conservation areas and existing security exclusions apply to complete
candidate polygons. Independent overlap checks found zero intersections or
boundary touches in the passing output. Launches, moving vessel buffers,
season/depth/gear rules and current notices remain trip-time checks. This is a
spatial planning screen, not a declaration that fishing is currently permitted.

## Local results; production verified separately

| Reach | Selected valid km² before → after | Physical candidates after | Screened areas before → after | Screened habitat km² after | Held |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cambria r01 | 0 → 49.586900 | 361 | 0 → 326 | 8.197403 | 35 |
| Cambria r02 | 7.091355 → 62.784835 | 296 | 47 → 225 | 3.548911 | 71 |
| Southern Big Sur r03 | 4.844459 → 70.103262 | 488 | 51 → 60 | 0.629329 | 428 |

Before values are the public ledger subset. These **182.475 km² and 1,145
physical candidates already existed privately** before this overnight batch;
qualification/adoption do not count as newly computed geographic coverage.
The planned release raises selected measured support over the prior public
subset by **170.539 km²**, and screened candidate count by **513**. It preserves
534 held candidates. Most southern Big Sur candidates intersect MPAs; they stay
private. Its screened habitat area falls from 0.898501 to 0.629329 km² as the
finer source set replaces the prior subset, despite nine more passing polygons.
No fish-presence evidence is required or claimed.

The existing default workflow also reevaluates any already processed neighboring
reach whose selected source set changes. Those effects must be measured from
its production receipts; they are not included in this three-reach local result.

## Reproduction and release

Use the existing native drafts and caches, `promote-survey`, then restore original
catalog ordering. For legacy receipts, run `migrate-numeric-cache --private`
without `--apply` first, then apply only a verified numeric-only migration.
After rights qualification use `adopt-private-physics`, `refresh-screen`, and the
ordinary `run --reach` for each reach. No force, archive download or new pipeline
is needed. Private proof is under `var/seafloor/overnight-cambria/`.

Focused seafloor validation passes: 66 tests and 3,445 subtests, followed by
platform regeneration and repository/web checks. Current-head full CI and
independent review remain required. The production workflow owns the generated
ledger and publishes complete regional archives. Confirm ready manifests and
exact PMTiles HTTP Range responses before reporting this batch live.
