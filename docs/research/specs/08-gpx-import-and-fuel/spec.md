# 08 · GPX import into saved spots, and an optional fuel estimate for the boat run

Status: proposed, 2026-11-19 · Priority 8 · Effort estimate: S · Depends on: none
Source: SkipperCast competitor analysis, recommendation 8 (Salty Offshore GPX import; GulfWire route and fuel planner).

## Intended goal

An angler can bring their chartplotter waypoints into SkipperCast's private saved spots from a GPX file in one step. A Boat brief can show an optional, clearly-labelled fuel estimate for the planned run when the owner has entered their boat's burn rate.

## Purpose

- **GPX import.** A safe GPX waypoint reader already exists and is tested (`web/gpx-waypoints.ts` `readGpxWaypoints`, plus `tests/test_gpx_waypoints.mjs` and `tests/test_gpx_xml_whitespace_eol.mjs`), but no UI calls it. Saved spots take one typed position at a time. Every serious competitor imports GPX.
- **Fuel.** The boat profile already holds `fuel_gal`, `max_hp` and `cruise_kn` (`dist/boat-handling.js` ranges). The Boat brief computes the water-route distance and run time (`web/brief/run.ts` `RunPlace.nm`, `runMinutes`). It deliberately leaves fuel to the skipper today: "Sea state, the bar crossing itself and fuel are left to the skipper". This spec keeps that stance by default. It adds an opt-in estimate only when the owner enters their own burn rate, and states every assumption.

## User journey

**GPX import**

1. Rosa opens the account panel → Saved spots → **Import GPX**, and picks `garmin_marks.gpx` (180 waypoints).
2. SkipperCast reads the file in the browser. Nothing is uploaded until she confirms. It shows "180 waypoints read · 12 route points not imported · 0 refused".
3. Each waypoint is screened against protected areas with the same rule as saving a mark: inside, within 70 m, or unchecked means not saved. The list shows "158 can be saved · 22 inside or near a protected area (not saved)".
4. She has 40 spots already, so 60 slots are left (the limit is 100). She ticks which to import, or takes "first 60 by name". Names and descriptions become spot names and notes.
5. She confirms. The spots are saved and appear in the "Your saved spots" layer.

**Fuel estimate**

1. Rosa opens Boat → Edit and fills in the new optional field **Fuel burn at cruise (gal/h)**: 9.
2. In the Boat brief for a spot 18 nm out, a line appears under run time: "Fuel estimate ≈ 14 gal round trip at 24 kn (your 9 gal/h) · tank 70 gal · thirds rule: OK". It's tagged "estimate: not a fuel plan; sea state, load and detours change it".
3. Without a burn rate, nothing about fuel is shown (today's behaviour).

## Use cases

- **Move years of chartplotter marks into SkipperCast** without retyping.
- **Check whether a far spot is within the thirds rule** for the boat.

## Requirements

1. **R1** The account panel offers Import GPX. It accepts a single `.gpx` file of at most 1 MiB (`MAX_GPX_BYTES`), parsed by `readGpxWaypoints` in the browser. Route and track points are reported but not imported (the reader already refuses them).
2. **R2** Every candidate is screened with the existing protected-area screen (`dist/geo-screen.js` `screenPlace`/`placeRefused`). The same refusal rules as saving a mark apply: inside, within 70 m, unchecked, or a screen older than 36 hours all mean not saved.
3. **R3** Saving respects `MAX_SPOTS = 100`, `NAME_UNITS = 80` and `NOTE_CHARS = 1000`. Add `POST /api/spots/batch` (at most 100 per request, all-or-nothing validation, one transaction), or reuse single creates with a progress bar. Either way, a partial failure reports which ones failed.
4. **R4** No GPX content is logged or sent anywhere except the confirmed spots to the owner's own route.
5. **R5** The boat profile gets an optional `burn_gph` (0.5–200), with manual entry only. The AI lookup must not fill it in this increment.
6. **R6** The Boat brief shows the fuel line only when `burn_gph` and `cruise_kn` are set and the run basis is `water`. Gallons = 2 × nm / cruise_kn × burn_gph, rounded up to whole gallons. The thirds rule is OK when the round trip ≤ 2/3 × `fuel_gal`, and "check fuel" otherwise. Without `fuel_gal`, only the gallons are shown.
7. **R7** Copy keeps "estimate, not a fuel plan" and never says "enough fuel" or "safe range". `docs/boat-profile.md` and the `run.ts` header comment are updated.

## Acceptance

- Importing `tests/fixtures/` GPX samples (add a 150-waypoint fixture with points inside an MPA) saves only the clear ones, up to capacity, and reports the counts.
- A file over 1 MiB is refused before parsing, with the reader's message.
- With burn 9 gal/h, cruise 24 kn and 18 nm, the line shows 14 gal (2 × 18 / 24 × 9 = 13.5, rounded up). Without a burn rate, no fuel text exists in the DOM.
- `node --test tests/test_*.mjs`, `pnpm typecheck`, `pnpm build`, `node scripts/check_copy.mjs` and `node scripts/check_client.mjs` pass.

## Non-goals

- No route or track import into trip plans in this increment. No fuel price, no range rings, no automatic burn lookup.
