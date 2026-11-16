# AUDINV-FIX-149 — candidate-only tier-one handoff

## Boundary and source check

This is an **inert candidate**, not an installed legacy-helper repair. No product,
source data, approval policy, queue, services or installed helper was changed.
Checked main: `0991fc70d212c9405f7b174950cb3fa4d7c6846d`.
The spec's reusable-control finding still applies: existing typed Ref IO validates
literal root/path/hash/bytes, while vertical.py supplies metre lane floors. Those
sources are reused from this clone, hash-bound by BASES.json; vertical imports
must resolve to this clone. Historical helpers were never imported or run.
No open PR in the pre-build snapshot touched this candidate root.

## Contract and semantic checks

- The caller supplies an independently posted manifest, explicit admitted metadata
  refs and operator bindings. Only their bounded JSON leaves are read; no recursive
  discovery, arbitrary hex extraction, native hash reread or installed CLI calls.
  Receipt content must match a verified metadata leaf. Duplicate paths refuse even
  if hashes match; identical hashes at different literal paths are checked twice.
- The adapter returns a new object and never writes receipts. Original failed
  receipt/attempt history, window and status remain available unchanged; no grant,
  retry, refund, next-tile/model/render dispatch or semantic acceptance is inferred.
- Acquire HOLD stops with HELD / REVIEW_REQUIRED. Measured acquire zero remains
  zero; unrun qualification/map counts, mask, bands and deepest values stay null.
  Claims of later work after that HOLD are integrity HOLD, not quality evidence.
- Mapping metadata alone cannot call the band function. Independently admitted
  samples must match attempt/window and mapped producer and supported count.
  The pure function accepts only qualified, already-normalized finite nonnegative
  positive-down metres and a same-length Boolean support mask. It does not apply
  abs, unit conversion, sign changes, datum changes or requalification.
- Labels partition 0–300 ft (<=91.44 m), >300–600 ft (>91.44 through 182.88 m),
  >600 ft (>182.88 m). Exact and adjacent boundaries are assigned once; 300/600
  **metres** both belong to >600 ft. Unsupported samples cannot establish source
  depth or visual quality. Quality is always unavailable; visual_certified false.
- All committed examples and temporary test leaves are **synthetic**, not observed
  or live records. Native-source citations are explicitly AS_RECORDED. Existing
  scientific, visual, legal, human and source/live-apply HOLDs remain unchanged.

## Executed acceptance

Cwd for the following command: the task-local clone root (`repo/`).

Command (using the provisioned clone interpreter):
```
~/agent-work/bin/memcap -- .venv/bin/python -m pytest -q workspace/candidates/AUDINV-FIX-149/tests
```
Exit 0; full output:
```
....................................                                     [100%]
36 passed in 0.04s
```
The explicit candidate command is required: ordinary CI does not collect these
workspace tests. Offline synthetic acceptance is not scientific/visual/legal
acceptance or installation authority. Final whitespace/pre-PR/push evidence is
reported in the PR and task handoff; hosted CI/review/merge belongs to ship-queue.

## Environment

Initial checker exited 2 ENV-MISSING because the fresh clone had no venv.
The expressly authorized worktree-env builder provisioned its own editable package,
reusing existing dependency storage without modifying the shared venv. No hidden
package installation, native download/open or legacy-helper execution occurred.
