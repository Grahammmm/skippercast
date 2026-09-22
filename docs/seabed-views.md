# Surveyed bottom views

Every one of the 132 existing reef targets has a measured USGS survey window. Clicking a target loads one small numeric tile and draws an oblique relief image or a north-up depth image. No generative image model invents rocks, crevices, fish, vegetation or substrate textures.

The compiler reads the original 2008 USGS Point Buchon, Morro Bay and Point Estero bathymetry grids: WGS84 UTM zone 10, 2 m cells, signed metre elevations referenced to MLLW. It extracts 129 × 129 cells around the nearest target cell, retains missing-data masks, and quantizes elevation to 0.1 m for compact transfer. That encoding precision is not survey accuracy. A window spans 256 m (about 840 ft), distinct from the qualified fishing footprint.

The browser checks the tile's SHA-256, region and target identity. It renders one image on demand, avoiding the cost of loading all seabed tiles on a phone. The relief view draws a 4 m mesh with **2× vertical scale**; the grid-north-up image retains 2 m drawing cells. The caption identifies native resolution, survey year, source-grid coverage and datum. Missing cells remain blank. Cross-section bearings follow source grid north, not true or magnetic north. The target ring is centered on the nearest native cell; the stored subcell offset is under a cell width.

Relief can distinguish a ridge, slope, depression or uneven patch at supported scales. Native pixel size does not prove boulder detection or physical rock dimensions. Backscatter and geological interpretation also do not establish individual boulders without appropriate resolution and ground truth. This image is historical bathymetry, not a contemporary photograph or a navigation surface. Surrounding window depths may exceed the user's fishing limit; only qualified target geometry carries the depth screen.

The local manifest contains source paths, source IDs, survey years and datums. Paths are never copied into public output. Each public index retains source-file digest, source URL and tile digests, so a different region can supply a different approved native grid through the same process. Candidate/restricted sources are rejected. This adapter requires square metre-based cells at 2 m or finer and MLLW; add a separately validated adapter for other datums/resolutions instead of silently treating them as equivalent.

Areas without supporting native data show an explicit unavailable message. In particular, San Simeon's smoothed 10 m contours and regional geology cannot generate the same detailed bottom view. There is no decorative stand-in that could be mistaken for measured terrain.

## Channel Islands context adapter

`scripts/build_socal_habitat.py` is a separate reviewed adapter for the NOAA NCCOS/NCEI 0304093 merged grids. It preserves native 2 m and 4 m values, source WKT, file digests, blank masks and an **unspecified common hydrographic vertical reference**. It never calls those depths MLLW. The source itself includes some IDW gap interpolation and vertical shifts; source-grid coverage therefore does not mean every displayed cell was a direct sounding. The tile contains the producer, survey-date range and these limitations.

These windows are attached to historical habitat context, not qualified fishing targets. Their bounds can extend outside the context outline and the 200-ft source-depth mask. Source-depth screening is separate from legal depth qualification. Representative views are capped per island to keep the mobile package small, and are loaded individually. Catalina lacks imported native terrain in this release. See the [source and processing record](southern-habitat-sources.md) for reproduction and the actual island coverage report.
