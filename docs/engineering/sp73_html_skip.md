# SP73: tag-aware exclusion in the shared fleet HTML tree

Scope: `fleet.adapters._html` only. This is a forgiving extraction tree, not
an HTML sanitizer, a browser rendering contract, or permission to render markup.
The landing-pages adapter's separate parser is unchanged.

## Behavior and claim-to-test map

All inputs are committed synthetic markup in
`tests/fixtures/sp73_html_skip/cases.json`, derived from the shared tree's
`parse`/`Node` interfaces and the existing landing parser's synthetic vessel,
class, table and list shapes. No acquired pages, real fleet inputs or private
records are used. Each fixture produces a separately named `SkipTests.test_*`
case in `tests/unit/test_sp73_html_skip.py` (43 cases).

- A1/A4: `primary_unmatched_svg` and `healthy_balanced_template` are the exact
  pre-repair primary/control pair. `unmatched_noscript` covers the other unrelated
  closer. Exact text is `beforeafter`; the two visible paragraphs remain
  selectable. Hidden nodes/text cannot be found by class, tag or text predicate
  through either `find` or `find_all`.
- A2, opening scopes: `proper_nested`, `nested_same_tag`, `normal_siblings`,
  `balanced_*` and `case_insensitive` cover the tag stack and preserved normal
  tree parentage. Non-skipped starts while excluded never enter the normal tree.
- A2, matching/unwinding: `ancestor_unwind` closes an ancestor with unclosed
  skipped descendants; `nearest_matching_ancestor` chooses the nearest matching
  ancestor, not an older same-name scope. `repeated_closer_inside`,
  `repeated_closer_after` and `ordinary_closer_inside` establish that unmatched
  or ordinary closers do not release another scope or pop normal tree parents.
- A2, self-closing: `selfclosing_*` and `selfclosing_nested_*` cover every current
  SKIP member. Such elements create neither a node nor an exclusion scope.
  Ordinary `br/` and `i/` remain ordinary nodes.
- A2, end-of-input: `unclosed_*` suppress the remainder for every SKIP member.
- A2, tokenizer preservation: `script_raw_text`, `style_raw_text`,
  `raw_script_inside_template`, `raw_style_inside_template`,
  `unclosed_script_in_template` and `unclosed_style_in_template` use actual
  HTMLParser raw-text syntax. Apparent markup/ancestor closers inside script or
  style are text until their own closing tag; they are not nested callbacks.
  An unclosed raw-text element also prevents a later apparent template close
  from being tokenized. The implementation does not change HTMLParser behavior.
- A3: `implicit_p`, `implicit_li`, `implicit_td_th`, `implicit_dd_dt` and
  `spacing_entities_classes_stray` assert exact text, selected element identities,
  parents, entity decoding, classes and br spacing. The existing implicit-close
  loop is unchanged, including its existing recovery for an omitted cell/row
  close: a new tr closes the nearest cell first, so the synthetic second row is
  nested in the first. This card does not repair or normalize that behavior.
- A3 compatibility: the literal unchanged selector is
  `tests.unit.test_fleet_landings.ParserTests` (five methods). This is not the
  network/server-based `LandingPagesTests` class or full repository testing.

The production change replaces only the numeric skip depth with tag-aware
nesting and omits self-closing SKIP nodes. Normal tree creation, attributes,
implicit-close groups, normal end-tag handling, text collection and selection
are otherwise unchanged. Balanced skipped containers and unaffected ordinary
markup keep their existing results. Ancestor-unwind recovery and omission of
self-closing SKIP nodes are intentional specified changes.

## Acceptance and retained evidence

From the candidate repository, run the portable launcher with `python3`:

    python3 scripts/accept_sp73_html_skip.py --suite baseline --output ../out/author-baseline
    python3 scripts/accept_sp73_html_skip.py --suite focused --output ../out/author-focused
    python3 scripts/accept_sp73_html_skip.py --suite regression --output ../out/author-regression
    python3 scripts/accept_sp73_html_skip.py --suite repository --output ../out/author-repository

Baseline is BEFORE the repair only: the launcher requires the pinned complete
module SHA256 and exactly one primary semantic failure, one healthy pass, zero
errors/skips, raw child exit 1 and wrapper exit 0. It records
`BASELINE_DEFECT_REPRODUCED`, never GREEN. After repair the same frozen tests and
fixtures must match a retained successful historical baseline before any green
phase can qualify. Do not rerun baseline on a repaired head.

Each invocation creates a fresh unique directory, including child TMPDIR,
under its output parent. It retains raw stdout/stderr, structured child results
and schema-version-1 `receipt.json`: command/cwd, runtime/version, original
staging base, actual HEAD and dirty status, source/test/fixture/import-closure
hashes, case IDs/counts/exits, historical-baseline reference and raw file hashes.
Final green evidence must be rerun at the signed-off clean HEAD, not inferred
from the precommit runs. Reviewer reruns use their own output parents.

Historical author sequence (all receipts retained, none overwritten):

1. `author-baseline/baseline-z4acb7dq`: original primary/control reproduction.
2. `author-focused/focused-wl5ngoue`: 42 passed, one failed compatibility
   expectation. The fixture incorrectly expected sibling tr nodes, rather than
   the unchanged builder's nested-row recovery. Not product acceptance.
3. Restored the complete product module to its pinned bytes; corrected only the
   synthetic table selection expectation. No assertion about skip suppression
   was weakened. `author-baseline/baseline-hb4np1hq` is the new honest baseline
   for the final frozen test/fixture hashes: child 1, wrapper 0, one declared
   semantic failure and one healthy pass.
4. Reapplied the scoped repair; `author-focused/focused-13plt1ct` passed all 43.
   The final-head packet, outside the repo, identifies final green reruns.

## Runtime, closure and offline boundary

The helper derives all paths from its own location and reads the operator-owned
`SOURCE-MANIFEST.json` above the repo. It requires the pinned staging base and
actual candidate ancestry, the staged `.venv/bin/python3` for tests, and exactly
`runtime.credential_scan_python3` for repository scanning. No fallback or install
is used. The scan interpreter executes this file's child entry, which uses
`runpy` to invoke the unchanged `scripts/check_repository.py` as `__main__`;
the receipt records both the literal entry argv and target script. The scan is
the existing local link/private-material guard, not a fabricated new scanner.

Before importing target modules, the launcher statically inventories local
imports (including package initializers and dormant process-call candidates)
and requires all existing closure members other than the owned parser to match
the pinned base. It checks the literal regression class/method closure: five
pure parser tests, no server setup, sink invocation or child command. Their
called value/HTML parsing functions perform no acquisition. Other suites in the
imported test module are not loaded or executed. Closure imports define classes,
functions, regexes and registry/configuration constants; they do not instantiate
a session or invoke a job. Imports originate in this candidate, not shared
installed source. The runtime is already operator qualified.

The file-based child installs process-local audit sentinels before target
imports, refusing socket/DNS/HTTP, process/model subprocesses and SQLite opens.
Any attempted sentinel event fails the phase, even if target code catches it.
Writes are confined to the fresh output; bytecode is disabled, TMPDIR is explicit,
SKIPPERCAST_ROOT is the candidate before root constants/defaults bind, and the
ambient HTTP cache override is removed. No cache/session constructor or
live-default function is called by the selected tests; consequently there is no
bound cache/session default requiring replacement. No browser/profile cache is
used. Sentinels are accidental-side-effect defenses, not a hostile-code sandbox.
The tests themselves install no permanent audit hooks or global environment
changes during ordinary discovery, avoiding pollution of peer suites.

## Ownership and limits

Material author: actual gpt-6.1-sol / openai-codex, sol-reviewer, task
`t_f1822ff1` run 1684, under the operator's explicit Sol builder admission.
Luna's earlier run performed read-only admission/staging checks and made no
material commit. All new product, test, fixture, helper and note changes here
are Sol-authored; no Astra diagnostic implementation or copied test code is
claimed as independent material. Commit metadata also records this provenance.

Sole independent same-card reviewer: actual Claude Opus 5.5 on
`opus-coder-bopus`. Self-review and machine success remain REVIEW REQUIRED.
The operator owns PR creation, full-suite/exact-head CI, DCO and shipping.
Those obligations remain OWED. No push, merge, network/source acquisition,
live run, publication, service change, cap change or hold release is performed
or authorized by this evidence.
