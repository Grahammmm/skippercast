---
name: skippercast-fleet-activity
description: Check charter fleet fishing activity from AIS through the existing processor jobs, run backfills, reprocessing and classifier validation, and propose threshold changes as PRs. Use for the daily activity cycle or one of those steps; it reads the watch list and never changes it.
---

# Keep the charter fleet's fishing activity honest

The AIS processor turns the watched boats' positions into trips, fishing
segments by mode (`drift-anchor`, `troll-slow`, `troll-pelagic`), events and
heat cells. This skill keeps that running, fills history, scores the
classifier against labelled trips and proposes threshold changes. It reads
the watch list only: `skippercast-fleet-registry` owns it. Read `AGENTS.md`
and `CONTRIBUTING.md` first, then
[design.md § 11](../../docs/plans/charter-fleet/design.md#11-ais-processor)
for the processor, the classifier and validation.

## What runs today, and what does not

| Job | Schedule | Runbook |
| --- | --- | --- |
| listener unit `skippercast-fleet-ais@<region>` | always on; installed by `fleet-ais-listener.yml` | [fleet-ais-down.md](../../docs/operations/runbooks/fleet-ais-down.md) |
| `fleet-ais.yml` | every 30 minutes: process, match, aggregate, sync label copies | [fleet-labelling.md](../../docs/operations/runbooks/fleet-labelling.md) |
| `fleet-health.yml` | hourly; opens the `fleet-ais-stale` issue | [fleet-ais-down.md](../../docs/operations/runbooks/fleet-ais-down.md) |

`fleet-ais.yml` has no region input: it processes `vars.FLEET_REGION`
(default `CA`) and always writes to the Worker. For any other region this
skill runs `report` only.

Nothing schedules this skill yet: an agent session runs it on request. These
parts of #469 are **not built**, and the skill names them as gaps:

- the host check and profile from #468 (`scripts/agentorange/check_host.sh`,
  `docs/operations/agentorange.md`);
- the status script `scripts/check_activity.py`;
- the long-term raw archive and its nightly backup: the raw store keeps
  `thresholds.retention.raw_days` of positions, and no backup job exists;
- the activity-side identity checks (a watched boat that never leaves port,
  moves like a cargo or pleasure vessel, or contradicts its class);
- Hermes scheduling of the skill, and Telegram alerts (the AgentOrange side
  belongs to Codex's trial and coordinator work);
- a workflow that runs `watch-check` or `report` against the live registry:
  both need the fleet-job identity, which exists only inside a fleet workflow
  run on `main`. From a session report `not run (no job identity)`.

## Inputs

- `region`: default `CA`.
- `mode`: `cycle`, `backfill <YYYY-MM>`, `reprocess <from> <to>`, `validate`,
  `tune` or `report`; default `report`.

Commands marked *on the runner* need a shell as the runner user, set up as in
[fleet-labelling.md § 1](../../docs/operations/runbooks/fleet-labelling.md).
Without one, mark those lines `not run (no runner shell)`. `gh` commands take
`--repo Grahammmm/skippercast`.

`fleet-ais.yml` keeps one pending run in its concurrency group: a newer
dispatch or the next scheduled run cancels the pending one. Dispatch one at a
time, check with `gh run list --workflow fleet-ais.yml --event workflow_dispatch --limit 1`
that it started, and wait for it (`gh run watch <run id>`) before the next.

## Modes

### `cycle` (daily)

1. Health: `gh run list --workflow fleet-ais.yml --limit 10 --json databaseId,status,conclusion,createdAt,url`,
   the same for `fleet-health.yml`, and
   `gh issue list --label fleet-ais-stale --state open`. An open stale issue
   is a stop condition.
2. Watch list: `python -m skippercast.fleet.ais watch-check --region <id>`
   (read only; counts by status and method).
3. Raw store growth, *on the runner*: `du -sh "$SKIPPERCAST_FLEET_VAR/<id>/ais/raw"`,
   size only. Report the backup as a gap.
4. Aggregation needs no dispatch: every `ais process` run rebuilds the heat
   cells of the seasons it touched. Take trip and cell counts from the last
   processor run's summary (`gh run view <run id> --log`).
5. Validation, *on the runner*, when label copies exist under
   `<FLEET_VAR>/<id>/ais/validation/`:
   `python -m skippercast.fleet.ais validate --region <id> --offline --labeller admin`.
   Counts and scores only.
6. Identity errors: the `match` hook inside `ais process` already opens
   `mmsi` reviews in the registry queue. Report their count if the owner or
   admin view gives it; never decide them.
7. Owner steps: as `skippercast-fleet-registry` does, one `owner-task` and
   `charter-fleet` issue per missing step, linked to #437 and #458, never a
   duplicate.

### `backfill <month>`

`gh workflow run fleet-ais.yml -f backfill_month=<YYYY-MM>`: NOAA
MarineCadastre history for one month per dispatch, up to 150 minutes each;
wait for it before the next month. Every row is tagged `noaa-planning-only`
and stays off paid surfaces. Unlabelled backfill positions are deleted 30
days after ingest, so labelling follows promptly.

### `reprocess <from> <to>`

`gh workflow run fleet-ais.yml -f from=<YYYY-MM-DD> -f to=<YYYY-MM-DD>`:
re-runs that window of departures with the current classifier, for example
after a threshold change merges. Positions older than the raw store's
retention are gone; reprocess those months from a backfill instead.

### `validate`

`gh workflow run fleet-ais.yml -f validate=true` syncs the labels and their
copies and writes the report to the run summary. Or, *on the runner*:
`python -m skippercast.fleet.ais validate --region <id> --offline`. Report
fishing precision and recall overall and per mode against the targets (0.8
and 0.7), `transit_lost` minutes and the coverage counts. Labelling itself
follows [fleet-labelling.md](../../docs/operations/runbooks/fleet-labelling.md):
the owner approves every agent-proposed label.

### `tune`

*On the runner*, score a candidate:
`python -m skippercast.fleet.ais validate --region <id> --offline --thresholds <json>`,
and the current thresholds without `--thresholds`. Open a PR that changes
`regions/<id>/fleet.json` `thresholds.activity`, with both sets of scores in
its description. Never apply a change silently; after the merge,
`reprocess` the affected window.

### `report`

Status with no side effects beyond the report files `report` writes under
`SKIPPERCAST_FLEET_VAR`:
`python -m skippercast.fleet report --region <id> --sink staging --status-line`
*on the runner* for a staging registry; for the live registry it needs the job
identity (see the gaps), so report from the run summaries instead.

## Guardrails

- Reads the watch list only. Never writes `POST /api/fleet/jobs/watch` or
  decides a review.
- Label times and trip ids never reach logs, issues, PRs or chat. Raw
  positions, exports, proposals and MMSIs stay on the runner: nothing raw goes
  to git or any public surface.
- The public heat route stays behind `FLEET_PUBLIC_HEAT_ENABLED`. It goes live
  only after validation passes and the owner clears Q1, as an owner step
  ([fleet-public-heat.md](../../docs/operations/runbooks/fleet-public-heat.md)).
- `uncertain` segments stay out of the heat cells unless validation shows
  that including them helps, in a reviewed PR.
- Public sources only; no outreach, sign-ups or purchases.
- One run at a time per workflow. Bound each session to 60 minutes: record
  the UTC start and deadline, stop dispatching at the deadline and report.

## Stop and open an owner issue when

- a credential, secret or `gh` permission is denied;
- a workflow fails twice on the same input;
- the listener has been down more than 3 hours (the `fleet-ais-stale` issue;
  [fleet-ais-down.md](../../docs/operations/runbooks/fleet-ais-down.md));
- a step needs `sudo`, money, approval of an agent-labelled set, or any public
  exposure of the heat map.

## End-of-run report

One short message, counts only, no names, ids or label times:

- trips and fishing minutes by mode, where a summary gives them;
- validation scores per mode and overall, `transit_lost`, coverage counts;
- heat cells by mode and season, where a summary gives them;
- listener and processor health, raw store size;
- open owner steps with their issue links, and the workflow runs read or
  dispatched;
- `not available` for each line no command reports today, naming the gap.

## Install

On AgentOrange, symlink this folder from the repository checkout the
`AGENTS.md` AgentOrange section names. For Claude Code:
`ln -s "$PWD/skills/skippercast-fleet-activity" ~/.claude/skills/` from the
checkout root. Where Hermes and Codex load skills is not recorded in this
repository yet: that is part of #468's foundation step.
