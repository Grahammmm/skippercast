# Monterey native source batch — September 30, 2026

A repeatable physical mapping batch, dependent on the rollout pipeline in
[PR #114](https://github.com/Grahammmm/skippercast/pull/114) and bounded native
processing in [PR #115](https://github.com/Grahammmm/skippercast/pull/115).
Both remained open when this batch began; no owner merge or production upload
was performed. Existing Morro/Conception source and screening PRs were retained.
The previous goal turn delivered real r01 coverage and the tile fix; this turn
advances a different original producer product rather than repeating that work.

## Qualified source and geographic scope

The original [USGS DS781 Monterey bathymetry ZIP](https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/data/Bathymetry_2m_OffshoreMonterey.zip)
was reused from the earlier inspected cache and independently hash-verified:
`2a769bc2bb343f6df5041ad7cab7bfcfe3eb641e2ef0bba7f3709edcd07c17f1`,
223,411,714 bytes. Its exact member is
`Bathymetry_2m_OffshoreMonterey/Bathymetry_2m_OffshoreMonterey.tif`.
The delivered raster is 11,418 × 9,065 pixels, 2 m grid spacing, EPSG:26910.
The reviewed native window is WGS84 [-122.064886, 36.532722, -121.811775, 36.692799].
The bounding rectangle is not valid surveyed coverage: only valid nominal
0–91.44 m depth pixels contribute. Native inspection counted 51,449,760 valid
pixels and 32,571,329 nominal shallow pixels in this full window; the normalized
COG is 115,458,734 bytes. Pixel counts are not deduplicated reach areas.

The [fresh original bathymetry metadata](https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/metadata/Bathymetry_2m_OffshoreMonterey_metadata.xml)
confirms acoustic acquisitions 1998–2012 and lidar 2009–2010, NAVD88 depths, and
2016 publication/processing. The single acquisition year stays unknown. This
producer's nearshore NOAA TopoBathy Merge was resampled to a 2 m delivery grid;
its separate MBARI 5 m product was not merged into that grid. A 2 m pixel is
not proof of 2 m sounding precision or of a tiny isolated rock pile. Metadata
states accuracy no better than 2 m horizontally / 0.20 m vertically. No per-cell
interpolation or acquisition-lineage mask was supplied. Nominal depths are not
water-level-corrected navigation depths.

[The paired seafloor-character product](https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/data/SeafloorCharacter_2m_OffshoreMonterey.zip)
was downloaded once (1,744,935 bytes) and checked against its existing pinned
SHA-256. Its [fresh metadata](https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/metadata/SeafloorCharacter_2m_OffshoreMonterey_metadata.xml)
and native raster/VAT define the category mapping. It is EPSG:32610, 2 m spacing;
bathymetry and categories are aligned by the existing nearest-neighbor adapter.
Its video/sample-supervised interpretation of shared bathymetry and backscatter
adds substrate information, not independent depth or fish-presence evidence.

All 22 native values are explicitly decoded from the publisher's depth/slope
coding. Class 1 smooth sediment and class 4 coarse sediment in scour depressions
are conservatively excluded from reef candidates. Class 2 remains mixed sediment
and rock; class 3 is rugose rock/boulder. The metadata abstract says steep slopes
are absent, but the raster/VAT contains 101–113; those values use the documented
VALUE slope offset 100 and are preserved. Unknown/absent classes remain unknown.
Source metadata and native observations are pinned in the
[review receipt](../../research/receipts/seafloor-monterey-native-review.json),
with original-publisher URLs, hashes, rights and caveats. Public-domain government
reuse requires USGS/CSUMB acknowledgement; source/navigation notices are retained.

## Actual expansion and ranking

| Reach | New measured tier-1 km² | Selected valid footprint km² | Physical candidates | Terrain A / B / C | Lingcod fit 3 / 2 / 1 | Reef-rockfish fit 3 / 2 / 1 |
| --- | ---: | ---: | ---: | --- | --- | --- |
| monterey-point-sur-r01 | 21.253125 | 21.818020 | 292 | 78 / 169 / 45 | 227 / 65 / 0 | 197 / 77 / 18 |
| santa-cruz-monterey-bay-r13 | 55.740625 | 55.387307 | 313 | 14 / 76 / 223 | 84 / 229 / 0 | 82 / 200 / 31 |
| santa-cruz-monterey-bay-r12 | 24.878750 | 25.320745 | 67 | 0 / 5 / 62 | 0 / 65 / 2 | 0 / 45 / 22 |
| Total | **101.872500** | **102.526072** | **672** | **92 / 250 / 330** | **311 / 359 / 2** | **279 / 322 / 71** |

All candidates have sufficient neighborhood support to receive the existing
terrain/fit rankings. Those rankings remain physical planning proxies, not
locally calibrated optima or catch predictions. Reef-rockfish uses the existing
copper-rockfish habitat proxy; it does not promise the same habitat for every
rockfish species. The bathymetry-derived heuristic and categorical interpretation
share source lineage.

Compared with PR #115's ledger, coast tier 1 increases 145.963125 → 247.835625 km²;
selected valid footprint increases 142.619872 → 245.145944 km². Tier 2 remains
15.578340 → 15.578340 km². **New screened candidates = 0; new public/exported
locations = 0.** All 672 candidates are private and held as `screen-deferred`.
The current reviewed restriction scope does not include these Monterey reaches.
No MPA or security policy was loosened, and a hold did not prevent physics.
The ledger is generated by actual runs, not manually credited from survey bounds.

Seven of 46 Central Coast reaches now have physical assessments on this stack.
This is a useful Monterey batch, not completion of the California coast. The
remaining original-source queue and unresolved gaps stay visible in `plan`.

## Commands, validation and saved progress

```bash
PYTHONPATH=src:. .venv/bin/python -m skippercast.seafloor add-survey \
  --id bathymetry-2m-offshoremonterey-zip-172dbd1794 \
  --url https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/data/Bathymetry_2m_OffshoreMonterey.zip \
  --bounds -122.064886 36.532722 -121.811775 36.692799
# Explicit metadata/rights review sets the private draft license, retaining mixed dates.
PYTHONPATH=src:. .venv/bin/python -m skippercast.seafloor promote-survey \
  --draft var/seafloor/drafts/bathymetry-2m-offshoremonterey-zip-172dbd1794.json \
  --rights-url https://cmgds.marine.usgs.gov/data/csmp/OffshoreMonterey/metadata/Bathymetry_2m_OffshoreMonterey_metadata.xml
PYTHONPATH=src:. .venv/bin/python -m skippercast.seafloor run --reach monterey-point-sur-r01 --physical-only
PYTHONPATH=src:. .venv/bin/python -m skippercast.seafloor run --reach santa-cruz-monterey-bay-r13 --physical-only
PYTHONPATH=src:. .venv/bin/python -m skippercast.seafloor run --reach santa-cruz-monterey-bay-r12 --physical-only
```

Private caches and per-reach `run.json`, `physical.json`, candidate/held files
and hashes are saved under ignored `var/seafloor/`. Consolidated before/after,
grades, fits, timings and output hashes are in `var/seafloor/monterey-batch-progress.json`.
Repeats use the existing input/output verification and do not force a rebuild.
The r13 extraction has 30,602,199 native pixels and a maximum padded read of
1,263,376 pixels (27 owned tiles), proving the prior #95 fix on another real area.

156 focused GIS/seafloor contract tests passed (2,982 subtests). New offline
checks exercise slope/depth-coded sand/scour exclusion even with strong terrain
roughness, missing categorical coverage, refusal of unreviewed new codes, mixed
acquisition dates and same-survey identity. The prior two-binding test now checks
exact source-specific withdrawal rather than assuming the coast never expands.
Original hashes, geometry validity, nominal depth bounds and private/export-held
state were checked for all 672 candidates. Regional and search-plan outputs were
rebuilt from source. Record final full-suite and PR CI outcomes separately;
local environment failures are not counted as success. The full local Python run
had 1,001 passes, 18 private-cache skips and the same 23 unchanged HTTP fixture
failures (macOS OpenSSL rejects explicit-ECC test certificates). Local typecheck
and production build passed after the configured dependency release-age window
elapsed, without bypassing the policy. The local Node suite retained two
unchanged module-preload fixture failures; Linux PR CI must pass before merge.

## Remaining work and exact next batch

Merge #114 then #115 before this source batch. Preserve the newer shared ledger;
reconcile older overlapping ledger PRs rather than applying their full snapshots.
The next physical batch is the two remaining intersections of this qualified
product: `monterey-point-sur-r02` and `santa-cruz-monterey-bay-r11`, with actual
valid pixels deciding whether they earn coverage. Then inspect an adjacent
original Point Sur or Big Sur shelf grid (or NOAA BAG) to continue south.
No new metadata audit is needed for this Monterey product.

Separately review a coherent Monterey restriction scope (MPAs, federal areas and
applicable local security), refresh it, rescreen these saved candidates, then
encode/publish and verify public feeds and the map. That review must not restart
terrain work or stop the next physical source batch. Linux/GDAL reproduction of
the newly normalized COG and eventual R2/state-cache recovery still need a
production run; no cold-run/cloud-upload proof is claimed here.
