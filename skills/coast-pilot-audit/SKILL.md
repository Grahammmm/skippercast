---
name: coast-pilot-audit
description: Produce an evidence-scoped coastal pilot readiness audit from a frozen cohort, without granting readiness or starting long runs.
---

# Coast pilot audit

## Purpose

Pilot programme only; retire after long runs start. Write a readiness report for
the operator from pinned receipts, not remembered numbers. This is not an
automatic release gate or scientific acceptance.

Governing contracts: [discovery](../skippercast-discover-coastal-sources/SKILL.md),
[mapping](../skippercast-map-coast/SKILL.md), [shared contracts](../coast-campaign-shared/references/contracts.md),
[metrics](../coast-campaign-shared/references/metrics.md) and
[layout/environment](../coast-campaign-shared/references/directory-layout.md).

## Runs on

An admitted independent reviewer under the actual-model qualification policy.
Profile names are not proof of model identity; same-model review is forbidden.
Use the card's pinned AgentOrange worktree and existing shared SC_PY, not a new
venv, installed skill copy, alternate host or substituted model route.

## Inputs

Card-bound absolute SC_REPO, SC_PY, COAST_ROOT, ROOTS, COHORT, CYCLE_START_UTC,
METRICS_OUT and audit destination. Confirm git rev-parse HEAD against the card's
expected commit and SC_PY before execution. COHORT freezes ALL admitted inventory
admissions (including held/missing runs), explicit continuations, every review
round/attempt and both ledger snapshots. It independently admits root IDs;
ROOTS supplies their disjoint actual paths. See metrics.md for exact shapes.
Also supply the pinned READINESS-CRITERIA.md, optional INTERIM_DIR, BOARD_EXPORT,
and separately reviewed actual contour/preview, N16 and campaign-performance
measurement envelopes. Missing optional evidence stays unavailable.

## Exact commands

Execute from SC_REPO; all variables below are card-bound, never guessed paths.
With the optional evidence present, the rev4 section 7.9 command is:

```bash
"$SC_PY" skills/coast-campaign-shared/scripts/metrics_rollup.py --roots "$ROOTS" --root "$COAST_ROOT" --cohort "$COHORT" --since "$CYCLE_START_UTC" --interim "$INTERIM_DIR" --board-events "$BOARD_EXPORT" --out "$METRICS_OUT"
```

Omit --interim and/or --board-events entirely when not supplied; never pass an
empty string. Use a new METRICS_OUT for each attempt (write-once). Audit prose is
written through file tools to the designated destination, citing output Ref and
field paths against EVERY readiness-criteria line. Do not type replacement
numbers into the report. The output is a structurally checked review input, not
an operator decision.

## Acceptance checks

- W contains all distinct admitted inventory windows, replacement attempts
  deduplicated. Missing run evidence does not remove W. Show W/A/Q and exclusions.
- Q/W alone assesses the all-admitted 95% target; Q/A is explicitly conditional.
  Zero denominators are not measured. Every hold needs an accepted cause.
- Report examined mapped complete-evidence confusion only, lists/counts of
  held/unavailable/unfinished/invalid/unexamined/undetermined, misses, sample size
  and sampling bias. No whole-coast detection assertion from a selected sample.
- Isolated no-geometric-neighbours N/A is not unavailable. Required unavailable
  remains excluded from tn even if its closure cause was accepted.
- Contours need separate reviewed contour/preview artifacts; hillshade statistics
  do not prove seams clean. N16 needs actual PC-6 execution, not held/dry-run data.
- Throughput counts distinct final accepted original inventories, not corrective
  verdicts. Report fully mapped and accepted-held throughput separately; preserve
  unknown cache/cost/projection/rescue evidence and its observation period.
- Post exact output hash, evidence gaps and every readiness line's disposition
  to the admitted audit card. Operator readiness approval remains separate.

## Failure modes

Unknown evidence is not measured, not pass. Bad refs are visible broken evidence;
unknown admissions, ambiguous replacements or unsafe paths refuse rather than
invent a denominator. Correct upstream evidence through a fresh attempt/card;
never edit old receipts or rerun queue jobs to make the report clean. Missing
endpoint/media/required decision is an external blocker, not permission to change
routes. Audit failures and corrective integrity findings do not grant readiness.

## Metrics emitted

The full metrics.md envelope: qualification populations, confusion and sample,
receipt integrity, review rounds/minutes, Tier2 accuracy, distinct-plan throughput,
pipeline versus model time, tokens and explicit unavailable supplementary
contour, N16, cache, cost, projection and scoped operator-rescue measurements.
Interim producer observations remain separately labelled interim.

## Never

Start long runs, tune thresholds, grant gates/routes/caps/hosts/concurrency,
duplicate local queue jobs, mutate canonical ledgers/Store, download sources,
install skills, publish, email, delete cache or turn structural validation into
semantic acceptance. Follow-up implementation belongs to specialist child cards.
