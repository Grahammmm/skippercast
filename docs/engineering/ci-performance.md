# Offline CI performance

## Scope and baseline (2026-10-27)

One change to Offline checks and DCO scheduling. No application code, test
assertions, skip allowlist, runner configuration, branch protection or deployment
policy changes. Required context remains `survey-science`.

Timings below come from GitHub job/step timestamps (`gh run view ID --json jobs`),
not estimates. Queue delay is measured from run creation to job start, and is not
execution time. The shared runner/account queue is a separate limitation.

| Successful baseline run | Event / head | Full Python job | Python test step | Browser job | Core 3.11 / 3.13 | Creation to completion |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| [40609252018](https://github.com/Grahammmm/skippercast/actions/runs/40609252018) | PR / `7a86c6a773765d1e63037e8e325ae7897ad01f02` | 2346 s | 2309 s | 705 s | 244 / 259 s | 6288 s |
| [40618570283](https://github.com/Grahammmm/skippercast/actions/runs/40618570283) | main / `b7a309b0f1d224244b7855c74814d4f757063992` | 3540 s | 3498 s | 715 s | 284 / 251 s | 10217 s |

Survey job queue delay was 3941 / 6677 seconds respectively. Dependency installation
was only 16 / 23 seconds. The first run's full JUnit artifact has 5481 cases:
5448 passed, 33 allowlisted skips, zero failures/errors. Its two slowest modules
(`test_coast_close_safety`, `test_coast_segment_close`) used about 966 and 743
seconds. Splitting by directory or file would leave those tests on one slow job.

## Changes and why

- Four full-stack Python shards. Every job collects the same default pytest
  testpaths, requires GIS, retains the original strict options, and runs one
  deterministic balanced partition of node IDs. Long historical tests are
  distributed first; new/fast tests use a small nonzero default weight. Historical
  weights are scheduling hints only, never an allowlist. Each shard retains
  original collection order for its selected tests.
- Each shard uploads its JUnit and a receipt of all collected, selected and
  actually executed node IDs. The original required `survey-science` name is now
  an always-running aggregate. It rejects missing/failed/cancelled jobs, mismatched
  heads/collections, missing/duplicate tests or shards, and incomplete execution.
  Strict skip reporting runs on every shard. Search-plan rebuild, geometry check
  and committed-output diff still run (once, on shard 1).
- Python-only core checks still run in a no-GIS environment. Ordinary PRs use 3.13;
  main pushes, `batch/*` PRs and manual bot-PR runs use 3.11/3.12/3.13. Batch branch
  pushes are deliberately not an extra trigger: their PR already runs the full
  matrix, avoiding duplicate suites. Python-independent Node/type/copy/token/
  website/build/audit checks move unchanged into one parallel `web` job, instead
  of being repeated per Python version. The required aggregate also requires
  these checks and the browser suite.
- Pip cache keys now include `pyproject.toml` and the relevant pinned requirement
  files; setup-python also separates Python/OS/architecture. Both Node consumers
  use setup-node's pnpm lockfile cache after installing pnpm. Locked installation
  always runs; `node_modules`, editable checkouts and generated outputs are not
  cached. Chromium uses an exact lockfile/OS/architecture/Node-major key, no broad
  fallback, in runner-local temporary storage. Browser installation still verifies
  the revision and installs OS libraries on hosted runners, even on a cache hit.
- Concurrency includes workflow, event and ref; only PR revisions share the
  replaceable `latest` slot and cancel in progress. Main/manual runs retain a
  unique run ID so pending deploy-eligible main runs cannot be replaced by a
  manual run. DCO uses its own workflow/ref group. Scheduled/data/deploy
  concurrency is intentionally unchanged.
- Deploy already only follows successful **push/main** Offline checks (or its
  explicitly guarded manual route), never PRs. It is unchanged and covered by a
  new contract test. No deployment is requested for validation of this PR.

## Path-filter safety

The workflow itself is never path-filtered. `changes` uses a full local Git tree
diff between the PR base and head (NUL separated, no rename folding), not a
paginated API result or GitHub's limited path-filter list. Unknown/empty/failed
diffs run all suites. Comparing trees is conservative if main advanced. Main,
batch and manual runs always run everything.

The survey suite may skip only for changes exclusively to contribution forms
(`.github/ISSUE_TEMPLATE/` or `.github/pull_request_template.md`). Core Python,
repository/privacy scans, all web checks and DCO still run. In particular,
`docs/` is **not** ignored: claims and contract tests consume documentation.

Browser tests may also skip for changes exclusively to Python files in
`src/skippercast/`, `tests/` or `research/tests/`. These are not inputs to the
JS/TS browser build. Any accompanying generated `dist/`, region/catalog,
JS/TS, dependency, workflow, build-script or unknown-path change runs browsers.
The `e2e` aggregate reports the intentional exclusion without leaving a required
context pending. Deleted/renamed files are considered on both sides of the diff.

## Validation and interpretation

Local mechanical tests cover PR/main/batch/manual selection, conservative
fallback, mixed/renamed paths, aggregate success and failure/cancel/skip cases,
new-test inclusion, deterministic partitions and receipt corruption. The actual
pytest plugin is exercised with parameterized/class cases, a setup skip and a
real failure. No test is removed or marked expected-failure for this change.

Actionlint validates workflow syntax/expressions. Representative candidate
GitHub Actions results and before/after observations are recorded in the PR and
review handoff once complete. Local Python 3.12 diagnostics are not claimed to
be the required Python 3.13 CI. Historical timing weights cannot prove a speedup;
compare actual candidate job duration, critical path and queue delay separately.
Warm caches, runner load, changed test counts and moving main limit direct
before/after comparisons. No improvement to account-wide runner capacity is
claimed.
