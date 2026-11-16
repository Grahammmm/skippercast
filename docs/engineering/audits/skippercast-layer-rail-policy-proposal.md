# Layer-rail ownership and dependency-only lockfile policy: proposal (AUDINV-CIW-75)

Status: PROPOSAL ONLY. Report-only unit. It assigns no PR, starts no round, creates no card, queue row or PR, and implements no pipeline. Nothing here is semantic acceptance.

## 1. Problem and source

`reports/ci-audit/WORK-SHAPING.md` (agent-work, SHA256 `2c177abe...853ef`) names two rules:

- Line 67 (observed, timestamped sample): `web/app/App.tsx`, `web/app/LayerRail.tsx`, `e2e/p04-catch-contrast.spec.ts` and `package.json` + `pnpm-lock.yaml` were touched by 4 / 3 / 3 / 3 open PRs. An 8-PR cluster sat on the layer rail. Proposed fix: one "layer rail" PR per round with one builder, and lockfile changes only in a dependency PR.
- Line 87 (rule R4): "lockfile only in dependency PRs".

The line 67 counts are a historical sample. This report does not show the cluster still exists. In the visible part of the open-PR snapshot taken for this unit (remote main `0991fc70...`; the listing was truncated), no PR touched `LayerRail.tsx`, `App.tsx` or a lockfile. Recheck before any implementation.

Related facts on main (observed): `scripts/check_e2e_pins.py` fails a PR that changes a file pinned by `REVIEWED_SOURCE_INPUTS` (for example in `e2e/p04-catch-contrast.spec.ts`) without re-pinning it in the same PR. Layer-rail files are therefore hash-pinned. Two parallel PRs on those files will conflict on the pin constants as well as on the source. That is a second reason to give the area a single owner.

## 2. Definitions

- **Round**: one planner pass (Overwatch, Astra or operator), as in WORK-SHAPING R1. Round identity = `<planner>-<ISO date>-<seq>`, recorded in the planning card, for example `overwatch-2026-11-16-1`.
- **Feature-area key**: the module directory or screen/stage, per R1. The layer-rail key is `web/app/layer-rail`. It covers `web/app/LayerRail.tsx`, `web/app/rail.ts`, the layer-rail strings, and the `App.tsx` and e2e hunks that exist only to host the rail.
- **Owner**: the single builder card/branch/PR assigned for a (round, area key) pair. The planner names it at planning time.
- **Contribution**: a requirement ID or change request that falls in the same (round, area) but belongs to a non-owner. It is handed to the owner as a section of the owner's acceptance table, not as its own PR (R1).
- **Dependency PR**: a PR whose only product effect is changing `package.json`, a lockfile (`pnpm-lock.yaml`) or both.

## 3. Proposed policy

P1. **One layer-rail owner per round.** For a named round, at most one PR may change files in the layer-rail area key. All layer-rail requirement IDs in that round become sections of that PR's acceptance table.

P2. **Owner decision.** The planner records the owner when it names the round. If two changes arrive with no owner recorded, ownership is UNKNOWN. Nothing is reassigned automatically. The planner (the custodian of round metadata) decides.

P3. **Non-owning contribution handoff.** A contribution is posted as a comment on the owner card with: requirement ID, files, and its acceptance assertion. The owner includes it in the one PR, or says in the PR body why not. The contributor does not open a rival PR.

P4. **Dependency-only lockfile changes.** `package.json` dependency fields and lockfiles change only in a dependency PR. A UI/feature PR may not change the lockfile. Where a feature needs a new package, the dependency PR comes first and merges first. This matches the R2 exception for a dependency "that is not on main".

P5. **The dependency pair is atomic.** `package.json` and its lockfile always change together in one dependency PR. Never split them and never leave one behind.

P6. **Scope of serialization.** The rule binds only the layer-rail area and the lockfile. Unrelated feature areas run in parallel and are not serialized globally.

P7. **Preserve existing arrangements.** Existing owner admissions, hash pins and already-authorized dependency exceptions stay as they are. The proposal does not reassign any active PR. If an admitted exception conflicts with P1 or P4, it goes to the owner of that admission, and the proposal does not overwrite it.

P8. **Receipts preserved.** Failed or partial receipts and attempt histories are kept as they are. A merged-into-owner contribution does not erase the history of the card it came from.

## 4. Fixed synthetic collision (illustration; NOT observed)

Everything below is synthetic. It has no real PR numbers, creates no PR, mutates no board and makes no throughput or timing claim.

Round `SYNTH-ROUND-1`. Two hypothetical changes arrive:

- Change A (synthetic): add a "Wind" toggle row to `LayerRail.tsx`, a hook in `App.tsx`, and an assertion in `e2e/p04-catch-contrast.spec.ts`.
- Change B (synthetic): reorder rail entries, touching `LayerRail.tsx`, `App.tsx` and the same e2e spec. B also needs a new package, so it edits `package.json` and `pnpm-lock.yaml`.

**Today (collision):** A and B are two PRs. Both edit `LayerRail.tsx`, `App.tsx` and the e2e spec, so the second to merge conflicts on all three. Both re-pin the same `REVIEWED_SOURCE_INPUTS` hashes, so a second conflict arises in the pin constants. B's lockfile diff also conflicts with any other lockfile PR.

**Under the proposal:**

| Item | Outcome |
|---|---|
| Owner | One branch/PR (call it `SYNTH-LAYER-RAIL-OWNER`) holds both UI changes. |
| A's requirement | Section A1 of the owner's acceptance table: Wind row present, e2e assertion kept. |
| B's requirement | Section B1: rail order changed, e2e assertion kept. |
| Pins | Re-pinned once, in the owner PR (`check_e2e_pins.py`). |
| Lockfile | Not edited by the owner PR. B's new package goes into a separate dependency PR (`SYNTH-DEP`), which changes `package.json` and `pnpm-lock.yaml` together. It merges first, and the owner PR is based on it. |
| Admission | The dependency PR needs its own admission. This proposal does not supply one. |

Result: two PRs (one owner, one dependency) replace two overlapping UI PRs. Both acceptance requirements survive, one set of conflicts is removed, and the lockfile is touched by one PR only.

## 5. Report acceptance cases

| # | Case | Treatment under the proposal |
|---|---|---|
| 1 | Two disjoint non-layer-rail features | Not serialized (P6). Each keeps its own PR. |
| 2 | Two changes in one layer-rail round | One owner, both requirements kept as sections (P1, P3, section 4). |
| 3 | Needed dependency + lockfile | Stays atomic in one dependency PR; a UI PR may not change the lockfile (P4, P5). |
| 4 | Existing admitted exception | Escalated to its admission owner, not overwritten (P7). |
| 5 | Missing round/owner metadata | Ownership UNKNOWN; no automatic reassignment (P2). |
| 6 | Synthetic collision | Labeled synthetic; no PR, no board change, no timing claim (section 4). |

## 6. Mechanism versus expected gain

- **Mechanism (reasoned, not measured):** fewer PRs may edit the same hunks, so fewer textual conflicts and fewer repeated pin re-pins.
- **Expected gain (UNKNOWN):** WORK-SHAPING reports R4's effect as a drop from a 13-PR cluster to a 3-PR cluster. That is the audit's own estimate, not measured here. No post-change conflict rate exists, and none is claimed.
- **Costs and risks:** the owner PR gets larger and may become a bottleneck. A late contribution waits for the next round or is added to the owner by the owner's decision. A dependency PR in front of a UI PR adds one merge step.

## 7. Future enforcement

Any pipeline enforcement (for example a round-ownership check or a "lockfile only in dependency PR" gate) must be separately admitted as a hermes-ops CANDIDATE ONLY. It must have no live `bin/`, `modes/`, `units/` service or queue edits. This report creates no card or queue row, assigns no ongoing PR or round, and publishes nothing.

## 8. Gaps (named)

- Current layer-rail overlap: UNKNOWN. The only evidence is the line 67 sample. The visible, truncated open-PR snapshot shows no overlap. Custodian: ship-queue/planner.
- Round identity convention: PROPOSED here. Custodian: the planner owners (Overwatch/Astra/operator).
- `pnpm-lock.yaml` exists at the repository root of the main clone used for this unit (observed).
- Admission of any dependency PR or pipeline gate: not given by this report.
