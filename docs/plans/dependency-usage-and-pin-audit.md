# Dependency usage and pin audit

## R1. Direct dependencies and where they are used

| Package | Kind | Exact pin | Root lock resolution | Matching files | Bundle or other use (source evidence) |
| --- | --- | --- | --- | ---: | --- |
| `@block65/webcrypto-web-push` | Runtime | `2.0.0` | `2.0.0` (`pnpm-lock.yaml:14–16`) | 1 | Worker: `server/index.ts:7`, `server/trips.ts:3`. |
| `@preact/signals` | Runtime | `2.11.4` | `2.11.4(preact@11.2.0)` (`:17–19`) | 135 | Client and Worker: `web/i18n-core.ts:7`; Worker chain below. |
| `@simplewebauthn/server` | Runtime | `14.1.0` | `14.1.0` (`:20–22`) | 1 | Worker: `server/app.ts:28` → `server/routes/auth.ts:4` → `server/auth.ts:5`. |
| `drizzle-orm` | Runtime | `0.45.4` | `0.45.4(@cloudflare/workers-types@5.20261114.1)` (`:23–25`) | 1 | Tooling and tests, not Worker or client: `db/schema.ts:1`, `package.json:14`, `tests/test_d1_restore_runbook.mjs:135`. |
| `hono` | Runtime | `4.13.18` | `4.13.18` (`:26–28`) | 39 | Worker: `server/index.ts:2`, `server/app.ts:10`. |
| `maplibre-gl` | Runtime | `6.18.0` | `6.18.0` (`:29–31`) | 27 | Client: `web/app/boot.ts:23`, `web/map/maplibre.js:9–11` (includes its browser worker, not the Cloudflare Worker), `vite.config.mjs:30–34`. |
| `pmtiles` | Runtime | `4.5.0` | `4.5.0` (`:32–34`) | 8 | Client: `web/map/maplibre.js:14`, `web/map/bottom-relief.ts:4`, `vite.config.mjs:30–34`. |
| `preact` | Runtime | `11.2.0` | `11.2.0(preact-render-to-string@6.8.3)` (`:35–37`) | 249 | Client: `web/app/main.tsx:9`, `vite.config.mjs:206–207`. Worker: reached indirectly via signals (`pnpm-lock.yaml:1584–1587`; see below). |
| `three` | Runtime | `0.187.0` | `0.187.0` (`:41–43`) | 11 | Client: deferred terrain, `web/map/stage.ts:166` → `web/map/terrain.js:13` → `packages/coast/src/embed.ts:6` → `packages/coast/src/coast3d/viewer.ts:5–8`. |
| `suncalc` | Runtime | `2.1.4` | `2.1.4` (`:38–40`) | 3 | Client: `web/landing/main.tsx:90` → `web/landing/live-verdict.ts:13` → `packages/coast/src/daily.ts:1`; also `web/trip-times.ts:4`. |
| `@axe-core/playwright` | Dev | `4.14.0` | `4.14.0(playwright-core@1.65.1)` (`:45–47`) | 5 | Tests only: `e2e/fixtures.ts:7`, `e2e/wcag-static.spec.ts:6`. |
| `@cloudflare/workers-types` | Dev | `5.20261114.1` | `5.20261114.1` (`:48–50`) | 0 | Tooling only: Worker type declarations in `tsconfig.json:11`; also the ORM's locked peer. |
| `@playwright/test` | Dev | `1.65.1` | `1.65.1` (`:51–53`) | 64 | Tests and tooling: `playwright.config.ts:11`, `package.json:15`, `scripts/measure_startup.mjs:224`, `scripts/relief/qa_shots.mjs:9`, `scripts/showcase_capture.mjs:24`. |
| `drizzle-kit` | Dev | `0.31.11` | `0.31.11` (`:60–62`) | 0 | Tooling only: migration generator CLI (`package.json:14`). |
| `esbuild` | Dev | `0.28.2` | `0.28.2` (`:63–65`) | 208 | Tooling and tests: builds the Worker and the client's theme boot script, but is not itself shipped (`scripts/build-worker.mjs:1,33–34`, `vite.config.mjs:17,169–175`, `e2e/coast-markup.spec.ts:8`). |
| `preact-render-to-string` | Dev | `6.8.3` | `6.8.3(preact@11.2.0)` (`:66–68`) | 152 | Direct imports only in tests (`tests/test_alerts.mjs:25`); see Preact's optional lock edge below. |
| `typescript` | Dev | `7.0.2` | `7.0.2` (`:69–71`) | 0 | Tooling only: `tsc` CLI (`package.json:12`). |
| `vite` | Dev | `8.3.8` | `8.3.8(esbuild@0.28.2)(tsx@4.23.15)` (`:72–74`) | 1 | Tooling only: client builder (`scripts/client-build.mjs:24,199`, `vite.config.mjs:18`); also `vite/client` declarations (`packages/coast/tsconfig.json:10–12`). |
| `@types/three` | Dev | `0.187.0` | `0.187.0` (`:57–59`) | 0 | Tooling only: TypeScript declarations for `three` imports (`package.json:12,38`, `packages/coast/src/coast3d/viewer.ts:5–8`). |
| `@types/suncalc` | Dev | `1.9.2` | `1.9.2` (`:54–56`) | 0 | Tooling only: TypeScript declarations for `suncalc` imports (`package.json:12,39`, `web/trip-times.ts:4`). |

**Snapshot:** staged `origin/main` at `9e078e2bd4c2db659e0f6e175c33cd6b0fd18553`, read offline on 2026-11-21. The manifest has **10 runtime + 10 dev** entries, all exact (no ranges), not 11 runtime entries (`package.json:17–40`). Every root lock resolution matches its declared version; parentheses record resolved peers, not version ranges (`pnpm-lock.yaml:12–74`). Short `:line` references in the lock column refer to that same file.

**Count:** From the repository root at that SHA, substitute the table's package name for `<name>`:

```sh
git grep -lE "from '<name>" -- server web packages scripts tests e2e | wc -l
```

This counts **matching files**, not import statements or shipped modules. It includes single-quoted subpaths, re-exports and type-only references; it misses double quotes, bare side-effect imports, `import()` and `require()`. The prefix `preact` also matches `preact-render-to-string`; with a package boundary (`git grep -lE "from 'preact(/|')" -- server web packages scripts tests e2e | wc -l`), Preact still has **249** files because every matching renderer file also matches Preact itself. The specified command gives 249 and 152 respectively at this SHA, one higher each than the task's seed counts. `db/`, authored `dist/` files and root configs were checked for additional usage but are not in the count.

**Bundle attribution is a source trace, not a byte audit.** `scripts/build-worker.mjs:20,33–34` runs the client build and separately bundles `server/index.ts`. Vite uses top-level `dist/*.html` inputs (`scripts/client-build.mjs:195–201`, `vite.config.mjs:20–21,222–225`); for example `dist/app.html:49` starts the app. The Worker reaches signals even though no `server/` file imports them directly: `server/index.ts:2` → `server/app.ts:23` → `server/routes/coast-pages.ts:4` → `server/coast-pages.ts:3` → `web/fish-links.ts:3` → `web/profile.ts:10`. The lock links signals to Preact (`pnpm-lock.yaml:1584–1587`) and lists the renderer as an optional Preact dependency (`pnpm-lock.yaml:1952–1958`); the latter alone is not proof the renderer ships. No build, install or package resolution was run for this audit.

## R2. No imports, test-only imports and undeclared imports

- **No package imports found:** the three declaration packages (`@cloudflare/workers-types`, `@types/three`, `@types/suncalc`) and the two CLI packages (`drizzle-kit`, `typescript`). All have tooling uses shown above; zero is not evidence they can be removed.
- **Direct imports only in tests:** `@axe-core/playwright` and `preact-render-to-string`. The ORM's lone counted match is in tests, but `db/schema.ts:1` uses it in the migration generator. `@playwright/test` also drives browser tooling outside the test runner. To see the non-`from` calls, run `git grep -nE '(import|require)\(' -- scripts tests e2e` and filter by package name.
- **One undeclared bare package import found** in authored JS/TS/HTML/CSS across the six count roots, `db/`, authored `dist/` inputs and the Vite and Playwright configs: `tests/test_habitat_context.mjs:12` calls `require('@maplibre/maplibre-gl-style-spec')`. The lock resolves it to `26.7.0` via `maplibre-gl` (`pnpm-lock.yaml:451–453,1897–1904`); no root direct declaration guarantees the test's ability to resolve it. This is a test-only **direct use**; it does not imply MapLibre's own dependencies are test-only. The scan covered literal static imports/re-exports, side-effect imports, dynamic imports, `require()` and CSS imports; it does not resolve computed specifiers or inspect third-party vendored bodies. Vendored assets are handled separately from npm imports (`vite.config.mjs:10–14,85–90`).
- **`packages/coast` is local source**, not an undeclared npm package. `git ls-files '*package.json'` prints only `package.json`; the lock has only the root importer (`pnpm-lock.yaml:10–76`), and the workspace file only allows esbuild's build step (`pnpm-workspace.yaml:1–2`). The Worker and client use relative imports (`server/coast-pages.ts:4–8`, `web/map/terrain.js:9–13`). Coast's own bare imports (`packages/coast/src/daily.ts:1`, `packages/coast/src/coast3d/viewer.ts:5–8`, `packages/coast/src/coast3d/mvp.ts:1`) resolve through the root declarations for SunCalc, Three and MapLibre.

## R3. The one override still affects Drizzle Kit

`package.json:41–45` and `pnpm-lock.yaml:7–8` force one edge: root dev dependency `drizzle-kit@0.31.11` → `@esbuild-kit/esm-loader@2.6.5` → `@esbuild-kit/core-utils@3.3.2` → `esbuild@0.25.12` (`pnpm-lock.yaml:60–62,1246–1254,1756–1761`). Drizzle Kit's *own* direct esbuild edge already resolves to `0.25.12`; the root build tool remains `0.28.2` (`pnpm-lock.yaml:63–65,1756–1761`). The override does not apply globally.

**Removing it is not a no-op.** Removing it from the manifest doesn't itself rewrite the checked-in lock. On re-resolution, the old loader would no longer be forced to use `0.25.12` at that edge. The same path was locked to `0.18.20` just before the override: `git show -U3 4411db47e -- package.json pnpm-lock.yaml` (2026-11-18, “Fix the Drizzle Kit dev-only esbuild advisory”) shows `- esbuild: 0.18.20` and `+ esbuild: 0.25.12` under `@esbuild-kit/core-utils@3.3.2`. That is evidence for a change on removing the pin, not a fresh registry prediction. The loader is still present at this SHA, so the override still serves its original purpose. No manifest or lockfile was edited to test removal.

## R4. Follow-up

No buildable unit is needed to complete this audit. The current override is active (R3); the undeclared test import is recorded for the dependency owner (R2). No change to dependencies, tests or policy is made here.
