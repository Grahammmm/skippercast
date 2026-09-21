# SkipperCast

**Find structure worth investigating. Collect the evidence for a good morning on the water.**

SkipperCast is a mobile-first boat-fishing map and research toolkit. Open the map, find a spot, expand its notes, and download a GPX for your chartplotter. Select a species, scrub seven days of ocean conditions, and inspect a tide chart and wave components. Map, Conditions, and Guide views keep habitat, marine evidence, and research context within reach on a phone. It began with rockfish and lingcod fishing near Morro Bay, California, from a 23-foot boat.

**[Open the app](https://skippercast.com)** · [Hosting address](https://skippercast.email-me-here-2016.chatgpt.site) · [Web app guide](docs/web-app.md)

**Status:** mobile web app and research release. The code and original documentation are **source-available for personal use** under the [SkipperCast Personal Use License](LICENSE).

**See how it fits together:** [data flow, chart layers, and software stack](docs/system-overview.md).

## What you can use today

| Part | What it does | Start here |
| --- | --- | --- |
| Interactive map | NOAA nautical chart, seven-day wind/wave/tide timeline, seven species profiles, 132 reef candidates, 12 connected soft-bottom habitat outlines, three charter-reported grounds with dated boat histories, and offshore search references. | [Web app guide](docs/web-app.md) |
| Fishing atlas | 132 noted habitat candidates, 107 partial reef outlines, and 31 optional drift alignments from Avila / Point Buchon to Point Estero. GPX for chartplotters, GeoJSON, and searchable offline notes. | [Atlas and downloads](atlas/avila-point-estero-2026-09-20/README.md) |
| Forecast collector | Saves public forecast responses, model metadata, buoy observations, advisories, and access failures for a Morro Bay example profile. Compares numerical ranges and flags missing or inconsistent evidence. | [Run the collector](docs/quickstart.md#collect-live-evidence) |
| Alert lifecycle | Given an already reviewed assessment and prior delivery state, decides whether an initial alert, update, retraction, or day-before assessment is due. | [Offline demo](#try-it-offline) · [Assessment workflow](docs/forecast-workflow.md) |

The collector **does not decide a trip is safe, assign fishing scores, or predict catches**. Reviewing sources, checking the complete trip and current rules, scoring an opportunity, scheduling checks, and delivering alerts require a person, an agent, or a separately implemented integration. The [architecture](docs/architecture.md) shows that boundary.

## Try it offline

From the repository root, with Python 3.11 or newer:

```bash
PYTHONPATH=src python3 -m skippercast demo
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

The demo uses invented assessments. It prints an initial alert decision, silence for an unchanged assessment, a retraction when evidence disappears, and a day-before decision. It makes no network requests and sends no messages. Windows and installation instructions are in the [quickstart](docs/quickstart.md).

To use the existing atlas without Python, download [complete.gpx](atlas/avila-point-estero-2026-09-20/exports/complete.gpx) and follow the [iNavX import guide](docs/inavx.md), or download and open [spot-notes.html](atlas/avila-point-estero-2026-09-20/exports/spot-notes.html) locally.

## Read the atlas correctly

- A grade ranks **mapped habitat search priority**, not catch probability, boulder size, or a verified fishing hotspot. Purple boat labels mark [three charter-reported grounds](docs/charter-grounds.md), backed by 45 published trips. Their outlines are approximate search water, not exact boat positions. There are **no AIS-confirmed charter hotspots** in this release.
- Outlines are selected portions of surveyed habitat. Drift lines are optional alignments over structure, **not safe approach or passage routes**.
- Depths are referenced to the survey's MLLW datum. Actual sounder depth changes with water level; the example fishing limit is 200 feet.
- This public atlas excludes 11 Cambria targets and the older DS1091 charter-ground annotations whose source reuse terms are unresolved. The [source register](docs/data-sources.md) explains the smaller public edition.
- The monitor example covers **Cambria–Diablo Canyon**; the included public atlas covers **Avila / Point Buchon–Point Estero**. They have different extents.

Use current official charts, rules, protected-area boundaries, and local entrance conditions for the actual trip. This dated research layer is not navigation or legal clearance.

## Repository map

```text
src/skippercast/       Portable Python code: collector, alert rules, atlas exporter
dist/                 Authored static web app, public data, downloads, vendored map library
configs/              Public example configuration; no delivery credentials
atlas/                Dated, attributed public data and ready-to-import exports
docs/                 Quickstart, workflow, scoring, methods, and source rights
tests/                Offline tests for missing evidence, alert state, and exports
scripts/              Repository checks used locally and in CI
.github/workflows/    Offline CI and daily public-evidence collection
```

Start with the [quickstart](docs/quickstart.md), then the [forecast workflow](docs/forecast-workflow.md) or [atlas methodology](docs/atlas-methodology.md). The [roadmap](docs/roadmap.md) separates future app work from shipped functionality. See [CONTRIBUTING.md](CONTRIBUTING.md) for development.

## License and data rights

The custom license permits individuals to use and modify SkipperCast for private recreation and learning, and to share free copies under the same terms. Commercial, charter, professional, and organizational use requires separate permission. A personal-use restriction makes this **source-available, not OSI open source**; see the [Open Source Definition](https://opensource.org/osd).

Third-party and public-domain data retain their own rights. The personal-use restriction does not relicense underlying USGS facts, CDFW CC BY data, or other third-party material. See [NOTICE.md](NOTICE.md) and the full [LICENSE](LICENSE).

## Daily fishing evidence

The app adds species-specific confidence notes from dated charter reports, plus satellite surface temperature, chlorophyll and radar-current context when available. A daily GitHub Actions job refreshes the public feed at 4:17 a.m. Pacific, with per-source dates and visible failures. Weather continues to refresh separately. No bite probability is claimed. Read the [research and operating guide](docs/bite-evidence.md), inspect [job status](https://github.com/Grahammmm/skippercast/actions/workflows/daily-data.yml), or use the [public feed](https://raw.githubusercontent.com/Grahammmm/skippercast/data/latest.json).
