---
name: coast-sign-off
description: Independently review an immutable coastal packet or issue a corrective integrity verdict with chained evidence, never scientific acceptance from syntax alone.
---

# Purpose

Tier 3 reviews every flag and deterministic sample in one admitted plan/round/attempt.
A normal verdict is independent semantic judgement; a bad-evidence verdict is only
corrective. These are draft offline helpers, not authorization for live mapping,
publication, installed-skill changes, model routes or release.

Governing contracts: [discovery](../skippercast-discover-coastal-sources/SKILL.md),
[mapping](../skippercast-map-coast/SKILL.md), and
[shared receipts/lifecycle](../coast-campaign-shared/references/contracts.md).
Implements design rev4 sections 1, 3–6, 7.4, 7.6–7.7; design SHA256
c8fabf7e2e1451af762ee9c9e52c32cab5831877e34cae3f7a5a98b00bb6d433.

# Runs on

A named, qualified reviewer with proven ACTUAL runtime model/family independent
of the run author, admitted by the pinned operator routing policy. Profile names
and requested aliases are not provenance. The checked-in empty routing template
is fail-closed, not an operational grant. Missing qualification, same family,
forbidden family pair or absent allowed pair refuses before semantic review.
Never substitute another model/route to make the command succeed.

# Inputs

Use the card's AgentOrange SC_REPO, shared-venv SC_PY, exact code commit, COAST_ROOT
and operator ROOTS bindings. Confirm `git rev-parse HEAD` and `"$SC_PY" --version`.
C is the campaign root, P=C/plans/plan-id, R=P/review/rNN/aNN, CTX=R/context.json.
All CLI file paths are absolute. Run from SC_REPO. QUEUE_ROOT_ID and any additional
root IDs come independently from the admitted card, not by trusting ROOTS contents.

CONTEXT_INPUT is an independently supplied JSON context envelope, matching
coast-review-context-v1 (the helper sets schema/round/attempt). It contains exact
admission/run/bridge/enqueue Refs, identity/author provenance, posted hashes,
root inventory, config/prompt refs and explicit supersedes/correction-verdict refs.
No latest-file search. One round correction retains plan identity; source/grid/
plan changes need a new admission. New attempts supersede the preceding context;
r02/a01 pins r01's must_fix verdict. Existing output files are never overwritten.

The following evidence envelopes contain JSON but use .txt filenames (opaque to
the shared graph validator; checked by role here):

- identity_provenance: exact campaign_segment_id, coordinator_segment_id, plan_id,
  plan_sha256, run_author_model, run_card_id from the trusted card/handoff.
- posted_hashes: admission/run/bridge/enqueue keys with the independently posted
  Refs. Current disk hashes cannot silently replace missing posted pins.
- run_author_provenance and REVIEWER_PROVENANCE: exactly actual_model, family,
  profile, card_id, code_commit, skill_commit, created_utc, session_id, provider;
  every value is a nonempty string. This is card-authenticated runtime evidence,
  not a model's self-declaration. Reviewer qualification is a separate policy Ref.

DECISIONS is write-once reviewer-authored JSON: exactly verdict (accept/must_fix/
hold), decisions, must_fix, tier2_assessments, external_blocker. Each window decision
contains window_key, defect (boolean or null), accepted_cause (string or null),
detail and evidence (Refs). Findings use the shared severity/code/detail/evidence
shape. Tier2 assessments contain finding_index (index in packet.flags) and confirmed
(boolean); accuracy names the assessed versus total finding population. No assessed
claims means null, not perfect accuracy. For hold, external_blocker must contain
kind (endpoint/medium/operator_decision) and nonempty detail; otherwise it is null.
Retain and hand off the decisions file, its hash and printed action/metrics alongside
the verdict; no board IDs are inserted into an immutable verdict.

# Exact commands

Create the explicitly admitted fresh R/tier3 directory before these commands.
Repeat `--allowed-root-id` for EVERY independently admitted binding, including repo
config roots if used. These examples show a single queue binding, as in the tests.
The context/report hash options extend rev4's minimal argv: independent pins are
necessary to detect changed context/report bytes rather than trusting a pathname.

```sh
"$SC_PY" skills/coast-sign-off/scripts/prepare_round.py --roots "$ROOTS" --allowed-root-id "$QUEUE_ROOT_ID" --inputs "$CONTEXT_INPUT" --round "$REVIEW_ROUND" --attempt "$ATTEMPT" --out "$CTX"
"$SC_PY" skills/coast-sign-off/scripts/open_packet.py --roots "$ROOTS" --allowed-root-id "$QUEUE_ROOT_ID" --context "$CTX" --expected-context-sha256 "$CONTEXT_SHA256" --packet "$R/tier2/review-packet.json" --expected-packet-sha256 "$PACKET_SHA256" --reviewer-model "$REVIEWER_MODEL" --reviewer-provenance "$REVIEWER_PROVENANCE" --out "$R/tier3/open-report.json"
"$SC_PY" skills/coast-sign-off/scripts/write_verdict.py --roots "$ROOTS" --allowed-root-id "$QUEUE_ROOT_ID" --context "$CTX" --expected-context-sha256 "$CONTEXT_SHA256" --open-report "$R/tier3/open-report.json" --expected-open-report-sha256 "$OPEN_REPORT_SHA256" --decisions "$DECISIONS" --minutes "$MINUTES" --out "$R/tier3/verdict.json" --ledger "$C/ledger.jsonl" --campaign-ledger "$COAST_ROOT/campaign-ledger.jsonl"
```

Post prepare_round's context Ref independently before tier execution. T1/T2 run
between prepare and open, using explicit pins; see their producer skills. Post
packet SHA independently before open; retain open-report Ref from its stdout for
write_verdict. Optional `--expected-packet-bytes` adds a posted byte-count check.
A missing packet SHA writes a corrective report, never authenticates current bytes.

# Acceptance checks

- Context bytes, independently supplied identity and actual author provenance agree.
  Rehash the full normal graph, not only products; all window states match the
  admission/run/T1 inventory. Re-derive population and coast_sample selection from
  map_done, complete required measurements and every T1/T2 must/should finding.
- Examine every flagged and sampled window. Accept refuses any packet must finding
  (including HASH_MISMATCH/REQUESTS_NONZERO), nonempty corrective findings or reviewer
  defects. Held/unavailable/unfinished cases require explicit accepted closure causes;
  these do not become negative quality labels or authorize segment closure.
- Normal verdict uses full_graph. Integrity failure uses mandatory must_fix/invalid,
  packet/population/confusion/accuracy=null, no examined windows or next inventory.
  The context edge is identity_snapshot ONLY on the corrective branch: failed producer
  expectations are diagnostics, not valid scientific refs. Context corruption itself
  needs a new independently authenticated diagnostic context before a verdict.
- Validate every receipt with validate_coast_receipt.py and independently check both
  ledger chains. Exit 0 is structural validity, not scientific acceptance.
- write_verdict alone writes verdict rows through coast_ledger.append_index. Both
  segment and campaign-index rows must exist before announcing a result. Repeating
  identical inputs reconciles a cross-file crash idempotently; different payload
  at the same round/attempt refuses. New work needs a new attempt, never overwrite.

Board lifecycle (performed by the profile, NEVER by a script):

- accept: create the authorized next admission child, or separately gated close
  preparation after FULL inventory accounting; complete the current V-/T3 card
  with verdict and created IDs in the handoff. Not a publication declaration.
- must_fix: create a correction child with numbered findings and exact pins, plus
  the fresh r+1 T1/T2/T3 dependency chain; complete current V-/T3 as review completed:
  must_fix, NOT plan accepted. Third bounce goes to fable-2nd-look.
- hold: block the current review only for a genuine external endpoint, medium or
  required operator decision. Hash/packet defects are corrective must_fix, not holds.

Never call request_changes on an already completed RUN parent. Read board writes
back via kanban tools. Board IDs belong in the subsequent handoff, not the verdict.

# Failure modes

open_packet exit 3 with an open-report still proceeds to write_verdict's mandatory
integrity-error branch. Retained observed packet bytes are opaque .bin evidence.
Changed direct context-pinned run and changed tier input both permit corrective
ledger/index rows without requiring the broken scientific chain to validate itself.
Wrong/uncertain reviewer or corrupted context refuses semantic output; obtain
corrective authenticated identity/pairing, never opt a normal review down to the
snapshot scope. If evidence changes after a successful open, write_verdict refuses;
start a new attempt/report. Broken ledger chain is an external reconciliation need,
not permission to truncate, repair or bypass it.

# Metrics emitted

Receipt: actual review minutes, windows_examined, named confusion counts and
exclusions, assessed Tier2 packet accuracy or null. Stdout additionally computes
recall, precision and misses plus explicit held, unavailable-required, unfinished,
invalid-evidence, unexamined and reference-undetermined populations. Only examined
mapped complete-evidence definite-reference windows enter tp/fp/fn/tn. Optional
structural N/A is not unavailable; accepted closure causes never convert held or
required-unavailable windows to tn. Null means not measured. These sampled,
flag-enriched metrics are NOT whole-coast detection performance. Preserve stdout
in the review handoff; no inference of readiness from these counts alone.

# Never

No source/network/model calls, Store/board DB writes, cap/policy/allowlist changes,
installed-skill/profile edits, hidden route substitution, output rewriting, deletion,
email, publication, live runs or release authorization. Preserve all previous round
bytes and AgentOrange canonical service/data boundaries.
