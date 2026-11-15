# Local merge-queue feasibility — AUDINV-CIW-67

## Decision and boundary

**Technically plausible; activation HOLD.** The recorded public repository and
current `merge_group` wiring justify further evaluation, not an enabled or proven
queue. Account entitlement, live merge-group check parity, a successful week of
safe stacking and activation ownership are **UNKNOWN**. This report requests no
administrator action and sets no deadline, timer or automatic after-a-week action.

The only change authorized here is this local report, delivered in its report PR.
No queue/ruleset/branch-protection/API writes, activation PRs, merges, orchestrator
removal, workflow changes or service changes are performed or authorized.
Historical G intent does not widen this report-only unit. Machine-valid fixtures
are review-required evidence, not semantic or operational acceptance.

## Evidence identities and scope

Snapshot reviewed on **2026-11-15T23:26:00Z**. Repository evidence is frozen at
main **`0991fc70d212c9405f7b174950cb3fa4d7c6846d`** (`git log -1
--format='%H %cI'`: commit time `2026-11-15T14:59:46-08:00`). Relative repository
locators below refer to that SHA, not an unpinned future main.

| Ref | Source / exact locator | Date and identity |
|---|---|---|
| S1 | `.github/workflows/ci.yml`:3–24, 30–87, 118–151, 160–221, 278–436 | Frozen main above; SHA256 `d5adcbf28f195542346f21c37f68b2902441a3533778225a4bbaf5c7c5bfef6e` |
| S2 | `.github/workflows/dco.yml`:9–60 | Same main; SHA256 `829d753fd31c17efbaf031ff2cd55db4dac22984d40f60711569a8225d3184f1` |
| S3 | `.github/required-checks.json`:1–9 | Same main; SHA256 `5a39f6f09c1ecf638680742be66c8ca92557dd453dd6064077a2992bd187a47c` |
| S4 | `scripts/ci_select.py`:55–101, 104–145 | Same main; SHA256 `3a012dae24ecd89cc5c3505f80fbdcb968b09c9d22dda8f894a94aa4515a346d` |
| S5 | Local admitted spec `/home/user/agent-work/reports/oc-specs/AUDINV-CIW-67.md`:1–71, 293–336 | Dated 2026-11-15; SHA256 `48aa8bb3bf1678a5a976dfc8cc8329da3d31bc9ea35dffd3f3ba7678dc5e9f20` |
| S6 | Local `/home/user/agent-work/reports/ci-audit/THROUGHPUT.md`:3, 21–59, 84–113 | Historical analysis, 2026-10-28 08:45 PDT; SHA256 `4abb6d2a63ae648efeded66645711e526e5c50fc5c63d975f2935bc698cf16ed` |
| S7 | Local `/home/user/agent-work/reports/ci-audit/evidence3.txt`:1–24, 53–64 | Historical receipts, 2026-10-28 08:2x PDT (minute incomplete in source); SHA256 `7eea0f9872017884750548cf69176545e72ed52c43faecd00fed5881ee983164` |

S5 retains successful read-only API commands and their exact responses; these are
**recorded receipts**, not API observations refreshed by this builder. Its checked
source was rechecked at `2026-11-15T23:13:02.893314+00:00`; separate API collection
timestamps are not recorded. API state is not intrinsically bound to a git SHA.
No account/billing/credential inspection or new live-group experiment was made.

## Feasibility matrix

OBSERVED means source/receipt observation; INFERRED means limited interpretation;
UNKNOWN means missing evidence, not a negative result. HOLD means do not activate.

| ID | Dimension | Evidence and classification | Feasibility / missing proof |
|---|---|---|---|
| MQ01 | Public repository / plan availability | OBSERVED recorded S5: `visibility=public`, `archived=false`, `default_branch=main`. S6:59 says public SkipperCast is available. | Public-repository route is plausible (INFERRED); current account/plan entitlement is UNKNOWN, not verified by visibility. |
| MQ02 | Queue / ruleset state | OBSERVED S5 rulesets response `[]`. Repo receipt has `allow_auto_merge=false`. | Enabled native queue is UNKNOWN; an empty rulesets list does not exclude classic branch protection, and auto-merge is a different feature. |
| MQ03 | Classic required checks | OBSERVED recorded S5: `strict=false`; three context/app pairs retained verbatim below. | Protection settings exist in the receipt. `strict=false` neither proves queue state nor supplies a safe-stacking receipt. |
| MQ04 | Merge-group event coverage | OBSERVED S1:8–9 and S2:15–16 both declare `merge_group: types: [checks_requested]`. | Source wiring PRESENT; trigger presence is not queue enablement or evidence that GitHub delivered a production group. |
| MQ05 | Required-context parity | OBSERVED S3 adds `e2e` to the three API contexts; S1 has four e2e shards. | Recorded API / local registry / emitted-name parity is UNRESOLVED. Live group contexts, app IDs and conclusions are UNKNOWN. |
| MQ06 | Exact tested tree / SHA | OBSERVED S1 uses default checkout, synthetic-merge first-parent comparisons and merge-group base SHA; S4 selects all areas for non-PR events. | Source is merge-group aware. Actual production group head/base, check-suite SHA, tested tree and eventual merged-tree correspondence are UNKNOWN. PR-head green alone cannot prove them. |
| MQ07 | Evidence gate / cancellation | OBSERVED S4 rejects failed, cancelled, pending, empty and skipped required prerequisites; S1:22–24 cancels obsolete PR runs only. | Offline evaluator behavior is covered by fixtures; live cancellation, expiration and stale-group replacement handling remain UNKNOWN. No cancelled result becomes success. |
| MQ08 | DCO semantics | OBSERVED S2:31–60: PR commits use the base checker; merge-group `sign-off` only emits a notice that PR heads were already checked. | This is an existing prior-PR-check assumption, not a fresh group-commit signature audit. Live same-head admission/removal behavior remains UNKNOWN; preserve the gate unchanged. |
| MQ09 | Full-tier workload | OBSERVED S1: non-PR groups run both Python legs, full GIS parts and four e2e shards; 3.13 non-PR runs also audit production dependencies. | Source coverage is broader than PR affected-area coverage. Queue latency, capacity, cost and audit failure rate are UNKNOWN; S6 throughput estimates are not measurements of today's queue. |
| MQ10 | Safe-stacking observation window | S6 proposes Option S and recommends evaluating Q after a week. S7 records historical batch totals, not a week of Option S success. | Zero qualifying week-long receipts identified in the bounded inputs; actual safe-stack count and safety are UNKNOWN, not zero executions, proof of safety or proof of unsafety. |
| MQ11 | Culprit / duplicate / stale behavior | S6 describes prefix bisect, quarantine, no automatic re-addition and exact-head review. | Proposal is not an executed trace. Production failure isolation, duplicate suppression, expired group disposal and stale approval/check rejection are UNKNOWN. |
| MQ12 | Activation authority / ownership | S5:20–22 admits the audit row; S5:275 quotes historical G queue intent dated 2026-10-28. | Report-only scope governs. Current administrator availability, designated activation operator and approved concrete change package are UNKNOWN; no administrator request is sent. |
| MQ13 | Custom orchestration coexistence | S6:59 anticipates removing custom tooling; S6:113 reserves changes. | A retirement/cutover/rollback plan and current sole-merger ownership receipt are UNKNOWN. Preserve existing custom orchestration and verification ownership; no removal or parallel merger. |

### Recorded API commands and exact context identities

The following commands are **S5 receipts, not commands executed in this report
build**. Each has recorded exit 0; stdout is reduced here only to relevant fields.

- `gh api repos/Grahammmm/skippercast --jq '{full_name,visibility,archived,default_branch,allow_auto_merge,allow_merge_commit,allow_squash_merge,allow_rebase_merge}'`
  recorded public, non-archived, main; `allow_auto_merge=false`,
  `allow_merge_commit=true`, `allow_squash_merge=true`, `allow_rebase_merge=true`.
- `gh api repos/Grahammmm/skippercast/rulesets` recorded **`[]`**.
- `gh api repos/Grahammmm/skippercast/branches/main/protection/required_status_checks`
  recorded **`strict=false`**, with exactly these context/app pairs:

| Exact context | app_id |
|---|---|
| `survey-science` | `15368` |
| `check (3.13)` | `15368` |
| `sign-off` | `15368` |

S3 records those same pairs **plus `e2e` / `15368`**. S1:181 produces four e2e
matrix legs (workflow commentary names `e2e (1)` through `e2e (4)`), rather than
an explicit unsharded `e2e` aggregate job. This is a static mismatch to reconcile,
not authority to edit protection/registry or a claim about actual group checks.
`survey-science` aggregates `changes`, both `check` legs and `survey-tests`; its
success does not establish e2e success. Live required/emitted parity stays UNKNOWN.

## Safe-stacking evidence and limits

S7:53–56 records **46 opened / 40 failed / 2 merged** historical batches across
the audited tooling; the source does not establish these as SkipperCast-only
Option S prefixes. S7:59 names historical SkipperCast main `4854d361d3`
(abbreviated as recorded), with 15 successful and 6 skipped check-runs at that
snapshot. Neither aggregate proves a currently green main or a week of safe stacks.
S6's Option S throughput and risk calculations are explicitly modeled estimates.
Do not count ordinary merges, legacy batch merges, synthetic fixtures, time since
G's intent or elapsed calendar weeks as the required successful observation window.
This bounded review read S1–S7 and searched current `docs/` and `reports/` for
stack/queue references; it did not exhaust runtime logs or request new custody data.

## Future activation prerequisites — not actions scheduled here

All remain prerequisites for a **separately scoped, explicitly authorized** change.
Missing custody facts do not block completion of this report.

1. **Repository/account custodian:** provide dated native-queue entitlement and
   full applicable protection/ruleset evidence, including target branch and any
   inherited rules. Public visibility and `[]` alone do not discharge this gap.
2. **CI/check custodian:** reconcile exact required names/app IDs across classic
   protection, local registry and all emitted group checks, including e2e shards;
   retain exact-head CI, DCO, review and science/publication gates unchanged.
3. **Existing merge/stack operator:** supply a dated successful week-long Option S
   trace with admitted members, approved heads, green starting main, disjointness/
   hazard decisions, tested prefix trees, check IDs/conclusions, merge outcomes,
   resulting main checks, and all failures/cancellations/expired/stale/duplicate
   cases retained. A missing case is UNKNOWN, not an invented passing trace.
4. **CI and merge operators:** in separately admitted validation, establish actual
   merge-group head/base and check-SHA/tree semantics, same-name app-bound reports,
   capacity/latency and safe failure/removal behavior. Existing local fixtures
   cannot substitute for a production-group receipt or authorize such a run.
5. **Policy/admission owner and designated administrator:** identify the existing
   sole merger/verifier, exact authorized activation package, reviewer coverage,
   cutover/rollback conditions and protected holds. No ownership is reassigned by
   this report, and historical intent is not permission for an unscoped live edit.

**Stop condition:** retain this evidence-gap report for review. No administrator
request, branch-protection/API change, custom-tool retirement, queue activation or
automatic action follows after a week, even if the missing receipts later arrive.

## Bounded local validation

On the frozen source, `python3 -B scripts/ci_select.py --fixtures` executed under
`/home/user/agent-work/bin/memcap --` and reported **3263 selector/evidence fixtures
passed** (exit 0). These are synthetic evaluator/path fixtures, including negative
prerequisite statuses, not production merge groups. The unchanged workflow-pin and
determinism wiring unittest selection passed **9 tests** (exit 0). Report acceptance
also requires a nonempty file, clean whitespace and manual semantic review of the
six S5 edge cases; exact build commands/output belong to the PR handoff. No new
permanent checker, tests, pins, manifests or implementation files are introduced.
