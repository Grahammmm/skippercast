# SP1402 nearshore product attribution (SP-14-v1)

This is synthetic report-contract hardening, not source onboarding or evidence of a production incident. The complete real `web/map/nearshore.ts` module is imported with the installed Node runtime's native type stripping. No planner-extracted code, live report, DB, API, provider or model is used.

## Contract and tests

- A1 / `primary regression`: two fresh same-area sites with distinct report source labels. The second clicked card must use Synthetic Other in kind, source, basis and provider label; the first keeps CDIP MOP. Mixed summary uses the literal `multiple nearshore models`.
- A1 / `A1 attribution is per clicked site regardless of site and source ordering`: reverse site and source order, compare both complete cards, preserve output ordering and mixed summary.
- A2 / `healthy control`: the same two-site report with both source IDs set to cdip-mop retains both CDIP cards and the old summary.
- A2 / `A2 single and same-product CDIP preserve complete card and summary wording`: exact single-site wording, href, time zone, cadence, depth, warning, unknown-ID null; distinct IDs sharing one product still have a single-product summary.
- A3 / `A3 missing or unusable source labels fall back to the exact clicked source ID`: absent, null, empty, non-string, whitespace and empty product segment; missing status and missing sources. Fallback never borrows another site's source.
- A3 / `A3 geometry scale hit area ordering and per-site run age are unchanged`: coordinates, radii, key, ordering, hit paint, stroke, per-site age and warning.
- A3 / `A3 freshness span sampling and binding admission remain intact`: freshness boundaries, invalid coordinates, availability, area, span, sampling, missing binding and undrawn-source controls.
- A4: baseline registers only `primary regression` and `healthy control`, not filtered/skipped extra tests. The primary captures the actual card/exception before its precise semantic assertion. Baseline is valid only at the pinned unchanged product bytes and base HEAD, child exit 1, exactly one semantic failure and one passing control, zero skips/cancellations/todos. This is BASELINE_GAP_REPRODUCED, never a fix pass. Focused reruns those identical tests and all additional A1-A3 cases green.

Fixture shape is authored from the existing nearshore layer test's NearshoreSite/Report shape, using synthetic site names, coordinates and example.test URLs. `report.mjs` is input, not generated run evidence. `acceptance-spec.json` binds the versioned acceptance summary; the admitted task body remains controlling.

## Compatibility and delta

Each Ring carries its own `productOf(report, site.sourceId)` result. `Rings.product` remains that value when all drawn products agree and is `multiple nearshore models` otherwise. Only clicked-card attribution changes for heterogeneous products. Empty trimmed product labels fall back to the exact source ID rather than producing blank names. No source, registry, URL or acquisition path is added. The original key, geometry, freshness/span rules, radius, hit area and latest-run summary behavior remain unchanged. Mixed-run-age presentation is not redesigned here.

The unchanged `tests/test_nearshore_layer.mjs` is the regression mode and covers the original integration, Swell, cards, fake engine and rendered legend. It must execute every named test without skip or failure. Its test-owned temporary legend bundle is redirected into each unique run's tmp directory. No original tests or shared helpers are edited.

## Portable acceptance

From this repository's root, run each command separately, replacing OUTPUT with an absolute path beneath the staged candidate's out directory:

    python3 scripts/accept_sp1402_nearshore_product.py --suite baseline --output OUTPUT
    python3 scripts/accept_sp1402_nearshore_product.py --suite focused --output OUTPUT
    python3 scripts/accept_sp1402_nearshore_product.py --suite regression --output OUTPUT
    python3 scripts/accept_sp1402_nearshore_product.py --suite repository --output OUTPUT
    python3 scripts/accept_sp1402_nearshore_product.py --suite typecheck --output OUTPUT
    python3 scripts/accept_sp1402_nearshore_product.py --suite build --output OUTPUT

Baseline is a historical pre-edit run, not a final-HEAD green command. Every invocation creates a unique timestamp/UUID child, retains stdout/stderr and hashes, literal argv/cwd/interpreters, registered test names/counts/exits, spec/source/test/fixture hashes and actual HEAD/status. The source manifest supplies the exact credential-scan interpreter; no fallback interpreter or install is permitted. Typecheck invokes each of the three project configs separately. Build invokes existing pnpm build only, never deploy. Inputs are hashed before and after; unexpected mutation fails acceptance. Final receipts must be run at the signed-off exact HEAD, then frozen outside the repository; reviewer reruns use separate output roots and do not reseal author evidence.

Node bootstrap installs process-local network and browser-storage sentinels before any product import, including defaults. The new tests also install before dynamic import and around each case, restoring globals afterward. These guards are defense-in-depth for trusted pure modules, not a hostile-code sandbox or a general filesystem restriction. Complete original tests use their own injected offline fakes. Ordinary Node discovery of the new test remains supported without the launcher and restores its globals; baseline registration is selected only by the launcher's explicit SP1402_TEST_SUITE=baseline environment delta.

## Review and retained obligations

Actual author: gpt-6.1-sol / openai-codex, sol-reviewer task t_70c9b868 run 1815. Material commits carry model/provider trailers and sign-off. Sole independent reviewer: Claude Opus 5.5 on opus-coder-bopus. Scoped passes require independent review, not semantic or whole-repository release acceptance.

The operator still owes PR publication, unchanged complete Node/Python/GIS suites with strict skips, parity/rebuilds, privacy/link/public-tree checks as applicable, web/client/copy/token checks, dependency audit, browser/e2e, and exact-head required CI. No worker push/merge, network/source acquisition, live action, deployment, legal/scientific/navigation/safe-water/fish-presence conclusion or hold release is authorized. SC#1/PR846, SC-5b, terrain-mask, public-viewer, legal-preview, source/live and bulk-download holds remain. DeFlock public-tree checks do not apply to this non-DeFlock delta.
