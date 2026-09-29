# Testing

How SkipperCast is tested, how to run each layer, how to add a test or fixture, and where the layout is going. The rules for PRs are in [AGENTS.md](../../AGENTS.md); what CI runs is `.github/workflows/ci.yml` (**Offline checks**).

## Rules that apply to every test

- **Offline.** No test may reach the network. Use synthetic fixtures, fake clients (`unittest.mock.patch`, injected `fetcher`/`client_factory` arguments) or in-memory stores. A test that genuinely needs the network is marked `network` and is skipped unless `SKIPPERCAST_NETWORK=1` (none exists today). Scheduled workflows that touch the network are not tests.
- **Skip cleanly when a private local file is absent.** Some checks read gitignored data under `var/` (private survey caches, local reference grids). They use `unittest.skipUnless(path.exists(), ...)` and have a twin that checks the committed output, so CI still covers the claim. The full CI run fails on any skip whose exact reason is not in `ALLOWED_SKIPS` in `scripts/pytest_report.py`; a missing package is never an allowed reason.
- **Never lower the bar.** No deleted tests, no `continue-on-error`, no expected-fail markers to get green (guide §0). `xfail_strict` is on.
- **Generated files are checked by rebuilding.** Change the source and rebuild; CI fails when the committed output differs (see the table in [AGENTS.md](../../AGENTS.md)).
- **No path tricks.** Tests never edit `sys.path` and never compute the repository from `__file__`: import `ROOT` and `FIXTURES` from `tests/_support.py` (research tests: `research.lib.paths.ROOT`). `tests/contract/test_test_layout.py` enforces this.
- **Fast and clock-free.** The suite runs in seconds; keep new tests free of sleeps and real clocks. Code that needs the time takes it as a parameter (`now=` in most pipeline functions, `validateTrip(input, now)` in `server/trips.ts`; `clock=`/`wall_clock=` on `skippercast.http.Session` and `runs.RunManifest`; `now=` on `seafloor.publish.publish_bundle`/`build` and `platform.build.build`; `clock=` on `pipeline.intelligence.run`). Tests pass `tests._support.NOW` (a fixed aware instant) or a `FakeClock` (`clock()`, `clock.timestamp()`, `clock.advance(minutes=5)`); `test_test_layout.py` fails if a product test calls `datetime.now()`, `date.today()` or `time.time()`. CI prints the 15 slowest tests (`--durations=15`).

## Running the Python tests

Tests are `unittest.TestCase` classes run by [pytest](https://docs.pytest.org/) (pinned in the `test` extra and `requirements-test.txt`). Configuration is in `pyproject.toml` under `[tool.pytest.ini_options]`: `testpaths = ["tests", "research/tests"]`, `--strict-markers -ra`, and `pythonpath = ["."]`, which puts the repository root on `sys.path` so `tests`, `research` and product `scripts` import as packages. The `skippercast` package itself comes from `pip install -e .`.

```bash
python -m pip install -e ".[test]"                  # pytest, jsonschema, moto
python -m pytest -m "not gis"                       # what CI's check job runs (Python 3.11 and 3.13)
python -m pip install -e ".[survey,ocean,publish,test]"
SKIPPERCAST_REQUIRE_GIS=1 python -m pytest          # what the survey-science job runs: everything
python -m pytest tests/unit                         # one layer
python -m pytest -m claims                          # every claims pin
python scripts/run_core_tests.py --scope live       # the live-conditions gate
```

The classes still run under `unittest` (the research workflows use `python -m unittest research.tests.gis.test_<name>`).

## Layers

Layers are directories. `tests/conftest.py` and `research/tests/conftest.py` add the markers from the directory, so a test never declares them; `--strict-markers` rejects any other marker.

| Layer | Where | Markers | Contents | In CI |
| --- | --- | --- | --- | --- |
| Unit | `tests/unit/` | | Pure functions, parsers, HTTP policy, alert lifecycle, forecast/verification logic on inline or `tests/fixtures/` data; no committed repository data | `check` (3.11, 3.13) and `survey-science` |
| Contract | `tests/contract/` | | Checks over committed files: schemas, regions, catalogs, jurisdictions, commercial-source register, workflow action pins, receipt manifest, package extras, versions, the research boundary, this layout | `check` and `survey-science` |
| Integration | `tests/integration/` | | Pipelines run end to end on fixtures in a temporary directory: live loop, region refresh and run manifests, branch/R2 publishers, habitat publication | `check` and `survey-science` |
| GIS | `tests/gis/` | `gis` | Product code needing the pinned scientific/GIS stack (numpy, rasterio, shapely, pyproj, …): seafloor, forecast tiles, NOAA gridded feeds, region previews | `survey-science` only |
| Claims | `research/tests/` | `claims` | Pins of statements to committed research receipts and outputs, and tests of research scripts ([research/tests/README.md](../../research/tests/README.md)) | `check` and `survey-science` |
| Claims (GIS) | `research/tests/gis/` | `claims`, `gis` | The same, for research needing the survey stack | `survey-science` only |

**GIS collection rule.** Without the survey packages the modules under a `gis/` directory cannot be imported, so the conftests leave those directories out of collection (the pytest header says so). `-m "not gis"` therefore selects the same tests whether or not the packages are installed. The survey-science job sets `SKIPPERCAST_REQUIRE_GIS=1`, which turns that off: a missing package is then an import error, not a quiet omission. A module outside `gis/` must not import a survey package at module level (`test_test_layout.py` checks direct imports; the no-GIS `check` job catches indirect ones at collection).

**Live scope.** `scripts/run_core_tests.py --scope live` runs the product test modules (under `tests/`, never the claims pins) whose source matches `LIVE_CODE` (`skippercast.pipeline`, `refresh_regions`, `check_saved_trips`, `prune_habitat_tiles`, `live_loop`, `report_conditions`, `publish_branch_snapshot`) before every live cycle in `live-conditions.yml`, so an unrelated test can never stop the feed.

**CI reporting.** Each Python job writes JUnit XML (uploaded as the `pytest-core-<python>` and `pytest-survey` artifacts) and appends a per-layer table and the slowest tests to the job summary with `scripts/pytest_report.py`; the survey-science job runs it with `--strict-skips`. Coverage is not collected yet.

## Other checks

| Check | What | Where | Run locally | In CI |
| --- | --- | --- | --- | --- |
| Node | Worker routes and auth, feeds, forecast service, browser modules (planning, export, regulations, regions) | `tests/test_*.mjs` | `node --test tests/test_*.mjs`; `pnpm typecheck` | `check` job |
| Offline demo | The alert lifecycle end to end on invented assessments | `src/skippercast/__main__.py` | `PYTHONPATH=src python3 -m skippercast demo` | `check` job |
| Contract drift | Regional contracts and species search plans rebuilt from source must equal the commit | `src/skippercast/platform/build.py`, `scripts/build_search_plans.py` | `PYTHONPATH=src python3 -m skippercast.platform.build && git diff --exit-code`; `python scripts/build_search_plans.py && git diff --exit-code` (needs `requirements-survey.txt`) | `check` and `survey-science` jobs |
| Repository checks | Local Markdown links resolve; no private paths, credentials or private keys; binary files match `scripts/web-vendor-sha256.json` | `scripts/check_repository.py` | `python3 scripts/check_repository.py` | `check` job |
| Web checks | Page entry points, asset references, vendor hashes, GPX validity, canonical data copies | `scripts/check_web.py` | `python3 scripts/check_web.py` | `check` job |
| Build | Worker bundle and Vite-built site; the Vite manifest, page references, boot-chain preloads, `sw.js` and `precache.json` agree (`tests/test_client_build.mjs` builds fixtures and the real site) | `scripts/build-worker.mjs`, `scripts/check_client.mjs` | `pnpm install --frozen-lockfile && pnpm build && node scripts/check_client.mjs` | `check` job |
| Browser (E2E) | The built site under `wrangler dev` (real Worker, local D1) at 390×844 and 1280×800: map, species, forecast and meteogram with `?hour=`, regulations summary, GPX export, same-region port change without reload, offline save and reopen (service worker), passkey account (virtual authenticator); axe on each screen fails on serious or critical violations and prints the rest. Other origins are blocked; public data comes through the Worker from the repository's raw GitHub branches | `e2e/`, `playwright.config.ts`, `e2e/serve.mjs` | `pnpm build && pnpm e2e` (needs `npx playwright install chromium`, or `PW_CHROMIUM=/path/to/chrome`) | `e2e` job |

Before a PR, run the full list in [AGENTS.md → Before opening a PR](../../AGENTS.md#before-opening-a-pr).

Other `scripts/check_*.py` files are not tests: `check_feed_freshness.py` and `check_saved_trips.py` run in scheduled workflows against production, and `check_estero_review_change.py`, `check_nbs_modeling_scheme.py` and `check_point_buchon_rov_access_change.py` watch external sources for research.

Known gap: `tests/species-fit.test.mjs` does not match the CI glob `tests/test_*.mjs`, so it never runs in CI (guide P2-09 renames it; left to the Node test owner).

## Claims pins

The modules in `research/tests/` read committed research receipts (`research/receipts/`, through `research.lib.receipts.RECEIPTS`) and research outputs under `dist/data/`, and assert what they say, for example that a dated screen of Point Conception components keeps `fishing_target` and `exportable` false (`research/tests/gis/test_point_conception_4m_access.py`). These are **claims pins**: they fix a statement the app or docs make ("no Morro–Avila target passes the full chart-depth gate", "this layer is research-only") to the receipt that supports it, so a later edit cannot quietly strengthen the claim without changing the evidence and the test together.

When you change a pinned receipt, change the pin in the same PR and say in the PR's **Claims and data** section why the claim changed. A pin that fails after an unrelated change usually means a generated file was edited by hand or rebuilt from different inputs.

## Adding a test

**Python.** Add `test_<topic>.py` with `unittest.TestCase` classes to the layer it belongs to (table above); import `ROOT`/`FIXTURES` from `tests._support`. If it imports a survey package, it goes in a `gis/` directory. A test of a research script or receipt goes in `research/tests/`, named by the claim it pins. Plain `def test_*` functions are collected by pytest but not by `unittest`, so keep to `TestCase` classes. If it covers code the live job runs (see **Live scope**), it also runs before every live cycle, so keep it fast and deterministic.

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
- **Recorded provider responses** go in `tests/fixtures/<provider>-<what>.json` (today: `gefs-wave-probability.json`, read by `tests/unit/test_pipeline_intelligence.py` as `ROOT / 'tests/fixtures/gefs-wave-probability.json'`). Keep them small (trim to the fields and cells the test needs), strip anything personal or credential-like, and note the source URL and retrieval date in the test or a neighbouring comment. `check_repository.py` scans fixtures like every other file.
- **Binary fixtures** (a tiny GeoTIFF, BAG or PMTiles) must be added to `scripts/web-vendor-sha256.json` with their SHA-256, or `check_repository.py` fails with "unexpected or changed binary file requires review". Keep them to a few kilobytes; never commit downloaded surveys (see `.gitignore` and [CONTRIBUTING.md](../../CONTRIBUTING.md)).
- **HTTP in Python** is faked by patching the opener used by the module (`patch('skippercast.pipeline.collect.build_opener', ...)` in `tests/unit/test_pipeline.py`, `patch('skippercast.seafloor.fetch.urlopen', ...)` in `tests/gis/test_seafloor_adapters.py`), or by passing a fake `client_factory` to `collect.source`.

## Planned layout (guide §9)

The Python layers above follow the guide's plan inside today's tree; when the monorepo move (P1-04) lands they become `packages/pipeline/tests/{unit,contract,integration,gis}`. The rest of the plan:

| Layer | Location | Runs | Contents |
| --- | --- | --- | --- |
| Worker | `apps/worker/test`, `apps/worker/test/integration` | every PR | middleware and routes; `wrangler dev` smoke for `/api/health`, `/feeds/*`, auth and a billing webhook with recorded fixtures |
| Web unit | `apps/web` (Vitest) | every PR, < 30 s | components and browser modules |
| E2E | `apps/web/e2e` (Playwright + axe) | every PR at 390×844; nightly full matrix | the [mobile review](../archive/mobile-review.md) flows (six today; the guide plans eight), dark mode, offline pack, paywall |
| Load | `oha` against staging | before each production deploy | `/api/om`, `/feeds/*`, cache hit ratio, p95 latency |
| Visual | Storybook screenshots | every PR | < 0.5 % diff |

Still planned for Python: coverage in the CI summary, and a clock parameter for the research scripts whose freshness checks read the real clock (their tests pair it with real-clock inputs today: `test_usgs_context_pipeline`, `test_habitat_shortlist_closures`, `test_regular_bag_hard`).
