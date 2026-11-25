# Fixed dates that will break tests

| First failure (UTC) | First failure (Pacific) | What to prioritize |
| --- | --- | --- |
| 2027-01-01 00:00:00 | 2026-12-31 16:00:00 PST | Wide reef restoration, plus the known sibling-owned 3D embed cases. Land the restoration test fix before New Year's Eve (R1–R2). |
| 2027-02-01 00:00:00 | 2027-01-31 16:00:00 PST | More reef and shore restoration cases; fix them in the same test-file change (R1–R2). |
| 2098-12-31 through 2999-01-01 | See inventory | Far-future sentinels still depend on the wall clock. They are not 2027 blockers. |

## R1. Method and inventory

Source and line numbers: `e2cfc500163c0551cda4458f738e68cec04af6b3`. A read-only GET of `https://api.github.com/repos/Grahammmm/skippercast/commits/main` with `Accept: application/vnd.github.sha` on 2026-11-21 returned that SHA. The cited anchors were unchanged from the task baseline (`git diff d52008bfba3a55529a4965c23243cf487838ffad HEAD -- dist/coasts.js packages/coast/src/coast3d/regional.ts tests/coast/coast-embedded.test.ts scripts/check_test_determinism.py`).

```sh
 git grep -nE '20(2[6-9]|[3-9][0-9])-[01][0-9]-[0-3][0-9]' -- tests research/tests
 git grep -nE '(2999|9999)-[01][0-9]-[0-3][0-9]|(Date\.UTC|new Date|datetime|date)\(20[2-9][0-9][[:space:]]*,' -- tests research/tests
 git grep -nE 'Date\.now|new Date\(\)|datetime\.(now|utcnow|today)|date\.today|time\.time' -- dist packages/coast web server scripts src research/scripts
 git grep -nE 'coast-embedded\.test|coast-habitat-event\.test|_coastal_catalog_fixture' -- tests
```

Follow date inputs, shared fixture imports and defaults to the deciding comparison, then check whether a committed assertion changes. A fixed date used for formatting, a requested trip day, or a deliberately supplied test clock is not itself a deadline. Rows group cases sharing a fixture and threshold; assertion lines identify the first red checks, not downstream assertions that become unreachable. Pacific means `America/Los_Angeles` (future conversions use current zone rules).

**CI key:** **N** = direct top-level Node entry via the `tests/test_*.mjs` glob (`.github/workflows/ci.yml:432–440`); **N1/N12** = that same glob via `tests/test_coast_renderer.mjs:1/12`. **P** = pytest discovery (`pyproject.toml:78–86`), non-GIS check (`.github/workflows/ci.yml:357–359`) and survey `rest` when selected (`:128–155`). **G** = pytest discovery in survey CI (`:95–105,128–155`). These are PR CI entry points, not promises that every PR runs all tiers: see `.github/workflows/ci.yml:42,95,315,358,433` for the draft and changed-area gates.

| Committed test, fixture and first red assertions | Fixed input | Wall clock and comparison | First failure UTC → Pacific | PR CI |
| --- | --- | --- | --- | --- |
| `tests/test_coast_habitat_selection.mjs:35,38` (wide reef) | `2027-01-01T00:00:00Z` | Wide-context binding at `packages/coast/src/state/habitat-selection.ts:39–49` calls the default clock in `packages/coast/src/coast3d/regional.ts:38–39`; receipt also checks `:18` in the selection module. Both reject equality. | 2027-01-01 00:00:00 → 2026-12-31 16:00:00 PST | N |
| `tests/coast/coast-embedded.test.ts:119–120,130–131` (known, sibling-owned) | `2027-01-01T00:00:00Z` | `packages/coast/src/coast3d/viewer.ts:278,330–332`: receipt expires when remaining time is zero. | 2027-01-01 00:00:00 → 2026-12-31 16:00:00 PST | N1 |
| `tests/test_coast_habitat_selection.mjs:4–6,10` (curated reef) | Earliest of `2027-02-01`, `2027-03-01`, `2027-04-01` at 00:00 UTC | `packages/coast/src/map/habitat-lifecycle.ts:19–25,35–36,46–50`; final receipt takes the minimum in `packages/coast/src/state/habitat-selection.ts:49`. | 2027-02-01 00:00:00 → 2027-01-31 16:00:00 PST | N |
| `tests/test_coast_habitat_selection.mjs:4,24,27,45,48` (two shore positives) | `2027-02-01T00:00:00Z` | `packages/coast/src/state/habitat-selection.ts:18,33–34`: filters out the dated run at equality. | 2027-02-01 00:00:00 → 2027-01-31 16:00:00 PST | N |
| `tests/coast/coast-embedded.test.ts:156–158` (known, sibling-owned) | Earliest of `2027-02-01`, `2027-03-01`, `2027-04-01` at 00:00 UTC | `packages/coast/src/coast3d/viewer.ts:278,330–332`: earliest expiry clears receipt immediately. | 2027-02-01 00:00:00 → 2027-01-31 16:00:00 PST | N1 |
| `tests/test_skill_scorecard.mjs:106,118` | `2099-01-01T00:00:00Z` | `dist/skill-page.js:11,28–35,74`: stops being “future” **10 minutes before** the stamp. | 2098-12-31 23:50:00 → 2098-12-31 15:50:00 PST | N |
| `tests/coast/coast-habitat-event.test.ts:15,19,30–50,57–62,76–105` | `2099-01-01T00:00:00Z` | `packages/coast/src/coast3d/viewer.ts:255` omits `now`; `packages/coast/src/coast3d/regional.ts:41–42` drops expired reef ranks. | 2099-01-01 00:00:00 → 2098-12-31 16:00:00 PST | N12 |
| `tests/test_coast_data.mjs:126,131,197,204,335–338` | `2099-01-01T00:00:00Z` | `server/coast-data.ts:153,306` changes asset replies to 503; `packages/coast/src/map/habitat-lifecycle.ts:19–25,35–36` throws before the test's intended retired-source refusal. | 2099-01-01 00:00:00 → 2098-12-31 16:00:00 PST | N |
| `tests/test_trip_i18n.mjs:72,86` | `2099-01-01T00:00:00Z` | `web/app/Trip.tsx:180` passes `new Date()` to `web/trip-ocean-lines.ts:23–25`; “saved until” changes to “past its age limit.” | 2099-01-01 00:00:00 → 2098-12-31 16:00:00 PST | N |
| `tests/unit/test_site_uptime_alert.py:97,108`; `tests/unit/test_site_uptime_body_limit.py:18,64`; `tests/unit/test_site_uptime_json_depth.py:16,83,90` | `2099-01-01T00:00:00Z` | `scripts/site_uptime_alert.py:79–83`: embedded probe uses `datetime.now(timezone.utc)` even when the calling test passes a fixed report clock. | 2099-01-01 00:00:00 → 2098-12-31 16:00:00 PST | P (each) |
| `tests/unit/test_coastal_catalog_bridge.py:186–192` (whole UTC stamp) | `2099-01-01T00:00:00Z` | `src/skippercast/coastal/coordinator/catalog_bridge.py:402–403,430,533`: a candidate expires at equality. | 2099-01-01 00:00:00 → 2098-12-31 16:00:00 PST | P |
| `tests/test_trip.mjs:326,332` | `2099-01-01T00:00:00Z` | `web/trip.ts:31,122` captures real session start at import, before `tests/test_trip.mjs:276` fixes the save clock; `dist/offline-pack.js:73–81` keeps equality but rejects anything older. | 2099-01-01 00:00:00.001 → 2098-12-31 16:00:00.001 PST | N |
| `tests/unit/test_coastal_catalog_bridge.py:37,54–56`; `tests/unit/test_coastal_catalog_bridge_io.py:15–24,114–123`; `tests/unit/test_coastal_catalog_bridge_metadata.py:24–36,91–95`; `tests/unit/test_sc32_bridge_bounds.py:124–150,370–372`; `tests/unit/test_coastal_bridge_run.py:96,113–114,130,145`; `tests/gis/test_coastal_catalog_bridge_acquire.py:56–66,144–159` | `2099-01-01T00:00:00.870400Z` from `tests/_coastal_catalog_fixture.py:18,22` | `src/skippercast/coastal/coordinator/catalog_bridge.py:402–403,430`: omitted `now` expires the shared lead; enqueue also rechecks through `src/skippercast/coastal/coordinator/bridge_run.py:461–463`. | 2099-01-01 00:00:00.870400 → 2098-12-31 16:00:00.870400 PST | P except acquire (G) |
| `tests/test_f16_11_audit.mjs:17,34–70`; `tests/test_planner.mjs:30,95,268,294`; `tests/test_planner_order.mjs:16,52,72,91`; `tests/test_planner_route.mjs:48,75,258` | `2099-12-31T00:00:00Z` | Planner fallback `new Date()` (`web/planner.ts:214,601`); `web/ranking.ts:469–474` / `dist/seafloor-data.js:24–35` withholds stale rank input; `dist/trip-export.js:136,143–146` refuses expired ranked exports. | 2099-12-31 00:00:00 → 2099-12-30 16:00:00 PST | N (each) |
| `tests/coast/coast-embedded.test.ts:202,209–210` (known, sibling-owned) | `2999-01-01T00:00:00Z` | The test passes wall time into `packages/coast/src/shore-review.ts:15–30`; the dated sand run is no longer shown. | 2999-01-01 00:00:00 → 2998-12-31 16:00:00 PST | N1 |

**Lookalikes checked.** `tests/test_coasts.mjs:29–55` supplies `now` to the active checks; its `seasonalMarkup` case has no successful retrieval stamp and expects the unavailable copy (`dist/coasts.js:43–62,82–90`). The similarly named `tests/coast/coast-embed.test.ts:300–304` checks detail and explicit clear, not receipt survival; the unchanged file passed the January rollover replay. The sibling's other Jan 1 reef fixtures at `:37–38,53–55,102–108` also stayed green: those assertions observe callbacks or display that `selectFeature` still writes after the synchronous receipt withdrawal (`viewer.ts:278–283` in the path above). `tests/test_marks_layer.mjs:152–154,419–424` and `tests/test_mark_layer_i18n.mjs:87–88,283` check formatted receipts or inject time; both passed after their Jan 2 literal. `tests/test_f15_12_audit.mjs:35–46` and `tests/test_depth_contours.mjs:394–409,496–497` drive explicit review dates. `tests/test_advisor_rules.mjs:138–163` and `tests/test_advisor_pages.mjs:143–180` use fixed reference dates or the test's Worker clock, not the future due dates as timers. Python controls include `tests/unit/test_sca_051.py:40–72` (compares copied bytes), `tests/unit/test_coast_assets.py:176–188` (passes `NOW`), `tests/unit/test_maplayer_sst.py:84–90` (passes a comparison date) and `tests/contract/test_shore_habitat.py:153–167` (input-stamp preservation).

## R2. Offline replay of the earliest five failing cases

Scratch driver: `python3 replay.py <UTC-instant> <test-path> ...` from the task workspace, with Node 22 and the locked dependencies installed offline. It runs `node --import <scratch>/clock.mjs --test <test-path>` in the clone. The preload fixes `Date.now()` and no-argument `new Date()`, preserves explicit construction/parsing and refuses unstubbed `fetch`. Each file runs in a fresh process. The two files below passed at `2026-12-31T23:59:59.999Z`. At `2027-01-31T23:59:59.999Z` only the January cases were red; at February equality the new failures appeared. Both runs 1 ms after the cutoff returned Node exit 1, with these failures:

| Clock argument | Test path argument | Observed failure |
| --- | --- | --- |
| `2027-01-01T00:00:00.001Z` | `tests/test_coast_habitat_selection.mjs` | `:38` — reading `latitude` of null, in the wide reef case registered at `:33`. |
| Same | `tests/coast/coast-embedded.test.ts` | `:120` — receipt immediately invalidates once; expected zero invalidations. |
| Same | `tests/coast/coast-embedded.test.ts` | `:131` — first positive reef selection already invalidates; expected zero. |
| `2027-02-01T00:00:00.001Z` | `tests/test_coast_habitat_selection.mjs` | `:10` — got null instead of the exact curated reef receipt. |
| Same | `tests/test_coast_habitat_selection.mjs` | `:27` — got null instead of the source-bound shore receipt. |

Same February run also failed `tests/test_coast_habitat_selection.mjs:48` (reading `kind` of null) and `tests/coast/coast-embedded.test.ts:158` (reading `expires` of null). The same preload reproduced the late JavaScript rows; for example, the scorecard passes at `2098-12-31T23:49:59.999Z` and fails at `23:50:00.000Z`, and `test_trip.mjs` passes at exact equality before failing 1 ms later. The scratch Python driver `py-clock.py <UTC-instant> <pytest-path-or-node-id> ...` patches the `datetime` binding in `scripts.site_uptime_alert` and `skippercast.coastal.coordinator.catalog_bridge` only, then runs unchanged pytest cases inside an offline namespace (loopback allowed). At `2099-01-01T00:00:00.870401Z` it reproduced all the Python file rows, including the synthetic GIS acquire case (`:66`, expected one selected lead, got none).

## R3. What the existing lint catches

`scripts/check_test_determinism.py:31–51,53–64,141–166` looks for direct Python wall-clock calls, hard-coded ports and unguarded interpreter-version assertions. It recognizes file-level freezing evidence (including recognized clock patch targets), permits a reasoned pragma and does not match monotonic duration clocks (`:4–19,118–158`). Only changed matching lines fail PR mode (`:187–200,204–238`; `.github/workflows/ci.yml:387–399`); existing matches are warnings. It walks Python files only (`:174–180`), so it never sees the Node/TS fixtures. Nor does it follow a Python fixture literal through an imported producer to the producer's wall-clock default: the calls that matter are in `scripts/site_uptime_alert.py:82` and `src/skippercast/coastal/coordinator/catalog_bridge.py:430`, not in the tests.

## R4. Smallest fixes, ranked by first failure

Use the existing `now` parameter where it controls the whole path. If the path captures its own time (including at import), freeze the test clock before that read and restore it afterward. When the contract is simply “still in the future,” derive the stamp from the same reference clock instead of replacing it with a later calendar year. Keep intentionally stale or expired controls and their expected refusals. No production gate needs loosening.

| Rank | One follow-up per file | Land by (Pacific, before cutoff) | Estimate |
| --- | --- | --- | --- |
| 1 | `tests/test_coast_habitat_selection.mjs` — freeze the resolver's test clock for all curated, wide and shore cases. Keep the dates and earliest-expiry assertions. | 2026-12-30 | 45 min |
| 2 | `tests/test_skill_scorecard.mjs` — make the Spanish fixture's stamp relative to the same test clock, beyond the 10-minute tolerance. | 2098-12-30 | 30 min |
| 3 | `tests/coast/coast-habitat-event.test.ts` — freeze time around the viewer harness. | 2098-12-30 | 45 min |
| 4 | `tests/test_coast_data.mjs` — pass the same fixed `now` into the Worker options and habitat-head validator for the affected cases. | 2098-12-30 | 60 min |
| 5 | `tests/test_trip_i18n.mjs` — freeze the inventory-render clock or derive its drawable deadline from that clock. | 2098-12-30 | 30 min |
| 6 | `tests/unit/test_site_uptime_alert.py` — pin the probe clock for the manifest test. | 2098-12-30 | 30 min |
| 7 | `tests/unit/test_site_uptime_body_limit.py` — pin the same probe clock for the exact-cap case. | 2098-12-30 | 30 min |
| 8 | `tests/unit/test_site_uptime_json_depth.py` — tie the probe clock to the existing `NOW`. | 2098-12-30 | 30 min |
| 9 | `tests/unit/test_coastal_catalog_bridge.py` — supply fixed `now` at the bridge calls, including the whole-second expiry case. | 2098-12-30 | 60 min |
| 10 | `tests/test_trip.mjs` — import the trip module under a fixed session clock, then seed the cache stamp on or after it. | 2098-12-30 | 60 min |
| 11 | `tests/unit/test_coastal_catalog_bridge_io.py` — pass `now` to fixture bridge operations. | 2098-12-30 | 30 min |
| 12 | `tests/unit/test_coastal_catalog_bridge_metadata.py` — set the test bridge clock for direct and CLI tests. | 2098-12-30 | 45 min |
| 13 | `tests/unit/test_sc32_bridge_bounds.py` — pass `now` through the test helper. | 2098-12-30 | 30 min |
| 14 | `tests/unit/test_coastal_bridge_run.py` — pin the bridge module's clock as well as the existing driver clock, so enqueue revalidation sees the same instant. | 2098-12-30 | 60 min |
| 15 | `tests/gis/test_coastal_catalog_bridge_acquire.py` — pin the bridge clock in the synthetic acquire tests, including revalidation. | 2098-12-30 | 60 min |
| 16 | `tests/test_f16_11_audit.mjs` — give both planner instances the same fixed test clock. | 2099-12-29 | 30 min |
| 17 | `tests/test_planner.mjs` — use one fixture `now` for ranking and export. | 2099-12-29 | 60 min |
| 18 | `tests/test_planner_order.mjs` — use the same fixed planner and export clock. | 2099-12-29 | 45 min |
| 19 | `tests/test_planner_route.mjs` — use a fixed reference in route ranking and export. | 2099-12-29 | 45 min |
