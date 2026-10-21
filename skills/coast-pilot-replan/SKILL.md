---
name: coast-pilot-replan
description: Turn a pinned coastal pilot audit into numbered bounded changes and next-cycle cards, without changing gates or executing follow-up work.
---

# Coast pilot replan

## Purpose

Pilot programme only; retire after long runs start. The driver translates an
exact audit into numbered changes, revised segment plans and bounded next-cycle
cards. It is not an autonomous replan executable or permission for long runs.

Governing contracts: [discovery](../skippercast-discover-coastal-sources/SKILL.md),
[mapping](../skippercast-map-coast/SKILL.md), [shared contracts](../coast-campaign-shared/references/contracts.md),
[metrics](../coast-campaign-shared/references/metrics.md) and
[audit](../coast-pilot-audit/SKILL.md).

## Runs on

The admitted campaign driver. Independent review follows actual-model
qualification, never profile-name assumptions. Use the exact pinned AgentOrange
SC_REPO and existing shared SC_PY; no route or host substitution.

## Inputs

Exact audit/metrics file pins, prior plan, READINESS-CRITERIA.md pin, designated
replan destination, card-authorized source/cohort inventory and next-cycle scope.
For reproducibility, the same card-bound absolute ROOTS, COAST_ROOT, COHORT,
CYCLE_START_UTC, optional INTERIM_DIR and BOARD_EXPORT as the audited attempt.
METRICS_OUT is a NEW write-once destination. Confirm the card's code commit with
git rev-parse HEAD and confirm SC_PY before use.

## Exact commands

From SC_REPO, reproduce the section 7.9 rollup (no invented replan CLI):

```bash
"$SC_PY" skills/coast-campaign-shared/scripts/metrics_rollup.py --roots "$ROOTS" --root "$COAST_ROOT" --cohort "$COHORT" --since "$CYCLE_START_UTC" --interim "$INTERIM_DIR" --board-events "$BOARD_EXPORT" --out "$METRICS_OUT"
```

Omit an optional argument when absent, not an empty value. Compare semantic
fields and evidence pins with the audit; never overwrite either attempt. Edit
only designated plan/replan documents through file tools. Every numbered change
cites the measured issue, its population/Ref/field, proposed bounded change and
next acceptance test/preconditions. An unavailable metric becomes an explicit
test gap, not an invented estimate or tuned threshold.

Create bounded specialist cards using kanban_create with explicit kernel parent
IDs, admitted inputs/pins, exact tests and do-not-touch scope. Use verified real
profile names. B3 consumes this numbered list only AFTER its producer parents
are complete at reviewed pins. Read back created cards/edges before announcing
handoff. Preserve old receipts byte-for-byte; next cycle is a new cohort/attempt.

## Acceptance checks

Every change maps to a numbered audit issue and test; no measurement or evidence
claim is stronger than the audit. Preserve all-window Q/W, conditional Q/A,
replacement deduplication, examined-only confusion, required-unavailable versus
structural N/A, distinct-plan throughput and unknown cost/rescue evidence.
Record operator readiness disposition explicitly, including gaps and prerequisites.
Report the numbered plan and exact file pins to the operator. This is not a new
G decision unless it genuinely exceeds existing authorization.

## Failure modes

An unknown statistic remains a test gap. A missing authenticated audit/plan pin
requires corrective handoff; no newest-file search. Ambiguous scope or genuinely
unavailable endpoint/medium/decision is surfaced on the current card. Do not
silently loosen a gate, substitute a held model or execute proposed changes to
keep the next cycle moving.

## Metrics emitted

Same receipt-derived metrics envelope as the audit; plus numbered issue-to-change
and acceptance-test mapping with evidence, preconditions and operator disposition.
No handwritten performance figures and no extra corrective verdict throughput.

## Never

Execute follow-up build work, change thresholds/caps/routes/allowlists, install
skills, mutate old receipts or canonical ledgers, enqueue duplicate local jobs,
start long runs, publish, email, release cache or silently grant any gate. Route
implementation to bounded specialist cards; semantic acceptance stays independent.
