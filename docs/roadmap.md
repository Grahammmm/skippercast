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
- A private catch and effort log API for the signed-in owner: fish, blank and unknown outcomes, optional positions, and listing and deletion by the owner only. There is no catch-log screen yet, and the log feeds no public route, score or aggregate, so it is not evidence of where fishing succeeds (`server/routes/catch-log.ts`, `server/app.ts`).
- An offline trip pack and a service worker that serves saved data marked as saved (`dist/sw.js`, `web/trip.ts`).

**Public pages**

- A data status page at `/status` showing when each source last published and whether that is on time, and listing the sources it does not watch (`dist/status.html`, `server/routes/assets.ts`).
- A coverage page at `/coverage` showing each published region by its fishing bounds; the spaces between the boxes are not covered (`dist/coverage.html`, `server/routes/assets.ts`).
- A forecast skill page showing how often the forecast was close to a buoy reading over the last 7 and 30 days. A window with too little history reads "not enough data yet" with no percentage, and swell period and water temperature are not scored. It is served at `/skill.html`; there is no bare `/skill` route on main yet (`dist/skill.html`, `dist/skill-page.js`, `server/routes/assets.ts`).
- Port pages at `/ports/<port>` for ports whose region is built, answering only while the public pages or the advisor are switched on. A port page does not make a region active (`server/advisor/pages/port.ts`, `server/routes/advisor.ts`, `server/advisor/gate.ts`).
- A sources page and a licences page with the source attribution and licensing boundaries (`dist/sources.html`, `dist/licenses.html`).

**Behind the scenes**

- A Text Advisor that is built and stays off until the owner launches it (`server/advisor/gate.ts`, [plan](plans/text-advisor/README.md)).
- Scheduled data jobs that publish live conditions and forecast tiles every 30 minutes and daily evidence each day, with a watchdog and a freshness check that restart or report a stalled feed (`.github/workflows/live-conditions.yml`, `.github/workflows/daily-data.yml`, `.github/workflows/feed-freshness.yml`, `server/watchdog.ts`).

The evidence limits in [web-app.md](web-app.md#evidence-limits) still apply: bottom scores rank mapped habitat, not catch probability, and forecasts are regional model values.

## Next

The owner sets the order. Morro Bay is the only active region until it is refined.

1. **Morro Bay, refined.** Finish and check the Morro Bay data, brief and trip tools before anything else.
2. **About ten miles north of Morro Bay.** Extend along the central coast once Morro Bay is refined.
3. **South along the central coast.** After the northern step.
4. **Trip planning depth.** Shipped: planning routes over the land-water screen for the Boat run (a labelled straight line when none is computed), the line-of-sight smoothing of its stair-step path, and the daylight and legal-opening fishing-time comparison (#1260). Still to do: avoiding protected areas on the route.
5. **Better fishing evidence.** Verified charter identities and defensible AIS stop and effort analysis, with coverage limits kept apart from habitat priority. Do not label sites as charter hotspots without evidence.

Held data rights must be resolved before adding the excluded Cambria and charter layers. Any later commercial offering would need separate rights for the original project material and compliance with each provider's data and service terms.
