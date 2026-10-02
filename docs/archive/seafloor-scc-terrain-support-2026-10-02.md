# SCC24–28 native terrain support — October 2, 2026

Bind five original CSUMB rough/smooth grids to their exact original 2 m depth
products using the reviewed native-terrain method. SCC24/25 remain usable;
SCC26–28 remain physical-only. No source rights, quality hold, depth limit,
habitat formula or spatial restriction is relaxed. No new measured geography
is acquired in this batch.

## Source evidence

The four source-only receipts in `research/receipts/` are
`seafloor-scc24-25-native-terrain-review.json` and
`seafloor-scc26-terrain-review.json` through `seafloor-scc28-terrain-review.json`.
They identify original publisher URLs, archive/member hashes, native alignment,
class metadata and legend. The combined before/after review is
`seafloor-scc24-28-terrain-binding-review.json`.

The interpretation is derived from the same survey DEM: it is positive support
for rough terrain, not independent rock/sediment evidence. Manual smoothing and
heave exclusions are not a comprehensive artifact mask. Unknown accuracy and
interpolation remain unknown. SCC25 metadata conflict is retained: its abstract
and NOAA record report September 30–October 14, while structured fields repeat
SCC24 dates. Source dates and native datum are not rewritten by this binding.

Both calibration and extraction use supported cells. Missing class values do
not remove valid measured depth, and cannot create rough habitat. The unchanged
shared calibration formula can change cutoffs for neighboring unbound sources;
the proof therefore compares every affected reach and contributor.

## Measured comparison

Normal processing reused checked caches, without `--force`. Selected coverage
cell records are identical before and after, including source choice. Their
receipt identity changes when relevant bindings change.

| Reach | Selected valid km² (unchanged) | Physical before → after | Screened before → after | Habitat km² before → after |
| --- | ---: | ---: | ---: | ---: |
| point-arguello-conception-r04 | 69.353977618 | 100 → 225 | 72 → 161 | 11.224146973 → 8.166707806 |
| point-arguello-conception-r05 | 28.122019530 | 767 → 29 | 0 → 0 | 0 → 0 |
| point-arguello-conception-r06 | 56.900908883 | 947 → 947 | 452 → 452 | 2.838981687 → 2.838981687 |

The affected r04/r05 physics recomputed. The unaffected NOAA-only public r06
reused its physical cache unchanged. Net screened outlines increase **89**,
while eligible habitat decreases **3.057439167 km²**. This is fragmentation and
boundary refinement, not new sonar coverage or increased fish abundance.
All eligible polygons pass the current whole-polygon CDFW, NOAA and security
screen and retain valid 1–3 species ranks and 25–300 ft product depth properties.
All 29 r05 candidates remain held for unreviewed screening scope.

The all-source private runs retain 32 physical candidates in r05 and 840 in r06,
at 38.991811670 and 82.655034790 km² selected support respectively. These totals
include private sources and must not be added to the public subset. SCC26–28
yield four, 24 and ten candidates. Source status and publication holds remain.

## Native diagnostic review

An earlier proof visually examined all 39 SCC26–28 candidates across 13 pages
of original numeric depth, contextual plane residual and same-survey class.
Its later shared-calibration change reduces SCC26 from five to four patches;
the combined receipt explicitly distinguishes that earlier geometry from the
final outputs. The earlier proof had zero eligible patches: five in unreviewed
screen scope and 34 intersecting MPAs, including 27 also intersecting security
areas. This batch does not publish them or use those checks to clear source
quality holds.

For the final public-source SCC24/25 proof, all 109 SCC24 candidates received
native-center numeric diagnostics and 18 deterministic samples were inspected
visually across six pages. SCC25 has no extracted candidates. Sampled terrain
includes connected nearshore ridges/outcrops and isolated edges. Native-center
rough support is at least 98.45%; no selected center has missing class data.
Those comparisons can differ slightly from projected polygon edges. They are
not exhaustive artifact checks, independent substrate accuracy or navigation
depth certifications. Diagnostic images and held geometry stay private.

The reusable research-only panel tool reads hash-checked existing outputs and
native sources; it cannot change ranks, holds or publication. It requires the
seafloor runtime plus optional `matplotlib` (reviewed with 3.10.6). Example:

```bash
PYTHONPATH=src:. python research/scripts/audit_native_terrain_support.py \
  --root . --stage standard \
  --reach point-arguello-conception-r04 \
  --reach point-arguello-conception-r05 \
  --source csumb-scc-block24-2m-native \
  --source csumb-scc-block25-2m-native \
  --panel-limit 18 --output var/seafloor/NEW_PRIVATE_AUDIT
```

It refuses an existing output directory and diagnostic windows larger than
eight million native pixels; it never resamples to bypass that bound. Native
quantitative diagnostics cover every selected feature, even when panels are
sampled. Do not publish its private candidate identifiers or locations.

## Release and next batch

The committed ledger remains production-workflow owned. The existing locked
seafloor workflow must rebuild affected archives and verify current public
manifests and HTTP byte ranges before these local results are called live.
Retain credited CSUMB noncommercial and not-for-navigation terms. The next
independent batch is original PGE South terrain support; held SCC26–28 work
does not block that processing.
