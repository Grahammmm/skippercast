# AUDINV-FAB-15 — inert single-hotspot candidate receipt

## Scope / checked first

Checked main: `0991fc70d212c9405f7b174950cb3fa4d7c6846d`.
The current tree has `scripts/changelog_section.py` and its three test modules,
not an existing fragment aggregator. Open-PR owned-path collision query returned
no matches. Reuse is the unchanged, SHA-bound extractor and its fence parser,
loaded only from this candidate's `sources/` closure. `BASES.json` binds every
source, test and synthetic fixture (not itself or this evolving receipt).

Candidate ONLY: no live CHANGELOG edit, release workflow/docs adoption, installed
CLI replacement, CI enrollment, fragment consumption or other hotspot work.
All fixtures are synthetic. Temporary test data stays under this candidate root
and is cleaned per test; checked fixtures are never modified. The optional
stdout CLI has no output-file switch and completes validation before stdout.

## Contract / manual semantic check

Strict four-digit order + user/internal filenames; globally unique order keys.
Numeric ordering within categories; user then Internal partition. New list
content follows existing category content without reordering existing bullets.
Exactly one Unreleased; at most one Internal in it; the shared fence parser
rejects unclosed fences and ignores headings in closed examples. Real release,
Unreleased and Internal headings in fragments refuse. Invalid names, traversal,
symlink paths, nonregular entries and non-UTF8/empty content refuse. Every entry's
name/type is checked before fragment content reads. Files are opened no-follow,
nonblocking, then fstat-checked as regular. No fragment is consumed or written.

Modified Unreleased: preserve interior existing content/whitespace, strip only
boundary CR/LF, separate header/category bodies/fragments with one blank LF line,
and use one final LF at EOF or one blank LF line before the next section. Other
prefix/released bytes are untouched (including CRLF and missing final newline).
An empty fragment directory returns valid base bytes unchanged. Repeated original
inputs and reversed enumeration/creation produce the same union, not a claim of
rendered-input idempotence. Cancellation/expiry are not static-file API states;
stale input means the supplied base, not fetched state. No clocks, GitHub calls,
locks or live inventory are introduced. Duplicate keys fail atomically.

Extractor-output and byte parity cover every synthetic released section; the
unchanged main extractor's existing regression tests additionally run below.
This is machine-valid evidence requiring review, not adoption or live acceptance.

## Acceptance execution

Cwd: `/home/user/.hermes/kanban/boards/skippercast/workspaces/t_aad1a2bd/repo`

Command: `/home/user/agent-work/bin/memcap -- .venv/bin/python3 -B -m pytest -q -p no:cacheprovider workspace/candidates/AUDINV-FAB-15/tests`

Exit: **0**

stdout (complete):
````text
.............................                                            [100%]
29 passed in 0.69s
````

stderr (complete):
````text
````

Cwd: `/home/user/.hermes/kanban/boards/skippercast/workspaces/t_aad1a2bd/repo`

Command: `/home/user/agent-work/bin/memcap -- .venv/bin/python3 -B -m unittest tests.contract.test_changelog_section tests.contract.test_changelog_section_edges tests.contract.test_changelog_section_fences -v`

Exit: **0**

stdout (complete):
````text
````

stderr (complete):
````text
test_accepts_bare_version_and_last_section (tests.contract.test_changelog_section.ChangelogSectionTests.test_accepts_bare_version_and_last_section) ... ok
test_cli_exit_status (tests.contract.test_changelog_section.ChangelogSectionTests.test_cli_exit_status) ... ok
test_empty_section_fails (tests.contract.test_changelog_section.ChangelogSectionTests.test_empty_section_fails) ... ok
test_extracts_section_with_internal_subsection (tests.contract.test_changelog_section.ChangelogSectionTests.test_extracts_section_with_internal_subsection) ... ok
test_prefix_versions_do_not_match (tests.contract.test_changelog_section.ChangelogSectionTests.test_prefix_versions_do_not_match) ... ok
test_rejects_non_versions_and_unreleased (tests.contract.test_changelog_section.ChangelogSectionTests.test_rejects_non_versions_and_unreleased) ... ok
test_repository_changelog_has_current_release (tests.contract.test_changelog_section.ChangelogSectionTests.test_repository_changelog_has_current_release) ... ok
test_unreleased_separates_internal_changes (tests.contract.test_changelog_section.ChangelogSectionTests.test_unreleased_separates_internal_changes) ... ok
test_doubled_heading_is_refused (tests.contract.test_changelog_section_edges.ChangelogSectionEdgeTests.test_doubled_heading_is_refused) ... ok
test_folder_as_changelog (tests.contract.test_changelog_section_edges.ChangelogSectionEdgeTests.test_folder_as_changelog) ... ok
test_missing_file (tests.contract.test_changelog_section_edges.ChangelogSectionEdgeTests.test_missing_file) ... ok
test_non_utf8_bytes (tests.contract.test_changelog_section_edges.ChangelogSectionEdgeTests.test_non_utf8_bytes) ... ok
test_prerelease_prefix_is_not_a_double (tests.contract.test_changelog_section_edges.ChangelogSectionEdgeTests.test_prerelease_prefix_is_not_a_double) ... ok
test_real_changelog_newest_release_unchanged (tests.contract.test_changelog_section_edges.ChangelogSectionEdgeTests.test_real_changelog_newest_release_unchanged) ... ok
test_v_heading_matched_once (tests.contract.test_changelog_section_edges.ChangelogSectionEdgeTests.test_v_heading_matched_once) ... ok
test_backtick_info_string_with_backtick_is_not_a_fence (tests.contract.test_changelog_section_fences.ChangelogSectionFenceTests.test_backtick_info_string_with_backtick_is_not_a_fence) ... ok
test_fenced_version_example_is_not_a_doubled_heading (tests.contract.test_changelog_section_fences.ChangelogSectionFenceTests.test_fenced_version_example_is_not_a_doubled_heading) ... ok
test_heading_inside_fence_neither_ends_nor_starts_a_section (tests.contract.test_changelog_section_fences.ChangelogSectionFenceTests.test_heading_inside_fence_neither_ends_nor_starts_a_section) ... ok
test_real_changelog_notes_match_main_for_every_heading (tests.contract.test_changelog_section_fences.ChangelogSectionFenceTests.test_real_changelog_notes_match_main_for_every_heading) ... ok
test_tilde_long_and_indented_fences (tests.contract.test_changelog_section_fences.ChangelogSectionFenceTests.test_tilde_long_and_indented_fences) ... ok
test_unclosed_fence_in_earlier_section_exits_one_by_line (tests.contract.test_changelog_section_fences.ChangelogSectionFenceTests.test_unclosed_fence_in_earlier_section_exits_one_by_line) ... ok

----------------------------------------------------------------------
Ran 21 tests in 0.194s

OK
````

Cwd: `/home/user/.hermes/kanban/boards/skippercast/workspaces/t_aad1a2bd/repo`

Command: `git diff --check`

Exit: **0**

stdout (complete):
````text
````

stderr (complete):
````text
````
