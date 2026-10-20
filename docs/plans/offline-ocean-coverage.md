# Plan: explicit ocean-data coverage for offline chart packs

Status: proposal (planning only). Kanban t_21970644, a follow-up from BP CI6-05
(t_a64baa00, PR #773, issue #767). Nothing here changes code, data, gates or
prefetch. Implementation needs separate cards, each with its own review.

## Why

A chart pack (`dist/offline-pack.js`, `web/trip.ts` FE-51) saves the region's
files, forecast bundle, NOAA ENC chart tiles and the v2 basemap. For Water temp
and Currents it saves only the region's `habitat_feed` manifest URL. It does
not save the SST or WCOFS tiles that manifest lists. A tile shows up offline
only if the page happened to fetch it during the session that saved the pack:
`savePack` copies `sc-data` entries stamped after `sessionStart`. PR #773 made
that gap visible ("not saved for offline"), and the Trip dialog says the tiles
are not prefetched.

Morro Bay and Cambria do not read those tiles at all. Their place binds a coast
report, so Water temp and Currents come from the report and ocean packet
(`/api/coast/report`, `/api/coast/ocean`). Those are saved separately and
explicitly through Coastal readings (`dist/coastal-offline-core.js`). When the
packet fails, no other source is shown (`web/map/currents.ts`
`currentsStatus`, `web/map/sst.ts` `analysisStatus`).

This plan proposes a bounded, explicit contract. Ocean tiles are saved only
when the user presses Save for offline, only for regions that read them, whole
layers or nothing, with recorded coverage, under the same age and hash gates
the readers already apply.

## Measured sizes (conditions branch, 2026-10-20T18:37Z)

These were read from `origin/conditions:regions/<id>/habitat-dynamics.json`
(the declared `bytes` of every listed tile):

| Region | Manifest | SST tiles / bytes | WCOFS tiles / bytes |
| --- | --- | --- | --- |
| southern-california (largest) | 55,880 B | 28 / 101,030 B | 29 / 4,154,326 B |
| morro-bay | 46,763 B | 8 / 17,130 B | 8 / 626,020 B |
| point-reyes-pigeon | 45,761 B | 6 / 14,101 B | 6 / 482,982 B |
| big-sur-coast | 42,840 B | none | 6 / 188,280 B |
| others (11 regions) | 44–47 KB | 2–8 / ≤ 14 KB | 2–8 / ≤ 465 KB |

The largest single tile is 190,422 B (WCOFS, southern-california). The
manifest's `max_age_hours` is 72 for SST, 36 for WCOFS and 96 for chlorophyll.
Chlorophyll is `missing` everywhere and has no v2 reader.

## Decisions

D1. Scope. Only the two layers the v2 readers draw from a regional feed are
saved: `sst-analysis` (`regionalSST`) and `wcofs-surface-forecast`
(`regionalCurrents`) in `web/map/habitat-feed.ts`. These stay out of scope:

- chlorophyll and any other manifest layer (no reader);
- HF radar (published only in the coast packet);
- seafloor habitat tiles under `/feeds/tiles/seafloor/` (`dist/sw.js` never
  caches them because a saved copy would outlive the Worker's expiry gate;
  this is unchanged);
- `/api/habitat` (the Worker's JSON copy of the feed; the v2 app reads
  `/feeds/conditions/...` directly).

D2. Regional tiles and coastal snapshots are separate paths. At save time the
pack decides the region's ocean path with the same call the layers use:
`resolveReportBinding(regionPlace(region, ...))`.

- `regional`: no report binds (every region except Morro Bay and Cambria
  today). The chart pack saves the ocean layers (D3–D7).
- `coastal-report`: a report binds (Morro Bay, Cambria). The chart pack saves
  no ocean tiles, because the readers would never use them. It writes nothing
  to `sc-coastal-snapshot-*` or `sc-coastal-index`. It only reads the
  committed snapshot pointer (`readCoastalSnapshot`, read-only) so the dialog
  can say whether Coastal readings are saved.
- Coastal readings never write to `sc-pack-*`. The coastal caches, the
  `skippercast-coastal-snapshot:<origin>` lock, the 8/8/16/32 MiB limits, the
  three-product all-or-nothing commit and `X-SC-Offline-Save` stay exactly as
  they are.

D3. Where it runs. Ocean saving is a new phase in the v2 pack extras
(`web/trip.ts` `v2Pack`, the `more` hook). It lives in a new module, e.g.
`web/map/ocean-pack.ts`, that reuses `habitatManifestURL`, `habitatTileURL`,
`tileRows` and the layer checks from `habitat-feed.ts`. Only v2 draws these
layers; v1's loader was retired in FE-61. It runs only inside the explicit
Save action. Nothing is fetched on page load, on reconnect, on a timer or in
the service worker (no prefetch, no background sync, no automatic refresh).

D4. Caps. All caps are checked against the manifest's declared sizes before
any tile is fetched, and again while bytes are read.

| Cap | Value | Reason |
| --- | --- | --- |
| Manifest bytes | 1 MiB | Largest observed is 56 KB |
| Tiles per layer | 64 | Same as the reader's `MAX_TILES` |
| Bytes per tile | 5,000,000 | Same as the reader's `MAX_TILE_BYTES` |
| Ocean total per pack | 12 MB (`OCEAN_BYTE_CAP`) | About 2.8× the largest observed (southern-california, about 4.3 MB) |
| Concurrency | 4 | Same as the pack's `CONCURRENCY` |

The phase plans SST first (small, 72 h life), then WCOFS. A layer that would
pass the remaining budget is skipped whole and recorded as `over-cap`. A layer
is never trimmed to fit.

D5. Layer-atomic saves. A layer counts as saved only when every tile it lists
passes these checks:

- it is fetched with `cache: 'no-cache'`;
- the answer is `ok` and has no `X-SC-Offline` header, so an older save is
  never re-stamped as new data;
- `tileRows` passes: length, SHA-256, region, layer, fields, grid, bounds and
  frame times.

If any tile fails, the tiles already stored for that layer are deleted from
this pack and the layer is recorded as `failed` with the first reason. The
readers refuse a partial grid anyway, so a partial layer would only cost bytes
while promising coverage.

D6. Age gate at save. A layer is fetched only if the reader would load it at
save time: status `ok`/`retained`, latest frame (SST) or `issued_at` (WCOFS)
inside its own `max_age_hours`, a `data_retrieved_at`, and for WCOFS
`surface_only: true`. Otherwise it is recorded as `not-current` and no tiles
are fetched. Offline, the readers re-judge age at the current clock exactly as
they do now. The pack adds no new expiry logic and no way around
`max_age_hours`. Expired saved data shows the existing stale or "no fresh
frame · last …" reason. It is never drawn and never labelled "not saved".

D7. Hash and identity gates. The pack records the SHA-256 of the manifest bytes
it used. Tile paths are content-addressed (`-<16 hex>.json`), and the reader
re-verifies every tile's SHA-256 and length against the manifest on every read,
including offline. The service worker verifies no hashes.

The ocean phase stores the manifest bytes it validated under the manifest URL.
This replaces the copy the files phase saved, so the pack's manifest and tiles
always come from the same publication.

D8. Coherent offline selection (the only service-worker change). Today
`newestSaved` returns the newest copy across `sc-data` and all packs. That
can go wrong after a save: a later online visit can put a newer manifest into
`sc-data` whose tiles were never viewed, or were evicted by `DATA_LIMIT`
(150). That manifest then shadows the pack's complete copy, and the layer is
refused offline.

Proposal: after a network failure on a `habitat-dynamics.json` request, the
worker tries the saved manifests newest first. It answers with the first one
whose loadable layers' tile paths are all present in some cache. If none
qualifies, it falls back to today's newest copy, which the reader then refuses
as it does now. The worker checks presence only. Hashes stay the reader's job
(D7). Other data routes keep plain newest-wins.

Alternative considered: prefer any pack copy over `sc-data`. That is simpler,
but a complete newer `sc-data` set would lose to an older pack.

D9. Metadata. The pack meta gains an additive `ocean` record, and
`schema_version` stays 1. Older readers ignore unknown fields, as they do the
`v2` record. `meta.missing` keeps meaning "files". Ocean misses are listed
only under `ocean`.

```json
"ocean": {
  "schema_version": 1,
  "path": "regional",
  "manifest": {"url": "/feeds/conditions/regions/<id>/habitat-dynamics.json", "sha256": "<64 hex>", "bytes": 46763, "generated_at": "..."},
  "bytes": 643150,
  "cap_bytes": 12000000,
  "layers": {
    "sst-analysis": {"state": "saved", "tiles": {"saved": 8, "listed": 8}, "bytes": 17130,
      "data_at": "2026-10-19T12:00:00Z", "max_age_hours": 72, "usable_until": "2026-10-22T12:00:00Z"},
    "wcofs-surface-forecast": {"state": "failed", "reason": "integrity", "tiles": {"saved": 0, "listed": 8}, "bytes": 0,
      "data_at": "2026-10-20T03:00:00Z", "max_age_hours": 36, "usable_until": null}
  }
}
```

- `path` is `regional`, `coastal-report` (then `layers` is `{}`, and
  `coastal` is `{saved_at}` or `null`, read from the committed snapshot
  pointer) or `none` (the region publishes no manifest).
- `state` is one of `saved`, `failed`, `over-cap`, `not-current`, `absent`
  (the layer is not in the manifest) or `cancelled`.
- `reason`, when `state` is `failed`, is one of `network`, `http`,
  `offline-copy`, `length`, `integrity`, `identity`, `byte-limit` or
  `manifest`.
- `usable_until` is `data_at + max_age_hours` when `state` is `saved`, and
  `null` otherwise. It is display-only. The readers' own gates decide.

Ocean failures never fail the pack. Only a missing region config does, as now.
Cancelling deletes the whole candidate pack, as now. Replacing a pack deletes
the older pack together with its ocean tiles. It never touches coastal caches.

D10. UI scope (`web/app/Trip.tsx` only):

- Each saved pack gets one line each for Water temp and Currents. Examples:
  "saved, usable until Wed 05:00", "not saved: failed check", "not saved: too
  large for this pack", "not saved: no current data at save time".
- For coastal-report regions the line reads "from Coastal readings (saved
  <time> / not saved)", with the existing pointer to Coastal readings.
- The sentence "Water temp and current tiles are not prefetched…" is replaced
  only once the ocean phase ships. Until then it stays true.
- No new toggle. The bytes are small next to chart tiles, and the save is
  already explicit. No progress beyond an `ocean` phase in the existing
  progress callback.
- New copy passes `scripts/check_copy.mjs`. It makes no coverage or "full
  functionality" claims, and the reminder "Check the saved pack before
  leaving coverage" stays.

D11. Unchanged: `X-SC-Offline`, the saved-at banner, `bannerText`,
`stampedHeaders`, the ENC `TILE_CAP` (1,500) and zoom 8–12, the basemap plan,
`sc-data` limits, the coastal snapshot contract, the seafloor no-cache rule,
canonical feeds and the producer pipeline.

## Source-to-cache matrix

"Pack" is `sc-pack-<region>-<time>`. "Recent" is `sc-data` (bounded, 150
entries). "Coastal" is `sc-coastal-snapshot-*` plus `sc-coastal-index`.

| Source (request key) | Saved today | Proposed | Cache | SW route offline | Offline gate (reader) |
| --- | --- | --- | --- | --- | --- |
| Region directory, config, manifest, coverage, assets, shared files | Pack files phase | unchanged | Pack | `data`, newest copy | each file's own checks |
| `/api/forecast`, `/api/intelligence`, `/api/daily?part=` (swell, wind, rules) | Pack files phase | unchanged | Pack | `data` | forecast run age |
| Tides, NWS alerts | Pack files phase | unchanged | Pack | `data` (tides by dataset key) | own ranges |
| ENC chart tiles (`__skippercast-tile/...`) | Pack tiles phase, ≤1,500, z8–12 | unchanged | Pack | `tile` | none (chart image) |
| v2 shell, hashed files, basemap ranges | Pack v2 extras | unchanged | Pack | `shell`/`precached`/`basemap` | none |
| `/feeds/conditions/regions/<id>/habitat-dynamics.json` (regional path) | Pack files phase (separate fetch from tiles) | Ocean phase overwrites it with the validated bytes; sha256 in meta | Pack (+ Recent from browsing) | `data`, complete-first selection (D8) | region id, schema, layer shape |
| `.../habitat-tiles/sst-analysis-*.json` | Only if viewed this session (copied from Recent) | Whole layer, D4–D6 caps and gates | Pack | `data` | length, SHA-256, identity; 72 h age at the current clock |
| `.../habitat-tiles/wcofs-surface-forecast-*.json` | Only if viewed this session | Whole layer, D4–D6 | Pack | `data` | as above; 36 h from `issued_at`; frame deadlines |
| `.../habitat-tiles/chlorophyll-*` | no | no (no reader) | — | — | — |
| `/feeds/tiles/seafloor/...` | never | never | — | not cached (`routeFor` null) | Worker expiry gate |
| `/api/habitat` | no | no | — | `data` if browsed | — |
| `/api/coast/report`, `/ocean`, `/history` (Morro Bay, Cambria) | Coastal readings save only | unchanged; the pack only reads the pointer for the UI line | Coastal | `coastal`, complete committed snapshot only | product schema, generated_at, byte limits |

## Proposed tests

Every test is offline and in Node, using the existing fakes (`tests/test_sw.mjs`
vm `self`, the synthetic `feed()`/`server()` in `tests/test_habitat_feed.mjs`
and `tests/helpers/wcofs-feed.mjs`). A new `tests/test_ocean_pack.mjs` holds the
pack-phase tests.

First save:

1. For a synthetic regional region, the pack holds the manifest and every SST
   and WCOFS tile. `meta.ocean.path` is `regional` and both layers are `saved`,
   with tile counts, bytes, `usable_until`, and a manifest sha256 equal to the
   stored bytes' hash.
2. The manifest stored in the pack is the copy the ocean phase validated, not
   the files-phase copy. Test this by making the server change the manifest
   between the two fetches.
3. For Morro Bay and Cambria (the real `dist/regions/*/region.json`),
   `path` is `coastal-report`. No `habitat-tiles/` keys are in the pack, no
   `sc-coastal-*` cache is created or changed, and `coastal` mirrors the
   committed pointer (or `null`).
4. A region whose manifest is 404 gives `path: 'none'`, and the pack still
   commits.
5. Guard test: no ocean tile is fetched outside `savePack`. Check page load,
   `online` events and SW install/activate. `/feeds/tiles/seafloor/` stays
   uncached.

Partial save:

6. One WCOFS tile returns 500, one has a wrong SHA-256, and one comes back with
   `X-SC-Offline`. Each case makes WCOFS `failed` with the right `reason`, and
   none of its tiles remain in the pack. SST is still `saved`, and the pack
   commits.
7. A manifest whose declared bytes pass `OCEAN_BYTE_CAP` after SST gives WCOFS
   `over-cap` with no WCOFS fetch. More than 64 tiles, or a tile over
   5,000,000 B, refuses that layer before any fetch. A body longer than its
   declared bytes is cut off at the limit.
8. A layer that is `stale`, past `max_age_hours`, missing
   `data_retrieved_at`, or WCOFS without `surface_only` is `not-current`, and
   none of its tiles are fetched.
9. Cancelling during the ocean phase deletes the whole candidate pack, and the
   previous pack and the coastal snapshot are unchanged.

Offline startup:

10. The SW and readers run together with `fetch` rejecting. The manifest and
    tiles are answered from the pack with `X-SC-Offline`. `regionalSST` and
    `regionalCurrents` return `ready`, the layers draw, and the banner shows
    the pack's saved-at.
11. D8: a newer `sc-data` manifest whose tiles are absent does not shadow the
    pack's complete copy. A newer `sc-data` manifest whose tiles are all
    present does win. With no complete copy anywhere, the behaviour is today's:
    `network: true` and "not saved for offline" with `TILES_NOT_SAVED`.
12. No pack exists: the result matches PR #773's tests exactly (regression
    guard).
13. Coastal-report region offline with a committed coastal snapshot: the
    layers read the snapshot, and no regional manifest or tile is requested.
    Without a snapshot: `COAST_NOT_SAVED`.

Expiry:

14. With the clock past `issued_at + 36 h`, saved WCOFS gives `listed` and
    "no fresh frame · last …". It is not drawn and not labelled "not saved".
    With the clock past SST `data_at + 72 h`, the stale reason
    "no fresh analysis · last <date>" is shown.
15. A WCOFS frame's own deadline still withdraws the drawn frame offline
    (existing `expiresAt` behaviour).
16. `usable_until` in the meta equals the reader's cut-off for both layers, at
    the boundary (one millisecond before and at the limit).
17. A tampered saved tile (bytes changed in the pack) is refused offline by
    the reader's SHA-256 check (`error`, not `network`), so the layer shows
    "unavailable", not saved data.

Separation and unchanged contracts:

18. Coastal save, delete and replace never touch `sc-pack-*`. Pack save,
    replace and delete never touch coastal caches. The SW `coastal` route
    ignores pack contents.
19. `X-SC-Offline`, `stampedHeaders`, `bannerText` and the PR #773 copy tests
    still pass. `TILE_CAP` and the Morro Bay budget test in `tests/test_trip.mjs`
    are unchanged.

## Proposed implementation cards (after this plan is approved)

1. SW: complete-first habitat manifest selection (D8), with tests 11, 12 and
   18. This is small and independent, and it fixes today's shadowing hazard
   for opportunistically viewed tiles too.
2. Ocean pack phase and meta (D1–D7, D9), with tests 1–10, 13, 14, 16 and 17.
   Depends on card 1.
3. Trip dialog coverage lines and copy (D10), with tests 15 and 19, plus the
   copy lint. Depends on card 2. Also update `docs/web-app.md` "Data, storage
   and offline".

Each card goes in its own signed-off PR with a different-model review. Merges
follow the normal deploy gate (#766, merged). No card enables prefetch or
changes producer data.

## Open questions (non-blocking, with proposed defaults)

- Should there be an opt-out toggle for ocean tiles? Default: no. The measured
  worst case is about 4.3 MB, and the pack already holds up to 1,500 chart
  tiles, the basemap and about 2.2 MB of app files. Card 2 records the ocean
  share of `meta.bytes` on a real save. Revisit the toggle if that share
  passes 25 %.
- Should the 12 MB cap be per region instead? Default: one cap. Southern
  California is the only region above 1 MB. If its WCOFS grows past the cap,
  the layer reports `over-cap` and does not silently shrink.
