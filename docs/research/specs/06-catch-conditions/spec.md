# 06 · Conditions recorded with each catch-log entry

Status: proposed, 2026-11-19 · Priority 6 · Effort estimate: M · Depends on: 02 (history for entries logged after the day), 01 (shared samplers)
Source: SkipperCast competitor analysis, recommendation 6 (Salty Offshore logbook with conditions at every bite and season patterns; RideScore trip reports).

## Intended goal

When an angler logs a catch, or a blank, with a position, SkipperCast attaches the conditions there at that time: water temp, temp contrast, distance to the nearest SST front, chlorophyll, current, swell, wind and tide stage. Over a season the angler can see the conditions their own good days had in common.

## Purpose

The private catch log (`catch_log`: started_at, outcome, count, species, method, optional lat/lon, trip link, note) records what happened but not the water. SkipperCast's evidence stance (`docs/evidence-ladder.md`, `docs/bite-evidence.md`) favours building its own dated evidence rather than claiming catch odds. A conditions snapshot does that, privately, for each owner. It also gives Fish-or-Pass-style self-checking ("what was the water when you caught?") without a public score.

## User journey

1. Jon logs "Fish · 3 · lingcod · jig" at a position and time from the account panel (the existing form).
2. After saving, the entry shows a **Conditions** line: "Water 56.9 °F · 0.4 °F/nm contrast · 2.1 nm from a front · chl 2.4 mg/m³ · current 0.3 kn · swell 5 ft @ 11 s from WNW · wind 9 kn NW · tide ebbing, 1.2 ft". Each value has a small info tooltip naming its product and age.
3. A value that wasn't available reads "not available (cloud)" or "not archived", never a guess.
4. If he logs later, for example the next evening, the snapshot uses the archived observed frames of that day (spec 02 history). Forecast values use the archived forecast nearest that hour if kept. Otherwise they're marked "not archived".
5. In the account panel, **My patterns** summarises fish vs blank entries by water-temp band and tide stage. It always shows n and says "your log only, not a forecast".
6. The CSV and **Export my records** downloads include the snapshot columns.

## Use cases

- **Learn the temperature band a reef fished best in this season.**
- **Compare blank days with good days** on contrast and fronts.
- **Bring a dated record to a skipper conversation** without sharing positions.

## Requirements

1. **R1** Add a new nullable `conditions` JSON column on `catch_log` (migration). The shape is versioned: `{v:1, at, layers:{water_temp:{value, unit:'F', product, sample_at}|{missing:reason}, contrast:…, front_nm:…, chlorophyll:…, current:{kn, toward_deg, run, valid_at}…, swell:…, wind:…, tide:{stage, height_ft, station}}}`.
2. **R2** The snapshot is computed server-side on create, and when position or time changes on patch, from the region's published feeds in `FEEDS`. It uses the native-cell samplers shared with spec 03. Observed layers use the frame whose day equals `started_at`'s local day (current or spec 02 history). Forecast layers use the hour nearest `started_at` only if that publication is still held. Otherwise they're `missing:'not archived'`.
3. **R3** Entries without a position get only regional values (tide, and wind/swell at the region's forecast point), clearly labelled "region, no position".
4. **R4** The snapshot is private, like the coordinates. It is never in a public route, feed, preview, analytics point or log line.
5. **R5** **My patterns**: a client-side aggregation over the owner's entries (up to the existing 2,000-entry export bound) by water-temp band (1 °F) and tide stage, fish vs blank counts. It is hidden when n < 10 and always shows n.
6. **R6** The CSV adds snapshot columns. The JSON export includes the object.
7. **R7** Copy uses "your log" language and never "predicts" or "best".

## Acceptance

- Creating an entry with a position inside fixture feeds stores all layers with values and product names. Inside a cloud gap, chlorophyll is `{missing:'no retrieval'}`.
- Patching the time to a day without history sets the observed layers to `missing:'not archived'`.
- No snapshot data appears in any response from non-owner routes (route test sweep, as existing privacy tests do).
- `node --test tests/test_*.mjs`, `pnpm typecheck` and `pnpm build` pass. The migration is generated with `pnpm db:generate`.

## Non-goals

- No public aggregation, no cross-user patterns, no "bite score".
- No automatic catch detection or GPS tracking in this increment.
