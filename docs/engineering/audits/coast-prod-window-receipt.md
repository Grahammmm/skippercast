# AUDINV-FIX-111 bounded implementation receipt

Base: `0991fc70d212c9405f7b174950cb3fa4d7c6846d`.
Branch: `rb/audinv-fix-111`; actual material author: Sol / gpt-6.1-sol.
Sole requested downstream reviewer: `opus-coder`; ship-queue owns CI/review/merge.

Checked first: the original-A pin and existing strict final windows match the
spec baseline. No owned-file collision in the open-PR snapshot at build start.
The installed-closure skill already records a later bounded wheel receipt;
older absence statements remain dated snapshots. No assertion was relaxed.

The new API is a pure offline grid compatibility option; validate_adoption
continues to use original A. Final-A live adoption remains HOLD. Synthetic
arrays never populate live/observed records. No source data or external
receipt was opened, hashed or downloaded. No native phase, installed skill,
ordered trial, grant, metadata or canonical ledger changed.

## Semantic and preservation checks

Author re-read the source/test diff and crosswalk against the frozen main above.
Each plan/report key 01–06 occurs once in the crosswalk table; skill 02 is
separate installed closure, and plan 04/06 never overwrite skill 04/06.
Strict and partial four-window sets resolve to the unchanged production pins.
The legacy helper call inside validate_adoption and all existing tests are
byte-unchanged outside the helper's optional selector. Accounting, expiry,
review and source identity checks are not modified. Attempts 1–6 are retained
individually, including attempt-3 UNKNOWN rather than an invented zero;
pre-scans, uncertain charges and two reruns remain separate rows. No new
scientific or live acceptance is claimed. All four changed files are owned;
source/test changes remain below the 300-line target. No pin refresh was needed.

The first signed-off commit was gated/pushed before the slower local checks:
`0377a058bde78278dc691debd0b8d8ea9353e03f`.

```text
PREPUSH-TESTS PASS repo=skippercast head=0377a058bde78278dc691debd0b8d8ea9353e03f base=0991fc70d212c9405f7b174950cb3fa4d7c6846d
```

That gate reported changed tests PASS and survey PR tier PASS. Three core
failures also failed at the merge base (historical local-byte-replay e/f/g in
`tests/unit/test_coastal_four128_admission.py`), so were classified PREEXISTING.
Web tests were not run locally because node_modules is absent; CI owns them.
The final gated push verdict and exact PR head are recorded in the PR handoff,
not recursively committed inside their own head-bound receipt.

Before final validation, separate `git fetch origin` and
`git merge --no-edit --signoff origin/main` succeeded (already up to date).
Remote main and local origin/main both resolved to the frozen base above.

## Executed acceptance (full stdout/stderr)

Every command below ran from the same candidate clone. The provisioned venv
imports this clone's src (worktree-env verified it); no installed-source fallback.
The memcap wrapper keeps every test/check within the existing 8G cap.


### `/home/user/agent-work/bin/memcap -- .venv/bin/python -m pytest -q tests/gis/test_coastal_saved_area_scope_grid.py tests/gis/test_coastal_saved_area_native_grid.py tests/unit/test_coastal_saved_area_horizon.py tests/unit/test_coastal_saved_area_paths.py tests/unit/test_coastal_governed_discovery_deadline.py`

Cwd: `/home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo`

Exit: 0

stdout:
```text
........................................................................ [ 60%]
................................................            [100%]
=============================== warnings summary ===============================
tests/gis/test_coastal_saved_area_scope_grid.py::test_final_pin_uses_a_row_not_whole_block_upper_left
  /home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo/tests/gis/test_coastal_saved_area_scope_grid.py:56: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    assert tuple(full * Affine.translation(*FINAL[:2]))[:6] == saved_area.STRICT_FINAL_A['transform']

tests/gis/test_coastal_saved_area_scope_grid.py::test_final_pin_uses_a_row_not_whole_block_upper_left
  /home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo/tests/gis/test_coastal_saved_area_scope_grid.py:57: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    assert tuple(full * Affine.translation(3762, 3360))[:6] != saved_area.STRICT_FINAL_A['transform']

tests/gis/test_coastal_saved_area_scope_grid.py::test_final_pin_uses_a_row_not_whole_block_upper_left
  /home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo/tests/gis/test_coastal_saved_area_scope_grid.py:60: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    final_facts['header']['transform'] = list(full * Affine.translation(3762, 3360))[:6]

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
120 passed, 3 warnings, 13 subtests passed in 0.38s
```

stderr:
```text
```

### `/home/user/agent-work/bin/memcap -- .venv/bin/python -m unittest tests.contract.test_test_layout tests.contract.test_research_boundary -v`

Cwd: `/home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo`

Exit: 0

stdout:
```text
```

stderr:
```text
test_every_layer_is_a_package (tests.contract.test_test_layout.LayoutTest.test_every_layer_is_a_package) ... ok
test_every_module_is_in_a_layer (tests.contract.test_test_layout.LayoutTest.test_every_module_is_in_a_layer) ... ok
test_gis_imports_only_in_gis_directories (tests.contract.test_test_layout.LayoutTest.test_gis_imports_only_in_gis_directories) ... ok
test_gis_package_list_matches_the_survey_requirements (tests.contract.test_test_layout.LayoutTest.test_gis_package_list_matches_the_survey_requirements) ... ok
test_no_path_hacks_or_file_relative_roots (tests.contract.test_test_layout.LayoutTest.test_no_path_hacks_or_file_relative_roots) ... ok
test_node_test_modules_match_the_standard_suite_glob (tests.contract.test_test_layout.LayoutTest.test_node_test_modules_match_the_standard_suite_glob) ... ok
test_product_tests_never_read_the_real_clock (tests.contract.test_test_layout.LayoutTest.test_product_tests_never_read_the_real_clock) ... ok
test_shared_survey_packages_are_pinned_the_same_in_the_test_extra (tests.contract.test_test_layout.LayoutTest.test_shared_survey_packages_are_pinned_the_same_in_the_test_extra) ... ok
test_app_and_worker_do_not_load_receipts (tests.contract.test_research_boundary.ResearchBoundaryTest.test_app_and_worker_do_not_load_receipts) ... ok
test_new_research_scripts_do_not_land_in_scripts (tests.contract.test_research_boundary.ResearchBoundaryTest.test_new_research_scripts_do_not_land_in_scripts) ... ok
test_product_python_never_imports_research (tests.contract.test_research_boundary.ResearchBoundaryTest.test_product_python_never_imports_research) ... ok
test_product_scripts_never_run_research (tests.contract.test_research_boundary.ResearchBoundaryTest.test_product_scripts_never_run_research) ... ok
test_product_workflows_run_no_research (tests.contract.test_research_boundary.ResearchBoundaryTest.test_product_workflows_run_no_research) ... ok
test_research_scripts_compile (tests.contract.test_research_boundary.ResearchBoundaryTest.test_research_scripts_compile) ... ok
test_research_workflows_publish_nothing (tests.contract.test_research_boundary.ResearchBoundaryTest.test_research_workflows_publish_nothing) ... ok
test_web_and_worker_never_import_research (tests.contract.test_research_boundary.ResearchBoundaryTest.test_web_and_worker_never_import_research) ... ok

----------------------------------------------------------------------
Ran 16 tests in 8.052s

OK
```

### `/home/user/agent-work/bin/memcap -- python3 /home/user/agent-work/bin/sc-ci-local-check.py /home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo`

Cwd: `/home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo`

Exit: 0

stdout:
```text
PASS layout contract
PASS repository checks
PASS changed tests tests/gis/test_coastal_saved_area_scope_grid.py
ALL PASS
```

stderr:
```text
```

### `/home/user/agent-work/bin/memcap -- .venv/bin/python scripts/check_e2e_pins.py`

Cwd: `/home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo`

Exit: 0

stdout:
```text
e2e pin guard: 28 pinned files match
```

stderr:
```text
```

### `/home/user/agent-work/bin/memcap -- .venv/bin/python scripts/check_test_determinism.py --base origin/main`

Cwd: `/home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo`

Exit: 0

stdout:
```text
determinism lint: new=0 existing=18 (clock=18) mode=fail-on-new
  existing (warning) tests/_coastal_operations.py:151 clock: kwargs = {} if offset is None else {"clock": lambda: time.time() + offset}
  existing (warning) tests/_coastal_operations.py:154 clock: now = time.time() + (offset or 0)
  existing (warning) tests/_coastal_operations.py:225 clock: kwargs = {} if self.offset is None else {"clock": lambda: time.time() + self.offset}
  existing (warning) tests/gis/test_util_helpers.py:19 clock: return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds").re
  existing (warning) tests/gis/test_util_helpers.py:23 clock: moment = moment or datetime.now(timezone.utc)
  existing (warning) tests/unit/child_release_fixture.py:37 clock: now, mono = time.time(), time.monotonic()
  existing (warning) tests/unit/child_release_fixture.py:69 clock: return time.time(),time.monotonic()
  existing (warning) research/tests/test_check_terrain_acceptance_dependencies.py:162 clock: terrain_only.verify(tmp_path, {}, now=datetime.now(timezone.utc))
  existing (warning) research/tests/test_noaa_bag_previous.py:22 clock: return (datetime.now(timezone.utc) + delta).isoformat()
  existing (warning) research/tests/test_usgs_doi_previous.py:31 clock: return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()
  existing (warning) research/tests/test_usgs_map_previous.py:33 clock: return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()
  existing (warning) research/tests/gis/test_check_terrain_acceptance_render.py:86 clock: now = datetime.now(timezone.utc)
  existing (warning) research/tests/gis/test_check_terrain_acceptance_render.py:188 clock: now = datetime.now(timezone.utc)
  existing (warning) research/tests/gis/test_check_terrain_acceptance_render.py:213 clock: now = datetime.now(timezone.utc)
  existing (warning) research/tests/gis/test_habitat_shortlist_closures.py:14 clock: stamp = datetime.now(timezone.utc).isoformat()
  existing (warning) research/tests/gis/test_regular_bag_hard.py:27 clock: 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'features': features}
  existing (warning) research/tests/gis/test_regular_bag_hard.py:35 clock: snapshot['retrieved_at'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
  existing (warning) research/tests/gis/test_usgs_context_pipeline.py:19 clock: context.mpa_union({'sources':{'mpas':{'status':'ok','data_retrieved_at':datetime.now(timezone.utc).i
```

stderr:
```text
```

### `/home/user/agent-work/bin/memcap -- .venv/bin/python -m ruff check src/skippercast/coastal/coordinator/saved_area.py`

Cwd: `/home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo`

Exit: 0

stdout:
```text
All checks passed!
```

stderr:
```text
```

### `git diff --check`

Cwd: `/home/user/.hermes/kanban/boards/skippercast/workspaces/t_c8c9714d/repo`

Exit: 0

stdout:
```text
```

stderr:
```text
```
