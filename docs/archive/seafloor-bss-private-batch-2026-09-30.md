# Original Big Sur South private batch — September 30, 2026

Three existing catalog products were reconciled rather than duplicated:
BSS Block02, Block03 and Block12. Their original NOAA-hosted archives match the
previous source-review hashes and exact ArcInfo grid directories recorded in
[catalog/csumb-bss-native-sources.json](../../catalog/csumb-bss-native-sources.json).
All retain 2011 acquisition, native 2 m NAD83/UTM10 and NAVD88 (Geoid09 in
original metadata). No chart-datum conversion or interpolation mask was invented.

The producer's [current data policy](https://csumb.edu/undersea/sfml-data-library/)
allows public use/display with requested credit; for-profit use requires express
permission. The standardized publication contract does not yet carry these
noncommercial terms. Rows therefore remain `physical-only`, with publication
rights unqualified. They are not mislabeled government public-domain products.

## Local physical results

| Reach | Selected valid km² | Planning-cell Tier 1 km² | Candidates | Supported terrain ranks |
| --- | ---: | ---: | ---: | ---: |
| south-big-sur-san-simeon-r02 | 39.604673429 | 41.123125 | 427 | 390 |
| south-big-sur-san-simeon-r01 | 0.727169019 | 1.0625 | 19 | 9 |
| big-sur-coast-r05 | 2.634516971 | 3.01 | 19 | 13 |

Deduplicated selected valid footprint totals 42.966359419 km² across disjoint
reference reaches; 465 physical candidates have 412 supported ranks and 53
unknown metric-support results. Lingcod fit is 2 for 406 candidates and 3 for 6;
53 remain unknown. These are terrain/habitat suitability, not observed catches.
Backscatter/substrate interpretation and independent video were not added.

All outputs are private, publication-prohibited, and spatial screening remains
deferred. No new public point, export or live coverage is claimed. The committed
public ledger remains unchanged. Measurements and reproducible receipts are in
`var/seafloor/private-reaches/` and `var/seafloor/bss-private-batch-results.json`.

The next release steps are a source-specific noncommercial publication contract
with attribution retained in map/export products, current whole-polygon spatial
screening, production processing, and live regional map verification. Other
Big Sur and San Simeon blocks remain source-review work, not completed coverage.
