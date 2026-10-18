# B02 focused browser acceptance

[sc-b02-region-identity.mjs](sc-b02-region-identity.mjs) is the isolated B02 browser acceptance harness. It uses Node's test runner to drive Playwright against bundled real app source with synthetic responses and GPU-free renderer handles.

Run from the repository root on the separately qualified hosted Chromium route:

```sh
node --test --test-concurrency=1 --test-force-exit e2e/sc-b02-region-identity.mjs
```

This browser harness belongs beside the browser tests. It is outside the Node-only `tests/test_*.mjs` matrix and is not a Playwright `.spec.ts` file collected by `pnpm e2e`. Moving it does not turn its assertions into optional checks: the bounded B02 hosted acceptance is a required separate release gate. There is no skip-on-missing-browser fallback.

Keep all 18 serial scenarios (nine each at 390x844 and 1280x800), the seven desktop disclosures, the ordinary Reset click, the retry-revisit, explicit plan-loader and real aerial-callback assertions. Stop at the first failing scenario. Success requires no skipped scenarios and exactly 18 new root identity JSON snapshots under `../sc-b02-evidence/`; disclosure/control JSON and screenshots stay in their nested directories.

The retained `sc-b02-focused` job runs only for its explicit dispatch input on `codex/sc-b02-focused-ci`. Before dispatch, its owner must bind this composition's exact base, source head/tree, full patch hash and relocated fixture hash in a newly reviewed immutable delivery. Preserve its qualified hosted runner and pinned dependency/browser route, one-attempt guard, source scans, exit handling and evidence upload. An old delivery's pins do not cover this source.

Browser/runtime qualification, the remaining B02 attempt budget and actual final source/delivery review are prerequisites. This fixture must never be launched as a way to discover or repair an unsupported local browser environment. Normal required CI and deployment verification remain separate gates.
