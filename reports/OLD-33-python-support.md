# OLD-33: supported Python consumers and the 3.11 matrix leg

Inventory row OLD-33 (source: audit finding "Main always runs a Python 3.11 matrix leg although moving it to nightly was suggested conditionally"). Queue id AUDINV-OLD-33.

Checked against skippercast `origin/main` = `96061961f` (2026-11-15). The spec author's earlier head was `2f543f81c`; every line number below was re-checked on `96061961f`.

## Decision

**No reduction. Keep the 3.11 + 3.13 matrix on pull requests, main pushes, the merge queue and the nightly run.** G ruled on 2026-10-31 18:20 (`decisions/G-DECISIONS.log` line 1353, card PY311-PR, commit `005b8121e`): G considered dropping 3.11 from main and chose to widen the PR tier instead. The audit row is stale on "conditionally moving to nightly". This record changes no workflow.

## Supported-Python consumers

| Consumer | Evidence | What it requires |
| --- | --- | --- |
| Declared package range | `pyproject.toml:10` `requires-python = ">=3.11"` | 3.11 or newer |
| CI `check` job matrix | `.github/workflows/ci.yml:291` `python: ["3.11", "3.13"]`, `fail-fast: false` at `:287`, comment `:289-290` citing the G decision | Both legs run on PRs (since #1163 / `005b8121e`), main pushes, merge queue and nightly (`ci.yml:12` `cron "0 9 * * *"`; the same workflow, so the 3.11 leg already runs nightly) |
| Fleet AIS listener host | `docs/operations/runners.md:158` virtualenv built on the box's `python3`, "3.11 or newer"; Ubuntu 24.04 ships 3.12 | 3.11 or newer |
| Contributor docs | `CONTRIBUTING.md:17` "Core runtime code uses Python 3.11+" | 3.11+ |
| Test docs | `docs/engineering/testing.md:21` and `:53` say the `check` job runs on 3.11 and 3.13 | Describes the matrix; would need the same edit as any change |
| Other workflows | `grep -rn python-version .github/workflows`: all pin 3.12 (`research-fish-survey.yml`, `research-substrate.yml`) or 3.13 (all others); `ci.yml:94` pins 3.13; `ci.yml:299` is the matrix | Do not test 3.11 |
| Third-party installers of the package | UNKNOWN: no evidence in the repository either way | Not verified |

Dropping 3.11 from CI without changing `pyproject.toml:10`, `runners.md:158` and `CONTRIBUTING.md:17` would leave a declared range that nothing tests.

## Evidence commands (re-run on `96061961f`)

```console
$ grep -n -E "requires-python" pyproject.toml
10:requires-python = ">=3.11"

$ grep -n -E "python: \[|Pull requests test the same|G decision 2026-10-31" .github/workflows/ci.yml
289:        # Pull requests test the same Pythons as main, so a version-specific break
290:        # cannot first appear after merge (G decision 2026-10-31 18:20).
291:        python: ["3.11", "3.13"]

$ git log --oneline -3 --format='%h %ad %s' --date=short -S'python: ["3.11", "3.13"]' -- .github/workflows/ci.yml
005b8121e 2026-10-31 [PY311-PR] Run the check job on 3.11 and 3.13 in pull requests
7ec2d464a 2026-10-28 ci: fast PR tier (R12)
076eeb67b 2026-10-28 ci: skip duplicate PR work in Offline checks; add required-checks.json

$ grep -rln '"3.11"' tests scripts --include=*.py
(no output, exit 1)
```

No test pins the matrix, so a later change would not trip a pin; the contract lives in `ci.yml` and `docs/engineering/testing.md`.

## What would reopen this

Only a new dated G decision that overrides the 2026-10-31 18:20 ruling. A builder, reviewer or audit row cannot reduce the matrix. Any such change would be its own spec and would also have to update `pyproject.toml:10` (if the range changes), `runners.md:158`, `CONTRIBUTING.md:17` and `docs/engineering/testing.md:21,53`, and would need an answer on third-party installers (UNKNOWN above).
