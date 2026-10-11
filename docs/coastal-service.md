# Coastal data service

`server/coast-data.ts` serves the coast map's public datasets from SkipperCast's
own storage: the report, ocean and history snapshots from the feeds SkipperCast's
collectors publish to the `FEEDS` R2 bucket (FE-84, FE-87), and the terrain,
imagery and habitat assets from the hashed R2 release (FE-85). Until FE-62 it
was a bounded bridge to the Fish Worker; that bridge is retired, and the Worker
reads no other origin. A dataset that is not published, valid and current is
unavailable (503), never filled from elsewhere.

- `/api/coast/report`, `/api/coast/ocean`, `/api/coast/history`: SLO packets,
  validated for schema, county and assembly-clock identity. Optional
  regional bindings are limited to Morro/Avila and Cambria/San Simeon. Other
  regions do not inherit these forecasts or observations.
- `/api/coast/habitat/release` and `/api/coast/habitat/tiles`: the published
  habitat release with its producer rights, hash and expiry gates. The common
  client must still validate the returned manifests and per-archive HEAD
  identity before displaying habitat.
- `/coast-data/data/...`: only enumerated public habitat files and flat coastal
  terrain/chart-model filenames. Private archives, receipts, percent-encoded
  aliases, traversal and arbitrary URLs are refused.

Only GET/HEAD are supported, and no request leaves the Worker, so client
cookies, identity, authorization, origin and referrer headers go nowhere.
Snapshot and geometry reads have bounded byte budgets; range requests require
exact offsets and length. Responses carry the asset's SHA-256 ETag and habitat
release header and are not cached, so expiry and replacement checks remain
effective. The existing feed rate limit applies.

## Assets in SkipperCast storage (FE-85)

`scripts/coast/publish_assets.py`, run only by the dispatch workflow
`.github/workflows/coast-assets.yml` on the owner's runner, copies two asset
groups from the Fish Worker into the `FEEDS` R2 bucket (the copy is the one step
that still reads Fish, so it must run before the owner deletes the Fish Worker):

- `terrain`: everything the coast-wide terrain manifest and the chart model
  reference under `/data/coast-wide/` and `/data/coast3d/` (terrain, NAIP
  imagery, provenance), 8,391 objects and about 680 MB on October 8, 2026;
- `habitat`: `/api/habitat/release`, `/data/skippercast-manifest.json`, the
  curated details and species files, the reef context (it is derived from the
  habitat release and pinned to its archives) and every region archive the
  release lists, read in ranges of at most 2 MiB and checked against the
  release's `archiveSha256`. A region whose `archiveETag` is not
  `"sha256-<archiveSha256>"`, or whose public copy differs from the live
  release, refuses the run.

The Fish shore files (`/data/slo-shore-habitat.geojson`,
`/data/slo-shoreline.geojson`) belonged to no group and were dropped with the
bridge (FE-62); the app draws shore runs from FE-43's
`dist/regions/<id>/shore-habitat.geojson`.

Each source behind a group must be an approved `catalog/sources.json` row with
`commercial_use: allowed`, matched by DOI or documented URL. An unknown source
or a held one (candidate, restricted, permission-required, unknown) refuses the
run before any asset is downloaded, and so does a group whose manifest names
no source at all. Terrain reads the sources of the coast-wide manifest and of
the chart provenance (`/data/coast3d/chart-provenance.json`, NOAA ENC Direct).
An asset whose upstream manifest declares a SHA-256 and byte count is checked
against them on download. Bare paths a manifest names without a digest (the
two terrain provenance files, `skippercast-species.json`) have no upstream
digest: they are pinned to the bytes of their first download, and the copied
indexes are pinned to the exact bytes that were enumerated and rights-checked. Objects are stored as `coast/objects/<sha256>`, the
manifest (`{path: {sha256, bytes, contentType, habitatRelease?, expiresAt?}}`)
as `coast/releases/<manifest sha256>.json`, and `coast/current.json` is written
last after every object and the manifest read back. `/feeds/` cannot read the
`coast/` prefix, and no R2 lifecycle rule covers it. Objects of earlier
releases are kept; content addressing means an unchanged asset is stored once.

The Worker reads `coast/current.json` on every request for a grouped asset.
With no pointer every grouped asset is unavailable (503). With one, each group the release
lists is served only from R2: the manifest must hash to its release id, a path
missing from the manifest is 404, a `release` parameter other than the entry's
habitat release is 404, an expired entry is 503, and the object's whole bytes
are hashed against its entry before any byte (or HEAD identity) is returned.
Each Worker isolate hashes an object once (concurrent first reads share that
one read) and then pins that R2 version's etag for range reads; a replaced
object is hashed again. Responses carry `ETag: "sha256-<digest>"` and the
original `X-Fish-Habitat-Release`, so the renderer's own SHA, ETag and HEAD
checks are unchanged. A pointer with any status other than `ready` makes every
grouped asset route 503, and so does deleting it. An R2 error (a
failed read, an unreadable pointer or manifest) is also 503. Groups left out of a run are
unavailable, so publish together every group the map needs. Snapshots
(`report`, `ocean`, `history`) come from the feeds below.

Habitat entries carry the release's expiry. A published habitat group serves
503 after that date until the workflow runs again on the newer Fish release, so
the owner re-runs it whenever Fish publishes one, and before the current
release's `expiresAt`. Once the Fish Worker is deleted no newer release can be
copied, so the habitat group serves 503 after the last copied release's
`expiresAt` until SkipperCast publishes a habitat release of its own.

On October 8, 2026 the rights check refused both groups: the USGS Morro Bay,
Point Buchon and Point Estero rows are `permission-required` (CSUMB
co-production), and NOAA BAG, CSMP Monterey and Point Conception, ETOPO, CRM,
3DEP, NOAA lidar, NOAA chart, NOAA ENC Direct and NAIP sources have no matching
catalog row. The
owner resolves those rows before the first publish. A download-only dry run
that day (164 objects: all ten habitat assets and 154 terrain and imagery
assets, 54 MB, kept outside the repository) matched every manifest SHA-256,
and served from an in-memory R2 stand-in through `server/coast-data.ts` it
passed the renderer's `verifiedAsset` and `readReviewedHabitat` checks.

## Snapshots from SkipperCast feeds (FE-84)

Every snapshot source is served from SkipperCast's own published feed in the
`FEEDS` bucket. Until FE-62 the Worker var `COAST_FEEDS` switched them one by
one from the Fish Worker; with the bridge retired nothing reads it (the deploy
workflow still copies it until that step is removed). The SLO county's feeds
live under the Morro Bay region:

| Name | Feed (R2 key) | Written by | Age limit | Replaces |
| --- | --- | --- | --- | --- |
| `nearshore` | `conditions/regions/morro-bay/nearshore.json` | FE-40, each live cycle | 3 h after `generated_at` | the report's `nearshore` and its `cdip-*` sources |
| `water-quality` | `conditions/regions/morro-bay/beach-health.json` | FE-41, about hourly | 3 h after `generatedAt` | the report's `waterQuality` and its `slo-beach-water-quality` source |
| `ocean` | `conditions/regions/morro-bay/coast-ocean.json` | `coast_snapshots.py`, each live cycle | 3 h after `generatedAt` | the whole `/api/coast/ocean` packet |
| `history` | `data/regions/morro-bay/history.json` | FE-42, weekly recent pass | 8 days after `generatedAt` | the whole `/api/coast/history` packet |
| `report` | `conditions/regions/morro-bay/coast-report.json` | `coast_report.py`, each live cycle (FE-87) | 2 h after `generatedAt` | the report's base: forecasts, observations, tides, alerts, catches and spatial layers |

A switched feed is used only while it is present, readable, shaped as the
`packages/coast` type it stands for and inside its age limit, measured by the
Worker against its own clock (a feed more than five minutes in the future is
stale too). Otherwise that one source is unavailable: the `ocean` and `history`
packets and the report's base answer 503, and the report is served without the
nearshore or beach rows whose feed is not used. The server makes
the age check itself because a collector that fails for a whole region keeps
its last published file: a region-wide CDIP failure re-publishes the previous
`nearshore.json`, whose sites still say `current`.

Values are never re-dated. Each row keeps its fetch, issue, sample and
observation clocks and each source its `outcome`, so a failed beach fetch is
served as an `error` source with no rows, never as open beaches. Two values are
re-read against the request's clock, only ever towards stale: a nearshore site
whose model issue is 48 h old or more is `stale`, and a history station whose
last observation is more than 3 h old has `recent.stale` set (the weekly pass
publishes it as current). Until the recent pass runs more often than weekly,
a switched History view shows the recent series as stale most of the week; on
October 8, 2026 Fish's recent series was under an hour old. Every snapshot
response names each source's state in `X-Coast-Upstream`, for example
`report=skippercast, nearshore=skippercast, water-quality=unavailable (stale)`;
the reasons are `unbound` (no `FEEDS` binding), `missing`, `unreadable`,
`invalid`, `stale` and `refused` (below). A history bundle without a positive
`recentWindowDays` is invalid, and a packet whose merged rows exceed the route's
byte limit (8 MB for the report) is refused with 503, as the service worker
would refuse it.

A feed is read only while none of the `catalog/sources.json` rows behind it is
refused by the rights register: a missing row, a `restricted` or `unavailable`
review status, or `commercial_use` of `prohibited` or `permission-required`
makes that source `refused`, so it is unavailable. The rows are `cdip-mop` (nearshore), `slo-beach-water-quality`
(water quality), `noaa-wcofs`, `noaa-hfr-thredds` and `noaa-goes-nowcoast`
(ocean), `ndbc-history` (history), and `nws-weather`, `ndbc-buoys`,
`noaa-tides`, `landing-reports`, `noaa-blended-sst` and `cdfw-mpas` (report).
A `candidate` row or `unknown` commercial use is not a refusal: the owner
confirms those register rows (on October 11, 2026 `cdip-mop`,
`noaa-goes-nowcoast` and `ndbc-history` were `candidate`, and
`slo-beach-water-quality` and `landing-reports` had `unknown` commercial use).

`python -m skippercast.pipeline.coast_snapshots --root var/live-published` runs
in `scripts/live_cycle.sh` after the GOES index. It builds `OceanData` from the
region's `intelligence.json` (WCOFS and HF radar surface currents, with the
Fish Worker's own selection rules ported from `normalizeSkipperOcean`: status
`ok`, fetched within 6 h, a forecast issued within 36 h or an observation
sampled within 6 h, native frames, SLO marine bounds, HDOP and radar-count
gates) and from `goes-times.json` while its newest frame is within 90 minutes.
On October 8, 2026 its currents were byte-identical to Fish's normaliser run on
the same `intelligence.json`.

## Report base from SkipperCast collectors (FE-87)

`python -m skippercast.pipeline.coast_report --root var/live-published` runs
in `scripts/live_cycle.sh` after the ocean packet and writes
`regions/morro-bay/coast-report.json`, the SLO county's `Report`:

| Report field | Source status ids | From |
| --- | --- | --- |
| `forecasts` | `nws-north`, `nws-central`, `nws-south` | NWS gridpoints of each county area's marine point, fetched here (`fish` `expandGrid` rules: 168 hours from the current hour, WMO units converted, gaps left blank) |
| `alerts` | `nws-alerts` | NWS active alerts for `CA,PZ`, kept for an area when an affected zone is the area's marine zone or one its marine or shore point reports, or the polygon covers either point (`filterAlerts`); a paginated answer is an error |
| `tides`, `tideEvents` | `coops-tides`, `coops-tide-events` | CO-OPS Port San Luis predictions, MLLW, 6-minute and high/low, the previous UTC day to three days ahead (`parseTides`) |
| `observations` | `ndbc-46215`, `ndbc-46028` | this cycle's `regions/morro-bay/latest.json` (`live.py`): the newest row with a wave height, else with wind, every field from that one row (`parseNdbc`) |
| `catches`, `catchStatus`, `catchContext` | `landing-reports` | the daily feed (`collect.py`, its public copy), with `fish` `collectCatches` checks: each trip within the reviewed window and identical to its day receipt, receipts under 72 h old, facts and links only |
| `spatial` | `noaa-blended-sst`, `cdfw-protected-areas` | the daily feed's sea-surface temperature grid (NOAA Geo-Polar Blended 5 km, the region's configured analysis; `fish` read JPL MUR, so the layer keeps this source's id and resolution) and CDFW DS582 boundaries |

Each source keeps its own outcome and clocks: an NWS source's issue and valid
times, a buoy's live-feed retrieval, the daily feed's retrieval and analysis
times, a trip's receipt time. A failed source is an `error` status with no
rows. As `fish` did, a run with no populated forecast area and no buoy
observation under three hours old writes nothing; the last report then ages out
of the Worker's 2 h limit and `/api/coast/report` is unavailable until a run
writes one. On October 8, 2026 a
dry run outside the repository matched Fish's live report: identical forecast
hours for all three areas over the 168 common hours, identical tide curve (1,200
points) and events (19), the same two alerts with the same areas, and the same
20 catch trips and catch status; the buoys differed only by Fish's newer fetch.

With a current report feed, `/api/coast/report` is SkipperCast's report with
the nearshore and beach feeds merged in. A nearshore or beach feed that is not
used leaves its rows and source statuses out of the report (the `Report` type
makes both optional), and the header says why; Fish's rows are never read.

## Retiring the Fish bridge (FE-62)

FE-62 removed the Fish Worker origin and every fallback to it from
`server/coast-data.ts`; `tests/test_coast_data.mjs` fails if `server/` names a
Fish origin again. The readable `/report` and `/feed.xml` pages read the same
report through the `FEEDS` binding. Producer attribution, measurement dates,
masks, datum limits and reuse restrictions remain in each feed's source
statuses, the asset manifests and `catalog/sources.json`. The `fish` repository's
historical receipts are archived under `docs/archive/fish/` (FE-62a).

The retirement needs every dataset published in SkipperCast's storage: the five
feeds above, current, and the FE-85 asset groups in R2. A dataset that is not is
unavailable rather than served from Fish. `scripts/coast/publish_assets.py`
still copies the assets from the Fish Worker, so the owner runs its first
publish before deleting that Worker.
