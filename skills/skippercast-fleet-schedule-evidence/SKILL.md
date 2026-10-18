---
name: skippercast-fleet-schedule-evidence
description: Maintain private California charter schedule snapshots and conservative AIS identity evidence from the existing data pipeline. Use for schedule evidence collection, status, or review; it never starts AIS collection, changes the watch list, approves identities, or claims fishing from a schedule.
---

# Keep charter schedule evidence separate from AIS conclusions

This skill maintains a private, append-only SQLite record of published charter schedules and evidence from the existing California AIS listener. It is deterministic and uses no model in routine runs. The registry and watch list remain owned by `$skippercast-fleet-registry`; AIS processing and fishing classification remain owned by `$skippercast-fleet-activity`.

Read `AGENTS.md`, `CONTRIBUTING.md`, the fleet registry and activity skills, [the fleet design](../../docs/plans/charter-fleet/design.md), and [the schedule evidence runbook](../../docs/operations/runbooks/fleet-schedule-evidence.md) before making changes.

## What is collected

The CA collector walks only enabled `landing-pages` bindings from `regions/CA/fleet.json`. It reuses the landing-page parser, the TECK adapter's `teck_client`, and the existing HTTP cache. The underlying `FleetSession` enforces the configured host allowlist, off-limits denylist, robots.txt, redirects, public-address checks, byte caps, retries, and per-host delay/budget.

Each run reviews at most 20 page responses, sequentially (one active host at a time), and stops within 15 minutes. A user systemd timer runs every 12 hours. A nonblocking file lock prevents overlap. The default private database is:

`~/.local/share/skippercast/fleet/CA/schedule-evidence/evidence.sqlite3`

The collector stores factual fields only: source and trip IDs, source/page URLs, boat, landing/operator and port labels, trip date/type/duration, published local departure time, a derived return time only when the existing parser exposes a duration, timezone, uncertainty, source retrieval time, parser version, rights basis, revisions, and content hashes. Target species remain unknown unless a future reviewed parser extracts an explicit field. Prices, seat counts/load text, contact details, photos, page bodies, and catch-report prose are not copied into the evidence database.

The requested Seaforth `fishcounts.php` URL is checked for reachability and represented by retrieval time, status, hash and rights metadata only. A successful fetch is not evidence that a particular boat sailed. Landing-page facts are retained for internal/private research; the rights register says commercial reuse needs owner/counsel review.

## How to run and report

- `scripts/fleet/install_schedule_evidence.sh CA` installs the user-scoped service and 12-hour timer. It needs no `sudo`, new credentials, paid APIs or changes to the AIS listener.
- `python scripts/fleet/schedule_evidence.py --region CA --report` reads count-only status without network access or writes.
- `python scripts/fleet/schedule_evidence.py --region CA --max-pages 20 --deadline-seconds 900` runs one bounded collection using the repository's fleet Python runtime and `SKIPPERCAST_FLEET_VAR`.
- Both commands report counts only. Do not print boat names, source rows, MMSIs, call signs, trip IDs, exact evidence windows or DB contents in chat, issue comments or pull requests.

A failed fetch or changed page layout is recorded as a source skip/status. Keep the prior schedule revisions. A boat or trip disappearing from a source is **unknown**, not cancelled. Cancellation or substitution is recorded only when the page exposes an explicit, machine-readable marker tied to that trip. Never infer cancellation from a missing row.

## AIS evidence and interpretation

The collector reads `ais/state.sqlite` and retained raw daily stores read-only. It compares an exact normalized boat-name string to existing `match_statics`, then summarizes relevant received positions by time window and reception gaps. It stores no coordinates and never changes the AIS store, registry, watch list or processor state. Its possible outcomes are `abstain`, `candidate-unconfirmed`, or `competing-candidates`; there is no automatic verified/approved identity state. A single name hit is still only a candidate. Missing observations and receiver gaps stay visible as missing coverage, never as proof that a trip did not happen.

AIS names, call signs, and other static fields are self-reported. The separate `identity_evidence` table records an explicit source class and a strict field allowlist; the current collector writes only `ais-self-reported` facts. Its schema can distinguish `official-register` (FCC/PSIX) or `official-vivs` facts, but no official record is currently written to this database. The repository already has FCC ULS and USCG PSIX adapters; a one-sector PSIX check through its existing route returned an HTTP status error on 2026-10-12, and the FCC weekly download was not verified after a 403 HEAD response and a 41.75 MB file-size limit. Do not retry by bypassing source access controls. VIVS access is restricted to authorized federal/state law-enforcement users. No owner/person/contact/address fields are in the evidence schema. Official record collection may be added when the current public adapter path returns validated rows under existing policy; source failure must not block schedules. A VIVS no-result is a coverage gap, not a mismatch. A difference in vessel dimensions by itself is not proof of a wrong identity.

Schedules express intent. Catch reports express what was reported. AIS records describe received transmissions. None alone proves passengers, departure, or fishing. Do not use schedule/AIS correlations to validate or retune the fishing classifier. If evaluating either identity matching or the fishing classifier, keep those test sets separate and hold out boats and time periods.

## Guardrails

- Do not start, duplicate, backfill or dispatch AIS collection; the existing `skippercast-fleet-ais@CA` listener and 30-minute workflow already do that.
- Do not promote an AIS match, write a watch row, label a trip, or use a classifier result as identity evidence.
- Do not bypass robots, logins, host allowlists, terms or the page/deadline cap. Do not access paywalled or off-limits sites.
- Keep database, HTTP cache, source outputs and local logs private under the fleet data directory. Never commit them.
- Stop and ask the parent when source identity is ambiguous, source terms/access change, the requested host is not already allowed, a page layout cannot be interpreted deterministically, or installation requires a security-sensitive grant.
- Do not install the timer or claim it is active until a bounded run succeeds and the timer's first scheduled run also succeeds.
