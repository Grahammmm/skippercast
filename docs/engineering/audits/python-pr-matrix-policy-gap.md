# CIW-56 policy-gap report: Python PR matrix and advisory audit

Unit AUDINV-CIW-56 (inventory row CIW-56). Report only: no workflow, pin, branch-protection, test or schedule change.
Checked against skippercast `origin/main` = `3f699e39554f88304000b004549289c231739446` (2026-11-15). The spec author's head was `0991fc70d`; the line numbers below were re-checked on `3f699e395`.

## Disposition

| Part of the audit recommendation | Disposition |
| --- | --- |
| Move the advisory `pnpm audit` off pull requests | **NO GAP.** Already done on main. |
| Run only Python 3.13 on pull requests | **RETAIN CURRENT POLICY (3.11 + 3.13).** A later, specific G ruling chose the opposite. |

Nothing remains to build for CIW-56. The inventory row still reads NOT-STARTED; its own NOTE already says the audit was moved and only the duplicate matrix persists.

## Part 1: advisory audit (NO GAP)

Observed, `.github/workflows/ci.yml:458-461` on `3f699e395`:

```
- name: Production dependencies have no high or critical advisories
  # Not on PRs: new advisories fail it for reasons unrelated to the change.
  if: matrix.python == '3.13' && github.event_name != 'pull_request'
  run: pnpm audit --prod --audit-level high
```

The step runs on one Python (3.13) and not on `pull_request`. It runs on main pushes, the merge queue, the nightly schedule and dispatch (the workflow's `on:` block covers `push: main`, `merge_group`, `schedule`, `workflow_dispatch`). Audit absence from PRs therefore does not leave CIW-56 pending (edge case 1). The recommendation in `reports/ci-audit/CI-CHANGES.md:131-137` is already applied verbatim.

## Part 2: Python matrix (RETAIN CURRENT POLICY)

Observed workflow state, `ci.yml:296-302` (matrix at `:299-302`):

```
fail-fast: false
matrix:
  # Pull requests test the same Pythons as main, so a version-specific break
  # cannot first appear after merge (G decision 2026-10-31 18:20).
  python: ["3.11", "3.13"]
```

The header comment at `ci.yml:16-18` states PRs run core areas "on 3.11 and 3.13 (main's Pythons)".

Rulings, `decisions/G-DECISIONS.log` (read-only source, quoted):

| Line | Date | Ruling | Effect on this row |
| --- | --- | --- | --- |
| 1350 | 2026-10-31 17:10 | CIS-SC-3 approved moving the PR tier from **3.12** to 3.13; "main keeps 3.11 + 3.13". | Approval concerned dropping 3.12 only. It does **not** authorize dropping 3.11 (edge case 2). |
| 1353 | 2026-10-31 18:20 | Add 3.11 to the PR tier so PRs test what main tests. G "considered dropping 3.11 from main and chose to widen the PR tier instead." End state: PR tier = main set = 3.11 + 3.13 (card PY311-PR). | Specific, later and directly on point. It wins over the older audit wording in `CI-CHANGES.md:119-130` and over the broad 2026-11-15 "approve ALL 295 NOT-STARTED audit rows" decision (log:1931), which does not name or revoke it (edge case 3). |

Other observed facts:

- `pyproject.toml:10`: `requires-python = ">=3.11"`. Dropping the PR 3.11 leg would leave a declared range whose lowest version is first exercised after merge.
- Required status contexts (`gh api .../branches/main/protection/required_status_checks`, recorded by the spec author, not re-run here): `survey-science`, `check (3.13)`, `sign-off`. Only `check (3.13)` is required for the `check` job. This shows the 3.11 leg is advisory in branch protection; it does not show 3.11 is unsupported (edge case 4). The `check` job comment at `ci.yml:297` says every leg reports, so a failing 3.11 leg is visible even though not required.
- Source-only coverage of the Node duplication: `CI-CHANGES.md:119-130` justifies 3.13-only partly because "the Node steps need one leg". In `ci.yml` the Node-bearing steps already carry `if: matrix.python == '3.13'` where single-run is intended (`:372`, `:405`, audit `:460`). Whether every remaining Node step runs twice was read from source only; no run logs or timings were examined. Any wall-time saving is UNKNOWN.

### Expected loss if the original recommendation were applied

PRs would no longer run unit, contract, integration and claims tests on 3.11 before merge. A 3.11-only break would first appear on the main push or nightly run. This is the exact failure G described in log:1353 (main red 14:40-18:22, capping merges). That is an inference from the ruling text, not a new measurement.

### UNKNOWN (not zero, not measured)

| Item | Status | Custodian |
| --- | --- | --- |
| Wall-time or runner-minute saving from a 3.13-only PR tier | UNKNOWN; no timings collected and none invented | Existing CI policy/admission owner |
| Third-party installers of the package on 3.11 | UNKNOWN; no repository evidence either way (same gap recorded in `reports/OLD-33-python-support.md`) | Existing policy/admission owner |
| Whether a later G decision supersedes log:1353 | None found in the cited rows; not searched beyond them | G decision log custodian |

## Related PR

PR #2286 `[AUDINV-OLD-33] Record supported Python consumers; keep 3.11 + 3.13 matrix`, head `36ac39f624f97d0df8993fd535923919aa83f398`. The spec recorded it OPEN; at this build `gh pr view 2286` returned state MERGED (adds only `reports/OLD-33-python-support.md`, 49 lines). It is cited as overlapping research that reaches the same conclusion. It is not a dependency, is not a G decision, and was not edited or duplicated here.

## Verification record

- `grep -n 'python: \[' .github/workflows/ci.yml` -> `302:        python: ["3.11", "3.13"]`
- `grep -n 'pnpm audit' -B3 .github/workflows/ci.yml` -> lines 458-461 above
- `grep -n requires-python pyproject.toml` -> `10:requires-python = ">=3.11"`
- `gh pr view 2286 --repo Grahammmm/skippercast --json state,headRefOid,files` -> state MERGED, head `36ac39f6...`
- Branch-protection contexts and the G-DECISIONS.log lines were taken from the spec's recorded excerpts (read-only); they were not re-fetched.
