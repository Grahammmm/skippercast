# #422 front-end review follow-ups re-checked at main (2026-11-04)

- **Checked main:** `b7756837e85506ce3a45ff7e485c238d67824167` (builder clone, 2026-11-04). At the same time `git diff --stat b7756837… origin/main` over every path cited below was empty, so the citations also hold for the newer `origin/main` (`d6a5eeabdc9b518ba5e55806039c581b5068aaee`) the PR is merged with.
- **Issue:** https://github.com/Grahammmm/skippercast/issues/422 (OPEN, 16 unticked body bullets). Source retrieval date 2026-11-04; the issue and its comments are historical (2026-10).
- **Read-only acquisition:** `gh issue view 422 --repo Grahammmm/skippercast` and `... --comments`. Nothing was edited or closed.
- **Scope:** the 16 original body bullets, every nested or compound request counted as its own child clause.
- **What DONE means here:** current source plus (where one exists) its regression test at the cited file:line. It is a source/test reconciliation only; it does not mean deployed, native-accepted, safe or owner-approved. Merged PRs, issue comments and `docs/audit/status-index.json` flags were used as leads and were not accepted as proof.
- Ordinals are local (`P` = parent, `.n` = child). Where an existing id covers exactly one clause it is shown as `SC-FE422-body-…` in the clause column; ids are not redefined.

## Inventory

### P01 FE-07 landing (#421) — DONE (5 of 5 children done)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P01.1 (`SC-FE422-body-01`) | Readout said "for your launch" but always reads Morro Bay: name the place | DONE | `web/landing/Readout.tsx:21` renders `Latest readings · {placeLabel(...)}`; `web/landing/readings.ts:17,19` (`DEFAULT_PLACE`, `placeLabel`); `tests/test_landing.mjs:327-330` pins "Morro Bay & Avila area", no second "area", and that the strip names the place, not the launch. | The strip names the region's area; it does not claim to follow the port input. |
| P01.2 | Wind basis should say the buoy is ~50 nm out and not a harbor reading | DONE | `web/landing/readings.ts:59-66` (`fromHarbor`: "about N nm BEARING of … harbor"), `:111-114`, `:132` ("out at sea: not a harbor or launch reading"); `tests/test_landing.mjs:44,48,113`. | Distance is computed from region positions (56 nm, not the 50 nm guessed in the issue). |
| P01.3 | `build_landing_shoreline.mjs:13` cited a nonexistent test file | DONE | `scripts/build_landing_shoreline.mjs:16` now cites `tests/test_landing.mjs`, which exists and runs the check at `tests/test_landing.mjs:129-131`; also `tests/test_landing_shoreline_inputs.mjs`. | Citation is real. |
| P01.4 | Commit the 10 m extract step so the shoreline can be rebuilt | DONE (replaced) | The one-off 10 m extract was replaced by FE-10's committed importer `scripts/shoreline/import_cusp.py:1-20` (NOAA CUSP zoom-12), its output `catalog/shoreline/morro-bay.geojson`, and the generator `scripts/build_landing_shoreline.mjs` (`--check` mode, header lines 9-16); `tests/test_landing.mjs:129-131` fails when the committed `web/landing/shoreline-path.ts` differs. | Original concern (rebuildable shoreline) is kept; the importer fetches NOAA tiles, so a rebuild from the committed GeoJSON is offline, a re-import is not. |
| P01.5 | Re-check "seafloor and currents on one map" before FE-60 | DONE | Currents layer exists beside seafloor: `web/map/layers.ts:173`, `web/app/rail.ts:15`, `web/app/presets.ts:5`; line is `dist/landing.html:62`, pinned by `tests/test_landing.mjs:171`. | Claim is supported by shipped layers. |

### P02 FE-50 account menu (#420) — STILL OPEN (3 done, 1 open)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P02.1 (`SC-FE422-body-02-01`) | Escape on the open-menu trigger does nothing | DONE | `web/app/AccountMenu.tsx:76-78,99` (Escape handled on the root, trigger included); `e2e/v2-account.spec.ts:93-108`, `:110-125`. | — |
| P02.2 (`SC-FE422-body-02-02`) | Comment claims outside-click returns focus | DONE | `web/app/AccountMenu.tsx:5-7` now says outside click/focus closes "without moving focus back"; behaviour at `:53-60`. | Comment corrected. |
| P02.3 (`SC-FE422-body-02-03`) | Load the SimpleWebAuthn UMD on demand | STILL OPEN | `dist/app.html:30` loads `vendor/simplewebauthn-browser-14.0.0/index.umd.min.js` with `defer` on every page; `dist/account.js:60` reads `globalThis.SimpleWebAuthnBrowser`; `tests/test_app_shell.mjs:761` pins it as the only vendored script. | **FE-50: load the SimpleWebAuthn UMD only when the passkey dialog opens** |
| P02.4 (`SC-FE422-body-02-04`) | Menu remount on mobile layers toggle refetches `/api/session` | DONE | `web/account.ts:38-61` (`ensureSession` coalesces and reuses a settled session); `web/app/AccountMenu.tsx:49`; `tests/test_account_menu.mjs:25-39,105`. | — |

### P03 FE-55 advisor (#417) — STILL OPEN (1 done, 1 open)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P03.1 (`SC-FE422-body-03-01`) | HEAD `/chat.html` probe on every desktop v2 page view; use a server flag | STILL OPEN | `web/app/Masthead.tsx:105-107,111-114` still sends `HEAD /chat.html` once per page load via `ChatEntry`; `tests/test_app_shell.mjs:655-662` pins "one HEAD". No server-provided flag channel found. | **FE-55: replace the masthead HEAD /chat.html probe with a server-provided advisor flag** |
| P03.2 (`SC-FE422-body-03-02`) | Token lint skips `dist/advisor/*.css` | DONE | `scripts/check_tokens.mjs:33-35` (scope `dist/advisor`, `cssOnly`); `tests/test_check_tokens.mjs:157-168`. | — |

### P04 FE-73 state (#415) — DONE (2 of 2)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P04.1 | v2 always writes `presentation=chart` explicitly, never v1's `presentationURL` | DONE | `web/map/stage.ts:247` (`choosePresentation` → `withParams(... {presentation: next})`); `web/state.ts:261-266,297`. The v1-style helper `web/coast-context.ts:19` (deletes the key for chart) has no caller under `web/`. | — |
| P04.2 | Regression pin for that contract | DONE | `tests/test_coast_state_keys.mjs:52-70` (chart written explicitly, `presentationURL` key never introduced, round trip). | — |

### P05 FE-76 token bridge (#419) — DONE (3 of 3)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P05.1 | Shore outline used `gradeA` while the comment said reef outline | DONE | Shore now has its own role: `packages/coast/src/palette.ts:20,36` (`shoreLine`), used at `packages/coast/src/coast3d/viewer.ts:210`. | Role and comment no longer disagree. |
| P05.2 | Lint that every used `--coast-*` role is declared in `tokens-bridge.css` | DONE | `scripts/check_tokens.mjs:110-160` (`collectCoastRoleCoverage`, rule `coast-role-undeclared`), `:218-295` (`--coast-inventory` gate); `tests/test_check_tokens.mjs:205-221,336-351`. Note: the gate runs with an approved inventory file; `.github/workflows/ci.yml:329-331` runs the default scopes only. | Check exists and is tested. Whether CI should call `--coast-inventory` was not asked in #422. |
| P05.3 | Fix the coast baseline note text | DONE | `scripts/token-lint-coast-baseline.json` note now reads "Literals that predate the token lint … only shrinks … Never add entries"; entries list is empty. | — |

### P06 FE-72 chart style (#416) — DONE (1 of 1)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P06.1 | Record fonttools/Pillow versions in `build_glyphs.py` | DONE | `scripts/basemap/build_glyphs.py:44,62,197` prints a `versions:` line; `tests/unit/test_build_glyphs.py:45-56`. | — |

### P07 FE-83 home memory (#418) — DONE (2 of 2)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P07.1 | Cookie mode re-saved when stored profile is invalid (v1 only when absent): test it | DONE | `web/ports.ts:183-195` (`resolveHome`; an invalid stored profile counts as unset); `tests/test_ports.mjs:126-137` runs invalid / missing / valid stored profile. | Behaviour is pinned by a test; whether v2 should match v1 exactly is a product choice and not reopened here. |
| P07.2 | Choosing a port drops `place` and `habitat`: pin it | DONE | `web/ports.ts:29` (`AREA_KEYS`), `:249`; `tests/test_ports.mjs:108-115`; v1 side `tests/test_home_port.mjs:68-75`. | — |

### P08 FE-06 mobile (#362) — DONE (2 of 2)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P08.1 (`SC-FE422-body-08-01`) | First-run card overlaps the sheet handle at 320×568 | DONE | `e2e/v2-landing.spec.ts:225,260-290` (320×568 and 390×844; asserts the handle is in viewport and the profile card never covers it, `:283-286`). | e2e only; not run here. |
| P08.2 (`SC-FE422-body-08-02`) | Sheet pointercancel should snap back to the previous detent | DONE | `web/ui/Sheet.tsx:97-105` (cancel abandons the gesture and clears the transform; only a release picks a detent); `:70-78`; `e2e/v2-shell.spec.ts:187-` ("cancelled drags retain every detent"); `tests/test_sp1710_sheet_pointer_owner.mjs`. | — |

### P09 FE-77b panel.css (#477) — DONE (3 of 3)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P09.1 | `.catch-bar` gradient ended on translucent `--coast-mint-glow` | DONE | `packages/coast/panel.css:2875` now ends on `var(--coast-panel)` (opaque, `packages/coast/tokens-bridge.css:20`). | Opaque end role in use. |
| P09.2 | Mint text there was ~3.9:1 light theme | DONE | `scripts/check_contrast.mjs:248-266,444` (`checkCatchGradient`); `tests/test_contrast_rgba.mjs:213-242`; CI runs the contrast suite (`.github/workflows/ci.yml:301-302`). | Ratio was not recomputed here; the gate is the evidence. |
| P09.3 | `check_contrast.mjs` skips translucent roles | DONE | `scripts/check_contrast.mjs:79` still leaves translucent roles out of the bridge pass, but `:199-206` (`TRANSPARENT_CASES`, alpha-range requests) and `:248-` (catch gradient) cover the named case. | A general translucent-role check is not claimed. |

### P10 FE-81 overlays (#464) — STILL OPEN (0 done, 3 open)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P10.1 | Coarsening to fit triangle/segment caps is silent | STILL OPEN | `packages/coast/src/coast3d/overlays.ts:9-10,243-248` doubles `cell`/`step` to fit the caps without telling the caller; the host-facing `setOverlay` returns `void` (`packages/coast/src/embed-types.ts:134`, `packages/coast/src/coast3d/viewer.ts:289`). | **FE-81: return `{cell, step}` from the coast embed's `setOverlay`** |
| P10.2 | Return `{cell, step}` from `setOverlay` | STILL OPEN | An internal accessor `CoastOverlays.spacing(id)` exists (`overlays.ts:156-157`, tested at `tests/coast/coast-overlays.test.ts:101-112`) but is not exposed on the embed handle (`embed-types.ts`, `embed.ts:75`) and no `web/` code calls it. | Same unit as P10.1 (expose the existing spacing through the handle). |
| P10.3 | Host says so; over land a coarse fill can sink under relief | STILL OPEN — not verified | No `web/map` code discloses coarser draping, and no test asserts a coarse cell stays above land relief (`overlays.ts:171` re-drapes on relief change; vertex lift is constant). Relief behaviour needs a rendered check that was not run offline. | **FE-81: tell the host when an overlay was draped coarser, and pin coarse fill over land relief** |

### P11 FE-79 host chrome (#470) — DONE (1 of 1)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P11.1 | Committed reverse assignability check `TerrainSource` ⇄ `CoastTerrainSource` | DONE | `tests/fixtures/coast-types/terrain-source-assignability.ts:8-9` (both directions) with two `@ts-expect-error` controls `:16-19`; wired by `tests/test_terrain_source_types.mjs:20`. | — |

### P12 FE-12 time dock (#479) — STILL OPEN (4 done, 3 open)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P12.1 (`SC-FE422-body-12-01`) | `terrainHour` rebuilt the 169-hour horizon on every camera change | DONE | `web/map/stage.ts:90-95` returns a parsed `?hour=` directly; `tests/test_map_stage.mjs:109-112` pins the same hour as the dock (it does not count horizon builds). | — |
| P12.2 (`SC-FE422-body-12-02`) | `DOCK_ZONE` duplicated App's zone | DONE | No `DOCK_ZONE` remains under `web/`; `web/app/TimeDock.tsx:73` uses the shared `zone()`. | — |
| P12.3 (`SC-FE422-body-12-03`) | Dock reads App's last-render `now`; stage ticks its own clock | STILL OPEN | `web/app/Desktop.tsx:61,67` passes the render-time `now` (`= new Date()`) to `TimeDock`; the stage keeps a separate hour clock `web/map/stage.ts:280-287`. Play uses a fresh clock (`TimeDock.tsx:79-83`). | **FE-12: drive the time dock and the stage from one ticking clock** |
| P12.4a (`SC-FE422-body-12-04`, part 1) | e2e clicks the day chip through `evaluate` (skips actionability) | STILL OPEN | `e2e/v2-shell.spec.ts:107` still uses `.nth(1).evaluate(b => b.click())`. | **FE-12: click the day chip in v2-shell e2e with a real actionable click** |
| P12.4b (`SC-FE422-body-12-04`, part 2) | `v2-shell` dropped the slider value check | STILL OPEN — not verified | `e2e/v2-shell.spec.ts:109-122` asserts URL and readout text after End/Home but never `toHaveValue` on the Hour slider after the change; part 1 and 2 are one proposed unit. | Same unit as P12.4a (add the slider value assertion). |
| P12.5 (`SC-FE422-body-12-05`) | Next hour / Play stay enabled on the last hour | DONE | `web/app/TimeDock.tsx:94` (`advanceDisabled={nextHour(...) === null}`), `web/hour.ts:111-114`, `web/ui/Dock.tsx:57-58`; `tests/test_ui_icons.mjs:154-163`. | — |
| P12.6 (`SC-FE422-body-12-06`) | No unit render test for `stepOnly` | DONE | `tests/test_ui_icons.mjs:154-163` renders `stepOnly` true and false. | — |

### P13 FE-84 coast feeds (#478) — DONE (3 of 3)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P13.1 | History accepted without checking `recentWindowDays` | DONE | `server/coast-data.ts:186-188`; `tests/test_coast_data.mjs:654-658` (absent, 0, `'45'` refused). | Sampled. |
| P13.2 | 8 MB limit not re-checked after merging rows | DONE | `server/coast-data.ts:253-257` (`ownResponse`); `tests/test_coast_data.mjs:659-671`. | — |
| P13.3 | `COAST_FEEDS` has no rights gate (owner ask on #474) | DONE (code) | `server/coast-data.ts:193-208` (`FEED_SOURCES`, `refused`, `coastFeeds`); `tests/test_coast_data.mjs:459-461`. | Code refuses rights-refused or unknown sources. Whether the owner has enabled any feed is a deployment choice that was not read or verified here. |

### P14 FE-11 chart (#480) — DONE (4 of 4)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P14.1 (`SC-FE422-body-14-01`) | Dynamic-only guard for `maplibre-gl` and `pmtiles` | DONE | `scripts/check_client.mjs:157-184` (both packages, source and chunk names); `tests/test_check_client_graph.mjs:36-61` runs it for each package; dynamic-only subtrees allowed. | Sampled. |
| P14.2 (`SC-FE422-body-14-02`) | `licenses.html` lists stale MapLibre; vendored copy unused | DONE | `dist/licenses.html:36` names 6.16.0 = `package.json:23`; `scripts/check_web.py:~311-326` fails when licences and `package.json` pins differ; `dist/vendor/` holds only licence texts for MapLibre/PMTiles. | — |
| P14.3 (`SC-FE422-body-14-03`) | One failing ENC tile marks "Chart detail" unavailable until destroy | DONE | `web/map/chart.ts:198-200` (a loaded ENC tile clears the mark); `tests/test_map_layers.mjs:519-568`. | — |
| P14.4 (`SC-FE422-body-14-04`) | Precache budget disposition | DONE | `scripts/check_client.mjs:136-153` enforces raw `install` and `pack_shell` budgets from `scripts/startup-budget.json` (`precache`). | A budget exists and is enforced; the file records `pack_shell_raw_max` was raised 10% by BF-saved-spots, so the ~1.7 MB growth is bounded, not reversed. |

### P15 CI flake (fleet) — DONE (2 of 2)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P15.1 | Shared `calls.jsonl` torn-line race: lock or per-record files | DONE | `tests/unit/test_fleet_run_osint.py:8-13,64-80` (one file per record, `os.replace`); #499 (`04a2befee8`) is the historical fix. | Sampled. |
| P15.2 | Strict record reading + batch retry/resume regression | DONE | `tests/unit/test_fleet_run_osint.py:159-166` (`records` parses every file, a bad file fails), `:174-201` (`BatchTests.test_batches_run_resume_and_retry_once`). | A passing suite is not a stress guarantee. |

### P16 Plan — DONE (1 of 1)

| Clause | Original concern | Status | Current evidence | Reason / unit title |
| --- | --- | --- | --- | --- |
| P16.1 (`SC-FE422-body-16`) | FE-60 still lists dropped FE-13 as a dependency | DONE | `docs/plans/front-end/dev-plan.md:536` ("FE-13 … (not FE-13)"), `:149` (FE-13 DROPPED), `:57`. | — |

## Totals (derived from the rows above)

- Parents: **16**. DONE parents (all children done): P01, P04, P05, P06, P07, P08, P09, P11, P13, P14, P15, P16 = **12**. STILL OPEN parents: P02, P03, P10, P12 = **4**. 12 + 4 = 16; none omitted or duplicated.
- Child clauses: **45** = **37 DONE + 8 STILL OPEN** (open: P02.3, P03.1, P10.1, P10.2, P10.3, P12.3, P12.4a, P12.4b).

| Parent | Children | Done | Open |
| --- | --- | --- | --- |
| P01 | 5 | 5 | 0 |
| P02 | 4 | 3 | 1 |
| P03 | 2 | 1 | 1 |
| P04 | 2 | 2 | 0 |
| P05 | 3 | 3 | 0 |
| P06 | 1 | 1 | 0 |
| P07 | 2 | 2 | 0 |
| P08 | 2 | 2 | 0 |
| P09 | 3 | 3 | 0 |
| P10 | 3 | 0 | 3 |
| P11 | 1 | 1 | 0 |
| P12 | 7 | 4 | 3 |
| P13 | 3 | 3 | 0 |
| P14 | 4 | 4 | 0 |
| P15 | 2 | 2 | 0 |
| P16 | 1 | 1 | 0 |
| **Total** | **45** | **37** | **8** |

The parent count (16) and the child count (45) are separate figures and are not added together. P12.4 is counted as two children (4a, 4b) because the issue names two separate faults. The 8 open children collapse into **6 proposed units** below; the sampled FE-11 chart guard (P14.1), FE-84 history window (P13.1) and fleet run_osint race (P15.1) are DONE and carry no open work.

## Still-open items, one card-ready unit title each

1. **FE-50: load the SimpleWebAuthn UMD only when the passkey dialog opens** (P02.3)
2. **FE-55: replace the masthead HEAD /chat.html probe with a server-provided advisor flag** (P03.1)
3. **FE-81: return `{cell, step}` from the coast embed's `setOverlay`** (P10.1, P10.2)
4. **FE-81: tell the host when an overlay was draped coarser, and pin coarse fill over land relief** (P10.3 — not verified)
5. **FE-12: drive the time dock and the stage from one ticking clock** (P12.3)
6. **FE-12: click the day chip in v2-shell e2e with a real click and assert the Hour slider value** (P12.4a, P12.4b)

No queue ids, owners or schedules are assigned and no cards were created.

## Limitations

- Source and test reading only. No browser, e2e, tile, auth, feed or fleet call was run; the e2e citations (P02.1, P08, P12.4) are read, not executed.
- Line numbers are for `b7756837…`; they were unchanged by `origin/main` at merge time for the cited paths.
- `docs/audit/status-index.json` was read as a lead only and is untouched; its flags (e.g. stale integration-pending label for ENC) were not copied.
- #422 comments were searched for the open items (UMD, HEAD probe, `setOverlay` spacing, day-chip e2e) and contain no owner disposition for them.
- "Not verified" rows (P10.3, P12.4b) could not be settled offline from the inspected files; they are titles to obtain the missing evidence, not defects.

## Local commands and results

Recorded in the PR body (check_repository.py, the two named unit suites, `git diff --check`).

## Operator-only closing note

This report does not close #422 and does not certify the later comment work in the issue. Closing, ticking boxes or carding the units above stays with the operator. Even if every unit above is carded and finished, the 155 later comments are outside this report.
