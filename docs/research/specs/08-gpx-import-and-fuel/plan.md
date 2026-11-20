# Implementation plan · 08 GPX import and fuel

## Evidence (observed 2026-11-19, commit fa9c358)

- `web/gpx-waypoints.ts`: `readGpxWaypoints(xml) → {ok, waypoints:[{name, lat, lon, note}], rejected, ignoredTrackPoints}` or an error code. `MAX_GPX_BYTES` 1,048,576 and `MAX_GPX_POINTS` 1,000. It mirrors the spot-store limits. It is pure and DOM-free ("runs in the unbundled account panel"). It is imported only by tests today.
- `server/routes/spots.ts`: `MAX_SPOTS 100`, `NAME_UNITS 80`, `NOTE_CHARS 1000`, `validateSpot`, owner CRUD.
- `dist/account.js`: the saved-spots UI and GPX export (L653–L680 use `geo-screen.js` `screenPlace`, `placeRefused`, and `trip-export.js`).
- `docs/web-app.md` Account paragraph: the saving rules (inside, within 70 m, or unchecked not saved; screen older than 36 h withheld).
- `dist/boat-handling.js` L29–L32: reference boat `cruise_kn 20`; ranges `cruise_kn [2,60]`, `max_hp [0,3000]`, `fuel_gal [0,1500]`. Normalised by `normalizeBoat`.
- `web/brief/run.ts`: `RunPlace {name, nm, basis:'water'|'straight'}`, `runMinutes(nm, speedKn)`. The header comment leaves fuel to the skipper.

## Architecture choices

- The import is entirely client-side until confirmation. The batch endpoint is optional: start with sequential single creates (at most 100) in the client, with a progress bar. Add `POST /api/spots/batch` only if request limits (`request_limits`) make sequential creates fail.
- `burn_gph` is added to the boat normaliser's ranges and to the manual form. It is kept in the browser profile like the other fields (the boat profile stays in this browser) and copied into trips as `boat_burn` only if needed later (not now).

## Files to create or modify

| File | Change |
| --- | --- |
| `dist/account.js` | Import GPX UI: file input, preview list, screen, select, save |
| `server/routes/spots.ts` | (optional) `/api/spots/batch` |
| `dist/boat-handling.js` | `burn_gph` range `[0.5,200]` in normalisation |
| boat form (`web/boat-entry.ts` and its UI) | optional field |
| `web/brief/run.ts` + brief rendering | `fuelEstimate(nm, cruise, burn, tank)` and the line |
| `catalog/app/strings.json` | `spots.import.*`, `boat.burn.*`, `brief.fuel.*` en+es |
| `docs/boat-profile.md`, `docs/web-app.md` | document |
| `tests/test_spots_import.mjs`, `tests/test_fuel_estimate.mjs` (new), `tests/fixtures/gpx/marks-150.gpx` | |

## Edge cases

- Duplicate positions (same lat/lon to 5 decimals as an existing spot) are skipped and reported.
- Names that are blank or have characters GPX forbids are kept as typed (the spot store keeps what was typed; export cleans them).
- The protected-area screen is unavailable: nothing is saved, with a "try again later" message (fail closed).
- Straight-line runs (no water route): no fuel line.

## Dependencies

None.
