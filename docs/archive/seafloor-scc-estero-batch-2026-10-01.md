# Native Point Estero–northern Morro batch — October 1, 2026

Inspect original SCC07–09 native **2 m and 5 m depth-band** bathymetry from
three checked NOAA-hosted CSUMB archives, totaling **617,069,933 bytes**.
The original links were observed on official publisher pages; all downloads
passed the shared source container/byte/checksum controls. Six native grids
were inspected and qualified through the existing bounded nested ArcInfo
adapter. No format, resolution, science threshold or public app changes.

| Native source | Spacing | Valid nominal 0–300 ft pixels | Within 200–300 ft |
| --- | ---: | ---: | ---: |
| [csumb-scc-block07-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block07_mb.html) | 2 m | 6,042,112 | 2,545,296 |
| [csumb-scc-block07-5m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block07_mb.html) | 5 m | 227,551 | 227,551 |
| [csumb-scc-block08-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block08_mb.html) | 2 m | 6,213,819 | 2,032,397 |
| [csumb-scc-block08-5m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block08_mb.html) | 5 m | 169,125 | 169,125 |
| [csumb-scc-block09-2m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block09_mb.html) | 2 m | 4,687,342 | 1,967,070 |
| [csumb-scc-block09-5m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block09_mb.html) | 5 m | 203,261 | 203,261 |

Actual native footprints span approximately 35.44–35.56° N. Native FGDC dates
agree with each block's abstract (2010); processing metadata specifies
NAVD88/Geoid09. Exact members, bounds, dates, original hashes and native mask
counts are in `catalog/csumb-scc-estero-native-sources.json`. Per-cell uncertainty
and separate interpolation masks remain unknown; grid spacing is not sounding
accuracy. Source pixel counts are not deduplicated geographic expansion.

The 2 m products terminate at 85 m. The 5 m products extend into deeper water, but
only positive valid pixels **≤91.44 m** enter this rollout. Preserve native 5 m
spacing instead of inventing 2 m detail. Same-acquisition 2 m/5 m companions and any
USGS compilation using them are one acquisition line, not independent evidence.
Rendered hillshade, slope, 5 m-all composites and deeper pixels are not used.

## Actual measured result

| Reach | Selected valid native km² | Physical candidates |
| --- | ---: | ---: |
| morro-bay-r01 | 44.467912 → 43.155482 | 478 → 462 |
| morro-bay-r02 | 55.277639 → 55.062084 | 789 → 792 |
| cambria-san-simeon-r02 | 46.423921 → 62.784835 | 237 → 296 |

Selected valid area increased **146.169472507 → 161.002401918 km²
(+14.832929411)**; planning Tier 1 **151.073750 → 168.235000 km² (+17.161250)**;
physical candidates **1,504 → 1,550 (+46 net)**. All are existing reach updates,
including actual outer-band support. Finest/newest per-cell selection prevents
summing overlapping acquisitions. New native surfaces may replace parts of
older selections and change candidate outlines; neither is proof of independent
new fishing grounds. The committed private proof retains exact source ownership,
before/after statistics and ranking distributions without private geometry.

After processing, 1,476 polygons have supported lingcod/reef-rockfish fits and
74 remain unknown. The existing species-specific 1–3 scale is unchanged, with
3 strongest. Suitability does not prove fish presence or confirmed rock substrate.
All three runs completed without incomplete terrain; every candidate is private,
nonexportable and within the nominal 300 ft ceiling (existing float32 tolerance).

## Release and remaining work

**Zero new live or exportable locations.** All six added rows are physical-only;
all prior 421 catalog rows unchanged (427 total). Reviewed
[CSUMB source terms](https://csumb.edu/undersea/sfml-data-library/), retained-physics
verification, current whole-polygon MPA/security screens, regional publication
and actual live-map/export verification remain separate requirements. Any MPA
overlap remains excluded at release; physics does not grant fishing permission.
No raw archive, private geometry, original metadata body or public ledger committed.

Full GIS suite: **1,050 passed, 14 allowlisted skips, 4,006 subtests**. Strict skip report,
platform build, repository/web and diff checks passed. App and science unchanged.
Depends on #169; fresh main reconciliation, independent review and exact-head CI
required before merge. The full Monterey–Point Conception goal remains active.

Next acquisition: SCC10–13 original product URLs were freshly observed and
saved in this batch's private `next-original-queue.json`; native footprints,
valid shallow pixels and available depth-band members remain uninspected.
Qualify useful original windows and process their real reference intersections;
never infer coverage from a program title or cruise bounds. Review release PRs
156/157/160/161 and the source stack independently before publication. Their
current absence of independent reviews is a release blocker, not a reason to
repeat successful physical processing or erase saved candidates.
