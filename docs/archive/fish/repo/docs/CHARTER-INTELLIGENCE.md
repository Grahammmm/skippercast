> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/CHARTER-INTELLIGENCE.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Charter intelligence: reviewed facts and planned activity pipeline

**Status: small reviewed factual catch display implemented; licensed bulk reuse and charter activity design remain pending.** Fish imports linked, dated local boat-trip facts under the existing September 21 facts-only source review. Charter AIS identities, trip movement classification and activity map overlays are not implemented. This document distinguishes that narrow working binding from the proposed larger Morro Bay/Port San Luis pipeline. Reviewed October 1–2, 2026.

## Implemented linked catch facts

Source: [public SkipperCast Morro/Avila report feed](https://raw.githubusercontent.com/Grahammmm/skippercast/data/regions/morro-bay/latest.json), with the `landing-reports` review pinned to [catalog commit a481da68923649db6fda277af4bd6f40813f6436](https://github.com/Grahammmm/skippercast/blob/a481da68923649db6fda277af4bd6f40813f6436/catalog/sources.json). The reviewed scope is **small linked factual counts**, not publisher creative content, complete-page copying or a bulk operator-feed license. The audited feed had 74 dated trips, latest September 28, 2026; this does not guarantee today's trip recency, display count or ongoing availability. Independent original publisher-fetch clocks remain separate from feed generation and Fish receipt. See [reviewed source evidence](../research/reviewed-catch-binding.md).

`src/providers/catches.ts` accepts only the SLO binding, fixed feed schema/region, Morro Bay/Avila Beach ports, supported factual labels and exact original SoCal Fish Reports date URLs. It preserves boat, landing port, trip date/class, nullable angler count, species/category names, counts and explicit reported/retained/released semantics. Feed and independently successful publisher-day receipts must each be within 72 hours, with a five-minute future-clock tolerance; raw trips must match their original receipt. A newly fetched wrapper cannot make failed/stale original evidence current. Exact duplicates are removed, conflicts/invalid/stale records excluded, and independent good rows can survive partial source failures.

Parsing is bounded to the reviewed feed's maximum 30-day window, 3 MiB body and 12-second request. The boat-only brief and dated modal show eligible reports from the past **seven local calendar days**, capped at **eight trip cards**. Each card links its original publisher/date. Forecast-day selection does not move these historical reports into tomorrow. The source sheet can open the same dated evidence, with no claim of shore or dive results.

Unmarked counts mean **reported**, not necessarily retained. Missing reports or categories do not mean zero fishing/catch. Display bars compare reported counts within a trip; they are not probability, effort-adjusted abundance or catch-per-angler estimates. Landing port and optional broad ground text do not locate a fish. No reef pin, fish-location inference, AIS track, charter-stop claim or forecast/shore/dive ranking is generated from these totals.

This scope excludes prose, articles, photos, audio and bulk licensed operator data. Broader recurring database republication, raw-page archives, operator partnerships and movement/catch linkage require separate source agreements and review. No operator has been contacted. The existing implementation is not described as a licensed bulk feed or general permission to republish a publisher's product.

## Existing evidence and the feasibility gate

SkipperCast's September 21 audit processed eleven complete national NOAA daily broadcast files, retaining 37,202 regional broadcasts and 65 reported MMSIs from 106,892,412 national messages. It obtained **zero independently verified local sportfishing charter identities**. This was a finite sample, including June 24–30, not a complete fleet survey. An AIS broadcast name or vessel category does not verify an operator. Missing tracks do not establish no fishing, no AIS carriage or a rules violation.

The historical report audit collected 601 Morro/Avila trips across 173 pages, April 1–September 20. Named grounds were often absent or broad; multi-ground catch totals could not be allocated to an individual location. Fish's [current source review](../research/source-registry.md) directly verified local trip rows on September 27–28, while September 30 had no local rows and Virg's embedded count page still ended in May. Page accessibility and a “latest” heading do not establish recent local evidence.

The [NOAA 2026 broadcast index](https://noaaocm.blob.core.windows.net/ais/csv2/csv2026/index.html) returned HTTP200 on October 1 and still ended with `ais-2026-06-30.csv.zst`. These archives support historical analysis. A daily metadata check cannot turn them into a current tracking feed. The [official NOAA access guide](https://github.com/ocm-marinecadastre/ais-vessel-traffic) describes custom-area CSV access, bulk archives, experimental GeoParquet and source metadata. The inspected product license is CC0; retain exact downloaded-product terms and attribution.

## Sources, rights and cost choices

| Source | Planned role | Access and publication gate |
| --- | --- | --- |
| [SoCalFishReports boat-day pages](https://www.socalfishreports.com/dock_totals/boats.php?date=2026-09-27) | Existing linked trip facts; possible larger future feed | Small linked factual-count display uses the pinned reviewed scope above. No licensed bulk commercial feed established; broader systematic/bulk republication requires independent terms/permission. Do not copy creative articles, pictures or audio. |
| [Morro Bay Landing](https://morrobaylanding.com/our-fleet/), [Virg's Landing](https://www.virgslanding.com/), [Patriot Sportfishing](https://www.patriotsportfishing.com/) | Confirm fleet/operator context; future first-party trip and identity agreements | Operator websites and syndication may share one underlying report. Deduplicate; do not count them as independent catch observations. No operator has been contacted for this project. |
| NOAA Marine Cadastre / USCG NAIS | Free historical tracks and reception audit | Inspect exact broadcast interval, footprint, sample and quality transformations. Annual transit-count map services and one-position-per-day inventories cannot reconstruct fishing stops. |
| Operator-provided GPS or AIS logger exports | Verified trip coverage and activity labels | Future operator agreement must define use, retention, derived-map publication and location precision. Most valuable small pilot fallback when public AIS does not cover the fleet. |
| Licensed historical AIS | Fill demonstrated public track gaps | Obtain a vessel/date sample before a subscription. Quote historical depth, position frequency, regional reception, monthly usage, derived-area commercial display and raw redistribution separately. No supplier pricing or charter coverage has been verified. |
| [Global Fishing Watch](https://globalfishingwatch.org/our-apis/documentation/docs/license-rate-limits) | Separate research on apparent commercial fishing effort | CC BY-NC API terms require a commercial-use agreement for this sponsored product. Its fleet/activity models do not establish recreational charter identity, gear or catch. Do not import SkipperCast's noncommercial effort layer into Fish under assumed rights. |

The small reviewed catch-fact display can operate while the activity filter remains unavailable. For broader data and movement work, start with zero-cost identity research and a small operator-authorized pilot. Pay only after a sample demonstrates usable coverage of the actual named vessels. Establish a pilot spending cap before any purchase; no numeric supplier price is assumed here.

## Identity and coverage audit

Build a time-versioned fleet register with operator, home port, vessel name/aliases, dimensions, call sign, MMSI, evidence URLs, effective dates and reviewer. Discovery leads include Avenger, Endeavor (MB), Starfire, Fiesta, Rita G, Flying Fish, Patriot (Avila Beach) and Sunny Day, subject to current operator confirmation. Boat names can repeat, transfer or change; these are leads, not verified MMSIs.

Use the [USCG Vessel Information Verification Service](https://navcen.uscg.gov/ais-vivs-home) to compare broadcast fields with FCC station-license and USCG vessel-documentation records. Its coverage and latency are limited. Match dimensions, call sign, official registration and current operator evidence rather than accepting a similar name. Status is `verified`, `plausible` or `unresolved`; only verified identities can contribute public charter activity. [USCG AIS requirements](https://navcen.uscg.gov/ais-requirements) vary by vessel and operation, so completeness must be measured rather than inferred from those requirements.

For each verified boat, audit at least several complete, confirmed operating dates from each home port. Record expected departures, observed trips, first/last messages, median/p95 message gaps, along-track gap distribution, harbor reception, offshore reception and identity confidence. Report both tracked boats / confirmed active fleet and covered trips / known trips, with denominators and their evidence. Keep a per-date archive availability ledger. Sampling eleven national files does not establish statewide or local recreational charter coverage.

## Proposed broader collection and normalization

For a separately reviewed/licensed broader pipeline, collect reports evening and next morning; revisit the last 14 days for corrections. Preserve rights-permitted raw receipts, hashes, outcomes, clocks and parser versions. The current small binding consumes the upstream dated factual feed on report refresh and independently checks original day receipts; it does not implement Fish's own full-page collection/correction archive. Preserve species categories without turning ambiguous “rockfish” into a specific species. Keep reported, retained, released, unknown and explicit zero counts separate. A missing report is unreported, not a zero-catch trip.

Ingest movement records in bounded regional/date partitions using an offline/container job for large CSV/Zstandard/GeoParquet files. Cloudflare R2 stores permitted raw receipts; D1 indexes source versions, vessels, trips and aggregates. Normalize timestamps to UTC, speeds to knots, positions to stated source CRS and courses to degrees true. Keep broadcast time distinct from retrieval time. Deduplicate repeated messages, flag invalid coordinates, implausible jumps, duplicated timestamps and inconsistent MMSI/static information. Reconstruct trips across UTC midnight, rendering dates in America/Los_Angeles.

Use stable report IDs plus a revision table: boat identity + local trip date + departure/trip class where supplied + publisher record ID. A boat can run AM and PM trips on one date. Do not merge them because date and name match. Keep a source relationship graph to deduplicate syndicated reports.

## Activity classification and location inference

Segment each complete track into harbor/moored, approach or entrance, transit, search, stationary/anchor-like, drift-like, likely fishing, and unknown. Harbor polygons, dock areas, anchorages and navigation/entrance corridors are reviewed regional configuration. Harbor queuing, anchoring, idle time and waiting to cross a bar cannot become fishing stops.

Use position-derived speed, reported SOG, distance traveled, turning, net displacement, time in an area and repetition of drift passes. Consider daylight, trip class and vessel-specific behavior. Reported navigation status is supporting self-reported evidence. Fishing may involve drift or trolling; a speed-only stationary detector will miss those methods and confuse slow travel, wildlife viewing or mechanical delay with fishing.

A first transparent research rule can flag offshore intervals of at least 15 minutes below roughly 3 knots with multiple actual positions, or repeated short drifts separated by repositioning. These are **starting parameters for testing**, not established fishing thresholds. Preserve the original positions and uncertainty in the research record. Never bridge a reception gap and assign elapsed missing time as fishing. Start with a maximum allowed gap of five minutes; tune it against the vessel/source's message cadence and labels. Larger gaps split segments into unknown. Require several real observations across a candidate interval; never manufacture a dwell from two distant endpoints.

Manual reviewers label pilot tracks; operator-confirmed logs provide the strongest validation. Publish **inferred charter fishing activity**, with confidence reasons. A human's track interpretation is still inference unless the fishing activity was independently confirmed.

Link a catch report to a movement trip only when boat identity, date, departure/time and trip class support a unique match. Store the linkage confidence and rejected alternatives. Catch remains at trip level: a trip visiting four reefs with 20 lingcod does not establish where any individual fish was caught. Nearness to SkipperCast habitat is separate context and cannot turn the catch into a reef observation.

## Planned broader records

| Entity | Required fields |
| --- | --- |
| `VesselIdentity` | stable vessel ID, operator ID, home port, names/aliases, MMSI/call sign, dimensions, effective dates, evidence IDs, verification status/reviewer/date |
| `CatchTrip` | report ID/revision, vessel/boat identity confidence, local trip date, departure if known, trip class, anglers, target if explicitly reported, species retained/released counts, effort if known, named-ground text and precision, publisher/producer, publication/retrieval times, rights |
| `TrackReceipt` | source/version/hash, exact broadcast period, retrieved time, rights, geographic partition, retained/rejected counts, reception limits |
| `TrackPoint` | vessel ID, original MMSI, UTC broadcast time, lat/lon/CRS, SOG/COG/navigation status, position quality, duplicate/jump flags, source receipt |
| `ActivitySegment` | trip ID, start/end, observed point count, median/max gap, observed duration, movement features, candidate class, confidence reasons, classifier version, label/reviewer, geometry and position uncertainty |
| `TripReportLink` | trip/report IDs, matching evidence, competing matches, confidence, reviewer; no point-level species attribution |
| `ActivityArea` | aggregation period/cell or corridor geometry, distinct dates/trips/boats, observed activity minutes, source period, coverage denominator, latest observation, confidence method, legal/habitat review versions, publication rights and precision |

## Map, refresh and rollout

The future optional filter is **Inferred charter fishing activity**. Offer 30-day, 90-day and historical-season selections only for available broadcast dates. Aggregate drift corridors or cells at a declared display resolution, initially 500 m–1 km subject to actual position and inference error. Candidate publication requires repeat activity on at least three distinct trip dates and a reviewed sample; distinguish multiple vessels from repeated use by one vessel. These are proposed display gates to test, not statistically established thresholds. Avoid exact-stop pins, individual live tracks, fabricated heatmap gaps and a “proven successful spot” label.

Each area card shows dates, distinct trips/boats, source latency, coverage completeness, classification reasons, display resolution and any separately linked trip-level catch facts. Re-screen whole geometry against current MPAs/security restrictions, method-specific rules and available native depth. Areas with missing depth cannot claim 0–300 ft qualification. A historical track intersecting a current closure is not evidence of a violation under the rules that applied then; event-date research and current trip guidance are different tasks.

Check archive indexes daily, ingest only new source versions, rebuild aggregates weekly or when corrections arrive, and review vessel identities monthly. Licensed current feeds follow actual provider cadence. Every public layer states latest **broadcast** date. Catch trends can refresh daily even while movement archives remain months old. Sponsorship cannot change source confidence, activity classification or ranking.

Rollout gates:

1. **Rights and identity:** source terms support commercial derived-map publication; at least one pilot vessel is independently verified. No current fleet coverage claim.
2. **Reception feasibility:** confirmed full trips from both ports if claiming both-port coverage; quantify gaps and tracked share. Narrow the advertised scope when coverage is partial.
3. **Classifier validation:** review diverse transits, anchorages, search/drift/troll behavior and actual fishing labels. Split validation by trip/vessel/date, not individual neighboring points. Measure precision, false positives and recall separately; tune only on training examples.
4. **Public display validation:** require high precision for published likely-fishing segments, repeated independent trip dates and complete provenance. Select the numerical acceptance target after the pilot; disclose sample size and confidence uncertainty. Unvalidated scores are not probabilities.
5. **Reproducibility and monitoring:** source changes and corrections regenerate affected trips/areas; missing identities, changed rights or degraded reception withdraw affected areas. Catch corrections retain revision history.

The first **activity-pipeline** deliverable is a go/no-go pilot: verified registry, access/rights table, reception audit, a manually labeled set of complete trips and a proposed aggregation screenshot. Public charter activity remains unavailable until those gates pass. The separate small reviewed factual trip display does not satisfy or bypass any AIS/activity gate.
