# Data confidence

The single reference for how sure SkipperCast is about what it shows: what each grade means, what a region's coverage states mean, how freshness is judged, and which claims have limits or were withdrawn. Other documents link here instead of repeating these caveats. The legally required caveats shown in the app are in [disclaimers.md](../legal/disclaimers.md).

## Grades and ratings

| Label | What it ranks | What it is not | Defined in |
| --- | --- | --- | --- |
| Terrain grade **A / B / C** | Mapped habitat search priority from four measured terrain factors: relief (35 points), rough-cover fraction (30), detrended complexity (20) and rough area (15). A ≥ 75 is a first look, B 55–74 a useful alternative, C < 55 exploratory. | Catch probability, safety, present conditions, boulder size or charter popularity. The weights are a research heuristic, not a validated ecological model. | [atlas-methodology.md](../atlas-methodology.md), [`atlas/scoring.py`](../../src/skippercast/atlas/scoring.py) |
| Species fit **1–3** | How a habitat patch's nominal depth sits against a species' published depth band (3 = grade A/B fully inside the band, 2 = overlap or grade C, 1 = outside). | Fish presence, temperature, prey or season. | [seafloor.md](../seafloor.md) |
| Seafloor tier **0–3** | Evidence behind a seafloor cell or polygon: 0 no usable survey; 1 measured depth in at least 25% of a 250 m cell; 2 a screened rough-bottom polygon 25–300 ft nominal with a grade and fit; 3 tier 2 plus datum-qualified depth or independent confirmation (not yet produced). | A navigation depth or a verified reef. | [seafloor.md](../seafloor.md#tiers-and-units) |
| Conditions rating **1–10** | A disclosed comfort and gear-control heuristic from forecast wind and sea state, scaled to the saved boat. | A fishing forecast or a statement that a trip or entrance is safe. | [assessment-rubric.md](../assessment-rubric.md), [boat-profile.md](../boat-profile.md) |
| Recent-activity confidence | How much dated, source-linked reporting supports recent activity for a species. | A bite probability. Target and habitat records carry `catch_probability: null`; the `calibrated-catch-model` capability is not ready in any region. | [bite-evidence.md](../bite-evidence.md) |

The seafloor habitat layer labels every patch **"Habitat candidate, unverified"** and every depth **"Nominal depth; verify on your sounder."** ([`dist/seafloor-data.js`](../../dist/seafloor-data.js)).

## Coverage states

Each region binds its data needs (bathymetry, substrate, protected areas, regulations, forecasts and so on) to reviewed sources in `regions/<id>/region.json`. The build writes `dist/regions/<id>/coverage.json` with one state per need ([`platform/contracts.py`](../../src/skippercast/platform/contracts.py), `need_status`):

| State | Meaning |
| --- | --- |
| `ready` | An **approved** source is bound and the region's reviewed evidence says it covers the need. |
| `partial` | An approved source is bound but covers the need only in part; the `reason` says what is missing. |
| `research` | Only **candidate** sources are bound: promising, but records, precision or rights still need review. |
| `missing` | No reviewed source is bound. |
| `not-applicable` | The need does not apply to this region. |

Coverage is never inferred from a successful HTTP request or an institution's name. A product capability (for example `surveyed-bottom-targets`, `fishing-exports`, `season-status`) is ready only when every need it depends on is `ready` or `not-applicable`; otherwise its `gaps` list names the blocking needs. Readiness describes reviewed source coverage only; current freshness and legal permission are checked separately.

Regions themselves are `active` (Morro Bay & Avila) or `preview` (every other package) in `dist/regions/index.json`.

## Freshness

Every collected source carries its own status ([`pipeline/collect.py`](../../src/skippercast/pipeline/collect.py)):

| Status | Meaning |
| --- | --- |
| `ok` | Fetched this run, and its sample or issue time is inside the source's `max_age_hours` window. |
| `stale` | Fetched, but its own timestamp is outside the freshness window (or more than an hour in the future). |
| `missing` | Fetched, but no usable cells in the regional grid. No gap filling is applied. |
| `failed` | The fetch failed and there is no previous value. |
| `retained` | The fetch failed; the previous value is kept with its original retrieval and success times, never relabelled as new. |

Consequences in the product:

- **Live observations** show station, observation time and age. Missing, failed and over-two-hour-old measurements are marked; a fetch time never becomes an observation time, and missing values never become zero wind or calm seas ([live-conditions.md](../live-conditions.md)).
- **Regulations:** a changed, missing, failed, retained, future-dated or over-36-hour-old source check withholds "season open" for the dependent species until a person reviews it ([regulations.md](../regulations.md)).
- **Feeds:** the live conditions feed publishes every 30 minutes. The hourly freshness check opens a `feed-stale` issue when the public feed is more than three hours old ([production-operations.md](../production-operations.md), [runbook](../operations/runbooks/feed-stale.md)). A failed forecast or feed run keeps the previous generation rather than publishing a partial one.
- **Seafloor habitat:** a polygon's legal screen must be no older than 35 days to publish.

## Depth datum

Depths are only comparable to a chart or sounder when the survey's vertical datum is known.

- The 11 survey-qualified Channel Islands reef patches use surveyed MLLW depths from original NOAA BAG files, with product uncertainty and a planning allowance screened at native 1–4 m resolution ([island-target-quality.md](../archive/island-target-quality.md)).
- Other Channel Islands terrain uses an unspecified merged reference and remains context only.
- The 132 historical Morro Bay–Avila terrain candidates come from a 2 m USGS raster whose output vertical datum and product uncertainty are unresolved. They are research-only.
- Monterey comparison bands are in NAVD88, not MLLW; conversion needs NOAA VDatum and its added uncertainty ([coverage ledger](../archive/central-coast-coverage-and-accuracy.md)).
- Seafloor tier-2 depths are nominal in the source datum; an unknown datum stays `"unknown"`.
- Actual sounder depth also changes with the water level.

The Central Coast boat-planning ceiling is 300 ft. No Morro Bay–Avila or Monterey–Point Conception target currently passes the full chart-depth qualification gate.

## Withdrawn and limited claims

- **Withdrawn September 27, 2026:** the MLLW/200 ft qualification of the 132 Morro Bay–Avila candidates. They keep exploratory terrain fits only ([coverage ledger](../archive/central-coast-coverage-and-accuracy.md)).
- **No AIS-confirmed charter hotspots.** Purple labels mark two named charter vicinities backed by 31 published trips; outlines are approximate search water, not boat positions ([charter-grounds.md](../charter-grounds.md)). The `verified-charter-hotspots` capability is not ready in any region.
- **No bite or catch probability** anywhere in the product.
- **Forecast verification** compares collected forecasts with nearby buoys; more independent outcomes are needed before any calibration ([forecast-verification-quality.md](../forecast-verification-quality.md)).
- **Outlines and drift lines:** outlines are partial habitat footprints, not reef boundaries; drift lines are optional alignments over structure, not safe approach or passage routes. Seafloor tile geometry is for display, not navigation or GPX boundaries.
- **Public atlas scope:** the downloadable atlas covers Avila / Point Buchon to Point Estero and omits 11 Cambria targets and the older DS1091 charter-ground annotations whose reuse terms are unresolved ([data-sources.md](../data-sources.md)). The forecast monitor example covers Cambria–Diablo Canyon, a different extent.
