# Documentation index drift

| Check | Finding |
| --- | --- |
| R1. Missing direct links | **220 of 291 tracked files** in scope: **180 Markdown files** (including the index itself), **1 HTML document** and **39 supporting files**. |
| R2. Broken links | **0 missing targets** across 84 link occurrences; **0 fragment links** to check. |
| R3. Stale descriptions | Three clear row mismatches: web app views, land/water implementation status and runner coverage. The archive count is stale too. |
| R4. Proposed rows | 180 draft rows for the other unlinked reading documents. One optional index-only follow-up; no code change proposed. |

Snapshot: locally staged `origin/main` at `26aa28ab1ce4e883c0850cdb7f1243c4ed48c07e` (commit time 2026-11-21 09:11:29 PST). Read offline on 2026-11-21; no live site or GitHub link checks. All source line references are at that snapshot.

## R1. Files the index does not link

`docs/README.md:3` says “Every document in `docs/`, grouped by who it is for.” This is a direct-link inventory, not a judgment that a file is undiscoverable. An index link to a directory or to a child README is not a direct link to the files inside it. For example, the index links the ADR, Text Advisor and research indexes (`docs/README.md:63–67`), and those indexes link onward (`docs/engineering/adr/README.md:3`, `docs/plans/text-advisor/README.md:3–8`, `docs/research/README.md:3`). The index itself is included in the count because it does not self-link.

Reproduce the inventory with `git ls-tree -r --name-only 26aa28ab1ce4e883c0850cdb7f1243c4ed48c07e -- docs` and the link list with `git show 26aa28ab1ce4e883c0850cdb7f1243c4ed48c07e:docs/README.md`. Exclude the `docs/archive/` and `docs/images/` prefixes from the file list, resolve link paths from `docs/`, then subtract the distinct file targets. The heading column cites the first Markdown heading (or first HTML heading); a dash means no document heading. For each path use `git log -1 --format='%cs %s' 26aa28ab1ce4e883c0850cdb7f1243c4ed48c07e -- <path>`: the date is the committer date of the latest Git change at that path, and the title is the commit subject. Dates are not document publication dates.

Dated scan output (2026-11-21):

```text
FILES 291; MARKDOWN 251; TOP-LEVEL MARKDOWN 55
UNLINKED 220: 180 .md, 1 .html, 19 .png, 15 .json, 2 .err, 1 .patch, 1 .tsv, 1 .txt
UNLINKED MARKDOWN: 16 top level, 67 research, 49 engineering, 27 plans,
                   14 operations, 4 audit, 1 diagnostics, 1 perf, 1 product
INDEX LINK OCCURRENCES 84; MISSING TARGETS 0; FRAGMENTS 0
ARCHIVE INDEX DISTINCT LINKS TO TRACKED ARCHIVE MARKDOWN 53
```

| File | First heading (line) | Last change (date · commit title) |
| --- | --- | --- |
| `docs/FISH-MERGE-REVIEW.md` | FishReport merge inventory and independent review (1) | 2026-10-11 · Remove the dead UI_V2 front-end switch configuration (#593) |
| `docs/FISH-MERGE-STATUS.md` | Fish → SkipperCast integration (1) | 2026-10-11 · Release v0.8.0: the new map is the default (#559) |
| `docs/README.md` | SkipperCast documentation (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/audit/ISSUE-PUBLICATION-PLAN.json` | — | 2026-10-18 · Add sanitized cross-repository audit contribution handoff |
| `docs/audit/OWNERSHIP.md` | Owners and path reservations (1) | 2026-10-18 · Add sanitized cross-repository audit contribution handoff |
| `docs/audit/README.md` | Audit collaboration start page (1) | 2026-10-18 · Add sanitized cross-repository audit contribution handoff |
| `docs/audit/SC-11-browser-2m-scope.md` | SC-11: 2 m selected-copy browser acceptance (1) | 2026-10-20 · Document the SC-11 selected-copy browser evidence gap (#750) |
| `docs/audit/packets/ENC-RECOVERY.md` | ENC recovery: current-base integration (1) | 2026-10-18 · Add sanitized cross-repository audit contribution handoff |
| `docs/audit/packets/enc-recovery.patch` | — | 2026-10-18 · Add sanitized cross-repository audit contribution handoff |
| `docs/audit/status-index.json` | — | 2026-10-18 · Reconcile the public audit release index and remaining work (#702) |
| `docs/coast-capabilities-status.md` | Captain feature status (3) | 2026-11-04 · [SC0452-12] Record existing contour tracks in captain feature status |
| `docs/coast-rights-coverage.md` | Recipe rights coverage (N3) (1) | 2026-11-12 · Delete 81 acceptance scripts no test uses, with their one-page docs |
| `docs/coastal-catalog-bridge.md` | Frozen catalog to coordinator acquire bridge (1) | 2026-11-19 · [SCA-358] Keep bridge continuation receipts within their own reader limit |
| `docs/coastal-discovery-intake.md` | Held coastal discovery intake (1) | 2026-10-19 · Retain heterogeneous coastal leads as held metadata (#725) |
| `docs/coastal-live-discovery.md` | Governed live coastal discovery (1) | 2026-10-20 · Read CRM netCDF in the bridge lane and keep THREDDS .nc links |
| `docs/coastal-service.md` | Coastal data service during the Fish merge (1) | 2026-11-14 · Use SkipperCast reef release and retire Fish habitat bridge |
| `docs/diagnostics/SC0922-05.md` | SC0922-05: first-run brief timeouts on `e2e (2)` laptop (1) | 2026-11-04 · [SC0922-05] Lift the mobile CPU throttle once the funnel budget is measured |
| `docs/engineering/adr/0001-record-architecture-decisions.md` | 0001. Record architecture decisions (1) | 2026-09-29 · Add licensing ADR and DCO sign-off check |
| `docs/engineering/adr/0002-own-forecast-tiles.md` | 0002. Build our own forecasts from NOAA and ECMWF open data (1) | 2026-09-29 · Add ADRs 0002, 0003, 0005 and 0006 |
| `docs/engineering/adr/0003-r2-system-of-record.md` | 0003. R2 is the feed system of record; git feed branches are single-commit mirrors (1) | 2026-11-12 · Document R2-only published feeds (SC2184-13) |
| `docs/engineering/adr/0004-licensing.md` | 0004. Licensing, copyright ownership and contributor terms (1) | 2026-09-29 · Add licensing ADR and DCO sign-off check |
| `docs/engineering/adr/0005-front-end-preact-vite-maplibre.md` | 0005. Front end: Preact and Vite, with MapLibre and PMTiles for the map (1) | 2026-10-05 · FE-01: UI_V2 flag, shell routing, ADR status (#355) |
| `docs/engineering/adr/0006-passkey-accounts-stripe-later.md` | 0006. SkipperCast accounts with passkeys now; Stripe billing later (1) | 2026-09-29 · Add ADRs 0002, 0003, 0005 and 0006 |
| `docs/engineering/adr/0007-text-advisor-channels-and-vision.md` | 0007. Text Advisor: an owned number with a self-hosted iMessage relay, Twilio as the fallback, and a two-provider vision chain (1) | 2026-10-03 · Add the Text Advisor build plan and ADR 0007 |
| `docs/engineering/adr/0008-charter-fleet-registry-and-ais.md` | 0008. Charter fleet: state-level region config, a headless OSINT step, raw AIS kept off D1, and aisstream behind a source adapter (1) | 2026-10-04 · CF-06: ADR 0008, data-rights rows, threat model, MarineCadastre terms (#295) |
| `docs/engineering/adr/0009-front-end-rebuild-and-fish-merge.md` | 0009. Front end: rebuild the shell on ADR 0005's stack behind a flag, self-host the basemap, and merge `fish` (1) | 2026-10-07 · Reconcile the front-end plan with the merged coast package (#414) |
| `docs/engineering/adr/0010-spot-alert-events.md` | 0010. Store spot-watch alert events separately (1) | 2026-11-20 · Record the spot-watch alert event storage decision |
| `docs/engineering/audits/coast-pilot-b3-root-gaps.md` | COAST / PILOT / B3 original-root evidence gaps (1) | 2026-11-15 · [AUDINV-FIX-205] Map COAST PILOT B3 root evidence gaps |
| `docs/engineering/audits/coast-prod-window-crosswalk.md` | COAST-PROD identifiers and saved-area window crosswalk (1) | 2026-11-15 · Add opt-in strict final-A grid compatibility and window crosswalk |
| `docs/engineering/audits/coast-prod-window-receipt.md` | AUDINV-FIX-111 bounded implementation receipt (1) | 2026-11-15 · Fix receipt paths rejected by repository checks |
| `docs/engineering/audits/coastal-receipt-erratum-20261020.md` | Erratum: two retained-byte figures in the 2026-10-20 four128 rerun receipts (1) | 2026-11-15 · Add coastal receipt erratum with both retained-byte figures |
| `docs/engineering/audits/coastal-snapshot-2026-10-20.json` | — | 2026-10-20 · Audit SC-4: classify snapshot-only coastal modules (#749) |
| `docs/engineering/audits/coastal-snapshot-2026-10-20.md` | SC-4: coastal snapshot port-or-retire inventory (1) | 2026-10-20 · Verify coastal snapshot handoffs against all test imports (#758) |
| `docs/engineering/audits/four-sector-fetch-ready-receipt.md` | Four-sector PSIX fetch: offline retry-readiness receipt (AUDINV-FIX-115) (1) | 2026-11-15 · Add offline four-sector PSIX retry-readiness receipt (live retry HOLD) |
| `docs/engineering/audits/live-hole-preservation-gap.md` | Live hole and disjoint-core preservation: retained evidence gap (1) | 2026-11-15 · Resolve gap-matrix citations to frozen source references |
| `docs/engineering/audits/local-merge-queue-feasibility.md` | Local merge-queue feasibility — AUDINV-CIW-67 (1) | 2026-11-15 · Use sanitized operator-local evidence locators |
| `docs/engineering/audits/morro-bay-readiness-gap.md` | Morro Bay bathymetry readiness gap — AUDINV-OLD-21 (1) | 2026-11-15 · docs: assess Morro Bay bathymetry readiness gaps |
| `docs/engineering/audits/prepare-assembly-receipt.md` | AUDINV-FIX-056 — prepare-to-assembly regression receipt (1) | 2026-11-19 · Add hermetic prepare-to-assembly regression test (AUDINV-FIX-056) |
| `docs/engineering/audits/python-pr-matrix-policy-gap.md` | CIW-56 policy-gap report: Python PR matrix and advisory audit (1) | 2026-11-15 · [AUDINV-CIW-56] Policy-gap report: audit already off PRs; retain 3.11+3.13 PR matrix |
| `docs/engineering/audits/registry-discovery-receipt.md` | Registry and shared-fixture discovery receipt (1) | 2026-11-15 · [AUDINV-CIW-76] Record combined discovery no-gap evidence |
| `docs/engineering/audits/remaining-dossier-archival-consumer-gap.md` | OLD-07 — remaining dossier archival / consumer gap (1) | 2026-11-15 · [AUDINV-OLD-07] Record remaining dossier archival evidence gaps |
| `docs/engineering/audits/rollup-gate-receipt.md` | survey-science roll-up gate receipt (AUDINV-CIW-04) (1) | 2026-11-15 · Document shallow-CI repair and frozen-source reproduction |
| `docs/engineering/audits/run218-receipt-locator.md` | Run218 receipt / preview locator (AUDINV-FIX-125) (1) | 2026-11-15 · Fix private home path in run218 locator report |
| `docs/engineering/audits/skippercast-layer-rail-policy-proposal.md` | Layer-rail ownership and dependency-only lockfile policy: proposal (AUDINV-CIW-75) (1) | 2026-11-15 · [AUDINV-CIW-75] Layer-rail ownership and lockfile policy proposal |
| `docs/engineering/audits/standing-e2e-diagnosis.md` | AUDINV-CIW-19 — Standing e2e diagnosis (1) | 2026-11-15 · Record restored retirement-history CI evidence for PR 2302 |
| `docs/engineering/audits/t08-admission-gap.md` | T08 admission gap report (AUDINV-FIX-059) (1) | 2026-11-15 · [AUDINV-FIX-059] T08 admission gap report: HOLD pending fresh owner admission |
| `docs/engineering/audits/thirteen-unit-disposition-gap.tsv` | — | 2026-11-15 · Add thirteen-unit disposition gap TSV (AUDINV-FIX-042) |
| `docs/engineering/bedrock-canonical-exclusion.md` | Opt-in canonical occupied exclusion for original interpreted bedrock (1) | 2026-10-06 · Add conservative canonical occupied bedrock exclusion (#383) |
| `docs/engineering/classified-geometry.md` | Classified habitat map representation (1) | 2026-10-04 · Preserve native classified geometry across map representations (#299) |
| `docs/engineering/e2e-quarantine.md` | Bounded browser-test quarantine (SC-CI-3) (1) | 2026-11-16 · [SCBB-10] Retire the Swell e2e quarantine row |
| `docs/engineering/native-terrain-support.md` | Reviewed native terrain support (1) | 2026-10-30 · Add native-grid preflight script (P4) |
| `docs/engineering/sc32_bridge_bounds.md` | SC32-BRIDGE-BOUNDS: malformed geographic boxes never plan a coast catalog bridge (1) | 2026-10-24 · fix(coastal): keep world-edge window footprints complete (SC32-BRIDGE-BOUNDS round 2) |
| `docs/engineering/sc34_terrain_json.md` | SC34: strict JSON in the terrain CLI metadata reader (1) | 2026-10-24 · Refuse ambiguous JSON in the terrain CLI metadata reader |
| `docs/engineering/sc38_prefetch_version.md` | SC38: integer schema_version for coast prefetch plans (1) | 2026-10-24 · SC38: stage prefetch paths before import and fail closed without pytest |
| `docs/engineering/sc_cache_clock.md` | SC-CACHE-CLOCK: explicit, host-independent cached evidence times (1) | 2026-11-12 · Re-point acceptance-script tests at product code; delete the scripts |
| `docs/engineering/sc_catalog_rows.md` | SC-CATALOG-ROWS: unique literal candidate identities in frozen catalog diffs (1) | 2026-10-25 · SC-CATALOG-ROWS: contain default tempfile root inside the acceptance run |
| `docs/engineering/sc_metadata_object.md` | SC-METADATA-OBJECT: cached metadata must be a JSON object (1) | 2026-10-24 · SC-METADATA-OBJECT: refuse nonobject cached metadata before caching |
| `docs/engineering/sc_png_dtype.md` | Coastal preview PNG: uint8-only input (SC-PNG-DTYPE) (1) | 2026-10-24 · Refuse non-uint8 pixel arrays before writing the fixed-format coastal preview PNG |
| `docs/engineering/sc_recipe_offline.md` | Offline coast recipe schema references (SC-RECIPE-OFFLINE) (1) | 2026-11-16 · Merge origin/main into rb/rf0410-4 |
| `docs/engineering/sc_rights_delta.md` | SC-RIGHTS-DELTA: compare two frozen rights observations (1) | 2026-11-12 · Re-point acceptance-script tests at product code; delete the scripts |
| `docs/engineering/sc_sample_audit.md` | Coast sample composition report (SC-SAMPLE-AUDIT) (1) | 2026-11-12 · Re-point acceptance-script tests at product code; delete the scripts |
| `docs/engineering/sc_schema_closure.md` | SC-SCHEMA-CLOSURE: static JSON Schema dependency closure (1) | 2026-11-12 · Re-point acceptance-script tests at product code; delete the scripts |
| `docs/engineering/sc_segment_delta.md` | SC-SEGMENT-DELTA: explain two frozen segment receipts (1) | 2026-11-12 · Re-point acceptance-script tests at product code; delete the scripts |
| `docs/engineering/seafloor-numeric-cache.md` | Stable seafloor measurement encoding (1) | 2026-10-01 · Migrate checked legacy numeric-only seafloor caches |
| `docs/engineering/sp1301_event_segment.md` | SP1301-EVENT-SEGMENT: an event's segment must belong to the event's own trip (1) | 2026-11-12 · Re-point acceptance-script tests at product code; delete the scripts |
| `docs/engineering/sp1510_classifier_identity.md` | Classifier identity v3 (SP-15-v1 / SP1510-CLASSIFIER-IDENTITY) (1) | 2026-11-12 · Re-point acceptance-script tests at product code; delete the scripts |
| `docs/engineering/sp1602_report_unknown_counts.md` | Advisor count display semantics (1) | 2026-11-11 · Point SP1602 note at direct regression commands |
| `docs/engineering/sp1603_fleet_identity_diagnostic.md` | Fleet identity byte diagnostic (SP-16-v1) (1) | 2026-11-18 · Require current fleet parity and retain the SP1603 baseline |
| `docs/engineering/subsystem-retirement.manifest.json` | — | 2026-11-15 · [AUDINV-SCA-22] Freeze 19-01 retirement ownership and hashes |
| `docs/evidence-ladder.md` | The evidence ladder (1) | 2026-11-03 · Wire evidence rungs into shipped fleet activity outputs |
| `docs/i18n-glossary.md` | Spanish caveat glossary (1) | 2026-11-17 · [SC1352-09] Reconcile Spanish caveat glossary with catalogue |
| `docs/operations/basemap-detail.md` | Trinidad–Klamath basemap detail (R4-SC-12) (1) | 2026-11-13 · Check statewide basemap detail settings before extraction |
| `docs/operations/coast-prefetch.md` | Coast campaign raw prefetch (operator runbook) (1) | 2026-10-23 · Hold prefetch when the mirror has receipts the primary lacks |
| `docs/operations/coast-statewide-runsheet.md` | Statewide coast recipe runsheet (OC-STATE) (1) | 2026-10-29 · feat(coast): prepare statewide offline recipes and runsheet |
| `docs/operations/cost-ceiling.md` | Cost ceiling and per-caller limits (1) | 2026-11-17 · Bind session cost attribution to the observed build |
| `docs/operations/perf-budget.md` | Size budget (quick pull request check) (1) | 2026-11-19 · Check DCO on each refreshed budget bot PR head |
| `docs/operations/runbooks/fleet-ais-down.md` | Runbook: the fleet AIS listener is down or silent (1) | 2026-11-18 · Point fleet runbooks, skills and the stale-issue link at private skippercast-ops |
| `docs/operations/runbooks/fleet-ais-receiver.md` | Runbook: Morro Bay AIS receiver (parts, site, install, licence note, rollback) (1) | 2026-11-18 · Point fleet runbooks, skills and the stale-issue link at private skippercast-ops |
| `docs/operations/runbooks/fleet-schedule-evidence.md` | Schedule evidence collector (1) | 2026-10-16 · Bind schedule status to departures and scan full trip windows |
| `docs/operations/runbooks/r2-snapshots.md` | Coherent R2 feed publication (1) | 2026-10-13 · Create immutable R2 objects once before publication (#632) |
| `docs/operations/runbooks/region-promotion.md` | Check a region before promotion (1) | 2026-11-13 · Add read-only per-region promotion preflight |
| `docs/operations/runbooks/relief-rollback.md` | Runbook: roll back a regional relief release (1) | 2026-11-20 · Add the regional relief rollback command and runbook |
| `docs/operations/runbooks/research-daily-enc-unavailable.md` | research-daily: NOAA ENC hazard step unavailable (1) | 2026-10-19 · Bind ENC hazard coverage to an explicit run/attempt identity |
| `docs/operations/runbooks/trip-checks.md` | Runbook: saved-trip alerts are late or missing (1) | 2026-09-29 · Add Analytics Engine metrics and a daily operations report |
| `docs/operations/station-failover.md` | Station priorities (1) | 2026-10-12 · Add a reviewed offshore backup buoy for Morro Bay (#611) |
| `docs/perf/tile-cost.md` | Per-view request and byte audit (BF-tile-cost) (1) | 2026-11-02 · Count each failed request once in the tile-cost audit |
| `docs/plans/charter-fleet/README.md` | Charter fleet registry and AIS activity map (1) | 2026-11-16 · Record AISWATCH-1 registry read-back and 14-day watch |
| `docs/plans/charter-fleet/design.md` | Charter fleet: design (1) | 2026-11-18 · Retire the public fleet workflows (#2891) |
| `docs/plans/charter-fleet/dev-plan.md` | Charter fleet: development plan (1) | 2026-10-05 · CF-14: landing-pages adapter with offerings and departures (#315) |
| `docs/plans/charter-fleet/graph.md` | Charter fleet: the run as a node graph (1) | 2026-10-12 · Package the fleet registry and activity skills (N8) (#586) |
| `docs/plans/charter-fleet/open-questions.md` | Open questions for the owner (1) | 2026-11-18 · Retire the public fleet workflows (#2891) |
| `docs/plans/charter-fleet/references/classification.md` | Activity classification: rules, thresholds and sources (1) | 2026-10-11 · Classify fishing as drift, slow troll and pelagic troll (N5) (#577) |
| `docs/plans/charter-fleet/user-stories.md` | User stories: charter fleet registry and AIS activity map (1) | 2026-10-04 · Add the charter fleet registry and AIS activity plan (#290) |
| `docs/plans/fish-bridge-retirement.md` | Fish bridge retirement: remaining dependencies (1) | 2026-11-16 · Plan the Fish bridge retirement dependencies (SCBB-06) |
| `docs/plans/front-end/README.md` | Front-end rebuild and the `fish` merge (1) | 2026-10-11 · Archive fish docs and receipts (FE-62a) (#573) |
| `docs/plans/front-end/design.md` | Front-end rebuild: design (1) | 2026-11-11 · [SC1407-15] Preview the planning route on Chart |
| `docs/plans/front-end/dev-plan.md` | Front-end rebuild: development plan (1) | 2026-11-03 · docs: name FE-62 in front-end status summary |
| `docs/plans/front-end/open-questions.md` | Open questions for the owner (1) | 2026-10-09 · FE-20: Layer rail, legend, ?layers=, profile defaults (#504) |
| `docs/plans/front-end/user-stories.md` | User stories: front-end rebuild and the `fish` merge (1) | 2026-10-19 · Put the admin trip map and strip on web/tokens.css names (US-L3) (#729) |
| `docs/plans/santa-cruz-monterey-bay-hold.md` | Santa Cruz-Monterey Bay: held habitat, per-reach hold report (1) | 2026-11-16 · [SCBB-11] Santa Cruz-Monterey Bay per-reach hold report |
| `docs/plans/second-active-region.md` | Second active region: criteria, Morro Bay assessment and a costed plan (1) | 2026-11-16 · [SCBB-03] Add Central Coast promotion sheet (section 8) |
| `docs/plans/text-advisor/00-decisions.md` | 00. Decisions, principles and boundaries (1) | 2026-10-03 · Add the BlueBubbles channel adapter, webhook and relay runbooks (TA-C1) |
| `docs/plans/text-advisor/01-architecture.md` | 01. Architecture (1) | 2026-10-04 · Give the web chat its own model budget, per address and overall |
| `docs/plans/text-advisor/02-data-model.md` | 02. Data model, storage, retention and privacy (1) | 2026-10-04 · Use fictional boat names and handles throughout the advisor tests |
| `docs/plans/text-advisor/03-channels.md` | 03. Channels: the number, the relay, Twilio, web chat (1) | 2026-10-04 · Keep relay copies off iCloud and under 30 days; say so in the notice |
| `docs/plans/text-advisor/04-advisor-engine.md` | 04. The advisor engine (1) | 2026-10-04 · Give the web chat its own model budget, per address and overall |
| `docs/plans/text-advisor/05-skipper-intake.md` | 05. Skipper onboarding and content intake (1) | 2026-10-04 · Require the invitee's YES before a crew link takes effect |
| `docs/plans/text-advisor/06-angler-answers.md` | 06. Angler answers: reports, planning, fish ID, rules, advice, safety (1) | 2026-10-04 · Draft social posts from consented photos for review (TA-S1) |
| `docs/plans/text-advisor/07-vision.md` | 07. Vision: providers, contracts and schemas (1) | 2026-10-04 · Add the Hermes vision provider and conformance script (TA-V2) |
| `docs/plans/text-advisor/08-website.md` | 08. Website: public pages, web chat, admin (1) | 2026-11-02 · Sitemap and robots follow the public-pages switch; WebPage JSON-LD for port and species pages |
| `docs/plans/text-advisor/09-social.md` | 09. Social: Instagram and Facebook Page (1) | 2026-11-18 · Docs: Meta Page token goes to a private file (SCA-173b, r2) |
| `docs/plans/text-advisor/10-work-breakdown.md` | 10. Work breakdown (1) | 2026-10-04 · Add the Text Advisor threat model, fixture privacy scan and data rights |
| `docs/plans/text-advisor/11-testing-rollout.md` | 11. Testing, rollout and metrics (1) | 2026-11-18 · Docs: Meta Page token goes to a private file (SCA-173b, r2) |
| `docs/product/ranked-reef-export.md` | Ranked reef day plans (1) | 2026-11-04 · [SC2207-04] Best available keeps its distance by water |
| `docs/research/competitors/competitors.json` | — | 2026-11-19 · Omit third-party screenshots from the research package |
| `docs/research/competitors/competitors.md` | SkipperCast competitor analysis (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/README.md` | SkipperCast data sources from 36 competitor apps (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources.json` | — | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/aviso-fsle.md` | AVISO+ FSLE (Finite-Size Lyapunov Exponents) — Lagrangian fronts (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cdse-sentinel-1.md` | Sentinel-1 SAR imagery (Copernicus Data Space) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cencoos-erddap-stations.md` | CeNCOOS ERDDAP shore stations (Cal Poly Pier, Morro Bay, Monterey Bay) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cmems-glo-bgc-anfc.md` | Copernicus Marine global biogeochemistry forecast (oxygen, productivity) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cmems-glo-phy-anfc.md` | Copernicus Marine global physics analysis + 10-day forecast (Mercator 1/12 deg) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cmems-oc-chl.md` | Copernicus GlobColour chlorophyll: OLCI 300 m daily + gap-free 4 km daily (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cmems-sealevel-nrt.md` | Copernicus Marine L4 NRT sea level (DUACS): SLA, ADT, geostrophic currents (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cw-acspo-l3s-leo-daily.md` | NOAA ACSPO L3S-LEO daily super-collated SST (VIIRS + AVHRR) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cw-goes-west-sst-hourly.md` | GOES-West (GOES-18) ACSPO hourly SST + fronts (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cw-kd490-water-clarity.md` | Water clarity Kd490 (MODIS West US 0.0125 deg, VIIRS 4 km, DINEOF gap-filled 2 km) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cw-nesdis-ssh-1day.md` | NOAA CoastWatch SSH anomaly + geostrophic currents (experimental) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/cw-smos-sss.md` | SMOS satellite sea-surface salinity (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/hycom-espc-d-v02.md` | HYCOM ESPC-D-V02 global ocean forecast (US Navy) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/nasa-gibs-truecolor.md` | NASA GIBS VIIRS / MODIS true-colour imagery tiles (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/nasa-pace-oci.md` | NASA PACE OCI ocean colour (hyperspectral) L3 daily (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/noaa-coops-current-predictions.md` | NOAA CO-OPS tidal current predictions (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/noaa-hrrr.md` | NOAA HRRR 3 km weather model (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/noaa-mrms-radar.md` | NOAA MRMS radar mosaic (NEXRAD) + nowCOAST radar WMS (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/noaa-rrfs.md` | NOAA RRFS (Rapid Refresh Forecast System, NAM/HRRR successor) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/noaa-rtofs.md` | NOAA Global RTOFS (HYCOM-based operational ocean forecast) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/open-meteo-more-models.md` | Open-Meteo extra models: DWD ICON, ECMWF AIFS, UK Met Office, Canadian GEM (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/data-sources/sources/sccoos-erddap.md` | SCCOOS ERDDAP (Southern California shore stations, HABs, gliders) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/inspiration/cmocean_stops.json` | — | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/inspiration/palettes.json` | — | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/inspiration/skippercast_inspiration.json` | — | 2026-11-19 · Omit third-party screenshots from the research package |
| `docs/research/inspiration/skippercast_inspiration.md` | SkipperCast map inspiration (X research, 2026-11-19) (1) | 2026-11-19 · Omit third-party screenshots from the research package |
| `docs/research/morro-bay-tuna.md` | Morro Bay tuna search overlay (1) | 2026-09-28 · Improve offshore tuna search areas and explain priorities (#18) |
| `docs/research/specs/01-point-readout-and-ramps.md` | 01 · Full point readout and adjustable colour ranges (3) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/01-point-readout-and-ramps/plan.md` | Implementation plan · 01 point readout and ramps (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/01-point-readout-and-ramps/spec.md` | 01 · Full point readout and adjustable colour ranges (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/01-point-readout-and-ramps/tasks.md` | Tasks · 01 point readout and ramps (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/02-observed-lookback.md` | 02 · Look-back playback for observed ocean layers (3) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/02-observed-lookback/plan.md` | Implementation plan · 02 observed look-back (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/02-observed-lookback/spec.md` | 02 · Look-back playback for observed ocean layers (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/02-observed-lookback/tasks.md` | Tasks · 02 observed look-back (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/03-spot-water-alerts.md` | 03 · Water-condition alerts on saved spots, and new-data alerts (3) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/03-spot-water-alerts/plan.md` | Implementation plan · 03 spot water alerts (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/03-spot-water-alerts/spec.md` | 03 · Water-condition alerts on saved spots, and new-data alerts (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/03-spot-water-alerts/tasks.md` | Tasks · 03 spot water alerts (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/04-heading-aware-comfort.md` | 04 · Heading-aware comfort ("ride by heading") and calibration from comfort reports (3) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/04-heading-aware-comfort/plan.md` | Implementation plan · 04 heading-aware comfort (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/04-heading-aware-comfort/spec.md` | 04 · Heading-aware comfort ("ride by heading") and calibration from comfort reports (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/04-heading-aware-comfort/tasks.md` | Tasks · 04 heading-aware comfort (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/05-chlorophyll-edges-eddies-ssh.md` | 05 · Chlorophyll edges, eddies and sea-surface height (3) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/05-chlorophyll-edges-eddies-ssh/plan.md` | Implementation plan · 05 chlorophyll edges, eddies, SSH (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/05-chlorophyll-edges-eddies-ssh/spec.md` | 05 · Chlorophyll edges, eddies and sea-surface height (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/05-chlorophyll-edges-eddies-ssh/tasks.md` | Tasks · 05 chlorophyll edges, eddies, SSH (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/06-catch-conditions.md` | 06 · Conditions recorded with each catch-log entry (3) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/06-catch-conditions/plan.md` | Implementation plan · 06 catch conditions (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/06-catch-conditions/spec.md` | 06 · Conditions recorded with each catch-log entry (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/06-catch-conditions/tasks.md` | Tasks · 06 catch conditions (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/07-subsurface-depth-ladder.md` | 07 · Subsurface depth ladder: temperature at depth, thermocline, mixed layer, salinity (3) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/07-subsurface-depth-ladder/plan.md` | Implementation plan · 07 subsurface depth ladder (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/07-subsurface-depth-ladder/spec.md` | 07 · Subsurface depth ladder: temperature at depth, thermocline, mixed layer, salinity (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/07-subsurface-depth-ladder/tasks.md` | Tasks · 07 subsurface depth ladder (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/08-gpx-import-and-fuel.md` | 08 · GPX import into saved spots, and an optional fuel estimate for the boat run (3) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/08-gpx-import-and-fuel/plan.md` | Implementation plan · 08 GPX import and fuel (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/08-gpx-import-and-fuel/spec.md` | 08 · GPX import into saved spots, and an optional fuel estimate for the boat run (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/08-gpx-import-and-fuel/tasks.md` | Tasks · 08 GPX import and fuel (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/09-text-advisor-launch.md` | 09 · Launch the built Text Advisor (plain-English briefings by text and on the site) (3) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/09-text-advisor-launch/plan.md` | Implementation plan · 09 Text Advisor launch (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/09-text-advisor-launch/spec.md` | 09 · Launch the built Text Advisor (plain-English briefings by text and on the site) (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/09-text-advisor-launch/tasks.md` | Tasks · 09 Text Advisor launch (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/10-coverage-and-distribution.md` | 10 · Coverage and distribution: a second active region, and an installable store-listed app (3) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/10-coverage-and-distribution/plan.md` | Implementation plan · 10 coverage and distribution (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/10-coverage-and-distribution/spec.md` | 10 · Coverage and distribution: a second active region, and an installable store-listed app (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/10-coverage-and-distribution/tasks.md` | Tasks · 10 coverage and distribution (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/rea-evidence/fishare.endpoints.json` | — | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/rea-evidence/fishare.err` | — | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/rea-evidence/fishare.evidence.json` | — | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/rea-evidence/fishorpass.endpoints.json` | — | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/rea-evidence/fishorpass.err` | — | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/rea-evidence/fishorpass.evidence.json` | — | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/references/README.md` | Spec references (1) | 2026-11-19 · Add Hermes feature research under docs/research |
| `docs/research/specs/specs.json` | — | 2026-11-19 · Restore Spec 07 R2 definitions in the research index |
| `docs/scb-07-c-manifest-probe.md` | SCB-07-C: read-only regional control probe (1) | 2026-11-14 · Use SkipperCast reef release and retire Fish habitat bridge |
| `docs/seafloor-bluetopo-scheme-repin.md` | BlueTopo tile scheme re-pin (2026-11-09 scheme) (1) | 2026-11-09 · seafloor: re-pin the BlueTopo tile scheme to the 2026-11-09 object (ledger regeneration held) |
| `docs/seafloor-ec.md` | Seafloor error correction (EC): shared contract (1) | 2026-10-31 · Merge pull request #1140 from Grahammmm/claude/ec-verify-identical-overlap |
| `docs/seafloor-second-scope.md` | Second seafloor scope: private, physical-only planning and runs (1) | 2026-11-16 · [MGL-19] seafloor: private physical-only plan and run for a second scope |
| `docs/seafloor-source-review-digital-coast.md` | Source review: NOAA Digital Coast DEM datasets admitted as reviewed original URLs (1) | 2026-11-09 · seafloor: admit dataset folders only for canonical URL text (allowlist follow-up; needs Codex review) |
| `docs/showcase/2026-10-31/boat-page.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/cambria-phone-after.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/cambria-phone-before.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/chart-laptop.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/chart-phone-after.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/chart-phone-before.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/conditions-phone-after.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/conditions-phone-before.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/first-run-phone-after.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/first-run-phone-before.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/history-laptop.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/landing-laptop-after.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/landing-laptop-before.png` | — | 2026-10-31 · Showcase: count anti-aliased edge blends as rendering noise |
| `docs/showcase/2026-10-31/landing-phone-after.png` | — | 2026-10-31 · Showcase: count anti-aliased edge blends as rendering noise |
| `docs/showcase/2026-10-31/landing-phone-before.png` | — | 2026-10-31 · Showcase: count anti-aliased edge blends as rendering noise |
| `docs/showcase/2026-10-31/port-page.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/spear-phone-after.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/spear-phone-before.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/2026-10-31/species-page.png` | — | 2026-10-31 · [SHOWCASE-1] Before/after visual gallery and reusable showcase script |
| `docs/showcase/pages-2026-10-31.json` | — | 2026-10-31 · Showcase: count anti-aliased edge blends as rendering noise |
| `docs/showcase/showcase-2026-10-31.html` | SkipperCast: what changed on screen, 2026-10-31 (24) | 2026-10-31 · Showcase: count anti-aliased edge blends as rendering noise |
| `docs/social-preview-prompt.txt` | — | 2026-09-21 · Improve fishing map protections, AIS evidence and forecast detail |

## R2. Missing targets or anchors

None. All 84 inline link occurrences in `docs/README.md:1–101` resolve to tracked files or a directory present in the tree. This includes the directory link and the individual runbook links on line 81, the root-level links on lines 69 and 93, and the archive links on lines 5, 97 and 101. The index has no reference-style link definitions, external destinations or `#` fragments in its link destinations. This checks the index, not links inside the documents it points to.

`python scripts/check_repository.py` checks that parsed local Markdown **paths** exist inside the repository (`scripts/check_repository.py:23,179–186`). It skips URL-only and fragment-only destinations and does not test a fragment on a valid path. It does not check whether a file is indexed or compare descriptions. The file hygiene and privacy checks in the same tool are separate (`scripts/check_repository.py:151–178`).

## R3. Index descriptions that no longer match

These are discrepancies between documents, not a check of what is deployed or a change to owner policy. An opening paragraph that is merely less detailed than the index is not counted as drift.

### Web app views

`docs/README.md:11`:

> The app's views (Map, Conditions, Export, Guide), what works, evidence limits and source layout

`docs/web-app.md:3`:

> The app is a mobile-first map workspace written in TypeScript and Preact. It has two pages: a landing page at `/` and the map app at `/map`. The map app has five views (Coast, Conditions, History, Fleet and Reports), a brief beside or under the map, a layer rail, and a time dock. This page describes what the code does today (package version 0.8). The older Leaflet "classic" shell is removed.

Only Conditions is named as a view in both lists; the guide describes Coast, History, Fleet and Reports instead of the other three index names.

### Land/water method

`docs/README.md:43`:

> Proposed land/water check for ranked places, built from the CUSP shoreline (CI6-01B step 0, round 2, in review)

`docs/land-water-method.md:3–10`:

> Status: approved at step 0 (round 2, sol-reviewer, STEP0 APPROVED at 90aa40ba,
> 2026-10-20) and implemented as described under "Implementation" below. Evidence
> comes from `research/scripts/assess_land_water_feasibility.py` (read-only). It ran on the
> published Morro Bay shoreline, which is byte-identical from b2474f6d through
> `origin/main` 573b6682a, and on terrain habitat release 4c24f963f09b…, whose
> detail file matched its manifest sha256 cb4d9cbb…. Every topology test in it is
> exact: coordinates are compared as integers on the published 5-decimal grid.
> `--self-test` runs the same rules on injected geometry. Output is quoted below.

The method document records approval and implementation; the index still describes a proposal in review. This does not extend that approval to another use.

### Runner guide

`docs/README.md:80`:

> Where the jobs run, what GitHub-hosted minutes cost on a private repository, and the self-hosted runner switch

`docs/operations/runners.md:3–5`:

> This guide inventories GitHub Actions jobs for capacity planning. It describes the
> checked-in workflows, not how often jobs actually start, and separates public hosted jobs
> from private fleet jobs.

The current guide leads with capacity planning and a public-hosted/private-fleet split. It calls the older estimates historical assumptions, not measured usage or a bill (`docs/operations/runners.md:9–15`), and documents distinct runner assignments, not a general switch for public jobs (`docs/operations/runners.md:46–66`).

### Also stale: archive count (introductory text, not a table row)

`docs/README.md:97` says “lists the 39 archived research logs.” The opening paragraph of `docs/archive/README.md:3` says:

> Dated audit, rollout, source-request and review records, kept as the evidence trail behind coverage and product decisions.

The paragraph does not give a count. The link inventory in `docs/archive/README.md:15–105` points to 53 distinct tracked Markdown files under `docs/archive/` (dated scan above). This counts what the archive index links, not the size of the archive tree.

## R4. Proposed rows to add

Draft rows below cover the 179 missing Markdown documents other than the index itself, plus the showcase HTML. Labels come from the headings in R1; they do not designate a plan, audit, or held record as current behaviour or approve any action. No self-link is proposed. The other 39 files are supporting material (for example, screenshots accompanying the showcase and the source prompt already named at `docs/README.md:57`); inventory them in R1 but do not add separate reader rows for them. Existing child indexes make many of these detailed rows optional **if** the index's opening promise is changed to describe a guide with child indexes rather than direct coverage of every document. The list below is the direct-coverage option, not that editorial decision.

The text in the first column is the proposed path relative to `docs/README.md`; links in this report point to the same files from `docs/plans/`.

> | Document | Purpose |
> | --- | --- |
> | [`FISH-MERGE-REVIEW.md`](../FISH-MERGE-REVIEW.md) | FishReport merge inventory and independent review |
> | [`FISH-MERGE-STATUS.md`](../FISH-MERGE-STATUS.md) | Fish → SkipperCast integration |
> | [`audit/OWNERSHIP.md`](../audit/OWNERSHIP.md) | Owners and path reservations |
> | [`audit/README.md`](../audit/README.md) | Audit collaboration start page |
> | [`audit/SC-11-browser-2m-scope.md`](../audit/SC-11-browser-2m-scope.md) | SC-11: 2 m selected-copy browser acceptance |
> | [`audit/packets/ENC-RECOVERY.md`](../audit/packets/ENC-RECOVERY.md) | ENC recovery: current-base integration |
> | [`coast-capabilities-status.md`](../coast-capabilities-status.md) | Captain feature status |
> | [`coast-rights-coverage.md`](../coast-rights-coverage.md) | Recipe rights coverage (N3) |
> | [`coastal-catalog-bridge.md`](../coastal-catalog-bridge.md) | Frozen catalog to coordinator acquire bridge |
> | [`coastal-discovery-intake.md`](../coastal-discovery-intake.md) | Held coastal discovery intake |
> | [`coastal-live-discovery.md`](../coastal-live-discovery.md) | Governed live coastal discovery |
> | [`coastal-service.md`](../coastal-service.md) | Coastal data service during the Fish merge |
> | [`diagnostics/SC0922-05.md`](../diagnostics/SC0922-05.md) | SC0922-05: first-run brief timeouts on `e2e (2)` laptop |
> | [`engineering/adr/0001-record-architecture-decisions.md`](../engineering/adr/0001-record-architecture-decisions.md) | 0001. Record architecture decisions |
> | [`engineering/adr/0002-own-forecast-tiles.md`](../engineering/adr/0002-own-forecast-tiles.md) | 0002. Build our own forecasts from NOAA and ECMWF open data |
> | [`engineering/adr/0003-r2-system-of-record.md`](../engineering/adr/0003-r2-system-of-record.md) | 0003. R2 is the feed system of record; git feed branches are single-commit mirrors |
> | [`engineering/adr/0004-licensing.md`](../engineering/adr/0004-licensing.md) | 0004. Licensing, copyright ownership and contributor terms |
> | [`engineering/adr/0005-front-end-preact-vite-maplibre.md`](../engineering/adr/0005-front-end-preact-vite-maplibre.md) | 0005. Front end: Preact and Vite, with MapLibre and PMTiles for the map |
> | [`engineering/adr/0006-passkey-accounts-stripe-later.md`](../engineering/adr/0006-passkey-accounts-stripe-later.md) | 0006. SkipperCast accounts with passkeys now; Stripe billing later |
> | [`engineering/adr/0007-text-advisor-channels-and-vision.md`](../engineering/adr/0007-text-advisor-channels-and-vision.md) | 0007. Text Advisor: an owned number with a self-hosted iMessage relay, Twilio as the fallback, and a two-provider vision chain |
> | [`engineering/adr/0008-charter-fleet-registry-and-ais.md`](../engineering/adr/0008-charter-fleet-registry-and-ais.md) | 0008. Charter fleet: state-level region config, a headless OSINT step, raw AIS kept off D1, and aisstream behind a source adapter |
> | [`engineering/adr/0009-front-end-rebuild-and-fish-merge.md`](../engineering/adr/0009-front-end-rebuild-and-fish-merge.md) | 0009. Front end: rebuild the shell on ADR 0005's stack behind a flag, self-host the basemap, and merge `fish` |
> | [`engineering/adr/0010-spot-alert-events.md`](../engineering/adr/0010-spot-alert-events.md) | 0010. Store spot-watch alert events separately |
> | [`engineering/audits/coast-pilot-b3-root-gaps.md`](../engineering/audits/coast-pilot-b3-root-gaps.md) | COAST / PILOT / B3 original-root evidence gaps |
> | [`engineering/audits/coast-prod-window-crosswalk.md`](../engineering/audits/coast-prod-window-crosswalk.md) | COAST-PROD identifiers and saved-area window crosswalk |
> | [`engineering/audits/coast-prod-window-receipt.md`](../engineering/audits/coast-prod-window-receipt.md) | AUDINV-FIX-111 bounded implementation receipt |
> | [`engineering/audits/coastal-receipt-erratum-20261020.md`](../engineering/audits/coastal-receipt-erratum-20261020.md) | Erratum: two retained-byte figures in the 2026-10-20 four128 rerun receipts |
> | [`engineering/audits/coastal-snapshot-2026-10-20.md`](../engineering/audits/coastal-snapshot-2026-10-20.md) | SC-4: coastal snapshot port-or-retire inventory |
> | [`engineering/audits/four-sector-fetch-ready-receipt.md`](../engineering/audits/four-sector-fetch-ready-receipt.md) | Four-sector PSIX fetch: offline retry-readiness receipt (AUDINV-FIX-115) |
> | [`engineering/audits/live-hole-preservation-gap.md`](../engineering/audits/live-hole-preservation-gap.md) | Live hole and disjoint-core preservation: retained evidence gap |
> | [`engineering/audits/local-merge-queue-feasibility.md`](../engineering/audits/local-merge-queue-feasibility.md) | Local merge-queue feasibility — AUDINV-CIW-67 |
> | [`engineering/audits/morro-bay-readiness-gap.md`](../engineering/audits/morro-bay-readiness-gap.md) | Morro Bay bathymetry readiness gap — AUDINV-OLD-21 |
> | [`engineering/audits/prepare-assembly-receipt.md`](../engineering/audits/prepare-assembly-receipt.md) | AUDINV-FIX-056 — prepare-to-assembly regression receipt |
> | [`engineering/audits/python-pr-matrix-policy-gap.md`](../engineering/audits/python-pr-matrix-policy-gap.md) | CIW-56 policy-gap report: Python PR matrix and advisory audit |
> | [`engineering/audits/registry-discovery-receipt.md`](../engineering/audits/registry-discovery-receipt.md) | Registry and shared-fixture discovery receipt |
> | [`engineering/audits/remaining-dossier-archival-consumer-gap.md`](../engineering/audits/remaining-dossier-archival-consumer-gap.md) | OLD-07 — remaining dossier archival / consumer gap |
> | [`engineering/audits/rollup-gate-receipt.md`](../engineering/audits/rollup-gate-receipt.md) | survey-science roll-up gate receipt (AUDINV-CIW-04) |
> | [`engineering/audits/run218-receipt-locator.md`](../engineering/audits/run218-receipt-locator.md) | Run218 receipt / preview locator (AUDINV-FIX-125) |
> | [`engineering/audits/skippercast-layer-rail-policy-proposal.md`](../engineering/audits/skippercast-layer-rail-policy-proposal.md) | Layer-rail ownership and dependency-only lockfile policy: proposal (AUDINV-CIW-75) |
> | [`engineering/audits/standing-e2e-diagnosis.md`](../engineering/audits/standing-e2e-diagnosis.md) | AUDINV-CIW-19 — Standing e2e diagnosis |
> | [`engineering/audits/t08-admission-gap.md`](../engineering/audits/t08-admission-gap.md) | T08 admission gap report (AUDINV-FIX-059) |
> | [`engineering/bedrock-canonical-exclusion.md`](../engineering/bedrock-canonical-exclusion.md) | Opt-in canonical occupied exclusion for original interpreted bedrock |
> | [`engineering/classified-geometry.md`](../engineering/classified-geometry.md) | Classified habitat map representation |
> | [`engineering/e2e-quarantine.md`](../engineering/e2e-quarantine.md) | Bounded browser-test quarantine (SC-CI-3) |
> | [`engineering/native-terrain-support.md`](../engineering/native-terrain-support.md) | Reviewed native terrain support |
> | [`engineering/sc32_bridge_bounds.md`](../engineering/sc32_bridge_bounds.md) | SC32-BRIDGE-BOUNDS: malformed geographic boxes never plan a coast catalog bridge |
> | [`engineering/sc34_terrain_json.md`](../engineering/sc34_terrain_json.md) | SC34: strict JSON in the terrain CLI metadata reader |
> | [`engineering/sc38_prefetch_version.md`](../engineering/sc38_prefetch_version.md) | SC38: integer schema_version for coast prefetch plans |
> | [`engineering/sc_cache_clock.md`](../engineering/sc_cache_clock.md) | SC-CACHE-CLOCK: explicit, host-independent cached evidence times |
> | [`engineering/sc_catalog_rows.md`](../engineering/sc_catalog_rows.md) | SC-CATALOG-ROWS: unique literal candidate identities in frozen catalog diffs |
> | [`engineering/sc_metadata_object.md`](../engineering/sc_metadata_object.md) | SC-METADATA-OBJECT: cached metadata must be a JSON object |
> | [`engineering/sc_png_dtype.md`](../engineering/sc_png_dtype.md) | Coastal preview PNG: uint8-only input (SC-PNG-DTYPE) |
> | [`engineering/sc_recipe_offline.md`](../engineering/sc_recipe_offline.md) | Offline coast recipe schema references (SC-RECIPE-OFFLINE) |
> | [`engineering/sc_rights_delta.md`](../engineering/sc_rights_delta.md) | SC-RIGHTS-DELTA: compare two frozen rights observations |
> | [`engineering/sc_sample_audit.md`](../engineering/sc_sample_audit.md) | Coast sample composition report (SC-SAMPLE-AUDIT) |
> | [`engineering/sc_schema_closure.md`](../engineering/sc_schema_closure.md) | SC-SCHEMA-CLOSURE: static JSON Schema dependency closure |
> | [`engineering/sc_segment_delta.md`](../engineering/sc_segment_delta.md) | SC-SEGMENT-DELTA: explain two frozen segment receipts |
> | [`engineering/seafloor-numeric-cache.md`](../engineering/seafloor-numeric-cache.md) | Stable seafloor measurement encoding |
> | [`engineering/sp1301_event_segment.md`](../engineering/sp1301_event_segment.md) | SP1301-EVENT-SEGMENT: an event's segment must belong to the event's own trip |
> | [`engineering/sp1510_classifier_identity.md`](../engineering/sp1510_classifier_identity.md) | Classifier identity v3 (SP-15-v1 / SP1510-CLASSIFIER-IDENTITY) |
> | [`engineering/sp1602_report_unknown_counts.md`](../engineering/sp1602_report_unknown_counts.md) | Advisor count display semantics |
> | [`engineering/sp1603_fleet_identity_diagnostic.md`](../engineering/sp1603_fleet_identity_diagnostic.md) | Fleet identity byte diagnostic (SP-16-v1) |
> | [`evidence-ladder.md`](../evidence-ladder.md) | The evidence ladder |
> | [`i18n-glossary.md`](../i18n-glossary.md) | Spanish caveat glossary |
> | [`operations/basemap-detail.md`](../operations/basemap-detail.md) | Trinidad–Klamath basemap detail (R4-SC-12) |
> | [`operations/coast-prefetch.md`](../operations/coast-prefetch.md) | Coast campaign raw prefetch (operator runbook) |
> | [`operations/coast-statewide-runsheet.md`](../operations/coast-statewide-runsheet.md) | Statewide coast recipe runsheet (OC-STATE) |
> | [`operations/cost-ceiling.md`](../operations/cost-ceiling.md) | Cost ceiling and per-caller limits |
> | [`operations/perf-budget.md`](../operations/perf-budget.md) | Size budget (quick pull request check) |
> | [`operations/runbooks/fleet-ais-down.md`](../operations/runbooks/fleet-ais-down.md) | Runbook: the fleet AIS listener is down or silent |
> | [`operations/runbooks/fleet-ais-receiver.md`](../operations/runbooks/fleet-ais-receiver.md) | Runbook: Morro Bay AIS receiver (parts, site, install, licence note, rollback) |
> | [`operations/runbooks/fleet-schedule-evidence.md`](../operations/runbooks/fleet-schedule-evidence.md) | Schedule evidence collector |
> | [`operations/runbooks/r2-snapshots.md`](../operations/runbooks/r2-snapshots.md) | Coherent R2 feed publication |
> | [`operations/runbooks/region-promotion.md`](../operations/runbooks/region-promotion.md) | Check a region before promotion |
> | [`operations/runbooks/relief-rollback.md`](../operations/runbooks/relief-rollback.md) | Runbook: roll back a regional relief release |
> | [`operations/runbooks/research-daily-enc-unavailable.md`](../operations/runbooks/research-daily-enc-unavailable.md) | research-daily: NOAA ENC hazard step unavailable |
> | [`operations/runbooks/trip-checks.md`](../operations/runbooks/trip-checks.md) | Runbook: saved-trip alerts are late or missing |
> | [`operations/station-failover.md`](../operations/station-failover.md) | Station priorities |
> | [`perf/tile-cost.md`](../perf/tile-cost.md) | Per-view request and byte audit (BF-tile-cost) |
> | [`plans/charter-fleet/README.md`](charter-fleet/README.md) | Charter fleet registry and AIS activity map |
> | [`plans/charter-fleet/design.md`](charter-fleet/design.md) | Charter fleet: design |
> | [`plans/charter-fleet/dev-plan.md`](charter-fleet/dev-plan.md) | Charter fleet: development plan |
> | [`plans/charter-fleet/graph.md`](charter-fleet/graph.md) | Charter fleet: the run as a node graph |
> | [`plans/charter-fleet/open-questions.md`](charter-fleet/open-questions.md) | Open questions for the owner |
> | [`plans/charter-fleet/references/classification.md`](charter-fleet/references/classification.md) | Activity classification: rules, thresholds and sources |
> | [`plans/charter-fleet/user-stories.md`](charter-fleet/user-stories.md) | User stories: charter fleet registry and AIS activity map |
> | [`plans/fish-bridge-retirement.md`](fish-bridge-retirement.md) | Fish bridge retirement: remaining dependencies |
> | [`plans/front-end/README.md`](front-end/README.md) | Front-end rebuild and the `fish` merge |
> | [`plans/front-end/design.md`](front-end/design.md) | Front-end rebuild: design |
> | [`plans/front-end/dev-plan.md`](front-end/dev-plan.md) | Front-end rebuild: development plan |
> | [`plans/front-end/open-questions.md`](front-end/open-questions.md) | Open questions for the owner |
> | [`plans/front-end/user-stories.md`](front-end/user-stories.md) | User stories: front-end rebuild and the `fish` merge |
> | [`plans/santa-cruz-monterey-bay-hold.md`](santa-cruz-monterey-bay-hold.md) | Santa Cruz-Monterey Bay: held habitat, per-reach hold report |
> | [`plans/second-active-region.md`](second-active-region.md) | Second active region: criteria, Morro Bay assessment and a costed plan |
> | [`plans/text-advisor/00-decisions.md`](text-advisor/00-decisions.md) | 00. Decisions, principles and boundaries |
> | [`plans/text-advisor/01-architecture.md`](text-advisor/01-architecture.md) | 01. Architecture |
> | [`plans/text-advisor/02-data-model.md`](text-advisor/02-data-model.md) | 02. Data model, storage, retention and privacy |
> | [`plans/text-advisor/03-channels.md`](text-advisor/03-channels.md) | 03. Channels: the number, the relay, Twilio, web chat |
> | [`plans/text-advisor/04-advisor-engine.md`](text-advisor/04-advisor-engine.md) | 04. The advisor engine |
> | [`plans/text-advisor/05-skipper-intake.md`](text-advisor/05-skipper-intake.md) | 05. Skipper onboarding and content intake |
> | [`plans/text-advisor/06-angler-answers.md`](text-advisor/06-angler-answers.md) | 06. Angler answers: reports, planning, fish ID, rules, advice, safety |
> | [`plans/text-advisor/07-vision.md`](text-advisor/07-vision.md) | 07. Vision: providers, contracts and schemas |
> | [`plans/text-advisor/08-website.md`](text-advisor/08-website.md) | 08. Website: public pages, web chat, admin |
> | [`plans/text-advisor/09-social.md`](text-advisor/09-social.md) | 09. Social: Instagram and Facebook Page |
> | [`plans/text-advisor/10-work-breakdown.md`](text-advisor/10-work-breakdown.md) | 10. Work breakdown |
> | [`plans/text-advisor/11-testing-rollout.md`](text-advisor/11-testing-rollout.md) | 11. Testing, rollout and metrics |
> | [`product/ranked-reef-export.md`](../product/ranked-reef-export.md) | Ranked reef day plans |
> | [`research/competitors/competitors.md`](../research/competitors/competitors.md) | SkipperCast competitor analysis |
> | [`research/data-sources/README.md`](../research/data-sources/README.md) | SkipperCast data sources from 36 competitor apps |
> | [`research/data-sources/sources/aviso-fsle.md`](../research/data-sources/sources/aviso-fsle.md) | AVISO+ FSLE (Finite-Size Lyapunov Exponents) — Lagrangian fronts |
> | [`research/data-sources/sources/cdse-sentinel-1.md`](../research/data-sources/sources/cdse-sentinel-1.md) | Sentinel-1 SAR imagery (Copernicus Data Space) |
> | [`research/data-sources/sources/cencoos-erddap-stations.md`](../research/data-sources/sources/cencoos-erddap-stations.md) | CeNCOOS ERDDAP shore stations (Cal Poly Pier, Morro Bay, Monterey Bay) |
> | [`research/data-sources/sources/cmems-glo-bgc-anfc.md`](../research/data-sources/sources/cmems-glo-bgc-anfc.md) | Copernicus Marine global biogeochemistry forecast (oxygen, productivity) |
> | [`research/data-sources/sources/cmems-glo-phy-anfc.md`](../research/data-sources/sources/cmems-glo-phy-anfc.md) | Copernicus Marine global physics analysis + 10-day forecast (Mercator 1/12 deg) |
> | [`research/data-sources/sources/cmems-oc-chl.md`](../research/data-sources/sources/cmems-oc-chl.md) | Copernicus GlobColour chlorophyll: OLCI 300 m daily + gap-free 4 km daily |
> | [`research/data-sources/sources/cmems-sealevel-nrt.md`](../research/data-sources/sources/cmems-sealevel-nrt.md) | Copernicus Marine L4 NRT sea level (DUACS): SLA, ADT, geostrophic currents |
> | [`research/data-sources/sources/cw-acspo-l3s-leo-daily.md`](../research/data-sources/sources/cw-acspo-l3s-leo-daily.md) | NOAA ACSPO L3S-LEO daily super-collated SST (VIIRS + AVHRR) |
> | [`research/data-sources/sources/cw-goes-west-sst-hourly.md`](../research/data-sources/sources/cw-goes-west-sst-hourly.md) | GOES-West (GOES-18) ACSPO hourly SST + fronts |
> | [`research/data-sources/sources/cw-kd490-water-clarity.md`](../research/data-sources/sources/cw-kd490-water-clarity.md) | Water clarity Kd490 (MODIS West US 0.0125 deg, VIIRS 4 km, DINEOF gap-filled 2 km) |
> | [`research/data-sources/sources/cw-nesdis-ssh-1day.md`](../research/data-sources/sources/cw-nesdis-ssh-1day.md) | NOAA CoastWatch SSH anomaly + geostrophic currents (experimental) |
> | [`research/data-sources/sources/cw-smos-sss.md`](../research/data-sources/sources/cw-smos-sss.md) | SMOS satellite sea-surface salinity |
> | [`research/data-sources/sources/hycom-espc-d-v02.md`](../research/data-sources/sources/hycom-espc-d-v02.md) | HYCOM ESPC-D-V02 global ocean forecast (US Navy) |
> | [`research/data-sources/sources/nasa-gibs-truecolor.md`](../research/data-sources/sources/nasa-gibs-truecolor.md) | NASA GIBS VIIRS / MODIS true-colour imagery tiles |
> | [`research/data-sources/sources/nasa-pace-oci.md`](../research/data-sources/sources/nasa-pace-oci.md) | NASA PACE OCI ocean colour (hyperspectral) L3 daily |
> | [`research/data-sources/sources/noaa-coops-current-predictions.md`](../research/data-sources/sources/noaa-coops-current-predictions.md) | NOAA CO-OPS tidal current predictions |
> | [`research/data-sources/sources/noaa-hrrr.md`](../research/data-sources/sources/noaa-hrrr.md) | NOAA HRRR 3 km weather model |
> | [`research/data-sources/sources/noaa-mrms-radar.md`](../research/data-sources/sources/noaa-mrms-radar.md) | NOAA MRMS radar mosaic (NEXRAD) + nowCOAST radar WMS |
> | [`research/data-sources/sources/noaa-rrfs.md`](../research/data-sources/sources/noaa-rrfs.md) | NOAA RRFS (Rapid Refresh Forecast System, NAM/HRRR successor) |
> | [`research/data-sources/sources/noaa-rtofs.md`](../research/data-sources/sources/noaa-rtofs.md) | NOAA Global RTOFS (HYCOM-based operational ocean forecast) |
> | [`research/data-sources/sources/open-meteo-more-models.md`](../research/data-sources/sources/open-meteo-more-models.md) | Open-Meteo extra models: DWD ICON, ECMWF AIFS, UK Met Office, Canadian GEM |
> | [`research/data-sources/sources/sccoos-erddap.md`](../research/data-sources/sources/sccoos-erddap.md) | SCCOOS ERDDAP (Southern California shore stations, HABs, gliders) |
> | [`research/inspiration/skippercast_inspiration.md`](../research/inspiration/skippercast_inspiration.md) | SkipperCast map inspiration (X research, 2026-11-19) |
> | [`research/morro-bay-tuna.md`](../research/morro-bay-tuna.md) | Morro Bay tuna search overlay |
> | [`research/specs/01-point-readout-and-ramps.md`](../research/specs/01-point-readout-and-ramps.md) | 01 · Full point readout and adjustable colour ranges |
> | [`research/specs/01-point-readout-and-ramps/plan.md`](../research/specs/01-point-readout-and-ramps/plan.md) | Implementation plan · 01 point readout and ramps |
> | [`research/specs/01-point-readout-and-ramps/spec.md`](../research/specs/01-point-readout-and-ramps/spec.md) | 01 · Full point readout and adjustable colour ranges |
> | [`research/specs/01-point-readout-and-ramps/tasks.md`](../research/specs/01-point-readout-and-ramps/tasks.md) | Tasks · 01 point readout and ramps |
> | [`research/specs/02-observed-lookback.md`](../research/specs/02-observed-lookback.md) | 02 · Look-back playback for observed ocean layers |
> | [`research/specs/02-observed-lookback/plan.md`](../research/specs/02-observed-lookback/plan.md) | Implementation plan · 02 observed look-back |
> | [`research/specs/02-observed-lookback/spec.md`](../research/specs/02-observed-lookback/spec.md) | 02 · Look-back playback for observed ocean layers |
> | [`research/specs/02-observed-lookback/tasks.md`](../research/specs/02-observed-lookback/tasks.md) | Tasks · 02 observed look-back |
> | [`research/specs/03-spot-water-alerts.md`](../research/specs/03-spot-water-alerts.md) | 03 · Water-condition alerts on saved spots, and new-data alerts |
> | [`research/specs/03-spot-water-alerts/plan.md`](../research/specs/03-spot-water-alerts/plan.md) | Implementation plan · 03 spot water alerts |
> | [`research/specs/03-spot-water-alerts/spec.md`](../research/specs/03-spot-water-alerts/spec.md) | 03 · Water-condition alerts on saved spots, and new-data alerts |
> | [`research/specs/03-spot-water-alerts/tasks.md`](../research/specs/03-spot-water-alerts/tasks.md) | Tasks · 03 spot water alerts |
> | [`research/specs/04-heading-aware-comfort.md`](../research/specs/04-heading-aware-comfort.md) | 04 · Heading-aware comfort ("ride by heading") and calibration from comfort reports |
> | [`research/specs/04-heading-aware-comfort/plan.md`](../research/specs/04-heading-aware-comfort/plan.md) | Implementation plan · 04 heading-aware comfort |
> | [`research/specs/04-heading-aware-comfort/spec.md`](../research/specs/04-heading-aware-comfort/spec.md) | 04 · Heading-aware comfort ("ride by heading") and calibration from comfort reports |
> | [`research/specs/04-heading-aware-comfort/tasks.md`](../research/specs/04-heading-aware-comfort/tasks.md) | Tasks · 04 heading-aware comfort |
> | [`research/specs/05-chlorophyll-edges-eddies-ssh.md`](../research/specs/05-chlorophyll-edges-eddies-ssh.md) | 05 · Chlorophyll edges, eddies and sea-surface height |
> | [`research/specs/05-chlorophyll-edges-eddies-ssh/plan.md`](../research/specs/05-chlorophyll-edges-eddies-ssh/plan.md) | Implementation plan · 05 chlorophyll edges, eddies, SSH |
> | [`research/specs/05-chlorophyll-edges-eddies-ssh/spec.md`](../research/specs/05-chlorophyll-edges-eddies-ssh/spec.md) | 05 · Chlorophyll edges, eddies and sea-surface height |
> | [`research/specs/05-chlorophyll-edges-eddies-ssh/tasks.md`](../research/specs/05-chlorophyll-edges-eddies-ssh/tasks.md) | Tasks · 05 chlorophyll edges, eddies, SSH |
> | [`research/specs/06-catch-conditions.md`](../research/specs/06-catch-conditions.md) | 06 · Conditions recorded with each catch-log entry |
> | [`research/specs/06-catch-conditions/plan.md`](../research/specs/06-catch-conditions/plan.md) | Implementation plan · 06 catch conditions |
> | [`research/specs/06-catch-conditions/spec.md`](../research/specs/06-catch-conditions/spec.md) | 06 · Conditions recorded with each catch-log entry |
> | [`research/specs/06-catch-conditions/tasks.md`](../research/specs/06-catch-conditions/tasks.md) | Tasks · 06 catch conditions |
> | [`research/specs/07-subsurface-depth-ladder.md`](../research/specs/07-subsurface-depth-ladder.md) | 07 · Subsurface depth ladder: temperature at depth, thermocline, mixed layer, salinity |
> | [`research/specs/07-subsurface-depth-ladder/plan.md`](../research/specs/07-subsurface-depth-ladder/plan.md) | Implementation plan · 07 subsurface depth ladder |
> | [`research/specs/07-subsurface-depth-ladder/spec.md`](../research/specs/07-subsurface-depth-ladder/spec.md) | 07 · Subsurface depth ladder: temperature at depth, thermocline, mixed layer, salinity |
> | [`research/specs/07-subsurface-depth-ladder/tasks.md`](../research/specs/07-subsurface-depth-ladder/tasks.md) | Tasks · 07 subsurface depth ladder |
> | [`research/specs/08-gpx-import-and-fuel.md`](../research/specs/08-gpx-import-and-fuel.md) | 08 · GPX import into saved spots, and an optional fuel estimate for the boat run |
> | [`research/specs/08-gpx-import-and-fuel/plan.md`](../research/specs/08-gpx-import-and-fuel/plan.md) | Implementation plan · 08 GPX import and fuel |
> | [`research/specs/08-gpx-import-and-fuel/spec.md`](../research/specs/08-gpx-import-and-fuel/spec.md) | 08 · GPX import into saved spots, and an optional fuel estimate for the boat run |
> | [`research/specs/08-gpx-import-and-fuel/tasks.md`](../research/specs/08-gpx-import-and-fuel/tasks.md) | Tasks · 08 GPX import and fuel |
> | [`research/specs/09-text-advisor-launch.md`](../research/specs/09-text-advisor-launch.md) | 09 · Launch the built Text Advisor (plain-English briefings by text and on the site) |
> | [`research/specs/09-text-advisor-launch/plan.md`](../research/specs/09-text-advisor-launch/plan.md) | Implementation plan · 09 Text Advisor launch |
> | [`research/specs/09-text-advisor-launch/spec.md`](../research/specs/09-text-advisor-launch/spec.md) | 09 · Launch the built Text Advisor (plain-English briefings by text and on the site) |
> | [`research/specs/09-text-advisor-launch/tasks.md`](../research/specs/09-text-advisor-launch/tasks.md) | Tasks · 09 Text Advisor launch |
> | [`research/specs/10-coverage-and-distribution.md`](../research/specs/10-coverage-and-distribution.md) | 10 · Coverage and distribution: a second active region, and an installable store-listed app |
> | [`research/specs/10-coverage-and-distribution/plan.md`](../research/specs/10-coverage-and-distribution/plan.md) | Implementation plan · 10 coverage and distribution |
> | [`research/specs/10-coverage-and-distribution/spec.md`](../research/specs/10-coverage-and-distribution/spec.md) | 10 · Coverage and distribution: a second active region, and an installable store-listed app |
> | [`research/specs/10-coverage-and-distribution/tasks.md`](../research/specs/10-coverage-and-distribution/tasks.md) | Tasks · 10 coverage and distribution |
> | [`research/specs/references/README.md`](../research/specs/references/README.md) | Spec references |
> | [`scb-07-c-manifest-probe.md`](../scb-07-c-manifest-probe.md) | SCB-07-C: read-only regional control probe |
> | [`seafloor-bluetopo-scheme-repin.md`](../seafloor-bluetopo-scheme-repin.md) | BlueTopo tile scheme re-pin (2026-11-09 scheme) |
> | [`seafloor-ec.md`](../seafloor-ec.md) | Seafloor error correction (EC): shared contract |
> | [`seafloor-second-scope.md`](../seafloor-second-scope.md) | Second seafloor scope: private, physical-only planning and runs |
> | [`seafloor-source-review-digital-coast.md`](../seafloor-source-review-digital-coast.md) | Source review: NOAA Digital Coast DEM datasets admitted as reviewed original URLs |
> | [`showcase/showcase-2026-10-31.html`](../showcase/showcase-2026-10-31.html) | SkipperCast: what changed on screen, 2026-10-31 |

**One follow-up unit (estimate: 90 minutes):** Update `docs/README.md` only. Add the draft rows under the existing audience groups (use a separate reference group for dated plans and diagnostics), include any new documents since this snapshot, refresh the three stale descriptions, and replace the hard-coded archive count with a link description that does not repeat a count. Offline acceptance: rerun the R1 comparison against the edited index and confirm only the agreed exceptions (self-link and supporting files) remain; rerun the R2 destination check and `python scripts/check_repository.py`. Keep the archive, all underlying documents and any approval or release decisions unchanged. This report does not make that edit.
