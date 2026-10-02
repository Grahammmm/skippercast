# Kasler, Soberanes and Yankee native survey batch

Three original CSUMB 2 m grids add useful measured support in the Monterey–Point
Sur region. They are 2004 acquisitions distributed by NOAA NCEI, not new sonar
surveys. Source archives, native raster identities, valid-data masks and reviewed
windows were verified before ordinary processing of three reaches.

| Source | Original report | Native shallow footprint | Sequential shallow-footprint difference | Missing prior valid depth: native-cell area proxy |
| --- | --- | ---: | ---: | ---: |
| Kasler Point | [NOAA report](https://www.ngdc.noaa.gov/ships/ventresca/KaslerPoint_mb.html) | 16.388974 km² | 10.946497 km² | 10.940284 km² |
| Soberanes Point | [NOAA report](https://www.ngdc.noaa.gov/ships/ventresca/SoberanesPoint_mb.html) | 11.761112 km² | 6.696060 km² | 6.670996 km² |
| Yankee Point | [NOAA report](https://www.ngdc.noaa.gov/ships/ventresca/YankeePoint_mb.html) | 12.907373 km² | 7.939912 km² | 7.886352 km² |

These are distinct measurements. The footprint difference removes earlier
qualified shallow footprints in source order, including Hurricane Point and the
preceding sources in this batch. The native-cell proxy also treats previously
valid *deeper* cells as existing measurements. Soberanes has 4,854 and Yankee
12,028 such cells; they are not new sonar coverage. Neither proxy is the
pipeline's selected-footprint metric or additional independent acquisition
corroboration. Multiple products derived from a survey remain one family.

## Scientific limits and permitted use

Native bathymetry metadata says predicted-tide MLLW; companion grayscale
metadata also claims final NAVD88 products. Each datum remains **unknown**.
Depths are nominal, without a chart-datum conversion or chart-depth guarantee.
The original producer used shoal-biased decimation and AverageGridder
interpolation. A 2 m cell size does not imply independently measured soundings
in every cell or reliable detection of a 2 m boulder. Interpolation and
per-cell uncertainty masks remain unknown.

Kasler quotes approximate horizontal ±2 m and vertical ±0.20 m accuracy without
an independently validated confidence statement. Soberanes and Yankee supply
instrument specifications rather than total map uncertainty; these are not
promoted to seafloor accuracy. Soberanes' one-day acquisition-date discrepancy
and the 2006 metadata/update dates remain recorded separately from acquisition.

Use is credited noncommercial use under the [CSUMB SFML policy](https://csumb.edu/undersea/sfml-data-library/).
The existing for-profit gate and not-for-navigation notice remain. Producer
permission for for-profit use has not been obtained. Raw archives and held
habitat geometries remain private.

## Local pipeline results

The baseline is the prior usable-source computation, including the Hurricane,
Cooper and Point Sur batch for r04. The run includes the subsequently merged
Conception classification rules; they do not provide substrate evidence here.

| Reach | Selected measured support, before → after | Physical candidates | Screened candidates | Screened habitat, before → after |
| --- | ---: | ---: | ---: | ---: |
| Monterey r02 | 6.703702 → 9.384424 km² | 126 → 154 | 14 → 12 | 0.153591 → 0.148995 km² |
| Monterey r03 | 11.544077 → 26.958271 km² | 128 → 332 | 91 → 265 | 2.069371 → 3.615563 km² |
| Monterey r04 | 95.371711 → 101.767106 km² | 826 → 902 | 462 → 530 | 12.426375 → 14.774068 km² |

Net change: **24.490311 km² selected measured support, 308 physical candidates,
240 screened candidates and 3.889289 km² screened habitat**. The final three
reaches contain 1,388 physical candidates: 807 pass and 581 are held. All 807
passing polygons were checked for whole-polygon intersections and boundary
touches with current CDFW, NOAA and security exclusions; there are zero.
The checked snapshot is dated October 2, 04:03 UTC.

The small reduction in r02's passing count follows source selection and
reach-wide terrain thresholds, not relaxed screening. New Yankee support in
that reach does not automatically create an eligible fishing area. Existing
1–3 species-fit rankings and all thresholds remain unchanged. Habitat suitability
is not an assertion of fish presence or a season/gear permission decision.

## Reproduce and publish

Use the canonical mapping skill. Restore checked original-source caches and the
reference grid, verify the three registered source review receipts, then run the
ordinary pipeline for `monterey-point-sur-r02`, `monterey-point-sur-r03` and
`monterey-point-sur-r04`. Preserve prior physical output identities and compare
selected coverage, physical candidates, screened candidates and held output
separately. No forced rebuild or cache-identity override is required.

Validation: 41 habitat, tiled-processing, manifest, source-rights and receipt
checks passed, with 3,504 subtests. Saved output hashes, nominal 25–300 ft habitat
limits, 1–3 fit values and independent whole-polygon exclusion checks passed.
These are local results. Production must finish its ordinary serialized workflow
and pass ready-manifest/archive verification before reporting this batch live.
