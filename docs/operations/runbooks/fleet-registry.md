# Runbook: the fleet registry run

**Use when:** switching the charter fleet registry on (first run), a weekly *Fleet registry* run (`fleet-registry.yml`) failed or ended `partial`, a run must be repeated or resumed, or a region needs a staging (dry) run.
**Severity:** SEV4 for a failed or partial weekly run. Nothing user-facing changes in real time: the registry keeps last week's values, and the next Monday run catches up. Raise it to SEV3 if two weekly runs in a row fail.
**Owner:** repository owner (variables, secrets, the box). An agent can dispatch the workflow, read its summary and, given a shell on the box, the run directory; it opens fix PRs.
**Setup reference:** [design.md § 9](../../plans/charter-fleet/design.md#9-ingest-and-refresh), [runners](../runners.md#the-fleet-registry-run), [fleet AIS listener down](fleet-ais-down.md) for the box itself.

## What runs where

`fleet-registry.yml` runs every Monday at 09:47 UTC and on dispatch, on `vars.DATA_RUNNER` (Hermes), only from `main`. It installs the `fleet` extra and runs

```bash
python -m skippercast.fleet run --region CA --sink worker --run-id <id>
```

which chains `discover → resolve → enrich-code → ingest → refresh` in one run and stops at the first failed step. A discovery binding that fails is recorded and makes the run `partial`; the other steps still run. With `--sink worker` the operations go to `POST /api/fleet/jobs/registry` (D1) with a GitHub OIDC token; the Worker accepts it only from this workflow on `main` (`server/routes/fleet.ts` `FLEET_JOB_SCOPE`, `deployments/production.json` `scheduler.workflows`). A last step prints `coverage-status` (counts per coastal region, no names) into the summary. It never runs `--apply`: region files change only through a PR (below).

| Dispatch input | Default (and the schedule's value) | What |
| --- | --- | --- |
| `region` | `CA` (the schedule uses `vars.FLEET_REGION`, else `CA`) | A region with `regions/<id>/fleet.json`. |
| `sink` | `worker` | `worker` writes the registry; `staging` writes a SQLite registry on the box and never calls the Worker. |
| `steps` | empty: all five | A comma-separated subset, run in pipeline order. |
| `run_id` | empty: a new run | Resume this run (same sink). |

The summary's first line names the run id; the CLI then prints `{"run_id", "dir", "status", "steps"}` with per-step counts. Neither prints registry rows, names or contacts: workflow logs are readable by anyone who can read the repository.

Files on the box (`~` is the runner user's home):

| What | Where |
| --- | --- |
| Registry runs (`sink=worker`) | `~/.local/share/skippercast/fleet/<REGION>/runs/<run_id>/` |
| Staging runs (`sink=staging`) | `~/.local/share/skippercast/fleet-staging/<REGION>/runs/<run_id>/`, registry `~/.local/share/skippercast/fleet-staging/staging/<REGION>.sqlite` |
| In each run directory | `state.json` (each step's status, counts, error; the Worker batch counter), `report.json`, `discover.json` (each binding's status, and `complete`), `candidates.jsonl`, `resolved.jsonl`, `facts.jsonl`, `ingest-snapshot.json`, `ingest-ops.jsonl` |
| HTTP cache | `<var>/<REGION>/http-cache/` |

If the runner's environment sets `SKIPPERCAST_FLEET_VAR`, that path replaces `~/.local/share/skippercast/fleet` (and gets `-staging` appended for staging runs). Staging runs keep their own directory because `refresh` counts every complete discovery run under `<var>/<REGION>/runs/` towards `vanished`: a staging run there would count as a registry run that missed every boat.

**Never delete old run directories** under `fleet/<REGION>/runs/`: their `discover.json` files are the history `vanished` and `returned` are computed from. They hold registry data, so they stay on the box (never in git, an issue or a PR).

## First run (owner steps, once)

Order (design.md § 16): Worker flag, then the workflow switch, then the first run.

1. **Worker flag.** In [repository variables](https://github.com/Grahammmm/skippercast/settings/variables/actions) set `FLEET_ENABLED` to `true` (or `gh variable set FLEET_ENABLED --body true --repo Grahammmm/skippercast`). It reaches the Worker with the next deploy: dispatch *Deploy to Cloudflare* (`gh workflow run deploy-cloudflare.yml --repo Grahammmm/skippercast -f action=deploy`) or wait for the next merge to `main`. Until then every `/api/fleet/jobs/*` call answers 404.
2. **Places key (optional).** `gh secret set GOOGLE_PLACES_API_KEY --repo Grahammmm/skippercast` with a key restricted to the Places API and a daily quota cap ([Q5](../../plans/charter-fleet/open-questions.md#q5-google-places-api-key)). Without it the `google-places` adapter makes no request and reports `skipped`; the run is still `ok`.
3. **Workflow switch.** On the same page set `ENABLE_FLEET` to `true` (`gh variable set ENABLE_FLEET --body true --repo Grahammmm/skippercast`). `DATA_RUNNER` is already set for the data jobs. The job is skipped while either is unset, and on any branch but `main`.
4. **Dry run first (recommended).** `gh workflow run fleet-registry.yml --repo Grahammmm/skippercast -f region=CA -f sink=staging`, then `gh run watch`. Read the summary: every binding's counts, `status` `ok` (or `partial` with the failing bindings named in `discover.json` on the box), and the coverage statuses. Nothing reaches D1.
5. **First registry run.** `gh workflow run fleet-registry.yml --repo Grahammmm/skippercast -f region=CA -f sink=worker`, then `gh run watch`. From an empty registry `refresh` records `new` for every boat. The schedule takes over from the next Monday.
6. **Fill the gaps.** design.md § 9: `run`, then `fleet-osint` (CF-21, once it exists), then `run` again fills the registry; the review queue in the admin is the only human step.

## Reading a run

- **`ok`**: every step ran and every discovery binding succeeded.
- **`partial`**: one or more discovery bindings failed (`steps.discover.counts.failed`). The others' boats were still ingested. A partial run never counts towards `vanished`. On the box: `jq '.bindings | map_values(.status)' <run dir>/discover.json`, then `jq '.bindings["<binding>"]' <run dir>/discover.json` for the error. A source that fails every week needs an adapter fix PR (a changed page layout) or an owner decision (a blocked or retired source).
  Known gap, [#339](https://github.com/Grahammmm/skippercast/issues/339): `refresh` retires a boat's offerings that this run's sources did not list without checking that discovery was `complete`, so in a `partial` run offerings only the failed source listed are retired (a `schedule` change) and come back as added in the next good run. Read `schedule` changes from a partial run with that in mind.
- **Failed** (the job is red): the step that failed and its error are in the log and in `state.json`. Common causes, in order:
  - `fleet run: region ... is dry-run: only the staging sink is allowed`: a `dry-run` region dispatched with `sink=worker`. Use `sink=staging` until the region is promoted.
  - `HTTPError: HTTP Error 404` reading `/api/fleet/jobs/snapshot` (at `resolve`, the first Worker call): `FLEET_ENABLED` is off or not yet deployed (first run, step 1).
  - `HTTP Error 401` or `403` there: the OIDC token was refused. The workflow file name must be in `FLEET_JOB_SCOPE` and `deployments/production.json` `scheduler.workflows`, and the run must be from `main`.
  - `fleet run: batch N: HTTP 400 invalid operations`: an operation failed the Worker's checks, which the sink runs first, so this means the Python and Worker checks differ (`tests/test_fleet_sink_parity.mjs`). Nothing of that batch was written. Open a fix PR; do not rerun until it merges.
  - `BatchTooLarge` (HTTP 413): the sink's batching is wrong; a code fix, not a rerun.
  - HTTP 429 or 5xx after five attempts, or a timeout: the Worker or D1 was unavailable. Resume the run (below).

## Reruns

Every step is idempotent: ids are deterministic, upserts change only what differs, a decided review is never reopened and a change id includes its after-value. Running the same input twice writes zero rows the second time.

- **Repeat the whole run** (a transient failure early on, or to pick up a fix): dispatch again with no `run_id`. It is a new run with its own id and `fleet_runs` rows.
- **Resume a failed run**: dispatch with `run_id=<the id from the failed run's summary>`, the **same sink**, and `steps` from the failed step on, for example `-f run_id=20261012T094712Z-a1b2c3 -f steps=ingest,refresh`. The run reuses its saved candidates and facts (no second fetch of every source), and the Worker batch counter continues from `state.json`, so batch numbers never repeat. Each rerun step updates its `fleet_runs` row (`<run_id>:<step>`) to the latest attempt's status and counts, keeping the first start time.
- **Ingest failed part way**: the batches before the failure are already in D1. Resuming at `ingest` takes a fresh snapshot that includes them, so `refresh` records no change for the boats in those batches (a `new` or `moved` written before the failure is applied but not logged). The registry values are right; only the change log misses them.
- **A step fixed by a code change**: merge the fix, then resume with `run_id` so the run uses the new code on its saved inputs.

Do not dispatch from another branch with `--ref`: the job is skipped off `main`, and the Worker refuses the token anyway.

## Staging runs

Use `sink=staging` for a new region (its `fleet.json` has `status: "dry-run"`, design.md § 21), to try an adapter change after it merges, or before the first registry run. A staging run never calls the Worker. It writes the box's `fleet-staging/staging/<REGION>.sqlite` (the committed migrations applied, the same operations and checks as the Worker) and its own run directories.

```bash
gh workflow run fleet-registry.yml --repo Grahammmm/skippercast -f region=OR -f sink=staging
gh workflow run fleet-registry.yml --repo Grahammmm/skippercast -f region=OR -f sink=staging -f steps=discover,resolve,enrich-code,ingest
```

The summary's per-step counts and coverage statuses are the dry-run report; `report.json` and the SQLite file on the box hold the rest (boats by port and class, sources per boat). Promote a region with `status: "active"` in its own PR after the owner has read that report. To start a staging registry over, delete `fleet-staging/staging/<REGION>.sqlite` and `fleet-staging/<REGION>/runs/` on the box; the next staging run rebuilds it.

## Applying charter-identity coverage

The summary's `charter-identity coverage` block is `coverage-status`'s output for the run's sink: per coastal region, `missing` or `partial` and a counts-only reason. To publish it, in a PR from a fresh `main`:

1. Save the JSON block from the summary of the latest `sink=worker` run as `var/coverage-status.json` (gitignored), then write it into the region files with the same code `--apply` uses:
   ```bash
   PYTHONPATH=src python -c 'import json, sys; from skippercast.fleet.coverage import apply; print(apply(json.load(open(sys.argv[1]))))' var/coverage-status.json
   PYTHONPATH=src python -m skippercast.platform.build
   ```
   `python -m skippercast.fleet coverage-status --region CA --apply` writes the files directly, but only from a staging registry on the same machine: `--sink worker` works only inside the workflow, because it needs the job's OIDC token. Publish the registry's (worker) statuses, never a staging run's.
2. **If `regions/fort-bragg-point-arena/region.json` changed**, regenerate `research/receipts/h11730-fort-bragg-regional-camera-support.json`, which pins that file's sha256 (`research/tests/test_mendocino_camera_relevance.py` fails otherwise). Fetch the two pinned USGS archives into the cache, re-run the audit and rebuild the receipt manifest:
   ```bash
   mkdir -p var/usgs-video-cache
   for cruise in c210nc f208nc; do
     curl -fsSL -o "var/usgs-video-cache/${cruise}_video_observations.zip" \
       "https://pubs.usgs.gov/ds/781/video_observations/data/${cruise}_video_observations.zip"
   done
   PYTHONPATH=src python -m research.scripts.audit_camera_region_support --region fort-bragg-point-arena --survey H11730 \
     --output research/receipts/h11730-fort-bragg-regional-camera-support.json
   PYTHONPATH=src python -m research.lib.receipts
   PYTHONPATH=src python -m pytest research/tests/test_mendocino_camera_relevance.py
   ```
   It needs `pyshp` (in `requirements-survey.txt`). The script checks each archive's sha256 against the reviewed pair file and stops if either changed. In the diff only `region_sha256` and `reviewed_at` may change; anything else means the audit's result changed and needs its own review.
3. Run the checks in [AGENTS.md](../../../AGENTS.md#before-opening-a-pr) and open the PR. `coverage-status` never writes `ready`: a registry MMSI is not an operator-confirmed identity.

## Known gaps

- [#339](https://github.com/Grahammmm/skippercast/issues/339): offering retirement in `refresh.py` does not yet gate on discovery being `complete` (see *Reading a run*).
- [#340](https://github.com/Grahammmm/skippercast/issues/340): the `teck-reports` and `directories` adapters record the binding id (`socalfishreports`, `ggfa`, ...) as `source_id`, but `catalog/fleet/resolver.json` ranks adapter kinds (`teck-reports`, `directories`), so their facts are stored but never win a column. Boats known only from those sources get no resolved values from them until it is fixed.
- design.md § 9 "Known gaps, CF-17 scope": the staging sink writes no `<run_id>:registry.<batch>` row, so a staging run's `fleet_runs` has the step rows only.
