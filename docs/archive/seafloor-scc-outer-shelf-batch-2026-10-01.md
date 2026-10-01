# Cached native outer-shelf batch — October 1, 2026

Privately qualify original SCC03/SCC04 native **5 m depth-band** bathymetry,
using already checked NOAA-hosted CSUMB archives. No new archive download.
Exact nested ZIP/grid members, source hashes, actual footprints, dates and
native resolution are in `catalog/csumb-scc-outer-shelf-native-sources.json`.
These are 80–250 m products, not 5 m-all composites, rendered slope/hillshade
or upsampled regional DEMs. Only positive valid depths **≤91.44 m** enter
coverage and habitat; deeper source pixels remain excluded.

| Original source | Embedded acquisition dates | Native pixels within 300 ft |
| --- | --- | ---: |
| [csumb-scc-block03-5m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block03_mb.html) | 20100319, 20100320, 20100425, 20100528, 20100708, 20100709 | 118,147 |
| [csumb-scc-block04-5m-native](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block04_mb.html) | 20100320, 20100417, 20100525, 20100526, 20100807, 20100808, 20100809, 20100810, 20100812 | 122,648 |

All listed shallow pixels are in the nominal 200–300 ft band. Their raster-cell
areas are source inspection counts, not deduplicated reach coverage. Native
resolution remains 5 m throughout the pipeline; small features below its useful
scale must not be invented or described as individual measured boulders. Final
depth surfaces are relative to NAVD88/Geoid09. Per-cell uncertainty and separate
interpolation masks remain unknown. Spacing is not sounding accuracy.

The original 2 m/5 m companions share acquisition lineage and archive hashes;
they are not independent evidence of habitat or fish presence. Finer/native
per-cell ownership retains the 2 m product where supported and prevents simply
adding both bounding envelopes or both pixel counts as geographic expansion.
The cached SCC02 archive has no named 5 m companion ZIP and was not promoted
as one. A program's intended depth ranges do not establish actual local coverage.

## Measured result

| Reach | Selected valid native km² | Physical candidates |
| --- | ---: | ---: |
| cambria-san-simeon-r01 | 49.222894 → 49.586900 | 361 → 361 |
| south-big-sur-san-simeon-r03 | 68.276710 → 70.103262 | 500 → 488 |

Across two existing reaches, selected valid native coverage increased
**117.499603707 →119.690162831 km² (+2.190559124)**; planning Tier 1
**123.367500 →126.168125 km² (+2.800625)**. Physical candidates changed
**861 →849 (−12 net)**. Additional measured terrain support changes the
reach-wide derived patches; science thresholds were not tuned to add markers.
The reduction is retained rather than reported as new fishing locations.

After processing, 804 polygons have supported lingcod/reef-rockfish fits and
45 remain unknown. The existing species-specific **1–3 rubric** is unchanged:
3 is strongest. Terrain suitability does not prove rock substrate or fish
presence. Per-reach ranking counts and actual selected source ownership are in
`docs/archive/scc-outer-shelf-private-proof-2026-10-01.json`. Both runs completed;
candidate masks, nominal depth limits and non-exportability were checked.
No private geometry or raw source content was committed.

## Release and next work

**Zero new live/exportable locations.** These two additions are physical-only;
all prior 419 source rows are unchanged (421 total). Original
[CSUMB publication terms](https://csumb.edu/undersea/sfml-data-library/), retained
physical-cache verification, current whole-polygon MPA/security screening,
regional publication and live-map/export checks remain separate. NOAA hosting
is not a federal public-domain license for third-party originals.

Full GIS suite: **1,050 passed, 14 allowlisted skips, 3,964 subtests**. Strict
skip report, platform regeneration, repository/web/diff checks pass. App and
science thresholds unchanged. Depends on #168; reconcile onto fresh main,
independent review and exact-head CI before merging. The full Monterey–Point
Conception goal remains active.

Next acquisition: original SCC07–13 native shelf windows, prioritizing actual
200–300 ft products/masks over new downloads of already-covered shallow bottom.
Keep any unavailable or absent product explicit; do not fill gaps with assumed
bathymetry. Improve substrate evidence after terrain with original backscatter,
habitat classifications and ground truth sharing documented lineage.
