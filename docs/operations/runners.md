# Runners: where the jobs run and what capacity they need

This guide inventories GitHub Actions jobs for capacity planning. It describes the
checked-in workflows, not how often jobs actually start, and separates public hosted jobs
from private fleet jobs.

## Workflow inventory

The September 2026 monthly estimates were historical planning assumptions, not measured
usage or a bill. They assumed four short CI jobs and monthly research dispatches, and
did not count the alarm clock. Do not use them to size today's runner pool.

The following inventory covers the workloads in the old estimate plus the alarm clock.
Schedules are configured triggers, not observed starts. Jobs can be skipped, delayed,
or cancelled; matrix legs each take a runner slot while executing.

| Workflow / job | Configured cadence and job count | Runner selection |
| --- | --- | --- |
| `live-conditions.yml` / `refresh` | Schedule at :07 and :37 UTC, manual dispatch, or a dispatch from the chain. One job refreshes every 30 minutes within a 330-minute loop budget (355-minute job timeout). | `ubuntu-latest` |
| `live-conditions.yml` / `alarm-clock` | One independent job per `main` run. Attempts a freshness dispatch at startup and hourly thereafter, stopping when it observes refresh completed or reaches its loop limit (330-minute window; 345-minute job timeout). It can occupy a runner while sleeping. | `ubuntu-latest` |
| `live-conditions.yml` / `notify` | One optional job alongside refresh, with a 345-minute loop budget and a 360-minute job timeout. Runs unless `ENABLE_QUEUES=true`; a manual dispatch with `check_trips` can still request it. | `ubuntu-latest` |
| `live-conditions.yml` / `next` | One job after refresh on uncancelled `main` runs (5-minute timeout); it skips dispatching a successor if refresh did not record at least one hour of elapsed time. | `ubuntu-latest` |
| `ci.yml` | Ready PR: up to 11 jobs (1 `changes`, 2 `check`, up to 4 `e2e`, 3 `survey-tests`, 1 `survey-science` roll-up). Main push, merge queue and dispatch: 11 jobs. Nightly at 09:00 UTC: the same full tier plus 1 `e2e-flake-rates` job. | `ubuntu-latest`. |
| `seafloor.yml` | Daily at 10:23 UTC, matching pushes to `main`, or manual dispatch. On `main`, `prepare` selects work; if there is work, the `reaches` matrix groups up to three selected reaches from the same region per worker leg, with at most three legs running in parallel. After `reaches`, `publish` runs one matrix leg per selected region (at most three in parallel), followed by `ledger`. Both are conditioned on successful `prepare` with work selected and can run despite an upstream failure. | `ubuntu-latest` |
| `daily-data.yml` | One refresh job; daily at 04:17 Los Angeles time, matching pushes to `main`, or manual dispatch. | `ubuntu-latest` |
| `research-daily.yml` | One inventory job on completion of `daily-data.yml` or manual dispatch; no separate cron. | `ubuntu-latest` |
| `feed-freshness.yml` | One check job; scheduled at :52 UTC each hour or dispatched, including by the alarm clock. | `ubuntu-latest` |
| `ops-report.yml` | One report job; daily at 15:23 UTC or manual dispatch. | `ubuntu-latest` |
| `research-substrate.yml` | Manual-only, 20 jobs defined (19 portable jobs and 1 macOS audit). No monthly executions assumed. | `ubuntu-latest`; `audit` uses `macos-latest`. |
| `research-fish-survey.yml` | Manual-only, 11 jobs defined. No monthly executions assumed. | `ubuntu-latest` |

### Observed duration by runner class

A comparable anonymized sample of elapsed job times for today's jobs is **unavailable**
for hosted Linux, hosted macOS, and self-hosted runners. Existing accounting aggregates
different workloads; it does not establish a like-for-like duration comparison. For any
future comparison, report sample size and elapsed time for the same job and tier by
assigned runner class, keeping unknown assignments separate.

Job elapsed time runs from start to completion and includes sleep. Parallel jobs add
runner occupancy, not sequential wall time. Queue wait is time before a runner starts;
host CPU time measures processing rather than occupancy; a configured timeout caps a
job but is not its observed duration. None of these is a billing measure. Repository
visibility, billing, and actual dispatch frequency were not measured for this inventory.

## Public hosted jobs and private fleet runners

Public `Grahammmm/skippercast` is GitHub-hosted only. Do not register runners to the
public repository or use runner-selection variables there.

Every public job uses literal `ubuntu-latest` except `audit` in
`research-substrate.yml`, which uses `macos-latest`.

`deploy-cloudflare.yml`, `dco.yml` and `release.yml` stay on GitHub-hosted runners: they
are short (about 1–3 minutes each) and the deploy holds the Cloudflare token, which we
would rather not hand to a long-lived box. `fleet-health.yml` (under a minute, hourly) stays
hosted too, so it can raise the `fleet-ais-stale` issue while the data runner is down.

The AgentOrange jobs live in private `Grahammmm/skippercast-ops`: `fleet-ais`,
`fleet-osint`, `fleet-registry`, `fleet-ais-listener`, and `fleet-ping`. They use the
private self-hosted `skippercast-ops` runners, not GitHub-hosted minutes. The fleet
jobs run from private `main` with `ENABLE_FLEET=true`; the operator's `fleet-ping`
diagnostic uses its own gate. There are no pull request triggers. The data jobs check
out public SkipperCast `main` for the scripts and Python package. Their workflow and
lock contracts are tested in `skippercast-ops` (charter fleet
[Q13](../plans/charter-fleet/open-questions.md#q13-self-hosted-fleet-jobs-on-a-public-repository),
[threat model § 10.4](../legal/threat-model.md) row E).

The fleet runner setup script (`scripts/runner/setup.sh`) lives in private
`skippercast-ops`. Fleet runner registration and host maintenance are operator tasks.

Separately, `ENABLE_QUEUES=true` (see `docs/cloudflare.md`) stops the hosted notify job
from running all day; the Worker's cron queues trip checks itself.

For hosted capacity planning, refresh and alarm can hold two slots at once; optional
notify can hold a third, and a freshness check or `next` can use another. Jobs may
queue when capacity is unavailable. This is an example, not a runner purchase recommendation.

## Keeping it healthy

- The runner service updates itself. Upgrade the host with `apt-get upgrade` monthly.
- Disk: jobs on the box write under `_work`; `df -h ~/actions-runner`
  should stay below 70%. The runner cleans job workspaces; toolchain caches persist.
- If both private runners are busy, jobs assigned to the box queue instead of failing.
- Artifacts and caches (`actions/upload-artifact`, `actions/cache`) still count against
  GitHub storage (500 MB free on the Free plan). The research workflows upload the most;
  shorten their `retention-days` if the storage bill appears.
- Fleet secrets used by jobs on the box include `AISSTREAM_API_KEY` (listener install,
  below) and `GOOGLE_PLACES_API_KEY` (registry, below). Keep the box patched and its
  SSH key-only; `docs/legal/threat-model.md` lists it as an asset.

## The advisor media job

`advisor-media.yml` (TA-M1; [09 · Derived images and graphics](../plans/text-advisor/09-social.md))
makes the Text Advisor's derived photos (`public.jpg`, `thumb.jpg`, `story.jpg` with the
"Text SkipperCast" footer), converts HEIC to JPEG and renders the daily, story and roundup
graphics, with Pillow and pillow-heif (`pip install -e ".[advisor]"`), and strips every video's
container metadata (location atoms included) with **ffmpeg**. It has no schedule:
the Worker dispatches it through `dispatchWorkflow` (the watchdog's `GITHUB_TOKEN`, Actions
read and write) when something becomes pending, at most once a minute, and its cron again
every 15 minutes while anything still is. A run takes seconds to a few minutes and holds one
runner instance; its concurrency group keeps it to one run at a time.

It runs on GitHub-hosted `ubuntu-latest` only when `ENABLE_ADVISOR=true`. If the variable
is unset, a dispatch skips the job without allocating a runner. The workflow installs
`ffmpeg` (which includes `ffprobe`) before running the media job. It needs:

| Name | Kind | What |
| --- | --- | --- |
| `R2_ADVISOR_TOKEN` | secret (owner step) | Cloudflare API token with R2 object read and write on `skippercast-advisor-media` only. `R2_PUBLISH_TOKEN` (feed bucket) is not reused. The job derives its S3 keys from it as `scripts/publish_r2.py` does. |
| `CLOUDFLARE_ACCOUNT_ID` | secret | Already set for the data jobs. |
| `ADVISOR_NUMBER` | variable | The advisor's number for the Story footer (shown as (805) 555-0100); without it the footer reads `skippercast.com/text`. |
| `ADVISOR_PUBLIC_BASE` | variable, optional | Where the job calls the Worker; default `https://skippercast.com`. |
| `ffmpeg` and `ffprobe` | workflow-installed tools | Required for videos. The job copies each video's streams without metadata (`-map_metadata -1 -map_chapters -1 -c copy -movflags +faststart`, no data tracks), checks with `ffprobe` and an atom walk that no `location`, `©xyz` or `com.apple.quicktime.location.ISO6709` tag is left, and uploads `advisor/derived/<id>/video.mp4`. If the media job runs without these tools, each video is reported `no-ffmpeg`: it can never be approved, posted or served (the admin card says why), and the run's log warns. Once the tools are available, put those videos back in the list with `UPDATE advisor_media SET derived_at=NULL, derived_error=NULL WHERE kind='video' AND derived_error='no-ffmpeg'` (`wrangler d1 execute`), and the next dispatch strips them. |

The job proves who it is with a GitHub OIDC token for the audience
`https://skippercast.com/api/advisor/jobs`; `deployments/production.json`
`scheduler.workflows` lists `advisor-media.yml`, and the Worker accepts that token only on
`/api/advisor/jobs/*`. If it fails: the run's log names each item it skipped; items it could
not decode are given up (the photo stays private and gets the upload link); network or R2
errors leave items pending and the next dispatch retries them.

## The fleet AIS listener

The charter fleet's AIS listener (CF-41, [design.md § 10](../plans/charter-fleet/design.md#10-ais-listener))
is not a job: aisstream has no replay, so it runs all the time as a **user** systemd unit of the
runner user, `skippercast-fleet-ais@<REGION>` (`scripts/fleet/skippercast-fleet-ais@.service`).
`fleet-ais-listener.yml` in private `skippercast-ops` installs and updates it. It has no
schedule or push trigger: the owner dispatches it in the private repo. It needs
`ENABLE_FLEET=true`, runs only from `main`, and uses `contents: read`.

`scripts/fleet/install_listener.sh` copies the checked-out public revision to
`~/.local/share/skippercast/app/<sha>` with its own virtualenv (the `fleet` extra, built on the
box's `python3`, 3.11 or newer; Ubuntu 24.04 ships 3.12, and the private setup script
installs `python3-venv`),
points `app/current` at it, writes `~/.config/skippercast/fleet-ais.env` with mode 0600, restarts
the unit and fails unless the heartbeat shows messages within 90 seconds. It keeps the three
newest revisions for rollback. The raw store lives outside any checkout in
`~/.local/share/skippercast/fleet` (`SKIPPERCAST_FLEET_VAR`), shared with the fleet jobs.

| Name | Kind | What |
| --- | --- | --- |
| `AISSTREAM_API_KEY` | secret (owner step) | The aisstream.io API key. Passed only to the install step's environment, never traced or printed, and stored on the box only in the 0600 env file. |
| `ENABLE_FLEET` | variable | `true` to let the fleet workflows run (design.md § 16). |
| Linger | owner step on the box | `sudo loginctl enable-linger runner` once, so the runner user's systemd manager runs without a login and starts the unit at boot. |
| Egress | box network | Direct outbound TCP to `stream.aisstream.io:443`; the listener's WebSocket client does not use an HTTP proxy. |

The unit caps its memory at 512 MB (`MemoryMax`). Restart, logs and
rollback: [fleet AIS listener down](runbooks/fleet-ais-down.md).
Optional Morro Bay receive-only receiver (plan only, nothing bought): [fleet AIS receiver](runbooks/fleet-ais-receiver.md).

## The fleet registry run

`fleet-registry.yml` in private `skippercast-ops` (CF-18,
[design.md § 9](../plans/charter-fleet/design.md#9-ingest-and-refresh))
runs the charter fleet registry pipeline (`python -m skippercast.fleet run`: discover, resolve,
enrich-code, ingest, refresh) every Monday at 09:47 UTC and on dispatch (`region`, `sink`, `steps`,
and `run_id` to resume a run). Like the listener install it needs `ENABLE_FLEET=true`
and runs only from `main`. Its token reads the repository and requests an
OIDC identity (`id-token: write`) for `/api/fleet/jobs/*`; the Worker answers those routes only
while `FLEET_ENABLED` is on. Run state lives in `~/.local/share/skippercast/fleet` (staging runs:
`fleet-staging`), never in the checkout. `GOOGLE_PLACES_API_KEY` (secret, owner step, optional)
reaches only the pipeline step; without it the Places adapter skips. First run, reruns, staging
runs and publishing coverage: [fleet registry run](runbooks/fleet-registry.md).

## The fleet OSINT run

`fleet-osint.yml` in private `skippercast-ops` (CF-21,
[design.md § 8](../plans/charter-fleet/design.md#8-the-osint-agent-step))
plans OSINT batch manifests, researches each batch as a headless `claude -p` session with the
`charter-osint` agent (`scripts/fleet/run_osint.py`) and ingests the profiles, every Sunday at
10:17 UTC and on dispatch (`region`, `mode`, `sink`, `max_batches`, and `run_id` to resume). It
needs `ENABLE_FLEET=true`, runs only from `main`, and requests an
OIDC identity for `/api/fleet/jobs/*`. It uses the Claude subscription only: the owner saves a
`claude setup-token` token in `~/.config/skippercast/claude.env` (mode 0600, on the box, not a
GitHub secret), and the script exits if `ANTHROPIC_API_KEY` is set. The Claude Code version is
pinned and installed under `~/.local/share/skippercast/claude-code/`. Setup, flags, reruns and
failures: [fleet OSINT run](runbooks/fleet-osint.md).

## Seafloor isolation

Seafloor preparation, reach processing and publication are pinned to GitHub-hosted
Ubuntu, independently of CI and the long-running live forecast loop. This keeps
reef publication from waiting behind occupied self-hosted runners. Source hashes,
spatial screens, R2 read-back and public archive checks still apply. Existing queued
jobs retain their assigned runner; rerun an interrupted refresh only after checking
its saved progress receipts.
