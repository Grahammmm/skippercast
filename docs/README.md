# SkipperCast documentation

Every document in `docs/`, grouped by who it is for. Start with the [architecture](architecture.md) for how the system fits together, or the [web app guide](web-app.md) for what it does.

Dated audit, rollout, source-request and review records live in [archive/](archive/README.md). They are the evidence trail behind coverage decisions, not descriptions of current product behaviour, and nothing in them is a product claim on its own. When a living document needs one of their conclusions, it states the conclusion itself and links the log as evidence. [research/morro-bay-tuna.md](research/morro-bay-tuna.md) is a dated method note for the Morro Bay tuna search overlay.

## Product: what the app does

| Document | Purpose |
| --- | --- |
| [web-app.md](web-app.md) | The app's views (Map, Conditions, Export, Guide), what works, evidence limits and source layout |
| [quickstart.md](quickstart.md) | First steps: use the atlas on a chartplotter, or run the Python tools |
| [roadmap.md](roadmap.md) | Shipped functionality versus future work |
| [coastal-directory.md](coastal-directory.md) | The five CDFW coastal regions, the region selector and seasonal species |
| [platform.md](platform.md) | How one shared app serves many reviewed regional packages |
| [live-conditions.md](live-conditions.md) | Live observations: buoys, weather stations, water level; also published as the `conditions` branch README |
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
| [product/data-confidence.md](product/data-confidence.md) | **Start here for trust:** grades, coverage states, freshness, depth datums and withdrawn claims |
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

## Engineering

| Document | Purpose |
| --- | --- |
| [architecture.md](architecture.md) | Current system context, containers, components, hosting and scheduled jobs |
| [region-pipeline.md](region-pipeline.md) | Region rollout and the full data flow |
| [regions.md](regions.md) | How to add a coastline: contracts, sources, compiler and checks |
| [data-contracts.md](data-contracts.md) | Data needs, source bindings and feed contracts |
| [monitor-reference.md](monitor-reference.md) | The legacy Morro Bay forecast collector and alert lifecycle |
| [social-preview-image-sources.md](social-preview-image-sources.md) | Provenance of the social preview image (prompt in `social-preview-prompt.txt`) |

| [engineering/api-reference.md](engineering/api-reference.md) | Every HTTP route the Worker answers, with examples |
| [engineering/testing.md](engineering/testing.md) | Test layers, what each covers and how to add a fixture |
| [engineering/adr/](engineering/adr/README.md) | Architecture decision records |

Also for engineers: [AGENTS.md](../AGENTS.md) (branch, PR and rebuild rules), [CONTRIBUTING.md](../CONTRIBUTING.md) and [CHANGELOG.md](../CHANGELOG.md).

## Operations

| Document | Purpose |
| --- | --- |
| [production-operations.md](production-operations.md) | Processes, cadences, failure behaviour, deployment, private records and retention |
| [cloudflare.md](cloudflare.md) | Running on SkipperCast's own Cloudflare account: Worker, D1, R2, watchdog, deploy, cost |
| [data-feed-readme.md](data-feed-readme.md) | README published on the `data` feed branch |
| [operations/release-process.md](operations/release-process.md) | Versions, tags, changelog and deploying a release |
| [operations/incident-response.md](operations/incident-response.md) | Severity levels, who acts, and postmortems |
| [operations/runbooks/](operations/runbooks/) | [Feed stale](operations/runbooks/feed-stale.md), [rollback a release](operations/runbooks/rollback-release.md), [D1 restore](operations/runbooks/d1-restore.md), [R2 outage](operations/runbooks/r2-outage.md), [secrets rotation](operations/runbooks/secrets-rotation.md) |

## Legal

| Document | Purpose |
| --- | --- |
| [legal/README.md](legal/README.md) | Index of the legal and commercial working documents |
| [legal/data-rights-register.md](legal/data-rights-register.md) | Whether a paid SkipperCast may use each dataset and service |
| [legal/disclaimers.md](legal/disclaimers.md) | The canonical user-facing caveats |
| [legal/threat-model.md](legal/threat-model.md) | STRIDE review of the Worker, D1, feeds and job auth |
| [data-sources.md](data-sources.md) | Licences and reuse terms per source (also listed above) |

Also: [LICENSE](../LICENSE) and [NOTICE.md](../NOTICE.md) (attributions and third-party terms).

## Archive

[archive/README.md](archive/README.md) lists the 39 archived research logs: regional rollouts, the Central Coast 300 ft evidence program, habitat source reviews, prepared source requests, and dated research, reviews and experiments.

## Keeping this index current

Add a line here when you add a document. When a document stops describing current behaviour, `git mv` it into `archive/`, list it in [archive/README.md](archive/README.md) and fix links (`python scripts/check_repository.py` fails on broken ones). The guide's target (P5-01) is at most 20 living documents; the product and methods groups above still need consolidation to get there.
