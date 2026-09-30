# Remaining Monterey native intersections — September 30, 2026

This batch starts from main `20f828aeec75995ffafa5e05d880cb07278925a1`,
after the owner's authorized merges of #114, #115 and #116, in that order.
All three heads had successful Offline checks and DCO. The stacked PRs were
retargeted to main before their merges; older overlapping source/screen PRs
were preserved. No whole historical ledger was cherry-picked.

## Acceptance and actual results

Process the two remaining intersections of the already qualified Monterey
producer product, preserve native resolution and nominal 300 ft bounds, rank
physical candidates, validate geometry and keep unscreened outputs private.
The generated ledger is from actual runs, not product bounding rectangles.

| Reach | New tier-1 km² | Selected valid footprint km² | Candidates | Terrain A / B / C | Lingcod fit 3 / 2 / 1 | Reef-rockfish fit 3 / 2 / 1 |
| --- | ---: | ---: | ---: | --- | --- | --- |
| monterey-point-sur-r02 | 2.765000 | 2.866118 | 52 | 14 / 33 / 5 | 39 / 13 / 0 | 27 / 16 / 9 |
| santa-cruz-monterey-bay-r11 | 24.955625 | 24.777177 | 10 | 0 / 0 / 10 | 0 / 10 / 0 | 0 / 10 / 0 |
| Total | **27.720625** | **27.643295** | **62** | **14 / 33 / 15** | **39 / 23 / 0** | **27 / 26 / 9** |

Coast ledger tier 1: **247.835625 → 275.556250 km²**. Selected valid footprint:
**245.145944 → 272.789239 km²**. Tier 2 is unchanged at **15.578340 km²**.
**New legally screened candidates: 0; new public/exported locations: 0.**
All 62 are held as `screen-deferred`. Their public habitat outputs are empty.
Nine of 46 Central Coast reaches now have physical assessments in this ledger;
neither these individual reaches nor the entire coast is completely surveyed.
Tier-1 support covers about 16.5% of r02's reference band and 33.9% of r11's.

r02 has 1,718,200 native window pixels and completed in 2.17 seconds; r11 has
10,611,630 pixels and completed in 6.02 seconds. Both use the existing native
monolithic path because they are below the tiled threshold. A repeat returned
`unchanged: true` for each; no forced terrain rebuild or new source download
was needed. r11's large measured footprint produces only ten grade-C patches;
surveyed smooth/sedimentary bottom is not automatically reef habitat.

## Evidence, quality and validation

Use the same [original-source qualification receipt](../../research/receipts/seafloor-monterey-native-review.json)
and [prior batch handoff](seafloor-monterey-batch-2026-09-30.md).
The original bathymetry SHA-256 is
`2a769bc2bb343f6df5041ad7cab7bfcfe3eb641e2ef0bba7f3709edcd07c17f1`;
normalized COG SHA-256 is
`b32698ae396fe34793ab3eb8aa049227b2f9d0f55791226e6cb64e71cd47b5c3`.
The paired substrate archive remains
`8ca813f1fbfd7afb231914d7a9ebdb5667559bf0172a2024f3d45e9180d94e08`.
The existing adapter verifies cache bytes rather than trusting an old download.
No source metadata, rights, grading thresholds or spatial policy changed.

Delivered grid spacing is 2 m, not guaranteed 2 m sounding precision. Mixed
1998–2012 acoustic / 2009–2010 lidar acquisitions, producer resampling, unknown
interpolation masks and NAVD88 nominal depths remain explicit. Shared
depth/backscatter/substrate lineage is not independent corroboration.
Species ranks are the existing planning heuristic; reef-rockfish uses the
copper-rockfish proxy, not an optimum for every rockfish species.

Every new polygon was checked: nonempty/valid geometry, sufficient metric
support for grade and fit, fit values 1–3, nominal depths between 25 and 300 ft,
held status and non-exportability. r02 spans 25.004–299.983 ft; r11 spans
197.466–205.584 ft. Held counts match physical counts and public counts are zero.
92 focused GIS/seafloor contract tests and 2,970 subtests passed. Platform and
search-plan regeneration left unrelated output unchanged. Repository/web checks
and diff checks passed. Full Linux PR checks must pass before this batch merges;
their final result is recorded in the PR. The known Mac TLS fixture issue is
not retried or represented as a successful full local suite.

## Reproduce or resume without rebuilding unchanged work

```bash
export PYTHONPATH=src:.
.venv/bin/python -m skippercast.seafloor run --reach monterey-point-sur-r02 --physical-only --fetch
.venv/bin/python -m skippercast.seafloor run --reach santa-cruz-monterey-bay-r11 --physical-only --fetch
.venv/bin/python -m pytest tests/gis/test_seafloor_*.py tests/contract/test_seafloor_*.py -q
.venv/bin/python -m skippercast.platform.build
.venv/bin/python scripts/build_search_plans.py
.venv/bin/python scripts/check_repository.py
.venv/bin/python scripts/check_web.py
.venv/bin/python -m skippercast.seafloor plan --region monterey-point-sur --max-new 3 --json
```

Private `var/seafloor/monterey-next-progress.json` retains before/after totals,
grades, species ranks, processing bounds, timings, validation, output hashes and
merge history. The per-reach source receipts, `run.json`, `physical.json`,
candidate and held geometry remain under ignored `var/seafloor/reaches/`.
No held coordinates or raw surveys are committed.

## Exact next step and remaining blockers

The currently qualified Monterey producer window has now been processed in all
five intersecting reaches. Further southward expansion needs a different
original source, not another refresh of these five reaches. Run the planner,
select `monterey-point-sur-r03`, and inspect an original NOAA shelf BAG or
USGS/CSUMB contributor covering that reach toward Carmel/Point Sur. Check
original survey footprint, shallow valid pixels, rights, resolution and lineage;
record a bounded access/format hold if unavailable. Do not infer coverage from
the CSMP program's statewide goal or promote a compilation as fine habitat.

Separately review Monterey MPAs, federal areas and applicable local restrictions
as one coherent screen scope, then rescreen the saved candidates without terrain
recomputation. Only passing polygons may enter public PMTiles or fishing exports.
Merging the pipeline/source stack starts main-only workflows; it does not prove
cloud cache reproduction, R2 recovery or public availability. The current main
seafloor run is [36731694768](https://github.com/Grahammmm/skippercast/actions/runs/36731694768).
Its result and any operational failure must be checked before claiming publication.
