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

DCO (`sign-off`) remains a separate required context. Nothing was run in CI, dispatched or published.
