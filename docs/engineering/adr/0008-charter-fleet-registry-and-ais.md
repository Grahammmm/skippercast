# 0008. Charter fleet: state-level region config, a headless OSINT step, raw AIS kept off D1, and aisstream behind a source adapter

- **Status:** Accepted (owner decisions D2, D3, D6 and D8 in the charter fleet plan brief, 2026-10-04). The data-rights judgments it relies on are **owner/counsel to confirm** (see Links).
- **Date:** 2026-10-04

## Context

- The owner wants a re-runnable registry of every for-hire fishing boat in a
  region (California first, six-packs to San Diego long range), a sourced
  public profile per boat, an AIS match per boat, and a map of where those
  boats go (plan: `docs/plans/charter-fleet/`).
- SkipperCast's regions today are coastal map regions (`regions/<id>/region.json`).
  A charter fleet is organised by state: one licence list (CDFW CPFV), one
  set of state agencies, ports that span several coastal regions.
- Most boat facts come from deterministic sources (FCC ULS ship licences,
  USCG PSIX, TECK.net report sites, landing pages, Google Places). The
  21-boat pilot found about 40% of fields need judgment over varied operator
  sites, which a scheduled agent can do. The owner chose subscription auth
  for that agent, with no API key (D6).
- Raw AIS is high volume (a statewide box holds about 2,250 to 2,720 vessels a
  day in the 2025–2026 MarineCadastre sample), sensitive (it shows where an
  operator fishes) and, for the free real-time source, licensed by no
  published terms. D1 is the Worker's only database and is size- and
  write-limited.
- aisstream.io is free and supports a bounding box with up to 200 MMSIs per
  subscription, but publishes no terms (`/terms` returns 404, and the
  GitHub issues asking about commercial use are unanswered). Datalastic is
  the priced alternative (from €199/month).

## Decision

1. **State-level fleet config (D2).** Each fleet region has
   `regions/<id>/fleet.json`, validated by `schemas/fleet-region.schema.json`:
   ports, landings, harbor geofences, AIS bounding box, state agencies,
   adapter bindings and thresholds. Region `CA` is a state-level fleet region;
   each fleet port maps onto an existing coastal region id where one exists.
   Nothing California-specific lives in `src/`; a new state needs a
   `fleet.json` and any state-specific adapters.
2. **Registry in D1, raw AIS on Hermes (D3).** Vessels, operators, offerings,
   provenance facts, aliases, reviews, outreach, link clicks, the AIS watch
   list and *derived* trips, segments, events and aggregates live in D1 under
   a `fleet_` prefix (schema in `db/schema.ts`, drizzle-kit migrations).
   Raw positions never reach D1 or git: they stay in one SQLite file per UTC
   day under `$SKIPPERCAST_FLEET_VAR` on Hermes, kept 30 days (discovery 7,
   statics 90).
3. **A pipeline of idempotent steps, with a headless OSINT step (D6).**
   `python -m skippercast.fleet` runs `discover`, `resolve`, `enrich-code`,
   `enrich-agent`, `ingest` and `refresh` per region. `enrich-agent` runs
   `claude -p` with the `charter-osint` definition on Hermes under the owner's
   subscription login, never an API key (the script exits if
   `ANTHROPIC_API_KEY` is set). Its output must validate against
   `schemas/fleet-profile.schema.json` before `ingest` sends it to the
   Worker's OIDC job API.
4. **aisstream.io behind an `AisSource` adapter (D8).** A long-running
   listener (user systemd unit on Hermes) reads aisstream; a processor job
   every 30 minutes derives trips and events and pushes only derived rows.
   `marinecadastre` (history) and `datalastic` (stub until the owner pays)
   implement the same interface, so a source change is configuration.
   aisstream data stays internal (admin views and research) until it
   publishes or sends written terms; no live per-vessel display.

## Consequences

- (+) A second state is configuration plus any state-only adapter, not a fork.
- (+) D1 holds only small derived tables; position history can be deleted by
  deleting files, and the public repo never holds positions.
- (+) Judgment work costs nothing beyond the owner's existing subscription,
  and every agent-written fact passes the same validator and provenance rules
  as code-written facts.
- (+) The AIS vendor can change without touching the processor or the Worker.
- (–) Hermes becomes production infrastructure for AIS: a listener that must
  stay up (aisstream has no replay), a heartbeat, a staleness alert from a
  GitHub-hosted job.
- (–) Raw tracks older than 30 days cannot be re-processed; a classifier
  change applies to new data only, unless a labelled trip is kept.
- (–) The OSINT step depends on a subscription login on one machine and on
  the agent following its source rules; the validator and the off-limits
  deny catch violations after the fact, not before.
- (–) Until aisstream's terms exist, no AIS-derived layer can be public or
  paid, and MarineCadastre-derived output carries NOAA's planning-purpose and
  no-fee conditions (data-rights register).

## Alternatives

- **Fleet config inside each coastal `region.json`.** Rejected: one boat list
  and one licence source would be split across a dozen files, and ports
  would be duplicated.
- **Raw positions in D1 or R2.** Rejected: D1 size and write limits, and a
  per-vessel position archive on Cloudflare widens what a Worker bug could
  disclose. R2 remains possible for derived exports.
- **Anthropic API key for the OSINT step.** Not chosen (D6): it adds a
  metered bill for a weekly batch job the subscription already covers;
  deterministic adapters already cover refreshes.
- **Datalastic or another paid feed now.** Deferred to the owner (about $620 a
  month for useful polling, with redistribution terms also unpublished).
- **Global Fishing Watch.** Not used: CC BY-NC and its API is
  non-commercial only.

## Links

- Plan: `docs/plans/charter-fleet/README.md` (D1–D17), `design.md` §§ 3–6,
  8, 10, 17; owner questions Q1, Q2, Q3, Q8 and Q11 in `open-questions.md`.
- Rights: `docs/legal/data-rights-register.md` § Charter fleet registry and
  AIS. Security: `docs/legal/threat-model.md` § 10.
- Related: ADR 0003 (R2 system of record), ADR 0007 (Text Advisor, which
  links skipper boats to registry vessels).
