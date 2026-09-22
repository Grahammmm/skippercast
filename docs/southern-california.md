# Southern California rollout

The `southern-california` package covers the Mexico border–Point Conception coast, its islands and nearby offshore forecast samples. It uses the shared application; existing Morro Bay and Cambria–San Simeon packages remain separate. Its status remains **preview**: native bathymetry now supports detailed island context and numerical terrain views, but an unspecified common vertical datum, source age and coverage gaps prevent exact fishing-target qualification.

## Published context

- Nineteen weather sample points use four independent wind/wave model products. Zero combined-wave periods are rejected instead of rated calm; coastal reference points are checked against actual returned marine cells. Eight local context bindings choose the appropriate reference tide, airport, buoy and advisory zone. San Diego's current zones are PZZ740/PZZ745, not the retired PZZ750/755/775 identifiers. Tide height is never interpreted as bottom current or slack water.
- The CDFW DS582 download contains 61 intersecting MPA features, including the Channel Islands. All target/context geometry touching any MPA is withheld, regardless of limited species exceptions. Eight NOAA Southern California Groundfish Exclusion Areas provide an additional conservative exclusion layer. These are supplemental coordinates; federal regulations control. This is not a complete military/navigation restriction map.
- Sixteen historical artificial-reef complexes appear as single outlines. They derive from the [CDFW June 2001 appendix](https://nrm.dfg.ca.gov/FileHandler.ashx?DocumentID=30217&inline=), linked from the [official guide](https://wildlife.ca.gov/Conservation/Marine/Artificial-Reefs/Guide). DMS facts retain an unspecified source datum; WGS84 is only assumed for a broad display envelope. A 500 m padding is a search/display convention, not measured error. Reported construction depths and material are historical facts, not current depth qualification or individual boulder measurements.
- Two reef envelopes intersect MPAs and are withheld. Pendleton is withheld pending military-access evidence; International Reef is withheld for unresolved datum/position near the international boundary. Unlocated/disintegrated individual modules are not advertised as current habitat. No A/B/C rank, GPX target, charter claim, automatic drift or measured bottom view is assigned to these areas.
- Separate Southern regulations account for the legal 50-fathom RCA line and the October–December offshore-only lingcod/shelf/slope rockfish period. Nearshore rockfish are closed then. The 200-ft user preference is unchanged; a sounder reading does not establish legal-side access. Seasonal restrictions suppress an unrestricted-open badge and saved-trip threshold qualification.
- The 16 regional selectors are lingcod/rockfish, sheephead, whitefish, kelp bass, barred sand bass, spotted sand bass, halibut, white seabass, yellowtail, bonito, barracuda, bluefin, yellowfin, dorado, albacore and spiny lobster. Dungeness and salmon are not Southern selectors. Each has researched habitat, method, depth and uncertainty notes plus local official-rule links. The [species research](southern-species-research.md) records source scope and legal ambiguities.
- The [island habitat import](southern-habitat-sources.md) combines NOAA's actual historical hard/soft footprints with native 2 m/4 m NCCOS bathymetry and CDFW's September 2016 canopy/subsurface kelp detections. Species selection changes these ecological associations without asserting fish presence. Bay bass does not inherit island reef polygons; mobile/offshore fish do not receive invented fixed hotspots. Kelp is explicitly historical.
- Northern Channel Islands and Santa Barbara Island have source-grid terrain views where coverage permits. Catalina has dated kelp context only. San Clemente and San Nicolas habitat recommendations are withheld pending verified access. Island focus shortcuts are browsing extents, not fishing-ground boundaries.
- Lobster uses hoop/hand methods and boat comfort only; the app does not score hoop handling or diving safety. The scheduled October 2 opening retains its 6 p.m. Pacific time and an opening-review gate. Choosing a calendar date never implies an all-day opening. A current source check is still required before any open badge.

## Rebuild and update ownership

`regions/southern-california/reef-records.json` holds the reviewed historical facts. To rebuild outlines after a reviewed source or closure update:

```sh
node scripts/build_reef_context.mjs southern-california
# Optional GIS environment; hash-pinned cache, or --fetch for original sources.
python scripts/build_socal_habitat.py
PYTHONPATH=src python -m skippercast.platform validate --region southern-california
PYTHONPATH=src python -m skippercast.platform.build
```

The existing daily-data workflow discovers this package and checks official rules, MPA geometry, the reviewed NOAA closure-coordinate fingerprint and local environmental evidence. Changed fingerprints need review; they never approve themselves. Failed legal fetches retain the original timestamps and withhold current-open claims. The NOAA coordinates are at a versioned URL, so the watched NOAA closed-area page also needs human review when changed.

Historical survey inputs are pinned in `habitat-sources.json`, with source and derived-output receipts. The existing daily source-document audit includes these providers. An updated catalog, closure or source version triggers review and a new bounded GIS build; it does not silently replace survey data or relabel old observations as current. Run the complete geometry/tile tests before publishing a coherent site version. Raw archives stay under ignored `var/` and are never served to the browser; the map loads outlines once and a terrain tile only when requested.

The packaged observation snapshot is a dated fallback only; it becomes stale under the same two-hour measurement and 90-minute collection checks.

The existing half-hourly live-conditions workflow collects each distinct configured buoy once, plus regional ocean/ensemble data. It publishes under `regions/southern-california/` on the `conditions` branch. The daily feed lives on `data`. Five-minute browser observations and half-hourly model refreshes remain separate. Forecast sample order and station identities are part of the package: compare feed identity and coverage before publication. Prospective verification begins with this release; no retrospective skill is invented.

First local ingestion on September 22 returned all four deterministic models, all six zone-advisory queries, MPA geometry, the NOAA closure fingerprint, satellite/radar context, tide predictions and configured buoy observations. Direct CDFW/harbor downloads failed in this environment; rules were read through official web sources, but no new content hash was falsely approved. The rule panel therefore remains “Check rules” until a successful direct download is reviewed. Deployment does not turn partial feeds into complete ones.

## Qualification work remaining

Resolve the imported merged bathymetry's common datum and uncertainty before qualifying small targets. Replace older substrate and kelp products with newer, ground-truthed sources where available; extend native bathymetry to Catalina and the mainland. Review local charter identities before any AIS matching. Add effort-aware catch evidence before a bite model. The international maritime boundary is not the package's rectangular bounding box; no cross-border clearance or rules are supplied.

To withdraw this rollout, change the package to draft and rebuild/publish, or restore the previous coherent site/package version. Preserve data timestamps, feed receipts and private user records. Do not create a new scheduler for this region.

Island focus controls bind to their explicit forecast samples. Anacapa, Santa Rosa, San Miguel and Santa Barbara Island now have their own requested marine samples, in addition to Santa Cruz and Catalina. Returned model grid coordinates still determine actual resolution; a new requested point is not a new high-resolution model. The Anacapa sample uses [NWS PZZ655](https://api.weather.gov/zones/forecast/PZZ655). Western islands use [NWS PZZ673](https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=PZZ673); Santa Barbara Island uses [NWS PZZ676](https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=PZZ676). Mainland tide stations remain explicitly distant references.
