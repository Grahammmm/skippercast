> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/SPECIES-OPPORTUNITY.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Shore species opportunity model

Reviewed 2 October 2026 (Pacific). Model: `shore-context-v1`.

## What is built

`buildShoreOpportunities(report, county, shoreCollection, species, date, now)` in `src/opportunity.ts` returns a sorted set of named beaches, exact source geometry, public approach references, source clocks, reasons, uncertainties, tactics and dated forecast-hour windows. It supports **surfperch and California halibut from shore**. Boat and spear habitat remain separate models.

The result has `sites` and a MapLibre-ready `featureCollection`. Every feature has `id`, `name`, `areaId`, `species`, numeric `priority`, `label`, `whenStart`, `whenEnd`, `reason`, `uncertainty`, `sourceYear`, `sourceUrl` and `catchProbability: null`. Public approach point coordinates are in each site's `access` array. Render those as inventory references, with original links and opening checks; do not imply turn-by-turn entrance navigation.

`target-species.json` supplies the two shore profiles and current dated rule summaries. `skippercast-species.json` continues to supply reef context. No offshore halibut reef fit is created from this beach layer.

## Source-grounded fishing guidance

The [CDFW Central California beach-fishing guide](https://wildlife.ca.gov/Fishing/Ocean/Beach-Fishing/1000) identifies sandy bar edges, channels and drop-offs as useful places to inspect. Its regional guidance emphasizes early morning, pre-dusk and incoming tide, with mild to moderate surf. Its seasonal emphasis is October–June for surfperch and May–August for California halibut. These are regional angling guidance, not calibrated independent predictors for SLO.

[CDFW's surf-zone research](https://wildlife.ca.gov/Conservation/Marine/Surf) distinguishes sandy surf species from kelp and deeper-water perches; barred surfperch is the main sandy-beach recreational study species in central and southern California. The surfperch selector therefore means sandy surf species, chiefly barred surfperch, with identification still required.

Surfperch tactics emphasize finding crab beds and inspecting channels. The light tackle suggestion—7–9 ft rod, 6–12 lb line, light bait or a Carolina-rigged grub—is paraphrased from the CDFW guide. California halibut context emphasizes baitfish activity and sandy channels; this model does not measure baitfish, castable water depth or current halibut presence. Neither model invents an optimum SST, lunar bite multiplier, visibility estimate or success percentage.

## Real shoreline geometry

The five features in `public/data/slo-shore-habitat.geojson` are **Hearst Memorial Beach at San Simeon, Morro Strand, Cayucos sandy shore, Pismo Beach, and Oceano near Pier Avenue**: 600 retained source vertices, approximately 36 KB. North, central and south county areas now each have actual sourced sandy shoreline; fish presence remains unknown.

Source: [NOAA Central California ESI 2006 service](https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/Central_California_ESI_2006_test/FeatureServer), shoreline layer 3. This is published by NOAA's Office of Response and Restoration. The [source item](https://www.arcgis.com/home/item.html?id=5eb03df505b14b57a6a717261f529496) states no use constraints beyond its mapping limitations and encourages attribution. Its `_test` endpoint name is retained literally in provenance; it is a NOAA-owned published service, not an independent Fish survey.

NOAA ESI **3A** means fine to medium-grained sand beach, verified against [NOAA's shoreline classification list](https://response.restoration.noaa.gov/oil-and-chemical-spills/oil-spills/resources/shoreline-sensitivity-rankings-list). Oil sensitivity rank itself never becomes a fishing rank. Only the physical sand classification is reused.

| Beach | NOAA shoreline object IDs | Official access object IDs |
|---|---|---|
| Hearst Memorial Beach, San Simeon | 2094, 2100, both complete original paths | 770 |
| Morro Strand | 2294 | 804, 805 |
| Cayucos sandy shore | 2283, 2287, 2289 | 797, 798 |
| Pismo Beach | 2632, 2636, 2637 | 868, 870 |
| Oceano near Pier Avenue | 2638, partial contiguous source run | 875 |

The importer selects contiguous runs of original vertices inside reviewed beach latitude ranges. It retains provider-transformed WGS84 coordinates exactly. It does not interpolate new end vertices, simplify, bridge gaps, buffer points or manufacture polygons. Named extents are curated investigation scopes, not surveyed park boundaries. Beach width, current sandbars, individual troughs and horizontal accuracy remain unknown. **The source year 2006 must be visible**, despite a recent retrieval date.

The [official Coastal Commission access inventory](https://services9.arcgis.com/wwVnNW92ZHUIr0V0/arcgis/rest/services/AccessPoints/FeatureServer) supplies public beach approach names, IDs and factual coordinates. Full editorial descriptions, photographs, and modified university copies are not imported. Its [source terms](https://www.arcgis.com/home/item.html?id=e45f130ce101423ea1de943a69445ece) are preserved in the GeoJSON provenance, including representational-data limitations. This is a separate state source, not covered by NOAA's federal public-domain status.

[State Parks confirms fishing at Morro Strand](https://www.parks.ca.gov/?page_id=593), and its [park brochure](https://www.parks.ca.gov/pages/593/files/MorroStrandSBFinalWebLayout042115.pdf) requires designated approaches and respect for fenced restoration and nesting areas. [State Parks confirms Pismo surf fishing](https://www.parks.ca.gov/?page_id=30470) and emphasizes changing sandbars and rip currents. [Oceano's official page](https://ohv.parks.ca.gov/?page_id=1207) identifies the Grand Avenue and Pier Avenue approaches; vehicle, creek and wildlife restrictions require separate checks. A public approach does not establish that the whole mapped beach is currently open.

## Transparent priority logic

| Priority | Label | Meaning |
|---|---|---|
| 0 | Hold | Protected-area intersection, applicable marine warning, or nearby current beach-health notice. |
| 1 | Habitat context | Sourced sandy shoreline exists; complete fresh conditions, boundary, access or rule context is missing. |
| 2 | Investigate | A daylight hour passes the complete conditions checks; regional timing context may be partial. |
| 3 | Conditions align | Priority 2 plus seasonal emphasis, rising station tide and morning/pre-dusk timing. |

No category is a catch probability, measured fish concentration or clearance to fish. Confidence remains **Low** because current fish presence, exact breaking surf, channel geometry and local access are unmeasured.

### Forecast time and source gates

- Use `buildDaily` to select the actual county-local date; it retains fresh NWS source issue/fetch gates, 72-hour horizon, applicable warning intervals and source outages.
- Full hourly windows must start after the actual current clock and sunrise and end by sunset. Tomorrow's layers use tomorrow's samples. No all-day summary is substituted for an hourly window.
- A CDIP model must be available/current, issued within 48 hours and fetched within 3 hours, with finite clocks and no more than one hour future skew. It must be in the same area and within 10 km of the actual shoreline's representative source vertex. The closest qualifying model is selected; 10 km is an editorial match radius, not measured spatial skill.
- A native nearshore sample must be on the selected local date and within 90 minutes of the hour's midpoint. Native 3-hour resolution, sample time and source URL are retained. The sample is not linearly invented, and is not labeled breaking surf.
- Initial screening uses wind ≤8 kt, gust ≤12 kt, offshore seas ≤3 ft and nearshore modeled waves ≤3 ft. At wave height ≥2.5 ft and period ≥15 s, withhold the complete window. These are provisional editorial exposure filters, not biological optima, universal surf definitions or safety limits.
- Rising tide is computed only from valid closely bracketed NOAA station prediction points with fresh prediction acquisition. Nearly flat, unbracketed or gapped curves remain unknown. Port San Luis tide stage is never called beach current, inlet current or slack water.
- Temperature and moon phase are displayed by the report but never silently added to this rank. Lack of a measurement never becomes zero.

## Legal and source review

The [CDFW Central Region page](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central), publisher update 1 October, was explicitly rechecked on **2 October 2026 at 19:43:19 Pacific (3 October 02:43:19 UTC)**. The review expires **4 October 02:43:19 UTC**; source collection alone does not renew it. California halibut: year-round, 5 fish south of Point Sur, minimum 22 inches. Surfperch: year-round, 20 combined/10 per species, separate shiner allowance; redtail minimum 10.5 inches. These are summaries, with original links and a **24-hour review expiry**, not a full legal engine. [CDFW's beach/pier guidance](https://wildlife.ca.gov/Fishing/Ocean/Beach-Fishing/1000) distinguishes normal beach licensing from the defined public-pier exemption. Identify species and recheck method and exact location.

Protected geometry comes from Fish's current `collectSpatial` pipeline, which verifies the ArcGIS count against full returned polygons and rejects truncation/invalid rings. The shore model requires a nonempty, valid polygon collection fetched within 24 hours. It checks **all shoreline vertices and all line edges**, plus each approach point. Any interior intersection or boundary touch excludes the whole beach feature from the overlay; a centroid-only test is insufficient. Polygon holes are respected. All MPAs are conservatively excluded rather than trying to infer allowed finfish take from designation alone.

The coastline is historical, and a shoreline that does not intersect a mapped MPA does **not** establish that a cast offshore stays outside it. Wildlife closures, private approaches, fishing method, dynamic emergency orders and posted restrictions still need a local check. Empty or stale geometry yields `legalStatus: unknown` and priority 1, never an absence-of-closure assertion.

Source review expires after 30 days, public approach review after 7 days, species rule review after 24 hours. Current collectors refresh conditions and boundaries separately. Renewing shoreline acquisition does not renew a human-reviewed legal statement: the importer deliberately retains the dated rule review until someone verifies the source and updates it. Do not overwrite that date with the import clock.

## Refresh and future refinement

Run `node scripts/import-shore-habitat.mjs` to fetch the original government subsets; read-only network access is needed. For an offline provenance-backed rebuild, supply a directory containing `slo-noaa-shore.json`, `slo-access.json`, `access-item.json` and `source-fetch.json`. The last file must retain the original `noaa`, `access` and `terms` receipts, each with `fetchedAt` and a matching `normalizedSha256`; use `sourceChecks.acquisitions` from the online import with the corresponding exact source JSON. Rebuild time never advances the cached source clocks. The import records original response byte hashes, normalized subset hashes and source terms. It fails if reviewed source IDs disappear, sand classification changes, access becomes nonpublic or has a documented closure/archive flag, coordinates are invalid, or source response truncates.

Next useful evidence: source-dated aerial/lidar shoreline verification, measured nearshore sand troughs, consistent zero-catch/effort logs, and exact-access closure geometry. SkipperCast's USGS interpreted sediment thickness is explicitly unsuitable as current sandy-surf substrate or depth; its 2008 nominal-depth reef exports do not locate today's casting channels. Government lidar could improve geometry after producer rights, acquisition date, resolution and actual shoreline coverage review. Do not turn old offshore geology into shore-perch polygons.

For rendering, use color and a restrained line glow over the **actual source lines**. Explain display width as cartographic emphasis, not a physical fishing corridor or uncertainty buffer. Every beach should reveal why, when, source age, what to look for, and what needs a local check.

## Verification

Twelve focused offline tests pass: real five-beach artifact, exact north source paths/approach and unchanged prior geometry, dated north conditions with rule expiry, ordinal positive context, date-specific native model samples, stale/missing source handling, full-edge MPA intersections and holes, tide bracketing, long-period swell/health notices, halibut seasonal context, original cached-source clocks, and source classification/access withdrawal. No browser verification, deployment or SkipperCast mutation was performed for this source addition.

## North beach and review evidence — 2 October 2026 Pacific

[William Randolph Hearst Memorial Beach's official State Parks page](https://www.parks.ca.gov/?page_id=589) confirms public beach access and parking, with dawn-to-dusk hours and shoreline wildlife precautions. The added 91-vertex geometry retains two **complete** NOAA ESI 3A line features beside official Coastal Commission approach 770. It excludes more easterly neighboring features from this reviewed investigation scope; no park boundary or permitted casting zone is inferred. The source still dates to 2006.

`research/shore-source-review-2026-10-03.json` records actual current primary-page fetch clocks, byte hashes, reviewed factual access inventory fields, retained original source geometries, and the manual CDFW rules review. Current owner pages for all five beaches and original NOAA/CCC source terms were checked. CCC closure fields were blank for the retained approaches; that inventory finding is **not** an assertion that real-time closures are absent. Check posted notices on arrival.

The current eight-polygon CDFW collection, fetched 3 October at 01:41:24 UTC, does not intersect either north source line or the retained approach point. The model repeats its full-line/edge/point check against fresh report polygons; no centroid shortcut or special north exemption was added. The four prior beach geometries are unchanged. The 24-hour legal, 7-day access and 30-day shoreline gates remain intact. The original species ecology/profile review clock was retained; only the actually rechecked species rule clocks were renewed.
