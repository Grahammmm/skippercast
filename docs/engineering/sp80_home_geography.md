# SP80: explicit coastal geography wins over the saved home

## Contract and change

Frozen card contract version 1, SP80-HOME-GEOGRAPHY. The sole product change
extends the existing presence-based place/area guard in `homeURL` to region
and coast. This matches the shared-address selectors in `onboarding.ts`.
It does not validate locations, change storage, or change any viewer logic.
Reset still clears query/hash first, making saved place/profile the only
restored parameters. No terrain, place inventory or navigation guarantee.

## Claim-to-test mapping

The synthetic fixture is `tests/fixtures/sp80_home_geography/cases.json`,
shaped from the committed `HomePreferences` interface and original port
URL tests. All addresses use the reserved example.test domain as inert URL
data; no address is fetched. The tests dynamically import the complete
actual preferences module only after installing offline/browser sentinels.
That module has only a type-only import and no top-level browser operation.

- A1: `A1/A2 region`, `region-extra`, `coast`, `coast-extra`, `empty-region`,
  `empty-coast`, `both`, and `empty-both-extra`, each with explicit/saved
  profile. Exact URL equality proves no home place is injected and all query
  values/hash/origin/path/port survive. Empty values retain presence semantics.
- A2: the same matrix includes place, area, empty-place and empty-area;
  explicit profiles win and absent profiles get the saved mode. The two
  additional named A2 cases exercise empty profile and bare query/hash.
  Every helper invocation asserts cloned URL identity, unchanged input URL,
  unchanged frozen preferences, and zero network/browser sentinel attempts.
- A3: `A3 reset <fixture-id> restores exactly home`, plus bare reset, checks
  exact restored URL and parameter list, with no fragment. Original addresses
  include explicit profile and unrelated query values as discard controls.
- A4: `A4 primary explicit-region preserves geography` captures the product
  return/exception before asserting the named semantic requirement;
  `A4 healthy bare-address restores home` is the healthy control. Baseline
  runs these exact two tests only, not skipped versions of the whole suite.
  Focused reuses them unchanged, with all other A1-A3 cases (41 total).

## Evidence and reproduction

Run the portable launcher from the repository root:

    python3 scripts/accept_sp80_home_geography.py --suite baseline --output ../out/author-baseline
    python3 scripts/accept_sp80_home_geography.py --suite focused --output ../out/author-focused
    python3 scripts/accept_sp80_home_geography.py --suite regression --output ../out/author-regression
    python3 scripts/accept_sp80_home_geography.py --suite repository --output ../out/author-repository

Baseline is historical evidence: run BEFORE repair only. It verifies original
product SHA256 `3ca536f2e4763ee5591e5f3c7a66a096ddb5db104d38e148230a506ed89c02bc`
at staging base `a1f648632e64561d82dcbeb20d9bda19f812560a`.
Observed child exit 1: exactly the region primary fails, with observed
`place=morro`, while the bare control passes. The wrapper exit 0 means
`BASELINE_DEFECT_REPRODUCED`, NOT product acceptance. Tests/fixtures were
frozen before the one-line repair and remain identical for final green.
A baseline invocation on repaired source must fail, not regenerate evidence.

Each invocation creates a unique child output directory with raw stdout,
stderr and a schema-version-1 receipt: full actual HEAD, staging manifest
hash, source/test/fixture hashes, literal child argv/cwd, runtime/version,
child/wrapper exits and test counts. Final phases require historical
baseline evidence matching the exact test/fixture hashes. Earlier receipts
are never overwritten. Failed preflight receipts are retained, too.

Regression runs exactly the unchanged `tests/test_home_port.mjs` (8 tests)
and `tests/test_ports.mjs` (23 tests). The launcher checks their bytes against
the base, inventories local literal import closure and installed package
availability, including the original esbuild synthetic TSX entry. A preload
installs offline network sentinels before original suite imports. Fetch
mocks, synthetic storage/cookie doubles and explicit loader arguments remain
those of the original suites. Child TMPDIR is a fresh directory inside the
invocation output root, confining esbuild's existing temporary bundle there.
No product defaults require redirection on these invoked paths. These
sentinels are accidental-call detection, not a hostile-code sandbox.

Repository mode uses the automatically staged SOURCE-MANIFEST.json's
`runtime.credential_scan_python3` for unchanged `scripts/check_repository.py`;
it does not silently use the launcher interpreter. Run `pnpm typecheck`,
`pnpm build`, `git diff --check <base> HEAD` and `git status --porcelain`
separately at final signed-off HEAD as well. Generated build output stays in
the candidate's already ignored dist/client and dist/server directories.

## Limits and provenance

All new material and the single product edit are authored by actual
`gpt-6.1-sol` / `openai-codex`, sol-reviewer, card run 1558. No Astra diagnostic
code was copied. Sole independent same-card reviewer: actual Claude Opus
5.5 on opus-coder-bopus. The staged .venv symlink is retained with a local
untracked Git exclude; no tracked ignore or dependency change is included.

Scoped green remains REVIEW REQUIRED. These two compatibility suites are
not full-suite CI. The operator still owns PR creation, full-suite execution,
exact-head required CI, and any approved shipping. No push, merge, source
acquisition, network/model call, publication or hold release occurred here.
