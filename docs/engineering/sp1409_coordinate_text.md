# SP1409 coordinate-text suppression (SP-14-v1)

## Scope and behavior

`server/advisor/answers/advice.ts` adds one alternative to `COORDINATE`.
The added grammar requires one to three degree digits, a whitespace or
optional degree-symbol separator, one or two minute digits (optionally with
a decimal fraction), an optional minute prime, and an explicit N/S/E/W
compass token. Matching is case-insensitive. Degree numbers cannot start
inside a word, longer digit run or decimal fraction; direction letters
cannot be prefixes of longer word tokens. The original decimal-degree,
degree-sign and Loran-like alternatives remain in place.

`publicOnly` still drops the whole containing sentence with its existing
sentence splitter; it never rounds, substitutes or invents a location.
No bare-number filter, geographic inference, public-ground expansion,
catalog edits or source changes are introduced. Existing precision-based
filtering remains deliberately unchanged, including its conservative
false positives. This is not a general coordinate parser or navigation
qualification. Sentence splitting remains the existing punctuation followed
by whitespace policy, not a new NLP implementation.

## Acceptance mapping

All new assertions import the complete real advice module with its committed
JSON catalog imports; there is no extracted-function substitute.
`tests/fixtures/sp1409_coordinate_text/cases.json` contains only synthetic
text and unchanged-catalog expected controls. `requirements.json` freezes
SP-14-v1, selected test names, baseline pin and material-author provenance.

- A1: `primary regression` and `A1 coordinate grammar variants drop the
  sentence without replacement`. The exact unprimed coordinate sentence is
  removed and `Use a slow drift.` survives. Variants cover one/two/three
  degree digits, every compass direction, lowercase, primes, degree symbols,
  spaces/tabs/newlines/nonbreaking spaces, parentheses, comma/semicolon and
  terminal punctuation. Existing signed decimal pairs, high precision,
  degree-sign and Loran-like cases remain suppressed. Coordinate-only
  sentences yield null.
- A2: `healthy control` and `A2 ordinary fishing units clock dimensions and
  bounded tokens survive`. Depth, weight, line strength, decimal line weight,
  clock text, dimensions and near-miss word/number tokens survive unchanged.
- A3: the three `A3` tests exercise publicOnly ordering/null behavior,
  publicAreas allowlisting/region isolation/depth bands/candidate ordering,
  and strategyFor's unchanged lingcod/halibut/unknown-species controls.
  They read the original catalogs without modifying them.
- A4: baseline registers exactly `primary regression` and `healthy control`;
  it does not select by skipping other tests. The primary carries the unique
  `SP1409_PRIMARY_SEMANTIC_MISMATCH` assertion marker. The same test file and
  fixture bytes are used in final focused mode, which registers all seven
  tests. The unchanged-product baseline is expected to have exactly one
  assertion failure, one pass, child exit 1 and zero skips/cancellations/todo.
  Launcher exit 0 means `BASELINE_GAP_REPRODUCED`, NOT a fix pass.

The unchanged `tests/test_advisor_tools.mjs` regression suite runs all 31
registered tests, including its migration-backed in-memory SQLite cases.
No original expected values or catalogs were amended.

## Offline process and portability

The acceptance helper derives the repository and candidate from its own
location. It requires the operator's candidate-level SOURCE-MANIFEST.json,
matching source pin, staged runtime and credential-scanning interpreter;
it never installs dependencies or falls back to system Python for scanning.
Fixture/output paths are ancestry-checked before access, symlinks are refused,
and each invocation creates a unique child under its candidate-local output
argument. Prior evidence is never overwritten. Approved staged dependency
links are neither modified nor replaced.

The file-based offline bootstrap is preloaded before product imports. Global
fetch, HTTP(S), sockets, common DNS entry points and persistent-storage globals
are refusal sentinels. SQLite is constrained to `:memory:`; original regression
tests keep their own recorded feed/API fakes and migration-backed adapter.
The new test hooks restore globals between cases and at completion; original
regressions run in a separate guarded process. The sentinels are defense in
depth, not a hostile-code sandbox. No actual storage, provider/model, fleet,
inbox or external network operation is exercised.

Run separately from the staged repository (output roots are examples):

    python3 scripts/accept_sp1409_coordinate_text.py --suite baseline --output ../out/author-baseline
    python3 scripts/accept_sp1409_coordinate_text.py --suite focused --output ../out/author-focused
    python3 scripts/accept_sp1409_coordinate_text.py --suite regression --output ../out/author-regression
    python3 scripts/accept_sp1409_coordinate_text.py --suite repository --output ../out/author-repository
    python3 scripts/accept_sp1409_coordinate_text.py --suite typecheck --output ../out/author-typecheck
    python3 scripts/accept_sp1409_coordinate_text.py --suite build --output ../out/author-build

Baseline is only valid at the unchanged pinned product, before the product
edit; do not run it on the fixed HEAD expecting a green fix result.
Node uses installed runtime type stripping and a file-based bootstrap.
Typecheck launches three separate tsc children. Build invokes the existing
`pnpm build`, without deployment. Repository mode launches the unchanged
repository checker under the manifest's admitted scanner interpreter.
Explicit checks, not Python assertions, determine acceptance exits.
Receipts preserve actual argv/cwd, runtime, source/spec/test/fixture hashes,
HEAD and worktree status, material provenance, names/counts, child exits,
stdout/stderr and hashes. Reviewer reruns must use separate output roots.

## Development evidence and limitations

The first baseline correctly reproduced the leak. Initial original-regression
execution exposed an authored offline-wrapper bug: explicitly forwarding an
undefined SQLite options argument caused 10 setup failures (21 passed, zero
skips). The wrapper was corrected to preserve constructor argument omission;
no product assertion, original test or source dependency was weakened.
That failed receipt and the first baseline remain retained. A fresh baseline
was captured with the corrected wrapper and the exact original product hash
before reapplying the same product delta. The refreshed baseline's complete
test/fixture hashes are the final frozen baseline for review.

All material authored here is actual gpt-6.1-sol / openai-codex, sol-reviewer,
kanban t_cc1e7846 run 1808. Commit trailers repeat actual runtime provenance.
Sole independent reviewer: opus-coder-bopus on actual Claude Opus 5.5.
There has been no independent approval by this author.

Scoped passing results are REVIEW REQUIRED, not whole-repository or release
acceptance. The existing operator retains PR publication, unchanged complete
local full-suite execution, exact-head required CI and final release ownership.
All other repository groups remain OWED to those owners, including complete
Node discovery, Python/GIS matrices and strict skip accounting, regional/search
rebuild parity, credential/public-tree/link/privacy and web/client/copy/token
checks, audit and browser/e2e coverage. No local scoped result waives them.
SC#1/PR846, SC-5b, terrain-mask, public-viewer, legal-preview, source/live and
bulk-download holds remain. No source acquisition, network/model call,
publication, merge, live run, operational deletion, install or hold change
is authorized or performed by this work.
