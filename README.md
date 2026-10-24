# SkipperCast public evidence feed

This branch contains automatically collected public facts. Application source and documentation are on [main](https://github.com/Grahammmm/skippercast).

- `latest.json`: versioned evidence snapshot, source dates, failures, normalized charter facts and ocean samples.
- `health.json`: compact collection health. Check both `generated_at` and individual source dates.
- `regions/index.json`: one row per region. A region whose refresh raised an error is listed as `status: failed` with `error_class` and a short `error`; its files keep the last successful generation. The job fails only when the default region or more than half of the regions fail.
- `history/YYYY-MM-DD.json`: the latest snapshot for each UTC collection date, retained for 90 days (so is `regions/<id>/history/`). The branch is one commit, replaced on every run, so it carries no git history; older versions can still persist in GitHub's object store until garbage collection, in clones and forks, and in R2 until its lifecycle backstop. This is not an erasure policy.
- `survey-discovery.json`, `survey-products.json`: NOAA survey leads and original product links. They are a native-review queue, not approved fishing locations.
- `noaa-federal-areas.json`: NOAA's dated West Coast groundfish-area GIS geometry and source receipts. It includes Groundfish Exclusion Areas, Cowcod Conservation Areas and individual Yelloweye Rockfish Conservation Areas. The GIS is approximate; the linked 50 CFR text governs exact boundaries and applicability. A retained snapshot preserves its original retrieval time and is not current clearance.
- `recent-intel.json`, `source-access.json`, `coastal/` and `regions/<id>/`: the recent-discussion candidate feed, per-source access results, statewide coastal browse data and each region's daily files.

Research inventories (NOAA BAG download checks, ENC hazard snapshots, USGS map-block, CSMP and DOI metadata audits) are no longer published here. They run in the separate [research workflow](https://github.com/Grahammmm/skippercast/actions/workflows/research-daily.yml) and are kept as its workflow artifacts.

The [daily workflow](https://github.com/Grahammmm/skippercast/actions/workflows/daily-data.yml) requests a refresh at 4:17 a.m. America/Los_Angeles. GitHub can delay scheduled jobs and disables inactive public-repository schedules after 60 days. No machine needs to stay awake. Workflow failures are visible in Actions and stale data is labeled in the app. A successful job can still have degraded optional sources; inspect health.

NOAA/NASA/IOOS observations and forecasts retain their provider rights and attribution. MUR data were provided by JPL under support by NASA MEaSUREs. Chlorophyll is from NASA GSFC OBPG; radar currents are from NOAA IOOS/HFRNet, accessed through NOAA CoastWatch ERDDAP. Open-Meteo provides access to explicitly named NOAA/ECMWF models under CC BY 4.0 and its noncommercial API terms. Landing-reported catch facts link back to SoCalFishReports; no articles, photos, private logs, or raw report pages are redistributed.

See the [research and methodology](https://github.com/Grahammmm/skippercast/blob/main/docs/bite-evidence.md) and [NOTICE](https://github.com/Grahammmm/skippercast/blob/main/NOTICE.md). The project's personal-use license does not restrict the underlying public-domain or separately licensed data.

See [California seabed coverage and promotion gates](https://github.com/Grahammmm/skippercast/blob/main/docs/california-seabed-coverage.md) for what the source inventory can and cannot establish.

Reports are selected observations, not a fleet census or catch-probability model. Missing reports do not mean zero fish. Port names do not locate fish. Surface currents are not bottom drift. Tide predictions are not Morro Bay entrance-current predictions. Daily feeds are not live departure clearance.
# Production packaging

Site releases deploy from `main` only, through `.github/workflows/deploy-cloudflare.yml` ([Cloudflare](cloudflare.md)), which builds the Worker and fingerprinted client from the tested commit and smoke-tests the result. Verify the actual live script reference and map option after deployment.
