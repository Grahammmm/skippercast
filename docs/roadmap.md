# Roadmap

This separates what ships now from future work. The domain **skippercast.com** is registered by the project owner. The web app is described in [its guide](web-app.md) and the system in [architecture](architecture.md). Nothing here is a date or a commitment.

## What ships now (version 0.8)

This is what the code on `main` does. It is not a statement that a feature is live on skippercast.com, and each line names the files that implement it.

**The app and the brief**

- A landing page at `/` and a map app at `/map` with five views: Coast, Conditions, History, Fleet and Reports (`server/routes/assets.ts`, `web/landing/Landing.tsx`, `web/state.ts`, `web/app/App.tsx`).
- A brief for a port and a profile (Boat, Shore, Spear or Kayak): wind, swell, water and tide tiles, a lower-exposure window, where to look, and a caveat. It never gives a go/no-go or promises a catch (`web/brief/Brief.tsx`, `web/profile.ts`).
- For a Boat brief, run time at your own cruise speed, a turn-back time and the fishing time left. The distance is the water route over the NOAA land-water screen, shown as "by water", or a labelled straight line when no route is computed; it is a planning distance, not a navigation route (`web/brief/run.ts`, `web/route.ts`).
- For a Boat brief at a harbor entrance with bar conditions (Morro Bay is the active region), a leave-by and a be-back-by time, shown only when the entrance is judged and both times exist; otherwise the line gives the reason instead. The times are not a promise of a safe crossing (`web/brief/Run.tsx`, `packages/coast/src/entrance-window.ts`).
- Where to look lists ranked places and, for a selected place, up to three dated reasons each with its source. A place with no dated evidence says so instead of showing a reason (`web/brief/WhereToLook.tsx`, `web/area-reasons.ts`).
- English and Spanish catalogue-backed presentation across landing, map, brief, planning and account surfaces, with the explicit English/published-content exceptions below; this is not whole-screen or runtime translation (`web/i18n.ts`, `catalog/app/strings.json`, `scripts/check_copy.mjs`).

Inventory checked at `def43f14d0335f37df6a5787ef7ac0560bd67f1b` (post-SC1137-06 source), against the entire `COVERED` and `NOT_COVERED` exports in `scripts/check_copy.mjs` and every discovered `.tsx` in its `web/app`, `web/brief` and `web/landing` roots. The lists below describe catalogue-backed presentation, not every word inside a screen; a covered wrapper does not establish coverage for its children or data producers.

**Spanish presentation**

- **Landing and first run: hero, port/profile/region choices, readout, verdict and layer links.** `web/landing/main.tsx`, `web/landing/copy.ts`, `web/landing/Landing.tsx`, `web/landing/PortInput.tsx`, `web/landing/ProfileStep.tsx`, `web/landing/Readout.tsx`, `web/landing/readings.ts`, `web/landing/live-verdict.ts`, `web/landing/LayerDots.tsx`, `web/landing/RegionPicker.tsx`, `web/RegionPickerEntry.tsx`, `web/app/FirstRun.tsx`.
- **Map shell and controls: navigation, language choice, comfort limits, time dock, tour and presets.** `web/app/Masthead.tsx`, `web/app/Mobile.tsx`, `web/app/SkipLinks.tsx`, `web/app/CommandBar.tsx`, `web/app/AccountMenu.tsx`, `web/app/LanguageChoice.tsx`, `web/app/LimitsPanel.tsx`, `web/app/TimeDock.tsx`, `web/ui/Dock.tsx`, `web/app/ControlsTour.tsx`, `web/tour.ts`, `web/app/Presets.tsx`, `web/app/presets.ts`.
- **Map presentation, layer rail and legend: catalogue labels, basis and known status/age notes; not arbitrary renderer or provider text.** `web/app/MapStage.tsx`, `web/map/layers.ts`, `web/app/rail.ts`, `web/app/LayerRail.tsx`, `web/app/Legend.tsx`, `web/map/status-copy.ts`.
- **First answer and brief: verdict reasons, details, profile caveat and known source-gap sentences.** `web/first-answer.ts`, `web/app/FirstAnswerLine.tsx`, `web/brief/Brief.tsx`, `web/brief/verdict-copy.ts`.
- **Brief tiles, tide station, tide sparkline and mark forecast: labels and known detail/save-refusal wording.** `web/brief/Tiles.tsx`, `web/brief/tile-copy.ts`, `web/brief/TideStationControl.tsx`, `web/brief/TideSpark.tsx`, `web/brief/tide-copy.ts`, `web/brief/MarkForecast.tsx`, `web/brief/remaining-copy.ts`.
- **Where to look and Boat run: generated ranking reasons, distances, return-window and entrance-current presentation; unknown upstream sentences stay as received.** `web/brief/WhereToLook.tsx`, `web/brief/ranking-copy.ts`, `web/brief/Run.tsx`, `web/brief/EntranceCurrent.tsx`.
- **Conditions, hourly table and History: generated headings, readings, model disagreement and renderer copy supplied by these views.** `web/app/views/Conditions.tsx`, `web/app/views/HourlyTable.tsx`, `web/app/views/History.tsx`, `web/model-disagreement.ts`, `web/view-copy.ts`.
- **Public Fleet and Reports: controls, counts, known evidence phrases and supplied catch-card labels; not admin controls or published prose.** `web/app/views/Fleet.tsx`, `web/app/views/Reports.tsx`, `web/reports.ts`, `web/reports-copy.ts`.
- **Planning, Trip, offline-pack and position-check presentation: controls and known messages; exports and supplied plan text are not automatically translated.** `web/app/Planner.tsx`, `web/app/Trip.tsx`, `web/app/PositionCheck.tsx`, `web/app/PositionView.tsx`, `web/position-check.ts`, `web/trip-ocean-lines.ts`, `web/planner-copy.ts`, `web/app/PlanView.tsx`, `web/plan.ts`.
- **Selected marks and private saved spots: generated card/status/action wording; names and notes remain their own text.** `web/app/MarkCard.tsx`, `web/saved-spots.ts`, `web/mark-copy.ts`.
- **Account and private-record forms: passkey/account, catch-log and saved-spot controls, plus device-log chrome; not stored snapshots or free text.** `dist/account.js`, `web/account-copy.ts`, `web/app/PrivateMapLog.tsx`.
- **Saved-trip alerts, recap/digest preview and home-port alert: form labels and generated presentation, not server-written assessments or hazard notes.** `web/app/TripAlerts.tsx`, `web/alerts.ts`, `web/digest.ts`, `web/app/PortAlert.tsx`.
- **Rules-card, plan-rule and season-calendar labels and app-worded reasons; registry clauses remain English.** `web/app/RulesCard.tsx`, `web/app/PlanRules.tsx`, `web/app/RuleReason.tsx`, `web/app/SeasonStrip.tsx`, `web/season.ts`.
- **Shared local error/retry, default basis/source link and saved-copy notice chrome; caller-supplied popover contents stay caller-owned.** `web/ui/Guard.tsx`, `web/ui/Popover.tsx`, `web/degraded-notice.tsx`, `web/degraded.ts`.

**Stays English / as published**

These are the checker's exact `NOT_COVERED` reasons at that head, including composition-only files (which are not English screens) and explicitly deferred surfaces:

| File | `NOT_COVERED` reason (verbatim) |
| --- | --- |
| `web/app/PreviewLayers.tsx` | MAPLIVE-1 owner-only private map previews; admin-only research wording marked lang="en", outside the Spanish scope like the admin views (#1512) |
| `web/app/App.tsx` | composition and region loading; no visible text of its own |
| `web/app/CoastMarkup.tsx` | renders the coast package's chart markup, whose labels are drawn in packages/coast; deferred, not translated here |
| `web/app/Desktop.tsx` | desktop layout composition; its only literals are the Brief and Fleet pane aria-labels, deferred |
| `web/app/EnglishDetail.tsx` | wraps official English text in lang="en"; the one prefix it adds already comes from the catalogue |
| `web/app/main.tsx` | bootstrap that mounts the app and wires state; no visible text |
| `web/app/views/FleetAdmin.tsx` | admin-only fleet activity panel; admin views are outside the Spanish scope (#1512) |
| `web/landing/NightMap.tsx` | night map canvas is aria-hidden; its Basemap and Currents credit lines are English, deferred |
| `web/landing/Shoreline.tsx` | decorative shoreline SVG (aria-hidden); its English shoreline credit sentence is deferred |

Source discrepancy at this head: the `web/app/Desktop.tsx` reason is stale in detail. Its Brief pane aria-label already uses the catalogue, but its Fleet aria-label, fallback `Today's brief` and model-supplied `brief.label` remain English. This is partial coverage, not a claim that the desktop brief is entirely translated; the checker classification is retained unchanged.

- **Admin views — outside the TSX coverage inventory.** The separate admin app uses English-only admin/fleet copy rather than the app catalogue: `web/admin/app.tsx`, `web/advisor/copy.ts` (`ADMIN_COPY`), `web/admin/fleet-copy.ts`. The in-inventory Fleet admin and private-preview exclusions are listed above; a translated public Fleet wrapper does not translate its admin panel.
- **Server-written alert messages and hazard notes — outside the TSX coverage inventory.** `server/alert-policy.ts` writes English assessment/hazard sentences and `alertMessage`; `server/trips.ts` stores that message. The covered `web/app/TripAlerts.tsx` translates its own controls but shows received messages, hazard notes and server errors as English, marked `lang="en"` on a Spanish page; `web/digest.ts` does not translate raw hazard notes. There is no matching server-path `NOT_COVERED` entry.
- **Published names and data-supplied prose.** Port/region/station/species/source names and IDs, legal citations, datum/product names, original rule wording, arbitrary saved notes and supplied evidence remain as published or entered. The covered adapters do not translate unknown text: `web/brief/tile-copy.ts`, `web/brief/ranking-copy.ts`, `web/brief/remaining-copy.ts`, `web/mark-copy.ts`, `web/reports-copy.ts`, `web/plan.ts`, `dist/account.js`. The rules producer `web/regs.ts` is outside the TSX coverage inventory; `web/app/RulesCard.tsx`, `web/app/PlanRules.tsx` and `web/app/RuleReason.tsx` distinguish their translated labels from the registry's English clauses/geography notes. The exact `web/app/EnglishDetail.tsx` reason above explains its English wrapper; it is not a blanket classification for every data producer. Catalogue coverage is not legal advice, a translation of source rights, or a translation of server notifications, downloads or exports.
- **Stored device-log snapshots — outside the TSX coverage inventory at the producer.** `web/private-map-log.ts` writes and validates the v1 English record labels and position-basis sentence. `web/app/PrivateMapLog.tsx` translates its controls and counts, but shows stored snapshots unchanged inside `lang="en"`; switching language does not rewrite them.
- **Static legal pages — outside the TSX coverage inventory.** `dist/privacy.html` and `dist/terms.html` are English HTML drafts pending counsel review, with no app-catalogue translation. `dist/sources.html` and `dist/licenses.html` likewise retain their published English source/rights text. None has a `NOT_COVERED` entry; the TSX roots cannot certify these pages.

**Unclassified at `def43f14d`:** none in the three TSX roots; no file is in both lists. This says nothing about files outside those roots. The covered `web/brief/EntranceCurrent.tsx` passes the selected language into its producer `web/brief/entrance-current.ts`; that producer is outside the TSX inventory and in neither export, despite its catalogue-backed presentation. No missing classification is silently added here.

The shared saved-copy notice uses the selected language's locale for its timestamp. The legacy no-language `degradedText` helper still uses the browser locale and an English template; selected-English UI timestamps on a Spanish browser need not be byte-identical to that legacy output (`web/degraded-notice.tsx`, `web/degraded.ts`).

- One disclosed conditions model behind the brief and the advisor's comfort words ([conditions model](conditions-model.md)), and a day verdict rated for the boat saved in the browser. The rating names the saved boat, or the reference boat when none is saved; it is a comfort estimate from a rule-of-thumb model tuned on a 23 ft boat, not a validation of the saved boat, a bite forecast or a safety clearance (`web/brief/Brief.tsx`, `web/brief/verdict.ts`, `web/boat-range.ts`).

**The map and the plan**

- A MapLibre Chart on a self-hosted basemap, and 2D and 3D terrain views loaded on demand (`web/map/chart.ts`, `web/map/maplibre.js`, `packages/coast/src/coast3d.ts`).
- Layers for seafloor habitat, protected areas, currents, swell, water temperature, clouds, charter grounds and a dated commercial AIS layer, each with its basis sentence (`web/map/layers.ts`).
- A seven-day hourly time dock and a Conditions view that compares NOAA and ECMWF model runs and says in words where they disagree (`web/app/TimeDock.tsx`, `web/hour.ts`, `web/model-disagreement.ts`).
- A trip plan with ranked reef spots, GPX, share-sheet and offline-notes export (`web/planner.ts`, `web/app/Planner.tsx`, `dist/trip-export.js`).
- Every output that names a place (a ranked spot, a trip leg, a waypoint, a GPX point, a reach area, a Where to look row) goes through one protected-area screen and carries its verdict. A place the screen could not check is shown as unchecked, never as clear. This screens places; it does not yet route around protected areas (`dist/geo-screen.js`, `tests/test_closures_everywhere.mjs`).
- A yearly season calendar for each species, from the reviewed rules, with the revision it was read from and a link to the official page. It is not legal advice (`web/app/SeasonStrip.tsx`, `web/season.ts`).
- Rules cards with the bag, size and depth limits, the date the rule was last verified or checked, and one official link. A rule that is stale, overdue or unknown reads as checked or unknown, never as verified (`web/regs.ts`).

**Saved trips and your own records**

- Saved-trip alerts in the account menu, with passkey sign-in and private records in D1: an assessment of the saved window and its departure and return hours, sent when it materially changes and the day before. An assessment is a forecast read, not a clearance for the trip (`web/app/TripAlerts.tsx`, `web/alerts.ts`, `server/alert-policy.ts`, `server/trips.ts`).
- A private history of saved trips with a recap of each past trip. The forecast assessments we sent are kept apart from what the sea did, and are shown beside your own comfort reports (`web/app/TripAlerts.tsx`, `web/alerts.ts`).
- A private catch and effort log API for the signed-in owner: fish, blank and unknown outcomes, optional positions, and listing and deletion by the owner only. The account panel has a form and list for it, and the log feeds no public route, score or aggregate, so it is not evidence of where fishing succeeds (`server/routes/catch-log.ts`, `server/app.ts`, `dist/account.js`).
- Saved spots in the same account panel: named positions with an optional private note, kept for the signed-in owner only, up to 100, and listed and deleted by the owner only (`server/routes/spots.ts`, `dist/account.js`). Nothing publishes them. The owner can download the eligible positions as GPX; private notes are not in that GPX file. The whole GPX download is withheld if any spot's protected-area check is unavailable or the screen is older than 36 hours; spots inside or near a protected area are left out of an otherwise successful file. A signed-in person can add a saved spot as a stop in the browser's trip plan; the planner re-checks protected areas before adding it (`web/planner.ts`, `web/app/Planner.tsx`). A signed-in person can also save an eligible selected map mark to these private spots after the current protected-area check; inside, within-70 m and unchecked positions are not saved (`web/saved-spots.ts`, `web/app/MarkCard.tsx`). An off-by-default, Chart-only "Your saved spots" layer draws the owner's spots as named pins, read once per session, each with the shared protected-area reading and never the private note; the choice is not in the address, a share link, a feed or an export (`server/routes/spots.ts`, `dist/account.js`, `web/saved-spots.ts`, `web/map/saved-spots.ts`).
- An offline trip pack and a service worker that serves saved data marked as saved (`dist/sw.js`, `web/trip.ts`).

**Public pages**

- A data status page at `/status` showing when each source last published and whether that is on time, and listing the sources it does not watch (`dist/status.html`, `server/routes/assets.ts`).
- A coverage page at `/coverage` showing each published region by its fishing bounds; the spaces between the boxes are not covered (`dist/coverage.html`, `server/routes/assets.ts`).
- A forecast skill page showing how often the forecast was close to a buoy reading over the last 7 and 30 days. A window with too little history reads "not enough data yet" with no percentage, and swell period and water temperature are not scored. It is served at `/skill` and `/skill.html` (`dist/skill.html`, `dist/skill-page.js`, `server/routes/assets.ts`).
- Port pages at `/ports/<port>` for ports whose region is built, answering only while the public pages or the advisor are switched on. A port page does not make a region active (`server/advisor/pages/port.ts`, `server/routes/advisor.ts`, `server/advisor/gate.ts`).
- A sources page and a licences page with the source attribution and licensing boundaries (`dist/sources.html`, `dist/licenses.html`).

**Behind the scenes**

- A Text Advisor that is built and stays off until the owner launches it (`server/advisor/gate.ts`, [plan](plans/text-advisor/README.md)).
- Scheduled data jobs that publish live conditions and forecast tiles every 30 minutes and daily evidence each day, with a watchdog and a freshness check that restart or report a stalled feed (`.github/workflows/live-conditions.yml`, `.github/workflows/daily-data.yml`, `.github/workflows/feed-freshness.yml`, `server/watchdog.ts`).

The evidence limits in [web-app.md](web-app.md#evidence-limits) still apply: bottom scores rank mapped habitat, not catch probability, and forecasts are regional model values.

## Privacy notice and terms (SCB-05, 2026-11-13)

`/privacy` and `/terms.html` are back as short drafts written from what the code does (the 2026-11-12 drafts were
removed because they made claims the code does not support). Still open before they stop being drafts: the
operator's name and a contact address, a lawyer's read, the owner's confirmation that no usage-statistics
binding is set outside GitHub and whether the boat lookup is live, and a Text Advisor section before any pilot
(`docs/operations/runbooks/advisor-meta-app-review.md`). `tests/test_legal_pages.mjs` fails if the numbers in the
notice (retention, limits, session length) stop matching the server.

## Next

The owner sets the order. Morro Bay is the only active region until it is refined.

1. **Morro Bay, refined.** Finish and check the Morro Bay data, brief and trip tools before anything else.
2. **About ten miles north of Morro Bay.** Extend along the central coast once Morro Bay is refined.
3. **South along the central coast.** After the northern step.
4. **Trip planning depth.** Shipped: planning routes over the land-water screen for the Boat run (a labelled straight line when none is computed), the line-of-sight smoothing of its stair-step path, and the daylight and legal-opening fishing-time comparison (#1260). Still to do: avoiding protected areas on the route.
5. **Better fishing evidence.** Verified charter identities and defensible AIS stop and effort analysis, with coverage limits kept apart from habitat priority. Do not label sites as charter hotspots without evidence.

Held data rights must be resolved before adding the excluded Cambria and charter layers. Any later commercial offering would need separate rights for the original project material and compliance with each provider's data and service terms.
