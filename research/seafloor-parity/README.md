# Seafloor parity harness (MGL-03)

`run_parity.py` runs the reviewed seafloor `run --reach ID` once per reach in a prepared,
disposable **private** checkout and compares six ledger fields with an immutable copy of the
committed ledger. Standard library only, offline, no retries. Output is private,
review-required evidence: it is not legal clearance, not publication and not live proof.

## Invocation (MGL-06..09 use their own row ID and same-named private root)

```text
<python> -B <private-tools>/research/seafloor-parity/run_parity.py --row-id MGL-06 \
  --source-checkout <reviewed-source-checkout> \
  --checkout ~/agent-work/reports/seafloor-agg/private-runs/MGL-06/repo \
  --baseline-dir ~/agent-work/reports/seafloor-agg/private-runs/MGL-06/baseline \
  --reaches-file ~/agent-work/reports/seafloor-agg/private-runs/MGL-06/reaches.json \
  --output ~/agent-work/reports/seafloor-agg/private-runs/MGL-06/parity.jsonl \
  --python <python-with-seafloor-dependencies>
```

The launcher is fixed: `~/agent-work/bin/seafloor-cli.py`. Each reach runs exactly
`[python, -B, launcher, --checkout, CHECKOUT, run, --reach, ID]` (cwd = checkout, 1800 s
timeout). No fetch, force, physical-only, publish or forwarded option exists.
`reaches.json` is a nonempty JSON array of unique reach IDs in output order.

## Preparation (done by the downstream worker BEFORE any seafloor command)

Create the disposable checkout under `private-runs/<row-id>/`, then save the committed bytes
(via `git show <commit>:<path>` in the source checkout, not a derived worktree file) as
`baseline/seafloor-ledger.json` (`dist/data/seafloor-ledger.json`) and `baseline/reaches.json`
(`catalog/reaches.json`), and write `baseline/manifest.json` with exactly `source_commit`
(full hash), `ledger_sha256`, `reaches_sha256`. Do this from a script file, for example:

```python
import hashlib, json, subprocess
src, root, commit = "<source-checkout>", "<row-root>", "<full-commit>"
manifest = {"source_commit": commit}
for rel, name, key in (("dist/data/seafloor-ledger.json", "seafloor-ledger.json", "ledger_sha256"),
                       ("catalog/reaches.json", "reaches.json", "reaches_sha256")):
    data = subprocess.run(["git", "-C", src, "show", f"{commit}:{rel}"], check=True, capture_output=True).stdout
    open(f"{root}/baseline/{name}", "xb").write(data)
    manifest[key] = hashlib.sha256(data).hexdigest()
open(f"{root}/baseline/manifest.json", "x").write(json.dumps(manifest))
```

A non-Git archive checkout needs `<row-root>/checkout-commit.txt` holding its full commit
(recorded as `commit_verification: "declared"`; Git checkouts are `"git"`). Raw originals, caches,
the reference and the hash-bound screen snapshot must already be in the checkout; a missing input
is a named failure, never a download.

## Protections

All paths must resolve inside `private-runs/<row-id>/` (no symlink escapes; no symlinked
`dist`, `catalog`, `var` paths). The row root itself must be a real directory directly under the
fixed `private-runs` parent; a symlinked row root is refused, never adopted as the confinement root.
If both `var/seafloor/reaches/<id>/run.json` and `private-reaches/<id>/run.json` exist, the run is an
`error` (`receipt-ambiguous`): a hash-verified reuse does not rewrite its receipt, so modification
time cannot say which one the run used. Remove the stale receipt from the disposable checkout.
Source checkout is outside the row root and distinct from the
checkout; output must not exist and cannot alias an input. Baseline hashes and the source
checkout's HEAD + `git status --porcelain` are re-checked after every child (also on failure or
timeout); a change stops further children, sets `integrity` false and exits 2. Nothing is
restored, deleted or overwritten. Logs go to `<row-root>/logs/` (created exclusively).

## Rows (JSON Lines, schema_version 1, one per requested reach in order)

Keys: `schema_version`, `row_id`, `reach_id`, `status`, `baseline` (`source_commit`,
`ledger_sha256`, `reaches_sha256`, `values`), `actual` (null or `checkout_commit`,
`commit_verification`, `ledger_sha256`, `receipt_sha256`, `values`, `processing_status`,
`screen_status`, `screen_reasons`, `publication_prohibited`), `command`, `returncode`,
`unchanged`, `differences`, `findings`, `logs` (row-root-relative `stdout`/`stderr`), `integrity`
(`baseline_unchanged`, `source_checkout_unchanged`).

`values` has exactly `tier1_km2`, `selected_valid_km2`, `tier2_km2`, `polygons_by_grade`,
`habitat_count`, `held_by_reason`. Comparison is exact (no rounding or tolerance; `2` equals
`2.0`; absent vs zero map key is a difference). Each difference is
`{path, baseline_present, actual_present, baseline, actual}` with leaf paths such as
`held_by_reason.overlap-cdfw-mpa` or `polygons_by_grade.B`.

| status | meaning |
| --- | --- |
| `exact` | run verified (receipt output hashes; stdout, receipt and derived ledger row agree), screen ready, all six fields equal |
| `different` | run verified, screen ready, at least one field differs |
| `held` | verified run but screen not ready, or private / publication-prohibited receipt (even if values match) |
| `error` | non-zero exit, timeout, malformed or disagreeing evidence, incomplete processing, integrity change |
| `not_run` | not attempted after an earlier stop |

A failed child can never match: its stale ledger row/receipt is ignored. A hash-verified
`unchanged: true` reuse by the pipeline is allowed and recorded.

## Exit codes

`0` all rows `exact` and final integrity checks pass. `1` valid differences or holds only.
`2` invalid preparation (one stderr diagnostic, no child, no output), or any `error`/`not_run`
row, or an integrity failure (takes precedence over 1). stdout prints only the output path and a
status summary.

Tests: `research/tests/test_seafloor_parity.py` (synthetic fixtures, injected runner).
