# Web app

The app is a mobile-first map workspace with three views: **Map, Conditions, and Guide**. Its source lives in `dist/` and is tracked directly; no framework build or package installation is required. Serve that directory with any static HTTP server:

```bash
python3 -m http.server 8485 --directory dist
```

Open `http://localhost:8485/`. A file-system `file:` URL cannot fetch the atlas module/data reliably, so use the HTTP server. On an iPad, use the deployed HTTPS site.

## What works

- Open into a full-width map with bottom navigation, touch-sized controls, and safe-area spacing. Reef candidates group as you zoom out. Tap a marker or habitat area for a scrollable detail sheet with fixed actions; there is no permanent list or detail sidebar.
- Filter 132 targets by area, terrain grade, maximum survey-neighborhood depth, and linked geometry; search names and marker IDs.
- Select a target from a marker, a reef footprint, or a drift alignment. Its detail panel shows coordinates, survey depths, terrain metrics, notes, evidence limitations, and source links.
- Compare A/B/C definitions in Guide and inspect all four weighted score contributions for each target, with plain-language explanations of points, partial reef areas, and drift alignments.
- Tap purple boat labels for two named charter vicinities: Pecho Rock and Diablo coast. Inspect boats, dates, primary report links, approximate search outlines and nearby separate terrain candidates. The layer is backed by 31 single-ground reports from a 601-trip sample; broad Morro Bay reports are retained as regional evidence without an outline. It has no verified local charter AIS tracks. Read [the charter-ground method](charter-grounds.md).
- Use the detailed NOAA ENC chart basemap or street-map fallback; toggle reef outlines, drift lines, markers, and weather samples.
- Select regional targets from a shared catalog. The Central Coast offers **Lingcod & rockfish**, California halibut, Chinook salmon, albacore, bluefin and Dungeness. Southern California offers 16 targets, including lobster, sheephead, three bass groups, white seabass, yellowtail, yellowfin and dorado; see [Southern species research](southern-species-research.md). The combined reef view includes both species’ habitat and reports, counting each reported trip once. Their legal limits stay separate in the regulations card. Connected sediment outlines and pelagic search references retain their own evidence. Read [the species research](species-research.md).
- Download the complete 132-target rocky atlas GPX or a single rocky target with its linked geometry using direct file links, including from the mobile sheet. Charter search outlines, sediment regions and pelagic search references are currently map-only. GPX polygons are separate track rings; they are not navigable routes. Share the downloaded file to iNavX.
- Scrub or play 169 hourly samples from the current forecast hour through seven days ahead. Weather loads automatically at 13 coastal/offshore reference locations. Choose wind, waves, modeled sea-surface temperature, or a disclosed hourly comfort screen.
- Inspect wind, gusts, visibility, precipitation, swell/chop heights and periods, direction arrows, a boat-heading comparison, 24-hour trends, NOAA Port San Luis tides, and a separately timestamped recent water-level observation.
- Compare ECMWF IFS / NOAA GFS and ECMWF WAM / NOAA GFS Wave. Review per-model run metadata, returned grid coordinates, coverage, and active PZZ645/PZZ670 alerts. GFS primary-wave headline periods and ECMWF mean periods are labeled separately.

Shared cloud jobs publish regional environmental evidence. A Worker serves cached public feeds, with direct-provider recovery in the browser. Optional authenticated features store private saved trips and comfort feedback in D1; anonymous map browsing needs no account. Public assets contain no credentials or private records. See [production operations](production-operations.md) for isolation and retention. Hosting providers and external map/weather services process ordinary network requests. Base-map tiles are fetched only for the visible map; there is no bulk or offline tile download.

Changing views preserves filters, selection, map position, and loaded forecasts during the page session. Browser Back also closes an opened spot sheet. A reload resets target selection; an old sheet URL returns to Map. Public forecast responses are cached in session storage for up to 30 minutes to reduce repeated provider requests; the original retrieval time remains visible. Refresh bypasses the cache. The app is a mobile website, with no offline map cache or native installation required.

## Evidence limits

The atlas is a dated research layer, with no AIS-confirmed charter hotspots or verified catch success. It shows official MPA boundaries and screens all fishing geometries against them at load; this is not a complete live closure service. It has no nautical navigation route or harbor-current model. Saved-trip threshold alerts do not certify navigation or entrance clearance. Central Coast qualified targets end at Point Estero; Cambria–San Simeon adds geological context. Southern California adds 410 historical island habitat outlines and 84 source-grid terrain views with explicit datum and coverage limits. The excluded source products remain excluded. Weather/search-reference coverage extends offshore. Search references are constructed samples, not species detections or charted routes.

Forecasts are regional model values, not observations at individual targets. The browser checks units, timestamps, populated fields, published end times, model disagreements, and inconsistent gust/component values. It never assigns a go/no-go or a qualified trip recommendation. Morning ratings use a separate disclosed 0–10 conditions heuristic; bite potential stays unknown. The qualitative hourly comfort screen uses disclosed wind/sea preferences and does not calculate transit, verify four fishing hours, or certify an entrance. Days four through seven are provisional. Active alerts are a retrieval-time snapshot, not future clearance. Provider metadata are not guaranteed run attribution for every value in a rolling timeseries. Stale evidence cannot earn a calmer label.

NOAA chart images follow the service's portrayal units. Wave, tide, and habitat cards use feet; wind uses knots. Wave/wind directions are from; current direction is toward. All timestamps render in Pacific time. NOAA tides are astronomical predictions for Port San Luis, not Morro Bay bar currents. The Live tab loads dated buoy observations through the public conditions feed. Harbor pages remain external references, not live entrance clearance.

## Source layout

| File | Responsibility |
| --- | --- |
| `dist/index.html`, `styles.css`, `map-first.css` | Mobile-first app shell, bottom navigation, filters, map, sheets, and larger-screen layout |
| `dist/app.js` | Target selection, geometry layers, GPX download, optional WebMCP interface |
| `dist/charter-grounds.js`, `data/charter-grounds.json` | Named-ground report layer, dated boat histories, separate approximate search outlines |
| `dist/navigation.js` | Hash-based view navigation, modal history/focus, and responsive detail placement |
| `dist/forecast.js` | Original shared forecast helpers retained for the existing checks |
| `dist/marine-data.js` | Per-model requests, UTC sampling, tides, units, direction and comfort checks |
| `dist/marine-charts.js`, `marine-detail.js` | Wave diagrams, compass, tide/weather graphs, evidence detail |
| `dist/species.js`, `data/habitat-regions.json`, `data/species-habitat.json` | Sourced species guide, reef selection, connected surveyed sediment outlines, pelagic search references |
| `dist/chart-map.js`, `marine.css` | NOAA nautical basemap and mobile ocean controls |
| `dist/morning-outlook.js` | Seven-day morning ranking, missing-data safeguards, and top-bar highlights |
| `dist/live-conditions.js` | Current buoy, airport weather, water level and alert loading, source timestamps and freshness |
| `dist/weather-ui.js` | Shared map/detail timeline, playback, selected forecast sample, model choice, caching, overlay |
| `dist/gpx.js` | Selected-target GPX with separate polygon rings |
| `scripts/export_web_targets.mjs` | Generate the 132 direct single-target GPX files in `dist/downloads/targets/` |
| `dist/data/`, `downloads/` | Copies of the reviewed public atlas and exports; dated aggregate AIS research summary |
| `dist/vendor/` | Leaflet 1.9.4 plus its BSD license; exact hashes in `scripts/web-vendor-sha256.json` |

`scripts/check_web.py` verifies that deployed copies match the canonical atlas and license, checks vendor hashes and local assets, and parses the shipped GPX. After an atlas refresh, run `node scripts/export_web_targets.mjs` to rebuild the direct downloads. JavaScript checks use `node --test tests/test_web.mjs tests/test_marine.mjs tests/test_morning.mjs tests/test_charters.mjs` (Node 22+) and verify every prebuilt target file against the exporter; the existing Python checks remain independent.

Supported browsers can expose two page-scoped WebMCP tools: `list_fishing_targets` reads the currently filtered rocky-target list (sediment/search references are not yet part of that API); `show_fishing_target` resets filters and selects an existing target. Neither tool saves a trip, downloads a file, or sends an alert. Unsupported browsers retain the full visible interface.

## Hosting

The registered Sites project is identified by `.openai/hosting.json`; only its `dist/` static directory is published. Source credentials, generated archives, DNS receipts, and personal monitor state are not committed. The source repository and the hosting deployment are separate services. Never recreate a Site because an upload or build fails; reuse its existing project ID.

The private personal Telegram monitor is not wired into the public web app. The portable Python collector and alert lifecycle stay available for a later authenticated integration.

## Map simplification and review

The September 21 mobile review found obstructed popups, overlapping layer controls, crowded reef pins and excessive conditions scrolling. The app now uses a full-width map at every viewport, no permanent list or selected-detail sidebar, no automatic first selection, grid-clustered reef markers, and one native dialog for selected points and areas. NOAA cable/seabed symbols are off in Fishing chart and restored by Full NOAA chart. The initial map centers on the Morro Bay grounds at zoom 11; Fit map still shows all filtered grounds. Species and Options are the primary controls. The weather summary is compact, with the seven-day scrubber and playback behind Timeline. Rules start collapsed. The guide opens one topic at a time, and Conditions puts current weather ahead of expandable evidence and reference notes. Model/layer/filter/export controls are in Options. Conditions has Live/Waves/Wind/Tides/Sources tabs.

`dist/data/habitat-regions.json` contains connected soft-bottom outlines built by `scripts/build_habitat_regions.py`; the old 18-window artifact is retained but not rendered. `dist/morning-outlook.js` ranks complete future 7 a.m.–1 p.m. windows using two models and distinguishes conditions, comfort, gear control, confidence and unknown bite potential. The top bar links to the full evidence. [Research and scoring method](species-research.md#morning-ratings).

## Live measurements

Conditions opens to **Live**, showing dated NOAA buoy readings, KSBP airport weather
and Port San Luis measured water level. The map’s current-hour summary uses measured
buoy seas when fresh and explicitly labels a forecast fallback. Choose Waves, Wind
or Tides for the modeled/predicted timeline; selecting a future hour leaves Live.
The browser checks observations and marine alerts every five minutes while visible
and forecasts every 30 minutes. [Sources and the cloud refresh](live-conditions.md).

## Link previews

The initial HTML contains Open Graph and X large-image metadata for
`https://skippercast.com/`. Crawlers can read the title, description and absolute
image URL without running JavaScript. All hash views share this site-wide card.

The [published share image](../dist/skippercast-parker-preview.jpg) is a 1736 × 906
JPEG, 493,062 bytes. It preserves the composition and dimensions of the
[original PNG](../dist/og.png), generated from this [prompt](social-preview-prompt.txt).
The original 2.3 MB PNG exceeded [Signal Desktop's 1 MiB image download limit](https://github.com/signalapp/Signal-Desktop/blob/main/ts/linkPreviews/linkPreviewFetch.preload.ts),
so Signal displayed the title and description without the boat image. The JPEG
uses a new URL and is less than half that limit. Keep social-preview images below
1,048,576 bytes, publicly accessible as JPEG or PNG, and declared in the initial
HTML. This is separate from ordinary in-app attachment size limits.

Both image hashes are recorded in `scripts/web-vendor-sha256.json`. Keep image
dimensions, media type and hashes in sync when replacing the card. To check a
change, remove the existing unsent link and paste it into Signal again; an already
sent preview is embedded in its message and is not updated by redeploying the site.

## Map and forecast planning

See [the release method](map-and-forecast.md) for persistent MPAs, zoom-driven reef outlines, time-varying surface-current guides, measured drift input, daily/hourly scores and compact variables. The opt-in [historical commercial AIS layer](commercial-ais-research.md) is separate from habitat and charter evidence. [Product research](product-research.md) records potential future additions; it is not a claim that those features ship.

Southern island outlines are screened in a Web Worker against complete current closure geometry before display. Source dates, acquisition/compilation distinctions, numeric grid resolution, substrate uncertainty and kelp age stay visible in expandable cards. View shortcuts are shareable with `&focus=anacapa`; they change the nearest regional weather reference as well as the map. The original NOAA/CDFW files and compiler receipts are described in [the habitat guide](southern-habitat-sources.md).
