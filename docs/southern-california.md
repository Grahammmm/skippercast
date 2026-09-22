# Southern California rollout

The `southern-california` package covers the Mexico border–Point Conception coast, its islands and nearby offshore forecast samples. It uses the shared application; existing Morro Bay and Cambria–San Simeon packages remain separate. The initial status is **preview**, because current native bathymetry has not qualified fishing targets.

## Published context

- Fifteen weather sample points use four independent wind/wave model products. Zero combined-wave periods are rejected instead of rated calm; coastal reference points are checked against actual returned marine cells. Five local context bindings choose the appropriate reference tide, airport, buoy and advisory zone. San Diego's current zones are PZZ740/PZZ745, not the retired PZZ750/755/775 identifiers. Tide height is never interpreted as bottom current or slack water.
- The CDFW DS582 download contains 61 intersecting MPA features, including the Channel Islands. All target/context geometry touching any MPA is withheld, regardless of limited species exceptions. Eight NOAA Southern California Groundfish Exclusion Areas provide an additional conservative exclusion layer. These are supplemental coordinates; federal regulations control. This is not a complete military/navigation restriction map.
- Sixteen historical artificial-reef complexes appear as single outlines. They derive from the [CDFW June 2001 appendix](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=30217&inline=), linked from the [official guide](https://wildlife.ca.gov/Conservation/Marine/Artificial-Reefs/Guide). DMS facts retain an unspecified source datum; WGS84 is only assumed for a broad display envelope. A 500 m padding is a search/display convention, not measured error. Reported construction depths and material are historical facts, not current depth qualification or individual boulder measurements.
- Two reef envelopes intersect MPAs and are withheld. Pendleton is withheld pending military-access evidence; International Reef is withheld for unresolved datum/position near the international boundary. Unlocated/disintegrated individual modules are not advertised as current habitat. No A/B/C rank, GPX target, charter claim, automatic drift or measured bottom view is assigned to these areas.
- Separate Southern regulations account for the legal 50-fathom RCA line and the October–December offshore-only lingcod/shelf/slope rockfish period. Nearshore rockfish are closed then. The 200-ft user preference is unchanged; a sounder reading does not establish legal-side access. Seasonal restrictions suppress an unrestricted-open badge and saved-trip threshold qualification.
- The ecology dossier has region-specific limitations. No local Dungeness grounds, salmon catch positions or charter/AIS stops are qualified. The existing species set is preserved; other Southern fisheries require their own evidence and regulations before addition.

## Rebuild and update ownership

`regions/southern-california/reef-records.json` holds the reviewed historical facts. To rebuild outlines after a reviewed source or closure update:

```sh
node scripts/build_reef_context.mjs southern-california
PYTHONPATH=src python -m skippercast.platform validate --region southern-california
PYTHONPATH=src python -m skippercast.platform.build
```

The existing daily-data workflow discovers this package and checks official rules, MPA geometry, the reviewed NOAA closure-coordinate fingerprint and local environmental evidence. Changed fingerprints need review; they never approve themselves. Failed legal fetches retain the original timestamps and withhold current-open claims. The NOAA coordinates are at a versioned URL, so the watched NOAA closed-area page also needs human review when changed.

The packaged observation snapshot is a dated fallback only; it becomes stale under the same two-hour measurement and 90-minute collection checks.

The existing half-hourly live-conditions workflow collects each distinct configured buoy once, plus regional ocean/ensemble data. It publishes under `regions/southern-california/` on the `conditions` branch. The daily feed lives on `data`. Five-minute browser observations and half-hourly model refreshes remain separate. Forecast sample order and station identities are part of the package: compare feed identity and coverage before publication. Prospective verification begins with this release; no retrospective skill is invented.

First local ingestion on September 22 returned all four deterministic models, all six zone-advisory queries, MPA geometry, the NOAA closure fingerprint, satellite/radar context, tide predictions and configured buoy observations. Direct CDFW/harbor downloads failed in this environment; rules were read through official web sources, but no new content hash was falsely approved. The rule panel therefore remains “Check rules” until a successful direct download is reviewed. Deployment does not turn partial feeds into complete ones.

## Qualification work remaining

Obtain licensed native survey depths/substrate for each candidate area, verify horizontal/vertical datums and current geometry, and screen whole footprints against current rules and access restrictions. Then qualify small targets and measured bottom views through the existing survey pipeline. Review local charter identities before any AIS matching. Add effort-aware catch evidence before a bite model. The international maritime boundary is not the package's rectangular bounding box; no cross-border clearance or rules are supplied.

To withdraw this rollout, change the package to draft and rebuild/publish, or restore the previous coherent site/package version. Preserve data timestamps, feed receipts and private user records. Do not create a new scheduler for this region.
