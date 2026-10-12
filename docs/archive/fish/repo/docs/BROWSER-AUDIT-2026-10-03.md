> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/BROWSER-AUDIT-2026-10-03.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Isolated browser acceptance — 2026-10-03

Baseline: `16f832210d61ee9804bfbf6380f571475a3eebe6`.
This record supplements the rebuild acceptance document; it does not establish a production deployment or scheduled collection uptime.

## Environment and boundaries

The actual built Worker ran locally on a dedicated port, 8499, with a separate persistence directory, subscriptions disabled, and no production D1, R2 or credentials. Source files were reconstructed from the pinned GitHub tree and verified against Git blob hashes. The runtime/data snapshot contained 99 verified files before this patch. A copied isolated dependency installation supported the checks below; a fresh lockfile installation is left to CI.

The tracked 12,044,691-byte native PMTiles archive could not be retrieved through the connected text-only API. Two browser retrieval attempts timed out; neither produced verified bytes. The reviewed habitat binding also returned 503 under the unconfigured local release namespace. These sources were not replaced with synthetic successful responses or bypassed. Source-loss acceptance is verified; populated native-depth and reef rendering remain unverified.

## Interaction matrix

| Check | Actual result |
|---|---|
| Phone, 390 × 844, boat/lingcod | Briefing and timeline usable; unavailable reef/depth layers explicitly labeled |
| Phone, shore/surfperch, tomorrow | October 3 selected; Cayucos and Morro Strand guidance, nearshore samples and reference tides displayed; future water temperature explicitly not forecast |
| Phone, spear/cabezon | Visibility unverified; lower-exposure window labeled as requiring local checks |
| Forecast keyboard | ArrowRight changed 8 AM to 9 AM and corresponding conditions |
| Phone map expand/restore | Daily briefing restored and map controls remained available |
| Phone conditions | Selected-hour variables, independently scaled charts and reference-tide caveats displayed |
| Phone history | Station changed from Diablo Canyon to Cape San Martin; Wave height and 7-day selection changed charts, units and coverage counts |
| Desktop, 1280 × 800 | History and coast/shore/spear workflow rendered; no horizontal page overflow |
| Shore detail dialog | Cayucos details opened; Escape closed dialog and restored initiating-button focus |
| Keyboard focus indicator | Forecast slider had a visible solid outline |
| Motion control | Explicit toggle changed to Motion off; OS-level reduced-motion emulation and frame/performance measurements were not performed |
| Page width | Phone client/scroll width both 390; desktop both 1280 |

Historical means were labeled historical, not current; unavailable values and gaps remained distinct from zero. These checks do not establish source accuracy, fish presence, navigation clearance or complete screen-reader conformance.

## Defect and repair

In History, activating the former `#daily-brief` skip link focused the page body while its target was hidden. The link now targets the persistent visible `main-content` element with `tabindex="-1"`, so it also works when Conditions or an expanded map replaces the daily briefing. In the rebuilt actual Worker, Enter focused `main-content`, which had visible client rectangles at the phone viewport. A rendering regression checks the shared destination across all three fishing methods.

Validation: nine experience tests passed, both TypeScript checks passed, and the Worker/client build passed. Full repository CI is required before merge. Screenshots are retained in the isolated portfolio remediation evidence directory (`fish-mobile-conditions.jpg`, `fish-mobile-history-keyboard-fixed.jpg`, `fish-desktop-coast.jpg`), rather than presented as deployed screenshots.

## Remaining acceptance

1. Retrieve the original native PMTiles archive and use an authorized pinned habitat release to exercise populated reef/depth layers, their bounds and detail interactions.
2. Exercise OS-level reduced-motion preference, animation performance and a full assistive-technology pass.
3. Verify deployed runtime behavior separately and witness two scheduled collection receipts with intended bindings.

FSH-05 is partially addressed, not closed by this record. The blocking sources do not prevent the verified keyboard repair from shipping.

## Current-source follow-up — 2026-10-03 12:15–12:22 UTC

Reviewed source: `79125f0c333c0ba76255a9750646c2d1a2ad6478`, tree `5f2cdf6f48dc130415549f63f65aff0a028ecb8f`. All 43 product/provider TypeScript blobs match this tree. The actual Worker/client build ran on isolated localhost ports, with no production D1, R2, accounts, subscribers or publication. The earlier baseline record above remains historical.

The original native raster was subsequently rendered and decoded independently in the browser. The current follow-up exercises populated habitat using a clearly marked **synthetic** 65,536-byte PMTiles archive and curated rectangle, routed through the actual Worker proxy and MapLibre/PMTiles reader. Simulated approval, rights, depth and fit properties are fixture values, not a real survey or spatial-screen review. Two region archives repeat the same rectangle and must not be counted as independent habitat evidence.

| Additional check | Observed result |
|---|---|
| Populated habitat and details | Outline rendered; detail shows nominal 70–120ft, provenance and fit; Escape restores initiating-row focus |
| Species change | Fixture lingcod 3/3 changes to reef rockfish 2/3 |
| Depth filter | 100ft excludes the whole fixture polygon and labels the empty state; 300ft restores |
| Source withdrawal | Synthetic upstream withdrawal plus reload removes suggestions and labels the release unavailable |
| Responsive layout | Actual CSS 1280×720, 312×675 and 390×844; page scroll width equals viewport width |
| Real forecast evidence | Two read-only public-provider runs pass six contiguous required hours in each SLO area; original clocks and failed-source status retained |
| Date/hour/keyboard/playback | Tomorrow and outlook-day selection update data; hourly slider changes variables; ArrowRight advances 8AM→9AM; playback advances and stops at the last supported hour |

Two local collector invocations are **not** two deployed cron runs. The MUR route failed; the advertised Upwell metadata mirror returned200 but its grid route returned302 to the same failing CoastWatch host. No hostname-only fix or successful temperature layer is claimed. Catch-feed exclusion remains explicit. The provenance, compact source receipts, failure diagnosis and remaining gaps are recorded in `docs/acceptance/current-source-2026-10-03.json`; raw public-source outputs and screenshots are retained with the isolated audit evidence.

Remaining acceptance: actual government-only R2/Worker deployment and two intended scheduled storage receipts; OS reduced-motion preference, frame performance and full assistive technology. Application motion-toggle testing does not close those accessibility gaps. FSH-05 remains partially addressed; no new product defect was reproduced in this follow-up.
