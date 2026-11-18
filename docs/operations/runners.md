# Runners: where the jobs run and what capacity they need

This guide inventories GitHub Actions jobs for capacity planning. It describes the
checked-in workflows, not which runner labels are set or how often jobs actually start.

## Workflow inventory

The September 2026 monthly estimates were historical planning assumptions, not measured
usage or a bill. They assumed four short CI jobs and monthly research dispatches, and
did not count the alarm clock. Do not use them to size today's runner pool.

The following inventory covers the workloads in the old estimate plus the alarm clock.
Schedules are configured triggers, not observed starts. Jobs can be skipped, delayed,
or cancelled; matrix legs each take a runner slot while executing.

| Workflow / job | Configured cadence and job count | Runner selection |
| --- | --- | --- |
| `live-conditions.yml` / `refresh` | Schedule at :07 and :37 UTC, manual dispatch, or a dispatch from the chain. One job refreshes every 30 minutes within a 330-minute loop budget (355-minute job timeout). | `DATA_RUNNER` |
| `live-conditions.yml` / `alarm-clock` | One independent job per `main` run. Attempts a freshness dispatch at startup and hourly thereafter, stopping when it observes refresh completed or reaches its loop limit (330-minute window; 345-minute job timeout). It can occupy a runner while sleeping. | `DATA_RUNNER` |
| `live-conditions.yml` / `notify` | One optional job alongside refresh, with a 345-minute loop budget and a 360-minute job timeout. Runs unless `ENABLE_QUEUES=true`; a manual dispatch with `check_trips` can still request it. | `DATA_RUNNER` |
| `live-conditions.yml` / `next` | One job after refresh on uncancelled `main` runs (5-minute timeout); it skips dispatching a successor if refresh did not record at least one hour of elapsed time. | `DATA_RUNNER` |
| `ci.yml` | PR: up to 9 jobs (1 `changes`, 2 `check`, 4 `e2e`, up to 1 `survey-tests`, 1 `survey-science` roll-up). Main push, merge queue and dispatch: 11 jobs (3 `survey-tests` legs instead of 1). Nightly at 09:00 UTC: the same full tier plus 1 `e2e-flake-rates` job. | Hosted Ubuntu by default; see [CI readiness gate](#ci-readiness-gate). |
| `seafloor.yml` | Daily at 10:23 UTC, matching pushes to `main`, or manual dispatch. `prepare` selects work; if there is work, a matrix runs one `reaches` leg per selected reach, followed by `publish` and `ledger` as allowed by their job conditions. | `SEAFLOOR_RUNNER` |
| `daily-data.yml` | One refresh job; daily at 04:17 Los Angeles time, matching pushes to `main`, or manual dispatch. | `DATA_RUNNER_LIGHT` |
| `research-daily.yml` | One inventory job on completion of `daily-data.yml` or manual dispatch; no separate cron. | `DATA_RUNNER_LIGHT` |
| `feed-freshness.yml` | One check job; scheduled at :52 UTC each hour or dispatched, including by the alarm clock. | `DATA_RUNNER` |
| `ops-report.yml` | One report job; daily at 15:23 UTC or manual dispatch. | `DATA_RUNNER` |
| `research-substrate.yml` | Manual-only, 20 jobs defined (19 portable jobs and 1 macOS audit). No monthly executions assumed. | `DATA_RUNNER_LIGHT`; `audit` stays on hosted `macos-latest`. |
| `research-fish-survey.yml` | Manual-only, 11 jobs defined. No monthly executions assumed. | `DATA_RUNNER_LIGHT` |

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

## The switch: self-hosted runners

Every heavy workflow reads its runner from a repository variable, so moving the jobs is a
variable change, not a code change:

| Variable | Workflows | Unset (default) | Set to `skippercast` |
| --- | --- | --- | --- |
| `DATA_RUNNER` | live loop, daily data, freshness, ops report, legal review, research, rehearsal, forecast tiles, fleet AIS listener install, fleet registry, fleet OSINT, basemap | `ubuntu-latest` for jobs with a hosted fallback | our runners |
| `DATA_RUNNER_LIGHT` | the portable CPU-heavy subset: daily data, research daily, research substrate, research fish survey, draft-region health and rehearsal, forecast tiles, basemap | falls back to `DATA_RUNNER`, then `ubuntu-latest` | our runners; set `ubuntu-latest` instead to route just these portable jobs to hosted Ubuntu |
| `SEAFLOOR_RUNNER` | seafloor preparation, reach processing and publication | `ubuntu-latest` | a verified dedicated runner label |
| `CI_RUNNER` | `ci.yml` jobs | `ubuntu-latest` | our runners only when `CI_SELF_HOSTED_READY=true` and the run is eligible |

`deploy-cloudflare.yml`, `dco.yml` and `release.yml` stay on GitHub-hosted runners: they
are short (about 1–3 minutes each) and the deploy holds the Cloudflare token, which we
would rather not hand to a long-lived box. `fleet-health.yml` (under a minute, hourly) stays
hosted too, so it can raise the `fleet-ais-stale` issue while the data runner is down.

On a public repository anyone's pull request could run code on the box, so no pull
request from a fork may ever reach it.

**Rule for every workflow that can run on `DATA_RUNNER` or `SEAFLOOR_RUNNER`:** no
`pull_request` or `pull_request_target` trigger. Such a workflow runs on `schedule` (which
runs `main`), `workflow_dispatch`, `workflow_run`, or `push` limited to `branches: [main]`,
so only reviewed code reaches the box. Workflows that hold fleet secrets go further: their
jobs also require `github.ref == 'refs/heads/main'`, so a dispatch from another branch is
skipped (charter fleet [Q13](../plans/charter-fleet/open-questions.md#q13-self-hosted-fleet-jobs-on-a-public-repository),
[threat model § 10.4](../legal/threat-model.md) row E). `tests/unit/test_fleet_install_script.py`
checks the trigger rule for every workflow that names either variable. `ci.yml` is the one
`pull_request` workflow with a self-hosted switch (`CI_RUNNER`). Its jobs reach the box only
when `CI_SELF_HOSTED_READY=true` **and** the run is not a pull request from a fork or from
Dependabot: pushes to `main`, manual dispatches and pull requests from branches in this
repository (people with write access) use `CI_RUNNER`; a fork's pull request and a
Dependabot update (whose new packages run install scripts) always run on GitHub-hosted Ubuntu.
`tests/contract/test_workflow_pins.py` pins that expression. The guarantee CI gives is
limited: its jobs get no repository secrets injected and a read-only `GITHUB_TOKEN`
(`permissions: contents: read`). That restricts the token only. It does not stop a job
from reading files or credentials on the host, and a same-repository branch is a
write-access trust boundary, not proof that the code was reviewed. The current runners
run as the operator account and can read the operator's credentials, so CI must not move
onto them until isolation is verified (see [CI readiness gate](#ci-readiness-gate)).

## Setting up the box

The setup script defaults to four runner instances. If all live jobs share that pool,
refresh and alarm can hold two slots at once; optional notify can hold a third. A
freshness check or `next` can then fill the fourth slot, leaving other work queued.
That is a concurrency example, not a recommendation to buy or enable more runners.

Steps:

1. Create the box; SSH in as root.
2. In the repository: Settings → Actions → Runners → New self-hosted runner → copy the
   registration token (it expires in an hour).
3. Run the setup script from a checkout (or paste it in):
   ```bash
   sudo REPO=Grahammmm/skippercast RUNNER_TOKEN=<token> bash scripts/runner/setup.sh
   ```
   It installs the host packages the workflows expect, Chromium's shared libraries for the
   Playwright job, and registers four runners (`RUNNERS=4`) as systemd services with the
   labels `self-hosted,skippercast`. Python and Node still come from `actions/setup-python`
   and `actions/setup-node` inside each job, cached under the runner's work folder.
4. Check Settings → Actions → Runners shows four idle runners.
5. Set the repository variables: `gh variable set DATA_RUNNER --body skippercast` and
   `gh variable set CI_RUNNER --body skippercast`. The next scheduled data run uses the box.
   CI remains hosted until the complete readiness checks below pass and you set
   `CI_SELF_HOSTED_READY=true`. To move CI back to hosted runners, delete that readiness
   variable or set it to `false`; delete `DATA_RUNNER` to move data jobs back.
6. Also turn on `ENABLE_QUEUES=true` (see `docs/cloudflare.md`) so the notify job stops
   running all day; the Worker's cron queues trip checks itself.

## Keeping it healthy

- The runner service updates itself. Upgrade the host with `apt-get upgrade` monthly.
- Disk: the live loop and seafloor jobs write under `_work`; `df -h /opt/actions-runner`
  should stay below 70%. The runner cleans job workspaces; toolchain caches persist.
- If all four runners are busy, even a short freshness check or `next` job can queue.
- Artifacts and caches (`actions/upload-artifact`, `actions/cache`) still count against
  GitHub storage (500 MB free on the Free plan). The research workflows upload the most;
  shorten their `retention-days` if the storage bill appears.
- Secrets used by jobs on the box: `R2_PUBLISH_TOKEN` (or the deploy token as fallback),
  `R2_ADVISOR_TOKEN` (the advisor media job, below), `AISSTREAM_API_KEY` (the fleet AIS
  listener, below), `GOOGLE_PLACES_API_KEY` (the fleet registry run, below), `CLOUDFLARE_ACCOUNT_ID` and the Actions `GITHUB_TOKEN`. Keep the box patched and its SSH key-only; `docs/legal/threat-model.md`
  lists it as an asset once it exists.

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

It runs only on the box: the job's `if` needs `ENABLE_ADVISOR=true` and a non-empty
`DATA_RUNNER`, so with either unset a dispatch is skipped and costs nothing. It needs:

| Name | Kind | What |
| --- | --- | --- |
| `R2_ADVISOR_TOKEN` | secret (owner step) | Cloudflare API token with R2 object read and write on `skippercast-advisor-media` only. `R2_PUBLISH_TOKEN` (feed bucket) is not reused. The job derives its S3 keys from it as `scripts/publish_r2.py` does. |
| `CLOUDFLARE_ACCOUNT_ID` | secret | Already set for the data jobs. |
| `ADVISOR_NUMBER` | variable | The advisor's number for the Story footer (shown as (805) 555-0100); without it the footer reads `skippercast.com/text`. |
| `ADVISOR_PUBLIC_BASE` | variable, optional | Where the job calls the Worker; default `https://skippercast.com`. |
| `ffmpeg` and `ffprobe` | on the box's `PATH` | Required for videos (`sudo apt install ffmpeg` on Ubuntu or Debian, `brew install ffmpeg` on macOS). The job copies each video's streams without metadata (`-map_metadata -1 -map_chapters -1 -c copy -movflags +faststart`, no data tracks), checks with `ffprobe` and an atom walk that no `location`, `©xyz` or `com.apple.quicktime.location.ISO6709` tag is left, and uploads `advisor/derived/<id>/video.mp4`. Without ffmpeg each video is reported `no-ffmpeg`: it can never be approved, posted or served (the admin card says why), and the run's log warns. After installing it, put those videos back in the list with `UPDATE advisor_media SET derived_at=NULL, derived_error=NULL WHERE kind='video' AND derived_error='no-ffmpeg'` (`wrangler d1 execute`), and the next dispatch strips them. |

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
`fleet-ais-listener.yml` installs and updates it. That workflow has no schedule and no push
trigger: the owner dispatches it (`gh workflow run fleet-ais-listener.yml -f region=CA`), it needs
`ENABLE_FLEET=true` and a non-empty `DATA_RUNNER` (so it never runs on a GitHub-hosted runner),
runs only from `main`, and its token can only read the repository (`contents: read`).

`scripts/fleet/install_listener.sh` copies the dispatched revision to
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

`fleet-registry.yml` (CF-18, [design.md § 9](../plans/charter-fleet/design.md#9-ingest-and-refresh))
runs the charter fleet registry pipeline (`python -m skippercast.fleet run`: discover, resolve,
enrich-code, ingest, refresh) every Monday at 09:47 UTC and on dispatch (`region`, `sink`, `steps`,
and `run_id` to resume a run). Like the listener install it needs `ENABLE_FLEET=true` and a
non-empty `DATA_RUNNER`, and runs only from `main`. Its token reads the repository and requests an
OIDC identity (`id-token: write`) for `/api/fleet/jobs/*`; the Worker answers those routes only
while `FLEET_ENABLED` is on. Run state lives in `~/.local/share/skippercast/fleet` (staging runs:
`fleet-staging`), never in the checkout. `GOOGLE_PLACES_API_KEY` (secret, owner step, optional)
reaches only the pipeline step; without it the Places adapter skips. First run, reruns, staging
runs and publishing coverage: [fleet registry run](runbooks/fleet-registry.md).

## The fleet OSINT run

`fleet-osint.yml` (CF-21, [design.md § 8](../plans/charter-fleet/design.md#8-the-osint-agent-step))
plans OSINT batch manifests, researches each batch as a headless `claude -p` session with the
`charter-osint` agent (`scripts/fleet/run_osint.py`) and ingests the profiles, every Sunday at
10:17 UTC and on dispatch (`region`, `mode`, `sink`, `max_batches`, and `run_id` to resume). It
needs `ENABLE_FLEET=true` and a non-empty `DATA_RUNNER`, runs only from `main`, and requests an
OIDC identity for `/api/fleet/jobs/*`. It uses the Claude subscription only: the owner saves a
`claude setup-token` token in `~/.config/skippercast/claude.env` (mode 0600, on the box, not a
GitHub secret), and the script exits if `ANTHROPIC_API_KEY` is set. The Claude Code version is
pinned and installed under `~/.local/share/skippercast/claude-code/`. Setup, flags, reruns and
failures: [fleet OSINT run](runbooks/fleet-osint.md).

## CI readiness gate

`ci.yml` is written for a shared box: `pnpm/action-setup` installs into
`${{ runner.temp }}` (several instances share one `$HOME`, and the default
`~/setup-pnpm` races), and the Playwright step runs `--with-deps` (which calls
`sudo apt-get`) only on GitHub-hosted runners. On the box, Chromium's shared
libraries must already be present (Ubuntu 24.04 desktop has them; the setup
script installs them otherwise).

CI uses GitHub-hosted Ubuntu until `CI_SELF_HOSTED_READY=true` is set alongside
`CI_RUNNER`, and fork and Dependabot pull requests stay hosted even then. Setting a
runner label alone does not move CI. Before enabling the gate, verify all of these:

1. **Credential isolation.** The CI runner runs as an account that cannot read the
   operator's credentials or home directory (SSH keys, cloud and GitHub tokens,
   `~/.config/skippercast/`, password stores). A read-only `GITHUB_TOKEN` does not
   provide this; only host-level separation does.
2. **Workload isolation.** CI jobs cannot reach the secret-bearing `DATA_RUNNER` and
   `SEAFLOOR_RUNNER` workloads: not their runner directories, work trees, caches,
   environment files or processes.
3. Browser system dependencies install without an interactive password.
4. Parallel pnpm installs use separate directories.
5. A complete proof run of the CI suite passes green on the configured runner.

Today's runners run as the operator account and do not meet items 1 and 2, so
`CI_SELF_HOSTED_READY` stays unset until that isolation is verified and a complete
proof run is green. Keep the gate disabled while any prerequisite fails. Merging a
change to `ci.yml` does not enable it. Other data jobs continue to use `DATA_RUNNER`
independently.

## Seafloor isolation

Seafloor refreshes use `SEAFLOOR_RUNNER`, independently of CI and the long-running
live forecast loop. Leave it unset to use GitHub-hosted Ubuntu. This prevents
reef publication from waiting behind occupied self-hosted runners. Before setting
a dedicated self-hosted label, verify that the entire seafloor workflow completes
on that pool, including source hashes, spatial screens, R2 read-back and public
archive checks. Unset the variable to return to hosted processing; no checks or
publication gates are disabled. Existing queued jobs retain their assigned runner;
rerun an interrupted refresh only after checking its saved progress receipts.
