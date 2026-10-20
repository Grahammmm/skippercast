# Plan: explicit ocean-data coverage for offline chart packs

Status: proposal (planning only), revised after review round 1. Kanban
t_21970644, a follow-up from BP CI6-05 (t_a64baa00, PR #773, issue #767).
Nothing here changes code, data, gates or prefetch. Implementation needs
separate cards, each with its own review.

## Why

A chart pack (`dist/offline-pack.js`, `web/trip.ts` FE-51) saves the region's
files, forecast bundle, NOAA ENC chart tiles and the v2 basemap. It does not
deliberately save the SST or WCOFS tiles that the v2 Water temp and Currents
layers read. Two things put ocean data into a pack today, both by accident:

- The files phase saves the region's `habitat_feed` URL. That is the
  cross-origin `raw.githubusercontent.com/.../habitat-dynamics.json`. No v2
  reader requests it: `web/map/habitat-feed.ts` reads the same-origin
  `/feeds/conditions/regions/<id>/habitat-dynamics.json`
  (`habitatManifestURL`).
- After the files phase, `savePack` copies every `sc-data` entry stamped
  after `sessionStart` into the pack (`dist/offline-pack.js:90–104`). That
  copy has no filter. It can bring in the same-origin manifest and any tiles
  the page fetched: tiles from an older publication, part of a layer, or
  another region's tiles if the user switched regions during the session. No
  ocean byte, tile or identity cap applies to it.

PR #773 made the gap visible ("not saved for offline"), and the Trip dialog
says the tiles are not prefetched.

Morro Bay and Cambria do not read those tiles at all. Their place binds a coast
report, so Water temp and Currents come from the report and ocean packet
(`/api/coast/report`, `/api/coast/ocean`). Those are saved separately and
explicitly through Coastal readings (`dist/coastal-offline-core.js`). When the
packet fails, no other source is shown (`web/map/currents.ts`
`currentsStatus`, `web/map/sst.ts` `analysisStatus`).

This plan proposes a bounded, explicit contract. Ocean data enters a pack only
when the user presses Save for offline, and only through one ocean phase. That
phase runs only for regions that read the tiles. It saves whole layers or
nothing, records the coverage, and applies the same age and hash gates the
readers already use. Every other route that puts ocean data into a pack is
closed.

## Measured sizes and clocks (conditions branch, generated 2026-10-20T18:37:15Z)

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

The same manifests show each layer's clocks (southern-california; Morro Bay
is within a minute of it):

| Layer | Data clock | Retrieval (`sources.<id>.data_retrieved_at`) | Latest instant the readers draw (D6) | Left at generation |
| --- | --- | --- | --- | --- |
| SST | analysed 2026-10-19T12:00Z | 2026-10-20T13:09:57Z | 2026-10-22T12:00Z | about 41 h |
| WCOFS | issued 2026-10-20T03:00Z (frames to 10-23T03:00Z) | 2026-10-20T13:50:04Z | 2026-10-20T19:50:04Z | about 1 h 13 min |

WCOFS is limited by its retrieval clock, not by its 36-hour issue age. The
readers withdraw a WCOFS field 6 hours after `data_retrieved_at`
(`packages/coast/src/map-sources.ts:29`,
`packages/coast/src/state/current-layer.ts:31–32`). A pack therefore cannot
keep WCOFS drawable for longer than the producer's last retrieval plus 6 hours,
and this plan does not change that gate. The conditions branch is rewritten on
each publish, so its history shows only this one manifest, and how often the
retrieval refreshes is not measured here (see Open questions).

## Decisions

D1. Scope. Only the two layers the v2 readers draw from a regional feed are
saved: `sst-analysis` (`regionalSST`) and `wcofs-surface-forecast`
(`regionalCurrents`) in `web/map/habitat-feed.ts`. Temp contrast
(`regionalContrast`, PR #791) reads the same `sst-analysis` tiles, so a saved
SST layer is also present for it offline. Its own gates decide, unchanged. It
reports a failed read as `error` without a network flag, and this plan makes
no Trip-line or coverage claim for it; offline labelling for Temp contrast
would be a separate card. These stay out of scope:

- chlorophyll and any other manifest layer (no reader);
- HF radar (published only in the coast packet);
- seafloor habitat tiles under `/feeds/tiles/seafloor/` (`dist/sw.js` never
  caches them, because a saved copy would outlive the Worker's expiry gate;
  this is unchanged);
- `/api/habitat` (the Worker's JSON copy of the feed; the v2 app reads
  `/feeds/conditions/...` directly);
- the cross-origin `habitat_feed` copy that the files phase saves. It stays
  exactly as it is, outside the ocean accounting. No reader uses it, and
  removing it belongs to a separate cleanup card if anyone wants it.

"Ocean key" below means a same-origin URL whose path matches
`/feeds/conditions/regions/<id>/habitat-dynamics.json` or
`/feeds/conditions/regions/<id>/habitat-tiles/<file>`, for any `<id>`. One
shared predicate, `isOceanKey(url, origin)` in `dist/offline-core.js`, defines
it. The pack and the service worker both use it.

D2. Regional tiles and coastal snapshots are separate paths. At save time the
pack decides the region's ocean path with the same call the layers use:
`resolveReportBinding(regionPlace(region, ...))`.

- `regional`: no report binds (every region except Morro Bay and Cambria
  today). The ocean phase saves the region's own ocean layers (D3–D7).
- `coastal-report`: a report binds (Morro Bay, Cambria). The pack holds no
  ocean keys at all (D3a), because the readers would never use them. The pack
  writes nothing to `sc-coastal-snapshot-*` or `sc-coastal-index`. It only
  reads the committed snapshot pointer (`readCoastalSnapshot`, read-only) so
  the dialog can say whether Coastal readings are saved.
- Coastal readings never write to `sc-pack-*`. The coastal caches, the
  `skippercast-coastal-snapshot:<origin>` lock, the 8/8/16/32 MiB limits, the
  three-product all-or-nothing commit and `X-SC-Offline-Save` stay exactly as
  they are.

D3. One writer for ocean keys. The ocean phase is the only code that writes
ocean keys into a pack. It runs as a new step in the v2 pack extras
(`web/trip.ts` `v2Pack`, the `more` hook) and lives in a new module, e.g.
`web/map/ocean-pack.ts`. That module reuses `habitatManifestURL`,
`habitatTileURL`, `tileRows` and the manifest checks from `habitat-feed.ts`,
exporting the existing `layerOf` instead of copying it. Only v2 draws these
layers; v1's loader was retired in FE-61. The phase runs only inside the
explicit Save action. Nothing is fetched on page load, on reconnect, on a timer
or in the service worker: no prefetch, no background sync, no automatic
refresh.

D3a. The `sc-data` copy skips ocean keys. In `savePack`, the loop that copies
recent `sc-data` responses into the candidate pack skips every key where
`isOceanKey` is true, for every region, before reading the body. This is the
only change to that loop. Everything else it copies (forecast, tide and layer
requests) is unchanged. Three things follow from this:

- A coastal-report pack holds no ocean keys whatever the user browsed.
- Old-publication, partial or other-region tiles never enter a pack. The
  ocean caps (D4) and `meta.ocean.bytes` (D9) cover every ocean byte in the
  pack, because no ocean byte arrives any other way.
- Recently viewed ocean tiles are still served offline from `sc-data` itself,
  as today. They are only no longer copied into the pack.

The files phase (`packRequests`) contains no ocean key today, and a test keeps
it that way.

D4. Caps. All caps are checked against the manifest's declared sizes before
any tile is fetched, and again while the bytes are read.

| Cap | Value | Reason |
| --- | --- | --- |
| Manifest bytes | 1 MiB, read as a stream and cut off at the limit | Largest observed is 56 KB |
| Tiles per layer | 64 | Same as the reader's `MAX_TILES` |
| Bytes per tile | 5,000,000 | Same as the reader's `MAX_TILE_BYTES` |
| Ocean total per pack (manifest + saved layers) | 12 MB (`OCEAN_BYTE_CAP`) | About 2.8× the largest observed (southern-california, about 4.3 MB) |
| Minimum drawable time left at save (`MIN_WINDOW`) | 60 min | A layer the readers will withdraw within the hour is not worth storing |
| Concurrency | 4 | Same as the pack's `CONCURRENCY` |

The phase plans SST first (small, longest life), then WCOFS. A layer that
would exceed the remaining budget is skipped whole and recorded as `over-cap`.
A layer is never trimmed to fit. The manifest's own bytes count against the
total first.

D5. Layer-atomic saves, by buffering. Each layer's tiles are fetched into
memory and validated there, all of them, before any is written to the pack:

- each is fetched with `cache: 'no-cache'`;
- the answer must be `ok` with no `X-SC-Offline` header, so an older save is
  never re-stamped as new data;
- `tileRows` must pass: length, SHA-256, region, layer, fields, grid, bounds
  and frame times.

Only when every tile of the layer passes are they written, through the
existing extras `put`, which adds each body's length to the pack's `bytes`.
If any tile fails, the buffered bodies are dropped. Nothing of that layer
reaches the pack, and the layer is recorded as `failed` with the first reason.
So the extras API needs no delete or byte-adjust operation, and a layer that
fails validation leaves no keys and no counted bytes behind. A failure while
writing is handled in D5a. Memory use is bounded by
`OCEAN_BYTE_CAP`. The readers refuse a partial grid anyway, so a partial layer
would only cost bytes while promising coverage.

The manifest is written last, under `habitatManifestURL(region.id, origin)`,
from the exact bytes the phase validated. It is written whenever the path is
`regional` and the manifest passed its checks, even if no layer was saved,
because the readers then report offline what the manifest says (stale, or not
saved) instead of a bare network failure. Cancelling at any point deletes the
whole candidate pack, as now.

D5a. Two kinds of failure. Buffering makes validation all-or-nothing. It does
not make the writes a transaction: the extras `put` adds the body's length
to `bytes` before `await cache.put` and has no rollback
(`dist/offline-pack.js:115`). So the plan separates two kinds of failure:

- Nonfatal: everything decided before the first ocean write. That covers the
  manifest fetch and checks, the caps (D4), save-time eligibility (D6), and
  each tile's fetch, HTTP status, `X-SC-Offline`, length, SHA-256 and identity
  (D5). These record a layer as `failed`, `over-cap` or `not-current` (or the
  manifest as `stored: false`). The pack still commits, and no key or byte of
  that layer was ever written.
- Fatal: any rejection from `put` while writing a validated layer or the
  manifest. This includes `QuotaExceededError`, `InvalidStateError` and any
  other `cache.put` error. The ocean phase does not catch it. It rethrows it
  as `Error('storage on this device is full or unavailable. Saved regions are
  unchanged.', {cause})`, and `savePack`'s existing outer catch deletes the
  whole candidate cache (`dist/offline-pack.js:130–132`). `PACK_META` is never
  written. Older packs of the region are deleted only after `PACK_META` is
  written (`dist/offline-pack.js:126`), so the prior committed pack stays
  exactly as it was. `track('offline_saved')` is not called, and the Trip
  dialog shows its existing "Could not save: …" status, not "Saved". The
  counted `bytes`, including the failed body's, die with the candidate,
  because no meta records them. The phase writes a layer's buffered tiles
  one at a time (fetching stays at concurrency 4), so no ocean `put` is still
  in flight when the rejection reaches the outer catch and the candidate is
  deleted.

The plan does not commit a pack that holds part of a layer, and it does not
retry without the ocean layers (see Open questions). It does not swallow a
write error in order to keep a pack, so it needs no rollback or byte-adjust
API, and the extras API stays as it is. This is deliberately stricter than
the other phases today. `store` (files, chart tiles, v2 shell and hashed
files) catches a `cache.put` error and records a miss, after counting the
bytes (`dist/offline-pack.js:65–78`). A basemap `put` rejection is caught by
the `getZxy` try and also becomes a miss (`web/trip.ts:192`). Those are
existing behaviours outside ocean keys, and this plan leaves them alone
(D11). Ocean layers are different because the meta promises a whole,
verified layer. A swallowed write would leave part of a layer in the pack
under a `failed` record, so the ocean phase never writes through `store` and
never swallows a `put` rejection. A `put` rejection after the signal has
aborted is still the cancellation path (`AbortError`, "Cancelled").

D6. What `saved` means, and the drawable deadline. `saved` means
integrity-complete storage of a layer that the readers would draw at save time
for at least `MIN_WINDOW`. It does not mean the layer is drawable later. Each
layer gets a conservative deadline, `drawable_until`, computed from the same
clocks and comparisons the readers use. At or after this instant the readers
certainly refuse the layer. Before it, drawing still depends on the selected
hour and the grid.

- SST (`sst-analysis`):
  `drawable_until = min(analysed_at, retrieved_at) + max_age_hours`.
  `analysed_at` is the latest populated frame time (as `regionalSST` picks
  it), and `retrieved_at` is `sources['sst-analysis'].data_retrieved_at`.
  The readers' gates: `regionalSST` loads only while
  `now − analysed_at < max_age` (`habitat-feed.ts:193`). `judge` then
  requires both clocks fresh, with `−5 min ≤ now − t < limit`
  (`web/map/sst.ts:105, 165`), and its re-judge timer uses this same
  `min(...) + limit` (`sst.ts:299`). Before the deadline, it is still not
  drawn if the analysis is later than the selected hour, or if the grid
  cannot be drawn.
- WCOFS (`wcofs-surface-forecast`):
  `drawable_until = min(retrieved_at + 6 h, issued_at + 36 h, issued_at + max_age_hours)`.
  The readers' gates: `regionalCurrents` loads only while
  `now − issued_at < max_age` (`habitat-feed.ts:282`).
  `selectCurrentFrame` refuses once `now − fetchedAt > 6 h` or
  `now − issuedAt > 36 h`, and refuses either clock more than 5 min ahead
  (`map-sources.ts:29, 36`). `selectedCurrent` keeps a frame only while
  `min(fetchedAt + 6 h, issuedAt + 36 h) > now` (`current-layer.ts:31–32`).
  Together, a field is drawable only while `now < drawable_until`. Before the
  deadline, it is still not drawn unless the selected hour lies between the
  first and last frame and within 90 min of a populated frame, and the frame's
  grid can be drawn.

Save-time eligibility uses exactly these rules. A layer is fetched only if
status is `ok` or `retained`; the reader's load gate passes at the save clock;
`data_retrieved_at` is present and not more than 5 min ahead of the clock;
WCOFS has `surface_only: true` and a valid `issued_at`; and
`drawable_until − now ≥ MIN_WINDOW`. Otherwise the layer is recorded as
`not-current`, with `why` set to `status`, `age`, `retrieval`,
`no-retrieval`, `not-surface`, `future-clock` or `short-window`, and no tiles
are fetched. In particular, WCOFS retrieved more than 6 h ago but issued less
than 36 h ago is `not-current` (`retrieval`), never `saved`.

Offline, the readers re-judge every gate at the current clock exactly as they
do now. The pack adds no expiry logic, does not extend `max_age_hours` or the
6-hour retrieval limit, and gives no way around them. After its deadline,
saved data shows the readers' existing reasons: "no fresh analysis · last …"
for SST, "no fresh frame · last …" for WCOFS. It is never drawn and never
labelled "not saved".

D7. Hash and identity gates. The pack records the SHA-256 and length of the
manifest bytes it stored. Tile paths are content-addressed (`-<16 hex>.json`),
and the reader re-verifies every tile's SHA-256 and length against the manifest
on every read, including offline. The service worker verifies no hashes (D8
checks presence only).

D8. Offline manifest selection that keeps the pack's promises (the only
service-worker change). Today `newestSaved` returns the newest copy across
`sc-data` and all `sc-pack-*` caches. For the habitat manifest, that can
silently undo a pack. Suppose a later online visit stores a newer manifest in
`sc-data` but never fetched its tiles, or `DATA_LIMIT` (150) evicted them.
That manifest then shadows the pack's copy, and a layer the pack saved is
refused offline.

There are at most two candidates for a region's manifest URL. One is the
committed pack: an `sc-pack-<region>-*` cache that holds `PACK_META`. Packs
of a region replace each other, and a candidate pack that is still saving has
no meta, so it is not a candidate. The other is `sc-data`, which holds one
entry per URL. For a candidate manifest `m`, `complete(m)` is the set of
layers in {`sst-analysis`, `wcofs-surface-forecast`} whose status is `ok` or
`retained`, that list at least one tile, and whose every tile URL
(`habitatTileURL` resolution) is present in `sc-data` or a committed pack. The
worker parses only manifests of at most 1 MiB. A larger or unparsable
manifest has `complete = ∅`.

Rule, applied after a network failure on a request where `isOceanKey` is true
and the path ends in `habitat-dynamics.json`:

1. If only one candidate exists, answer with it (today's behaviour).
2. If both exist, answer with the `sc-data` copy only if it is newer
   (`X-SC-Saved-At`) and `complete(sc-data) ⊇ complete(pack)`. Otherwise
   answer with the pack copy.

What this guarantees:

- Every layer the pack saved stays served offline, unless a newer copy that is
  also complete for that layer replaces it.
- A pack with SST saved and WCOFS failed or over-cap is not displaced by a
  newer `sc-data` manifest with no tiles cached. SST stays drawable (within
  its deadline), and WCOFS shows "not saved for offline" because its tiles
  miss, the network error that PR #773 already handles.
- If the pack saved no layer (`complete(pack) = ∅`), any newer `sc-data` copy
  wins, which is today's newest-wins.
- When the two sets do not contain each other (pack {SST}, newer `sc-data`
  {WCOFS}), the pack wins. Offline then matches the pack's record. The layer
  only browsed is not shown, and its line says what the pack saved.

The worker checks presence only, no hashes and no ages. The reader still runs
every source, integrity and age gate on whatever it is given. Tiles keep plain
newest-wins: they are content-addressed, so every copy of one path holds the
same bytes. Other data routes are unchanged.

Alternatives rejected: requiring every loadable layer to be complete
(round 1). That drops a partly saved pack in favour of a newer copy with
nothing cached. Always preferring the pack is also rejected, because a newer
copy that is complete for every saved layer would lose to it for no reason.
Per-layer manifest answers would need a reader change and a second request
key, for no gain over the rule above.

D9. Metadata. The pack meta gains an additive `ocean` record, and
`schema_version` stays 1. Older readers ignore unknown fields, as they do the
`v2` record. `meta.missing` keeps meaning "files". Ocean misses are listed
only under `ocean`.

```json
"ocean": {
  "schema_version": 1,
  "path": "regional",
  "manifest": {"url": "/feeds/conditions/regions/<id>/habitat-dynamics.json", "sha256": "<64 hex>", "bytes": 46763, "generated_at": "...", "stored": true},
  "bytes": 63893,
  "cap_bytes": 12000000,
  "layers": {
    "sst-analysis": {"state": "saved", "tiles": {"saved": 8, "listed": 8}, "bytes": 17130,
      "data_at": "2026-10-19T12:00:00Z", "retrieved_at": "2026-10-20T13:08:37Z", "max_age_hours": 72,
      "drawable_until": "2026-10-22T12:00:00Z"},
    "wcofs-surface-forecast": {"state": "not-current", "why": "short-window", "tiles": {"saved": 0, "listed": 8}, "bytes": 0,
      "data_at": "2026-10-20T03:00:00Z", "retrieved_at": "2026-10-20T13:08:45Z", "max_age_hours": 36,
      "drawable_until": "2026-10-20T19:08:45Z"}
  }
}
```

- `path` is `regional`, `coastal-report` (then `manifest` is `null`,
  `layers` is `{}`, `bytes` is 0, and `coastal` is `{saved_at}` or `null`,
  read from the committed snapshot pointer) or `none` (the region publishes no
  manifest: 404).
- `state` is one of `saved`, `failed`, `over-cap`, `not-current`, `absent`
  (the layer is not in the manifest) or `cancelled`.
- `reason`, when `state` is `failed`, is one of `network`, `http`,
  `offline-copy`, `length`, `integrity`, `identity` or `byte-limit`. A failed
  manifest (`manifest.stored: false`, with `reason`) makes both layers
  `failed` with reason `manifest`.
- `why`, when `state` is `not-current`, is as in D6.
- `data_at` is the SST analysis time or the WCOFS `issued_at`. `retrieved_at`
  is the source's `data_retrieved_at`. `drawable_until` is the D6 deadline,
  recorded whenever the clocks are valid, for every state. It is display-only;
  the readers' own gates decide.
- `bytes` (in `ocean`) is the manifest bytes plus the bytes of saved layers.
  It is also counted once inside `meta.bytes`, through `put`. Bytes of failed,
  over-cap or not-current layers are never counted, because they were never
  written (D5).

Nonfatal ocean failures (D5a: fetch, validation, caps and eligibility, all
decided before any ocean write) never fail the pack, and they are recorded
here. A fatal one, a storage write rejected while writing a validated layer
or the manifest, fails the whole save: no meta is written, the candidate is
deleted, and the prior pack is kept (D5a). Otherwise only a missing region
config fails the pack, as now. Cancelling deletes the whole candidate pack,
as now. Replacing a pack deletes
the older pack together with its ocean entries. It never touches coastal
caches or `sc-data`.

D10. UI scope (`web/app/Trip.tsx` only):

- Each saved pack gets one line each for Water temp and Currents. The line
  never says "usable" or promises display. It gives the last moment the data
  can be shown, and the condition. Examples:
  - "saved · not shown after Wed 5 am · only for hours on or after the analysis"
  - "saved · not shown after Tue 12 pm · only for forecast hours"
  - "not saved: failed check"
  - "not saved: too large for this pack"
  - "not saved: forecast too old to show offline" (`not-current`, `why` of
    `retrieval` or `short-window`)
  - "not saved: no current data at save time"
- Once `drawable_until` has passed, the line reads "saved · past its age
  limit" and no time is promised.
- For coastal-report regions the line reads "from Coastal readings (saved
  <time> / not saved)", with the existing pointer to Coastal readings.
- The sentence "Water temp and current tiles are not prefetched…" is replaced
  only once the ocean phase ships. Until then it stays true.
- No new toggle (see Open questions). No progress beyond an `ocean` phase in
  the existing progress callback.
- New copy passes `scripts/check_copy.mjs`. It makes no coverage or "full
  functionality" claims, and the reminder "Check the saved pack before
  leaving coverage" stays.

D11. Unchanged: `X-SC-Offline`, the saved-at banner, `bannerText`,
`stampedHeaders`, the ENC `TILE_CAP` (1,500) and zoom 8–12, the basemap plan,
`sc-data` limits and its network-first storing, the files phase and
`packRequests`, the coastal snapshot contract, the seafloor no-cache rule,
canonical feeds, the producer pipeline, and every reader gate
(`max_age_hours`, the 6-hour retrieval limit, the 36-hour issue limit, the
5-minute clock allowance and the frame rules).

## Source-to-cache matrix

"Pack" is a committed `sc-pack-<region>-<time>`. "Recent" is `sc-data`
(bounded, 150 entries). "Coastal" is `sc-coastal-snapshot-*` plus
`sc-coastal-index`.

| Source (request key) | In a pack today | Proposed | Cache | SW route offline | Offline gate (reader) |
| --- | --- | --- | --- | --- | --- |
| Region directory, config, manifest, coverage, assets, shared files | Files phase | unchanged | Pack | `data`, newest copy | each file's own checks |
| `/api/forecast`, `/api/intelligence`, `/api/daily?part=` (swell, wind, rules) | Files phase | unchanged | Pack | `data` | forecast run age |
| Tides, NWS alerts | Files phase | unchanged | Pack | `data` (tides by dataset key) | own ranges |
| Other recent same-origin and data-host responses | `sc-data` copy (since `sessionStart`) | unchanged | Pack | `data` | own checks |
| ENC chart tiles (`__skippercast-tile/...`) | Tiles phase, ≤1,500, z8–12 | unchanged | Pack | `tile` | none (chart image) |
| v2 shell, hashed files, basemap ranges | v2 extras | unchanged | Pack | `shell`/`precached`/`basemap` | none |
| Cross-origin `habitat_feed` (raw.githubusercontent) | Files phase | unchanged, outside ocean accounting, unread by v2 | Pack | `data` | — (no reader) |
| `/feeds/conditions/regions/<id>/habitat-dynamics.json` (regional path) | Only via the unfiltered `sc-data` copy | Ocean phase only (validated bytes, sha256 in meta); `sc-data` copy skips it (D3a) | Pack (+ Recent from browsing) | `data`, D8 selection between pack and Recent | region id, schema, layer shape |
| `.../habitat-tiles/sst-analysis-*.json` | Only via the `sc-data` copy, any publication or region | Ocean phase only, whole layer, D4–D6 | Pack (+ Recent) | `data`, newest copy | length, SHA-256, identity; both clocks, `min(analysed, retrieved) + 72 h` at the current clock |
| `.../habitat-tiles/wcofs-surface-forecast-*.json` | as above | Ocean phase only, whole layer, D4–D6 | Pack (+ Recent) | `data`, newest copy | as above; `min(retrieved + 6 h, issued + 36 h)`; selected hour within frames and 90 min of one |
| `.../habitat-tiles/chlorophyll-*` | via `sc-data` copy only if fetched (no reader fetches it) | never (skipped by D3a; no reader) | — | — | — |
| `/feeds/tiles/seafloor/...` | never | never | — | not cached (`routeFor` null) | Worker expiry gate |
| `/api/habitat` | via `sc-data` copy if browsed | unchanged (not an ocean key) | — | `data` if browsed | — |
| `/api/coast/report`, `/ocean`, `/history` (Morro Bay, Cambria) | never (Coastal readings only) | unchanged; the pack only reads the pointer for the UI line | Coastal | `coastal`, complete committed snapshot only | product schema, generated_at, byte limits |

## Proposed tests

Every test is offline and in Node, using the existing fakes (`tests/test_sw.mjs`
vm `self`, the synthetic `feed()`/`server()` in `tests/test_habitat_feed.mjs`
and `tests/helpers/wcofs-feed.mjs`). A new `tests/test_ocean_pack.mjs` holds the
pack-phase tests. Clocks are injected, and none of the tests reads the real
time.

First save:

1. For a synthetic regional region, the pack holds the same-origin manifest
   and every SST and WCOFS tile. `meta.ocean.path` is `regional`, and both
   layers are `saved` with tile counts, bytes, `data_at`, `retrieved_at` and
   `drawable_until` as in D6. The manifest sha256 equals the stored bytes'
   hash. `meta.ocean.bytes` equals the summed body sizes of every ocean key
   in the pack, and `meta.bytes` counts them once.
2. The manifest stored in the pack is the copy the ocean phase validated.
   Test this by making the server change the manifest between the phase's
   read and any other request, and check that the files phase stores no
   ocean key (`packRequests` output has none).
3. For Morro Bay and Cambria (the real `dist/regions/*/region.json`), `path`
   is `coastal-report` and `ocean.bytes` is 0. No `sc-coastal-*` cache is
   created or changed, and `coastal` mirrors the committed pointer (or
   `null`). This runs with a prepopulated `sc-data` (see 7a): the pack still
   holds no ocean key.
4. A region whose manifest is 404 gives `path: 'none'`, and the pack still
   commits.
5. Guard test: no ocean tile is fetched outside `savePack`. Check page load,
   `online` events and SW install/activate. `/feeds/tiles/seafloor/` stays
   uncached.

Partial save:

6. One WCOFS tile returns 500, one has a wrong SHA-256, and one comes back with
   `X-SC-Offline`. Each case makes WCOFS `failed` with the right `reason`. No
   WCOFS key is in the pack, and WCOFS adds nothing to `ocean.bytes` or
   `meta.bytes`, including the bytes of tiles that passed before the failing
   one. SST is still `saved`, and the pack commits.
7. Caps. A manifest whose declared bytes exceed `OCEAN_BYTE_CAP` after SST
   gives WCOFS `over-cap`, with no WCOFS fetch. More than 64 tiles, or a tile
   over 5,000,000 B, refuses that layer before any fetch. A body longer than
   its declared bytes is cut off at the limit. A manifest over 1 MiB is
   `failed` (`manifest`), and no ocean key is written.
   7a. Prepopulated `sc-data` before saving: stamped after `sessionStart`, it
   holds this region's manifest and tiles from an older publication, half of
   a layer, another region's manifest and tiles, a chlorophyll tile, and
   unrelated data responses. After the save, every ocean key in the pack
   belongs to the ocean phase's manifest and its `saved` layers. None of the
   prepopulated ocean entries was copied. The unrelated responses were
   copied (`files.from_session` counts them). `meta.ocean.bytes` matches the
   retained ocean keys. With a 12 MB cap and over-cap WCOFS, no WCOFS key is
   present from any source.
8. Save-time eligibility (D6). Each case is `not-current` with the given
   `why`, and none of its tiles is fetched: a `stale` status; SST past
   `analysed + 72 h`; WCOFS past `issued + 36 h`; WCOFS with `issued` 10 h
   ago and `retrieved` 6 h 1 min ago (`retrieval`), while the same manifest
   with `retrieved` 4 h 30 min ago saves; a missing `data_retrieved_at`;
   `retrieved` 6 min ahead of the clock; WCOFS without `surface_only`; and a
   window of 59 min left (`short-window`), while one of 61 min saves. SST with
   different clocks (`retrieved` earlier than `analysed`, then later) gives
   `drawable_until` from the earlier one.
9. Cancelling during the ocean phase deletes the whole candidate pack, and the
   previous pack, `sc-data` and the coastal snapshot are unchanged.
9a. Fault injection, later tile write (D5a). A prior committed pack of the
   region exists. The fake `caches` makes `cache.put` reject with
   `QuotaExceededError` on the second WCOFS tile, after SST and the first
   WCOFS tile were written. Then: `savePack` rejects with the D5a storage
   message (with the original error as `cause`), and the Trip status is
   "Could not save: …", never "Saved". The candidate `sc-pack-<region>-*`
   cache is gone from `caches.keys()`. The prior pack's cache name, keys,
   bodies and `PACK_META` are byte-identical to before. `listPacks()` returns
   only the prior pack with its old meta. No new `PACK_META` exists anywhere,
   `track('offline_saved')` is not called, and `sc-data` and the coastal
   caches are unchanged. The same with the rejection on the first SST tile.
9b. Fault injection, manifest write. Both layers' tiles are written, and the
   final manifest `put` rejects. The checks are the same as 9a: no committed
   pack holds those tiles without their manifest, and the prior pack is kept.
9c. Fault injection, first save. 9a with no prior pack leaves no
   `sc-pack-<region>-*` cache at all. A nonfatal failure in the same run
   (WCOFS tile 500, as in test 6) with every `put` succeeding still commits,
   which shows the two kinds are kept apart. A `put` that rejects after the
   signal aborts gives "Cancelled. Nothing new was saved.", as in test 9.

Offline startup:

10. The SW and readers run together with `fetch` rejecting. The manifest and
    tiles are answered from the pack with `X-SC-Offline`. `regionalSST` and
    `regionalCurrents` return `ready`, the layers draw at a supported hour
    before `drawable_until`, and the banner shows the pack's saved-at.
11. D8 selection, one case each:
    (a) pack {SST, WCOFS} and a newer `sc-data` manifest with no tiles cached
    gives the pack;
    (b) pack {SST} and a newer `sc-data` copy {SST, WCOFS} gives `sc-data`;
    (c) pack {SST} and a newer `sc-data` copy {WCOFS} gives the pack;
    (d) pack ∅ and a newer `sc-data` copy gives `sc-data`, today's behaviour;
    (e) an older `sc-data` copy gives the pack;
    (f) a pack cache without `PACK_META` (a save in progress) is not a
    candidate;
    (g) an unparsable or over-1-MiB candidate counts as ∅.
12. Integrated partial save then offline (SST saved; WCOFS `failed` in one
    run, `over-cap` in another). Then, online, a newer publication's manifest
    lands in `sc-data` with none of its tiles cached. Offline afterwards,
    `regionalSST` is `ready` and Water temp draws from the pack.
    `regionalCurrents` is `error` with `network: true`, Currents shows
    "not saved for offline" (`TILES_NOT_SAVED`), and both match
    `meta.ocean.layers`.
13. No pack exists: the result matches PR #773's tests exactly (regression
    guard).
14. Coastal-report region offline with a committed coastal snapshot: the
    layers read the snapshot, and no regional manifest or tile is requested.
    Without a snapshot: `COAST_NOT_SAVED`.

Expiry (at the boundary, with an injected clock):

15. WCOFS retrieval limit. The manifest has `issued` 10 h before the save and
    `retrieved` 2 h before it. At `retrieved + 6 h − 1 ms` a supported hour
    draws. At `retrieved + 6 h`, with `issued + 36 h` still a day away, it is
    not drawn and shows "no fresh frame · last …", not "not saved". A second
    manifest where `issued + 36 h` comes first is withdrawn at that instant.
16. SST with different clocks. With `analysed` earlier than `retrieved`, SST
    is drawn at `analysed + 72 h − 1 ms` and shows "no fresh analysis ·
    last <date>" at `analysed + 72 h`. With `retrieved` earlier (synthetic),
    the cut-off is `retrieved + 72 h`. In both cases the cut-off equals
    `meta.ocean.layers['sst-analysis'].drawable_until`, and `sst.ts`'s
    re-judge timer fires at it.
17. Conditions before the deadline. SST is not drawn for an hour before
    `analysed`. WCOFS is not drawn for an hour outside its frames or more
    than 90 min from a frame. Each shows the readers' existing reason, and
    the Trip line's wording (D10) states these conditions.
18. A WCOFS frame's own deadline still withdraws the drawn frame offline
    (existing `expiresAt` behaviour).
19. A tampered saved tile (bytes changed in the pack) is refused offline by
    the reader's SHA-256 check (`error`, not `network`), so the layer shows
    "unavailable", not saved data.

Separation and unchanged contracts:

20. Coastal save, delete and replace never touch `sc-pack-*`. Pack save,
    replace and delete never touch coastal caches or `sc-data`. The SW
    `coastal` route ignores pack contents.
21. `X-SC-Offline`, `stampedHeaders`, `bannerText` and the PR #773 copy tests
    still pass. `TILE_CAP` and the Morro Bay budget test in `tests/test_trip.mjs`
    are unchanged. The existing reader gate tests in
    `tests/test_habitat_feed.mjs` and the `packages/coast` current tests pass
    without edits.

## Proposed implementation cards (after this plan is approved)

1. Shared predicate and SW selection: `isOceanKey` in `dist/offline-core.js`,
   and D8 in `dist/sw.js`, with tests 11, 13 and 20. This is small and
   independent, and it also fixes today's shadowing hazard for browsed
   tiles.
2. Pack integration and the ocean phase. Three parts: the `sc-data` copy
   filter in `dist/offline-pack.js` (D3a); a new `web/map/ocean-pack.ts`
   wired into `web/trip.ts` `v2Pack` (D1–D7), which exports `layerOf` from
   `habitat-feed.ts`; and the meta record (D9). Tests 1–10 (with 9a–9c), 12,
   14–16 and 19. Depends on card 1. The extras API (`store`/`put`) is
   unchanged: layers are buffered (D5), and a rejected ocean `put` is fatal and
   rethrown, never caught (D5a). The new storage-failure message passes the
   copy lint.
3. Trip dialog coverage lines and copy (D10), with tests 17, 18 and 21, plus
   the copy lint. Depends on card 2. Also update `docs/web-app.md` "Data,
   storage and offline".

Each card goes in its own signed-off PR with a different-model review. Merges
follow the normal deploy gate (#766, merged). No card enables prefetch, changes
a reader gate or changes producer data.

## Open questions (non-blocking, with proposed defaults)

- WCOFS offline life. The readers' 6-hour retrieval limit means a pack can
  keep WCOFS drawable for at most 6 h after the producer's last retrieval. In
  the measured manifest that left about 1 h at generation. A pack saved the
  evening before a trip will usually record WCOFS as `not-current`
  (`retrieval`) and spend no bytes on it. Default: ship it that way, with the
  honest Trip line. Changing the retrieval limit or the producer's refresh
  cadence is a separate decision for the owner and the data pipeline, and
  this plan does not make it. Card 2 should record, on real saves, how often
  WCOFS was `saved` versus `not-current`, so that decision has numbers.
- Should there be an opt-out toggle for ocean tiles? Default: no. The measured
  worst case is about 4.3 MB, and the pack already holds up to 1,500 chart
  tiles, the basemap and about 2.2 MB of app files. Card 2 records the ocean
  share of `meta.bytes` on a real save. Revisit the toggle if that share
  passes 25 %.
- Should the 12 MB cap be per region instead? Default: one cap. Southern
  California is the only region above 1 MB. If its WCOFS grows past the cap,
  the layer reports `over-cap` and does not silently shrink.
- `MIN_WINDOW` of 60 min is a reversible default. Card 2 may tune it with
  review. It never lets a layer past the readers' own gates.
- On a storage write failure, should the save retry once without the ocean
  layers? Default: no. D5a fails the save and keeps the prior pack. A retry
  would need a second, ocean-free candidate and its own tests. If real saves
  show quota failures, revisit it as a separate card. That card should also
  look at the existing `store` and basemap paths, which record a failed write
  as a miss after counting its bytes.
