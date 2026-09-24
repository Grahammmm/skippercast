# SkipperCast public evidence feed

This branch contains automatically collected public facts. Application source and documentation are on [main](https://github.com/Grahammmm/skippercast).

- `latest.json`: versioned evidence snapshot, source dates, failures, normalized charter facts and ocean samples.
- `health.json`: compact collection health. Check both `generated_at` and individual source dates.
- `history/YYYY-MM-DD.json`: the latest snapshot for each UTC collection date, retained in the working tree for 90 days. Git history can retain older versions; this is not an erasure policy.
- `survey-discovery.json`, `survey-products.json`, `bag-head-inventory.json`: NOAA survey leads, original product links, and bounded download-health checks. They are a native-review queue, not approved fishing locations.
- `enc-hazards/santa-barbara-island.geojson`: a daily bounded NOAA ENC Direct snapshot of charted obstruction, underwater-rock and wreck features across harbor, approach and coastal scale bands. All 18 layer queries must complete. The retrieval timestamp is not a chart issue time; this is a review aid, not navigational clearance or a complete hazard inventory.
- `usgs-map-blocks.json`, `usgs-map-metadata.json`: original USGS state-waters catalog products, source XML checksums and geographic metadata bounds. Rectangles do not mean every pixel was mapped.
- `usgs-doi-releases.json`, `usgs-doi-metadata.json`: newer DOI-linked USGS data releases and their original XML records, including Monterey and central coast products omitted by legacy catalog pages.
- `noaa-federal-areas.json`: NOAA's dated West Coast groundfish-area GIS geometry and source receipts. It includes Groundfish Exclusion Areas, Cowcod Conservation Areas and individual Yelloweye Rockfish Conservation Areas. The GIS is approximate; the linked 50 CFR text governs exact boundaries and applicability. A retained snapshot preserves its original retrieval time and is not current clearance.

The [daily workflow](https://github.com/Grahammmm/skippercast/actions/workflows/daily-data.yml) requests a refresh at 4:17 a.m. America/Los_Angeles. GitHub can delay scheduled jobs and disables inactive public-repository schedules after 60 days. No machine needs to stay awake. Workflow failures are visible in Actions and stale data is labeled in the app. A successful job can still have degraded optional sources; inspect health.

NOAA/NASA/IOOS observations and forecasts retain their provider rights and attribution. MUR data were provided by JPL under support by NASA MEaSUREs. Chlorophyll is from NASA GSFC OBPG; radar currents are from NOAA IOOS/HFRNet, accessed through NOAA CoastWatch ERDDAP. Open-Meteo provides access to explicitly named NOAA/ECMWF models under CC BY 4.0 and its noncommercial API terms. Landing-reported catch facts link back to SoCalFishReports; no articles, photos, private logs, or raw report pages are redistributed.

See the [research and methodology](https://github.com/Grahammmm/skippercast/blob/main/docs/bite-evidence.md) and [NOTICE](https://github.com/Grahammmm/skippercast/blob/main/NOTICE.md). The project's personal-use license does not restrict the underlying public-domain or separately licensed data.

See [California seabed coverage and promotion gates](https://github.com/Grahammmm/skippercast/blob/main/docs/california-seabed-coverage.md) for what the source inventory can and cannot establish.

Reports are selected observations, not a fleet census or catch-probability model. Missing reports do not mean zero fish. Port names do not locate fish. Surface currents are not bottom drift. Tide predictions are not Morro Bay entrance-current predictions. Daily feeds are not live departure clearance.
# Production packaging

After source changes, run `python scripts/package_site.py --output /tmp/skippercast-site.tar.gz` and save the Sites version using the pushed source commit and that archive. Packaging the unbuilt `dist/` source directory can leave the previous Worker and frontend live even when publication reports success. Verify the actual live script reference and map option after deployment.
