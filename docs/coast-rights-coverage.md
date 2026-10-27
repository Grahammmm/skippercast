# Recipe rights coverage (N3)

This offline diagnostic checks coverage, not whether reuse is legally permitted.
A rights page must not be called complete when a recipe source is omitted.
This tool does not generate that page, change catalog status, fetch data, make
navigation claims, or authorize publication. Machine-valid output is REVIEW
REQUIRED; all human, legal, source and publication holds remain in force.

## Interface

Run the candidate script with three required absolute paths:

    python3 scripts/coast_diagnostics/rights_coverage.py --repo-root ABS --recipe ABS --output-root NEWABS

The output directory must not exist. Symlink components and parent traversal
are refused. Inputs are read-only. Each successful invocation writes
`coverage.json` and `coverage.txt` and prints the plain-English table. Exit 0
means a report was produced, not COMPLETE or permission to publish; invalid
input or an existing output directory exits 2 without overwriting that output.
Use a fresh unique output path on every invocation.

The recipe uses the existing `sources` array (for example,
`regions/morro-bay/coast.json`). It must be nonempty and contain source slugs.
Repeated slugs are reported once, in first-seen order. The lookup indexes every
row of `catalog/sources.json` and every JSON entry in `catalog/candidates`.
Missing entries are `CatalogEntryMissing`; duplicate IDs are ambiguous and
fail closed. Malformed catalog inputs refuse the report rather than silently
omitting a source.

For a unique match the tool passes the catalog row unchanged to the actual
`skippercast.seafloor.rights.source_rights` module. It records the returned
rights object or typed exception and whether the returned attribution is a
nonblank string. It deliberately does NOT translate the provider register's
nested `rights` schema into the resolver's top-level survey schema, invent
producer permissions, substitute default licenses, or promote candidates.
Consequently a catalog entry can be found while the resolver still raises
ValueError. That is INCOMPLETE, not a legal judgment or a catalog defect fixed
by this tool. The human register is [data-rights-register.md](legal/data-rights-register.md).

COMPLETE requires every unique slug to have exactly one catalog match, a
successful rights result and nonblank attribution. All other reports are
INCOMPLETE and list every unresolved or unattributed slug. Rights objects,
exception messages and text are projected through URL-host sanitization:
schemes, credentials, URL paths, queries and fragments are not emitted. The
result is an aggregate source-level diagnostic: no cells, navigation geometry,
source downloads or raw survey data.

## Frozen acceptance and evidence

`run_n3_rights_coverage_acceptance.py` supports focused, compatibility, negative
and portability modes. Invoke each separately with `--mode MODE --output-root
ABS`. It allocates a new directory, records argv/cwd, exact local HEAD,
authored/protected byte hashes, raw stdout/stderr and their hashes, executed
test/subtest/skip counts and actual module origins. It uses unittest in-process;
there are no shell or child-interpreter calls. Missing dependencies exit 3
INPUT_UNAVAILABLE and remain an operator staging item, never an install or
import-path workaround. Explicit exits determine acceptance, not Python assert.
Socket, DNS and subprocess seams are installed before candidate imports;
invocations of those seams also fail the final receipt even if caught. These
are offline accidental-side-effect controls, not a hostile-code sandbox.

The initial focused red result was captured before implementation was present.
It is test-first evidence only and must not be counted as acceptance. Later
receipts retain that history rather than overwriting it.

A1: At least nine focused tests cover complete, absent, ambiguous, existing
ValueError/KeyError, missing attribution, unchanged resolver inputs, nested
catalog rights not silently promoted, URL privacy, malformed/empty recipes,
repeated slugs, no-overwrite, symlink refusal and the committed Morro Bay
recipe. The real recipe verdict is recorded and compared with direct actual
resolver calls, not hardcoded COMPLETE.

A2: All six admitted SourceRightsTests methods run, including all their
subTest cases. The sole excluded method is
`test_paid_deployment_cannot_enable_noncommercial_sources_or_weaken_policy`,
which deletes a synthetic file and stays operator-owned exact-head CI.
The runner checks byte identity of rights.py, its contract file and the
repository guard against the staged base. None is modified.

A3: An isolated in-memory `_verdict` mutation reports COMPLETE for a missing
catalog entry. The named missing-catalog test must fail exactly on its verdict
assertion, with no error or skip; after automatic restoration, the same test
must pass. The expected mutant failure is not an unexpected acceptance failure.

A4: The focused suite runs against a differently named copied root with a
synthetic HOME set before candidate imports, verifies every relevant module
origin belongs to that root, checks portable authored inputs and uses fresh
output/fixture allocation. No shared runtime or environment import override is
modified.

A5: Run the unchanged `scripts/check_repository.py` separately. Full discovery,
push, PR and exact-head CI are operator-owned and still owed before release.

The committed synthetic federal fixture is read-only. Runtime fixtures are
generated in each receipt's unique `tests/fixtures/n3_rights_coverage` subtree,
never inside committed fixture directories. Test-only allocations are retained
for inspection; the runner performs no deletion or cleanup commands.

The material author is actual gpt-6.1-sol via openai-codex on sol-reviewer.
Independent same-card review is assigned to actual Claude Opus 5.5 on
opus-coder-bopus. A signed-off local head and passing scoped tests do not
replace that independent review or operator exact-head CI.
