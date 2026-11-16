# Research workflow usage and evidence gaps

## Scope and trigger state

Read-only snapshot: **2026-11-15T22:51:26Z**, source main
`7db22f216e2dc91cb0158d840091f9a1f5254156` (`git rev-parse HEAD`).
This report covers only `research-substrate.yml` and `research-fish-survey.yml`.
[PR #2186](https://github.com/Grahammmm/skippercast/pull/2186) merged at
`2026-11-13T03:21:49Z`, merge commit
`cfe3d2c98fd4120174805c077aeeb9bb616d5616`, verified with:

```sh
gh pr view 2186 --repo Grahammmm/skippercast --json number,title,mergedAt,mergeCommit,files
```

Both current YAML `on` mappings contain only `workflow_dispatch`; neither has
`schedule` or `cron`. Line-numbered trigger search output (grep-equivalent
search for `workflow_dispatch|schedule|cron` in these two files):

```text
.github/workflows/research-substrate.yml
4:  workflow_dispatch:
.github/workflows/research-fish-survey.yml
4:  workflow_dispatch:
```

The scratch receipt helper parses the YAML mappings rather than counting
indented job-like keys; these are static definitions, not executed matrix legs.
The helper and raw JSON receipts remain outside the repository. Executed from
the clone root:

```sh
"$HOME/repos/skippercast/.venv/bin/python" ../receipts.py
wc -l .github/workflows/research-substrate.yml .github/workflows/research-fish-survey.yml
```

Relevant helper output and line-count output:

```text
research-substrate.yml: triggers=[workflow_dispatch], jobs=20, lines=1665
research-fish-survey.yml: triggers=[workflow_dispatch], jobs=11, lines=482
  1665 .github/workflows/research-substrate.yml
   482 .github/workflows/research-fish-survey.yml
  2147 total
```

The helper summary above is a compact rendering of its JSON fields. The old
audit's substrate line count of 1,658 is not the current count; no workflow was
edited to reconcile that historical claim.

## Retained run receipts

The helper executed these read-only commands, with no date or event filter:

```sh
gh run list --repo Grahammmm/skippercast --workflow research-substrate.yml --limit 1000 --json databaseId,createdAt,event,status,conclusion,headSha
gh run list --repo Grahammmm/skippercast --workflow research-fish-survey.yml --limit 1000 --json databaseId,createdAt,event,status,conclusion,headSha
gh run view 41328673050 --repo Grahammmm/skippercast --json jobs
gh run view 36897081294 --repo Grahammmm/skippercast --json jobs
gh run view 41522705083 --repo Grahammmm/skippercast --json jobs
gh run view 37035590972 --repo Grahammmm/skippercast --json jobs
```

Each list returned **two retained runs**, below the requested limit. All were
`completed`, triggered by the former `schedule`, and concluded `failure`.
No `workflow_dispatch` runs were returned, including after the manual-only
merge. Measured manual usage in the available receipts is zero recorded runs;
this is **not** a conclusion that the workflows are unused or have never run
manually. The retention window is UNKNOWN.

| Workflow | Public Actions run | Created (UTC) | Event | Conclusion | Jobs / timed jobs | Job-seconds | Job-minutes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| substrate | [41328673050](https://github.com/Grahammmm/skippercast/actions/runs/41328673050) | 2026-11-01T16:54:04Z | schedule | failure | 20 / 20 | 1097 | 18.3 |
| substrate | [36897081294](https://github.com/Grahammmm/skippercast/actions/runs/36897081294) | 2026-10-01T17:07:40Z | schedule | failure | 20 / 20 | 1427 | 23.8 |
| fish-survey | [41522705083](https://github.com/Grahammmm/skippercast/actions/runs/41522705083) | 2026-11-02T20:49:23Z | schedule | failure | 11 / 11 | 1186 | 19.8 |
| fish-survey | [37035590972](https://github.com/Grahammmm/skippercast/actions/runs/37035590972) | 2026-10-02T16:41:06Z | schedule | failure | 11 / 11 | 174 | 2.9 |

Job-seconds sum each returned job's `completedAt - startedAt`; job-minutes divide
that sum by 60 and round to one decimal place. Every returned job had usable,
nonnegative timestamps. This measures summed wall-clock **job time**, not total
workflow elapsed time: jobs may overlap. The query describes the job records
returned at observation time, not an independently verified history of attempts.

## Known

- Both workflows are already manual-only on the pinned main; the predecessor
  change is present, so there is no remaining schedule to remove in this scope.
- Available history contains only the failed scheduled runs shown above. There
  are no recorded manual runs in that history; no new runs were dispatched for
  this report.
- These receipts show time spent on failed runs, not successful-run cost or
  demonstrated demand for a per-topic split. Source size and job count alone
  do not measure usage, savings, or useful output.

## Unknown and evidence needed

| Gap | Current finding | Evidence that would close it (not collected here) |
| --- | --- | --- |
| Billing and monetary cost | **UNKNOWN: no billing receipt**; no billing account access was used. | Authorized billing receipt tied to the workflows and observation period. |
| Successful-run duration | **UNKNOWN**: no successful run is present in the returned history. Failed-run job time cannot establish successful-run duration or cost. | An existing successful-run receipt with complete job timestamps. |
| Billed minutes and adjustments | **UNKNOWN**: billing multipliers, chargeable rounding, runner type and queue wait are not established by this extracted timing data. | Existing runner/billing metadata and a supported billing calculation. |
| Retention window and completeness | **UNKNOWN**: returned history is not a lifetime usage ledger; deleted or expired runs cannot be recovered from this query. | Custodian's retention policy and any existing archived usage receipts. |
| Off-record manual use | **UNKNOWN** whether anyone invokes equivalent commands outside Actions or has dispatches absent from retained history. | Existing research-owner/manual-use receipts, not an assumption from zero returned dispatches. |
| Need for a workflow split | **UNKNOWN**: no measured topic-level demand, successful-run cost, or split-benefit comparison was supplied by these receipts. | Measured need and a separately admitted scope. |

No split or trigger change is recommended or made; that needs measured need and a separate scope.

This report is the stopping point. It does not dispatch workflows, change
triggers, add telemetry, retire tooling, or authorize a later implementation.
