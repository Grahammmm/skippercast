> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/QUALITY-REVIEW.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Independent conditions and data quality review

Review date: October 1, 2026. Scope: `src/assessment.ts`, `src/render.ts`, `src/counties.ts`, `src/providers/index.ts`, and read-only source checks. This review did not deploy, contact operators, or certify complete fishing/dive suitability. The owner is making fixes concurrently; the findings below distinguish fixes inspected from remaining work.

## Priority findings

| Priority | Finding | Required action / review status |
| --- | --- | --- |
| P1 | Originally, stale forecast hours survived an Unknown assessment and still populated current metrics and a forward outlook. Invalid issue timestamps also failed open because `NaN` age comparisons were false. | **Fix inspected:** `freshForecast()` now requires a successful source and finite fetch/issue ages, with 2 h fetch and 18 h issue gates. Assessment and outlook consume that gate. Add regression coverage for stale and malformed timestamps; retain current observations independently where genuinely fresh. |
| P1 | County reference URLs for beach water quality and Morro Bay Harbor returned HTTP 404 during direct requests. These are key local follow-up sources. | Replace with working verified URLs below. Do not infer “no notices” from failed reference access. |
| P2 | Tide chart assumes every Pacific calendar day lasts 86,400 s; outlook advances dates using `now + n*86,400 s`. Pacific DST produces 23/25 h days and can duplicate or skip a labeled local day near midnight. | Derive local calendar dates and actual day boundaries. Include November 1, 2026 and spring transition cases. Use dynamic timezone abbreviations rather than hardcoded PDT. |
| P2 | Tide SVG accessible description presents rounded plot-axis bounds as high/low predictions. | Describe actual minimum/maximum prediction values or omit numerical extrema from the description; keep official high/low event values separate. |
| P2 | Window period initially displays only its first hour, while wind/gust/wave values summarize maxima over the full period. | Display a period range or explicitly label first-hour period. Preserve individual swell components as the pipeline expands. |
| P2 | Methodology describes fixed 07:00–17:00 screening hours as daylight. These are not actual daylight boundaries all year. | Call them local screening hours or derive astronomical sunrise/sunset for location and date. |

## Verified source checks

Direct HTTP checks on October 1, 2026:

- [Morro Bay Harbor](https://www.morrobayca.gov/144/Harbor): HTTP 200. `/294/Harbor-Department` returned 404.
- [SLO County beach water quality](https://www.slocounty.ca.gov/departments/slo-health/public-health/environmental-health-services/all-environmental-health-services/recreational-health/beach-water-quality-monitoring): HTTP 200. The older `health-agency/.../beach-water-quality` URL returned 404.
- [SoCalFishReports boat totals](https://www.socalfishreports.com/dock_totals/boats.php): HTTP 200.
- [Virg's Landing](https://www.virgslanding.com/): HTTP 200.
- [Morro Bay Landing](https://morrobaylanding.com/): HTTP 200; `www` redirects to this hostname.
- [Patriot Sportfishing](https://patriotsportfishing.com/): HTTP 200; `www` redirects to this hostname.
- [NWS active CA and Eastern Pacific alerts](https://api.weather.gov/alerts/active?area=CA,PZ): HTTP 200; 17 features and no pagination in the inspected response. Including PZ avoids the known marine-region omission from a California-only request. Future responses still require payload/pagination validation.
- [North sample point](https://api.weather.gov/points/35.63,-121.20): HTTP 200; returned PZZ645 and gridpoint LOX/62,133. This establishes coverage for that sample, not every location in “Cambria & San Simeon.”

## Correct behaviors and verified limits

- Unit conversion returns null for unavailable/unrecognized units and non-finite inputs; renderer prints a missing marker. Reviewed paths do not translate missing values into zero wind, zero waves or a measured zero catch.
- NOAA forecast interval parsing validates positive intervals and distinguishes duration from end time. Malformed intervals remain unavailable.
- Tide predictions are converted from explicitly requested metric MLLW data to feet and UTC timestamps. The report states that Port San Luis is a reference and high/low tide does not imply slack current. No current prediction is implemented.
- Marine alerts include both marine and discovered land forecast zones, UGC matching and point/polygon matching. A failed/stale alert source prevents proposed windows. The review did not demonstrate full geographic coverage across the county, offshore routes, or all shore access points.
- NDBC fields are taken from one timestamp, avoiding a synthetic mixed-time observation. Freshness is based on observation time rather than retrieval time. A single Diablo buoy temperature is explicitly identified and does not establish every beach or bottom-water temperature.
- The screen does not produce a validated favorable/safe outing status. Initial thresholds are disclosed as editorial filters pending local validation. Boat return routes, harbor/bar conditions, surf transformation, shore access and current remain unmeasured.
- Spear visibility remains unknown. Satellite chlorophyll is not converted into sight distance. The spear view cannot certify a dive.
- Species tags are presented as habitat context with explicit eligibility caveats; there is no catch probability or successful-reef claim. Current rules remain external official links pending a reviewed legal pipeline.
- Charter catch collection, habitat export and AIS charter-stop maps remain clearly pending. Publisher link availability is not permission to republish their full reports.
- SLO County samples beach bacteria weekly and issues water-contact notices. A live reviewed ingestion is absent: links and a disclaimer are useful, but a clear NWS check cannot establish clear water-contact status. [County guidance](https://www.slocounty.ca.gov/departments/slo-health/public-health/environmental-health-services/all-environmental-health-services/recreational-health/beach-water-quality-monitoring).

## Next acceptance evidence

Before interpreting this preview as an operational fishing report, verify one complete fresh live collection for each sample area, including unit-populated wave fields and forecast timestamps; demonstrate one relevant marine alert fixture and one land surf-alert fixture; verify stale/malformed source rejection; and show the exact day boundaries through Pacific DST. The live-source status must remain visible when an optional source fails. Reviewed access, beach surf/water-contact feeds, rules and local visibility must precede stronger method-specific recommendations.

If a future catch record stores a date-only local trip date (`YYYY-MM-DD`), format it as that calendar date. Parsing it as UTC midnight and converting to Pacific time would show the preceding date. No live catch rows exist in the current collector, so this is a schema acceptance requirement rather than an observed production defect.

## Resolution and verification record

The initial findings above are retained as the review history. October 1 implementation resolves them as follows:

- Forecast issue/fetch times must be finite and fresh before metrics, assessments, hourly details or outlook consume the forecast. Regression fixtures reject stale and malformed issue clocks.
- Harbor, beach water-quality and landing links now use the verified canonical references listed above.
- Tide geometry uses the actual sampled local-day duration. Outlook uses local calendar dates anchored at noon; source clocks display PST/PDT dynamically. Regression fixtures cover both the 23-hour March 8 and 25-hour November 1, 2026 days and their consecutive outlook dates.
- The tide accessible description states actual sampled extrema, independently from rounded chart ticks.
- Window sea period is summarized and labeled as the maximum over the interval.
- Windows use astronomical sunrise/sunset at the forecast coordinates and require each full hour to fit within daylight. A winter fixture excludes the pre-sunrise hour.
- Date-only catch dates format on the intended Pacific calendar date. No live catch ingestion has been enabled.
- Separate county branding, tide references, temperature station and marker labels are configurable; a distinct county fixture checks that SLO branding/station text does not leak into the shared renderer.

Verification: 14 automated tests, both TypeScript checks and production build pass. Desktop (1280 px) and phone (390 px) browser checks verify mode navigation, area selection, real coastline rendering, and no document-wide horizontal overflow. Initial MapLibre worker asset loading failed; explicit self-hosted worker/shared assets resolved it. Production scheduler receipts, email confirmation/unsubscribe and stronger local-entry recommendations remain outstanding launch gates.
