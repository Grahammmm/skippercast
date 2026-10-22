# COAST MVP PR updates, 2026-10-22

Each open COAST MVP PR was brought up to date with `main` (8a1c2c7) by merging
`origin/main` into a new branch cut from the PR head. Nothing was rebased,
force-pushed or merged, and the original PR branches were not touched. Every
commit has `Signed-off-by`.

Environment limit: this container has no `rasterio`, so the GIS tests
(`research/tests/gis/*`, and the contour tests, which import `rasterio`) could
not run. Installing it would be a download beyond the lockfile installs. Run
`SKIPPERCAST_REQUIRE_GIS=1 python -m pytest` in CI or on AgentOrange before
merging. #845 was skipped as instructed.

## #831 coast mosaic and C1 acceptance

- Branch: `claude/update-pr831` (from 2ea3caa), head `f9f2755b9312b5fff852b2a5da0b384405097b14`
- Conflicts: none.
- `python scripts/check_repository.py`: passed.
- `pytest research/tests/gis/test_coast_mvp_mosaic.py`: not run (no `rasterio`).
- Leftover: GIS test still needs a run with the survey stack.

## #835 coast contours

- Branch: `claude/update-pr835` (from 8deb415), head `86b87b6cc661fc31f984297a648c1622643c66a3`
- Conflicts: none.
- `python scripts/check_repository.py`: passed.
- `pytest research/tests/test_coast_mvp_contours.py`: 12 errors, all `ModuleNotFoundError: rasterio` (not run).
- Leftover: needs a run with the survey stack.

## #836 regional coast QA packets

- Branch: `claude/update-pr836` (from 4f8f628), head `99b91215c434680a141a089160bd7a8d25b7b45a`
- Conflicts: none.
- `python scripts/check_repository.py`: passed.
- `pytest research/tests/test_coast_mvp_qa.py`: 9 passed.
- `pytest research/tests/gis/test_coast_mvp_qa_c1.py`: not run (no `rasterio`).
- Leftover: GIS test needs a run. Merge this before #843.

## #828 coast rights detection

- Branch: `claude/update-pr828` (from 3997319), head `5eb85140e718be3a8b907140026edeee637514f4`
- Conflicts: none.
- `python scripts/check_repository.py`: passed.
- `pytest research/tests/test_coast_mvp_rights.py`: 34 passed.
- Leftover: none.

## #838 terrain-RGB and contour MVT preview (fixture only)

- Branch: `claude/update-pr838` (from f218861), head `c745581d43b96ca3bedd9211903db79875e44670`
- Conflicts: `CHANGELOG.md` only. Kept both sides: main's three new entries, then this PR's entry.
- `pnpm typecheck`: passed. (`pnpm check` is an alias for typecheck.)
- `pnpm build`: passed. `node scripts/check_client.mjs`: passed. Build left no tracked changes.
- `python scripts/check_repository.py`: passed.
- `node --test tests/test_coast_mvp.mjs`: 3 passed.
- `pnpm exec playwright test e2e/p04-catch-contrast.spec.ts -g BODY09`: still fails (phone and laptop).
- Mask-aware handling is out of scope, as instructed.

### Why e2e failed (CI run 39727190576)

- Only 2 tests failed (the BODY09 Reports counts test on phone and laptop); 242 passed, 22 skipped.
- Cause: the PR adds one script to `package.json`. That file's hash is pinned in
  `e2e/p04-catch-contrast.spec.ts` (`REVIEWED_SOURCE_INPUTS`), and the test fails with
  "reviewed source bindings; changed final source requires applicability review".
  Expected `package.json` hash `4675341e…`, received `714c1869…`.
- Not fixed. Updating the pinned hash is a review sign-off ("applicability review"), not a
  mechanical fix, and the PR does not touch the code that test covers. Someone who owns
  that gate should confirm the new script is irrelevant to Reports counts, then update the hash.
- Alternative: move the new npm script out of `package.json`, so the pinned file stays unchanged.

## #843 bounded native-grid QA on cached C1 data

- Branch: `claude/update-pr843` (from 9ce2c10), head `302953ed11019806966edce92bd3b8a59adaa87b`
- Conflicts: none. (The branch already carries #836's commits; merge #836 first.)
- Requested changes, in a separate commit:
  - `RESERVE_BYTES` (in `coast_qa_regional.py`, not `coast_qa.py`) keeps its 250 GiB default.
    It can now be set with env `COAST_QA_RESERVE_BYTES` or the new `--reserve-bytes` flag.
  - `coast_qa.py` exits non-zero when any segment has `consistency.passed` false. Output is still printed first.
  - New offline test `test_cli_exits_nonzero_when_consistency_fails`; `QA_REGIONAL.md` updated.
- `python scripts/check_repository.py`: passed.
- `pytest research/tests/test_coast_mvp_qa.py`: 10 passed.
- `pytest research/tests/gis/test_coast_mvp_qa_regional.py`: not run (no `rasterio`).
- Leftovers:
  - The merge commit `d84922d` on this branch has no `Signed-off-by` (the change commit does). Fixing it needs a force-push, which was not allowed.
  - Not added to CHANGELOG (research tooling, not user-facing).
  - The env override is read at import time, as `RESERVE_BYTES` was a module constant.
