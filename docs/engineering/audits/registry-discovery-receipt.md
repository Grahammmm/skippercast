# Registry and shared-fixture discovery receipt

## Disposition: NO GAP (AUDINV-CIW-76)

Checked source: `Grahammmm/skippercast` main `0991fc70d212c9405f7b174950cb3fa4d7c6846d`. This is the same
source identity named by the admitted spec, verified in the fresh clone rather
than assumed. No historical combined-change failure was reproduced. The current
helpers represent the union without any registration change, so the conditional
source-repair envelope is not exercised. This PR adds this receipt alone.

Observed scope is the checked repository and the synthetic controls below; it
does not establish that every external runner or registry is discovery-friendly.
The prior work-shaping diagnosis is not itself a reproduced defect in this main.
Machine-valid output remains review-required, not semantic or live acceptance.

## Inspected source and deciding controls

| Source | SHA256 |
| --- | --- |
| `tests/contract/test_test_layout.py` | `45c9a94f3ef8eebb7328da2dff71e937c135af773cb7a3902e5727722c22cdbb` |
| `tests/_support.py` | `fb8b199bbe99ea83feee7c3e3ec8f3e73bdc6363556074fba6206911bea67cb3` |
| `tests/contract/test_research_boundary.py` | `1d9ccdf1bfaf49e217f56bc471de059ae3ed220e851e61a1a2d3b5b2a0f611e2` |
| `package.json` | `83cef009e623dee19207f8ebc741b0604766989616387917901c5c654561edb3` |
| `pyproject.toml` | `0052c34fb1ec293024e8d366bc17b95b58951368b23840066a2a3b272563daa4` |

- `tests/contract/test_test_layout.py:14-19,30-69`: recursive Python glob,
  deterministic sorting, stable safety layers, package requirements, top-level
  Node glob, GIS import, root/path and fixed-clock checks.
- `tests/_support.py:13-41,45-93`: shared ROOT/FIXTURES, fixed NOW/FakeClock,
  directory-derived GIS/claims collection. Nothing here was changed.
- `tests/contract/test_research_boundary.py:15-99`: product exceptions are safety
  classifications, not test-registration lists; product/research, receipts and
  publication boundaries remain unchanged.
- `pyproject.toml:78-83`: testpaths and test_*.py discovery;
  `package.json:11`: tests/test_*.mjs;
  `.github/workflows/ci.yml:311-313,386-396`: the ordinary Python and Node suites.
  The affected contract modules were also run through pytest below, not only unittest.
- An open-PR path check before work found no collision in either conditional
  test/support file or this receipt. `docs/engineering/testing.md` was not edited.

## Synthetic controls (not observed/live data)

The task-local evidence probe imports the unchanged contract modules from this
clone and substitutes only their ROOT with temporary fixture trees. Each tree
uses the existing package/layer conventions and an unchanged copy of shared
support. No contract implementation, assertion, safety set or registry is patched.
Reversed filesystem enumeration is a separate synthetic order control. Nothing
is added to the repository's runner inventory or ordinary test collection.

| Acceptance case | Observed deciding result |
| --- | --- |
| 1. Combined Python discovery, either order | alpha/beta and beta/alpha additions produce exactly both sorted paths; reversed rglob enumeration produces the same paths; actual unittest discovery runs both. |
| 2. Shared area fixture, not a test | Both Python modules read tests/fixtures/registry/sample.json via shared FIXTURES and use fixed NOW/FakeClock; both Node modules reuse that same JSON via a fixture-only helper; runner counts remain two per language. Removing the JSON makes both Python consumers fail with FileNotFoundError, not skip. |
| 3. Invalid root/nested Python layout | Independently inserted root-level and unsupported nested test modules each fail the existing layer assertion, after a passing same-tree control. |
| 4. Missing package | Removing tests/unit/__init__.py fails the existing package assertion, after its passing control. |
| 5. Node discovery and nested refusal | Both top-level modules execute successfully under the ordinary glob's paths; nested node:test fails the unchanged layout assertion. |
| 6. Fixture-only helper | helpers.mjs has no node:test import; all eight layout contracts pass and Node collects only the two test_*.mjs modules. |
| 7. Boundaries independently reject | GIS import, sys.path mutation, file-relative ROOT and real-clock injections fail their own unchanged assertions. Product Python/script/web/worker/package/workflow imports or runs of research, a research publication command, and a shipped receipt reference each independently fail the existing corresponding boundary assertion. |

Cancelled/expired request handling is not a behavior of these filesystem-only
contracts. Duplicate/stale registration is avoided by having no registration
rows; actual discovered path sets and runner counts are asserted, not inferred
from source resemblance. No broader request-lifecycle claim is made.

Probe retained only in the admitted task workspace for reproducibility:
`$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/discovery_probe.py`; SHA256 `3f2077645b248d40beaaff30442843c6d823a8f8bcaf664fadaa02874f47f3d5`.
Its command/cwd/exit/stdout/stderr records and contract-control verdicts
are included below with the host home prefix replaced by `$HOME`. The exact
unredacted local receipt is retained in the task workspace at
`docs/engineering/audits/registry-discovery-receipt.md`, outside the clone. The probe is evidence, not a new per-PR repository runner.

## Environment and preserved initial result

Initial command: `$HOME/agent-work/bin/memcap -- python3 $HOME/agent-work/bin/sc-ci-local-check.py $HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo`

Cwd: `$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo`; exit **2**. Stdout (home-prefix sanitized; otherwise exact):
```text
ENV-MISSING $HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo: no $HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo/.venv/bin/python; build it (this checker never builds envs): python3 $HOME/agent-work/bin/worktree-env.py build $HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo
```
Stderr was empty. The explicitly authorized worktree-env build then provisioned
this clone's own editable package using Python 3.12 and existing shared dependency
packages, without modifying the shared venv. The local checker subsequently
returned ALL PASS. No hidden dependency install or installed-source fallback was
used to impersonate the clone's product code. This is bounded local evidence,
not a claim that Python 3.11/3.13 hosted CI ran here. package.json has no `check`
script; no nonexistent npm check was claimed.

## Executed acceptance evidence (home-prefix sanitized copy)

Command: `$HOME/agent-work/bin/memcap -- python3 -m unittest tests.contract.test_test_layout tests.contract.test_research_boundary -v`

Cwd: `$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo`; exit: **0**.

Stdout (home-prefix sanitized; otherwise exact):
```text
```

Stderr (home-prefix sanitized; otherwise exact):
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
Ran 16 tests in 8.114s

OK
```

Command: `$HOME/agent-work/bin/memcap -- .venv/bin/python -m pytest -q tests/contract/test_test_layout.py tests/contract/test_research_boundary.py`

Cwd: `$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo`; exit: **0**.

Stdout (home-prefix sanitized; otherwise exact):
```text
................                                              [100%]
16 passed, 11 subtests passed in 8.14s
```

Stderr (home-prefix sanitized; otherwise exact):
```text
```

Command: `$HOME/agent-work/bin/memcap -- python3 $HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/discovery_probe.py`

Cwd: `$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo`; exit: **0**.

Stdout (home-prefix sanitized; otherwise exact):
```text
test_combined_modules_shared_fixture_and_order (__main__.CombinedDiscoveryEvidence.test_combined_modules_shared_fixture_and_order) ... {"command": ["$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo/.venv/bin/python", "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"], "cwd": "$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/tmpq6mt2dg5", "exit": 0, "stderr": "test_shared (tests.unit.test_alpha.SharedFixtureTest.test_shared) ... ok\ntest_shared (tests.unit.test_beta.SharedFixtureTest.test_shared) ... ok\n\n----------------------------------------------------------------------\nRan 2 tests in 0.000s\n\nOK\n", "stdout": ""}
{"command": ["$HOME/.hermes/node/bin/node", "--test", "--test-concurrency=2", "tests/test_alpha.mjs", "tests/test_beta.mjs"], "cwd": "$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/tmpq6mt2dg5", "exit": 0, "stderr": "", "stdout": "TAP version 13\n# Subtest: alpha shared fixture\nok 1 - alpha shared fixture\n  ---\n  duration_ms: 0.436392\n  type: 'test'\n  ...\n# Subtest: beta shared fixture\nok 2 - beta shared fixture\n  ---\n  duration_ms: 0.424055\n  type: 'test'\n  ...\n1..2\n# tests 2\n# suites 0\n# pass 2\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n# duration_ms 42.281226\n"}
PASS synthetic combined discovery: addition order ('alpha', 'beta'); reversed enumeration; shared fixture; no registry edit
{"command": ["$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo/.venv/bin/python", "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"], "cwd": "$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/tmpp97r7xwl", "exit": 0, "stderr": "test_shared (tests.unit.test_alpha.SharedFixtureTest.test_shared) ... ok\ntest_shared (tests.unit.test_beta.SharedFixtureTest.test_shared) ... ok\n\n----------------------------------------------------------------------\nRan 2 tests in 0.000s\n\nOK\n", "stdout": ""}
{"command": ["$HOME/.hermes/node/bin/node", "--test", "--test-concurrency=2", "tests/test_alpha.mjs", "tests/test_beta.mjs"], "cwd": "$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/tmpp97r7xwl", "exit": 0, "stderr": "", "stdout": "TAP version 13\n# Subtest: alpha shared fixture\nok 1 - alpha shared fixture\n  ---\n  duration_ms: 0.453714\n  type: 'test'\n  ...\n# Subtest: beta shared fixture\nok 2 - beta shared fixture\n  ---\n  duration_ms: 0.414877\n  type: 'test'\n  ...\n1..2\n# tests 2\n# suites 0\n# pass 2\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n# duration_ms 40.736945\n"}
PASS synthetic combined discovery: addition order ('beta', 'alpha'); reversed enumeration; shared fixture; no registry edit
ok
test_layout_rejections_independently (__main__.CombinedDiscoveryEvidence.test_layout_rejections_independently) ... PASS synthetic rejection root-python: test_every_module_is_in_a_layer; tests/test_bad.py
PASS synthetic rejection nested-python: test_every_module_is_in_a_layer; tests/unit/unsupported/test_bad.py
PASS synthetic rejection missing-package: test_every_layer_is_a_package; tests/unit/__init__.py
PASS synthetic rejection nested-node: test_node_test_modules_match_the_standard_suite_glob; tests/unit/test_bad.mjs
PASS synthetic rejection gis-import: test_gis_imports_only_in_gis_directories; tests/unit/test_bad.py
PASS synthetic rejection path-mutation: test_no_path_hacks_or_file_relative_roots; tests/unit/test_bad.py
PASS synthetic rejection file-relative-root: test_no_path_hacks_or_file_relative_roots; tests/unit/test_bad.py
PASS synthetic rejection real-clock: test_product_tests_never_read_the_real_clock; tests/unit/test_bad.py
ok
test_missing_shared_fixture_fails_both_modules (__main__.CombinedDiscoveryEvidence.test_missing_shared_fixture_fails_both_modules) ... {"command": ["$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo/.venv/bin/python", "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"], "cwd": "$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/tmpgtc64k6a", "exit": 1, "stderr": "test_shared (tests.unit.test_alpha.SharedFixtureTest.test_shared) ... ERROR\ntest_shared (tests.unit.test_beta.SharedFixtureTest.test_shared) ... ERROR\n\n======================================================================\nERROR: test_shared (tests.unit.test_alpha.SharedFixtureTest.test_shared)\n----------------------------------------------------------------------\nTraceback (most recent call last):\n  File \"$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/tmpgtc64k6a/tests/unit/test_alpha.py\", line 6, in test_shared\n    sample = json.loads((FIXTURES / 'registry/sample.json').read_text())\n                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.12/pathlib.py\", line 1029, in read_text\n    with self.open(mode='r', encoding=encoding, errors=errors) as f:\n         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.12/pathlib.py\", line 1015, in open\n    return io.open(self, mode, buffering, encoding, errors, newline)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nFileNotFoundError: [Errno 2] No such file or directory: '$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/tmpgtc64k6a/tests/fixtures/registry/sample.json'\n\n======================================================================\nERROR: test_shared (tests.unit.test_beta.SharedFixtureTest.test_shared)\n----------------------------------------------------------------------\nTraceback (most recent call last):\n  File \"$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/tmpgtc64k6a/tests/unit/test_beta.py\", line 6, in test_shared\n    sample = json.loads((FIXTURES / 'registry/sample.json').read_text())\n                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.12/pathlib.py\", line 1029, in read_text\n    with self.open(mode='r', encoding=encoding, errors=errors) as f:\n         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n  File \"/usr/lib/python3.12/pathlib.py\", line 1015, in open\n    return io.open(self, mode, buffering, encoding, errors, newline)\n           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\nFileNotFoundError: [Errno 2] No such file or directory: '$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/tmpgtc64k6a/tests/fixtures/registry/sample.json'\n\n----------------------------------------------------------------------\nRan 2 tests in 0.001s\n\nFAILED (errors=2)\n", "stdout": ""}
PASS synthetic missing-fixture control: both Python consumers fail, not silently skipped
ok
test_research_boundaries_independently (__main__.CombinedDiscoveryEvidence.test_research_boundaries_independently) ... PASS synthetic rejection product-python: test_product_python_never_imports_research; src/example.py
PASS synthetic rejection product-script: test_product_scripts_never_run_research; scripts/example.sh
PASS synthetic rejection research-script-location: test_new_research_scripts_do_not_land_in_scripts; scripts/audit_example.py
PASS synthetic rejection web-import: test_web_and_worker_never_import_research; web/example.ts
PASS synthetic rejection worker-import: test_web_and_worker_never_import_research; server/example.ts
PASS synthetic rejection package-import: test_web_and_worker_never_import_research; packages/example.ts
PASS synthetic rejection product-workflow: test_product_workflows_run_no_research; .github/workflows/product.yml
PASS synthetic rejection research-publication: test_research_workflows_publish_nothing; .github/workflows/research-alpha.yml
PASS synthetic rejection product-receipt: test_app_and_worker_do_not_load_receipts; dist/example.js
ok

----------------------------------------------------------------------
Ran 4 tests in 0.274s

OK
PROBE-SHA256 3f2077645b248d40beaaff30442843c6d823a8f8bcaf664fadaa02874f47f3d5
```

Stderr (home-prefix sanitized; otherwise exact):
```text
```

Command: `$HOME/agent-work/bin/memcap -- python3 $HOME/agent-work/bin/sc-ci-local-check.py $HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo`

Cwd: `$HOME/.hermes/kanban/boards/skippercast/workspaces/t_1105a5e1/repo`; exit: **0**.

Stdout (home-prefix sanitized; otherwise exact):
```text
PASS layout contract
PASS repository checks
ALL PASS
```

Stderr (home-prefix sanitized; otherwise exact):
```text
```

## Scope and semantic handoff

Only this owned receipt is changed. Source/test changed lines: zero; no unrelated
hash/pin updates. No new test registry, per-PR runner, source helper repair, broad
test migration, GIS/privacy/research relaxation, publication change, source/live
run or canonical-store mutation. The existing boundaries are retained byte for
byte. Full CI, independent review and any later merge belong to the existing
pipeline; this receipt does not claim those stages completed. The exact signed-off
receipt commit and authorized push verdict are supplied in the PR/card handoff.

Manual semantic check: each of the seven spec cases has one unique row above;
all inspected source identities resolve in the clone; every negative control
first passed on the same fixture root and then failed on its injected violation.
The bounded absence conclusion is NO GAP in these deciding controls, not proof
that historical failures or external registries never existed.

## Preserved documentation hygiene finding

After the initial receipt was written, the same local checker exited 1:
```text
PASS layout contract
FAIL repository checks
docs/engineering/audits/registry-discovery-receipt.md: possible private home path

SOME FAILED
```
The repository copy now uses `$HOME` rather than private absolute home prefixes.
No privacy rule or checker was changed. The raw local evidence remains separate;
the final rerun result is in the PR handoff.
