---
name: skippercast-fleet-registry
description: Keep the California charter boat registry and its AIS identities current through the existing fleet jobs. Use for the weekly registry cycle, a registry or matching pass, a counts-only look at the review queue, or a status report; it owns the watch list.
---

# Keep the charter fleet registry current

The registry is every for-hire fishing boat in a region, each with a sourced
profile and a likely AIS identity (MMSI) with its method, confidence and
evidence. The watched rows are the watch list, the only hand-off to
`skippercast-fleet-activity`: this skill decides what goes on it, through the
matcher and the owner's review decisions. Read `AGENTS.md` and
`CONTRIBUTING.md` first, then [design.md § 11](../../docs/plans/charter-fleet/design.md#11-ais-processor)
for the match methods and the watched gate.

## What runs today, and what does not

The work itself runs as GitHub Actions jobs on GitHub's schedules, only while
`ENABLE_FLEET` is set. The registry, OSINT and AIS jobs run on the self-hosted
data runner; `fleet-health.yml` runs on GitHub's hosted runner. The registry
and OSINT jobs run only from `main`; `fleet-ais.yml` and `fleet-health.yml`
carry no branch condition and rely on the Worker's job policy instead:

| Job | Schedule | Runbook |
| --- | --- | --- |
| `fleet-registry.yml` | weekly, Monday | [fleet-registry.md](../../docs/operations/runbooks/fleet-registry.md) |
| `fleet-osint.yml` | weekly, Sunday | [fleet-osint.md](../../docs/operations/runbooks/fleet-osint.md) |
| `fleet-ais.yml` | every 30 minutes; matching runs inside it | [fleet-ais-down.md](../../docs/operations/runbooks/fleet-ais-down.md) |
| `fleet-health.yml` | hourly; opens the `fleet-ais-stale` issue | [fleet-ais-down.md](../../docs/operations/runbooks/fleet-ais-down.md) |

Nothing schedules this skill yet: an agent session runs it on request. These
parts of #468 are **not built**, and the skill names them as gaps instead of
working around them:

- the AgentOrange host check `scripts/agentorange/check_host.sh` and the host
  profile `docs/operations/agentorange.md`;
- the status script `scripts/check_registry.py`;
- Hermes scheduling of the skill, and Telegram alerts (the AgentOrange side
  belongs to Codex's trial and coordinator work);
- a workflow that runs `watch-check`, `report` or `coverage-status` against the
  live registry. Those commands read the Worker with the fleet-job identity,
  which exists only inside a fleet workflow run on `main`. From a session they
  stop with an error: report `not run (no job identity)` and move on.

## Inputs

- `region`: a region with `regions/<id>/fleet.json`; default `CA`.
- `mode`: `cycle`, `discover`, `match`, `review` or `report`; default `report`.
- `sink`: `worker` or `staging`. Use `staging` for any region whose
  `fleet.json` `status` is `dry-run` (OR today); the CLI refuses `worker`
  for it. `worker` only for a region whose status is `active`.

Commands marked *on the runner* need a shell as the runner user, set up as in
[fleet-labelling.md § 1](../../docs/operations/runbooks/fleet-labelling.md),
with `SKIPPERCAST_FLEET_VAR` pointing at the fleet data directory (the
`fleet-staging` one for a staging region). Without such a shell, mark those
report lines `not run (no runner shell)`. `gh` commands take
`--repo Grahammmm/skippercast`.

## Modes

### `cycle` (weekly)

1. Read the last runs:
   `gh run list --workflow fleet-registry.yml --limit 5 --json databaseId,status,conclusion,createdAt,url`,
   and the same for `fleet-osint.yml` and `fleet-health.yml`. Note any red run
   and any open `fleet-ais-stale` issue.
2. Registry: if the last successful `fleet-registry.yml` run is older than
   seven days and none is queued or running, dispatch
   `gh workflow run fleet-registry.yml -f region=<id> -f sink=<sink>`.
   Otherwise leave it to the Monday schedule.
3. OSINT for new and stale boats: unless a `fleet-osint.yml` run is queued or
   running, dispatch
   `gh workflow run fleet-osint.yml -f region=<id> -f mode=refresh -f sink=<sink>`.
4. Matching needs no dispatch: every scheduled `ais process` run calls the
   `match` hook (FCC, call sign, AIS static name, geofence presence and
   `schedule-correlation`) and opens `mmsi` reviews for what it cannot
   promote. Run `python -m skippercast.fleet.ais watch-check --region <id>`
   (counts by status and method; exit 1 when a watched row fails the gate).
5. Report as in `report` below, with the counts by match method.
6. Owner steps: for each step a runbook names that is not done (a secret, a
   variable, a `sudo` command, the CPRA request in
   [open-questions.md](../../docs/plans/charter-fleet/open-questions.md)),
   check `gh issue list --label owner-task --label charter-fleet --state open`
   and open one issue per missing step with both labels, the exact link or
   command, and links to #437 and #458. Never duplicate an open one.

### `discover`

A registry pass only: `gh workflow run fleet-registry.yml -f region=<id> -f sink=<sink> -f steps=discover,resolve,enrich-code,ingest,refresh`.
For a local dry run, *on the runner*:
`python -m skippercast.fleet run --region <id> --sink staging`. Resume a
failed run with `-f run_id=<id from its summary>` and the same sink, as the
registry runbook says. Report the per-step counts from the run summary.

### `match`

Identity matching only, counts only.

1. `python -m skippercast.fleet.ais watch-check --region <id>`.
2. When a landing-report history file exists *on the runner*, measure
   `schedule-correlation` on that window:
   `python -m skippercast.fleet.ais schedule-precision --region <id> --from <YYYY-MM-DD> --to <YYYY-MM-DD> --reports <json>`.
   Without `--vessels <json>` it reads the registry from the Worker and needs
   the job identity. By default it reads the MarineCadastre backfill store
   (`--source`), so the window's months must be backfilled first. The
   January–June 2026 report history is not in the repository; if no file
   exists, say so.

### `review`

A counts-only summary of the review queue: open reviews by kind, as the owner
or the admin view gives them, passed to
`python -m skippercast.fleet report --region <id> --sink <sink> --open-reviews <n> --status-line`
(with `--sink worker` this needs the job identity, so from a session take the
counts from the last `fleet-registry.yml` run log, as `report` below says),
plus the queue link `https://skippercast.com/admin.html#fleet-review?region=<id>`.
Only the owner decides reviews, in that queue. This skill never decides a
review, never contacts a captain or operator, and never writes
`POST /api/fleet/jobs/watch` by hand. A captain's own confirmation reaches the
registry only as an owner decision (`admin` method).

### `report`

Status with no side effects beyond the files `report` writes under
`SKIPPERCAST_FLEET_VAR`: its report files, and with `--sink staging` the
staging SQLite registry when it is absent:

- `python -m skippercast.fleet report --region <id> --sink <sink> --status-line`;
- `python -m skippercast.fleet coverage-status --region <id> --sink <sink>`,
  never with `--apply` (region files change only through a PR, as the
  registry runbook says).

With `--sink staging` both run *on the runner*. With `--sink worker` they need
the job identity (see the gaps): take the per-step counts and the
`charter-identity coverage` block from the last `fleet-registry.yml` run
(`gh run view <run id> --log`), and say the status line was not produced.

## Guardrails

- Public sources only, never the off-limits sources of
  [D7](../../docs/plans/charter-fleet/README.md). No outreach, sign-ups
  or purchases. Nothing paid without a quote put to the owner first.
- Never commit, post or paste registry data: contacts, OSINT output,
  positions, MMSIs, vessel ids, boat names, run directories. Issues, PRs,
  chat and the status log get counts only.
- `--sink worker` only for a region whose `fleet.json` status is live
  (`active`).
- One run at a time per workflow: check `gh run list` before any dispatch.
- Bound each session to 60 minutes. Record the UTC start and deadline; at the
  deadline stop dispatching, leave running jobs alone and report.
- Never run a fleet job from another session's checkout, rerun with
  `--ref`, or edit the runner's data by hand.

## Stop and open an owner issue when

- a credential, secret or `gh` permission is denied;
- a workflow fails twice on the same input (read its runbook's "Reading a run"
  first; a code fault needs a fix PR, not a third run);
- the listener has been down more than 3 hours: the `fleet-ais-stale` issue
  is open; follow [fleet-ais-down.md](../../docs/operations/runbooks/fleet-ais-down.md);
- a step needs `sudo`, money, a terms request or anything public.

## End-of-run report

One short message, counts only, no names or ids:

- the status line (or why it was not produced);
- MMSI matches by method (`fcc-uls`, `call-sign`, `ais-static-name`,
  `geofence-presence`, `schedule-correlation`, `admin`) and the watched count,
  from `watch-check` or the report;
- review counts by kind, if known;
- open owner steps, with their issue links;
- links to the workflow runs read or dispatched;
- the gaps above that blocked any line.

## Install

On AgentOrange, symlink this folder from the repository checkout the
`AGENTS.md` AgentOrange section names, so it updates with `git pull`. For
Claude Code: `ln -s "$PWD/skills/skippercast-fleet-registry" ~/.claude/skills/`
from the checkout root. Where Hermes and Codex load skills is not recorded in
this repository yet: that is part of #468's foundation step (the host profile).
