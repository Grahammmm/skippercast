# SP1707: stored Instagram handle case on verified boat pages

Spec: SP-17-v1 / SP1707-BOAT-HANDLE-CASE.

## Bounded behavior

The boat page's existing Instagram predicate now accepts ASCII uppercase letters
as well as lowercase letters, digits, dot and underscore, at the existing 1–30
character limit. Rendering preserves the stored handle's spelling in its URL and
label. The destination and escaping template are unchanged. This is a read-side
compatibility correction for stored rows, not an intake or verification change.
Current intake normalization and the incidence of affected live boats have not
been established. No live broken page is claimed.

Only `server/advisor/pages/boat.ts` changes among product files. Pending boats
still expose no contact details and remain noindex; rejected boats still return
404. No new contact method, account permission or outbound behavior is added.

## Synthetic integration coverage

`tests/test_sp1707_boat_handle_case.mjs` imports the complete real Worker and uses
the existing migration-backed `tests/_advisor_d1.mjs` adapter, with a fresh
in-memory database per render. The fixture row uses the original advisor suite's
real column vocabulary. Every database is closed. There are no copied rendering
algorithms or planner slices.

The dedicated preload installs accidental network/model-I/O sentinels before
product imports. The focused suite supplies only its in-memory DB and inert live
binding sentinels, disables fleet lookup and caching, injects the clock and an
unexpected-feed refusal, and restores globals and page dependencies. All requests
are calls to `worker.fetch` in-process, not network requests. Process-scoped
transport guards are restored at exit; an attempted external call makes the child
fail even if product code catches it. These guards are not a hostile-code sandbox.

Required mapping:

- A1: a verified boat with only mixed-case Instagram contact renders exactly one
  complete anchor and its contact section through the real route and full page.
- CONTROL: the same lowercase-only contact still renders normally.
- A2: 7 valid inputs, each in English and Spanish, preserve URL and label identity;
  11 invalid/null inputs are withheld, without an empty contact section. The
  matrix includes upper/lower/mixed case, dot/digit/underscore, length 1 and 30,
  length 31, slash, colon, markup, non-ASCII, whitespace, hyphen and leading at-sign.
- A3: pending pages remain byte-identical regardless of the valid handle; details,
  reports and photos stay hidden, with the pending badge/noindex. Rejected boats
  are 404/no-store/noindex. A disabled advisor remains 404.
- A4: whole-page mixed/lowercase comparison differs only in handle spelling.
  Booking URL/phone rendering, approved/posted versus private photos, credits,
  escaped hostile name/landing, edited report and catch counts are asserted.
  Invalid booking protocols/credentials and phone values remain withheld.

Focused TAP count: 23 (5 parent tests plus 18 A2 subtests), zero skips. The
unchanged `tests/test_advisor_pages.mjs` regression suite executes 15 tests, zero
skips. These are scoped counts, not full-repository CI counts.

## Test-first and retained preflight history

The admitted base is `8a805820c30895f5f037e26af9079fd3dc015b0f`.
Tests, fixture and runner were authored before the product edit. The primary
selector failed with `ERR_ASSERTION` and `SP1707_A1_MIXED_CASE_ANCHOR` on unchanged
product, while the lowercase control passed. Initial baseline receipt SHA256:
`054b6158c0a54dbb3e1811bea59b2178344830146c14177d5527915dd3844d57`.

The first focused run caught an authored length-boundary fixture typo (32 versus
30) before A2's matrix ran. Its failed receipt is retained:
`566504c932a87e8a208988036fc767c2c4081ed9372b30b01731702c6be99391`.
Only the synthetic literals were corrected; assertions were not weakened. The
one-line product edit was restored to baseline before re-running the diagnostic.
The renewed baseline receipt is
`34159439c374e5c8c821b811aba1f871d0be8361dc5c8e510658d93fe95623b6`:
one named primary failure (child exit 1), one healthy pass (child exit 0), no
skips or setup failures. Test, runner and corrected fixture bytes were then
frozen before reapplying the same product repair. No prior receipt was resealed.

## Reproduce and inspect evidence

From this staged repository, invoke the file-based runner with installed Python:

    python3 scripts/accept_sp1707_boat_handle_case.py --phase focused --output ../out/reviewer-focused
    python3 scripts/accept_sp1707_boat_handle_case.py --phase regression --output ../out/reviewer-regression
    python3 scripts/accept_sp1707_boat_handle_case.py --phase repository --output ../out/reviewer-repository
    python3 scripts/accept_sp1707_boat_handle_case.py --phase typecheck --output ../out/reviewer-typecheck
    python3 scripts/accept_sp1707_boat_handle_case.py --phase build --output ../out/reviewer-build

Run each command separately. `--phase baseline` is intentionally accepted only
on unchanged baseline product, not the repaired head. Its exact frozen primary
and control selectors are also part of the full focused suite. Historical red
receipts retain their own source identity; no reset of this clone is needed for
review. Tests can also be discovered directly by the repository's standard Node
runner; no staging manifest or planner path is imported by a test.

Every invocation creates a new UUID output child outside the repo. Each receipt
records HEAD, base, dirty status, diff digest, source/test/fixture/runner hashes,
staging-manifest hash, Python/Node runtime, actual child argv/cwd/exits/counts and
full raw stdout/stderr hashes. A missing runtime, skipped test, child failure,
source mutation or unexpected baseline result fails explicitly, without relying
on Python assertions. The baseline wrapper exits 0 only for its exact red/green
contract. Never reinterpret that expected red as a passing product test.

The runner validates the operator's adjacent source manifest and uses its
`runtime.credential_scan_python3` for unchanged `scripts/check_repository.py`,
without substituting system Python. Typecheck runs three separate installed
`pnpm exec tsc --noEmit --project` children for the root, web and coast configs.
Build runs the existing local `pnpm build`; no deploy is invoked. Dependencies
must already be staged; nothing is downloaded or installed. Author final-green
receipts use the `../out/author-final-*` roots. The final review handoff outside
the repository identifies the exact signed-off HEAD and verified receipt hashes.

## Authorship and retained gates

All new material and the product edit are authored by actual `gpt-6.1-sol` via
`openai-codex`, profile `sol-reviewer`, task run 2204, under the explicit operator
reassignment. The preceding Luna run authored no material. Each material commit
is signed off and records actual model/provider provenance. Sole independent
same-card reviewer: `opus-coder-bopus`, actual Claude Opus 5.5. Sol is the builder
here and does not approve its own work.

Successful local acceptance means REVIEW REQUIRED. Operator-owned PR publication,
full-repository/exact-head required CI, browser/e2e and other retained release
checks remain OWED. This candidate grants no merge, source acquisition, live run,
publication, scientific/legal/navigation acceptance or hold release. All existing
source/live/bulk-download, public-viewer, legal-preview, terrain-mask,
SC#1/PR846 and SC-5b holds remain intact.
