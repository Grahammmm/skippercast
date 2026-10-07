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
