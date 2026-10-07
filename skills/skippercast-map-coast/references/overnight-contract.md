# Overnight execution contract

Use after the owner authorizes a timed mapping goal. This is an execution mode
of the existing mapping skill, not a new scheduler or source catalog. Read
`parallel-pilot.md` for method-specific handoffs and `execution-and-release.md`
for real production commands. Do not copy all references into worker context.

## Preflight before unattended processing

1. Fetch main and reconcile relevant open PRs and active workers. Restore the
   latest private handoff and immutable regional baseline; do not reread the
   conversation or research archive. Verify runtime, cache and publishing access.
2. Record the UTC start, deadline, coordinator, optional release operator,
   actual slot limit, model choices and reporting cadence in the existing
   private checkpoint. If duration is unspecified, announce an eight-hour
   checkpoint window. This deadline does not mean the corridor is complete.
3. Select one bounded, executable positive batch and its acceptance checks.
   Reproduce any release blocker from retained evidence. Repair it in a focused
   reviewed PR, or select an independent ready batch; do not fill a discovery
   pool while no handoff can be processed or published.
4. Complete one end-to-end calibration batch, including current screens and
   live archive/map readback. If release access is unavailable, identify that
   limitation and continue useful private physical work; do not claim a release.
5. Prefer two workers plus one independent reviewer within the host's slots.
   Do not increase the pool until the two-hour checkpoint shows actual useful
   batches, capacity and no integration/review backlog.

Creating a goal is not proof that a worker, command or schedule is running.
Record actual dispatch and start receipts. A goal supplies continuity; it does
not wake a sleeping Mac or bypass account limits, permissions or unavailable
services. Preserve checkpoints before interruption. Never claim missed work ran.

## Queue state in the existing private checkpoint

Keep one coordinator-written `jobs` array alongside the existing handoff, not a
second state store. Worker evidence lives in exclusive output directories;
workers return receipt paths and do not edit the shared checkpoint. Each job has:

| Field | Meaning |
| --- | --- |
| `id`, `region`, `reach`, `source_ids`, `method`, `native_window` | Exact bounded batch identity; distinguish source pairs and windows. |
| `input_hashes`, `baseline_commit`, `baseline_receipts` | Source, method, dependencies and baseline used for this attempt. |
| `owner`, `branch`, `output_path`, `dispatch_state` | Exclusive owner and isolated writable scope; queued/dispatching/acknowledged. |
| `state`, `attempt`, `started_utc`, `checkpoint_utc` | queued/running/ready_for_review/reviewed/publishing/published, or blocked/no_delta. |
| `command`, `runtime`, `resource_bound`, `acceptance` | Reproducible command, bounded pixels/memory/bytes and observable success. |
| `receipt_paths`, `blocker`, `next_action`, `active_minutes` | Persisted evidence, exact failure and next reproducible step. |
| `metrics` | Separate native measured, physical, screened, public and ranked deltas, with evidence paths. |

Validate every claim before dispatch: no other active claim may own the same
source/reach/method/window or writable directory. At reassignment, first verify
that the earlier worker/process stopped; never steal a claim after a timer alone.
A worker acknowledges its current identity and output path before writing.
If dispatch is ambiguous, reconcile actual worker/process state before retrying.
Use `followup_task` for a completed worker; `send_message` alone does not start it.

The record describes execution, not scientific approval. Do not set `published`
until current rights/restriction receipts and complete regional live readback
pass. Keep pending publication regions until individually verified; a later
scoped push can replace a pending run without carrying its omitted scope forward.
At most two qualified handoffs may wait for integration. Reassign source capacity
to the bottleneck or let it idle instead of growing an unusable queue.

Use existing processing commands and receipts. Where this queue protocol lacks
a deterministic guard, implement a small offline-tested research helper before
claiming automated enforcement. Keep it outside product imports. Test exclusive
claims, interrupted dispatch, invalid transitions and missing release evidence.
Until that helper exists, the coordinator performs these checks explicitly;
this document alone is not a running queue service.

## Compact worker manifest

Send a fresh bounded brief with the following fields, not the full history:

- Outcome and acceptance; region/reach/source/method/window identity.
- Main commit and source/baseline receipt paths with hashes.
- Relevant skill reference only; runtime and exact first command.
- Exclusive branch/output path and resource bounds.
- Known blocker and two-attempt/20-active-minute change-of-approach rule.
- Required receipt and metrics; reviewer/integrator recipient.
- No shared-state writes, unrelated discovery, public restricted geometry,
  unsupported rank, gate waiver or additional agents outside assigned scope.

Prefer Luna medium for known-source qualification, established script execution
and simple receipt checks. Prefer Sol medium for coordination and implementation;
use Sol high for consequential scientific method review when needed. Keep the
coordinator's explicit user-selected model until the user changes it. Do not
silently escalate to Astra. Claim model savings only with measured appropriate
usage; total goal tokens cannot establish per-model cost or cache behavior.

## Cheap negatives, meaningful validation

Before expensive processing, check actual source headers/footprints, rights,
nominal depth support, known occupancy and preliminary MPA intersection. An
all-held batch need not consume a public release attempt. Keep useful physical
knowledge private. Preliminary negatives prioritize work; they do not replace
current whole-polygon publication restrictions or authorize publication.

Compare canonical geometry and declared scientific invariants, not raw JSON
ring order or insignificant formatting. Preserve geometry-to-ID associations.
Tiny positive projection intersections must be investigated with retained
native and projected fixtures, real-overlap negative controls and independent
review. No arbitrary epsilon, repair, buffer or threshold bypass. Version any
scientific method change and preserve invalid-original/material-overlap holds.

For production/native reconciliation, retain input identities, component counts,
areas, native membership fingerprints, hold categories and runtime receipts.
Use privacy-safe aggregate diagnostics for coordination; keep original geometry
and restricted records private. Equal counts do not prove equal geometry.

## Checkpoint, switch and stop

Report outcomes hourly in overnight mode, plus material failure, completion and
required owner action. At two hours, report the deliverable, unique area deltas,
rejected/held batches, processing and review/release waits, blocker and next task.
Increase concurrency only when ready independent jobs and processing capacity
exist and observed useful throughput warrants it. Do not promise linear speedup.

After two unsuccessful attempts, change approach using evidence. After 20 active
investigation minutes without a usable batch or demonstrated release-blocker
fix, save the blocker and select an independent executable task. New metadata
or debugging output alone does not extend that window. Diagnostics inform the
next approach but are not map expansion; a pipeline repair needs a reproduced
before/after test. If no useful task remains,
stop active expenditure and state the external dependency. Do not stay active
merely to use the whole overnight budget. Do not repeatedly poll unchanged jobs;
use completion events or bounded deterministic observation with changed states.

At the deadline, save a concise handoff with commands, completed/passed checks,
measured before/after unions, publication links, remaining holds and the exact
next command. Report separately:

- Additional deduplicated native measurement support.
- New physical habitat, with ranked terrain versus interpreted outlines.
- Current legally screened candidates and withheld candidates.
- Actually verified public area/count and newly supported ranks.
- Demonstrated blocker repairs, observed timing and provider-reported usage.

Polygon fragments, downloads and green refreshes are not geographic expansion.
Preserve unknown measurements as unknown. Mark a goal complete only when its recorded objective is achieved. A goal
explicitly limited to a bounded pilot may complete after that pilot is reconciled;
a broader corridor-mapping goal remains incomplete at the checkpoint deadline.
