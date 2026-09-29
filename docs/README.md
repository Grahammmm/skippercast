# SkipperCast documentation

Every document in `docs/`, grouped by who it is for. Start with the [architecture](architecture.md) for how the system fits together, or the [web app guide](web-app.md) for what it does.

Documents marked **research log** are dated audit, rollout and source-request records. They are the evidence trail behind coverage decisions, not descriptions of current product behaviour, and nothing in them is a product claim on its own. They will move to a research archive (guide P5-01; the move waits until the open pull requests that touch `docs/` have merged). When a product document needs one of their conclusions, it should state the conclusion itself and link the log as evidence.

## Product: what the app does

| Document | Purpose |
| --- | --- |
| [web-app.md](web-app.md) | The app's views (Map, Conditions, Export, Guide), what works, evidence limits and source layout |
| [quickstart.md](quickstart.md) | First steps: use the atlas on a chartplotter, or run the Python tools |
| [roadmap.md](roadmap.md) | Shipped functionality versus future work |
| [coastal-directory.md](coastal-directory.md) | The five CDFW coastal regions, the region selector and seasonal species |
| [platform.md](platform.md) | How one shared app serves many reviewed regional packages |
| [live-conditions.md](live-conditions.md) | Live observations: buoys, weather stations, water level; also published as the `conditions` branch README |
| [map-and-forecast.md](map-and-forecast.md) | Map protection overlays, drift guides and forecast ratings (September 21 feature note) |
| [local-map-context.md](local-map-context.md) | How targets and rules follow the selected spot or map area |
| [regulations.md](regulations.md) | The Rules card: season, limits and how rule updates are reviewed |
| [regional-intelligence.md](regional-intelligence.md) | Regional forecast comparison, ensembles, currents and saved-trip alerts |
| [boat-profile.md](boat-profile.md) | Entering your boat and how comfort and drift ratings scale to it |
| [assessment-rubric.md](assessment-rubric.md) | The fixed 1–10 comfort and fishing-conditions rubric for reviewed assessments |
| [forecast-workflow.md](forecast-workflow.md) | Operator or agent review from forecast evidence to an assessment |
| [species-search-plans.md](species-search-plans.md) | Per-species map shortlists and how they are built |
| [fishing-strategies.md](fishing-strategies.md) | Reviewed starter methods for each target species |
| [charter-grounds.md](charter-grounds.md) | Charter-reported fishing grounds (purple labels) and their limits |
| [seabed-views.md](seabed-views.md) | Measured bottom relief and depth views for reef targets |
| [chartplotter-export.md](chartplotter-export.md) | Exporting a GPX day plan and offline notes |
| [inavx.md](inavx.md) | Importing a day plan into iNavX |

## Product: data, methods and evidence

| Document | Purpose |
| --- | --- |
| [data-sources.md](data-sources.md) | Source register: providers, dates, licences and processing |
| [forecast-data.md](forecast-data.md) | SkipperCast's own NOAA and ECMWF forecast tiles: models, grids, licences |
| [forecast-verification-quality.md](forecast-verification-quality.md) | Prospective verification of collected forecasts against observations |
| [bite-evidence.md](bite-evidence.md) | Dated catch reports, the daily data pipeline and why there is no bite probability |
| [recent-intel.md](recent-intel.md) | Recent local fishing-discussion research pipeline and its review rules |
| [dynamic-species-method.md](dynamic-species-method.md) | Dated water-mass layers (temperature, fronts, chlorophyll, currents) and their limits |
| [atlas-methodology.md](atlas-methodology.md) | How the dated Morro Bay–Avila habitat atlas was derived |
| [seafloor.md](seafloor.md) | The seafloor pipeline: original surveys to graded, legally screened habitat tiles |
| [california-seabed-coverage.md](california-seabed-coverage.md) | Statewide seabed coverage and the gate for promoting an area to fishing targets |
| [data-quality-rollout.md](data-quality-rollout.md) | Quality gates from regional evidence to a published coastal map |
| [species-research.md](species-research.md) | Central Coast species, sea state and search-area research (September 21 review) |
| [southern-species-research.md](southern-species-research.md) | Southern California species and habitat evidence (September 22 review) |

## Engineering

| Document | Purpose |
| --- | --- |
| [architecture.md](architecture.md) | Current system context, containers, components, hosting and scheduled jobs |
| [region-pipeline.md](region-pipeline.md) | Region rollout and the full data flow |
| [regions.md](regions.md) | How to add a coastline: contracts, sources, compiler and checks |
| [data-contracts.md](data-contracts.md) | Data needs, source bindings and feed contracts |
| [monitor-reference.md](monitor-reference.md) | The legacy Morro Bay forecast collector and alert lifecycle |
| [map-engine-test.md](map-engine-test.md) | MapLibre + PMTiles versus Leaflet + GeoJSON test on one layer |
| [social-preview-image-sources.md](social-preview-image-sources.md) | Provenance of the social preview image (prompt in `social-preview-prompt.txt`) |

Also for engineers: [AGENTS.md](../AGENTS.md) (branch, PR and rebuild rules), [CONTRIBUTING.md](../CONTRIBUTING.md) and [CHANGELOG.md](../CHANGELOG.md).

## Operations

| Document | Purpose |
| --- | --- |
| [production-operations.md](production-operations.md) | Processes, cadences, failure behaviour, deployment, private records and retention |
| [cloudflare.md](cloudflare.md) | Running on SkipperCast's own Cloudflare account: Worker, D1, R2, watchdog, deploy, cost |
| [data-feed-readme.md](data-feed-readme.md) | README published on the `data` feed branch |

## Legal

| Document | Purpose |
| --- | --- |
| [data-sources.md](data-sources.md) | Licences and reuse terms per source (also listed above) |

Also: [LICENSE](../LICENSE) and [NOTICE.md](../NOTICE.md) (attributions and third-party terms).

## Pending in open pull requests

Not yet on `main`, so listed as paths rather than links:

- Engineering: `docs/engineering/api-reference.md` and `docs/engineering/testing.md` (PR #52); `docs/engineering/adr/` with ADR 0001 (record decisions) and 0004 (licensing) (PR #39).
- Operations: `docs/operations/incident-response.md` and runbooks `feed-stale`, `r2-outage`, `d1-restore`, `secrets-rotation` in `docs/operations/runbooks/` (PR #46); `rollback-release` runbook (PR #26); `docs/operations/release-process.md` (PR #44).
- Legal: `docs/legal/threat-model.md` (PR #52); `docs/legal/data-rights-register.md` and `docs/legal/README.md` (PR #33); `docs/legal/disclaimers.md` (PR #36).

## Research log (to be archived)

Dated records. Read them for the evidence behind a decision; check the product documents above for current behaviour.

**Regional rollouts and previews**

| Document | Purpose |
| --- | --- |
| [big-sur-rollout.md](big-sur-rollout.md) | Big Sur outer-coast limited preview |
| [south-big-sur-san-simeon-rollout.md](south-big-sur-san-simeon-rollout.md) | South Big Sur–San Simeon preview |
| [monterey-point-sur-rollout.md](monterey-point-sur-rollout.md) | Monterey Peninsula–Point Sur preview |
| [santa-cruz-monterey-bay-rollout.md](santa-cruz-monterey-bay-rollout.md) | Pigeon Point–Monterey Bay preview |
| [point-reyes-pigeon-rollout.md](point-reyes-pigeon-rollout.md) | Point Reyes–Pigeon Point source-review preview |
| [bodega-point-reyes-rollout.md](bodega-point-reyes-rollout.md) | Bodega Bay–Point Reyes preview |
| [point-arena-bodega-rollout.md](point-arena-bodega-rollout.md) | Point Arena–northern Sonoma preview |
| [mendocino-rollout.md](mendocino-rollout.md) | Fort Bragg–Point Arena rollout ledger |
| [shelter-cove-north-mendocino-rollout.md](shelter-cove-north-mendocino-rollout.md) | Shelter Cove–Fort Bragg preview |
| [northern-crescent-city-rollout.md](northern-crescent-city-rollout.md) | Crescent City / Del Norte preview |
| [san-francisco-expansion.md](san-francisco-expansion.md) | San Francisco outer-coast rollout record |
| [southern-california.md](southern-california.md) | Southern California package rollout |
| [statewide-buildout.md](statewide-buildout.md) | Statewide buildout ledger and map-area acquisition queue |

**Central Coast 300 ft evidence program**

| Document | Purpose |
| --- | --- |
| [central-coast-coverage-and-accuracy.md](central-coast-coverage-and-accuracy.md) | Coverage and accuracy program for Monterey–Point Conception; the withdrawn Morro–Avila qualification |
| [central-coast-300ft-review.md](central-coast-300ft-review.md) | 300 ft source and ranking review |
| [central-300ft-source-gap-strategy.md](central-300ft-source-gap-strategy.md) | Closing the 300 ft evidence gaps, survey by survey |
| [central-coast-data-acquisition-strategy.md](central-coast-data-acquisition-strategy.md) | Data acquisition and spot-quality strategy |
| [central-biological-evidence-and-gaps.md](central-biological-evidence-and-gaps.md) | Biological evidence and validation plan |
| [central-coast-habitat-context.md](central-coast-habitat-context.md) | Research-only reef context layer for five preview regions |

**Habitat source reviews**

| Document | Purpose |
| --- | --- |
| [island-target-quality.md](island-target-quality.md) | The 11 survey-qualified Channel Islands targets and their gates |
| [southern-habitat-sources.md](southern-habitat-sources.md) | Channel Islands habitat release: mapped footprints and gaps |
| [san-pedro-original-source-review.md](san-pedro-original-source-review.md) | San Pedro Shelf original habitat review |

**Source requests (prepared, not sent)**

| Document | Purpose |
| --- | --- |
| [cdfw-rov-original-data-request.md](cdfw-rov-original-data-request.md) | CDFW/MARE ROV data request |
| [estero-2012-source-request.md](estero-2012-source-request.md) | Estero Bay 2012 original-survey records |
| [lopez-point-source-request.md](lopez-point-source-request.md) | Lopez Point 2010 source package |
| [monterey-2009-processing-source-request.md](monterey-2009-processing-source-request.md) | Monterey 2009 original survey processing |
| [monterey-2013-merge-source-request.md](monterey-2013-merge-source-request.md) | Monterey 300 ft original-source request |
| [point-buchon-source-request.md](point-buchon-source-request.md) | Point Buchon survey records |
| [point-conception-source-request.md](point-conception-source-request.md) | Point Conception 200–300 ft sources |

**Dated research and reviews**

| Document | Purpose |
| --- | --- |
| [current-data-research.md](current-data-research.md) | Nearshore current data availability, Avila–Cambria (September 21) |
| [commercial-ais-research.md](commercial-ais-research.md) | Local charter and commercial AIS follow-up (September 21) |
| [product-research.md](product-research.md) | Feature research across 13 products (September 21) |
| [implementation-2026-09.md](implementation-2026-09.md) | Regional intelligence release ledger (September 2026) |
| [research-validation.md](research-validation.md) | Regional rollout validation (September 21) |
| [mobile-review.md](mobile-review.md) | Mobile readability review (September 22): tested viewports, flows and fixes |
| [system-overview.md](system-overview.md) | Early design snapshot, superseded by [architecture.md](architecture.md) |

## Keeping this index current

Add a line here when you add a document, and move a document to the research log when it stops describing current behaviour. The guide's target (P5-01) is at most 20 living documents outside the research archive; there are 42 today, including this index, so the product and methods groups above also need consolidation.
