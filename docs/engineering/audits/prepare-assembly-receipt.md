# AUDINV-FIX-056 — prepare-to-assembly regression receipt

Scope: one hermetic test, `tests/unit/test_coastal_four128_prepare_assembly.py`. No production code, guard,
allowlist, schema or pin changed. Synthetic metadata only; nothing here is live authority, a signed release, a
clock/attempt reset or native/source execution.

## What the test runs

Actual `coastal_four128_prepare.main` with explicit argv, then actual admission `prepare_inputs`,
`evidence_summary`, `render` and `assemble` with real `ManagedOutputs`, on fresh synthetic role documents and
historical templates under `tmp_path`. Strict and explicit partial support are both run, each with a simulated
preflight exit 0 and 2. Reads outside `tmp_path`/repo (and any `.bag/.tif`) fail; `Store` and systemd are not used.

## Replaced seams (only these)

- Preflight transport: `adm.subprocess.run` is a recording fake (output labeled `SIMULATED`); launched at most once.
- Executor-host code-identity gate: `adm.live_code` is replaced exactly as in
  `tests/unit/test_coastal_four128_admission.py` (`lambda cfg: (controls, cfg['head'])`), with `controls` built from
  the real control-file bytes. `adm.git` is not faked. The gate's own refusals stay covered, unchanged, by
  `test_live_code_rejects_dirty_head_and_wrong_root` and `tests/unit/test_coastal_source_guard.py`.

## Spec edge cases 1-8 (AUDINV-FIX-056.md) -> tests

1. Omitted root/cap/prior refuse before stage creation: `test_required_flags_refuse_before_stage`.
2. Historical/aliased root, missing/tampered/expired/non-independent role: `test_metadata_refusals_preserve_stage`.
3. Negative/float/bool prior and over-cap refuse; exact fit (`remaining_after_trial_bytes == 0`): `test_invalid_prior_and_overcap_refuse`, main test.
4. Existing stage/mission/run-tag scratch unchanged; repeat assembly refuses: `test_existing_roots_refuse_without_cleanup`, main test.
5. Nonzero prior propagates unchanged, no refunds: main test.
6. Strict vs partial pinned windows; historical context windows never selected: main test (`partial` param).
7. Nonzero preflight keeps the failure receipt, no relaunch/clock/sqlite: main test (`preflight_rc=2`).
8. Wrong source hash/ledger/controls refuse: `test_metadata_refusals_preserve_stage` (`source`, `ledger`), `test_control_ledger_mismatch_refuses_assembly`.

## Separate defect (NOT fixed here; for the coastal source-guard owner)

`main` tracks `src/skippercast/coastal/resources/private-mapping-input-v2.schema.json` as mode `120000` (symlink;
`git ls-tree` blob `96de6da1de2fcc25629cba1891f00a7bb18bb0ea`) and `guard_project_source` refuses any source
symlink; the entry was introduced by 3ad4a8f5 ("Keep one copy of the 27 duplicated schema files"), so the real `adm.live_code` cannot pass on a clean checkout of `main`. Logged in the
coordinator's NEXT-ITERATION.md (outside this repo, per the admission owner's disposition). This is why the code-identity gate is stubbed here; the guard and the tracked layout were left
untouched pending that owner's reconciliation.
