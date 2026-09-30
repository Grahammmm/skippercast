# Original ArcInfo reader verification — September 30, 2026

The original USGS SGF5G and SUR5G downloads contain real GDAL AIG grids, not
rendered relief images. The new adapter ingests their native 5 m floating grids,
retains missing pixels and leaves the undocumented vertical datum unknown.
These checks remove an ingestion blocker; they do not add published habitat.

| Original product | Valid pixels | Nominal positive depth ≤91.44 m pixels | Native spacing |
| --- | ---: | ---: | ---: |
| [SGF5G](https://pubs.usgs.gov/of/2001/0179/exp_arc/battopo/sgf5g.tgz) | 6,801,023 | 1,006,190 | 5 m |
| [SUR5G](https://pubs.usgs.gov/of/2001/0179/exp_arc/battopo/sur5g.tgz) | 9,947,888 | 2,806,415 | 5 m |

Source-pixel area is not deduplicated reach coverage. Native resolution is not
sounding accuracy. These grids still require reviewed rights/lineage and reach
processing before promotion and spatial screening before publication.

## Existing-source regression

Changing ingestion code changes cache keys. Each of the eleven currently usable
originals was normalized again using its reviewed window. Every scientific
raster identity matched: values, masks, grid, CRS, native spacing and depth datum.
The valid and shallow source-pixel counts also matched each reviewed receipt.
Source checksums and manifest identities remain unchanged. No arbitrary COG hash
was accepted and no source review was weakened.

| Source | Valid pixels | Nominal ≤300 ft pixels | Scientific raster identity |
| --- | ---: | ---: | --- |
| `bathymetry-offshoremorrobay-zip-fad659557e` | 28,337,123 | 28,337,123 | `{'version': 'normalized-raster-content-v1', 'sha256': 'ac2b74377292c9553ef8fb452ce462300e4783cc1ed2e9d4961f78f085ae9946'}` |
| `bathymetry-offshorepointbuchon-zip-fcc90bde5c` | 31,624,451 | 27,255,543 | `{'version': 'normalized-raster-content-v1', 'sha256': 'a51460614c8998d774f6359a4158fdc82a8ecce9be376927bbec8baf9a8e3761'}` |
| `bathymetry-offshorepointestero-zip-7e3be5eb12` | 31,244,953 | 26,023,976 | `{'version': 'normalized-raster-content-v1', 'sha256': 'eb33aa358d605e33c34bbab22616f72e99f7b69856d2cbe2d542de0ab01852c2'}` |
| `h11953-mb-2m-mllw-2of4-bag-fd284baf0f` | 6,281,842 | 6,281,842 | `{'version': 'normalized-raster-content-v1', 'sha256': '4630b8a7ed128d0cd9a8512fcc3e2cdce801b924b6e0279099399e8720e97aae'}` |
| `bathymetry-2m-offshoremonterey-zip-172dbd1794` | 51,449,760 | 32,571,329 | `{'version': 'normalized-raster-content-v1', 'sha256': '233b398cd2595fe806f8e884d60147b5432d1522f319547f8054c4cf00279c44'}` |
| `h11952-mb-2m-mllw-2of4-bag-ffa92402c6` | 4,408,374 | 4,408,374 | `{'version': 'normalized-raster-content-v1', 'sha256': '99b2d63a3557a2f3a6edcfd87bcc79486e1e7b8e90f994765f3271ba88fd213e'}` |
| `h11952-mb-4m-mllw-3of4-bag-1961b50d36` | 2,258,602 | 2,258,602 | `{'version': 'normalized-raster-content-v1', 'sha256': 'e3762c05655fc015eff36fb60e50641fb4c4a1d6ac07f77a36cf0c100a0b282c'}` |
| `h11952-mb-8m-mllw-4of4-bag-e1fb31ac2b` | 53,729 | 53,692 | `{'version': 'normalized-raster-content-v1', 'sha256': '0d1888f0d570e50108c9294da9c3d9d36667449d0aa70cef4f88d440e740a59b'}` |
| `h11953-mb-4m-mllw-3of4-bag-f90a1710f1` | 4,666,652 | 4,666,652 | `{'version': 'normalized-raster-content-v1', 'sha256': 'e1c4a32952c4e9eb8c86c08a2d403396c42dffb8ed00ce64d44ead82acf31b4b'}` |
| `h11953-mb-8m-mllw-4of4-bag-e70772d2bb` | 307,433 | 307,433 | `{'version': 'normalized-raster-content-v1', 'sha256': 'f550520d45180804cec73bc35c7c53e37db8d38b2cf336ca25d0ab8ac81aa495'}` |
| `h11953-mb-1m-mllw-1of4-bag-8b1bfa456f` | 6,417,802 | 6,417,802 | `{'version': 'normalized-raster-content-v1', 'sha256': '16a29f682e7cdf7c8dd97f8f07bfcf4bb473af9ce1399cf4f3788476001fcf7e'}` |

Validation: 110 seafloor tests / 2,994 subtests, eight research-boundary tests and
eleven client seafloor tests passed locally. Native AIG fixture tests cover exact
selection, decoder/normalizer parity, extraction member and byte limits,
traversal/links/duplicates, corruption and offline reuse. Metric-unit aliases
are accepted only with unit conversion factor 1; state-plane feet still fail.
Repository/web checks, generated platform rebuild, typecheck and client build
passed. Linux full-suite and browser CI remain the final merge gate.

Private reproducible checks are saved under `var/seafloor/usgs-legacy/` and
`var/seafloor/arcgrid-existing-source-parity.json`. Originals stay private and are
not committed. Next: qualify the two original products and process up to three
new Carmel/Point Sur/northern Big Sur reaches, retaining the native depth masks.
