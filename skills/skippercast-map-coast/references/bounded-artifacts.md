# Bounded artifact assignments

Choose one scope and output class before source work. Default to a proposed
60-minute wall-clock allowance, including five minutes to checkpoint and stop;
obtain a separate owner decision before extending it. Existing 45-active-minute
and observed-token controls remain ceilings, not targets to spend. Never start
timed trials, extra regions or schedules because a skill describes them.

## Define useful output and the complete path

Use one of these acceptance units in the existing private checkpoint:

| Assignment | Useful output | Does not count |
| --- | --- | --- |
| Public habitat | New/expanded screened outline with live readback | Private proof, CI or release bookkeeping |
| Private mapping handoff | Inspectable geospatial/terrain artifact, valid support/mask, provenance, class-specific independent acceptance, exact next action | Download, metadata report or a successful tool alone |
| Render preview | Reproducible local preview of an accepted slice, fixed camera and source/coverage labels | Build alone or a substitute region |
| Preparation | One explicitly requested, reproduced prerequisite fix | Unbounded source research behind other missing prerequisites |

Private/provisional outputs count only for an assignment that requests that
class. They never gain public coverage credit, ranks, fishing export or website
permission from being useful. Keep accepted, provisional and rejected candidates,
their stable source/window IDs, reason, artifact hash and next action in the
existing candidate/coverage store. Use its union/deduplication semantics.

Preflight exact host/runtime, input paths and hashes, native reader/window limits,
scratch, current source rights and restrictions, downstream schema/loader and
available reviewers. Record verified/blocked/unknown with one evidence pointer
per gate. Resolve a cheap unknown once. If several prerequisites are missing,
stop that route or take separately authorized independent work. A known
all-held fishing candidate cannot enter the publication lane. A different
permissible output class needs its own acceptance, not a waived gate.

## Enforce the command allowance

Use [run_bounded.py](../scripts/run_bounded.py) with the **same existing checkpoint**.
It adds a `run_control` block; it does not replace catalogs or the older
`progress_control` publication-readiness check. Run
[check_progress.py](../scripts/check_progress.py) before publication-lane stages
and honor its decision. The bounded runner governs local subprocess effort,
not scientific truth, tool permissions, hosted models or remote services.

Example, only after a real assignment is authorized:

```bash
python <mapping-skill>/scripts/run_bounded.py /private/checkpoint.json init \
  --scope REGION/BATCH --kind private_handoff
python <mapping-skill>/scripts/run_bounded.py /private/checkpoint.json run \
  --candidate SOURCE/WINDOW --fingerprint INPUT_METHOD_POLICY_SHA256 \
  --seconds 300 -- python existing_bounded_command.py
python <mapping-skill>/scripts/run_bounded.py /private/checkpoint.json status
```

`--kind` is `private_handoff`, `public_habitat`, `render_preview` or
`preparation`. Defaults: 3,600 wall seconds, 300-second cleanup reserve,
1,200 seconds without accepted useful output, two attempts per stable candidate,
500,000 observed uncached-input-plus-output tokens. Explicit owner allowances
can set smaller/different initialization limits. Never renew an initialized
checkpoint or rename a source to evade a stop. Keep the same deadline across
rebases, repairs, model changes and host restarts.

The input/method/policy fingerprint excludes superficial task names and formatting.
It includes immutable source/artifact hashes, source window, method revision and
only the policies relevant to that computation. Reuse unchanged scientific
proof after a rebase; run required CI on the new head separately. Retry only
with a changed fingerprint and `--changed` pointing to the new evidence/method
receipt. After two attempts, skip or escalate that candidate. Do not lower a
threshold or invent a new identity to get another attempt.

The runner saves intent atomically before launch, uses a monotonic subprocess
timeout bounded by remaining mission/stagnation time, and terminates its process
group on timeout/interruption (up to two seconds of termination grace). Commands
must not daemonize or create outside jobs; retain handles and use each service's
own bounded cancellation/observation facilities for those. One lock prevents
concurrent local launches. Process exit zero is not useful output.

Use `record-output --attempt N --artifact PATH --receipt PATH` only after
acceptance. Receipt JSON must contain `accepted: true`, the exact
`artifact_sha256`, and the initialized `scope` and `kind`. Retain actual
review evidence in that receipt; this binding verifies identity, not review
authority. Duplicate artifact hashes do not reset stagnation. No accepted
output extends the mission deadline or replenishes token/attempt budgets.

Ordinary SIGTERM/SIGHUP and keyboard interruption enter process cleanup. SIGKILL,
host loss and power failure cannot be intercepted; a host supervisor/cgroup is
needed for an execution deadline that survives loss of the wrapper. Do not claim
that this local helper controls external services or unobserved hosted models.

After a crash, status refuses a still-running intent. Inspect the recorded process
group/job and checkpoint. `recover --receipt PATH` requires a receipt with the
same `run_id` and `processes_stopped: true`, and refuses a still-existing process
group. If a crash occurred before its PID was saved, establish that no orphan
remains before attesting stopped. Recovery marks an interrupted attempt; it
does not erase the attempt or reset the allowance.

## Spend models on decisions, not waiting

Coordinator first: deterministic extraction, conversion, checks and receipts.
Use the lowest-cost available model that has passed comparable task checks;
where uncalibrated, use one available small-model worker on an isolated bounded
task. A local model is an option only after availability and task-specific checks,
not assumed access or savings. Keep the brief to goal, five relevant paths,
ownership, bounds and acceptance. Do not fork the full conversation.

Start independent review when artifacts exist. Do not keep a fixed pool of
guard/source agents, or a model alive to poll. One deterministic observer per
job records state changes. Use completion events or end the turn with the exact
resume command. Missing input/access/network problems need an environment or
scope decision, not a stronger model. Escalate a model-caused failure once with
its reproduction to an available stronger model; reserve Astra for diagnosis,
planning and hard exceptions. Never introduce paid services.

## Accounting and retrospective

Import scoped provider response records with `account --jsonl PATH`.
Required row: `response_id`, `usage.input_tokens`,
`usage.cached_input_tokens`, `usage.output_tokens`; optional model/effort and
reasoning-output subset. Identical response IDs count once; conflicting duplicates
fail. Input includes cached input. Accounted = input - cached + output.
Never add reasoning or cumulative thread/goal snapshots again. Missing imported
usage is unknown, so wall/attempt limits remain mandatory; this wrapper cannot
prevent a hosted model's first response exceeding an unseen token allowance.
Start audits in a small context, from the checkpoint and indexed sample.

Retain raw input/cached/output fields, model/effort, actual elapsed time,
cost-rate source/date/units (or unknown), useful-output denominator and its class.
Any dollar estimate is separate and must price cached input separately. Do not
call accounted tokens dollars, active time, marginal cost or waste.

End every authorized assignment with this compact receipt:

- Planned scope/class and acceptance; attempted candidates and useful artifacts.
- Exact paths/hashes, support geometry/method and union coverage delta; accepted,
  provisional/rejected counts separately; publication/readback separately.
- Input/cached/output totals, missing usage, elapsed versus available active time,
  assumptions, tokens/time per useful artifact (undefined for zero output).
- Attempts, changed retries, failure class, stopped/skipped regions, remaining jobs,
  allowance remaining/exhausted and one next action.
- Proposed evidence-backed skill correction for a **separate reviewed revision**.

Do not edit the running skill, turn a retrospective into another loop or add work
to fill unused time. A blocked route can finish early.
