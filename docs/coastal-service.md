# Coastal data service during the Fish merge

SkipperCast reads selected public datasets from the existing owner-operated
Fish Worker through a bounded same-origin bridge. This preserves Fish's running
report/history/ocean collectors and its private government-habitat publication
checks while the common map is integrated. It does not transfer or expose the
Fish database or private R2 storage, approve new contributors or change original
source times. No new refresh schedule is created.

- `/api/coast/report`, `/api/coast/ocean`, `/api/coast/history`: original SLO
  payloads, validated for schema, county and assembly-clock identity. Optional
  regional bindings are limited to Morro/Avila and Cambria/San Simeon. Other
  regions do not inherit these forecasts or observations.
- `/api/coast/habitat/release` and `/api/coast/habitat/tiles`: preserve the
  original upstream live release, producer rights, screening, hash and expiry
  gates. The common client must still validate the returned manifests and
  per-archive HEAD identity before displaying habitat.
- `/coast-data/data/...`: only enumerated public habitat/shore files and
  flat coastal terrain/chart-model filenames. Private archives, receipts,
  percent-encoded aliases, traversal and arbitrary URLs are refused.

Only GET/HEAD are supported. Cookies, identity, authorization, origin and
referrer headers are not forwarded. Upstream redirects are refused. Snapshot
reads and geometry reads have bounded byte budgets; range requests require
exact offsets, length and a 206 response. Original ETags and release headers
survive. Responses are not cached by this bridge, so expiry and replacement
checks remain effective. The existing feed rate limit applies.

## Assets in SkipperCast storage (FE-85)

`scripts/coast/publish_assets.py`, run only by the dispatch workflow
`.github/workflows/coast-assets.yml` on the owner's runner, copies two asset
groups from the Fish Worker into the `FEEDS` R2 bucket:

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

The shore files (`/data/slo-shore-habitat.geojson`,
`/data/slo-shoreline.geojson`) belong to no group and stay on the bridge until
FE-10 and FE-43 publish SkipperCast's own.

Each source behind a group must be an approved `catalog/sources.json` row with
`commercial_use: allowed`, matched by DOI or documented URL. An unknown source
or a held one (candidate, restricted, permission-required, unknown) refuses the
run before any asset is downloaded. Upstream SHA-256 and byte counts are
checked on download. Objects are stored as `coast/objects/<sha256>`, the
manifest (`{path: {sha256, bytes, contentType, habitatRelease?, expiresAt?}}`)
as `coast/releases/<manifest sha256>.json`, and `coast/current.json` is written
last after every object and the manifest read back. `/feeds/` cannot read the
`coast/` prefix, and no R2 lifecycle rule covers it. Objects of earlier
releases are kept; content addressing means an unchanged asset is stored once.

The Worker reads `coast/current.json` on every request for a grouped asset.
With no pointer it uses the bridge as before. With one, each group the release
lists is served only from R2: the manifest must hash to its release id, a path
missing from the manifest is 404, a `release` parameter other than the entry's
habitat release is 404, an expired entry is 503, and the object's whole bytes
are hashed against its entry before any byte (or HEAD identity) is returned.
Each Worker isolate hashes an object once (concurrent first reads share that
one read) and then pins that R2 version's etag for range reads; a replaced
object is hashed again. Responses carry `ETag: "sha256-<digest>"` and the
original `X-Fish-Habitat-Release`, so the renderer's own SHA, ETag and HEAD
checks are unchanged. A pointer with any status other than `ready` makes every
grouped asset route 503; deleting it returns to the bridge. Groups left out of
a run return to the bridge, so publish together the groups that should stay in
R2. Snapshots (`report`, `ocean`, `history`) always use the bridge.

Habitat entries carry the release's expiry. A published habitat group serves
503 after that date until the workflow runs again on the newer Fish release, so
the owner re-runs it whenever Fish publishes one, and before the current
release's `expiresAt`.

On October 8, 2026 the rights check refused both groups: the USGS Morro Bay,
Point Buchon and Point Estero rows are `permission-required` (CSUMB
co-production), and NOAA BAG, CSMP Monterey and Point Conception, ETOPO, CRM,
3DEP, NOAA lidar, NOAA chart and NAIP sources have no matching catalog row. The
owner resolves those rows before the first publish. A download-only dry run
that day (164 objects: all ten habitat assets and 154 terrain and imagery
assets, 54 MB, kept outside the repository) matched every manifest SHA-256,
and served from an in-memory R2 stand-in through `server/coast-data.ts` it
passed the renderer's `verifiedAsset` and `readReviewedHabitat` checks.

The upstream origin is fixed in `server/coast-data.ts`. The bridge is transport
for an existing reviewed publication, not an independent claim that every
underlying product is commercially reusable or locally complete. Producer
attribution, measurement dates, masks, datum limits and reuse restrictions remain
in the original manifest and Fish source receipts. SkipperCast's deployment
policy and private account/fleet routes remain unchanged.

Later retirement of the Fish service requires moving its collectors, source
registrations, immutable assets and publication checks into SkipperCast and
witnessing persisted refreshes. Until then, deleting the Fish Worker, database
or private archive would break this dependency.

Independent bounded-module review accepted October 6, 2026 after range metadata
and upstream cancellation findings were resolved. Eight focused offline tests
passed. This acceptance does not establish UI parity, live source freshness or
collector migration; those remain separate verification steps.
