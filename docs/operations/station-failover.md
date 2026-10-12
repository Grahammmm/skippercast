# Station priorities

Keep the existing primary IDs and names in `region.json` for current clients.
To opt a role into ordered selection, add this inside its `stations` object
(including a local context's `stations`):

```json
"roles": {
  "nearshore_buoy": {
    "stations": ["46053", "46054"],
    "evidence": "catalog/station-failover.json"
  }
}
```

Roles are `nearshore_buoy`, `offshore_buoy`, and `tide`. The first ID must match
its legacy primary. At most four distinct IDs are allowed. Repeated primary
roles within a region must share the same order. When roles share a primary
source ID, a priority list on either role applies to that shared observation
source and its spectrum. Unconfigured roles produce
exactly the legacy feed shape, with no optional source-level station fields.
Configured roles name `station` even when using the primary; `fallback_for`
exists only when the data actually came from a backup. Source IDs remain tied
to the primary role so aliases and current clients continue finding the data.
`data.station`, sample times, units and datum always describe the station used.

A failed check can retain the last served data inside its original max_age;
when those data age out, try backups in order. Successful tide responses must
cover the current day (high/low predictions may begin later today) and not
have expired. If all candidates are stale or fail, serve the newest data on
hand, judged by the data's own clock (observation or issue time, or a
prediction's coverage end; never a retrieval time). A reading that just came
back stale and is newer than the previous data is served as `stale` under its
own station. Otherwise the previous data and station are `retained`, with
their original retrieval times and the corresponding station name and URL. A
previous station that is no longer in the chain is not retained. Without
usable data, preserve the primary's result.
The normal source status keeps its meaning: an available backup is `ok`, while
feed health and the freshness checker report degraded service and name it.
A retained or stale backup is still subject to normal outage checks.

Buoy priorities apply to live observations/spectra and daily observations.
Tide priorities apply to the daily prediction source; the live feed collects
only buoys. Context-specific tide collection is not introduced here.
Review exact inventories, coordinates, exposure and endpoints before adding
another backup. The first rollout and remaining single-station decisions are
recorded in `catalog/station-failover.json`. Predictions remain reference
water levels, never local current or entrance-clearance claims.
