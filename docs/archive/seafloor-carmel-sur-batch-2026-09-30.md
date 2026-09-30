# Carmel and Point Sur original batch — September 30, 2026

Original USGS1998 A4-98-MB EM300 SGF5G/SUR5G grids were qualified using the
original metadata, native grid inspection and current USGS rights policy. Both
retain native5m spacing and unknown vertical datum, accuracy and interpolation
mask. Same-survey products are not independent confirmation. Original downloads
and checksums are in the source review receipt, not committed binary archives.

| Reach | Selected valid surveyed km² | Tier1 planning-cell km² | Physical candidates | Supported terrain/fit ranks |
| --- | ---: | ---: | ---: | ---: |
| `monterey-point-sur-r04` | 73.689364982 | 76.36125 | 790 | 745 |
| `monterey-point-sur-r03` | 11.544077117 | 13.45250 | 128 | 91 |
| `big-sur-coast-r01` | 0.033800802 | 0.06125 | 1 | 0 |

Totals: +85.267243km² selected valid footprint, +89.875km² Tier1 planning cells,
919 physical candidates, **836 supported ranks** and83 metric-incomplete holds.
BigSur's overlap is only0.0338km², not a claim that BigSur is substantially mapped.
No new screened or publicly published area: all three reaches were processed
with `run --physical-only`. Legal holds do not block measured processing.

Lingcod fit: 57 candidates score3/3,779 score2/3;83 remain unknown. Terrain grade
is separate:9A,48B,779C. Fit measures configured habitat suitability, not catch
probability. There is no classified hard-bottom layer or independent fish
presence evidence for this batch. Unknown datum remains a nominal depth basis.
The source's 5m grid supports broader terrain areas, not individual small piles.
Shore/shallow gaps and source nodata remain missing; no shoreline or bounding-box
area was filled or credited as sonar coverage.

## Validation and reproduction

Source review: [native source receipt](../../research/receipts/seafloor-carmel-sur-native-review.json).
Private original/source receipts: `var/seafloor/usgs-legacy/`;
reviewed drafts: `var/seafloor/drafts/usgs-1998-{sgf5g,sur5g}-native.json`.
The ordinary planner selected Monterey r04/r03 and northern BigSur r01.

```
PYTHONPATH=src:. .venv/bin/python -m skippercast.seafloor plan --max-new 3 --json
PYTHONPATH=src:. .venv/bin/python -m skippercast.seafloor run --reach monterey-point-sur-r04 --physical-only
PYTHONPATH=src:. .venv/bin/python -m skippercast.seafloor run --reach monterey-point-sur-r03 --physical-only
PYTHONPATH=src:. .venv/bin/python -m skippercast.seafloor run --reach big-sur-coast-r01 --physical-only
```

111 seafloor/receipt tests and3,012subtests passed locally. Native extraction
parity and all previously qualified scientific raster identities were verified
in the separate merged reader PR#132. No habitat thresholds were changed here.

Next: spatially screen full Monterey candidate polygons against current MPAs and
fixed restrictions, then publish eligible outlines. Continue the separate BigSur
and southern-coast source batches; those reaches are still incomplete.
