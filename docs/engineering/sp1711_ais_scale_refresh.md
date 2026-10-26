# SP1711 commercial AIS displayed-cell heat scaling

Spec: SP-17-v1. Scope: offline candidate, review required.
Base: `8a805820c30895f5f037e26af9079fd3dc015b0f`.
Material author: actual `gpt-6.1-sol` high / `openai-codex`, profile
`sol-reviewer`, task `t_b3668c02`, run 2100. Independent same-card reviewer:
actual Claude Opus 5.5 on `opus-coder-bopus`; this note is not that review.

## Defect and repair

`createCommercialAis` previously updated the GeoJSON source on the same engine
without updating the installed fill-opacity expression. When screening removes
the 20-hour cell from a two-cell 2/20-hour collection, the remaining 2-hour cell
therefore still uses a denominator of 20.

The shared `heatMaximum` calculation preserves the existing minimum denominator
of one hour. The render effect remembers the installed maximum. On a same-engine
maximum change, it removes and reinstalls only the commercial AIS overlay with
the current data, palette and insertion order, then updates its source. A repeated
`setOverlay` without removal is insufficient: the existing engine intentionally
retains styles for layer IDs already installed. Unchanged maxima use data-only
updates. First draw, empty/nonempty transitions and engine replacement still
install the current scale. The engine interface and all other products remain
unchanged.

Layer IDs, fill-opacity endpoints, line width, attribution, screened-cell eligibility
and aggregate-only source properties remain unchanged. Nothing adds charter-vessel
feeds, identities, thresholds, counters or data production. Existing destroy
behavior is retained: effects are disposed and state reset; overlay teardown and
cleanup of previously replaced engines are not new promises of this patch.

## Frozen tests and synthetic inputs

The new test, runner and fixture were authored and exercised before product edits,
then signed off in the test-first commit. No planner source slice, home path or
operator input bundle is a runtime dependency. `cells.json` mirrors the complete
`AisCollection` / `AisProps` producer shape from the real module, using explicitly
synthetic polygons, dates, aggregate labels and an invalid-domain source URL.
There are no real fleet/coastal records in the new fixture.

The test imports the complete production `createCommercialAis`, real signals,
screen geometry functions and `createEngine`. Only the MapLibre surface, engine
signal and injected feed/page/palette are deterministic doubles. The real engine
therefore enforces its retain-existing-ID semantics and deferred style behavior;
the test does not copy the heat algorithm. Network, model-transport and browser
live-store sentinels precede dynamic product imports, and mocks/globals are
restored at process teardown. The feed double accepts only the synthetic asset
URL. Synthetic payload changes occur only in its owned in-memory object, followed
by real screen signal invalidation.

Claim-to-test map (eight tests, zero skips expected):

- Healthy control: initial 2/20 cells, matching installed denominator 20.
- A1 primary regression: same-engine screen removes maximum; denominator becomes 2,
  with no toggle, replacement engine or new request.
- A2 growth/removal/unchanged maximum: repeated screen transitions keep the installed
  expression and current source aligned.
- A2 empty/nonempty: checking/stale screens remove overlay; zero and half-hour
  synthetic inputs retain the floor of one.
- A2 engine replacement: null interval and direct replacement install current data.
- A2 pending style load: latest reduced data and scale install together.
- A3 exclusions/order/off: anchor and geometry intersection exclusions, both
  option and master off toggles, palette, attribution and unrelated layer survival.
- A4 aggregate/destroy: only aggregate `id`/`hours` source properties; no charter
  feed request; pick behavior and existing post-destroy effect disposal.

## Acceptance and evidence

From this repository, run each phase separately, with an output root outside the
repository and fixtures:

    python3 scripts/accept_sp1711_ais_scale_refresh.py --phase baseline --output ../out/author-baseline
    python3 scripts/accept_sp1711_ais_scale_refresh.py --phase focused --output ../out/author-focused
    python3 scripts/accept_sp1711_ais_scale_refresh.py --phase regression --output ../out/author-regression
    python3 scripts/accept_sp1711_ais_scale_refresh.py --phase repository --output ../out/author-repository
    python3 scripts/accept_sp1711_ais_scale_refresh.py --phase typecheck --output ../out/author-typecheck
    python3 scripts/accept_sp1711_ais_scale_refresh.py --phase build --output ../out/author-build

Baseline is historical only and requires the unchanged pinned product bytes.
It runs the exact primary/control selectors separately. The known-red primary
must exit 1 for `SP1711_SCALE_MISMATCH`, `ERR_ASSERTION`, expected 2, actual 20;
the control must pass. The initial recorded run satisfied both with one test each
and zero skips. Initial red stdout SHA256:
`1c2e252d9b3cd2d03c571d519cc0fe139bef0e907e5787b51db1ff1e1bbc7bd7`.
Control stdout SHA256:
`0605f7ff7c10b146eca3792f56e60f67829237128dec10725b1096ecc33faff1`.
Do not rerun baseline on the repaired source or reseal that historical evidence.
Focused reruns the identical frozen tests green, including both selectors.

Each invocation creates a unique child output directory with a receipt, separate
raw stdout/stderr, actual argv/cwd/status/counts, source identity before/after and
raw hashes. The runner validates the standard source manifest schema, pinned base,
card/repository identity and operator scanner interpreter. Repository scan uses
that full-suite interpreter without fallback. Original compatibility is only the
unchanged `test_fleet_public_layers.mjs` suite (six tests). Three project typechecks
are separate child commands. Build runs the existing local build, never deploy.
Final exact-head results and source/test/fixture hashes live in the candidate's
out evidence, after all writers finish, not in synthetic fixture inputs.

Passing scoped checks is review required, not full-repository CI or semantic,
scientific, legal, navigation or fish-presence acceptance. Operator PR publication,
full-repository/exact-head CI, dependency audit and browser/e2e gates remain owed.
All public-viewer, source/live/bulk-download, terrain-mask, legal-preview,
SC#1/PR846 and SC-5b holds remain intact. No publication, push, merge, deployment,
service or hold change is authorized by this candidate.
