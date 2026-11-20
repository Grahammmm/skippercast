# Surveyed bottom views

Every one of the 132 existing reef targets has a measured USGS survey window. Clicking a target loads one small numeric tile and draws an oblique relief image or a north-up depth image. No generative image model invents rocks, crevices, fish, vegetation or substrate textures.

The compiler reads the original 2008 USGS Point Buchon, Morro Bay and Point Estero bathymetry grids: WGS84 UTM zone 10, 2 m cells, and signed metre elevations on an **unverified source datum**. The [USGS report review](../research/catalog/usgs-morro-report-datum-source.json) distinguishes the report's MLLW depths from the original rasters, which do not declare that datum. The compiler extracts 129 × 129 cells around the nearest target cell, retains missing-data masks, and quantizes elevations to 0.1 m for compact transfer without a datum conversion. That encoding precision is not survey accuracy. A window spans 256 m (about 840 ft); it does not qualify a fishing footprint.

The browser checks the tile's SHA-256, region and target identity. It renders one image on demand, avoiding the cost of loading all seabed tiles on a phone. The relief view draws a 4 m mesh with **2× vertical scale**; the grid-north-up image retains 2 m drawing cells. The caption identifies native resolution, survey year, source-grid coverage and datum. Missing cells remain blank. Cross-section bearings follow source grid north, not true or magnetic north. The target ring is centered on the nearest native cell; the stored subcell offset is under a cell width.

Relief can distinguish a ridge, slope, depression or uneven patch at supported scales. Native pixel size does not prove boulder detection or physical rock dimensions. Backscatter and geological interpretation also do not establish individual boulders without appropriate resolution and ground truth. This image is historical bathymetry, not a contemporary photograph or a navigation surface. Surrounding window depths may exceed the user's fishing limit; only qualified target geometry carries the depth screen.

### Private Morro Bay rebuild

Use the optional GIS environment and the original local GeoTIFFs. The manifest maps the atlas source keys to the reviewed catalog IDs:

```json
{
  "sources": {
    "PointBuchon": {"path": "/local/buchon.tif", "source_id": "usgs-point-buchon", "survey_year": 2008, "vertical_datum": "unverified source datum"},
    "MorroBay": {"path": "/local/morro.tif", "source_id": "usgs-morro-bay", "survey_year": 2008, "vertical_datum": "unverified source datum"},
    "PointEstero": {"path": "/local/estero.tif", "source_id": "usgs-point-estero", "survey_year": 2008, "vertical_datum": "unverified source datum"}
  }
}
```

```bash
python research/scripts/build_bottom_views.py --region morro-bay --manifest /local/survey-manifest.json --held-output /local/new-private-bottom-build
```

Use a new output directory outside the checkout, under a private parent. Before writing any tiles, the compiler rejects a conflicting datum (including `MLLW`), a mismatched source binding, or bytes that do not match the pinned original TIFF SHA-256. The output under `regions/morro-bay/bottom/` inside that directory includes an index and numeric tiles marked `research_only`, with the same unverified datum on both. Do not copy this output into `dist`; the rebuild does not change the atlas, qualify a fishing depth or target, or clear a release hold.

The adapter still requires approved, region-bound sources and square metre-based cells at 2 m or finer. The existing path for separately qualified MLLW inputs is unchanged. The index records source and tile digests and source URLs, not local input paths.

Areas without supporting native data show an explicit unavailable message. In particular, San Simeon's smoothed 10 m contours and regional geology cannot generate the same detailed bottom view. There is no decorative stand-in that could be mistaken for measured terrain.

A published depth-contour file (`dist/regions/<id>/depth-contours.geojson`) lists the grids it traced in `provenance.sources`. Its `provenance.sources_omitted` lists every other bathymetry survey bound to the region, each with its catalog `review_status` copied unchanged. For example, Morro Bay records `noaa-bag` as `approved` (a source family, not any one tile) and not traced. An omitted survey is not drawn and not converted. The Chart notes only bound surveys that are not yet approved, for example "1 bound survey not drawn: noaa-bag (not yet reviewed)", and reports approved ones it did not trace after them.

Held build mode lets a `candidate` survey be traced and reviewed before its rights are cleared. `scripts/build_depth_contours.py --held-output <path>` writes a private file stamped `publication_held: true`, with `held_sources` naming each traced survey that is not approved. The path must lie outside the repository work tree, so a held file is never committed; nothing is written under `catalog/` or `dist/`. `restricted` surveys and surveys whose licence is unresolved stay refused, held or not. The platform build refuses any contour file that carries `publication_held` or a source that is not approved.

A source whose catalog `adapter` is `bag` is traced from one regular NOAA BAG: `--grid noaa-bag=<file.bag> --bag-survey noaa-bag=<SURVEY_ID>`, one survey per source per build. The builder reads the BAG's elevation band through the unchanged seafloor adapter at the file's own native cell, and records the survey id, the survey start date and the vertical datum the BAG's metadata declares, copied as declared (none declared reads `unverified source datum`). Nothing is converted. Variable-resolution and ellipsoid-referenced BAGs are refused, and every grid passes the native-grid preflight before any read. Grids with different declared datums or cell sizes never merge inside a 16 m block; a block complete in neither is a gap. Reads are clipped to the region bounds, so a coast-wide BAG is never read whole, and no survey edge is drawn where the clip cuts a survey that continues.

`--provenance SOURCE_ID=<provenance.tif>` (optional, per GeoTIFF grid) reads the error-correction provenance raster written by the EC tools; it must share the grid's lattice and carry an `EC_VERSION` tag, or the build refuses before any read. Each 16 m block then carries a class: contours are cut into runs with `properties.provenance` (`measured`, `filled`, `verified`; a filled or verified run's id ends in its class), and unresolved blocks become `unresolved-area` polygons with a `reason`, never contours, with survey edges drawn round them as round a gap. A conflict area names its shallowest second-survey reading in `shoal_hint_ft`. The classes, codes and shoal rule are in [docs/seafloor-ec.md](seafloor-ec.md). Without `--provenance` the output is unchanged.

## Channel Islands context adapter

`research/scripts/build_socal_habitat.py` is a separate reviewed adapter for the NOAA NCCOS/NCEI 0304093 merged grids. It preserves native 2 m and 4 m values, source WKT, file digests, blank masks and an **unspecified common hydrographic vertical reference**. It never calls those depths MLLW. The source itself includes some IDW gap interpolation and vertical shifts; source-grid coverage therefore does not mean every displayed cell was a direct sounding. The tile contains the producer, survey-date range and these limitations.

These windows are attached to historical habitat context, not qualified fishing targets. Their bounds can extend outside the context outline and the 200-ft source-depth mask. Source-depth screening is separate from legal depth qualification. Representative views are capped per island to keep the mobile package small, and are loaded individually. Catalina lacks imported native terrain in this release. See the [source and processing record](archive/southern-habitat-sources.md) for reproduction and the actual island coverage report.
