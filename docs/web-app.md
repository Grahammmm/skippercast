# Web app

The app is a mobile-first map workspace with four views: **Map, Spots, Forecast, and Guide**. Its source lives in `dist/` and is tracked directly; no framework build or package installation is required. Serve that directory with any static HTTP server:

```bash
python3 -m http.server 8485 --directory dist
```

Open `http://localhost:8485/`. A file-system `file:` URL cannot fetch the atlas module/data reliably, so use the HTTP server. On an iPad, use the deployed HTTPS site.

## What works

- Open directly into a full-height map with bottom navigation, touch-sized controls, and safe-area spacing. Phones and tablets show a compact selected-spot card; tapping it opens a scrollable detail sheet with fixed map/export actions. Wide screens dock the list and detail panel alongside the map.
- Filter 132 targets by area, terrain grade, maximum survey-neighborhood depth, and linked geometry; search names and marker IDs.
- Select a target from the list, a marker, a reef footprint, or a drift alignment. Its detail panel shows coordinates, survey depths, terrain metrics, notes, evidence limitations, and source links.
- Compare A/B/C definitions in Guide and inspect all four weighted score contributions for each target, with plain-language explanations of points, partial reef areas, and drift alignments.
- Read the dated historical AIS research summary, exact sample coverage, aggregate counts, and limitations. No verified local sportfishing-charter tracks or charter-activity overlays are currently available.
- Toggle reef outlines, drift lines, markers, and forecast sample labels.
- Download the complete GPX or a single target with its linked geometry using direct file links, including from the mobile sheet. GPX polygons are separate track rings; they are not navigable routes. Share the downloaded file to iNavX.
- Request wind and wave forecasts for three fixed offshore samples. Compare ECMWF IFS / NOAA GFS and ECMWF WAM / NOAA GFS Wave, choose the next seven dates and hours 06:00–13:00 Pacific, inspect components, complete-window ranges, model metadata, returned grid coordinates, and current PZZ645 alerts.

Forecast requests go directly from the browser to the providers. There is no account, backend database, analytics code, saved trip record, or credential in this app. Hosting providers and external map/weather services process ordinary network requests. Base-map tiles are fetched only for the visible map; there is no bulk or offline tile download.

Changing views preserves filters, selection, map position, and loaded forecasts during the page session. Browser Back also closes an opened spot sheet. A reload starts a new session; an old sheet URL returns to Map because selection is not stored. The app is a mobile website, with no offline map cache or native installation required.

## Evidence limits

The atlas is a dated research layer, with no AIS-confirmed charter hotspots or verified catch success. It has no live closure overlay, nautical navigation route, harbor-current model, or trip qualification engine. Its public scope ends at Point Estero; the excluded Cambria data remain excluded.

Forecasts are coarse model values, not observations at individual targets. The browser labels missing fields unavailable, checks units and timestamps, flags model disagreements and inconsistent gust/component values, and never assigns a go/no-go or 9/10 score. The 06:00–13:00 screen does not calculate transit or establish four fishing hours. Four-to-seven-day dates are provisional. NWS alerts are a retrieval-time snapshot, not future clearance. Model availability metadata are not guaranteed run attribution for every value in a rolling timeseries. A forecast older than an hour receives a refresh notice; reloading is explicit.

## Source layout

| File | Responsibility |
| --- | --- |
| `dist/index.html`, `styles.css` | Mobile-first app shell, bottom navigation, filters, map, sheets, and larger-screen layout |
| `dist/app.js` | Target selection, geometry layers, GPX download, optional WebMCP interface |
| `dist/navigation.js` | Hash-based view navigation, modal history/focus, and responsive detail placement |
| `dist/forecast.js` | Provider requests and pure unit/time/missing-data checks |
| `dist/weather-ui.js` | Forecast controls, comparison tables, metadata, station overlay |
| `dist/gpx.js` | Selected-target GPX with separate polygon rings |
| `scripts/export_web_targets.mjs` | Generate the 132 direct single-target GPX files in `dist/downloads/targets/` |
| `dist/data/`, `downloads/` | Copies of the reviewed public atlas and exports; dated aggregate AIS research summary |
| `dist/vendor/` | Leaflet 1.9.4 plus its BSD license; exact hashes in `scripts/web-vendor-sha256.json` |

`scripts/check_web.py` verifies that deployed copies match the canonical atlas and license, checks vendor hashes and local assets, and parses the shipped GPX. After an atlas refresh, run `node scripts/export_web_targets.mjs` to rebuild the direct downloads. JavaScript checks use `node --test tests/test_web.mjs` (Node 22+) and verify every prebuilt target file against the exporter; the existing Python checks remain independent.

Supported browsers can expose two page-scoped WebMCP tools: `list_fishing_targets` reads the currently filtered list; `show_fishing_target` resets filters and selects an existing target. Neither tool saves a trip, downloads a file, or sends an alert. Unsupported browsers retain the full visible interface.

## Hosting

The registered Sites project is identified by `.openai/hosting.json`; only its `dist/` static directory is published. Source credentials, generated archives, DNS receipts, and personal monitor state are not committed. The source repository and the hosting deployment are separate services. Never recreate a Site because an upload or build fails; reuse its existing project ID.

The private personal Telegram monitor is not wired into the public web app. The portable Python collector and alert lifecycle stay available for a later authenticated integration.
