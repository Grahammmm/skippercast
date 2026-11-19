# Runners: where the jobs run and what they cost

SkipperCast's compute is GitHub Actions. On a public repository the minutes are free; on a
private one they are billed, and the live forecast loop alone runs about 24 hours a day.
This page records the numbers and separates the public hosted jobs from the private fleet jobs.

## What the jobs cost on GitHub-hosted runners

Measured from the workflow definitions (timeouts and loop budgets, 30 Sep 2026); billed
minutes are per job, so parallel jobs add up.

| Workflow | Cadence | Billed minutes / month (about) |
| --- | --- | --- |
| `live-conditions.yml` refresh | 330-minute self-chaining loop, all day | 43,000 |
| `live-conditions.yml` notify | Same, unless `ENABLE_QUEUES=true` | 43,000 |
| `seafloor.yml` | Daily; prepare + one job per reach + publish | up to 5,000 |
| `ci.yml` | Every push and PR; 4 jobs of 3–5 minutes | 1,500–3,000 |
| `daily-data.yml`, `research-daily.yml`, `feed-freshness.yml`, `ops-report.yml` | Daily / hourly | 1,500 |
| Monthly research workflows | Day 1 and 2 of the month | 500–1,000 (one job stays on `macos-latest`, billed at 10×: about 90 minutes, $7) |
| **Total** | | **50,000–95,000** |

A private repository on the Free plan includes 2,000 Linux minutes a month, then about
$0.008 a minute (check GitHub's current price list). At the totals above that is roughly
**$400–750 a month**. Paid plans add only 1,000–50,000 minutes, so no plan makes this cheap.

## Public hosted jobs and private fleet runners

All workflows in public `Grahammmm/skippercast` use GitHub-hosted runners. No public
workflow reads a runner-selection variable.

Every public job uses `ubuntu-latest` except one monthly research-substrate job, which
uses `macos-latest`.

`deploy-cloudflare.yml`, `dco.yml` and `release.yml` stay on GitHub-hosted runners: they
are short (about 1–3 minutes each) and the deploy holds the Cloudflare token, which we
would rather not hand to a long-lived box. `fleet-health.yml` (under a minute, hourly) stays
hosted too, so it can raise the `fleet-ais-stale` issue while the data runner is down.

The fleet AIS processor and listener install, registry and OSINT workflows run on
self-hosted runners registered to private `Grahammmm/skippercast-ops`. The jobs require
`ENABLE_FLEET=true` and the private repo's `main`, and check out public SkipperCast `main`
for the scripts and Python package. They have no `pull_request` or `pull_request_target`
triggers. Their workflow and lock contracts are tested in `skippercast-ops` (charter fleet
[Q13](../plans/charter-fleet/open-questions.md#q13-self-hosted-fleet-jobs-on-a-public-repository),
[threat model § 10.4](../legal/threat-model.md) row E).

## Setting up the box

One Ubuntu 24.04 machine with 4 vCPU, 8 GB memory and 80 GB disk is enough for four
runner instances. Options, ranked:

1. **Hetzner Cloud CX32** (4 vCPU, 8 GB, 80 GB, 20 TB traffic): about €7 a month. Any
   region works; the jobs are batch downloads from NOAA and ECMWF, not latency-sensitive.
2. A machine you already run at home, if it is on 24 hours a day and on a UPS. Free, but
   a power cut interrupts jobs configured to use the box.
3. Stay on GitHub-hosted runners and pay. Simplest; the most expensive by a factor of 50.

Use the operator instructions in private `skippercast-ops` to register fleet runners.
Do not register runners to the public repository. The stock `scripts/runner/setup.sh`
defaults do not describe the private fleet setup.

Separately, `ENABLE_QUEUES=true` (see `docs/cloudflare.md`) stops the hosted notify job
from running all day; the Worker's cron queues trip checks itself.

## Keeping it healthy

- The runner service updates itself. Upgrade the host with `apt-get upgrade` monthly.
- Disk: jobs on the box write under `_work`; `df -h /opt/actions-runner`
  should stay below 70%. The runner cleans job workspaces; toolchain caches persist.
- If all four runners are busy, jobs assigned to the box queue instead of failing.
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
box's `python3`, 3.11 or newer; Ubuntu 24.04 ships 3.12 and `setup.sh` installs `python3-venv`),
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
