# SkipperCast documentation

Every document in `docs/` outside `archive/` and `images/`, grouped by who it is for. Each one is linked from this page or from a folder index this page links ([ADRs](engineering/adr/README.md), [Text Advisor plan](plans/text-advisor/README.md), [charter fleet plan](plans/charter-fleet/README.md), [front-end plan](plans/front-end/README.md), [audit](audit/README.md), [legal](legal/README.md), [research](research/README.md)). Supporting files such as screenshots, JSON and logs are not listed separately. Start with the [architecture](architecture.md) for how the system fits together, or the [web app guide](web-app.md) for what it does.

Dated audit, rollout, source-request and review records live in [archive/](archive/README.md). They are the evidence trail behind coverage decisions, not descriptions of current product behaviour, and nothing in them is a product claim on its own. When a living document needs one of their conclusions, it states the conclusion itself and links the log as evidence. [research/](research/README.md) indexes the Hermes feature-research package (specs, inspiration, competitors, ingest guides) and the Morro Bay tuna method note.

## Product: what the app does

| Document | Purpose |
| --- | --- |
| [web-app.md](web-app.md) | The app's two pages (landing at `/`, map app at `/map`), its five views (Coast, Conditions, History, Fleet, Reports), what works, evidence limits and source layout |
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
| [conditions-model.md](conditions-model.md) | The one conditions model (`web/score.ts`): the graded score, the window rule, and where they differ |
| [forecast-workflow.md](forecast-workflow.md) | Operator or agent review from forecast evidence to an assessment |
| [species-search-plans.md](species-search-plans.md) | Per-species map shortlists and how they are built |
| [fishing-strategies.md](fishing-strategies.md) | Reviewed starter methods for each target species |
| [charter-grounds.md](charter-grounds.md) | Charter-reported fishing grounds (purple labels) and their limits |
| [seabed-views.md](seabed-views.md) | Measured bottom relief and depth views for reef targets |
| [chartplotter-export.md](chartplotter-export.md) | Exporting a GPX day plan and offline notes |
| [inavx.md](inavx.md) | Importing a day plan into iNavX |
| [product/ranked-reef-export.md](product/ranked-reef-export.md) | Ranked reef day plans: **Best available** in Export, its trip filters and limits |
| [i18n-glossary.md](i18n-glossary.md) | Contributor guidance: one Spanish rendering for each recurring caveat (not legal text or a translation engine) |

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
| [land-water-method.md](land-water-method.md) | Land/water check for ranked places, built from the CUSP shoreline (CI6-01B step 0: approved in round 2 and implemented) |
| [seafloor.md](seafloor.md) | The seafloor pipeline: original surveys to graded, legally screened habitat tiles |
| [california-seabed-coverage.md](california-seabed-coverage.md) | Statewide seabed coverage and the gate for promoting an area to fishing targets |
| [data-quality-rollout.md](data-quality-rollout.md) | Quality gates from regional evidence to a published coastal map |
| [species-research.md](species-research.md) | Central Coast species, sea state and search-area research (September 21 review) |
| [evidence-ladder.md](evidence-ladder.md) | The fixed evidence ladder for any statement that a charter boat spent time somewhere |
| [seafloor-ec.md](seafloor-ec.md) | Seafloor error correction (EC): the shared contract every EC tool imports |
| [coast-rights-coverage.md](coast-rights-coverage.md) | Offline check that every coast recipe source has rights coverage (coverage only, not legal permission) |

## Engineering

| Document | Purpose |
| --- | --- |
| [architecture.md](architecture.md) | Current system context, containers, components, hosting and scheduled jobs |
| [region-pipeline.md](region-pipeline.md) | Region rollout and the full data flow |
| [regions.md](regions.md) | How to add a coastline: contracts, sources, compiler and checks |
| [data-contracts.md](data-contracts.md) | Data needs, source bindings and feed contracts |
| [social-preview-image-sources.md](social-preview-image-sources.md) | Provenance of the social preview image (prompt in `social-preview-prompt.txt`) |
| [engineering/api-reference.md](engineering/api-reference.md) | Every HTTP route the Worker answers, with examples |
| [engineering/telemetry.md](engineering/telemetry.md) | Client funnel events and error reports: what is sent, when nothing is, retention |
| [engineering/testing.md](engineering/testing.md) | Test layers, what each covers and how to add a fixture |
| [engineering/subsystem-retirement.md](engineering/subsystem-retirement.md) | 19-01 candidate-only ownership, migration hashes and held runtime facts |
| [engineering/e2e-quarantine.md](engineering/e2e-quarantine.md) | Bounded browser-test quarantine (SC-CI-3): retries, never skips |
| [perf/tile-cost.md](perf/tile-cost.md) | Opt-in Playwright audit of requests and bytes per app view (no budget gate) |
| [coastal-service.md](coastal-service.md) | Coastal data service during the Fish merge: retired habitat paths (HTTP 410) and what is unchanged |
| [coastal-live-discovery.md](coastal-live-discovery.md) | Governed live coastal discovery: one bounded attempt, frozen into a discovery catalog |
| [coastal-catalog-bridge.md](coastal-catalog-bridge.md) | Bridge from a frozen discovery catalog to the coordinator's acquire stage |
| [coastal-discovery-intake.md](coastal-discovery-intake.md) | Held intake for metadata leads that cannot meet the strict 2 m BAG inventory contract (proposal; admits no execution) |
| [seafloor-second-scope.md](seafloor-second-scope.md) | Tooling for a private, physical-only second seafloor scope (no scope is approved) |
| [engineering/native-terrain-support.md](engineering/native-terrain-support.md) | Optional positive-support gate for original depth grids with documented vessel-heave artifacts |
| [engineering/classified-geometry.md](engineering/classified-geometry.md) | Classified habitat map representation: native polygons kept across map representations |
| [engineering/bedrock-canonical-exclusion.md](engineering/bedrock-canonical-exclusion.md) | Opt-in canonical occupied exclusion for original interpreted bedrock |
| [engineering/seafloor-numeric-cache.md](engineering/seafloor-numeric-cache.md) | Stable seafloor measurement encoding for reach input hashes |
| [engineering/adr/](engineering/adr/README.md) | Architecture decision records |
| [plans/text-advisor/](plans/text-advisor/README.md) | Build plan for the Text Advisor (iMessage/SMS fishing advisor, skipper intake, social pipeline, admin): decisions, architecture, data model, task breakdown |
| [plans/charter-fleet/](plans/charter-fleet/README.md) | Charter fleet registry and AIS activity map plan: user stories, design, development plan, open questions and the run graph |
| [plans/charter-fleet/references/classification.md](plans/charter-fleet/references/classification.md) | Fleet activity classification: rules, thresholds and sources |
| [plans/front-end/](plans/front-end/README.md) | Front-end rebuild and the `fish` merge plan: user stories, design, development plan and open questions |
| [plans/pelagic-context/design.md](plans/pelagic-context/design.md) | Design only: per-species pelagic context that follows the selected hour, with no score, and the validation test any search priority must pass first |
| [plans/offline-ocean-coverage.md](plans/offline-ocean-coverage.md) | Proposal: explicit SST/current coverage in offline chart packs (caps, partial-coverage metadata, age/hash gates, tests); regional tiles kept apart from coastal snapshots |
| [research/](research/README.md) | Feature research for Hermes: build specs and recommended order, map inspiration, competitor notes and ingest guides. Start at [research/specs/README.md](research/specs/README.md) |

Also for engineers: [AGENTS.md](../AGENTS.md) (branch, PR and rebuild rules), [CONTRIBUTING.md](../CONTRIBUTING.md) and [CHANGELOG.md](../CHANGELOG.md).

### Contract notes

One page per guarded behaviour in the coast tools and the fleet and advisor code.

| Document | Purpose |
| --- | --- |
| [engineering/sc32_bridge_bounds.md](engineering/sc32_bridge_bounds.md) | SC32-BRIDGE-BOUNDS: malformed geographic boxes never plan a coast catalog bridge |
| [engineering/sc34_terrain_json.md](engineering/sc34_terrain_json.md) | SC34: strict JSON in the terrain CLI metadata reader |
| [engineering/sc38_prefetch_version.md](engineering/sc38_prefetch_version.md) | SC38: integer `schema_version` for coast prefetch plans |
| [engineering/sc_cache_clock.md](engineering/sc_cache_clock.md) | SC-CACHE-CLOCK: explicit, host-independent cached evidence times |
| [engineering/sc_catalog_rows.md](engineering/sc_catalog_rows.md) | SC-CATALOG-ROWS: unique literal candidate identities in frozen catalog diffs |
| [engineering/sc_metadata_object.md](engineering/sc_metadata_object.md) | SC-METADATA-OBJECT: cached metadata must be a JSON object |
| [engineering/sc_png_dtype.md](engineering/sc_png_dtype.md) | SC-PNG-DTYPE: the coastal preview PNG accepts uint8 input only |
| [engineering/sc_recipe_offline.md](engineering/sc_recipe_offline.md) | SC-RECIPE-OFFLINE: offline coast recipe schema references |
| [engineering/sc_rights_delta.md](engineering/sc_rights_delta.md) | SC-RIGHTS-DELTA: compare two frozen rights observations |
| [engineering/sc_sample_audit.md](engineering/sc_sample_audit.md) | SC-SAMPLE-AUDIT: coast sample composition report |
| [engineering/sc_schema_closure.md](engineering/sc_schema_closure.md) | SC-SCHEMA-CLOSURE: static JSON Schema dependency closure |
| [engineering/sc_segment_delta.md](engineering/sc_segment_delta.md) | SC-SEGMENT-DELTA: explain two frozen segment receipts |
| [engineering/sp1301_event_segment.md](engineering/sp1301_event_segment.md) | SP1301-EVENT-SEGMENT: an event's segment must belong to the event's own trip |
| [engineering/sp1510_classifier_identity.md](engineering/sp1510_classifier_identity.md) | Classifier identity v3 (SP-15-v1 / SP1510-CLASSIFIER-IDENTITY) |
| [engineering/sp1602_report_unknown_counts.md](engineering/sp1602_report_unknown_counts.md) | Advisor count display semantics (SP1602) |
| [engineering/sp1603_fleet_identity_diagnostic.md](engineering/sp1603_fleet_identity_diagnostic.md) | Fleet identity byte diagnostic (SP-16-v1) |

### Research build specs

[research/specs/README.md](research/specs/README.md) gives the build order and dependencies. Each spec has a concatenated file generated from its directory's `spec.md`, `plan.md` and `tasks.md`; edit the directory files.

| Spec | Files |
| --- | --- |
| [01 · Full point readout and adjustable colour ranges](research/specs/01-point-readout-and-ramps.md) | [spec](research/specs/01-point-readout-and-ramps/spec.md), [plan](research/specs/01-point-readout-and-ramps/plan.md), [tasks](research/specs/01-point-readout-and-ramps/tasks.md) |
| [02 · Look-back playback for observed ocean layers](research/specs/02-observed-lookback.md) | [spec](research/specs/02-observed-lookback/spec.md), [plan](research/specs/02-observed-lookback/plan.md), [tasks](research/specs/02-observed-lookback/tasks.md) |
| [03 · Water-condition alerts on saved spots, and new-data alerts](research/specs/03-spot-water-alerts.md) | [spec](research/specs/03-spot-water-alerts/spec.md), [plan](research/specs/03-spot-water-alerts/plan.md), [tasks](research/specs/03-spot-water-alerts/tasks.md) |
| [04 · Heading-aware comfort and calibration from comfort reports](research/specs/04-heading-aware-comfort.md) | [spec](research/specs/04-heading-aware-comfort/spec.md), [plan](research/specs/04-heading-aware-comfort/plan.md), [tasks](research/specs/04-heading-aware-comfort/tasks.md) |
| [05 · Chlorophyll edges, eddies and sea-surface height](research/specs/05-chlorophyll-edges-eddies-ssh.md) | [spec](research/specs/05-chlorophyll-edges-eddies-ssh/spec.md), [plan](research/specs/05-chlorophyll-edges-eddies-ssh/plan.md), [tasks](research/specs/05-chlorophyll-edges-eddies-ssh/tasks.md) |
| [06 · Conditions recorded with each catch-log entry](research/specs/06-catch-conditions.md) | [spec](research/specs/06-catch-conditions/spec.md), [plan](research/specs/06-catch-conditions/plan.md), [tasks](research/specs/06-catch-conditions/tasks.md) |
| [07 · Subsurface depth ladder](research/specs/07-subsurface-depth-ladder.md) | [spec](research/specs/07-subsurface-depth-ladder/spec.md), [plan](research/specs/07-subsurface-depth-ladder/plan.md), [tasks](research/specs/07-subsurface-depth-ladder/tasks.md) |
| [08 · GPX import into saved spots, and an optional fuel estimate](research/specs/08-gpx-import-and-fuel.md) | [spec](research/specs/08-gpx-import-and-fuel/spec.md), [plan](research/specs/08-gpx-import-and-fuel/plan.md), [tasks](research/specs/08-gpx-import-and-fuel/tasks.md) |
| [09 · Launch the built Text Advisor](research/specs/09-text-advisor-launch.md) | [spec](research/specs/09-text-advisor-launch/spec.md), [plan](research/specs/09-text-advisor-launch/plan.md), [tasks](research/specs/09-text-advisor-launch/tasks.md) |
| [10 · Coverage and distribution](research/specs/10-coverage-and-distribution.md) | [spec](research/specs/10-coverage-and-distribution/spec.md), [plan](research/specs/10-coverage-and-distribution/plan.md), [tasks](research/specs/10-coverage-and-distribution/tasks.md) |

## Operations

| Document | Purpose |
| --- | --- |
| [production-operations.md](production-operations.md) | Processes, cadences, failure behaviour, deployment, private records and retention |
| [cloudflare.md](cloudflare.md) | Running on SkipperCast's own Cloudflare account: Worker, D1, R2, watchdog, deploy, cost |
| [data-feed-readme.md](data-feed-readme.md) | README published on the `data` feed branch |
| [operations/release-process.md](operations/release-process.md) | Versions, tags, changelog and deploying a release |
| [operations/incident-response.md](operations/incident-response.md) | Severity levels, who acts, and postmortems |
| [operations/runners.md](operations/runners.md) | GitHub Actions job inventory for capacity planning: public hosted jobs versus private fleet jobs and their runner assignments (old cost figures are historical assumptions) |
| [operations/cost-ceiling.md](operations/cost-ceiling.md) | The Worker's daily R2 read ceiling and per-caller limits, and what the site serves past them |
| [operations/perf-budget.md](operations/perf-budget.md) | Size budget: the pull request check on first-load and brief data file sizes |
| [operations/station-failover.md](operations/station-failover.md) | Ordered station priorities per role in `region.json` |
| [operations/basemap-detail.md](operations/basemap-detail.md) | Trinidad–Klamath basemap detail box and zooms (R4-SC-12) |
| [operations/coast-prefetch.md](operations/coast-prefetch.md) | Coast campaign raw prefetch runbook (its generated seed is marked incomplete; read the status first) |
| [operations/coast-statewide-runsheet.md](operations/coast-statewide-runsheet.md) | Statewide coast recipe runsheet (OC-STATE): preparation only, not a run or approval |
| [operations/runbooks/](operations/runbooks/) | [Feed stale](operations/runbooks/feed-stale.md), [rollback a release](operations/runbooks/rollback-release.md), [D1 restore](operations/runbooks/d1-restore.md), [R2 outage](operations/runbooks/r2-outage.md), [secrets rotation](operations/runbooks/secrets-rotation.md), [advisor relay setup](operations/runbooks/advisor-relay-setup.md), [advisor relay down](operations/runbooks/advisor-relay-down.md), [advisor port to Twilio](operations/runbooks/advisor-port-to-twilio.md), [advisor Meta App Review](operations/runbooks/advisor-meta-app-review.md), [advisor queue stuck](operations/runbooks/advisor-queue-stuck.md), [fleet registry run](operations/runbooks/fleet-registry.md), [fleet OSINT run](operations/runbooks/fleet-osint.md), [fleet public heat map go-live](operations/runbooks/fleet-public-heat.md), [fleet labelling](operations/runbooks/fleet-labelling.md), [fleet AIS listener down](operations/runbooks/fleet-ais-down.md), [Morro Bay AIS receiver](operations/runbooks/fleet-ais-receiver.md), [fleet schedule evidence](operations/runbooks/fleet-schedule-evidence.md), [coherent R2 feed publication](operations/runbooks/r2-snapshots.md), [region promotion check](operations/runbooks/region-promotion.md), [relief rollback](operations/runbooks/relief-rollback.md), [research-daily ENC unavailable](operations/runbooks/research-daily-enc-unavailable.md), [saved-trip alerts late](operations/runbooks/trip-checks.md) |

## Legal

| Document | Purpose |
| --- | --- |
| [legal/README.md](legal/README.md) | Index of the legal and commercial working documents |
| [legal/data-rights-register.md](legal/data-rights-register.md) | Whether a paid SkipperCast may use each dataset and service |
| [legal/disclaimers.md](legal/disclaimers.md) | The canonical user-facing caveats |
| [legal/threat-model.md](legal/threat-model.md) | STRIDE review of the Worker, D1, feeds and job auth |
| [data-sources.md](data-sources.md) | Licences and reuse terms per source (also listed above) |

Also: [LICENSE](../LICENSE) and [NOTICE.md](../NOTICE.md) (attributions and third-party terms).

## Reference: dated plans, audits and diagnostics

Reports, receipts, plans and diagnostics that record what was true at the commit or date each one names. None describes current behaviour on its own, and none is an approval or release decision.

| Document | Purpose |
| --- | --- |
| [coast-capabilities-status.md](coast-capabilities-status.md) | Captain feature status, pinned to the commit it names |
| [FISH-MERGE-STATUS.md](FISH-MERGE-STATUS.md) | Fish → SkipperCast integration: the merge goal and its status record |
| [FISH-MERGE-REVIEW.md](FISH-MERGE-REVIEW.md) | FishReport merge inventory and independent review (October 6 source inspection) |
| [plans/fish-bridge-retirement.md](plans/fish-bridge-retirement.md) | Fish bridge retirement: remaining dependencies (report-only plan, SCBB-06) |
| [plans/second-active-region.md](plans/second-active-region.md) | Second active region: criteria, Morro Bay assessment and a costed plan (SC-LAUNCH-7 decision document) |
| [plans/santa-cruz-monterey-bay-hold.md](plans/santa-cruz-monterey-bay-hold.md) | Santa Cruz-Monterey Bay held habitat: per-reach hold report (releases nothing) |
| [scb-07-c-manifest-probe.md](scb-07-c-manifest-probe.md) | SCB-07-C: read-only regional control probe (2026-11-14) |
| [seafloor-bluetopo-scheme-repin.md](seafloor-bluetopo-scheme-repin.md) | BlueTopo tile scheme re-pin to the 2026-11-09 scheme object |
| [seafloor-source-review-digital-coast.md](seafloor-source-review-digital-coast.md) | Source review of NOAA Digital Coast DEM datasets as reviewed original URLs (written as a proposal pending independent review) |
| [diagnostics/SC0922-05.md](diagnostics/SC0922-05.md) | SC0922-05: first-run brief timeouts on the `e2e (2)` laptop shard |
| [showcase/showcase-2026-10-31.html](showcase/showcase-2026-10-31.html) | SkipperCast: what changed on screen, 2026-10-31 (before/after gallery) |
| [audit/](audit/README.md) | Cross-repository audit start page: ownership and path reservations, issue packets and the status index |
| [audit/SC-11-browser-2m-scope.md](audit/SC-11-browser-2m-scope.md) | SC-11: 2 m selected-copy browser acceptance (not demonstrated; why it is out of scope) |
| [engineering/audits/coastal-snapshot-2026-10-20.md](engineering/audits/coastal-snapshot-2026-10-20.md) | SC-4: coastal snapshot port-or-retire inventory |
| [engineering/audits/coastal-receipt-erratum-20261020.md](engineering/audits/coastal-receipt-erratum-20261020.md) | Erratum: two retained-byte figures in the 2026-10-20 four128 rerun receipts |
| [engineering/audits/coast-pilot-b3-root-gaps.md](engineering/audits/coast-pilot-b3-root-gaps.md) | COAST / PILOT / B3 original-root evidence gaps |
| [engineering/audits/coast-prod-window-crosswalk.md](engineering/audits/coast-prod-window-crosswalk.md) | COAST-PROD identifiers and saved-area window crosswalk |
| [engineering/audits/coast-prod-window-receipt.md](engineering/audits/coast-prod-window-receipt.md) | AUDINV-FIX-111 bounded implementation receipt |
| [engineering/audits/four-sector-fetch-ready-receipt.md](engineering/audits/four-sector-fetch-ready-receipt.md) | Four-sector PSIX fetch: offline retry-readiness receipt (AUDINV-FIX-115) |
| [engineering/audits/live-hole-preservation-gap.md](engineering/audits/live-hole-preservation-gap.md) | Live hole and disjoint-core preservation: retained evidence gap |
| [engineering/audits/local-merge-queue-feasibility.md](engineering/audits/local-merge-queue-feasibility.md) | Local merge-queue feasibility (AUDINV-CIW-67) |
| [engineering/audits/morro-bay-readiness-gap.md](engineering/audits/morro-bay-readiness-gap.md) | Morro Bay bathymetry readiness gap (AUDINV-OLD-21) |
| [engineering/audits/prepare-assembly-receipt.md](engineering/audits/prepare-assembly-receipt.md) | Prepare-to-assembly regression receipt (AUDINV-FIX-056) |
| [engineering/audits/python-pr-matrix-policy-gap.md](engineering/audits/python-pr-matrix-policy-gap.md) | CIW-56 policy-gap report: Python PR matrix and advisory audit |
| [engineering/audits/registry-discovery-receipt.md](engineering/audits/registry-discovery-receipt.md) | Registry and shared-fixture discovery receipt |
| [engineering/audits/remaining-dossier-archival-consumer-gap.md](engineering/audits/remaining-dossier-archival-consumer-gap.md) | OLD-07: remaining dossier archival and consumer gap |
| [engineering/audits/rollup-gate-receipt.md](engineering/audits/rollup-gate-receipt.md) | survey-science roll-up gate receipt (AUDINV-CIW-04) |
| [engineering/audits/run218-receipt-locator.md](engineering/audits/run218-receipt-locator.md) | Run218 receipt and preview locator (AUDINV-FIX-125) |
| [engineering/audits/skippercast-layer-rail-policy-proposal.md](engineering/audits/skippercast-layer-rail-policy-proposal.md) | Layer-rail ownership and dependency-only lockfile policy: proposal (AUDINV-CIW-75) |
| [engineering/audits/standing-e2e-diagnosis.md](engineering/audits/standing-e2e-diagnosis.md) | Standing e2e diagnosis (AUDINV-CIW-19) |
| [engineering/audits/t08-admission-gap.md](engineering/audits/t08-admission-gap.md) | T08 admission gap report (AUDINV-FIX-059) |

## Archive

[archive/README.md](archive/README.md) lists the archived records: regional rollouts, the Central Coast 300 ft evidence program, habitat source reviews, prepared source requests, and dated research, reviews and experiments.

## Keeping this index current

Add a line here, or in the folder index this page links for that folder, when you add a document. When a document stops describing current behaviour, `git mv` it into `archive/`, list it in [archive/README.md](archive/README.md) and fix links (`python scripts/check_repository.py` fails on broken ones). The guide's target (P5-01) is at most 20 living documents; the product and methods groups above still need consolidation to get there.
