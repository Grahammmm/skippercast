> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/PRODUCT-DESIGN-RESEARCH.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Coastal operating view: product research and reviewed map sources

Research and live source probes completed October 1–2, 2026. This document supports the SLO rebuild. The county shell, filters, charts, source contracts and time semantics should be reusable; SLO source bindings and species conclusions are regional.

## What successful applications make easy

These are concrete product capabilities documented by their publishers, followed by our design choices. They are not a license to copy artwork, screenshots, proprietary forecasts or branding. The available computer-use inventory did not expose a controllable browser surface; product documentation and source probes were used. The NAIP and GOES sample images were actually downloaded and visually inspected.

| Reference | Documented strength | Apply to Fish |
| --- | --- | --- |
| [Windy](https://www.windy.com/articles/41954) | Map-based weather layers, point forecasts, model comparison, and a separate satellite-history slider. Data explanations are accessible on desktop and mobile. | Keep geography visible while changing a field. Give every selected field a value scale, valid time, source and explanation. Separate observation playback from forecast time. |
| [Windfinder](https://www.windfinder.com/help/weather-maps/forecast-overlays) | Forecast overlays use explicit value colors; wind direction can use animated particles or a static arrow grid. | Offer a static/reduced-motion view. Use true directional vectors and a consistent legend. Three forecast points can support three labeled arrows, not an apparently resolved regional wind grid. |
| [Surfline](https://support.surfline.com/hc/en-us/articles/13749782983579-Understanding-the-Spot-Forecast-Page-on-the-Surfline-Website) and [swell spectra](https://www.surfline.com/lp/whatsnew/features/swell-spectra) | A spot page connects forecast, expert regional analysis and a guide to local wind/tide/swell behavior. Swell spectra expose energy distribution beyond a single height/period. | Put the local decision first, with a drill-down into measured conditions and method-specific exposure. Keep primary swell, secondary swell and chop distinct. Never label offshore significant height as breaking surf at a beach. |
| [Windguru colors](https://www.windguru.cz/ajax/ajax_colors.php) and [preferences](https://www.windguru.cz/forms/preferences.php) | Wind is visually strongest; other quantities use deliberately quieter color treatment. Forecasts can be scanned by color before reading numbers. | Use a compact aligned hour strip, emphasizing wind/seas and keeping clouds, temperatures and tides legible. Avoid assigning every metric a competing rainbow. Keep units and null values explicit. |
| [Fishbrain depth maps](https://fishbrain.com/features/depth-maps) and [desktop maps](https://fishbrain.com/blog/fishbrain/using-fishbrain-maps-on-desktop) | Structure/depth context, map exploration, species-oriented planning and saved local knowledge. Full pages returned 403 during verification; the publisher's indexed feature descriptions remain discovery evidence, not a verified private app walkthrough. | Make the target species determine which habitat evidence is relevant. A species filter must also update the legend, explanatory copy, supported methods and unavailable-state behavior. Do not transplant an undocumented catch probability. |
| [Kongsberg OceanView](https://www.kongsberg.com/globalassets/kongsberg/1.-what-we-do/2.-ocean-space/3.-ocean-science/blue-insight/geomatics/110-0072975_bi_geomatics_datasheet-revd.pdf) | Marine data layers connect surveys, assets and metadata; filters affect all views of a dataset and temporal playback preserves history. This is the OceanView identified by official documentation, not a verified consumer fishing app of that name. | Build one shared selection state for county, area, method, species, day and hour. Selecting a map feature should reveal its provenance and relevant chart rather than open a disconnected card. |
| [Palantir Map widget](https://www.palantir.com/docs/foundry/workshop/widgets-map) and [timeline](https://www.palantir.com/docs/foundry/map/timeline) | Linked geospatial objects, configurable layers and time filtering. | Keep map selection, timeline and details synchronized. Source outages should change what is drawn as well as the source-status panel. |
| [Anduril Lattice entities](https://developer.anduril.com/guides/entities/overview) | Interoperable entities support a common operating picture across sensors. | Normalize stations, survey footprints and time-bound fields into clear contracts. Show disagreements, age and missing coverage. Apply the linked-data principle without military imagery or unsupported operational certainty. |

### First glance and progressive detail

The first mobile view should answer: **what the coast looks like today; the primary limiting condition; where the available evidence applies; and the time window worth investigating.** Use a restrained dark ocean canvas, colorful field data, a compact briefing, an accessible method/species selector and one shared timeline. Geographic and temporal selection belong in persistent controls; secondary sources belong in an expandable sheet.

1. Briefing: concrete wind/seas/tide information, temperature provenance, active alerts and important unknowns.
2. Map: one dominant field at a time, physical habitat context when supported, obvious source footprint/missing areas, labels for actual sample sites.
3. Hour strip: aligned wind, swell, tides, daylight and clouds, showing the current selection. A day summary must not silently stand in for a selected hour.
4. Details: local exposure, exact source and time, native spacing, station distance, observation versus forecast, and species/method limits.
5. Learning: historical observations and archived forecasts can eventually show local forecast error. Catch probability requires representative effort and zero-catch data; a beautiful heatmap does not establish that evidence.

Animation must describe real data: current arrows follow real toward bearings; wave glyphs reflect actual sampled height/period; tide motion follows real predictions. Smooth particle speed is a visual convention unless explicitly calibrated. Respect reduced-motion settings, pause offscreen work and avoid claiming transport trajectories from a few stationary samples.

## Sources that work now

### NOAA CUSP shoreline: sharper geographic context

- Publisher: [NOAA Shoreline Data Explorer](https://nsde.ngs.noaa.gov/) and [CUSP explanation](https://nsde.ngs.noaa.gov/more.html).
- Actual tile template: `https://nsde.ngs.noaa.gov/cusp/tiles/{z}/{x}/{y}.pbf`; source layer `tiles`, publisher max zoom 15. A SLO tile at `12/672/1617` returned real gzip-compressed MVT, 3,275 bytes. Publisher configuration was inspected, not guessed.
- Browser transport: the sampled PBF response had no CORS header, while NAIP/GOES did. Use the same-origin county extract; do not assume direct browser MVT access works.
- Delivered: `public/data/slo-shoreline.geojson`, 3,771 clipped line features from 26 populated tiles, 2,652,654 bytes. Bounds `[-121.34,34.92,-120.51,35.82]`. All contributing local records identify `DAT_SET_CR: NOAA`; source dates are February/March 1994 and May/August/November 2010. `HOR_ACC`, original attribution fields and source dates are retained. Imported z12 vector display quantization is approximately 8 m, independently of original source accuracy.
- The bounded request attempted 140 tiles; 114 returned 403. They remain recorded as unavailable, not silently certified empty. This is a contextual shoreline extract, not a complete navigation product, legal beach access, land polygon, current tide shoreline, seabed or 2 m measurement.
- Refresh: monthly catalog/footprint review, retaining tile hashes and source dates. Use an original reviewed download if full native precision or a complete land polygon is needed. Do not close unrelated line endpoints into invented coastal geometry.
- Rights: NOAA government information is generally public domain; original local creators and source citations are preserved. CUSP can include outside contributors in other regions, so a new county requires the same creator/rights review. [NOAA information policy](https://oceanservice.noaa.gov/about/faq.html).

### USGS NAIP-only aerial imagery: 0.6 m local shore context

- Fixed service: [USGSNAIPImagery ImageServer](https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer). Live metadata describes a predominantly 0.6 m natural-color aerial mosaic and explicitly identifies public-domain NAIP downloads. Attribution: **USGS / USDA · NAIP aerial imagery (dated mosaic)**.
- `exportImage` with `f=image`, Web Mercator output and `NaturalColor` rendering returned a real 512×512 PNG, 391,138 bytes, CORS `*`. The viewed Morro Bay sample clearly resolves beach/harbor form and buildings; it also has imagery gaps offshore.
- A bounded local catalog query returned 50 USDA records, 0.6 m, May 13–29, 2022, and `exceededTransferLimit:true`. Those are observed records, **not a complete county acquisition-date inventory**. The service publication date January 2025 is not the imagery acquisition date.
- `naipSource()` uses dynamic export tiles with `{bbox-epsg-3857}`, transparent PNG output and no account/key. Its max display zoom 19 does not add source detail. Fetch imagery only when selected; cap the active view/tile budget. Do not bulk harvest the public service as an offline tile store.
- Avoid substituting `USGSImageryOnly`/`USGSNAIPPlus` without review. The probed mixed service documents third-party imagery and license restrictions outside CONUS. The NAIP-only service gives the cleaner first binding. [USGS copyrights/credits](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits).
- This is aerial contextual imagery, not a live weather satellite, current kelp map, underwater photograph or bathymetry. A future county can query exact mosaic footprints/acquisition dates before labeling them.

### NOAA GOES longwave satellite imagery: real offshore weather patterns

- Live service: [nowCOAST](https://nowcoast.noaa.gov/); WMS capabilities `https://nowcoast.noaa.gov/geoserver/observations/satellite/ows?service=WMS&request=GetCapabilities&version=1.3.0`.
- Verified layer: `goes_longwave_imagery` (GOES East & West Satellite Longwave Imagery). The actual capabilities list five-minute observation times. Probe default/latest was **2026-10-02 02:53 UTC**. [NOAA service-change description](https://www.lstsrv.ncep.noaa.gov/pipermail/ncep.list.nos-nowcoast-status/attachments/20240329/eb1af6ef/attachment-0001.pdf) identifies Band 14 longwave infrared and five-minute updates.
- Pinned observation GetMap over `[-123,34,-120,37]` returned a real 512×512 PNG, 52,660 bytes, CORS `*`, and the image was viewed. It shows regional brightness-temperature/cloud structure, not a synthetic cloud mask.
- `parseSatelliteCapabilities()` reads explicit published timestamps and selects the latest not more than five minutes ahead of the actual clock. `cloudSource()` pins that timestamp in the WMS tile URL, never `latest`; imagery expires after 90 minutes. Recent metadata retains up to 24 available timestamps for optional historical playback.
- Attribution: **NOAA / NESDIS · GOES East & West longwave infrared**. Longwave brightness temperature is not cloud-cover percentage, beach fog clearance, precipitation, underwater visibility or a forecast.
- Display an **Observation · actual sample time** label. A tomorrow selection must hide this layer or prominently preserve its current-observation status. NWS `skyCover` is the separate forecast cloud percentage chart; it cannot manufacture a spatial forecast cloud field from three area points.
- NASA GIBS has documented public GOES products, but the capabilities probe closed the connection in this environment. No GIBS layer was enabled or claimed operational.

### NOAA WCOFS and HFR current fields through the existing SkipperCast collector

The read-only SkipperCast repository already implements bounded regional surface grids in `src/skippercast/pipeline/ocean.py` and documents them in `docs/regional-intelligence.md`. The public conditions feed was successfully downloaded from `https://raw.githubusercontent.com/Grahammmm/skippercast/conditions/regions/morro-bay/intelligence.json` (4,240,436 bytes; generated October 2, 01:37 UTC). An attempted `/feeds/regions/...` Worker path returned 403 and was not used.

| Field | Verified populated data | Display contract |
| --- | --- | --- |
| [NOAA WCOFS](https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html) | October 1 03 UTC cycle; 24 native three-hour forecast frames with 562 returned wet cells each. Actual populated horizon October 1 06 UTC to October 4 03 UTC. Approximately 4 km regular grid, NAD83, surface 0 m. | Forecast arrows at returned wet cells. Native valid times retained. No reef-scale detail or bottom/bar-current interpretation. Actual clock controls 36-hour issue-age and six-hour retrieval-age gates, separately from selected future time. |
| [NOAA/IOOS HFR 1 km](https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_1km.html) | Six hourly observed frames; latest populated sample October 1 22 UTC; patchy local cells. The upstream county subset uses stride 4 on the native 1 km grid: the returned display samples are about 4 km apart. The importer retains HDOP≤2 and at least two radars. | Observations only, maximum six-hour age. Missing geometry remains blank; no future projection or smooth streamlines across unobserved coastline. |
| [NOAA/IOOS HFR 6 km](https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_6km.html) | Public response had six observed frames; latest populated sample October 1 21 UTC. It crossed the six-hour freshness gate during the import and was therefore omitted from the current normalized snapshot. | This is a real stale-source distinction, not an invented outage or a permanently missing source. It can return when a later populated measurement passes the same gate. |

WCOFS assimilates HF radar and satellite information; agreement between them is not independent validation. Both represent near-surface movement, not boat windage, bottom drift or safe harbor setup. No interpolation across land or missing wet cells is implemented. Upstream retains rounded speed/bearing; the adapter reconstructs east/north display components from those values and does not pretend to retain the original NetCDF precision.

The new adapter ignores all other model products in the shared feed, including Open-Meteo commercial-access concerns. It selects only reviewed NOAA WCOFS/HFR bindings, validates source status, field order/units contract, timestamps, regional coordinates, native layer, bounded frame/cell counts and radar quality.

### Native bottom visualization: keep the actual export distinction

The currently reviewed SkipperCast PMTiles provides **survey-derived physical habitat outlines and coverage cells**, not a continuous bathymetry raster or contour map. See [SKIPPERCAST-BRIDGE.md](SKIPPERCAST-BRIDGE.md). Color habitat by its actual species planning fit and terrain evidence; never render coverage-cell values as invented depth contours.

Original paired USGS [Morro Bay](https://doi.org/10.5066/P9HEZNRO), [Point Estero](https://doi.org/10.5066/P9ZSTUK1), and [Point Buchon](https://doi.org/10.5066/P9KBGELE) releases are the relevant native bathymetry/character source family. Point Buchon's [official release](https://www.usgs.gov/data/bathymetry-backscatter-intensity-and-benthic-habitat-offshore-point-buchon-california-ver-11) is marked CC0; its [bathymetry metadata](https://cmgds.marine.usgs.gov/catalog/pcmsc/DataReleases/CMGDS_DR_tool/DR_P9KBGELE/Bathymetry_OffshorePointBuchon_metadata.html) documents a 2 m grid. Reuse requires the exact approved source's masks, acquisition date, datum and resolution profile, including deeper resampling. Hosting on NOAA or USGS does not override original producer restrictions on excluded CSUMB material.

No usable publisher native-raster XYZ tile service was verified during this research. The next correct display pipeline is a reviewed native-grid export: preserve nodata/wet footprint; render hillshade and nominal depth into bounded, immutable raster tiles or PMTiles; retain survey IDs/datum; host on R2; keep it visually separate from species fit. A screenshot, regional ETOPO grid or aesthetic contour texture cannot substitute for this export. Native visual detail can be useful with an unresolved navigation datum as long as the limitation stays explicit and it is not presented as navigation clearance.

## Implementation and refresh contract

Delivered modules:

- `src/ocean-types.ts`: `OceanData`, `CurrentField`, `CurrentFrame`, `CurrentCell`, `CloudImage` and independent source health.
- `src/providers/ocean.ts`: `collectOcean(county,actualNow,fetcher?)`, `normalizeSkipperOcean()` and `parseSatelliteCapabilities()`. Fixed source URLs; bounded body reads; timeout; rejected redirects; no accounts/keys. Unsupported counties return no fields until bindings are reviewed.
- `src/map-sources.ts`: fixed NAIP source, same-origin shoreline source, pinned-time cloud source, `selectCurrentFrame()` and native current-point features.
- `public/data/slo-ocean.json`: compact reviewed NOAA-only current/cloud snapshot. `public/data/slo-shoreline.geojson`: static contextual coastline with original attributes and receipt metadata.
- `tests/ocean.test.ts`: transport failure, stale cycle, changed schema/units, surface-layer gate, radar geometry quality, future/actual-clock distinction, real-time cloud contract and source URL checks.

The parent integration should call `collectOcean()` from the existing county refresh/Cron, store the latest snapshot separately or in the report contract, and serve it same-origin. A static build snapshot alone cannot keep a 90-minute satellite observation current. Recheck source ages while the layer is visible. Preserve last-good bytes for diagnostic history, but do not draw expired fields as current. A failed fresh collection must produce an error/blank field instead of refreshing the timestamp of old bytes.

Currents can be lazily fetched when their layer is selected to keep first paint lightweight. At this import, `slo-ocean.json` is about 1.34 MB and shoreline 2.65 MB uncompressed; use HTTP compression, avoid repeated decoding, and keep map updates bounded to the selected native frame. In a future optimization, split current frames into same-origin hashed shards so a mobile user downloads only the selected frame.

### CSP and attribution

| Use | Browser origin | Required policy |
| --- | --- | --- |
| NAIP raster export | `https://imagery.nationalmap.gov` | `connect-src` and `img-src`; persistent source attribution |
| GOES pinned WMS raster | `https://nowcoast.noaa.gov` | `connect-src` and `img-src`; visible observation timestamp and attribution |
| CUSP extract | Same-origin `/data/slo-shoreline.geojson` | Existing `'self'`; NOAA attribution; source dates/accuracy available in details |
| Current snapshot | Same-origin report/`/data/slo-ocean.json` | Existing `'self'`; NOAA WCOFS or IOOS/HFR label, source time and coarse resolution |
| Collector only | `raw.githubusercontent.com`, `nowcoast.noaa.gov` | Server-side fixed endpoints; do not broaden browser CSP for these downloads |

NAIP and NOAA sources do not require a paid basemap account for these public services. A later Mapbox/MapTiler/Esri satellite offering requires an explicitly provisioned key, current commercial service terms, quota/cost review, domain restrictions and the prescribed contributor attribution. Do not borrow demo keys or treat an unauthenticated third-party tile URL as commercial permission. NOAA/USGS logos are unnecessary; attribution does not imply government endorsement.

## Acceptance checks for this part of the rebuild

- Coastline comes from the same-origin source and displays at Morro, Cambria, Avila/Pismo; unavailable areas remain honest.
- NAIP tile decoding, CORS and CSP work in the actual Worker browser; the dated-aerial label remains visible.
- A GOES layer fetch requests an explicit supported UTC observation time and disappears or retains a clear observation label on a future-day view.
- Currents use toward degrees correctly (north=0, east=90) and label the selected **native frame**; no continuous arrows are fabricated from the three weather points.
- Source outage/expiry, empty cells, unsupported county and changed producer schema lead to blank or unavailable fields.
- Ocean currents never change a fishing catch probability, legal permission, underwater visibility, or navigation status by themselves.
- First paint and interaction remain usable on a small mobile screen; reduced-motion mode gives equal access to the same values.
