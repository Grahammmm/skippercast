# survey-science roll-up gate receipt (AUDINV-CIW-04)

Inventory row CIW-04 asked to fold the roll-up into `survey-tests` or make it skip when its inputs fail.
Neither was done: `survey-science` is a required branch-protection context, and a required job that is
skipped can count as success, which would turn a failed upstream into a pass. Folding it away would need an
external required-check migration. So the fail-closed contract is kept and only the diagnostic changes.

## Change

- `scripts/ci_select.py --gate` (new `gate()`): `evidence()` is unchanged and still decides pass/fail; exit
  is 1 whenever it refuses.
- Upstream `failure`/`cancelled` on `changes`, `check` or `survey-tests`: prints a readable line naming the
  job and exact result, with no `::error::` annotation (the failing job already carries the cause).
- Any other refusal (skipped, missing, pending, malformed booleans, all-false selection): explicit
  `::error::Required evidence incomplete (selector/contract)` on stderr.
- `GITHUB_STEP_SUMMARY`, when set, gets a short appended summary. Values outside `[A-Za-z0-9_.-]{0,32}`
  are replaced by `<invalid>` and are only written inside code spans, never as headings or commands.
- `.github/workflows/ci.yml`: the gate step is renamed "Roll-up gate (fails closed; names the failed
  prerequisite)". Job name/context, `needs` and `if: !cancelled()` are untouched. No required-check change.
- `tests/unit/test_ci_select_gate.py`: parity of exit code with `evidence()` over events x gate x check x
  tests x survey, plus output, summary and wiring assertions.

DCO (`sign-off`) remains a separate required context. The original implementation did not dispatch CI or publish anything.

## Review RETURN: frozen source unavailable in shallow CI

At head `88e58c7567a9d10baaa827c3d9e897a19ec4adbd`, Actions run `43776117415`
failed both core Python legs because two retirement-manifest tests could not resolve
`351e321dd8c7b3ef82b149d2bb9476fbe337e180`. The roll-up correctly reported
`check = failure`; it was not a separate GIS failure.

Merged main at `d75aa3a52fdde19564ca60176966525adbf5202a`, including its existing
frozen-history fixes (`af8d688e` and `4a84e938`). The workflow fetches the exact source
snapshot before offline validation in both core and full-tier jobs and verifies the
manifest's source commit is present. No manifest hashes, ownership assertions,
required contexts, or test selections were changed for this repair.

Local reproduction used Python 3.12.3 and pytest 9.1.1, not the hosted Python matrix:

- A depth-2 checkout of the returned head reproduced the same two failures:
  2 failed, 12 passed, with `fatal: not a tree object`.
- A depth-2 checkout after merging main, with CI mode enabled but before fetching,
  still refused the missing source: 12 passed, 2 errors, no skips.
- After the workflow's exact frozen-source fetch, that shallow checkout passed both
  the retirement-manifest and roll-up gate modules: 25 passed, no skips.
- The local CI helper passed layout contract, repository checks and the changed
  gate tests (`ALL PASS`). No packages were installed and no server was started.

These are local results; required checks at the newly pushed head remain a separate
CI/merge-gate decision, not evidence supplied by the old failed run.
