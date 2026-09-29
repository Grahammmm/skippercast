# Testing

How SkipperCast is tested today, how to run each layer, how to add a test or fixture, and where the test layout is going. The rules for PRs are in [AGENTS.md](../../AGENTS.md); what CI runs is `.github/workflows/ci.yml` (**Offline checks**).

## Rules that apply to every test

- **Offline.** No test may reach the network. Use synthetic fixtures, fake clients (`unittest.mock.patch`, injected `fetcher`/`client_factory` arguments) or in-memory stores. Scheduled workflows that do touch the network are not tests.
- **Skip cleanly when a private local file is absent.** Some checks read gitignored data under `var/` (private survey caches, local reference grids). They must use `unittest.skipUnless(path.exists(), ...)` and should have a twin that checks the committed output, so CI still covers the claim. Today 22 modules mention `var/`.
- **Never lower the bar.** No deleted tests, no `continue-on-error`, no expected-fail markers to get green (guide §0).
- **Generated files are checked by rebuilding.** Change the source and rebuild; CI fails when the committed output differs (see the table in [AGENTS.md](../../AGENTS.md)).
- **Fast.** The whole core suite runs in seconds; keep new unit tests free of sleeps and real clocks (pass `now` in, as `server/trips.ts` `validateTrip(input, now)` and most pipeline functions already allow).

## Current layers

| Layer | What | Where | Run locally | In CI |
| --- | --- | --- | --- | --- |
| Python core | Pipeline, platform compiler, forecast tiles, alert lifecycle, atlas, and the claims pins below. 221 `tests/test_*.py` modules; modules that import a scientific/GIS package are deferred automatically | `tests/test_*.py`, runner `scripts/run_core_tests.py` | `PYTHONPATH=src python3 scripts/run_core_tests.py` | `check` job, Python 3.11 and 3.13 |
| Python live scope | The subset covering the scheduled conditions pipeline, run before every live cycle so an unrelated survey test cannot stop the feed | same, selected by regex in `run_core_tests.py` | `PYTHONPATH=src python3 scripts/run_core_tests.py --scope live` | `live-conditions.yml` |
| Python full (GIS) | Everything, with the pinned native packages (rasterio, shapely, pyproj, h5py, numpy, …) | `tests/` | `pip install -r requirements-survey.txt -r requirements-test.txt`, then `PYTHONPATH=src python -m unittest discover -s tests -v` | `survey-science` job |
| Node | Worker routes and auth, feeds, forecast service, browser modules (planning, export, regulations, regions) | `tests/test_*.mjs` | `node --test tests/test_*.mjs`; `pnpm typecheck` | `check` job |
| Offline demo | The alert lifecycle end to end on invented assessments | `src/skippercast/__main__.py` | `PYTHONPATH=src python3 -m skippercast demo` | `check` job |
| Contract drift | Regional contracts and species search plans rebuilt from source must equal the commit | `src/skippercast/platform/build.py`, `scripts/build_search_plans.py` | `PYTHONPATH=src python3 -m skippercast.platform.build && git diff --exit-code`; `python scripts/build_search_plans.py && git diff --exit-code` (needs `requirements-survey.txt`) | `check` and `survey-science` jobs |
| Repository checks | Local Markdown links resolve; no private paths, credentials or private keys; binary files match `scripts/web-vendor-sha256.json` | `scripts/check_repository.py` | `python3 scripts/check_repository.py` | `check` job |
| Web checks | Page entry points, asset references, vendor hashes, GPX validity, canonical data copies | `scripts/check_web.py` | `python3 scripts/check_web.py` | `check` job |
| Build | Worker bundle and Vite-built site; the Vite manifest, page references, boot-chain preloads, `sw.js` and `precache.json` agree (`tests/test_client_build.mjs` builds fixtures and the real site) | `scripts/build-worker.mjs`, `scripts/check_client.mjs` | `pnpm install --frozen-lockfile && pnpm build && node scripts/check_client.mjs` | `check` job |

Before a PR, run the full list in [AGENTS.md → Before opening a PR](../../AGENTS.md#before-opening-a-pr). Without the GIS packages, `run_core_tests.py` prints the deferred modules and the package each needs; the `survey-science` job runs them.

Other `scripts/check_*.py` files are not tests: `check_feed_freshness.py` and `check_saved_trips.py` run in scheduled workflows against production, and `check_estero_review_change.py`, `check_nbs_modeling_scheme.py` and `check_point_buchon_rov_access_change.py` watch external sources for research.

Known gap: `tests/species-fit.test.mjs` does not match the CI glob `tests/test_*.mjs`, so it never runs in CI (guide P2-09 renames it).

## Claims pins

About 98 Python modules read committed research outputs under `dist/data/` and assert what they say, for example that a dated screen of Point Conception components keeps `fishing_target` and `exportable` false (`tests/test_point_conception_4m_access.py`). These are **claims pins**: they fix a statement the app or docs make ("no Morro–Avila target passes the full chart-depth gate", "this layer is research-only") to the receipt that supports it, so a later edit cannot quietly strengthen the claim without changing the evidence and the test together.

When you change a pinned receipt, change the pin in the same PR and say in the PR's **Claims and data** section why the claim changed. A pin that fails after an unrelated change usually means a generated file was edited by hand or rebuilt from different inputs. Many pins are named after survey ids today (`test_h11971_source_rights.py`); guide P2-09 renames them by claim and moves them to their own layer.

## Adding a test

**Python.** Add `tests/test_<topic>.py` with `unittest.TestCase` classes. `run_core_tests.py` discovers it automatically; if it imports a scientific package it is deferred to the `survey-science` job without any list to maintain. If it covers code the live job runs (anything matching `LIVE_CODE` in `run_core_tests.py`: `skippercast.pipeline`, `refresh_regions`, `check_saved_trips`, `prune_habitat_tiles`, `live_loop`, `report_conditions`), it also runs before every live cycle, so keep it fast and deterministic.

**Node.** Add `tests/test_<topic>.mjs` using `node:test` and `node:assert/strict`. To exercise Worker routes, set the build-time globals before importing the Worker, as `tests/test_private_api.mjs` does:

```js
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {default: worker} = await import('../server/index.ts');
```

The Worker is TypeScript (`server/*.ts`). Node 22.18 and later run it directly by stripping the types, so tests import the `.ts` files with no build step; `tsconfig.json` sets `erasableSyntaxOnly` so every file stays strippable (no `enum`, `namespace` or parameter properties). `pnpm typecheck` (`tsc --noEmit`, run in CI) checks the types. `server/model-api.js` stays plain JavaScript with a `.d.ts`, because the Python pipeline runs it through `scripts/model_api.mjs`.

Then call `worker.fetch(new Request(...), env)` with `env = {DB, FEEDS, IDENTITY_PROVIDER, ...}`. For D1, load `drizzle/0000_*.sql` into `node:sqlite`'s `DatabaseSync(':memory:')` behind a small `prepare/bind/first/all/run/batch` adapter (copy the one in `test_private_api.mjs`). For R2, pass an object with `async get(key)` (see `fakeBucket` in `tests/test_feeds.mjs`). For outbound HTTP, pass a `fetcher` where the module accepts one (`lookupBoat`, `verifyJobToken`) or stub `globalThis.fetch` for the test and restore it after.

## Adding a fixture

- **Small and synthetic first.** Most tests build their input inline (for example the 3×3 forecast tile in `tests/test_model_api.mjs`). Prefer that: it documents exactly which values matter.
- **Recorded provider responses** go in `tests/fixtures/<provider>-<what>.json` (today: `gefs-wave-probability.json`, read by `tests/test_pipeline_intelligence.py` as `ROOT / 'tests/fixtures/gefs-wave-probability.json'`). Keep them small (trim to the fields and cells the test needs), strip anything personal or credential-like, and note the source URL and retrieval date in the test or a neighbouring comment. `check_repository.py` scans fixtures like every other file.
- **Binary fixtures** (a tiny GeoTIFF, BAG or PMTiles) must be added to `scripts/web-vendor-sha256.json` with their SHA-256, or `check_repository.py` fails with "unexpected or changed binary file requires review". Keep them to a few kilobytes; never commit downloaded surveys (see `.gitignore` and [CONTRIBUTING.md](../../CONTRIBUTING.md)).
- **HTTP in Python** is faked by patching the opener used by the module (`patch('skippercast.pipeline.collect.build_opener', ...)` in `tests/test_pipeline.py`, `patch('skippercast.seafloor.fetch.urlopen', ...)` in `tests/test_seafloor_adapters.py`), or by passing a fake `client_factory` to `collect.source`.

## Planned layout (guide §9)

Not in place yet; the guide's P2-09, P3-06 and P4-09 tasks move toward it. Open PRs already add parts: #45 ([P3-06], `tests/test_worker_http.mjs`, Worker routes over HTTP), #40 ([P2-07], a ruff lint gate), #31 ([P1-03], `tests/test_packaging.py`), #33 ([P0-10], `tests/test_commercial_sources.py`, the first contract test for commercial use).

| Layer | Location | Runs | Contents |
| --- | --- | --- | --- |
| Unit | `packages/pipeline/tests/unit`, `apps/worker/test`, `apps/web` (Vitest) | every PR, < 30 s | pure functions, parsers, models, middleware, components |
| Contract | `packages/pipeline/tests/contract` | every PR | every region, jurisdiction and catalog file validates against its schema; every bound asset has `commercial_ok: true`; receipt manifest hashes match; no `-vN` filenames; no raw hex colours outside tokens |
| Claims | `research/tests` | every PR (fast) | "receipt X says Y" pins, named by claim |
| GIS | `packages/pipeline/tests/gis` (`pytest -m gis`) | survey job, all packages installed, zero skips | rasters, grids, seafloor |
| Integration | `packages/pipeline/tests/integration`, `apps/worker/test/integration` | every PR | pipeline on synthetic fixtures in a temporary directory; `wrangler dev` smoke for `/api/health`, `/feeds/*`, auth and a billing webhook with recorded fixtures |
| E2E | `apps/web/e2e` (Playwright + axe) | every PR at 390×844; nightly full matrix | the [mobile review](../archive/mobile-review.md) flows (six today; the guide plans eight), dark mode, offline pack, paywall |
| Load | `oha` against staging | before each production deploy | `/api/om`, `/feeds/*`, cache hit ratio, p95 latency |
| Visual | Storybook screenshots | every PR | < 0.5 % diff |

Planned rules: an injectable clock everywhere; no `sys.path` edits; one fixtures helper; every `var/`-gated test has a committed-output twin; JUnit and coverage in the CI summary; `--durations=10` to keep the suite fast.
