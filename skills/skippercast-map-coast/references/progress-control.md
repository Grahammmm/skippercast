# Control effort against a publishable result

Use at the start of a mapping run and before a new source, repair, review or
release stage. Keep this control block in the existing private checkpoint;
do not create another catalog, queue or scheduler. Explicit user allowances and
deliverables override these defaults. This control changes effort allocation,
never source qualification, rights, legal restrictions or required reviews.

## Plan the complete path first

Choose one named source/reach batch and an observable visitor-map acceptance
test. Before reading survey pixels, inspect the retained receipts and headers
for these downstream capabilities:

- A real native-processing path for the region and format, including CRS,
  window/resource bounds and physical-cache registration.
- A reviewed source-rights path and current, complete regional restriction
  screening. Preliminary intersection is triage, not publication clearance.
- A compatible geometry and publication contract. A region package, planning
  grid or private diagnostic does not establish this path.
- A positive opportunity outside the retained baseline, with an exact runtime,
  cache, command and sufficient scratch. Reuse known negative findings.

Record each readiness gate as `verified`, `unknown` or `blocked`, with its
evidence and the next cheap test. Resolve one cheap unknown in preflight rather
than qualifying many surveys behind missing regional infrastructure. A known
all-held candidate or missing publication path cannot enter the expansion lane.

For a map-growth task, allow a repair only when a retained reproduction links it
to the named positive batch and it is the last known blocking prerequisite.
If several independent prerequisites are missing, report that map growth is not
yet executable. If the user's scope includes regional infrastructure or private
research, select **one** bounded preparation deliverable with its own acceptance
test; do not silently turn expansion into an unlimited infrastructure project.

Start with the coordinator running deterministic scripts. Delegate one isolated
execution task only when useful; start the independent reviewer when a reviewable
artifact exists. Add a second source worker only after one complete release and
when the budget and downstream capacity can absorb it. Validated private
candidates awaiting any downstream gate count toward the two-handoff limit,
including blocked candidates. Renaming their stage does not free queue space.

## Shared operating allowance

Unless the user supplies an allowance, use an initial calibration ceiling of
**500,000 observed accounted tokens and 45 active minutes**, whichever is reached
first. Reserve 50,000 tokens and 10 active minutes within that ceiling to finish
or safely hand off an already-started named publication. These are conservative
operating defaults, not prices, promised throughput or a host goal budget.
Do not set a tool's `token_budget` unless the user explicitly requested one.

Use one cumulative counter covering coordinator and delegated work. Preserve its
scope and baseline across sources, turns, rebases and repairs. Read actual usage
at dispatch and stage boundaries, not on every model response. If no suitable
counter exists, record token usage as unavailable and enforce the active-time
and attempt limits; never estimate spent tokens as measured. Cached input,
uncached input, output, reasoning subsets and aggregate goal counters are
different quantities. Do not add cumulative snapshots or reasoning twice, or
infer billing from them.

Within the run ceiling, cap a candidate at 75,000 observed tokens / 20 active
minutes, a necessary repair at 100,000 / 20 minutes, and cheap preflight at
15 active minutes. Include all delegated work in these stage totals when
available. Background processing time does not consume the active-time clock;
model reasoning, repeated observation and reporting do. Record unknown timing
as unknown. A stage cap saves a handoff; it does not authorize another attempt.

After **two completed candidate batches without a verified public delta**, or
**30 active minutes since the last public delta**, stop active expansion and
report the failed path. A private proof, source download, CI pass, pipeline fix,
screen refresh, new branch or additional metadata does not reset either count.
Only a verified new outline or real expansion with retained live-readback
evidence resets them. No amount of intermediate progress replenishes the run
allowance. Continuing past the allowance requires a new explicit owner choice,
not a self-issued new run ID or another worker's encouragement.

## Execute and check decisions

The standard-library helper is advisory workflow control, not scientific
validation or an autonomous spender. It reads an existing checkpoint without
changing it. Call it before each stage; honor its result rather than merely
recording it. Its stop result forbids new active work, not safe checkpointing or
canceling an external job. It cannot enforce a budget in a host that ignores it.

```bash
python skills/skippercast-map-coast/scripts/check_progress.py /private/checkpoint.json
```

The checkpoint's `progress_control` block contains:

| Field | Contents |
| --- | --- |
| `run_id`, `batch_id` | Stable mission and bounded batch IDs. |
| `purpose`, `phase` | `publication` or explicitly scoped `preparation`; `preflight`, `qualification`, `repair`, `waiting` or `finalize`. |
| `limits` | Optional overrides to the documented defaults, with owner instruction retained in the checkpoint. |
| `accounting` | `scope`, `start`, `current`; use `null` counters for unavailable usage. Do not switch scope mid-run. |
| `active_minutes`, `stage_active_minutes`, `active_minutes_since_public_delta` | Cumulative active work; preserve across intermediate successes. |
| `candidate_tokens`, `repair_tokens` | Measured stage usage, or `null` when unavailable. |
| `gates` | Readiness statuses for `native_pipeline`, `rights_path`, `screen_path`, `geometry_contract`, `publication_contract`, `resources`. Keep evidence alongside these statuses. |
| `outcomes` | Ordered completed batches: `published_delta`, `private_proof`, `blocked`, `no_delta`, `pipeline_fix` or `maintenance`. Public deltas require positive `new_outlines` or `expanded_outlines` and a `readback_receipt`. |
| `qualified_handoffs_waiting` | Unique existing queue job IDs, including qualified-but-blocked jobs. |
| `repair` | Named batch, reproduced failure receipt and whether this is its only remaining known blocker. |
| `finalization_job_id` | An already-started job; the reserve cannot launch a new batch. |

The helper checks attestations, not their scientific truth. Existing source,
claim, independent-review and protected-release guards remain authoritative.
Counter monotonicity, owner overrides and handoff ownership are coordinator
responsibilities in the same checkpoint; the helper creates no parallel store.

## Avoid spending model work on waiting and revalidation

Use one deterministic observer per exact run/job. Persist its identity and
changed states. Do useful independent work while it runs; otherwise end active
expansion with an exact resume command. Use available completion events or
bounded observation within host limits. Do not keep a model agent active solely
to poll, restart a run after a read timeout, or manufacture hourly discoveries.
An observation deadline can be fulfilled by a real recorded observer; a goal or
instruction alone is not one. Do not create another schedule unless requested.

Invalidate evidence only for a changed scientific input, method, selection,
datum/registration or applicable policy. Unchanged scientific blobs after a
rebase reuse their existing source proof; review the new base and run all
required exact-head CI. Freeze the checked head before tests or review. Use a
prepared compatible runtime, existing dependencies and incremental receipts;
do not tar whole checkouts or repeatedly run known-incompatible local suites.
Never waive required CI or a newly relevant scientific check to save tokens.

At every calibration checkpoint, report public additions and active expenditure
first, then private discoveries and demonstrated repairs separately. When the
path is blocked, save the strongest verified handoff, rejected routes and exact
missing dependency. Stop. The next run starts from that evidence, not another
full conversation or archive read.
