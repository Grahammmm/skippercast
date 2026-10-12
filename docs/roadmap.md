# Roadmap

This separates what ships now from future work. The domain **skippercast.com** is registered by the project owner. The web app is described in [its guide](web-app.md) and the system in [architecture](architecture.md). Nothing here is a date or a commitment.

## What ships now (version 0.8)

- A landing page at `/` and a map app at `/map` with five views: Coast, Conditions, History, Fleet and Reports (`web/app/`).
- A brief for a port and a profile (Boat, Shore or Spear): wind, swell, water and tide tiles, a lower-exposure window, where to look, and a caveat. It never gives a go/no-go or promises a catch (`web/brief/`).
- For a Boat brief, run time at your own cruise speed, a turn-back time and the fishing time left. The distance is straight-line, not a charted route (`web/brief/run.ts`).
- One disclosed conditions model behind the brief and the advisor's comfort words ([conditions model](conditions-model.md)).
- A MapLibre Chart on a self-hosted basemap, and 2D and 3D terrain views loaded on demand (`web/map/`, `packages/coast/`).
- Layers for seafloor habitat, protected areas, currents, swell, water temperature, clouds, charter grounds and a dated commercial AIS layer, each with its basis sentence.
- A seven-day hourly time dock and a Conditions view that compares NOAA and ECMWF model runs.
- A trip plan with ranked reef spots, GPX, share-sheet and offline-notes export (`web/planner.ts`, `web/app/Planner.tsx`).
- Saved-trip alerts in the account menu, with passkey sign-in and private records in D1 (`web/app/TripAlerts.tsx`, `web/alerts.ts`).
- An offline trip pack and a service worker that serves saved data marked as saved (`dist/sw.js`, `web/trip.ts`).
- A Text Advisor that is built and stays off until the owner launches it (`server/advisor/gate.ts`, [plan](plans/text-advisor/README.md)).
- Scheduled data jobs that publish live conditions, daily evidence and forecast tiles, with a watchdog ([architecture](architecture.md)).
- Source attribution, licensing boundaries and documentation for a new reader.

The evidence limits in [web-app.md](web-app.md#evidence-limits) still apply: bottom scores rank mapped habitat, not catch probability, and forecasts are regional model values.

## Next

The owner sets the order. Morro Bay is the only active region until it is refined.

1. **Morro Bay, refined.** Finish and check the Morro Bay data, brief and trip tools before anything else.
2. **About ten miles north of Morro Bay.** Extend along the central coast once Morro Bay is refined.
3. **South along the central coast.** After the northern step.
4. **Trip planning depth.** Charted routes, daylight and fishing-time calculations beyond the straight-line run time.
5. **Better fishing evidence.** Verified charter identities and defensible AIS stop and effort analysis, with coverage limits kept apart from habitat priority. Do not label sites as charter hotspots without evidence.

Held data rights must be resolved before adding the excluded Cambria and charter layers. Any later commercial offering would need separate rights for the original project material and compliance with each provider's data and service terms.
