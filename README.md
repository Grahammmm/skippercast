# SkipperCast

[Statewide buildout ledger](docs/statewide-buildout.md) · [Central Coast coverage and accuracy](docs/central-coast-coverage-and-accuracy.md) · [Region pipeline and full data flow](docs/region-pipeline.md) · [How the regional platform works](docs/platform.md) · [Add a coastline](docs/regions.md) · [Data needs and contracts](docs/data-contracts.md) · [Operating the app](docs/production-operations.md) · [Data-quality rollout](docs/data-quality-rollout.md)


**Find structure worth investigating. Collect the evidence for a good morning on the water.**

SkipperCast is a mobile-first boat-fishing map and research toolkit. Open the map, find a spot, expand its notes, and build a small GPX day plan for your chartplotter. Select a species, scrub seven days of ocean conditions, and inspect a tide chart and wave components. Map, Conditions, Export, and Guide views keep habitat, marine evidence, and research context within reach on a phone. It began with rockfish and lingcod fishing near Morro Bay, California, from a 23-foot boat.

**[Open the app](https://skippercast.com)** · [Hosting address](https://skippercast.email-me-here-2016.chatgpt.site) · [Web app guide](docs/web-app.md)

**Status:** mobile web app with shared regional ocean feeds, private saved-trip alerts and research layers. The code and original documentation are **source-available for personal use** under the [SkipperCast Personal Use License](LICENSE).

**See how it fits together:** [current data flow and region rollout](docs/region-pipeline.md).

## What you can use today

| Part | What it does | Start here |
| --- | --- | --- |
| Coastal regions | Five CDFW ocean planning regions, locally ordered species, a daily NOAA seasonal watch and statewide MPAs. Detailed fishing packages remain separate from coastal browse coverage. | [Coastal directory and update process](docs/coastal-directory.md) |
| Statewide sectors | Nineteen smaller outer-coast planning sectors with a dated NOAA BAG-survey discovery feed. They organize future local packages; survey leads are not fishing spots. | [Statewide buildout ledger](docs/statewide-buildout.md) |
| Interactive map | NOAA nautical chart, seven-day wind/wave/tide timeline, regional species selectors (16 for Southern California), 132 Central Coast reef candidates, 11 survey-qualified island reef areas, 12 connected soft-bottom habitat outlines, source-dated Channel Islands habitat and terrain views, two named Central Coast charter vicinities, MPA boundaries, historical commercial AIS and dated boat histories, and offshore search references. | [Web app guide](docs/web-app.md) |
| Dynamic ocean layers | Dated satellite temperature, temperature gradients and chlorophyll; NOAA surface temperature and current forecasts at native resolution, following the selected time within actual forecast coverage. | [Methods and limitations](docs/dynamic-species-method.md) |
| Forecast verification | Prospective forecasts matched to nearby buoy observations, with distinct-hour coverage, measurement differences and fair model comparisons. More independent outcomes are needed before calibration. | [Verification method](docs/forecast-verification-quality.md) |
| Fishing atlas | 132 noted habitat candidates, 107 partial reef outlines, and 31 optional drift alignments from Avila / Point Buchon to Point Estero. GPX for chartplotters, GeoJSON, and searchable offline notes. | [Atlas and downloads](atlas/avila-point-estero-2026-09-20/README.md) |
| Chartplotter day plan | Choose individual spots, the current map, filtered spots or one region; include waypoints, linked outlines, fixed alignment tracks and protected-area reference tracks. Save a local draft, share GPX and download offline notes. | [Export and device guide](docs/chartplotter-export.md) · [Mobile review](docs/mobile-review.md) |
| Forecast collector | Saves public forecast responses, model metadata, buoy observations, advisories, and access failures for a Morro Bay example profile. Compares numerical ranges and flags missing or inconsistent evidence. | [Run the collector](docs/quickstart.md#collect-live-evidence) |
| Alert lifecycle | Given an already reviewed assessment and prior delivery state, decides whether an initial alert, update, retraction, or day-before assessment is due. | [Offline demo](#try-it-offline) · [Assessment workflow](docs/forecast-workflow.md) |

The public conditions rating is a disclosed comfort/gear-control heuristic. Optional private saved-trip alerts compare your chosen weather window and reviewed rules, with updates and a final previous-evening assessment. They do not certify a route or entrance and do not predict catches. See [regional intelligence](docs/regional-intelligence.md) and [production operations](docs/production-operations.md).

## Try it offline

From the repository root, with Python 3.11 or newer:

```bash
PYTHONPATH=src python3 -m skippercast demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The demo uses invented assessments. It prints an initial alert decision, silence for an unchanged assessment, a retraction when evidence disappears, and a day-before decision. It makes no network requests and sends no messages. Windows and installation instructions are in the [quickstart](docs/quickstart.md).

To use the existing atlas without Python, download [complete.gpx](atlas/avila-point-estero-2026-09-20/exports/complete.gpx) and follow the [iNavX import guide](docs/inavx.md), or download and open [spot-notes.html](atlas/avila-point-estero-2026-09-20/exports/spot-notes.html) locally.

## Read the atlas correctly

- A grade ranks **mapped habitat search priority**, not catch probability, boulder size, or a verified fishing hotspot. Purple boat labels mark [two named charter vicinities](docs/charter-grounds.md), backed by 31 published trips. Their outlines are approximate search water, not exact boat positions. There are **no AIS-confirmed charter hotspots** in this release.
- Outlines are selected portions of surveyed habitat. Drift lines are optional alignments over structure, **not safe approach or passage routes**.
- Qualified Central Coast targets and the 11 new island patches use surveyed MLLW depths. The island patches also screen product uncertainty and a planning allowance at native 1–4 m resolution. Other Channel Islands terrain retains an unspecified merged reference and remains context. Actual sounder depth changes with water level. The Central Coast boat-planning ceiling is 300 feet, but its currently published targets were only qualified through 200 feet; [the coverage ledger](docs/central-coast-coverage-and-accuracy.md) tracks the gap.
- This public atlas excludes 11 Cambria targets and the older DS1091 charter-ground annotations whose source reuse terms are unresolved. The [source register](docs/data-sources.md) explains the smaller public edition.
- The monitor example covers **Cambria–Diablo Canyon**; the included public atlas covers **Avila / Point Buchon–Point Estero**. They have different extents.

Use current official charts, rules, protected-area boundaries, and local entrance conditions for the actual trip. This dated research layer is not navigation or legal clearance.

## Repository map

```text
src/skippercast/       Portable Python code: collector, alert rules, atlas exporter
dist/                 Authored browser app and data; generated client/server folders ignored
server/               Cached public API, private access, trip outbox and OIDC job policy
db/ and drizzle/       D1 schema and reviewed migrations
regions/ and catalog/  Regional bindings, data needs and scoped species evidence
deployments/          Public origin and immutable scheduled-workflow identity policy
configs/              Public example configuration; no delivery credentials
atlas/                Dated, attributed public data and ready-to-import exports
docs/                 Quickstart, workflow, scoring, methods, and source rights
tests/                Offline tests for missing evidence, alert state, and exports
scripts/              Repository checks used locally and in CI
.github/workflows/    Offline CI and daily public-evidence collection
```

Before packaging a Sites release, run `npm run build`. Production serves generated `dist/client`, so a source-only edit under `dist/` will not reach visitors until that build has copied it into the client bundle. Verify the published URL for each new asset after deployment.

Start with the [quickstart](docs/quickstart.md), then the [forecast workflow](docs/forecast-workflow.md) or [atlas methodology](docs/atlas-methodology.md). The [roadmap](docs/roadmap.md) separates future app work from shipped functionality. See [CONTRIBUTING.md](CONTRIBUTING.md) for development.

## License and data rights

The custom license permits individuals to use and modify SkipperCast for private recreation and learning, and to share free copies under the same terms. Commercial, charter, professional, and organizational use requires separate permission. A personal-use restriction makes this **source-available, not OSI open source**; see the [Open Source Definition](https://opensource.org/osd).

Third-party and public-domain data retain their own rights. The personal-use restriction does not relicense underlying USGS facts, CDFW CC BY data, or other third-party material. See [NOTICE.md](NOTICE.md) and the full [LICENSE](LICENSE).

## Daily fishing evidence

Selecting a target opens its local regulations card: season status and dates,
size and bag limits, gear rules and official CDFW links. The daily job checks
the official sources against reviewed versions. Changed, failed or stale checks
withhold the open-season badge until reviewed. See [how regulation updates work](docs/regulations.md).

The app adds species-specific confidence notes from dated charter reports, plus satellite surface temperature, chlorophyll and radar-current context when available. A daily GitHub Actions job refreshes the public feed at 4:17 a.m. Pacific, with per-source dates and visible failures. A [recent discussion research pipeline](docs/recent-intel.md) rotates regional searches through a pinned last30days engine; its candidate links require review before they influence the map or ratings. The Live tab shows dated NOAA buoy readings, local airport weather and measured water level. A separate cloud job refreshes buoy observations every 30 minutes; the app checks current observations and advisories every five minutes while open. [Live conditions and sources](docs/live-conditions.md). The live job also collects regional forecasts, ensembles, radar, WCOFS surface currents and prospective verification. Its habitat stage refreshes native ocean tiles with six-hour provider caches, retaining original source dates and cloud gaps. A cached Worker feed supplies the app, with direct-provider recovery. No bite probability is claimed. Read the [research and operating guide](docs/bite-evidence.md), inspect [job status](https://github.com/Grahammmm/skippercast/actions/workflows/daily-data.yml), or use the [public feed](https://raw.githubusercontent.com/Grahammmm/skippercast/data/latest.json).

Recent additions: [map protection, drift guides and forecast ratings](docs/map-and-forecast.md), [historical commercial AIS](docs/commercial-ais-research.md), and [feature research across 13 products](docs/product-research.md).

Selected release features: [hourly comparison, scoped regulations, spot evidence, currents and ensembles, bottom exploration, iNavX sets and private alerts](docs/implementation-2026-09.md).
