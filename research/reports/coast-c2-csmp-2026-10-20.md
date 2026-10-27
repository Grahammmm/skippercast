# C2 CSMP bounded metadata discovery — 2026-10-20

Task t_80e99fb2; author model gpt-6.1-sol. Review required. No mapping,
acquisition, rendering, publication, queue or canonical-store changes.

## Scope and measured result

- cambria-san-simeon bbox (CRS84): [-121.95, 35.45, -120.95, 35.66].
- One discovery30 checkpoint; two official USGS catalogs; five initial queries
  and two literal returned-link queries. Seven successful metadata requests;
  no retries, redirects followed or raster downloads.
- 145,863 response-body bytes observed and charged (cap 250,000,000).
- Discovery start 2026-10-21T00:09:15.325564Z; stop
  2026-10-21T00:11:30.953317Z; 135.628 s (cap 1,800 s).
- within_caps=true. One Point Estero candidate; zero execution selections.
- No compatible manifest found in the checked coastal evidence locations.
  Seven-day TTL retained from the original metadata response time, not renewed.

## Evidence and limits

Point Estero release: https://cmgds.marine.usgs.gov/data-releases/datarelease/10.5066-P9ZSTUK1/

Its Bathymetry_OffshorePointEstero XML states a delivered 2 m GeoTIFF mosaic,
9,176 rows by 9,201 columns, WGS84 UTM zone 10 (EPSG:32610). It describes 2 m
input shallower than 80 m and 5 m deeper input mosaiced into delivered 2 m.
A separate 5 m download was not linked. Preserve this lineage: the deeper
cells are not independent 2 m measurement. XML coordrep absres/ordres says
10.0, conflicting with the stated 2 m delivery. Native header inspection is
required, not a silent metadata correction. Vertical datum is unstated;
horizontal WGS84 and acquisition tide corrections do not establish one.
The XML source-wide -148.7 to -0.450586 m range does not establish valid
cells or depth-band coverage inside C2. Exact native bytes/hash, member
identity, support, interpolation mask and upper uncertainty remain unknown.
Public-domain language and attribution are preserved together with the
repository's CSUMB for-profit permission caveat.

Index: https://pubs.usgs.gov/ds/781/

Regional catalog: https://cmgds.marine.usgs.gov/data/csmp/PointSurToPointArguello/data_catalog_PointSurToPointArguello.html

San Simeon catalog: https://pubs.usgs.gov/sim/3327/sim3327_data.html

The inspected catalogs did not link a separate native San Simeon 2 m raster.
This bounded negative result is not proof of geographic absence. San Simeon
Contours metadata explicitly says Vector and describes ten 3x3 smoothing
iterations plus 10/50 m contour intervals; the landing table's TIFF label
must not turn those contours into native bathymetry. Historic SCC source
locators are retained as leads only; no off-plan hosts were fetched. Existing
NOS/BSS/SCC acquisition work is not duplicated by this card.

## Holds and handoff

- Native execution: datum, member identity and actual support unverified.
- Resolution conflict and deep-water 5 m lineage need native inspection.
- San Simeon native raster and separate 5 m companion remain not located in
  this finite branch; never substitute smoothed contours.
- Commercial rights and all publication gates remain held.
- Campaign card/section 8 and region package agree on the bbox above;
  pilot cycle-1-plan line 47 differs. The card/package bbox was used.

The bridge child must consume the pinned catalog and report its own native
holds, not infer eligibility from machine-valid metadata. The existing local
screen, packet and independent verification children own review. Author is
Sol; no Sol-on-Sol semantic acceptance is allowed.

## Reproducibility pins and execution

- Frozen catalog SHA256: `7e81237516c5f3024b956da3910511b5b1253cade1c63b2dbadfed44b0b09ab8`.
- Source manifest SHA256: `abea015a57714407380214b3d18d5b97ed54e6faae67db457d057d5f86d108d6`.
- Receipt SHA256: `135b9308e03a6fffa7857f51383d7fe2aa5772ecbd4ea15abe60699305fc5105`.
- Recursive receipt inventory SHA256: `a5cf0aa22a33e6233801a63ce4909e0a0885c8107ea12fcf7282544c694b6591`.
- Retained receipt files inventoried: 28 (ephemeral lock excluded).
- Reviewed source-manifest validator: valid=true, mapping_accepted=false.
- test_coastal_live_discovery.py: 7 passed in the existing authoritative
  checkout's shared survey venv. The other repo venv lacked jsonschema;
  no packages, credentials, privileges or tool permissions were changed.
- Offline task verifier: C2_DISCOVERY_VERIFY_PASS (schema, original response
  hashes, frozen catalog reconstruction, read-only catalog, caps, TTL,
  one candidate, unknown datum/support and no native requests).

Raw responses, checkpoints, annotations, task-local driver/finalizer, private
receipt and full absolute-path hash inventory remain under the assigned
worktree's ignored var/coast-r-c2-d1 directory. This sanitized report does not
publish raw retained metadata or claim semantic acceptance.
