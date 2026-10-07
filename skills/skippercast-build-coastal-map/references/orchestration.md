# Bounded agents and progress

## Starting model/effort settings

Resolve names and supported efforts against the current tool/client. The pairs
below use the available October 2026 tool catalog. They are hypotheses to test,
not official workload guarantees or established empirical minima. Keep explicit
user settings. Do not silently substitute a model, change global settings or
inherit a flagship/maximum effort for every small worker.

| Task | Start | Raise only when |
| --- | --- | --- |
| Fetch, decode, hashes, ranges, raster math, builds, tests, job waiting | Existing deterministic scripts; no model for execution | Model diagnosis needs interpretation of a real failure |
| Extract explicit metadata, compare receipts, known-file inventory | `gpt-6-luna` / `low` pilot; `medium` if pilot fails | Missing/contradictory facts need interpretation rather than extraction |
| Bounded source discovery or visual defect triage | `gpt-6-luna` / `high` | Incomplete provenance or uncertain cause after a bounded attempt |
| Routine adapter/CSS or isolated interaction implementation | `gpt-6.1-sol` / `low` | Multiple state/edge cases or an unexplained failure → `medium` |
| Cohesive visual design, shaders, seams/LOD, shared state/integration | `gpt-6.1-sol` / `medium` | Cross-component ambiguity or quality remains below acceptance → `high`/`xhigh` |
| Independent science, rights, spatial exclusion or privacy review | `gpt-6.1-sol` / `high` | Conflicting consequential evidence → supported Astra / `medium` review |
| Coordinator for a substantial map/data/release batch | `gpt-6.1-sol` / `medium` | Difficult architecture/scientific tradeoff → `high`; retain current parent if changing it is unsupported |
| Final visual/interaction review | `gpt-6.1-sol` / `medium` | Persistent unclear defects → `high`; routine fixed-check scans can later test Luna/high |
| Release gate execution and live readback | Scripts plus coordinator's current setting | Unexpected state/identity/runtime mismatch; no automatic flagship escalation |

OpenAI's starting advice favors Luna for narrow work and Sol for demanding agents;
it also recommends experimenting on the same inputs. The Luna/low extraction
pilot is intentionally below its general Luna/high starting suggestion. Never
lower rights/privacy/science review on the strength of a successful formatting
exercise. Use [calibration](calibration.md) to find the lightest tested pair per
specific task. No prices, fixed subscription savings or token percentages inferred.

Sources checked October 2026:
[model selection](https://developers.openai.com/api/docs/guides/model-selection),
[subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).

## Team shape and ownership

A simple fix stays with the parent. For a substantive batch, assign one execution
worker and an independent reviewer; add a source worker only when its output can
advance independently. Honor repository limits and available slots. One owner
merges shared state/catalog/manifest/CSS changes and operates release. Workers use
owned worktrees or disjoint files; they cannot stage/reset another owner's changes.
A reviewer must not become the only author/reviewer of its own correction.

Use `fork_turns="none"` for bounded workers with explicit model/effort when tools
allow it. Supply relevant artifacts, not the whole chat. Existing agents retain
settings/context; inspect these before reuse. If a different setting is needed,
start a compact worker instead of assuming a follow-up changes its model. Do not
start a worker merely to wait for CI, format logs or repeat the parent's search.

### Worker brief (usually under 250 words)

```text
Outcome: one observable deliverable / answer.
Scope: region/layer, exact source or revision, owned paths; read-only paths.
Inputs: 2–5 relevant paths/URLs, current receipt and unresolved fact.
Constraints: required datum/rights/time/state invariants; mutation authority.
Acceptance: concrete check(s), expected output artifact.
Bound: one batch or investigation checkpoint; no recursive delegation.
Return: changed paths, checks, evidence links, blocker fingerprint, next action;
        concise summary, raw logs saved to files.
Model/effort: explicit supported pair, reason and escalation trigger.
```

Give an independent reviewer the task and raw artifacts, not the intended answer.
Serialize computer-use ownership. A source researcher does not need the browser
surface reserved for visual review. Integration-dependent stages stay sequential.

## Keep progress moving

Each active batch should end with a usable map delta, a demonstrated fix or a
specific source decision that unlocks the next executable action. More fetched
metadata, refreshed unchanged snapshots or larger polygon counts alone are not
completion. Keep at most two qualified source handoffs ahead of processing.

Classify a blocker: external policy/access; rejected rights/quality; runtime bug;
missing measurement; missing regional binding; visual acceptance. Record identity,
last evidence, attempted method and what change permits retry. Different archive
hashes do not resolve unchanged rights. Browser access failure cannot justify a
security bypass. Missing coverage can use honestly labeled model context, not
invented reef detail or rankings.

After two equivalent failed attempts without new evidence, change method or
move to an independent ready task. About 20 active investigation minutes without
a usable result is a checkpoint, not permission to weaken a gate. Time waiting
for a deterministic job is separate; let it run with bounded completion checks.
A materially changed source, authorized access or new diagnostic can justify
another attempt. For safety-critical/repeated user monitoring, follow its own
contract; do not apply a generic retry cutoff to required monitoring.

Use tool waits/event cursors or saved command sessions, not repeated model polls.
Keep one status receipt per job and read only changed/error output. If an upstream
service is unavailable and no independent work remains, report the exact blocker
and stop active investigation. Do not silently create a recurring task.

Checkpoint before a restart: current revision, source/hash identity, completed
stages, next command, active job/session, owner and evidence. Resume those stages;
never annual-backfill buoy history or reacquire unchanged surveys as routine upkeep.
