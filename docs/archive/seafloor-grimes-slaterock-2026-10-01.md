# Grimes Point and Slate Rock habitat — October 1, 2026

Add the original Grimes Point 2 m bathymetry and release the existing Slate Rock
2 m source under its reviewed producer terms. Two Big Sur reaches gain 416 net
locally screened habitat areas. This combines genuinely new native survey
coverage at Grimes Point with previously mapped private coverage at Slate Rock;
the two gains must not be counted as the same kind of progress.

## Original source evidence

| Source | Native evidence | Coverage and limits |
| --- | --- | --- |
| [Grimes Point](https://www.ngdc.noaa.gov/ships/ventresca/GrimesPoint_mb.html) | [Original archive](https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/GrimesPoint/multibeam/data/version2/products/GrimesPoint_additional_products.tar.gz), 540,383,878 bytes; native 2 m ArcInfo bathymetry; WGS84/UTM10N; NAVD88. Acquisition includes April–May 2005 and June 2006. | 14.220247 km² native nominal shallow footprint. Exact footprint difference against every intersecting reviewed/private-qualified source, including Slate Rock and Cooper Point, is 13.205623 km². A separate native-center diagnostic finds 13.197308 km² of cells without prior valid depth; this is a cell-area proxy, not another exact polygon measurement. |
| [Slate Rock](https://www.ngdc.noaa.gov/ships/ventresca/SlateRock_mb.html) | [Original archive](https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/SlateRock/multibeam/data/version2/products/SlateRock_additional_products.tar.gz), 533,397,873 bytes; existing native 2 m ArcInfo bathymetry, WGS84/UTM10N, NAVD88; September 2006 acquisition. | Existing 14.976504 km² shallow footprint. This rights-only review adds **zero new measured coverage** relative to the previously qualified private source. Original and normalized hashes, source ordering, year, native bounds and all scientific fields remain unchanged. |

The exact native bathymetry directories are selected through the existing nested
ArcInfo adapter. Neither grayscale imagery nor the co-packaged 25 m Slate Rock
grid is treated as 2 m measured terrain. Native masks, source checksums and
normalized raster identities are retained.

Both are sonar-derived producer-interpolated grids. Per-cell measured/filled
masks and calibrated uncertainty are unknown. Producer estimates of roughly
±2 m horizontal and ±0.20 m vertical accuracy have no verified confidence level
or independent validation; pixel spacing and those estimates are not a guarantee
of small-rock detection. NAVD88 is not MLLW, and no chart-depth conversion is
claimed. Depth limits remain nominal to the source datum.

Grimes Point's formal metadata date range omits the additional June 2006 survey
described in its abstract; the latest documented acquisition year is used and
the discrepancy retained. Product release/update dates are not acquisition dates.
Companion bathymetry, backscatter, slope and habitat products from each survey
family do not create independent confirmation.

Source-only review receipts:

- [Grimes Point](../../research/receipts/seafloor-grimes-point-native-review.json)
- [Slate Rock rights and scientific parity](../../research/receipts/seafloor-slaterock-rights-review.json)

The [CSUMB original-producer policy](https://csumb.edu/undersea/sfml-data-library/)
permits credited noncommercial public use. Producer credit, the prohibition on
navigation use and the express-permission requirement for for-profit deployment
remain enforced. NOAA distribution does not confer federal public-domain status.

## Two-reach local processing

The baseline includes the preceding Hurricane/Cooper/Point Sur batch. Shared
habitat rules and complete-polygon screening remain unchanged.

| Reach | Selected valid km² before → after | Physical candidates before → after | Screened candidates before → after | Screened habitat km² before → after |
| --- | ---: | ---: | ---: | ---: |
| Big Sur r02 | 4.810747 → 18.588505 | 60 → 369 | 54 → 339 | 0.333041 → 1.880369 |
| Big Sur r03 | 0 → 14.111440 | 0 → 151 | 0 → 131 | 0 → 0.887380 |

Net local public-eligible support changes are **+27.889198 km²** selected native
coverage, **+29.511875 km²** qualified planning-cell area, **+460** physical
candidates, **+416** screened candidates and **+2.434708 km²** screened habitat.
These totals include the Slate Rock release and must not be described as entirely
new measurements. Grimes Point's genuinely new shallow footprint is reported
separately above.

Of 470 passing areas, r02 has 307 Grimes Point, 31 Cooper Point and one Slate
Rock area; r03 has 131 Slate Rock areas. All passing polygons have zero
intersection or boundary touch with CDFW, NOAA and security exclusions.
Fifty candidates remain private because of incomplete metric/feature support
or spatial exclusions. The roughly 397 m² incremental Grimes Point footprint in
r03 is a boundary sliver, not proof of a newly completed coastal reach.

The expanded source population recalculates the existing reach-wide terrain
thresholds, so older Cooper Point components can change. Rankings describe
habitat suitability, not confirmed fish presence. No threshold was relaxed
to increase area or preserve a prior count.

## Reproduction and release

Restore only checked original/cache recovery objects. Promote the new Grimes
Point draft, but replace the existing Slate Rock row **in place**, changing only
status, license, rights review and notes. Register supplemental receipts and
regenerate the research receipt manifest.

Run the two affected reaches through the established bounded pipeline without
`--force`. New source sets require normal processing; source-level rights parity
alone does not justify reusing a whole private reach that also includes other
unreleased surveys. Keep the saved pre-change receipts.

Private results, full-polygon checks, recovery identities and before/after
measurements are retained in `var/seafloor/overnight-grimes-slaterock/`.
Validation: 36 adapter, inventory, rights and receipt-manifest tests plus 3,486
subtests passed; platform generation and repository/web checks passed.
Independent review and current-head CI precede protected merge. The existing
workflow owns the generated ledger and public publication. Local eligibility
does not imply that a ready production archive has been verified.
