# Southern Arguello native survey batch — October 1, 2026

Inspect and privately qualify three original SCC26–28 native 2 m bathymetry
grids, totaling 285,774,584 archive bytes. The original product links were
observed on official NOAA survey pages, retrieved with the checked downloader,
and opened through the existing bounded nested ArcInfo adapter. The web browser
could not read blocks 26/28; direct publisher HTTP200 reads succeeded and are saved.
A web access failure is not evidence that the original archive is unavailable.

| Original source | Native acquisition dates | Actual nominal 0–300 ft pixels |
| --- | --- | ---: |
| [csumb-scc-block26-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block26_mb.html) | 20100908, 20100924, 20100925, 20100929 | 5,397,061 |
| [csumb-scc-block27-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block27_mb.html) | 20100912, 20100914, 20100924 | 3,668,486 |
| [csumb-scc-block28-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block28_mb.html) | 20100907, 20100911, 20100912 | 2,040,249 |

The native footprints extend from about 34.67 to 34.55° N, not all of California
or every depth in the planning band. Actual 2 m depth maxima are 52.61 m, 38.42 m
and 32.75 m; all shallow valid pixels, positive-depth masks and boundary limits
are inspected. Native FGDC processing identifies NAVD88/Geoid09. Calendar
dates agree with the per-block abstracts. No per-cell uncertainty or separate
interpolation mask was delivered; unknown remains unknown. Grid spacing is
not sounding accuracy. Same-acquisition derivatives are not independent evidence.
Exact bounds, grid members, original hashes, native CRS and resolutions are in
`catalog/csumb-scc-south-native-sources.json`.

## Measured result

| Reach | Selected valid native km² | Physical candidates |
| --- | ---: | ---: |
| point-arguello-conception-r05 | 28.122020 → 38.991812 | 767 → 1119 |
| point-arguello-conception-r06 | 56.900909 → 82.655035 | 947 → 1203 |

Selected valid coverage increased **85.022928413 → 121.646846460 km²
(+36.623918047)**; planning Tier1 **89.400625 → 127.866250 km² (+38.465625)**;
physical candidates **1,714 →2,322 (+608 net)**. Both are neighboring reach
updates; no new reach IDs. Finest/newest per-cell ownership prevents overlapping
survey footprints being summed as new independent grounds. Candidate geometry
may change as reach-wide terrain thresholds see additional measured pixels;
science thresholds were not tuned to increase counts.

Of the 2,322 resulting candidates,2,202 have supported lingcod/reef-rockfish fit
and 120 remain unknown. The existing species-specific 1–3 rubric is unchanged;
3 is strongest, and neither that fit nor terrain proves fish presence or
confirmed rocky substrate. All physical outputs completed, are nonexportable,
and pass nominal depth limits with the existing float32 boundary tolerance.
Per-reach ranks and selected source ownership are retained in
`docs/archive/scc-south-private-proof-2026-10-01.json` without private geometry.
All prior 416 catalog rows remain unchanged; three physical-only additions yield 419.

## Other cached source check and remaining gap

The cached PGE Avila Block I/J outer-product names were inspected instead of
assuming “25m” meant 2 m/5 m: native cc_bi_25mbath/cc_bj_25mbth actually have
**25 m** spacing, while 5 m-all companions have 5 m spacing. Their bounding envelopes
do not extend the previously inspected 2 m envelopes materially. These companions
remain **unqualified**, with no shallow-pixel/selected-footprint expansion claim;
matching envelopes do not prove matching valid masks. They cannot be counted
as independent evidence, and combined products require effective-resolution
review before terrain extraction. No native 5 m derivative entered this batch.

The native SCC26–28 grids do not establish full 200–300 ft coverage. Next acquisition
should prioritize actual outer-band original products and remaining SCC07–13
shelf windows, using their native masks and actual footprints rather than titles.
Backscatter/substrate/video can strengthen terrain suitability afterward.

## Release and validation

**Zero new live or exportable locations.** Sources remain physical-only pending
reviewed [CSUMB producer terms](https://csumb.edu/undersea/sfml-data-library/),
retained-physics transfer, current whole-polygon MPA/security screen, regional
publication and actual live map/export verification. NOAA hosting grants no
federal public-domain license to third-party originals. No raw archive, original
metadata content, private geometry, credential or public ledger was committed.

Full GIS suite: 1,050 passed, 14 allowlisted skips, 3,950 subtests. Strict skip report,
platform regeneration, repository/web and diff checks pass. App unchanged. This
batch depends on #167; reconcile onto fresh main and obtain independently authorized
review plus exact-head CI before normal merge. The full coastal goal remains active.
