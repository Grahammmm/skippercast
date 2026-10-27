# SP71: URL authority normalization

Scope: only `clean_url` authority validation and reconstruction. This is not
an SSRF policy, host allowlist, URL acquisition or fleet registry change.

## Claims and executable cases

The synthetic fixture `tests/fixtures/sp71_url_port/urls.json` uses the string
interface of unchanged `NormalizeTests.test_roman_phone_url_slug` and fleet
`source_url` fields, not acquired records. `test_sp71_url_port.py` creates a
separately named unittest for every fixture row; each checks the exact result
and input immutability. It imports the complete real module, never a snippet.

| Contract | Named assertions on `CleanUrlAuthorityTests` |
|---|---|
| A1: alphabetic, negative, above-65535 ports; malformed bracket/literal; non-HTTPS and non-string return None | `test_invalid_*` (including explicit alphabetic/negative/above_range_port cases) |
| A2: IPv6 documentation literal retains brackets with no port, 443, 8443 and zero | `test_valid_authorities_ipv6_*`; emitted URLs are parsed again to compare host and port |
| A2: lowercase domain, explicit zero, upper boundary 65535 | `test_valid_authorities_lowercase_domain`, `test_valid_authorities_port_zero`, `test_valid_authorities_maximum_port` |
| A2: existing userinfo rejection | `test_invalid_userinfo_rejected` |
| A3: original valid-domain query example unchanged | `test_preservation_original_tracking_example` |
| A3: empty path, fragment removal, query order, blanks, duplicate nontracking values, stripping and case normalization unchanged | `test_preservation_*` |
| A4: identical before/after primary and separate healthy control | `test_primary_bad_port`, `test_healthy_control` |
| Original compatibility | Literal selector `tests.unit.test_fleet_resolve.NormalizeTests`, unchanged |

Changed product branches map to three classes: invalid `parts.port` raises
inside the validation boundary and returns None (A1); IPv6 hostname gains its
required authority brackets (A2); explicit numeric zero is retained using
`port is not None` (A2). Query parsing/filtering/encoding, string stripping,
HTTPS checks, userinfo checks, default slash and fragment removal are unchanged.
Valid domain preservation expectations are literal, not computed by a second
copy of the implementation. The original tracking example is retained from the
unchanged original suite, and the healthy control also passed before repair.

## Honest test-first evidence

The resumed Sol build preserved Luna's candidate repair outside the repository,
restored the complete pinned original product file, verified its SHA256 as
`3bd6ae8fa023757f2bded051006d1205c7eae180bae2e649061a1b3afda6dcea`, then ran a
fresh baseline with the final frozen test and fixture bytes before reapplying
that repair. The primary captures the product ValueError as data and fails a
named assertion; the separate healthy test passes. Baseline qualification
requires exactly that ValueError message, one failure, one pass, zero errors
and zero skips, child exit 1 and wrapper exit 0. It is
`BASELINE_DEFECT_REPRODUCED`, never final-head green evidence.

Earlier Luna receipts are retained untouched, including the invalid baseline
with one unittest ERROR and the earlier focused fixture mistake. They are not
acceptance for these final test bytes and are not reclassified or overwritten.
Final green acceptance runs again after the signed-off commit. Every receipt
records the actual HEAD separately from source/test/fixture hashes; baseline
had uncommitted new tests and its product file at the pinned base.

## Runtime and offline boundary

Run `python3 scripts/accept_sp71_url_port.py --suite MODE --output OUTPUT` from
the staged candidate, where MODE is baseline, focused, regression or repository
and OUTPUT is inside its sibling `out` directory. Every invocation makes a
fresh unique child under OUTPUT, even when that parent already exists. The
helper derives all repository and write paths from its own location and reads
only the staged `SOURCE-MANIFEST.json` above the repository. No plan directory
or box-only home path is embedded in committed files.

Python tests use the staged `.venv/bin/python3`; repository scan uses exactly
`runtime.credential_scan_python3`. There is no installation or fallback. A
file-based child entry in the helper sets candidate import paths in code and
suppresses bytecode. For the scan it executes the complete unchanged
`scripts/check_repository.py` through `runpy` under the manifest interpreter;
the receipt logs both child argv and target script identity. Raw stdout/stderr,
versions, counts, literal argv/cwd, exits and SHA256 values are retained. The
repository row reports one scan check plus the script's actual text-file count;
it is not a unittest count or a full-suite claim.

Before target imports the child installs process-local audit sentinels for
network/DNS, child processes and SQLite connections and for file writes outside
its unique output root. They fail acceptance if triggered, even if target code
catches an exception. `SKIPPERCAST_ROOT` is set before imports to bind all
repository constants and function defaults to this candidate; TMPDIR and the
Python temporary directory are set to that run's private `tmp` directory.
The selected tests are pure normalization calls and require no live constants,
cache, model calls or network. No actual target is contacted to probe guards.
These controls are not a hostile-code sandbox, nor a qualification of unrelated
modules. New test imports install no hooks and do not poison peer CI suites.

The helper statically enumerates the regression import closure before loading,
logs its hashes/imports/module calls, and verifies read-only local modules
against the staging base. Inspection found the test module's resolver catalog
read inside the candidate; the eager adapter registry imports parser modules,
HTTP definitions and collection definitions, but invokes no fetch, model,
sink, forecast sampler or child command. The selected NormalizeTests class has
no setup/teardown, lazy imports or child commands. Other classes in the original
module, including SQLite round-trip tests, are not selected. The literal
selector must resolve, execute all its loaded test IDs and have no failure,
error, expected failure or skip. The scanner's source is also checked unchanged.

## Authorship and remaining ownership

Luna's uncommitted implementation was preserved and continued by actual
`gpt-6.1-sol` on `sol-reviewer` / `openai-codex` (task run 1682). Operator admission
identifies Luna's earlier material as actual `gpt-6-luna` in the Codex lane
(task run 1628); Luna made no material commit. The final commit discloses both:
Luna originated the small product repair and initial fixture/test/helper/doc
scaffolding; Sol retained that product repair and rewrote/extended the test,
fixture, acceptance and engineering note. No Astra diagnostic implementation is
copied. This is author self-review only. Sole independent same-card review is
Claude Opus 5.5 on `opus-coder-bopus`, per operator disposition.

Local scoped success remains REVIEW REQUIRED. The operator owns PR creation,
full-suite checks, exact-head required CI and shipping. No push, merge, live
run, publication, hold lift or new release authority is claimed.
