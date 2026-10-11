> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `research/fishing-needs.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# SLO Fish Report: fishing needs and forecast methodology

Research date: October 1, 2026. Scope: marine recreational fishing in San Luis Obispo County for the first release. Commercial readers can use conditions, but commercial eligibility and regulations require a separate ruleset. Product name/domain: SLOFishReport.com. This document specifies a proposed method, not a live report or validated catch prediction model.

## Product promise

Answer four questions for a selected place and fishing method: **What are conditions like? What can I reasonably target? When are conditions most favorable? What information is uncertain or missing?** Offer today's hourly view, tomorrow's plan, and a short outlook. Describe favorable operating windows and recent catch evidence independently; calm water, high tide, and good habitat do not establish an imminent bite.

The existing SkipperCast bite evidence review (Fish `../../skippercast-best-trip-export/docs/bite-evidence.md`, not archived) already records the main evidence gap: standardized local catch effort including unsuccessful trips. Reuse its schema and documented collectors after checking their present operation. Do not copy its saved numbers into a current daily report.

## Needs by fishing mode

The table is a product requirements synthesis. Fields are inputs to useful decisions, not claims that every variable predicts catch.

| Mode | Questions to answer first | Essential conditions | Fishing context | Distinct needs and missing-data behavior |
| --- | --- | --- | --- | --- |
| Boat | Can this launch, route, fishing area, and return fit my boat and limits? Which legal habitat matches my target? | Hourly wind/gust/direction, combined seas, swell components and period/direction, observed buoy trends, fog/visibility, alerts, tide at launch/harbor, current source and depth | Surveyed depth and hard/soft bottom, target species and season, recent boat reports, actual drift if supplied; SST/front context for offshore search | Separate small powerboat, kayak, and charter passenger profiles. Evaluate the whole outing including return. Harbor/bar status needs a local authoritative source; a generic ocean model cannot clear an entrance. Unknown route or bar conditions stay unknown. |
| Shore | Which accessible beach, pier, or rocky shore suits my target and conditions? Will tide or surf remove my access? | Surf/shore hazard products, swell direction/period, local exposure, tide curve and access constraints, wind affecting casting, precipitation/runoff and water-contact advisories | Sandy surf versus rocky reef versus estuary versus pier, target-specific habitat/gear guidance, dated local observations | Separate dry pier fishing from surf wading and rock fishing. Boat swell height is not beach breaker height. Store access hours, closures, license context, and whether the exit is tide-dependent. Public access and accessibility need direct local verification. |
| Spearfishing | Is entry/exit usable, what is known about clarity and current, and is my target legal? | Entry-site surf/exposure, swell period and surge context, current/drift source, observed water temperature, water quality, recent in-water visibility observations | Shallow surveyed habitat, kelp/reef context, species identification, method-specific rules, exact MPA boundaries | A satellite pixel cannot supply trustworthy diver horizontal visibility in feet. Show observed visibility with time/depth/location and label clarity proxies. No observation means visibility unknown. Site needs boat traffic and exit context; no automated score certifies a dive as safe. |

NWS marine point forecasts represent a forecast grid cell rather than measurements at a precise pin; NWS describes a typical cell as about 2.5 km. Point conditions can be milder than a zone advisory, which still applies to the zone. Use both the point and zone products. [NWS marine point forecast documentation](https://www.weather.gov/marine/point).

For most of the SLO coast, NWS lists PZZ645 from Point Piedras Blancas to Point Sal within 10 nautical miles and PZZ670 at 10–60 nautical miles. The county extends beyond the northern Piedras Blancas boundary: determine zones by point/polygon and support adjoining forecast-office products rather than hardcoding a single county marine zone. The LOX product directory also supplies surf-zone forecasts. [NWS LOX marine zones](https://www.weather.gov/marine/loxmz).

## Local geography and species

Create subregion records for the north county coast/San Simeon, Cambria–Cayucos, Morro Bay harbor and open coast, Montaña de Oro–Point Buchon, and Avila/Port San Luis–Pismo/Oceano. These are editorial areas, not interchangeable ocean forecasts. Every actual place also needs coordinates or a polygon, habitat/access type, coastal orientation, exposed swell sectors, launch/entry/exit information, legal overlays, and applicable forecast/tide/current bindings. Keep sheltered harbor, exposed ocean, and surf-zone inputs distinct.

Start species cards with lingcod, identified rockfish groups, cabezon/greenlings, California halibut, surfperch, and sanddabs where local evidence supports them. Seasonal or occasional targets can appear after current reports and legality are reviewed. NOAA supports rocky reef as habitat for lingcod, many rockfish, and cabezon; this supports a candidate habitat overlay, not fish occupancy or an exact catch claim. Lingcod habitat also varies by life stage. [NOAA rocky reef](https://www.fisheries.noaa.gov/west-coast/habitat-conservation/rocky-reef-west-coast), [NOAA lingcod](https://www.fisheries.noaa.gov/species/lingcod).

Use species scientific IDs and preserve published labels. Do not infer individual rockfish species from a report saying “rockfish,” or combine California and Pacific halibut. Target cards should describe suitable habitat, methods, identification, current eligibility, and supporting dated evidence. Depth/bottom confidence comes from SkipperCast survey provenance and resolution, not how detailed a rendered map looks. Surface SST is surface context; it does not measure bottom temperature over a 300-foot reef.

## Tides, currents, surf, and visibility

Publish a full tide curve with high/low events, rising/falling stage, height, units, station, datum, and timezone. Bind a supported local station or official subordinate prediction to each place. Tide is vertical water level; current is horizontal flow. Do not relabel a high/low tide event as slack current or infer Morro Bay entrance current from Port San Luis tide predictions. NOAA current products explicitly distinguish maximum flood, maximum ebb, and slack. Astronomical tides also omit wind, pressure, and river-driven water-level changes. [NOAA currents](https://www.tidesandcurrents.noaa.gov/currents_info.html), [NOAA WCOFS](https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs.html).

Preserve swell components and direction/period; an offshore significant wave height is an average of the highest third, not a maximum wave or local shorebreak height. NWS notes larger individual waves may occur. Long-period swell can raise rip-current risk even when the offshore surface seems quiet. [NWS significant wave height](https://www.weather.gov/key/marine_sigwave), [NWS rip-current FAQ](https://www.weather.gov/safety/ripcurrent-faqs).

For spear visibility, prioritize recent local diver observations with estimated horizontal distance, time, depth, method, and location accuracy. Satellite chlorophyll, Kd490, rainfall, wave resuspension, and runoff can provide contextual evidence. NASA defines Kd490 as attenuation of downwelling light at a wavelength; it is not horizontal underwater sight distance. Coastal optical variability creates further limits. Preserve quality/cloud gaps; never convert low chlorophyll directly into “20 ft visibility.” [NASA Kd490](https://modis.gsfc.nasa.gov/data/dataprod/kd_490.php), [NASA ocean optics protocols](https://oceancolor.gsfc.nasa.gov/resources/docs/technical/protocols_ver4_voli.pdf), [CeNCOOS satellite coverage](https://www.cencoos.org/observations/satellites/recent-sst-and-chlorophyll-a/).

SLO County samples 19 coastal locations weekly and supplies water-contact advisories/closures through SurfSafeSLO. Its significant-rain guidance advises avoiding water contact for 72 hours. Carry the official advisory geometry/status and original sample time; a weekly test is not real-time assurance. Apply these notices especially to spearfishing and wading. [SLO County water quality](https://www.slocounty.ca.gov/departments/slo-health/public-health/environmental-health-services/all-environmental-health-services/recreational-health/beach-water-quality-monitoring).

Link an appropriate concise freediving preparation resource in spear mode, without generating breath-hold depth/time advice. DAN emphasizes trained direct buddy supervision and training; this cannot be replaced by favorable environmental conditions. [DAN freediving safety](https://dan.org/alert-diver/article/freediving-safety/).

## Favorable window methodology

1. **Eligibility first:** resolve the selected date, exact area, species, method, season/depth/gear constraints, and legal exclusion geometry. If unresolved, the recommendation is “verify restrictions,” with the official source. Apply active hazard/water-contact notices prominently; do not average a warning away with attractive weather or catch evidence.
2. **Calculate operating suitability by mode:** compare hourly wind, waves, exposure, currents and access with reviewed location/method profile limits. The initial result should be reasoned labels such as “lighter wind before noon; afternoon return becomes rougher,” not catch probabilities. Small-boat, kayak, and dive limits need expert review and personal preferences; do not invent a universal safe-wave cutoff.
3. **Preserve unknowns:** use `unknown` for missing current, visibility, closure status or key observations. Never impute zero wind, calm current, clear water or an open season. Do not award a high confidence recommendation when essential evidence is absent.
4. **Find continuous usable periods:** propose two or three hourly windows that include getting there, actual fishing time, and the return/exit. A favorable hour with a poor return is not a favorable boat trip. Tide stage can describe water depth and access; no generic incoming-tide bite bonus.
5. **Attach target evidence independently:** combine reviewed habitat relevance, historical season context and recent dated local reports as separate evidence cards. Show report date, source, boats/dates observed, and scope. Missing reports mean missing observations, not zero catches. Public landing counts have targeting, retention-limit and reporting biases; even catch per angler is not standardized CPUE.
6. **Write deterministic findings before prose:** create structured facts, reasons, unknowns, source IDs and timestamps. Report prose may summarize only those findings. Every prominent claim should link to its supporting source. A missing source produces a partial report, not invented detail.

Moon phase, solunar windows, pressure, and tide stage can be stored as candidate study variables. They receive no automatic bite weight. A future catch model needs target-specific effort (fishing duration, anglers/lines, gear, target, approximate habitat/depth), encounters/kept/released fish including zero-catch segments, and environmental data available before each trip. Compare a proposed model against a simple area/season baseline; hold out future periods and separate boats/areas. Publish calibration and error before promoting numerical catch probabilities.

## Horizon and refresh policy

These are initial product choices to validate, not a claim that forecasts become inaccurate at a universal hour:

| Horizon | Product treatment |
| --- | --- |
| Now/today | Hourly forecast plus latest nearby observations and active alerts; distinguish observed values from future model values. |
| Next 24–48 hours | Main planning detail, with source run, coverage and limitations. |
| 48–72 hours | Provisional windows; widen the language if models disagree or no observation exists. |
| Days 4–5 | Broad wind/swell trend and “check again” planning context, suppress exact dive-visibility or bite times. |
| Beyond day 5 | Optional coarse weather outlook or astronomical tides, clearly separated from short-range fishing recommendations. |

WCOFS documentation currently gives one daily 03Z cycle and a +72-hour forecast, so its last valid time cannot extend automatically with the page date. NWS point products provide seven-day text forecasts, but product availability is not demonstrated fishing prediction accuracy. [NOAA OFS FAQ](https://tidesandcurrents.noaa.gov/ofs/ofs_faq.html), [NWS point documentation](https://www.weather.gov/marine/point).

Proposed refresh: observations and alert checks every 15–60 minutes with provider-friendly caching; forecast ingestion when a new run is available; catch reports daily plus recent-date corrections; regulations checked daily with review on detected change; bottom habitat rebuilt only after surveyed data updates. Generate the daily editorial report before dawn Pacific time and revise structured outlook facts when conditions materially change. Keep `observed_at`, `issued_at`, `valid_at`, `retrieved_at` and `report_generated_at` distinct. Review stale thresholds per variable/provider; do not use one freshness flag for an entire station.

Archive issued forecasts before their valid time, then compare wind/waves/temperature against appropriate station observations by location and lead time. Keep forecast error distinct from point-to-station representativeness error. The page can later disclose actual local verification instead of unsupported labels such as “super accurate.”

## Rules and expansion

CDFW's Central recreational summary covers SLO County and was marked updated October 1, 2026 when inspected. Preserve method distinctions: for example, the summary has different eligibility for boat anglers versus divers/shore anglers for sheephead. Exact regulations and in-season notices control; a generic “open” icon is incomplete. [CDFW Central summary](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central), [in-season changes](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Inseason).

Review local MPA polygons with their exact permitted take, not a universal “all MPAs prohibit fishing” rule. Important SLO references include [Point Buchon](https://wildlife.ca.gov/Conservation/Marine/MPAs/Point-Buchon), [Cambria/White Rock](https://wildlife.ca.gov/Conservation/Marine/MPAs/Cambria-White-Rock), and [Morro Bay](https://wildlife.ca.gov/Conservation/Marine/MPAs/Morro-Bay). Shore cards must also distinguish qualifying public-pier license exemptions from beach/rock access, and confirm whether the facility is open. [CDFW pier and beach guidance](https://wildlife.ca.gov/Fishing/Ocean/Beach-Fishing/1000).

Keep county definitions, locations, station bindings, species evidence, exposure/entry profiles, legal geometry and sponsors as configuration. Share collectors, schemas, conditions logic, report renderer and verification tools. Adding Monterey or Santa Barbara requires a fresh coverage/regulation/access review; duplicating SLO's station IDs and score thresholds is not regional support. Commercial fishing rules require a separate harvest-mode layer, as CDFW maintains separate commercial regulations. [CDFW regulations](https://wildlife.ca.gov/Regulations).

## First implementation slice

Build boat, shore and spear report views for a small, explicitly reviewed location set around Morro Bay and Port San Luis. Include hourly wind/swell, full tides, active hazards, legal links, clear missing-data states, target habitat context and dated local catch evidence. Spear mode initially shows **visibility unknown** unless a credible current in-water observation exists. Add three-day planning detail and a five-day broad trend. Make the favorable-window rules explainable, record every input, and add no catch probability until a local study supports one.
