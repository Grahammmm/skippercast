# Point Buchon native batch — September 30, 2026

## Completed deliverable

Merged #117 at `af65bc586` after its passing checks, then qualified the original
USGS Point Buchon bathymetry and paired substrate. Processed two new reaches,
`morro-bay-r07` and `morro-bay-r08`, with the existing native tiled pipeline.
Do not duplicate r06: overlapping work remains in open #91. No app UI, grading
threshold, spatial-screen policy or new source adapter was changed.

| Measure | Before (main after #117) | After this batch | Delta |
| --- | ---: | ---: | ---: |
| Tier 1 reference-cell coverage, km² | 275.556250 | 352.531250 | 76.975000 |
| Selected valid native footprint, km² | 272.789239 | 348.409823 | 75.620584 |
| Legally screened Tier 2 habitat, km² | 15.578340 | 15.578340 | 0 |
| New physical patches | 0 | 1,166 | 1,166 |
| New patches with supported species ranks | 0 | 1,131 | 1,131 |
| New public/exported locations | 0 | 0 | 0 |

| Reach | Tier 1 km² | Selected valid km² | Patches / ranked | Terrain A/B/C | Lingcod 3/2/1 | Reef-rockfish 3/2/1 |
| --- | ---: | ---: | --- | --- | --- | --- |
| morro-bay-r07 | 57.014375 | 55.907729 | 689 / 663 | 25/149/489 | 154/509/0 | 111/509/43 |
| morro-bay-r08 | 19.960625 | 19.712855 | 477 / 468 | 5/108/355 | 103/365/0 | 59/316/93 |

Thirty-five patches have incomplete metric support, remain unranked and carry
explicit contract/support holds. All 1,166 physical patches remain private
(`screen-deferred`), and public habitat files are empty. Eleven of 46 Central
Coast reaches now have physical assessments; partial footprints are not complete
coastal coverage. Habitat suitability does not claim current fish presence.

## Original sources and scientific limits

The [source review receipt](../../research/receipts/seafloor-point-buchon-native-review.json)
records original URLs, metadata/archive hashes, rights, valid-pixel counts,
actual substrate enumerations and source lineage.

- [Bathymetry metadata](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9KBGELE/134dbdd47ee649b1863acc6cfa6ed0e6/Bathymetry_OffshorePointBuchon_metadata.xml): original metadata freshly returned HTTP 200; reused verified 63,660,952-byte archive. Acoustic acquisition 2008; release 2022. Actual delivered grid is 2 m, with 5 m inputs resampled below 80 m. Nominal source-datum coverage extends to 91.44 m (300 ft); fine habitat is strictly shallower than 80 m (~262 ft). Deeper fine habitat remains a gap. Unknown vertical datum, quantitative accuracy and interpolation mask stay unknown.
- [Character metadata](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9KBGELE/ac4288bd38594e1fa6e89e139995ab73/SeafloorCharacter_OffshorePointBuchon_metadata.xml): fresh HTTP 200; reused verified 1,872,472-byte archive. Whole-raster inspection confirms only classes 1/2/3. Soft class 1 is excluded even on rough terrain. Sonar 2008 and video supervision 2012 are explicit; catalog ground-condition 2011 and metadata 10 m spacing do not override actual dates/pixels. The paired classification is one sonar evidence line, not independent sounding evidence.
- USGS public-domain terms allow redistribution with metadata/source attribution to USGS, CSUMB and UCSC. No raw surveys or private candidate coordinates are committed. Grid spacing is not sounding precision or navigation clearance.

## Commands and validation

Use the pinned `.venv` and `PYTHONPATH=src:.`:

```bash
python -m skippercast.seafloor add-survey --id bathymetry-offshorepointbuchon-zip-fcc90bde5c --url ORIGINAL_URL --bounds -120.979799 35.127465 -120.781601 35.296794 --local VERIFIED_ARCHIVE
python -m skippercast.seafloor promote-survey --draft var/seafloor/drafts/bathymetry-offshorepointbuchon-zip-fcc90bde5c.json --rights-url ORIGINAL_METADATA_URL
python -m research.lib.receipts
python -m skippercast.seafloor run --reach morro-bay-r07 --physical-only --fetch
python -m skippercast.seafloor run --reach morro-bay-r08 --physical-only --fetch
python -m pytest tests/gis/test_seafloor_*.py tests/contract/test_seafloor_*.py -q
python -m skippercast.platform.build
python scripts/build_search_plans.py
python scripts/check_repository.py
python scripts/check_web.py
```

94 focused tests and 2,972 subtests passed, including tile edges, missing data,
depth limits and the newly qualified source's effective-resolution boundary.
Both repeat runs returned `unchanged: true`; no forced terrain rebuild.
All 1,166 polygons are valid/nonempty, nominal depths are within the fine source
zone, exportable is false and public outputs are empty. r07 used a 34,403,478-pixel
window with reads bounded to 1,263,376 pixels, demonstrating the previous oversized
window blocker is removed for this source. Platform/search builds left unrelated
generated output unchanged. Repository/web checks and diff checks passed.
Full Linux PR CI is authoritative; check its linked run before merging.

## Problems encountered and exact next actions

1. The first r07 terrain attempt found a wrong assumed ZIP member. Inspected
   the actual archive and set the exact root-level member. Rerun succeeded;
   its coverage checkpoint survived. No repeated transport download.
2. Carmel/Point Sur r03/r04: a fresh NOAA NOS BAG query for the actual bounds
   returned zero leads. The CSUMB source website failed certificate hostname
   verification; do not bypass it. Existing Harold Heath metadata footprints
   checked were outside these reaches, with unresolved contributor rights.
   These are source-discovery gaps, not proof that no data exists. The private
   `var/seafloor/carmel-nos-leads.json` receipt records the exact endpoint and
   response hash. Switch to an original contributor/survey-footprint catalog.
3. [Production run 36731694768](https://github.com/Grahammmm/skippercast/actions/runs/36731694768)
   completed all ten workers but failed aggregation/publication. Its bot #106
   reports seven results rejected as `no current completed result`; three
   existing Morro reaches applied and zero bundles published. This is a saved
   result/aggregation verification failure, not evidence of an MPA blocker.
   Root cause is unverified. Reproduce the exact worker→private restore→finish
   path with a completed held reach, compare input hashes and restored summary,
   and fix it in a separate focused PR. Do not weaken current-batch checks.
4. Next measured batch: reconcile #91's southern Morro r05/r06 against this
   now-qualified Buchon source (do not overwrite its ledger). Then inspect the
   next original Conception survey from #97/#104 or adjacent Estero/Cambria work.
   Spatial review remains a separate sweep; only passing whole polygons may
   publish. A legal hold never requires rerunning unchanged physical extraction.

Private resumable state: `var/seafloor/point-buchon-batch-progress.json`, source
cache, reach receipts and repeat-run output. This batch is not live. Its merger
can unlock scheduled processing but does not prove successful public publication.
