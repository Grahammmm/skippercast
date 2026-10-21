---
name: coast-segment-discover
description: Run one governed metadata discovery attempt and freeze a review-required coastal campaign catalog without acquiring native sources or accepting candidates.
---

# Purpose

One card-admitted metadata discovery under the governing
[discovery contract](../skippercast-discover-coastal-sources/SKILL.md),
[mapping contract](../skippercast-map-coast/SKILL.md) and
[shared contracts](../coast-campaign-shared/references/contracts.md).
Preserve candidate/absence evidence, rights, datum, variable-resolution and reader
uncertainty. A frozen catalog is review-required metadata, never source quality,
measured support, mapping acceptance or publication approval.

# Runs on

AgentOrange, checkout cwd SC_REPO, using its existing shared SC_PY interpreter
and PYTHONPATH=src. Verify interpreter and card-pinned commit first. Lead judgement
uses the admitted runtime; bounded staging only by an explicitly admitted worker
following a reviewed precedent. Profile names do not prove actual model identity.
No installed-skill/profile changes or model-route substitutions.

# Inputs

An approved finite live_discovery plan, campaign extent/label, source family,
original reviewed host allowance and allowance/retry bounds. Bind SC_REPO, SC_PY,
C (campaign queue), D=C/discovery/<unique-disc-id> and ROOTS to absolute card paths.
D/plan.json already exists. An optional previous manifest is an explicit absolute
card input, never the newest file. It must retain compatible source/method/policy/
region identities and original expiry. Campaign labels are not Store segment IDs.

# Exact commands

These existing producer commands do not resolve relative paths against C.
The run command is live metadata access and is executed only by its admitted
source-acquisition card, never merely because this draft documents it.

```sh
PYTHONPATH=src "$SC_PY" -m skippercast.coastal.live_discovery dry-run --plan "$D/plan.json" --out "$D/dry"
PYTHONPATH=src "$SC_PY" -m skippercast.coastal.live_discovery run --plan "$D/plan.json" --out "$D/run"
"$SC_PY" skills/coast-campaign-shared/scripts/validate_coast_receipt.py --roots "$ROOTS" --hash-dir "$D/run"
```

Optional producer --previous uses an explicitly supplied absolute path; do not
append an unset argument. Hash-dir is an integrity inventory ONLY, not semantic or
full native discovery graph validation. HELD: native discovery checkpoint/receipt
reference adapters and automatic evidence-envelope creation until their producer
adapter is reviewed and merged. An admitted coast-discovery-evidence-v1 envelope
may pin original catalog and retained metadata; do not rewrite native receipts,
flatten directory-relative references, or hide unsupported JSON behind text names.
This draft itself remains HELD for live use until independent review and merge.

# Acceptance checks

Actual producer receipt says within_caps; record complete output/diff/catalog
hash inventory, exact candidates/absences and unattempted queries. Catalog keeps
review_required=true, mapping_accepted=false, execution_authorized=false. Original
metadata evidence and unknown rights/datum/VR/reader state survive. The dry-run
alone does not prove requests ran or discovery succeeded. Native source bytes are
not downloaded. Only frozen explicit catalog/evidence pins pass to admission.

# Failure modes

Outage/access denial parks the bounded attempt with truthful partial evidence;
no same-card retry loop or host widening. Existing output requires a new disc-id,
not overwrite. Missing cache is a prefetch dependency/admission HOLD; it is not
permission to download native sources inside this skill. Unsupported receipt
references HOLD rather than claim a complete valid graph.

# Metrics emitted

Copy actual producer requests, response bytes, wall time, candidates, holds and
stop reason. Record unavailable measurements as unavailable, never synthetic
zeros. Metadata extent is not actual valid-data coverage.

# Never

Never acquire native sources, add hosts, edit canonical catalog, accept candidates,
start long runs, enqueue, publish, send email or install this draft into Hermes.
