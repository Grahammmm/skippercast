# Mobile readability review

Reviewed on September 22, 2026 in the Codex in-app browser against the local preview at `http://127.0.0.1:8485/`.

## Tested viewports and flows

The original audit verified `window.innerWidth` at **390 × 844** and **320 × 720 CSS pixels**; no browser zoom compensation was needed. Southern California / Anacapa and Morro Bay were exercised.

- Changed species, opened rules and scrolled their sources.
- Opened Map options and scrolled through its controls and layer labels.
- Advanced forecast hours, changed the model to ECMWF and opened Tides.
- Opened guide coverage and species field notes.
- Opened Morro Bay spot SC26-004, scrolled its details, and added, reviewed and removed it from the iNavX set.
- Verified 44px primary map targets, zoom buttons, layer labels and principal form/action controls. No GPX was shared or downloaded.

## Fixes in `dist/mobile-polish.css`

The stylesheet must be linked after the feature styles in `dist/index.html`.

| Observed issue | Change |
| --- | --- |
| The coverage table was 1553px wide inside a 286px guide card, clipping the Coverage and What it supports columns. | Keep the native table; give columns a fixed layout, wrap cell text and use 14px mobile table text. |
| At 320 × 720, the weather dock covered most of the final rules-source disclosure even at maximum scroll. | Bound the open rules card to the map's remaining height, scroll the whole card, keep its summary sticky and temporarily hide the weather dock while rules are open. Closing rules restores the dock. |
| The observed buoy source and time extended beneath Timeline. | Let both weather-summary lines wrap; prevent the Timeline button from shrinking. |
| The selected lobster name and fishing method were truncated at 320px. | Use a full-width species row and stack date/method fields below 360px. Keep mobile text-entry and select controls at least 16px. |

The owner linked the stylesheet last. Esbuild parsed it for Safari 15.4 and Chrome 105 with zero warnings. Post-change browser verification could not run because the in-app browser disconnected and its browser inventory remained empty; do not treat the original audit as visual verification of these fixes.

## Repeatable manual checklist

1. Load the local preview at 390 × 844, then 320 × 720. Confirm `window.innerWidth`, document width and panel width; verify no unintended horizontal page scrolling.
2. In Southern California / Anacapa, select California spiny lobster. Read the complete selected name; open Rules and confirm both date and method. Scroll to **All official sources & check status**, expand it and reach its last link. The bottom navigation and rules close control must remain reachable. Close Rules and confirm the weather dock returns with the full buoy name and time.
3. Open Timeline and change an hour. Open Rules while Timeline is expanded, then close Rules; confirm the timeline returns in its prior state.
4. In Options, inspect region, chart, weather and model selects, layer labels and the lowest actions. Open native pickers to inspect long option text. Close the sheet.
5. In Conditions, change hour and forecast date, select another model and visit Live, Waves and Tides. Horizontal date/table scrolling should stay inside its own control. Reach the lowest content and return using bottom navigation.
6. In Guide, open Regional data coverage. Read all three columns, including the first and last rows, without clipped text. Open species notes and their disclosures.
7. In Morro Bay, open SC26-004. Check the seabed controls, rules, export actions and card footer. Use a disposable test plan to add it to the day plan, review it in Export, then clear the test selection. Confirm zero selected spots afterward.
8. Restore the browser viewport and close temporary audit tabs.

The new Export tab was added after the original audit and still needs browser verification: exercise individual spot checkboxes, Current map / Filtered spots / Whole region selection, each included layer, saved plan name/date/selection/coverage after reload, a small GPX download and offline notes. In Southern California verify the no-qualified-waypoints message and a protected-area-only export. Inspect downloaded file contents before claiming export success. Its source CSS uses stacked fields/actions below 380px, wrapping labels and 48px primary controls; this static review is not a completed UI test.

## Limitations

- These are responsive desktop-browser checks, not a physical iPhone/iPad run. Native touch gestures, the on-screen keyboard, safe-area insets and iNavX import require device testing.
- The available browser API supports viewport changes but no temporary text-only scale. **200% text was not runtime tested**; repeat the checklist with a browser's text enlargement on a test profile. Fixed map overlays and long native-select text deserve particular attention.
- Native selects remain single-line controls; very long chart/location options may require opening the native picker to read their complete labels.
- No automated screenshot assertions or accessibility conformance certification are implied. Data accuracy, regulation interpretation, GPX geometry and forecast calibration are outside this readability check.
