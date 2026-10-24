---
name: coast-verify
description: Run the V- child coastal review using coast-sign-off's independent evidence and corrective-verdict lifecycle; no competing verifier.
---

# Purpose

The V- child is Tier 3, not another implementation. Load and follow
[coast-sign-off](../coast-sign-off/SKILL.md), including its shared contracts and
[discovery](../skippercast-discover-coastal-sources/SKILL.md)/
[mapping](../skippercast-map-coast/SKILL.md) governing boundaries.
Draft only; structural validity is never scientific acceptance.

# Runs on

The explicitly named qualified independent reviewer admitted by the pinned routing
policy. Verify actual author/reviewer runtime provenance and different model
families; profile names prove nothing. No held-route substitution.

# Inputs

Exactly coast-sign-off's card-pinned roots, immutable rNN/aNN context, independently
posted context/packet/report hashes, actual reviewer provenance and decisions.
Confirm AgentOrange SC_REPO/SC_PY and expected code head. No latest-file lookup.

# Exact commands

Use coast-sign-off's prepare_round.py, open_packet.py and write_verdict.py commands
unchanged, with absolute paths and independently admitted --allowed-root-id options.
There is intentionally no coast-verify script or alternate validation path.

# Acceptance checks

Apply all sign-off acceptance checks. Examine all flags and the re-derived clamped
sample, rehash all normal pins, require valid independent provenance and both
chain-valid verdict/index rows. Bad inputs produce a corrective must_fix/error
verdict with null measurements, never acceptance. Context corruption needs a new
independently authenticated diagnostic context.

Perform the shared lifecycle: accept creates next admitted work and completes V-;
must_fix creates correction + fresh r+1 T1/T2/T3 chain and completes V- as review
completed, not accepted; third bounce routes to fable-2nd-look. Only a genuine
external endpoint/medium/operator-decision blocker blocks the current review.
Never request_changes on the completed RUN parent. Scripts print actions; the
profile performs and reads back kanban writes. Created board IDs go in the handoff,
never a rewritten verdict.

# Failure modes

Follow sign-off's exit-3/error protocol. Hash/packet defects are corrective findings,
not external holds. Wrong/uncertain reviewer identity refuses semantic output.
Existing outputs require new attempts, not overwrite. No normal full_graph opt-down.

# Metrics emitted

The same review minutes, windows_examined/confusion exclusions, measured-or-null
Tier2 accuracy and stdout metrics as coast-sign-off. Held/required-unavailable
closure is never tn. Sampled metrics make no whole-coast recall claim.

# Never

No competing verifier, duplicate local jobs, source/model calls, canonical store
changes, installed skills, profile/permission/route changes, board DB writes,
publication, outbound email, destructive release or live execution.
