# Runners: where the jobs run and what they cost

SkipperCast's compute is GitHub Actions. On a public repository the minutes are free; on a
private one they are billed, and the live forecast loop alone runs about 24 hours a day.
This page records the numbers and the switch that moves the heavy jobs to a box we own.

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

## The switch: self-hosted runners

Every heavy workflow reads its runner from a repository variable, so moving the jobs is a
variable change, not a code change:

| Variable | Workflows | Unset (default) | Set to `skippercast` |
| --- | --- | --- | --- |
| `DATA_RUNNER` | live loop, daily data, freshness, ops report, legal review, research, rehearsal, forecast tiles | `ubuntu-latest` (GitHub-hosted, billed) | our runners (free minutes) |
| `SEAFLOOR_RUNNER` | seafloor preparation, reach processing and publication | `ubuntu-latest` | a verified dedicated runner label |
| `CI_RUNNER` | `ci.yml` (check, e2e, survey-science) | `ubuntu-latest` | our runners only when `CI_SELF_HOSTED_READY=true` |

`deploy-cloudflare.yml`, `dco.yml` and `release.yml` stay on GitHub-hosted runners: they
are short (about 1–3 minutes each) and the deploy holds the Cloudflare token, which we
would rather not hand to a long-lived box.

Self-hosted runners must be used only while the repository is **private**. On a public
repository anyone's pull request could run code on the box.

## Setting up the box

One Ubuntu 24.04 machine with 4 vCPU, 8 GB memory and 80 GB disk is enough for four
runner instances (the live loop, its notify job, the hourly freshness check and one CI
or seafloor job at a time). Options, ranked:

1. **Hetzner Cloud CX32** (4 vCPU, 8 GB, 80 GB, 20 TB traffic): about €7 a month. Any
   region works; the jobs are batch downloads from NOAA and ECMWF, not latency-sensitive.
2. A machine you already run at home, if it is on 24 hours a day and on a UPS. Free, but
   a power cut stops the forecast until the Worker watchdog restarts the loop, and
   `feed-freshness.yml` will open stale-feed issues.
3. Stay on GitHub-hosted runners and pay. Simplest; the most expensive by a factor of 50.

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
- If all four runners are busy, jobs queue instead of failing. The live loop's `next` job
  is tiny, so it never starves the chain.
- Artifacts and caches (`actions/upload-artifact`, `actions/cache`) still count against
  GitHub storage (500 MB free on the Free plan). The research workflows upload the most;
  shorten their `retention-days` if the storage bill appears.
- Secrets used by jobs on the box: `R2_PUBLISH_TOKEN` (or the deploy token as fallback),
  `R2_ADVISOR_TOKEN` (the advisor media job, below), `CLOUDFLARE_ACCOUNT_ID` and the Actions
  `GITHUB_TOKEN`. Keep the box patched and its SSH key-only; `docs/legal/threat-model.md`
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

## CI readiness gate

`ci.yml` is written for a shared box: `pnpm/action-setup` installs into
`${{ runner.temp }}` (several instances share one `$HOME`, and the default
`~/setup-pnpm` races), and the Playwright step runs `--with-deps` (which calls
`sudo apt-get`) only on GitHub-hosted runners. On the box, Chromium's shared
libraries must already be present (Ubuntu 24.04 desktop has them; the setup
script installs them otherwise).


CI uses GitHub-hosted Ubuntu until `CI_SELF_HOSTED_READY=true` is set alongside
`CI_RUNNER`. Setting a runner label alone does not move CI. Before enabling the
gate, verify browser system dependencies install without an interactive password,
parallel pnpm installs use separate directories, and the complete CI suite passes
on the configured runner. Keep the gate disabled while any prerequisite fails.
Other data jobs continue to use `DATA_RUNNER` independently.

## Seafloor isolation

Seafloor refreshes use `SEAFLOOR_RUNNER`, independently of CI and the long-running
live forecast loop. Leave it unset to use GitHub-hosted Ubuntu. This prevents
reef publication from waiting behind occupied self-hosted runners. Before setting
a dedicated self-hosted label, verify that the entire seafloor workflow completes
on that pool, including source hashes, spatial screens, R2 read-back and public
archive checks. Unset the variable to return to hosted processing; no checks or
publication gates are disabled. Existing queued jobs retain their assigned runner;
rerun an interrupted refresh only after checking its saved progress receipts.
