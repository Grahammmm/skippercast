# Bounded browser-test quarantine (SC-CI-3)

A quarantine **retries, never skips**. Ordinary Playwright tests have zero
retries. Only the admitted Swell-field case in `v2-map.spec.ts` has an effective
`@flaky` tag and two retries. Every assertion, viewport and shard is retained;
a failure on all three attempts still fails CI.

## Admission and clock

`e2e/flaky.tsv` requires one row per spec: `spec`, `first_seen` (UTC), `owner`,
`expiry` (exclusive UTC date), and the exact `test` title. Invalid dates,
unowned rows, duplicates and deadlines beyond 15 calendar days are rejected.
The owner is the repository owner, not an invented team. This is not permission
to tag an entire file or to quarantine a deterministic failure.

The existing nightly `Offline checks` schedule uploads every shard's Playwright
JSON even on failure. Its accounting job publishes `e2e-flake-rates` (JSON,
Markdown and clock state), plus the same table in the job summary. The flake
rate is **tests recovering on retry / executed project-test instances**, per
spec for that night; final failures and intentional skips are separate columns.
An all-skipped denominator is unknown, not zero. No historical rate is inferred
from incomplete runs. No tests are duplicated in the accounting job.

Fourteen consecutive UTC nights with first-attempt passes expire the effective
tag and retries automatically on subsequent runs. Every shard and both
phone/laptop instances of the admitted test must be present; retries, failures,
skipped/missing targets, duplicate shards, global errors and missing dates do
not earn green credit. A rerun cannot overwrite an observed bad night. The
nightly-only cache stores this clock; PRs only restore it and cannot save it.
Changing the registry resets its cache namespace. A missing/evicted cache
restarts observation, never invents green days. Independently, the TSV's hard
deadline removes the tag/retries even without green evidence (2026-11-27 for
the initial row), so cache loss cannot create an indefinite quarantine.
Expired rows remain as admission receipts; the report's **active** count shrinks.
Remove a retired row and its describe wrapper together in ordinary reviewed
cleanup. The browser test itself must remain.

## Before evidence (read-only Actions metadata/logs, 2026-11-13)

The latest 150 main runs ending at run 43468265209 reproduce the audit's
72 success / 11 failure / 67 cancelled. Eight failed runs include `e2e (2)`:

| Run | Failing browser spec/case | Disposition |
| --- | --- | --- |
| [43468265209](https://github.com/Grahammmm/skippercast/actions/runs/43468265209) | `v2-sheet-reach`: phone-land footer/drag geometry | Not proven flaky; unchanged |
| [43350390176](https://github.com/Grahammmm/skippercast/actions/runs/43350390176) | `v2-map`: Swell hit reads Survey edge | Same admitted Swell case |
| [43269215101](https://github.com/Grahammmm/skippercast/actions/runs/43269215101) | Swell pixels; phone-land sheet footer/drag | Swell recovers on attempt 2; sheet stays red |
| [43212726904](https://github.com/Grahammmm/skippercast/actions/runs/43212726904) | `wcag-views`: Basis/Source reading-order contract | Deterministic contract mismatch; unchanged |
| [43211282083](https://github.com/Grahammmm/skippercast/actions/runs/43211282083) | Same reading-order contract | Unchanged |
| [43209881266](https://github.com/Grahammmm/skippercast/actions/runs/43209881266) | Same reading-order contract | Unchanged |
| [43208432117](https://github.com/Grahammmm/skippercast/actions/runs/43208432117) | Same reading-order contract (also recovered account-autofill/layout-shift cases) | Unchanged; no blanket file quarantine |
| [43195186258](https://github.com/Grahammmm/skippercast/actions/runs/43195186258) | Swell pixels/hit selection | Same admitted Swell case |

The audit's **two whole-run same-head recoveries are not two e2e flakes**:

* [43168947180](https://github.com/Grahammmm/skippercast/actions/runs/43168947180),
  head `9312858cc2dc8c17ba084bd65b07f06f9f82336b`: attempt 1 job
  `131017321872` fails the laptop Swell case (pixels 67, expected <12);
  attempt 2 has no failed jobs and the run is successful.
* [43243379668](https://github.com/Grahammmm/skippercast/actions/runs/43243379668),
  head `ff3ec3ccd2726c31db606fca2f00f1934ce0f7ae`: attempt 1 job
  `131270059251` fails **Node**, `tests/test_accounts.mjs`,
  `sessions_need_auth_and_keep_existing_request_gates`; attempt 2 is successful.
  Playwright retries cannot fix a Node test, so it is not added to `flaky.tsv`.

The <1 failure/week and zero whole-run recovery targets require a post-merge
seven-day observation window; they are not claimed by this implementation.
Rollback: revert the SC-CI-3 commit through a reviewed PR. This restores the
previous Playwright retry policy and removes nightly accounting; no product,
source data, generated contracts, permissions or deployment settings change.
