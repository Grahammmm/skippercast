# Charter fleet: development plan

One task = one `charter-builder` = one branch `claude/cf-<id>` (for example
`claude/cf-02`) = one PR. Every task stays at or under about 400 changed lines,
not counting generated files (Drizzle migrations and snapshots, `dist/` build
output). Sizes: **S** under 150 lines, **M** 150–300, **L** 300–400. The
section numbers (§) refer to [design.md](design.md), which holds the detail;
re-read the section before starting a task. There are 37 tasks in seven phases.

Rules for every task:

- Start from a fresh `main`, depend only on merged tasks, and rebase before
  review (`AGENTS.md`). Run the checks in `AGENTS.md` § "Before opening a PR".
- Independent review by `charter-reviewer` against `AGENTS.md`'s checklist and
  the task's acceptance criteria; merge only on green CI at the current head.
- No registry data, OSINT output, positions or outreach text in the diff.
  Fixtures are synthetic (555-01XX phones, handles from
  `catalog/advisor/fixture-handles.json`, invented names, MMSIs `999xxxxxx`).
- AIS-derived copy says "inferred from movement", never "confirmed".
- `.github/CODEOWNERS` gives the owner `server/`, `.github/workflows/`,
  `deployments/`, `docs/legal/` and `wrangler.jsonc`. If branch protection requires
  code-owner review, the PR waits for the **Owner**'s GitHub approval; the
  builder says so in the PR body with the link.
- Material user-facing changes add a line under `## Unreleased` in
  `CHANGELOG.md`. Append a dated line to [README.md](README.md)'s status log
  when a task merges.

## Phase 0: foundations

### CF-01 · Fleet settings, flags, router, job scope, admin gate · M
- Depends: —
- Files: `server/fleet/settings.ts`, `server/routes/fleet.ts`, `server/app.ts`, `server/env.ts`, `server/middleware/admin.ts`, `scripts/wrangler_config.mjs`, `.github/workflows/deploy-cloudflare.yml`, `deployments/production.json`, `tests/test_fleet_settings.mjs`, `tests/test_wrangler_config.mjs`, `tests/test_worker_routes.mjs`, `tests/test_job_auth.mjs`, `docs/engineering/api-reference.md`.
- Build: `fleetSettings(env)` parsing `FLEET_ENABLED`, `FLEET_MAP_ENABLED` (default false) like `advisorSettings`. `fleetRouter` mounted unconditionally; a gate middleware answers 404 per request when off. `FLEET_JOB_SCOPE` (§12) and a `requireFleetJob` middleware using `verifyJobToken`. `GET /api/fleet/jobs/ping` (job-authenticated, returns `{ok, region}`). `adminUser` passes when advisor or fleet is enabled. Wrangler config copies `FLEET_*` vars; deploy workflow passes them; scheduler workflows list gains the four fleet workflows.
- Accept: 1. With both flags unset every `/api/fleet/*` route answers 404. 2. With `FLEET_ENABLED=true` a valid OIDC token for `fleet-ais.yml` reaches `ping`; a token for `advisor-media.yml` gets 401/404. 3. An admin can reach `/admin` with only `FLEET_ENABLED` on; with both off, 404 as today. 4. The `Env` type test passes with the new vars.
- Tests: settings defaults/overrides; route 404/200 across two env objects; scope accept/reject vectors; wrangler vars with and without `FLEET_*`.
- **Owner**: approve (touches `server/`, workflows, `deployments/`).

### CF-02 · Registry schema, migration 0013 · M
- Depends: —
- Files: `db/schema.ts`, `drizzle/0013_fleet_registry.sql` + `drizzle/meta/*` (generated), `tests/test_fleet_schema.mjs`.
- Build: the 0013 tables in §5 with the listed columns, defaults and indexes, and `advisor_boats.fleet_vessel_id` with index `boat_fleet`. `source_url`, `source_id`, `retrieved_at`, `method`, `confidence` and `rights` are `notNull` on `fleet_vessel_facts`. Generate with `pnpm db:generate --name fleet_registry`.
- Accept: 1. `tests/test_migrations.mjs` passes unchanged. 2. The migration applies on a fresh SQLite and on one with 0012 data, leaving `advisor_boats` rows intact. 3. Every index named in §5 exists. 4. A fact insert without `source_url` fails. 5. `fleet_vessels.map_display_consent` (`none`, `aggregate`, `named`) is NOT NULL with default `none`, and `fleet_operators.user_id` is nullable (US-C4, US-B3). 6. `fleet_vessels.removal_requested_at` and `fleet_operators.consent_revoked_at` exist as nullable ISO text columns with no default (US-C3, US-S3).
- Tests: apply migrations to the D1 fake; assert columns, indexes and NOT NULLs.

### CF-03 · Activity schema, migration 0014 · S
- Depends: CF-02 (serial: both edit `db/schema.ts` and the migration journal)
- Files: `db/schema.ts`, `drizzle/0014_fleet_activity.sql` + meta, `tests/test_fleet_schema.mjs`.
- Build: the 0014 tables in §5, including `fleet_trip_reports` (no code fills it yet). `fleet_events.basis` defaults to `inferred-from-movement`.
- Accept: 1. Migration parity test passes. 2. Indexes as listed. 3. `fleet_events.basis` default asserted. 4. US-B4 join fixture: a synthetic trip, an `advisor_reports` row on a linked `advisor_boats` row, and a landing-report row (boat alias + port + date) each resolve to the trip through the `fleet_trip_reports` keys (`vessel_id` + `local_date`; `fleet_aliases.alias_norm` + port + date) with plain SQL.
- Tests: as CF-02, plus the join fixture.

### CF-04 · Region config schema, CA config, shared catalog, loader · M
- Depends: —
- Files: `schemas/fleet-region.schema.json`, `src/skippercast/validate.py` (`fleet-region` kind), `scripts/build-worker.mjs` (skip directories without `region.json`), `regions/CA/fleet.json`, `catalog/fleet/resolver.json`, `catalog/fleet/off-limits.json`, `catalog/fleet/lead-score.json`, `src/skippercast/fleet/__init__.py`, `src/skippercast/fleet/config.py`, `tests/contract/test_fleet_region.py`, `tests/unit/test_fleet_config.py`.
- Build: the schema and keys in §3; `regions/CA/fleet.json` with all CA ports from the coverage estimate (Crescent City to San Diego, the Bay and the Delta), landings, generous hand-drawn harbor geofences (`geofence_source: "drawn"`, refined from charts later), the AIS bbox, agencies, source bindings and the thresholds in §3. `load_region(id)` validates the file and the catalog files and returns typed objects. Region config and its loader ship together as the deliberate exception to the data/code split (no other consumer).
- Accept: 1. The contract test checks every rule listed at the end of §3. 2. No CA-specific literal in `src/skippercast/fleet/` (a test greps for `"CA"` and port ids). 3. `regions/*/region.json` enumeration (platform build, region contract) is unaffected: `PYTHONPATH=src python -m skippercast.platform.build && git diff --exit-code` is clean. 4. Ports with a `home_port` match `catalog/home-ports.json` ids.
- Tests: contract test; loader errors on a missing geofence, an unknown adapter, an off-limits host.

### CF-05 · Profile schema, validator, repo-hygiene scan · M
- Depends: —
- Files: `schemas/fleet-profile.schema.json`, `src/skippercast/fleet/profile.py`, `tests/fixtures/fleet/profiles/*.json` (3 synthetic: party, six-pack, invalid), `tests/unit/test_fleet_profile.py`, `scripts/check_repository.py`, `tests/unit/test_check_repository.py`, `CONTRIBUTING.md`.
- Build: the schema from the pilot with the §8 changes; `validate_profile(doc) -> list[str]` (schema plus every §8 policy check); scan scopes extended to `tests/fixtures/fleet/` and `docs/plans/charter-fleet/`; one `CONTRIBUTING.md` line naming fleet registry data, OSINT output, positions and outreach as private records.
- Accept: 1. Valid fixtures pass and the invalid one reports each seeded error (off-limits `source_url`, MMSI disagreement without conflict, review text in `reputation.other`). 2. A non-555 phone or unlisted handle in a fleet fixture fails `check_repository.py`. 3. `tests/contract/test_schemas.py` still passes.
- Tests: as named; a run of the validator over all fixtures.

### CF-06 · ADR, data-rights rows, threat model · S
- Depends: —
- Files: `docs/engineering/adr/0008-charter-fleet-registry-and-ais.md`, `docs/engineering/adr/README.md`, `docs/legal/data-rights-register.md`, `docs/legal/threat-model.md`, `docs/data-sources.md`.
- Build: ADR for D2, D3, D6, D8 (state-level config, raw AIS off D1, headless OSINT, aisstream with adapter). Register rows: FCC ULS, PSIX, TECK.net (facts only, permission pending), landing and operator sites, Google Places, CPRA list, aisstream (no terms), MarineCadastre (FAQ conditions, not plain CC0). Threat-model section: `/go/` redirect, fleet job routes, admin and outreach data, Hermes listener. Correct the CC0 label for MarineCadastre in `docs/data-sources.md` to cite the NOAA FAQ (June 2026) conditions: "coastal and ocean planning purposes", citation, no fee for usage.
- Accept: 1. Each legal judgment is marked owner/counsel to confirm. 2. Every source in §6's table has a row. 3. `docs/data-sources.md` no longer describes MarineCadastre as plain CC0 and quotes the NOAA conditions with the FAQ link.
- **Owner**: approve (`docs/legal/`).

## Phase 1: registry pipeline

### CF-10 · Pipeline skeleton: CLI, runs, sinks, fleet HTTP session · L
- Depends: CF-01, CF-02, CF-04 (parallel with CF-11)
- Files: `src/skippercast/fleet/__main__.py`, `cli.py`, `runs.py`, `sinks.py`, `net.py`, `adapters/__init__.py`, `adapters/base.py`, `pyproject.toml` (`fleet` extra), `tests/unit/test_fleet_net.py`, `tests/unit/test_fleet_sinks.py`.
- Build: `python -m skippercast.fleet <step> --region --sink --run-id` with steps registered but empty; run directories under `$SKIPPERCAST_FLEET_VAR` (§4); `SqliteSink` applying `drizzle/*.sql` in order and executing operations; `WorkerSink` with OIDC token fetch (pattern of `scripts/advisor/media_job.py`), 500-op batching, backoff; `dry-run` regions refuse `WorkerSink`. `net.py` as in §6 (allowlist, off-limits deny incl. redirects, robots, interval, per-host budget).
- Accept: 1. Off-limits URLs and redirects to them are refused before any socket opens. 2. A robots-disallowed path is a recorded skip. 3. SqliteSink creates all `fleet_*` tables from the committed migrations. 4. Tests are offline.
- Tests: robots and deny via a local fake; sink round-trip; dry-run refusal.

### CF-11 · Worker job API: snapshot and registry upserts · L
- Depends: CF-01, CF-02
- Files: `server/fleet/ids.ts`, `server/fleet/jobs.ts`, `server/fleet/registry.ts`, `server/routes/fleet.ts`, `tests/test_fleet_jobs.mjs`.
- Build: `GET /api/fleet/jobs/snapshot` (paged) and `POST /api/fleet/jobs/registry` with the operation kinds in §9; body ≤ 1 MB, ≤ 500 ops; each op validated (enums, https `source_url` or `admin:`, confidence 0–1); D1 batches chunked under bound-parameter limits; admin-pinned fields are never overwritten; `review.open` never reopens a decided review; a `fleet_runs` row per call.
- Accept: 1. Posting the same batch twice changes no row the second time. 2. A fact without provenance is rejected with the op index. 3. Pinned fields survive an upsert. 4. Snapshot returns decided reviews.
- Tests: with the D1 fake in `tests/_advisor_d1.mjs` and a stubbed token verifier.

### CF-12 · Adapters: FCC ULS and USCG PSIX · M
- Depends: CF-10
- Files: `src/skippercast/fleet/adapters/fcc_uls.py`, `uscg_psix.py`, `tests/fixtures/fleet/fcc/*`, `tests/fixtures/fleet/psix/*`, `tests/unit/test_fleet_registries.py`.
- Build: §6 rows. FCC: download (conditional GET), parse the SH/EN records for the bound state, all statuses; emit candidates with call sign, MMSI, doc number; licensee kept only when an entity. PSIX: sector query, passenger-inspected service filter.
- Accept: 1. A synthetic individual licensee name never appears in output. 2. Same-name licences in different cities yield separate candidates. 3. Expired licences are included with their status.
- Tests: tiny synthetic fixture files.

### CF-13 · Adapters: TECK.net report sites and directories · M
- Depends: CF-10
- Files: `adapters/teck_reports.py`, `adapters/directories.py`, `src/skippercast/pipeline/collect.py` (expose its client factory and cache directory), `tests/fixtures/fleet/teck/*.html`, `tests/fixtures/fleet/directories/*.html`, `tests/unit/test_fleet_teck.py`.
- Build: extends the existing TECK.net fetch in `collect.py` (design § Relationship to the existing reports pipeline): the adapter uses the same `skippercast.http.Session` setup and the same conditional-GET cache directory, not a parallel scraper. Directory paging and the "Boat Information" block parser (name, landing, dimensions, year, load, last report date); GGFA and SAC list parsers; facts only, `rights=facts-only`; no captain phone stored.
- Accept: 1. Parser output on fixtures matches expected JSON. 2. No phone field emitted from these adapters. 3. A changed page layout raises a typed parse error, not empty output. 4. The adapter imports its session/cache from the shared code path used by `collect.py`; no second TECK.net client or cache directory exists (test asserts the cache path). 5. `parsers.charter_reports()` behaviour and the daily-data tests are unchanged.
- Tests: synthetic HTML fixtures modelled on the page structure.

### CF-14 · Adapter: landing pages, offerings and departures · M
- Depends: CF-10
- Files: `adapters/landing_pages.py`, `tests/fixtures/fleet/landings/*.html`, `tests/unit/test_fleet_landings.py`.
- Build: `fr-fleet-php` template (fleet list, boat page specs, captains, rate table, schedule rows → departures with time, price, load) and a `generic` template (names and links only); photos as link + attribution facts.
- Accept: 1. Schedule rows become departures with deterministic ids. 2. Prices parse to cents with basis. 3. No image bytes fetched.
- Tests: synthetic fixtures for both templates.

### CF-15 · Entity resolution · L
- Depends: CF-10
- Files: `src/skippercast/fleet/normalize.py`, `resolve.py`, `tests/unit/test_fleet_resolve.py`.
- Build: §7 steps 1–7 and the resolver over `catalog/fleet/resolver.json` with region overrides; deterministic vessel ids and slugs (unique against snapshot slugs, including advisor slugs).
- Accept: 1. Synthetic cases: rename by doc number (alias + `renamed`), two vessels same name same port with different MMSIs, New-X vs X kept apart, call-sign-only match at 0.9, 0.6–0.9 score opens one `merge` review, decided review honoured. 2. Running resolve twice on the same input gives identical output. 3. Pinned fields untouched.
- Tests: table-driven cases.

### CF-16 · Enrich-code: operator sites, Google Places, CPRA file import · M
- Depends: CF-10
- Files: `adapters/operator_site.py`, `adapters/google_places.py`, `adapters/file_import.py`, `src/skippercast/fleet/enrich.py`, fixtures, `tests/unit/test_fleet_enrich.py`.
- Build: §6 rows. Operator site: ≤ 6 pages, phone/email/social/booking-platform/og:image extraction, webmail flagged. Places: Text Search per port + Details for `place_id`, rating, count (key from `GOOGLE_PLACES_API_KEY`; skips cleanly without it); 30-day purge op. File import: `cdfw-cpfv-v1` CSV columns. Re-read the current Places terms and record the caching rule in the PR.
- Accept: 1. An off-limits booking URL found on an operator page is stored as a value with the operator page as `source_url`. 2. Without a key Places is skipped and reported. 3. Individual licensee names from the CSV are dropped.
- Tests: fixtures and a fake Places transport.
- **Owner**: create the Places API key and add `GOOGLE_PLACES_API_KEY` (link in the PR).

### CF-17 · Ingest, refresh, `run` orchestrator · L
- Depends: CF-11, CF-15
- Files: `src/skippercast/fleet/ingest.py`, `refresh.py`, `coverage.py`, `cli.py`, `catalog/sources.json`, `regions/*/region.json` (`charter-identity` binding and coverage only) + rebuilt `dist/regions/*` (generated), `tests/unit/test_fleet_ingest.py`, `tests/unit/test_fleet_refresh.py`, `tests/unit/test_fleet_coverage_status.py`.
- Build: §9: facts and resolved rows to operations, supersede rules, change detection table, `run` chaining steps with per-step `fleet_runs` and `report.json`. Supersede `operator-identities` (design § Relationship to the existing reports pipeline): add a `fleet-registry` source entry, point each coastal region's `source_bindings.charter-identity` at it, mark `operator-identities` superseded; `coverage-status --region CA` computes each mapped coastal region's `charter-identity` status and an aggregate-only reason from the registry; apply it and rebuild with `PYTHONPATH=src python -m skippercast.platform.build`.
- Accept: 1. From empty, a synthetic two-source fixture run fills vessels, facts, aliases, offerings. 2. A second identical run writes zero changes. 3. Fixture deltas produce exactly one of each: `new`, `renamed`, `sold`, `vanished` (after the configured runs and days), `price`, `schedule`. 4. Every fact row in the staging DB has a non-empty `source_url`. 5. `coverage-status` output on a fixture registry gives the expected status per coastal region and its reason holds counts only (no names, phones or URLs). 6. No region binds `charter-identity` to `operator-identities`; the platform build diff is clean after rebuild; `tests/contract/test_region_contract.py` passes.
- Tests: end-to-end on the SqliteSink with synthetic adapters.

### CF-18 · Workflow `fleet-registry.yml` and runbook · S
- Depends: CF-17
- Files: `.github/workflows/fleet-registry.yml`, `docs/operations/runbooks/fleet-registry.md`, `tests/contract/test_workflow_pins.py` (if it enumerates workflows).
- Build: weekly schedule and dispatch inputs (§9), `DATA_RUNNER`, `if: vars.ENABLE_FLEET == 'true' && vars.DATA_RUNNER != ''`, `id-token: write`, pinned actions, no `pull_request` trigger, `SKIPPERCAST_FLEET_VAR` set outside the checkout.
- Accept: 1. Workflow pin test passes. 2. No `pull_request` trigger. 3. Runbook covers first run, reruns, staging runs.
- **Owner**: set `ENABLE_FLEET=true` and `FLEET_ENABLED=true` when ready (links in the PR).

## Phase 2: OSINT agent step

### CF-20 · Plan-agent manifests and profile ingest · M
- Depends: CF-17, CF-05
- Files: `src/skippercast/fleet/agent.py`, `profile.py` (profile → facts), `ingest.py`, `tests/unit/test_fleet_agent.py`.
- Build: selection rules and manifest format (§8); `ingest --profiles` validating each file, mapping to facts/offerings/reviews, skipping invalid files with a report.
- Accept: 1. Manifests contain only snapshot data and batches of ≤ 20. 2. An invalid profile is refused and listed; valid ones ingest. 3. Re-ingesting the same profiles changes nothing. 4. A missing value in a newer profile does not supersede an older fact.
- Tests: synthetic profiles.

### CF-21 · Headless OSINT runner, workflow, agent definition · M
- Depends: CF-20
- Files: `scripts/fleet/run_osint.py`, `.github/workflows/fleet-osint.yml`, `.claude/agents/charter-osint.md`, `docs/operations/runbooks/fleet-osint.md`, `tests/unit/test_fleet_run_osint.py`.
- Build: §8 headless run: parallel batches, timeouts, resume from `state.json`, refusal when `ANTHROPIC_API_KEY` is set, tool allowlist. Pin the Claude Code CLI version and document the exact flags verified against its `--help`. Verify `.claude/agents/charter-osint.md` still matches D7 (it was rewritten in the plan PR) and add the manifest contract to it.
- Accept: 1. With a fake `claude` binary, batches run, resume and retry once. 2. The runner exits non-zero if `ANTHROPIC_API_KEY` is set. 3. `charter-osint.md` lists no off-limits host as a fetchable source and states the D7 handle rule (a test reads the file and checks it against `catalog/fleet/off-limits.json`). 4. The workflow never triggers on `pull_request`.
- **Owner**: on Hermes as the runner user, run `claude setup-token` and save it per the runbook.

## Phase 3: admin, profile, outreach, links

### CF-30 · Admin API: reviews and vessels · M
- Depends: CF-11
- Files: `server/fleet/admin/reviews.ts`, `server/fleet/admin/vessels.ts`, `server/routes/fleet.ts`, `tests/test_fleet_admin.mjs`.
- Build: §12 review and vessel routes; decisions write `decision_json`; vessel edits create `admin` facts and pin; `link-advisor` sets `advisor_boats.fleet_vessel_id`.
- Accept: 1. Non-admins get 404. 2. Deciding a merge returns in the next snapshot. 3. An admin edit appears as a fact with `source_url = admin:<id>` and the field is pinned.
- Tests: D1 fake, admin session helper used by existing admin tests.

### CF-31 · Admin UI: review queue, vessels · L
- Depends: CF-30
- Files: `web/admin/fleet-review.tsx`, `web/admin/fleet-vessels.tsx`, `web/admin/route.ts`, `web/admin/app.tsx`, `web/admin/api.ts`, `e2e/fleet-admin.spec.ts`.
- Build: §13 review and vessel views.
- Accept: 1. `pnpm typecheck && pnpm build && node scripts/check_client.mjs` pass. 2. Tabs hidden when the fleet flag is off. 3. Playwright: decide a review, edit a field, see the pinned marker.

### CF-32 · Operators, outreach, lead score · M
- Depends: CF-30, CF-03
- Files: `server/fleet/admin/operators.ts`, `server/fleet/leadscore.ts`, `server/routes/fleet.ts`, `web/admin/fleet-operators.tsx`, `web/admin/route.ts`, `tests/test_fleet_outreach.mjs`.
- Build: §13 operators and outreach; lead score from `catalog/fleet/lead-score.json` (bundled at build) with parts.
- Accept: 1. No route or function sends a message (test greps the module for channel/send imports). 2. Draft → approve → "log as sent by owner" transitions only. 3. `do-not-contact` blocks new drafts. 4. Consent changes record who and when.

### CF-33 · Public boat profile and advisor link · M
- Depends: CF-11, CF-01
- Files: `server/advisor/pages/boat.ts`, `server/advisor/pages/data.ts`, `server/advisor/pages/sitemap.ts`, `server/routes/advisor.ts`, `tests/test_fleet_profile_page.mjs`.
- Build: §13 public profile; the `/boats/*` gate passes when either flag is on; registry-only profiles `noindex` and out of the sitemap until the operator consents.
- Accept: 1. With `FLEET_ENABLED` off the page is byte-identical to today for advisor boats. 2. Hidden, excluded or inactive vessels 404. 3. No AIS data or `noaa-planning-only` fact renders. 4. The Google aggregate rating and review count render only with the Google attribution and only while the fact is within its 30-day window; no review text renders. 5. Links go through `/go/`.

### CF-34 · `/go/<slug>` redirect and click counts · S
- Depends: CF-01, CF-02
- Files: `server/fleet/go.ts`, `server/routes/fleet.ts`, `server/analytics.ts`, `server/fleet/admin/clicks.ts`, `tests/test_fleet_go.mjs`.
- Build: §12 `/go/`, daily counters, Analytics Engine point, admin clicks endpoint.
- Accept: 1. A `?url=` or any request-supplied target is ignored. 2. Non-https stored URLs 404. 3. UTM appended, existing params kept. 4. No IP, UA or referrer stored.

### CF-35 · Coverage page and AIS health view · M
- Depends: CF-30, CF-03
- Files: `server/fleet/admin/coverage.ts`, `server/fleet/admin/ais-health.ts`, `server/routes/fleet.ts`, `web/admin/fleet-coverage.tsx`, `web/admin/fleet-ais.tsx`, `web/admin/route.ts`, `tests/test_fleet_coverage.mjs`.
- Build: §13 coverage metrics from D1 (by port and class: boats, completeness by group, % MMSI, % seen 30 d, single-source boats, runs), and the `#fleet-ais` view with `GET /api/admin/fleet/ais/health` (§13 AIS health: last message age, messages per minute, reconnects and drops 24 h, gaps over 10 minutes, 7- and 30-day uptime from `fleet_ais_hours`, last processor run, watch list size).
- Accept: 1. Percentages computed on a seeded fixture match hand-computed values. 2. Boats with no AIS show as "not seen", never as non-compliant. 3. On seeded `fleet_ais_hours` and `job_state` rows, `ais/health` returns the expected uptime %, gap list (> 10 min) and last-message age. 4. Both routes 404 for non-admins and with `FLEET_ENABLED` off.

## Phase 4: AIS

### CF-40 · AIS store, source interface, aisstream adapter · M
- Depends: CF-04
- Files: `src/skippercast/fleet/ais/__init__.py`, `store.py`, `sources/base.py`, `sources/aisstream.py`, `sources/datalastic.py`, `tests/fixtures/fleet/ais/aisstream/*.json`, `tests/unit/test_fleet_ais_store.py`.
- Build: day-file schema and writer, retention, `AisSource`, aisstream message normalisation and subscription message, Datalastic stub.
- Accept: 1. Duplicate `(mmsi, ts, source)` inserts are ignored. 2. Retention deletes only day files past the limit and never `validation/`. 3. Every listed message type normalises.

### CF-41 · Listener service · M
- Depends: CF-40
- Files: `src/skippercast/fleet/ais/listener.py`, `watch.py`, `tests/unit/test_fleet_listener.py`.
- Build: §10 service: queue, writer, drop order, reconnect with jitter, idle reconnect, watch reload, heartbeat file, discovery buffer rules.
- Accept: 1. With a fake socket, a disconnect reconnects with growing delay. 2. Under a full queue watched positions are kept over discovery. 3. Unwatched positions outside geofences are never written. 4. Heartbeat updates every interval.

### CF-42 · Listener deployment: unit, workflow, runbook · S
- Depends: CF-41
- Files: `scripts/fleet/skippercast-fleet-ais@.service`, `scripts/fleet/install_listener.sh`, `.github/workflows/fleet-ais-listener.yml`, `docs/operations/runbooks/fleet-ais-down.md`, `docs/operations/runners.md`.
- Build: §10 install flow with the 90-second heartbeat check.
- Accept: 1. Dispatch only. 2. Env file written 0600; the key never echoed. 3. Runbook covers restart, logs (`journalctl --user -u`), rollback to the previous `<sha>`.
- **Owner**: aisstream key and `AISSTREAM_API_KEY` secret; `loginctl enable-linger`; dispatch the workflow once.

### CF-43 · Trip segmentation and classification · L
- Depends: CF-40
- Files: `src/skippercast/fleet/ais/segment.py`, `classify.py`, `tests/unit/test_fleet_classify.py`.
- Build: §11 segmentation and classification with config thresholds and `classifier_version`.
- Accept: 1. Synthetic tracks: a harbor shuffle yields no trip; a drift at 1 kn for 30 min yields `fishing-drift`; a 6 kn zig-zag yields `fishing-troll`; a straight 6 kn run yields `transit`; a 3 h mid-sea gap yields a `gap` segment. 2. Changing a threshold changes `classifier_version`. 3. Same input, same output.

### CF-44 · Events, simplification, aggregate module · M
- Depends: CF-43
- Files: `src/skippercast/fleet/ais/events.py`, `simplify.py`, `aggregate/base.py`, `aggregate/grid.py`, `tests/unit/test_fleet_events.py`.
- Build: §11 events (median, p90 radius, `basis`), Douglas-Peucker + polyline encoding, grid aggregator with the privacy knobs honoured when set.
- Accept: 1. Encoded polylines decode within tolerance. 2. With `min_distinct_vessels=3` a two-vessel cell is suppressed; with `null` it is kept. 3. Aggregate `rights` is the most restrictive input.

### CF-45 · Processor job, activity routes, health alerting · L
- Depends: CF-44, CF-11, CF-03
- Files: `src/skippercast/fleet/ais/process.py`, `server/fleet/activity.ts`, `server/routes/fleet.ts`, `.github/workflows/fleet-ais.yml`, `.github/workflows/fleet-health.yml`, `scripts/ops_report.py`, `tests/test_fleet_activity.mjs`, `tests/unit/test_fleet_process.py`.
- Build: §11 run sequence except the watch-list refresh and MMSI matching (CF-46 adds those as hooks in `process.py`); `activity`, `heartbeat`, `health` routes; replace-window delete+insert in one batch; `fleet-health.yml` on `ubuntu-latest` opening/closing the `fleet-ais-stale` issue; ops-report line.
- Accept: 1. Reprocessing a window twice leaves identical rows. 2. Replace-window touches only the given MMSIs, source and window. 3. Health reports stale at > 3 h on a fixture clock. 4. `fleet-health.yml` runs on `ubuntu-latest` with exactly `id-token: write` (for the OIDC health route) and `issues: write`, nothing wider. 5. `process.py` runs without any watch or match module present.
- **Owner**: approve workflows.

### CF-46 · MMSI matching and watch list · M
- Depends: CF-41, CF-11, CF-03, CF-45
- Files: `src/skippercast/fleet/ais/match.py`, `src/skippercast/fleet/ais/process.py` (hooks: refresh `watch.json`, run matching), `server/fleet/watch.ts`, `server/routes/fleet.ts`, `tests/unit/test_fleet_match.py`, `tests/test_fleet_watch.mjs`.
- Build: §11 three-stage matching; the processor hooks that refresh `watch.json` from the Worker and run matching each cycle; watch GET/POST routes; disagreeing statics recorded as `ais` facts; weak matches → `mmsi` reviews.
- Accept: 1. A same-name pleasure boat (type 37, wrong length, never in the port geofence) stays a candidate. 2. Three distinct days in the home geofence promote to watched. 3. Registry MMSI is never overwritten by AIS. 4. One processor run refreshes `watch.json` and pushes match updates.

### CF-47 · MarineCadastre backfill · M
- Depends: CF-44, CF-45
- Files: `src/skippercast/fleet/ais/sources/marinecadastre.py`, `backfill.py`, `.github/workflows/fleet-ais.yml` (dispatch input), `tests/unit/test_fleet_backfill.py`.
- Build: §11 backfill: streaming zstd CSV, bbox and MMSI filter, separate store, same processor, `noaa-planning-only` tag.
- Accept: 1. Every derived row carries `source=marinecadastre` and the rights tag. 2. Streaming memory stays bounded (test with a generated multi-MB file). 3. Re-running a day is idempotent.

### CF-48 · Labelling view and validation report · M
- Depends: CF-45, CF-31
- Files: `server/fleet/admin/labels.ts`, `web/admin/fleet-trip.tsx`, `web/admin/route.ts`, `src/skippercast/fleet/ais/validate.py`, `tests/unit/test_fleet_validate.py`, `tests/test_fleet_labels.mjs`.
- Build: §11 validation and §13 labelling view; copy labelled trips' positions to `validation/`.
- Accept: 1. Precision and recall on a synthetic labelled set match hand-computed values. 2. Labels record labeller and basis. 3. Labelled raw data is exempt from retention.
- **Owner**: label ≥ 30 trips, or approve an agent-labelled set.

## Phase 5: map

### CF-50 · Map API · M
- Depends: CF-03, CF-01
- Files: `server/fleet/map.ts`, `server/routes/fleet.ts`, `tests/test_fleet_map.mjs`.
- Build: §14 endpoints (filters, events, tracks, heat) as GeoJSON with every filter, caps and paging; admin and `FLEET_MAP_ENABLED` only.
- Accept: 1. Each filter narrows a seeded fixture as expected. 2. Caps enforced. 3. Every feature carries `basis` and `rights`. 4. 404 for non-admins or with the flag off.

### CF-51 · Map layers in the client · L
- Depends: CF-50
- Files: `dist/fleet-activity.js`, `dist/index.html`, `dist/app.js`, `dist/styles.css`, `tests/test_fleet_layers.mjs`.
- Build: §14 layers, toggles, filter card and details card following `dist/commercial-ais.js`.
- Accept: 1. Toggles absent for non-admins and with the flag off. 2. The event card shows the "inferred from movement" sentence. 3. `pnpm build`, `node scripts/check_client.mjs`, `python scripts/check_web.py` and `node scripts/check_copy.mjs` pass.

## Phase 6: second region and reporting

### CF-60 · Oregon config and staging dry run · M
- Depends: CF-17, CF-12, CF-13, CF-16
- Files: `regions/OR/fleet.json`, `tests/contract/test_fleet_region.py` (picks it up), `docs/plans/charter-fleet/README.md` (status line).
- Build: §21 config; run the dry run on Hermes; summarise counts (no registry data) in the PR.
- Accept: 1. No file under `src/` changes. 2. The contract test passes for OR. 3. A test proves `--sink worker` is refused for `OR`. 4. The PR records boats by port and class from the staging report.

### CF-61 · Fleet report tool · M
- Depends: CF-35, CF-45, CF-48
- Files: `src/skippercast/fleet/report.py`, `cli.py`, `tests/unit/test_fleet_report.py`.
- Build: `python -m skippercast.fleet report --region CA` from the snapshot and admin coverage data: boats by port and class, completeness %, MMSI and seen-30-day %, ingestion uptime (7 and 30 days, longest run of consecutive full days), validation precision/recall, run failures, and the monthly cost line (§19). Output Markdown and JSON under `<FLEET_VAR>`; aggregates only, no contact data.
- Accept: 1. Output on a seeded fixture matches expected numbers. 2. No phone, email or URL appears in the Markdown.

### CF-62 · Full California run and first activity map · S (operational)
- Depends: all above
- Files: `docs/plans/charter-fleet/README.md` (status log only).
- Build: run the registry, OSINT and second registry pass for `CA`; work the review queue down; confirm 7+ consecutive days of ingestion; run validation; record the fleet report's aggregate numbers and link the admin map in the status log.
- Accept: 1. The status-log line records boats by port and class, MMSI % and seen-in-30-days %. 2. Ingestion uptime shows ≥ 7 consecutive full days from `fleet_ais_hours`. 3. The validation report covers ≥ 30 labelled trips with precision and recall. 4. The open review-queue count is recorded. 5. The report and status line contain no contact data (no phones, emails, handles or operator URLs).
- **Owner**: flip `FLEET_MAP_ENABLED`; work or approve the review queue.

## Parallelism

- Phase 0: CF-01, CF-02, CF-04, CF-05, CF-06 in parallel; CF-03 after CF-02.
- Phase 1: CF-10 and CF-11 in parallel (both after CF-01 and CF-02); then CF-12, CF-13, CF-14, CF-15, CF-16 in parallel; CF-17 after CF-11 and CF-15; CF-18 after CF-17.
- Phase 3 can start once CF-11 merges, alongside Phase 1 adapters: CF-30, CF-33, CF-34 in parallel; CF-31, CF-32, CF-35 after CF-30.
- Phase 4 can start once CF-04 merges: CF-40, then CF-41 and CF-43 in parallel; CF-42 after CF-41; CF-44 after CF-43; CF-45 after CF-44; then CF-46 and CF-47 in parallel after CF-45.
- Phase 5 CF-50 can start after CF-03 and CF-01.
- Conflict hot spots: `db/schema.ts` (CF-02, CF-03 only); `server/routes/fleet.ts` (many tasks: keep each hunk to route registration and rebase); `web/admin/route.ts` (CF-31, CF-32, CF-35, CF-48: merge in that order); `dist/index.html` (CF-51 only). A later task that needs a schema change generates the next free migration number after rebasing.

## Dependency graph

```
CF-01, CF-02, CF-04, CF-05, CF-06: no dependencies
CF-02 ─► CF-03
CF-01 + CF-02 + CF-04 ─► CF-10 ─► CF-12, CF-13, CF-14, CF-15, CF-16
CF-01 + CF-02 ─► CF-11                      (CF-10 and CF-11 run in parallel)
CF-11 + CF-15 ─► CF-17 ─► CF-18
CF-17 + CF-05 ─► CF-20 ─► CF-21
CF-11 ─► CF-30 ─► CF-31
CF-30 + CF-03 ─► CF-32
CF-30 + CF-03 ─► CF-35
CF-11 + CF-01 ─► CF-33
CF-01 + CF-02 ─► CF-34
CF-04 ─► CF-40 ─► CF-41 ─► CF-42
CF-40 ─► CF-43 ─► CF-44
CF-44 + CF-11 + CF-03 ─► CF-45
CF-41 + CF-11 + CF-03 + CF-45 ─► CF-46
CF-44 + CF-45 ─► CF-47
CF-45 + CF-31 ─► CF-48
CF-01 + CF-03 ─► CF-50 ─► CF-51
CF-17 + CF-12 + CF-13 + CF-16 ─► CF-60
CF-35 + CF-45 + CF-48 ─► CF-61
all ─► CF-62
```

## Backlog (no task yet)

Stories, or parts of stories, that the plan scopes **Later** and no task above
builds. Each needs its own task (id, dependencies, files, acceptance) before
work starts.

- **US-C2 public correction form.** A "Report a correction" link on the boat
  profile opening a short form (or the Text Advisor chat) that creates a
  `fleet_reviews` item with field, proposed value and business contact; rate
  limiting and spam handling; approval writes a `method = operator` fact
  through the CF-30 review action.
- **US-A6 trip-planner API.** A public, flag-gated endpoint (and later UI)
  answering "boats from my port targeting species X this week" from
  `fleet_offerings`, `fleet_departures` and recent reports; caching, and only
  `listed` vessels.
- **CSV click export (US-S5, US-C6).** A CSV download of per-vessel monthly
  clicks by UTM source and placement from `fleet_link_clicks`, added to the
  CF-34 admin clicks endpoint; sending the report to operators stays a
  separate later task.

## Definition of done

Matches the owner's "Done when":

1. **Registry from empty**: `fleet-registry.yml` → `fleet-osint.yml` →
   `fleet-registry.yml` for `CA` on an empty registry fills it; the only human
   input is the review queue (CF-17, CF-18, CF-21, evidenced in CF-62).
2. **Safe re-runs and refreshes**: the second identical run writes nothing,
   and fixture tests show `new`, `renamed`, `sold`, `vanished`, `price` and
   `schedule` changes (CF-11, CF-17); scheduled weekly runs are live.
3. **New region = config + adapters**: `regions/OR/fleet.json` dry run to
   staging with no `src/` change and no Worker write (CF-60).
4. **Every fact has a source**: NOT NULL provenance columns (CF-02), op
   validation (CF-11), profile validation (CF-05), and the staging check in
   CF-17.
5. **Real-time ingestion 7+ consecutive days with monitoring**: listener and
   health alerting live (CF-41, CF-42, CF-45), shown by `fleet_ais_hours` in
   the fleet report (CF-61); **classification validated** on ≥ 30 labelled
   trips with precision and recall reported (CF-48).
6. **All stops and routes on the map behind a flag with the filters**: boat,
   port, vessel class, trip type, activity type, date range, season (CF-50,
   CF-51).
7. **Costs**: design §19 holds the monthly estimate; actual costs are logged
   monthly once live (CF-61, **Owner** confirms against invoices).
