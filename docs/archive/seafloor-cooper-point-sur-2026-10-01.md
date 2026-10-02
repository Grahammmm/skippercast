# Hurricane Point, Cooper Point and Point Sur native coverage — October 1, 2026

Qualify three original CSUMB sonar-derived 2 m products and process three existing
reaches using the unchanged native coverage, terrain and whole-polygon screening
pipeline. Local selected measured support increases by **62.909593 km²**. The
two Big Sur reaches increase from one to 126 passing habitat areas. Results
remain subject to production verification; neither native grid spacing nor
habitat suitability proves accuracy at a small rock pile or fish presence.

## Original sources

| Product | Original publisher/distribution | Native evidence and restrictions |
| --- | --- | --- |
| Cooper Point | [Acquisition report](https://www.ngdc.noaa.gov/ships/ventresca/CooperPoint_mb.html); [original archive](https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/CooperPoint/multibeam/data/version2/products/CooperPoint_additional_products.tar.gz) | April 2005 multibeam, native 2 m bathymetry, WGS84/UTM10N, nominal NAVD88. Original report and byte-range response verified against cached bytes. |
| Point Sur | [Acquisition report](https://www.ngdc.noaa.gov/ships/ventresca/PointSur_mb.html); [original archive](https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/PointSur/multibeam/data/version2/products/PointSur_additional_products.tar.gz) | Original 2 m bathymetry. The bathymetry/hill/slope process describes predicted-tide MLLW while another same-archive process claims final NAVD88. Retain **unknown vertical datum**; do not assert chart-depth qualification. |
| Hurricane Point | [Acquisition report](https://www.ngdc.noaa.gov/ships/ventresca/HurricanePoint_mb.html); [original archive](https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/HurricanePoint/multibeam/data/version2/products/HurricanePt_additional_products.tar.gz) | 2004–2005 acquisition, native 2 m bathymetry, WGS84/UTM10N. Native and companion processing consistently describe predicted-tide MLLW; this is the producer's datum assertion, not independent chart-depth validation. |

Each reviewed product uses the existing nested ArcInfo GRID adapter with its
exact bathymetry member. Original hashes, native masks and normalized raster
identity are pinned in the catalog. No hillshade is used as depth. Source-only
receipts preserve acquisition dates, bounds, exact archive members, processing,
access checks and limitations:

- [Cooper Point receipt](../../research/receipts/seafloor-cooperpoint-native-review.json)
- [Point Sur receipt](../../research/receipts/seafloor-point-sur-native-review.json)
- [Hurricane Point receipt](../../research/receipts/seafloor-hurricane-point-native-review.json)

These are producer-gridded sonar products, with interpolation documented in
the source processing. Per-cell measured-versus-filled masks are unavailable;
`interpolation_mask=unknown` is retained, as are unknown quantitative accuracy
and uncertainty. Do not mistake 2 m pixel spacing for 2 m feature accuracy or
soundings at every grid cell. No new independent-acquisition credit is assigned.

The [current CSUMB producer policy](https://csumb.edu/undersea/sfml-data-library/)
permits credited noncommercial public use and requires express permission for
for-profit use. Preserve source credit, navigation restrictions and the paid
deployment gate. Original NOAA distribution does not make these products US
government public-domain data.

## Geographic evidence and source priority

Cooper Point has 23.131135 km² of native nominal shallow footprint, of which
22.947405 km² lies outside the previously reviewed shallow support. Point Sur
has 30.999347 km² of native shallow footprint; after comparison with prior
reviewed sources **and Cooper Point**, its incremental shallow footprint is
27.907140 km². Native-cell-center diagnostics separately find 22.930336 and
27.886180 km² cell-area proxies without prior positive valid depth. These
diagnostics are not exact polygon areas and are never added to the footprint
measurements. Hurricane Point adds a 15.214680 km² native shallow footprint,
13.606304 km² outside the prior shallow support including Cooper Point and
Point Sur. Its separate native-center missing-depth proxy is 13.597916 km².

The shared processor selects a qualifying source per reference cell. Its
selected-support change is therefore 62.909593 km², distinct from the source
union gap or planning-cell area. Existing equal-resolution/newer-year priority
may select Point Sur over overlapping Cooper Point. Point Sur's unknown datum
does not become NAVD88 through selection; all depths remain nominal to their
recorded source basis, and boundary depths need sounder verification.

## Three-reach local result

| Reach | Selected valid km² before → after | Physical before → after | Screened before → after | Screened habitat km² before → after |
| --- | ---: | ---: | ---: | ---: |
| Monterey–Point Sur r04 | 73.689365 → 95.371711 | 790 → 826 | 541 → 462 | 3.906198 → 12.426375 |
| Big Sur r01 | 0.335541 → 36.752042 | 6 → 320 | 1 → 72 | 0.001624 → 0.367720 |
| Big Sur r02 | 0 → 4.810747 | 0 → 60 | 0 → 54 | 0 → 0.333041 |

Total changes: **+62.909593 km²** selected measured support, **+65.310000 km²**
qualified planning-cell area, **+410** physical candidates, **+46** screened
candidates and **+9.219315 km²** screened habitat. The 618 held candidates remain
private. All 588 passing polygons have zero intersection or boundary touch with
the CDFW, NOAA and security exclusion layers.

The existing reach-wide percentile thresholds are recalculated from the expanded
sample population. This can change components over older sources even where
their original pixels are unchanged. Monterey r04 contains 71 passing Hurricane
Point areas and 391 from the older USGS SGF5G/SUR5G grids; no passing 2 m Point
Sur feature is claimed there. Many new candidates overlap MPAs and remain
private. Big Sur r01 contains 61 passing Cooper Point
areas and 11 Point Sur areas; r02 has 54 Cooper Point areas. No candidate counts
were preserved artificially to avoid reporting a decrease elsewhere.

## Reproduction and release

Review the native drafts, recover their four hash-checked original/normalized
files per source, copy the source-only receipts and register their existing
inventory aliases. Use `promote-survey`, retain the detailed source limitations,
then normal `run --reach` for Monterey r04 and Big Sur r01/r02. Actual new source
identities trigger processing without `--force`. Existing whole-polygon scopes
cover all three reaches; no security or MPA rule was weakened.

Private before/after, native handoffs and complete polygon-overlap checks are
under `var/seafloor/overnight-cooper-point-sur/`. Adapter/inventory/source-rights
and receipt-manifest checks pass: 36 tests and 3,476 subtests. Current-head complete CI and independent
review precede protected merge. The established workflow owns the ledger and
public regional bundles; ready manifests and PMTiles range responses must be
checked before reporting this local result live.
