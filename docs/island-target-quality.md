# Original-survey island habitat targets

The first qualified island release contains **11 surveyed habitat candidates: eight around Anacapa and three on eastern Santa Cruz**. Each has a bounded search outline and a numerical bottom view. These are places to investigate with a sounder, not verified catches, charter stops, individual rock piles or navigation routes. The release is deliberately partial; it does not establish that the rest of either island lacks habitat.

## The source improvement

The earlier NOAA NCCOS merged grid remains useful regional context, but its documentation does not establish a common named vertical reference or per-cell uncertainty. The new compiler downloads the original NOAA survey products instead:

| Survey | Actual survey coverage | Acquisition | Inspected native data |
| --- | --- | --- | --- |
| [H13093](https://www.ngdc.noaa.gov/nos/H12001-H14000/H13093.html) | Vicinity of Anacapa Island | October 19–November 6, 2017 | 96,915,638-byte variable-resolution BAG, NAD83/UTM 11N, MLLW, signed metre elevations and `productUncert` values |
| [H13323](https://www.ngdc.noaa.gov/nos/H12001-H14000/H13323.html) | Cavern Point to Smugglers Cove, eastern Santa Cruz | October 4–21, 2019 | 31,537,503-byte variable-resolution BAG with the same explicit coordinate/depth reference and uncertainty type |

Both official dataset pages explicitly dedicate the data to **CC0-1.0**. Attribution to NOAA/NOS and the survey vessels is preserved. The dataset notices say these are not standalone navigation products. BAG content, embedded metadata and the inspected descriptive reports are hash-pinned in `regions/southern-california/bottom-sources.reviewed.json`. Validated discovery records live in `catalog/candidates/noaa-h13093.json` and `noaa-h13323.json`; catalog validation itself is not a publication approval.

The original BAGs have **1, 2, 4, 8 and 16 m native cells**. Only actual 1–4 m native supergrids are eligible here. The large coarse overview and interpolated NOAA ImageServer display are not imported as high-resolution measurements. A metadata envelope is not a valid-data footprint. The implementation reads original native arrays; its origin, row direction and values were independently checked against GDAL's BAG supergrid reader at 1, 2 and 4 m for both surveys. The [GDAL BAG documentation](https://gdal.org/en/stable/drivers/raster/bag.html) explains the distinction between native supergrids, resampled grids and interpolated displays.

## Qualification, before ranking

The first build processed approximately 6.8 million valid native nodes in the relevant habitat neighborhoods. Qualification runs before polygon aggregation or scoring:

1. Require a reviewed MLLW datum, actual survey dates, an unmodified native file and known product-uncertainty semantics. Unknown datum, unexpected overrides, missing files and source changes hold the release.
2. Require finite underwater elevation, finite positive product uncertainty no greater than 1 m, and native spacing at most 4 m. Zero, missing or rejected uncertainty does not become “perfect accuracy.”
3. Retain nominal depths of at least 25 ft. Require **native depth + reported product uncertainty + a stated 2 m planning allowance ≤200 ft**. The allowance is a conservative planning choice, not a tide forecast or a promise about the actual water level at a chosen time. No unsupported 95% interval is assigned to the uncertainty value.
4. Build footprints from qualifying native cell supports. Subtract invalid cell supports, including overlaps between adjacent supergrids. Preserve holes, remove a 4 m inward margin and intersect with the actual historical hard-substrate geometry.
5. Remove all imported MPAs and Groundfish Exclusion Areas with 75 m clearance. The entire polygon is screened. Closure snapshots must be complete for the region and no more than 36 hours old; seasonal species rules and actual access are checked separately by the app.
6. Keep supported connected geometry rather than bridging gaps with a hull. Candidate search outlines extend at most 200 m from a marker and stay inside the qualified footprint. Simplification is intersected back with that footprint. Nominal depth summaries conservatively include native cells touching each outline, rather than just cell centers inside it.
7. Limit the initial release to eight distinct targets per island, with at least 650 m spacing. The eastern Santa Cruz source/closure/footprint combination yields only three. More dots are not evidence of more accuracy.

The supported historical-hard-substrate footprint is approximately 16.2 km² around Anacapa and 0.57 km² in this eastern Santa Cruz survey subset. Only selected search patches within that support are published as the 11 target outlines; the full support area is not claimed to be exported.

The hard/soft substrate interpretation is still the older NOAA 2006 compilation. It is not target-specific ground truth. Resolution of the original bathymetry does not improve the older classification's unknown positional accuracy. The Anacapa [descriptive report](https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H12001-H14000/H13093/DR/H13093_DR.pdf) also describes dynamic ridges southwest of West Anacapa. Relief alone must not be called bedrock or a measured boulder. Improving substrate and camera/sample ground truth is the next important bottom-data step.

## Transparent terrain rank

This rank helps compare physical habitat candidates. It is **not a calibrated bite probability**, and a B site can fish better than an A site. Confidence in the evidence is shown separately and remains Moderate because substrate is historical and no target-specific catch validation exists.

Use native samples in the supported hard-bottom footprint within 250 m. Average observations into 4 m analysis bins so dense 1 m data do not dominate 4 m data. Fit and remove the broad local plane before measuring complexity. The score is:

`35 × R/(R+12 m) + 40 × C/(C+2 m) + 25 × A/(A+5 ha)`

- `R`: 95th–5th percentile depth relief, limiting sensitivity to isolated extrema.
- `C`: RMS residual after removing the fitted plane; a simple slope is not complex rock.
- `A`: area of qualified historical hard substrate within 250 m.

The constants are explicit comparison scales, not fitted species optimums. Smooth saturation preserves differences among rough patches instead of assigning all of them 100. The shared application grades are A at least 75, B at least 55 and C below 55; the first qualified island set spans **27–73**, so none is advertised as A. Each record stores the thresholds, components, source resolution, formula, slope, uncertainty gate and a null catch probability. The original Morro Bay ranking uses a different method; the UI must present the method belonging to the selected record, not compare the scores as statistically interchangeable.

## Numerical bottom views

Each released target has a 129 ×129, 4 m display grid spanning 512 m. A display cell is the mean of actual native 1–4 m nodes inside that bin. Unpopulated cells stay blank; no interpolation fills gaps. Display means are never used to qualify depths. Values are encoded at 0.1 m for storage, which is not a claim of survey accuracy. The native resolution range is preserved separately from the 4 m rendering grid.

The image can extend outside the qualified search outline and include deeper water. It shows historical bathymetric relief, not present kelp, sediment texture or fish. These tiles use the existing scientific renderer and retain source-file hashes and tile integrity hashes.

## Reproduce and extend

Use Python 3.12+ and the optional GIS environment pinned in `requirements-survey.txt` (CI uses Python 3.13). The reviewed first run used NumPy 2.5.3, SciPy 1.17.1, rasterio 1.5.1/GDAL 3.12.4, Shapely 2.1.2, pyproj 3.8.0, h5py 3.15.1 and affine 3.0.1. Version changes deserve geometry/array comparison rather than silently accepting new output. This optional compiler does not raise the core application's Python requirement.

```bash
python -m pip install -r requirements-survey.txt
python scripts/build_socal_targets.py --fetch
PYTHONPATH=src python -m unittest discover -s tests -p test_bottom_targets.py -v
PYTHONPATH=src python -m skippercast.platform candidate --file catalog/candidates/noaa-h13093.json
PYTHONPATH=src python -m skippercast.platform candidate --file catalog/candidates/noaa-h13323.json
```

The compiler defaults to the hash-pinned cache. `--fetch` obtains missing original files with bounded validated HTTP ranges and retains acquisition receipts. It does not silently approve changed bytes. An unavailable or changed source, stale legal geometry, wrong region or empty qualified result produces a held health record and retains the prior release. The existing source-monitor/publication process should own the refresh; do not create a second competing daily scraper for these historical surveys.

Output lives in `dist/regions/southern-california/qualified-bottom/`:

- `atlas.json`: a fragment containing qualified targets, areas and source records; no fabricated drift tracks.
- `bottom-index-fragment.json`: hashes and paths for the `SCI-Q-*.json` tiles in the regional `bottom/` directory.
- `quality.json`: qualification methodology, acquisition receipts, counts, limitations and closure fingerprints.
- `manifest.json`: final artifact hashes; written only after a successful build.
- `health.json`: latest success or held attempt, independent of retained usable content.

The shared regional build should integrate the ready atlas/index fragments and update region coverage as **partial**, preserving the larger context layer. It must not rerun old unknown-datum data through this qualification adapter. It should monitor official source metadata monthly, recheck legal sources on the existing daily schedule, and rebuild only after a reviewed source or geometry change. The app continues checking current closure freshness at display/export time.

For the next California deployment, bind a new survey manifest with an explicit `region_id` and unique uppercase `target_prefix`, inspect exact footprints and datum/uncertainty, identify geographically appropriate substrate evidence, and supply the region's complete closure inputs. The compiler rejects missing prefixes and malformed or nonpolygon closure geometries. Pass the new manifest using `--config` and that region's release directory using `--output`. Reuse the qualification primitives, failure tests, receipts and publication gates. A broader geographic label, forecast grid or smooth contour is not a replacement for native depth coverage.

## Next evidence to import

1. Continue with adjoining original BAGs H13322, H13324 and H13325 after independent metadata and source-quality review; these should expand Santa Cruz coverage without relabeling the merged NCCOS grid.
2. Import geographically matched seabed samples and georeferenced camera/ROV observations. Record sampling footprint, dates and classification confidence. The inaccessible older USGS sidescan catalogs remain leads until actual files and metadata can be verified.
3. Review the original NOAA backscatter mosaics as a separate variable, with acquisition frequency, processing and ground truth. Brightness alone is not a rock class.
4. Add species-specific depth/substrate evidence and observations with effort and zero catches. Do not turn occurrence points, charter schedules or general species preferences into a calibrated local bite score.
