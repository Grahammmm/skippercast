# SkipperCast competitor analysis
_v2 2026-11-19: SkipperCast facts from repo replace assumptions; recs re-ordered; rankings re-scored for California focus._ · Page: https://cursor.com/canvas/store-0c376c2f-e405-4dea-a9cb-a3cbd0b9a208/5bf1a2db-7cec-45e9-b192-deeae716534a

## SkipperCast today (from the repo)
Phone-first web app (v0.8, pre-beta): fishing map + ocean forecast for boat anglers on California's Central Coast. MapLibre + PMTiles on a self-hosted Protomaps basemap, NOAA ENC chart, 2D/3D terrain. Morro Bay & Avila active; 15 regions preview; 6 SoCal draft. Bottomfish/reef focus (habitat candidates, rules), not offshore pelagics.

Repo: https://github.com/Grahammmm/skippercast · Site: https://skippercast.com
Source: Repo github.com/Grahammmm/skippercast at commit fa9c3581 (2026-11-19), README.md, docs/roadmap.md ('What ships now'), docs/web-app.md, docs/boat-profile.md, web/map/layers.ts, catalog/app/strings.json; live site https://skippercast.com (HTTP 200).

### Has
- Per-layer basis sentence with source, product/grid and age; layers withheld past age limits; /status data-freshness page
- Forecast skill page (/skill) and in-brief measured-skill line vs buoys
- Shareable links that reopen region, port, profile, day, hour, target, view, layers, base
- 7-day hourly time dock (169 samples) scrubs/plays forecast layers; Conditions view compares NOAA (GFS/GFS-Wave) vs ECMWF (IFS/WAM) and states disagreement
- Boat profile (AI spec lookup or manual) scaling an hourly conditions score; day verdict Comfortable/Marginal/Rough/Unknown with the limiting factor
- Layers: water temp + 0.5 °F contours, SST contrast, SST fronts with uncertainty band, chlorophyll (NOAA OCI, dated), currents (WCOFS / HF radar, animated), swell, wind, clouds, seafloor habitat, relief, depth contours, MPAs, charter grounds, commercial AIS
- Where to look: ranked habitat places with up to 3 dated, sourced reasons
- Boat run: run time at your cruise speed by water route, turn-back time, bar-crossing leave-by/be-back-by at Morro Bay
- Saved-trip alerts (passkey account) when the assessment materially changes and the day before; home-port alert
- Saved spots (up to 100), private catch/effort log, comfort feedback
- Offline trip pack (ENC tiles + data, service worker); GPX/share-sheet/offline-notes export; every exported place screened against protected areas
- Rules cards and season calendar from CDFW; Reports view (dated catch cards, charter evidence); English + Spanish
- Text Advisor (SMS/Instagram advisor, skipper reports, fish ID, daily 'what's biting') built but switched off

### Lacks (not found in repo)
- Tap-to-read on every layer at once: today one reading at a time for water temp, contrast, currents, fronts and swell, and none for chlorophyll or wind. No user-adjustable colour ramp: the SST ramp auto-fits the analysis range but can't be fitted to the view or set by hand.
- Playback of past days for observed layers (time dock runs forward hourly; History view is station history only)
- Chlorophyll edges and eddy detection (fronts exist for SST only); sea surface height/altimetry
- Subsurface temperature, thermocline, mixed layer depth, salinity, dissolved oxygen
- Threshold alerts on a saved spot's water, and new-satellite-pass alerts
- Heading-dependent ride (boat model explicitly ignores heading); ride/track recording that feeds the boat model
- Conditions recorded at each catch (catch log stores outcome + optional position only)
- Fuel estimate (explicitly left to the skipper); GPX import in the UI (a parser exists in web/gpx-waypoints.ts, unwired)
- Native App Store / Google Play apps; broad active coverage (one active region vs competitors' 15–34)
- Offshore pelagic species modes / habitat suitability (by design it ranks habitat, not catch odds)

_Graham's phrases 'subsea weather' and 'raw general base layer map' don't appear in the repo; the closest layers are currents/water temp and basemap + ENC + seafloor._

## Ranked list
| # | App | Rel | Qual | Threat | Total/30 | Why |
|---|---|---|---|---|---|---|
| 1 | RideScore (Solitary Labs) | 9 | 9 | 9 | 27 | Does what SkipperCast's boat verdict does, plus heading and ride recording, natively and already advertising on Instagram. |
| 2 | Fish or Pass (Set Sale Marine) | 10 | 8 | 9 | 27 | Same California coast and same honesty stance, but already scores the whole SoCal Bight per species, where SkipperCast's SoCal is still preview/draft. |
| 3 | Salty Offshore | 9 | 9 | 8 | 26 | Closest analog to SkipperCast's multi-layer, subsurface-aware map, plus a logbook that learns from trips. |
| 4 | Fishare (Fishare Pro) | 9 | 9 | 7 | 25 | Best-in-class SST/subsurface UX and honesty at a low price; directly overlaps SkipperCast's subsea layer. |
| 5 | SiriusXM Fish Mapping (OceanBytes) | 8 | 7 | 8 | 23 | Big-brand relaunch with AI zones and thermocline; sets a price anchor at $199–$299/yr. |
| 6 | FishTrack (Surfline/Wavetrak) | 8 | 7 | 7 | 22 | The incumbent most new entrants position against; large install base. |
| 7 | Rigline Offshore | 8 | 7 | 7 | 22 | Free, explainable hotspot ranking built from the same layers; strong pattern for SkipperCast's decision layer. |
| 8 | PredictWind | 7 | 9 | 6 | 22 | Gold standard for weather UX; motion metrics overlap SkipperCast sea conditions. |
| 9 | BlueFronts | 8 | 7 | 6 | 21 | Small but sharp UX ideas (auto-scaling SST, box reports) that map directly onto SkipperCast's rendering. |
| 10 | Windy.com | 7 | 9 | 5 | 21 | The visual bar users will compare SkipperCast's weather layer against. |
| 11 | SeaLegs AI + DeepCast | 7 | 7 | 6 | 20 | Shows the AI-interpretation layer users now expect on top of raw ocean maps. |
| 12 | RipCharts | 7 | 7 | 6 | 20 | Respected incumbent; range slider and SST forecast are table stakes now. |
| 13 | SatFish (Bloodydecks) | 7 | 6 | 6 | 19 | Mainstream SST app that has already shipped playback and range controls. |
| 14 | Fishdope (Bloodydecks) | 7 | 6 | 6 | 19 | Shows paid demand for human fishing intel layered on SST. |
| 15 | GulfWire (Gulfwire LLC) | 6 | 6 | 5 | 17 | Gulf-only, so little overlap; its fuel planner and community feed are the borrowable parts. |
| 16 | BigBlue (GeoPelagic) | 6 | 7 | 4 | 17 | Pro-grade data cadence (hourly GOES, PACE) worth matching for SkipperCast's raw-data positioning. |
| 17 | BoatNGo (+ FishNGo) | 6 | 6 | 5 | 17 | Same score-for-your-boat idea as RideScore at a lower price; window comparison is a good UX detail. |
| 18 | Buoyweather (Surfline/Wavetrak) | 6 | 6 | 5 | 17 | Classic offshore point forecast; route forecast pattern. |
| 19 | Surfline | 5 | 9 | 3 | 17 | Best swell visualization; different audience. |
| 20 | Navionics Boating (Garmin) | 6 | 7 | 4 | 17 | Base-map benchmark; low ratings show room for a better UX. |
| 21 | Cobia | 5 | 7 | 4 | 16 | Retention mechanics and tide-animated scoring worth borrowing; less of a data-layer rival. |
| 22 | SkeeterCast | 6 | 6 | 4 | 16 | Bundles weather, ocean layers and AI for the same coastal user; broad but less polished. |
| 23 | SeaStatus: Launch Conditions | 6 | 6 | 4 | 16 | Tiny but clever framing; trip-mode monitoring is a cheap, high-value alert pattern. |
| 24 | Savvy Navvy | 5 | 8 | 3 | 16 | Design reference for a calm, uncluttered base map. |
| 25 | Orca | 5 | 8 | 3 | 16 | Rendering reference for a modern vector base layer. |
| 26 | Hilton's Realtime-Navigator (RT-Nav) | 6 | 5 | 4 | 15 | Legacy pro tool; weekly pass is a pricing idea. |
| 27 | Wavve Boating | 5 | 7 | 3 | 15 | Simple, powerful personalization of the base layer. |
| 28 | RipVision AI | 5 | 6 | 3 | 14 | Good model for documenting each layer's source and palette. |
| 29 | ROFFS | 5 | 6 | 3 | 14 | The $90 benchmark AI-report startups undercut. |
| 30 | Fishbrain | 3 | 7 | 3 | 13 | Scale benchmark; little offshore ocean data. |
| 31 | Fishing Points | 4 | 6 | 3 | 13 | Popular tide/solunar reference for SkipperCast's tides layer. |
| 32 | Aqua Map | 4 | 6 | 2 | 12 | Shows value of dated survey overlays on a base map. |
| 33 | Go or No? Marine Boat Weather | 5 | 4 | 2 | 11 | Low traction, but the 'now vs later' sentence is a free UX win. |
| 34 | Pathr Navigation | 4 | 5 | 2 | 11 | New nav entrant; seabed overlay idea for base layer. |
| 35 | DECKEE | 3 | 5 | 2 | 10 | Safety/alerts patterns; small US footprint. |
| 36 | Salinity | 5 | 3 | 2 | 10 | Not shipped yet, but its telemetry angle overlaps SkipperCast's raw-sensor approach. |

## Feature recommendations (effort is an estimate)
| # | Feature | Status | Effort | Layers | Inspired by | Why |
|---|---|---|---|---|---|---|
| 1 | **Full tap-to-read + adjustable colour ramps** — Tap any point for the exact water temp, chlorophyll, swell or current value; range slider and 'fit to view' on the legend. | new gap | S | water temp, chlorophyll, swell, currents | Fishare, BlueFronts, RipCharts, SatFish v2, Salty Offshore | Partly shipped: web/map/chart.ts reads one value at a tap for water temp, contrast, currents, fronts and swell, and none for chlorophyll or wind. The SST ramp auto-fits the analysis range, but users can't fit it to the view or set it. Cheapest upgrade to every raster layer. |
| 2 | **Look-back playback for observed layers** — Extend the time dock 3–7 days into the past for SST, fronts and chlorophyll so users watch a front move, then continue into the forecast. | extends shipped time dock | M | water temp, SST fronts, chlorophyll | Fishare, Salty Offshore, SatFish v2 | The time dock only runs forward hourly; History is station-only. |
| 3 | **Water-condition alerts on saved spots + new-data alerts** — 'Tell me when water at this spot is above 58 °F' and 'new chlorophyll sample landed', on the existing passkey account and alert pipeline. | extends shipped alerts | M | water temp, chlorophyll, swell | Salty Offshore, SeaStatus | Saved-trip alerts already exist; spot thresholds reuse that plumbing. |
| 4 | **Heading-aware comfort + learn from rides** — Add a heading rose to the boat verdict and use comfort feedback (and optional phone-motion ride recording) to calibrate the boat multipliers. | extends shipped boat profile | M | sea conditions (swell, wind) | RideScore, PredictWind (motion data) | docs/boat-profile.md says the model ignores heading and names comfort feedback as the calibration path. Comfort feedback already stores heading, phase, wind, sea and period. RideScore ships both. |
| 5 | **Chlorophyll edges, eddies and SSH** — Add detected chlorophyll edges and eddy outlines beside the existing SST fronts, plus a sea-surface-height layer. | extends shipped SST fronts | M | chlorophyll, currents / subsea | Fishare, BlueFronts, SiriusXM Fish Mapping, Salty Offshore | SST fronts and contrast already ship with uncertainty bands; the other edges are missing. |
| 6 | **Conditions at each catch** — When a catch-log entry has a position and time, store the layer values there (temp, chlorophyll, swell, current, tide) and show them back; optional track recording. | extends shipped catch log | M | all layers | Salty Offshore, RideScore | Catch log stores outcome + optional position only; joining it to layers builds SkipperCast's own evidence. |
| 7 | **Subsurface depth ladder (if 'subsea weather' means below-surface)** — Temperature at 10–100 m, thermocline/MLD, salinity, labelled as model output, switched like a depth slider. | new gap; confirm scope | L | subsea weather | Fishare, Salty Offshore Elite, SiriusXM Fish Mapping, RipCharts | Not in the repo; its water-temp basis says it is 'neither bottom temperature nor a forecast'. Confirm Graham's intent first. |
| 8 | **Small trip-plan gaps: GPX import, optional fuel estimate** — Import waypoints from chartplotters; optional fuel = run distance × burn the user enters. | extends shipped planner | S | base map, sea conditions | Salty Offshore, GulfWire, BoatNGo | GPX export, run time and a worst-hour line in the brief already exist. A GPX waypoint parser exists (web/gpx-waypoints.ts) but no UI uses it. Fuel is deliberately left to the skipper today. |
| 9 | **Launch the built Text Advisor / AI briefing** — Owner launch steps only; it already covers reports, rules, fish ID and daily 'what's biting'. | built, not launched | S | all layers | SeaLegs AI, SkeeterCast, Cobia | Competitors ship AI briefings now; SkipperCast's is built but dark. |
| 10 | **Coverage and distribution** — Move preview regions to active (SoCal first, where Fish or Pass operates) and consider a store-listed wrapper app. | roadmap item | L | all layers | Fish or Pass, Salty Offshore, RideScore | One active region vs 15–34 for competitors; every rival here is in the App Store. |

### Already shipped in SkipperCast (dropped from recs)
- Freshness/provenance labelling (basis sentences, /status, withholding)
- Shareable exact-view links
- Forward hourly time scrubber + model comparison
- Vessel profile + personal comfort verdict
- SST front detection with uncertainty
- Base map: ENC, relief, contours, MPAs, habitat, 2D/3D
- Offline pack + GPX export
- Explainable ranked places with dated reasons
- Public forecast scorecard (/skill)

## Per-app breakdown
### 1. RideScore (Solitary Labs)
- website: https://solitarylabs.com/ridescore
- app_store: https://apps.apple.com/us/app/ridescore-marine-forecast/id6814978445
- support: https://solitarylabs.com/support
- ads_tracker: https://appmarketspy.com/app/ridescore-marine-forecast-6814978445
- Pricing: Free tier; Pro $12.99/mo or $99.99/yr (App Store US IAP list).
- Rating: 4.2 (5 ratings, App Store US)
- Target: Coastal/offshore powerboaters in US East, Gulf, West Coasts, Hawaii, PR/USVI, Bahamas, Bermuda.
- Core: One comfort score per hour for YOUR boat, 11 days out, painted on the map (tap boat chip to re-score map); Wind, gusts, waves, swell, tide, current, first/last light under the score; Ride Rose: how the ride changes with heading (head/beam/following seas); Helm: live gauges during a ride vs forecast; report for every trip led by its roughest 10 minutes; shareable card; BoatScore: roughest water the boat can run before 'Rough'; 'Tested in' Calm/Moderate/Rough; Pro learns your boat from recorded rides; rides uploaded to improve the forecast; Offline forecast around you; spots with calmest windows; alerts; NWS advisories; radar, currents, sea-temp maps
- Differentiators: Phone-sensor ride telemetry feeds back into the forecast model; Same ruler for harbor and blue water; Running Facebook/Instagram ads now (AppMarketSpy: 4 active US ads)
- Worth borrowing: Personalized sea-state score per vessel; Heading-dependent 'Ride Rose'; Forecast-vs-felt trip report from device telemetry
- SkipperCast already has: Boat profile scaling an hourly conditions score; Day verdict with limiting factor; Comfort feedback API (calibration path); Saved-trip alerts
- SkipperCast lacks (per repo): Heading-dependent Ride Rose; Ride recording with live gauges that learns the boat; 11-day horizon (SkipperCast: 7); Score painted across the whole map per hour; Native iOS app; whole US coast coverage

### 2. Fish or Pass (Set Sale Marine)
- website: https://www.fishorpass.com/
- how_it_works: https://www.fishorpass.com/how-it-works
- pricing: https://www.fishorpass.com/pricing
- disclaimer: https://www.fishorpass.com/score-disclaimer
- Pricing: Angler $149/yr after 7-day trial (card up front); Captain $249/yr announced, not for sale yet.
- Rating: n/a (web app; no App Store listing found)
- Target: Southern California saltwater anglers (private boats, charters, pier/shore) from 9 home ports; 7 graded species.
- Core: Bite Score 0–100 + one-word verdict: Catching / Fishing / Pass, per patch of water and species; Six signals: recent activity, water temp & breaks, structure & depth, kelp & bait, sea conditions, tide & current; Confidence indicator on every read; yesterday's card graded against actual catches; Saved boat + range: unreachable water greys out for today's sea state; Water temp, chlorophyll, temp breaks, kelp, bathymetry overlays; MPA + regulation overlay; go/no-go sea-state call; No-account demo running on a real sample day
- Differentiators: Self-grading accuracy loop shown to users; Hyper-local (one bight, 7 species) with port guides; Roadmap shown openly on the pricing table (SOON rows)
- Worth borrowing: Confidence indicator per cell; Grey-out water you can't reach today; Public 'how we did yesterday' scorecard
- SkipperCast already has: Forecast skill page vs buoys (similar honesty); MPA + CDFW rules cards and season calendar; Habitat, bathymetry, water temp, chlorophyll layers; Boat range (Reach layer)
- SkipperCast lacks (per repo): Species bite score and Catching/Fishing/Pass verdict; Grading yesterday's call against what boats caught; Coverage of the whole SoCal Bight today (SkipperCast's SoCal is preview/draft)

### 3. Salty Offshore
- website: https://saltyoffshore.com/
- app_store: https://apps.apple.com/us/app/salty-offshore/id6741581379
- google_play: https://play.google.com/store/apps/details?id=com.saltyoffshore.android
- pricing: https://saltyoffshore.com/buy/compare
- web_app: https://saltyoffshore.com/app
- Pricing: Basic $99.99/yr (1 region, 3 datasets) · Pro $199.99/yr or $24.99/mo (2 regions, 5 datasets) · Elite $500/yr (all regions, 10 datasets) · AIS add-on $9.99. 7-day trial on Pro/Elite. Source: saltyoffshore.com/buy/compare + App Store IAP list.
- Rating: 5.0 (15 ratings, App Store US)
- Target: Offshore captains and serious recreational offshore crews; 34 regions on five continents.
- Core: SST, water color/chlorophyll, currents, sea surface height, salinity with depth, subsurface temp, dissolved oxygen, mixed layer depth, FSLE fronts, phytoplankton; Overlay two datasets on one chart; temperature breaks and eddies outlined; Water Playback of recent satellite passes; weather (wind, gusts, pressure, radar); Shaded relief + depth contours; AIS vessels; live buoys; bite windows and tides; Trip Tracker, hands-free logging via Lock Screen/Siri, end-of-trip summary; Conditions at every bite, trip analysis, season patterns, waypoint history; Condition alerts at a waypoint; new-satellite-pass alerts; offline maps; GPX import/export; Share a map link that opens the exact region, layers, ranges and satellite frame
- Differentiators: Closes the loop: plan on ocean data → record the trip → see the water at every bite → season patterns; Deepest subsurface stack of the new entrants (DO, MLD, subsurface temp, FSLE); User-tunable color ranges and saved layer setups
- Worth borrowing: Exact-view share links (layers + range + frame); Condition alerts: 'tell me when the water at this waypoint hits X'; Conditions-at-every-bite logbook; New-satellite-pass alerts with coverage % per pass
- SkipperCast already has: Multi-layer map with SST, chlorophyll, currents, fronts, relief, contours; Share links; Saved spots, catch log, offline pack, GPX export
- SkipperCast lacks (per repo): Subsurface stack (subsurface temp, MLD, DO, salinity, SSH); Satellite-pass playback; Conditions at every bite + season patterns; Waypoint threshold alerts and new-pass alerts; GPX import; native apps; 34 regions

### 4. Fishare (Fishare Pro)
- website: https://fishare.app/offshore-pro
- app_store: https://apps.apple.com/us/app/fishare-offshore-sst-charts/id6783726939
- hsi: https://fishare.app/hsi/
- Pricing: Fishare Pro US$8.99/mo or US$79/yr on web (App Store IAP lists $8.99 and $79.99); forecast, map, tides, logbook free. 7-day trial, no card.
- Rating: No ratings yet (App Store US)
- Target: Bluewater anglers across 15 regions (US NE canyons, Gulf, West Coast, Hawaii, Baja, Caribbean, AU/NZ, Japan, UK & Ireland, etc.).
- Core: Every VIIRS/AVHRR SST pass of last 72h drawn as seen (clouds left as holes), checked hourly, break auto-found and labelled; 24h/72h composites, hourly GOES/Himawari frames, daily gap-filled field with isotherms; Scrub back 7 days and forward 5 days on one timeline; 30-day pass history; Eddies drawn as closed break lines on the SST map with °C step; SSH with labelled contours; current vectors; Temperature at 25/50/75/100/150/200 m, checked against Argo floats, labelled as model output; Chlorophyll-a + 250 m VIIRS true colour; per-species habitat score (HSI) re-scored hourly; Tap anywhere for the actual value; GPX import; GO TO bearing/distance/ETA; one-tap share of the current pass
- Differentiators: Radical data honesty: observed vs model labelled; no accuracy claims; Pass-level SST instead of only composites; Cheapest full offshore stack ($79/yr, all regions)
- Worth borrowing: Auto-labelled fronts with °C-delta chips; Depth ladder UI that re-renders the whole field per depth, with stamped legend (T@50M °C); Past+future on one scrubber; Tap-to-read exact value
- SkipperCast already has: SST fronts with uncertainty band, SST contrast, chlorophyll; Honest source/age labelling and withholding; Forward 7-day time dock
- SkipperCast lacks (per repo): Pass-by-pass SST with clouds as holes; 7-day look-back on the same scrubber; Eddies, SSH, subsurface temp at depth; Tap-to-read on all layers at once; Species habitat score

### 5. SiriusXM Fish Mapping (OceanBytes)
- press_release: https://investor.siriusxm.com/news-events/press-releases/detail/2316/siriusxm-launches-all-new-fish-mapping-app-with-enhanced
- app_store: https://apps.apple.com/us/app/fish-mapping/id6450968706
- website: https://www.siriusxm.com/fishmapping
- Pricing: App-only: 1-Week Mobile+Desktop $24.99 · Annual Mobile $199 · Annual Mobile+Desktop $299 (App Store US IAP list). Included for SiriusXM Marine satellite subscribers.
- Rating: 4.2 (5 ratings, App Store US)
- Target: Offshore anglers, incl. existing SiriusXM Marine hardware owners.
- Core: Daily AI Hot Zones + oceanographer recommendations twice weekly; Sea temp, plankton, salinity, currents, thermocline, altimetry, true color, bathymetry; Front Finder: filter conditions to locate ideal areas; Desktop + mobile
- Differentiators: Commercial-fisheries data provider (OceanBytes) + human oceanographer curation; Distribution via SiriusXM Marine chartplotter ecosystem
- Worth borrowing: Human-in-the-loop expert annotations over AI zones; Front Finder filter UI (set thresholds, see matching water); Thermocline layer
- SkipperCast already has: SST fronts, chlorophyll, currents
- SkipperCast lacks (per repo): Thermocline, salinity, altimetry, plankton; Threshold 'Front Finder' filter; Expert-curated recommendations

### 6. FishTrack (Surfline/Wavetrak)
- website: https://fishtrack.com/
- app_store: https://apps.apple.com/us/app/fishtrack-charts-forecasts/id952022603
- google_play: https://play.google.com/store/apps/details?id=com.fishtrack.android
- x: https://x.com/FishTrack
- Pricing: Premium $14.99/mo or $95.99/yr (App Store US); web $79.99/yr option listed.
- Rating: 4.6 (6,278 ratings, App Store US)
- Target: Mass-market offshore anglers.
- Core: Cloud-free and latest SST, chlorophyll, true colour; Overlays: currents, bathymetry, SSH; Tides, moon, 7-day marine forecast, hot spots, routes, offline charts
- Differentiators: Scale + Surfline forecast stack
- Worth borrowing: Clean overlay toggling on top of imagery
- SkipperCast already has: SST, chlorophyll, currents, contours for its one region
- SkipperCast lacks (per repo): Native apps, broad coverage, true-colour imagery, SSH

### 7. Rigline Offshore
- website: https://riglineoffshore.com/
- analytics: https://riglineoffshore.com/features/fishing-analytics
- app_store: https://apps.apple.com/us/app/rigline-offshore/id6756441138
- reddit_feedback: https://www.reddit.com/r/offshorefishing/comments/1rdu7qc/has_anyone_tested_rigline_offshore_curious_if_it/
- Pricing: Free (no IAP on App Store US as of today).
- Rating: 5.0 (13 ratings, App Store US)
- Target: Offshore + inshore anglers in 25 offshore regions (Atlantic, Gulf, Pacific, Hawaii, Baja) and 8 estuaries.
- Core: Up to 30 ranked hotspots per region, each with its top-3 drivers (e.g. convergence+shear, shelf-break proximity, SST front strength), trend and run streak; Species modes: mahi, wahoo, tunas, marlin, sailfish, daytime swordfish; 48h weedline outlook; Gulf Stream current band; Inshore hotspots on a 100 m grid; 7-day bite forecast with hourly feeding windows; Deep Analytics weighs SST fronts, chlorophyll, currents, SLA, bathymetry, salinity, upwelling, MLD
- Differentiators: 'Analytics that show their work': each score decomposed into drivers; Free while competitors charge $100–$500/yr
- Worth borrowing: Driver breakdown chips on every score; Weedline/sargassum drift outlook; Species mode toggle that re-ranks the map
- SkipperCast already has: Ranked places with up to 3 dated reasons (Where to look)
- SkipperCast lacks (per repo): Per-score driver weights and trend/streak; Pelagic species modes; Weedline drift outlook; Hourly bite windows

### 8. PredictWind
- website: https://forecast.predictwind.com/en/features-packages-and-pricing/
- app_store: https://apps.apple.com/us/app/predictwind-marine-forecasts/id477048487
- x: https://x.com/PredictWind
- help: https://help.predictwind.com/en/articles/8563285-predictwind-subscriptions-differences-between-standard-and-professional
- Pricing: Basic $29/yr · Standard $249/yr · Professional $499/yr (App Store US IAP list).
- Rating: 4.8 (32,918 ratings, App Store US)
- Target: Cruisers, racers, passage makers.
- Core: Multi-model wind/wave forecasts, weather routing, departure planning; SST maps, high-res tidal currents; Professional: boat-motion data (roll, vertical acceleration, slamming), AI polars, GRIBs
- Differentiators: Boat-motion forecast (slamming incidence)
- Worth borrowing: Departure planner comparing several start days; Motion/slam metric for sea conditions
- SkipperCast already has: Model comparison (NOAA vs ECMWF)
- SkipperCast lacks (per repo): Departure planner across days; Vessel-motion (slam/roll) forecast; Weather routing

### 9. BlueFronts
- app_store: https://apps.apple.com/us/app/bluefronts-offshore-fishing/id6757767815
- google_play: https://play.google.com/store/apps/details?id=com.bluefronts.app
- Pricing: Plus $19.99/mo or $159.99/yr · Pro $29.99/mo or $239.99/yr (App Store US IAP list). Free tier includes one SST dataset + weather.
- Rating: 5.0 (3 ratings, App Store US)
- Target: Saltwater offshore anglers, global coverage with no locked regions.
- Core: SST, chlorophyll, altimetry, currents (particles), wind, waves; BlueFronts Reports: draw a box → on-demand detection of SST fronts, chlorophyll edges, convergence, shear, eddies; SST palette auto-scales to the current view; tap legend to rescale; Offshore wind turbines layer; platforms + Sentinel-1 imagery to verify rig location; wrecks & reefs; NOAA buoys; point weather; range/bearing marks
- Differentiators: User-drawn analysis box; Auto-scaling color ramp to local view; Radar satellite (Sentinel-1) verification of structures
- Worth borrowing: Auto-scale palette to viewport; Draw-a-box analysis report; Current particles animation
- SkipperCast already has: SST fronts and contrast; Currents animation; Buoy/station readings
- SkipperCast lacks (per repo): Viewport auto-scaling SST ramp; Draw-a-box front/edge/eddy report; Chlorophyll-edge and shear detection; Platform/wreck layers

### 10. Windy.com
- website: https://www.windy.com/
- app_store: https://apps.apple.com/us/app/windy-com-weather-radar/id1161387262
- google_play: https://play.google.com/store/apps/details?id=com.windyty.android
- Pricing: Premium $24.99–$29.99/yr (App Store US IAP list).
- Rating: 4.8 (80,670 ratings, App Store US)
- Target: Everyone incl. sailors, surfers, pilots.
- Core: 50+ animated layers, multiple models, particles; Premium: 1-hour steps, longer forecasts, alerts, route planner
- Differentiators: Visual benchmark for animated particle layers
- Worth borrowing: Particle wind/current animation and model switcher
- SkipperCast already has: Animated currents
- SkipperCast lacks (per repo): Particle wind/swell animation; Model switcher on the map

### 11. SeaLegs AI + DeepCast
- website: https://www.sealegs.ai/deepcast/
- app_store: https://apps.apple.com/us/app/sealegs-ai-marine-forecasts/id6739193930
- Pricing: Plus $5.99/mo or $49.99/yr · Pro $9.99/mo or $79.99/yr · DeepCast report $4.99 single; 10-pack $39.99 (sealegs.ai). Ocean map free, no account.
- Rating: 4.8 (71 ratings, App Store US)
- Target: Boaters, sailors and offshore anglers; US East/Gulf/West, Caribbean, Central America, Mediterranean.
- Core: AI marine forecast from ECMWF+GFS+ICON in plain English for a route/departure; DeepCast AI fishing report: inshore/midshore/offshore zones, annotated SST/CHL maps, GPS spots, tactics, downloadable PDF; Free interactive map: SST, chlorophyll, eddies, currents, thermal fronts, thermocline, depth contours; GPS tracking
- Differentiators: Pay-per-report pricing ($4.99) vs $90 legacy reports; Free map as funnel
- Worth borrowing: Plain-English multi-model briefing; Offline PDF report export
- SkipperCast already has: Plain-language day verdict; NOAA vs ECMWF disagreement in words; Text Advisor built (dark)
- SkipperCast lacks (per repo): Live AI report for any port/date with PDF export; Three-model blend incl. ICON

### 12. RipCharts
- website: https://www.ripcharts.com/register.aspx
- app_store: https://apps.apple.com/us/app/ripcharts/id993060891
- google_play: https://play.google.com/store/apps/details?id=com.ripcharts.android
- Pricing: Per region: $169.99/yr in-app (App Store US); US/Baja package $229.99. Web Standard ~$99/yr per search summary (not confirmed).
- Rating: 4.8 (492 ratings, App Store US)
- Target: Offshore anglers by region (US, Baja, AU, NZ).
- Core: SST, chlorophyll, altimetry; customizable SST range; Premium: app, offline maps, sub-surface SST, 5-day SST forecast
- Differentiators: 5-day SST forecast; sub-surface SST
- Worth borrowing: Live range slider on SST palette
- SkipperCast already has: SST, chlorophyll
- SkipperCast lacks (per repo): User range slider on SST palette; 5-day SST forecast; Sub-surface SST

### 13. SatFish (Bloodydecks)
- website: https://www.satfish.com/
- v2: https://www.satfish.com/offshore-fishing-maps-faster-more-powerful-satfish-v2/
- app_store: https://apps.apple.com/us/app/satfish-fishing-app/id1499577732
- Pricing: $129/yr, all regions, 30-day free trial (satfish.com).
- Rating: 4.6 (374 ratings, App Store US)
- Target: Offshore anglers.
- Core: High-res + cloud-free SST, chlorophyll, true colour, bathymetry, currents, buoys, 5-day wind; v2.0: adjustable SST/chl ranges, history playback, shared waypoints, offline caching
- Differentiators: Low price for all regions
- Worth borrowing: History playback
- SkipperCast already has: SST, chlorophyll, currents, buoys, offline
- SkipperCast lacks (per repo): History playback; Adjustable SST/chl ranges; Shared waypoints

### 14. Fishdope (Bloodydecks)
- website: https://www.fishdope.com/
- app_store: https://apps.apple.com/us/app/fishdope-fishing-app/id760423612
- Pricing: $199/yr (fishdope.com FAQ).
- Rating: 4.7 (571 ratings, App Store US)
- Target: Southern California offshore anglers.
- Core: Daily reports, hot-bite locations, spotter-plane reports; SST, cloud-free SST, daily chlorophyll
- Differentiators: Spotter-plane intel
- Worth borrowing: Human intel pins on the chart
- SkipperCast already has: Reports view with dated catch cards
- SkipperCast lacks (per repo): Daily written SoCal reports, spotter-plane intel

### 15. GulfWire (Gulfwire LLC)
- website: https://gulfwire.net/
- pro: https://gulfwire.net/pro
- about: https://gulfwire.net/about/
- support: https://gulfwire.net/support
- app_store: https://apps.apple.com/us/app/gulfwire/id6806878832
- Pricing: Pro $19.99/mo or $149.99/yr (App Store US IAP list and gulfwire.net/support). Base app free.
- Rating: No ratings yet (App Store US)
- Target: Gulf of Mexico (plus East Coast, Bahamas) offshore/billfish crews and tournament boats.
- Core: Community offshore fishing reports with photos/comments; species filters (blue/white marlin, sailfish, swordfish); Boat profiles, season catch totals, yearly billfish standings; Pro: SST, HD chlorophyll, salinity, sargassum, altimetry, currents; Track My Boat (private, foreground-only); verified drillship positions; Route & fuel planner: waypoints → distance, time, fuel burn, remaining fuel
- Differentiators: Social/tournament layer (standings, boat profiles) on top of ocean data; Sargassum layer + drillship positions for Gulf rigs; Very explicit 'observational, not forecast' labelling
- Worth borrowing: Route + fuel estimate from user's speed/burn; Sargassum layer; Boat leaderboards for community stickiness
- SkipperCast already has: Ocean layers (SST, chlorophyll, currents); Run time and turn-back time
- SkipperCast lacks (per repo): Fuel burn/remaining estimate; Sargassum layer; Public community report feed and boat standings

### 16. BigBlue (GeoPelagic)
- website: https://www.geopelagic.com/
- pricing: https://www.geopelagic.com/pricing.html
- app_store: https://apps.apple.com/us/app/bigblue-offshore-fishing/id6446953932
- google_play: https://play.google.com/store/apps/details?id=com.geopelagic.bigblue
- Pricing: Sport/Commercial/Fleet plans with 3/6/20 device licences (prices not captured); App Store IAPs listed at $9.99–$14.99 (periods not shown).
- Rating: not captured
- Target: Commercial and tournament crews.
- Core: Hourly GOES SST; MODIS/VIIRS/PACE colour + chlorophyll; currents, wind, waves, SLA, bathymetry; HUD speed/distance, great-circle lines, auto offline maps; Desktop app with AIS/NMEA instrument connectivity
- Differentiators: PACE hyperspectral chlorophyll; wheelhouse desktop with NMEA
- Worth borrowing: Hourly geostationary SST frames; NMEA/AIS feed into the map
- SkipperCast already has: Chart + terrain, AIS layer (dated commercial)
- SkipperCast lacks (per repo): Hourly geostationary SST; NMEA/live AIS instrument input

### 17. BoatNGo (+ FishNGo)
- website: https://boatngo.app/how-it-works
- app_store: https://apps.apple.com/us/app/boatngo-marine-weather/id6759305866
- google_play: https://play.google.com/store/apps/details?id=com.boatngo.app
- Pricing: Pro $59.99/yr (App Store US IAP list). Free tier: today's score with usage limits.
- Rating: 5.0 (8 ratings, App Store US)
- Target: Recreational boaters, inland lakes to offshore.
- Core: Score from wind, waves, wave period adjusted for boat type + length → GO/CAUTION/NO-GO; 7-day outlook comparing 8-hour departure windows; flags rough hours an average hides; Forecast tabs: overview, radar, wind, waves, tide; Vector Nav map; FishNGo: explore, species, setup, my trip
- Differentiators: Departure-window comparison that exposes hidden rough hours
- Worth borrowing: 'Worst hour in window' callout next to an average score
- SkipperCast already has: Boat-scaled conditions score + verdict; 7-day hourly view
- SkipperCast lacks (per repo): Side-by-side departure-window comparison (the brief already names the worst hour)

### 18. Buoyweather (Surfline/Wavetrak)
- website: https://www.buoyweather.com/
- app_store: https://apps.apple.com/us/app/buoyweather-marine-forecasts/id686664992
- Pricing: Premium $14.99/mo or $79.99–$95.99/yr (App Store US IAP list).
- Rating: 4.7 (1,252 ratings, App Store US)
- Target: Offshore boaters.
- Core: Pick-a-point wind/wave forecasts, 16-day premium; Live cams, route forecasting, ocean-current maps
- Differentiators: Pick-any-point offshore forecast
- Worth borrowing: Route forecast (conditions along a line)
- SkipperCast already has: Run time by water route; port conditions
- SkipperCast lacks (per repo): Forecast along a route line; Live cams

### 19. Surfline
- website: https://www.surfline.com/
- app_store: https://apps.apple.com/us/app/surfline-wave-surf-reports/id393782096
- google_play: https://play.google.com/store/apps/details?id=com.surfline.android
- x: https://x.com/surfline
- Pricing: Premium $15.99/mo or $119.99/yr; with ads $69.99/yr (App Store US).
- Rating: 4.7 (30,721 ratings, App Store US)
- Target: Surfers.
- Core: Live cams + rewind; 16-day spot forecasts, swell spectra, wave energy, expert summaries
- Differentiators: Cams + forecaster commentary
- Worth borrowing: Swell spectra visual; Human forecaster summary line
- SkipperCast already has: Swell layer with period isolines
- SkipperCast lacks (per repo): Swell spectrum view; forecaster summaries

### 20. Navionics Boating (Garmin)
- app_store: https://apps.apple.com/us/app/navionics-boating/id744920098
- google_play: https://play.google.com/store/apps/details?id=it.navionics.singleAppMarineLakesHD
- Pricing: US & Canada $49.99/yr (App Store US IAP list); other regions $49.99–$69.99.
- Rating: 2.9 (2,361 ratings, App Store US)
- Target: All boaters.
- Core: Nautical charts, 1-ft HD contours, relief shading, routes, tracks, chartplotter sync
- Differentiators: Chart data + Garmin ecosystem
- Worth borrowing: Relief shading + dense contours for base map
- SkipperCast already has: ENC chart, relief, 30 ft contours
- SkipperCast lacks (per repo): Navigation-grade routing and chartplotter sync

### 21. Cobia
- website: https://cobia.app/
- app_store: https://apps.apple.com/us/app/cobia-ai-fishing-guide-log/id6761017204
- google_play: https://play.google.com/store/apps/details?id=app.cobia.android
- Pricing: Free (Cups have prize pools).
- Rating: 5.0 (14 ratings, App Store US)
- Target: Inshore, freshwater and offshore anglers; Florida first.
- Core: Strike Zones: scores every pocket of water vs tide, wind, bottom; heat moves with the tide; Daily briefing score /100 with reasons; AI guide chat that knows your tackle box; Offshore hotspots (SE Florida/Bahamas) at temp breaks/colour edges; Verified-catch feed, Slams, Duels, Cups, Fishdex (600+ species), leaderboards; Spot privacy: irreversible pin fuzzing
- Differentiators: Gamification + verified in-camera catches; Irreversible location obfuscation for shared catches
- Worth borrowing: Animated score heatmap that moves with tide; Privacy-preserving pin fuzzing
- SkipperCast already has: Catch log; rules; Reports view
- SkipperCast lacks (per repo): Gamified verified catches and leaderboards; Tide-animated suitability heatmap; AI chat live to users (SkipperCast's advisor is dark)

### 22. SkeeterCast
- website: https://skeetercast.com/
- app_store: https://apps.apple.com/us/app/skeetercast/id6766407078
- google_play: https://play.google.com/store/apps/details?id=com.skeetercast.app
- Pricing: Free; premium unlocks 'V3.2' high-res model (price not shown on pages read).
- Rating: 5.0 (12 ratings, App Store US)
- Target: Atlantic + Gulf coastal anglers, Maine to Texas (18 states).
- Core: ML city forecasts for 25,000+ zips; NEXRAD HD radar (160 stations); nowcasts; SST, chlorophyll, currents, SSH anomaly, wave forecasts; Captain Steve AI: species scoring, strike times, chat, voice forecasts; 2,308 reefs with bathymetry; USACE channel surveys; inlet conditions; Buddies, group chat, GPS track sharing, AES-256 encrypted private spots
- Differentiators: Own ML weather model; voice forecasts; Inshore bathymetry from USACE surveys
- Worth borrowing: Voice briefings; Inlet-condition cards
- SkipperCast already has: Bar-crossing window at Morro Bay; buoy and station readings
- SkipperCast lacks (per repo): NEXRAD radar layer; Voice briefings; Live AI chat

### 23. SeaStatus: Launch Conditions
- app_store: https://apps.apple.com/us/app/seastatus-launch-conditions/id6811217650
- listing_mirror: https://www.appbrain.com/appstore/seastatus-launch-conditions/ios-6811217650
- Pricing: Pro $3.99/mo or $39.99/yr (App Store US IAP list).
- Rating: 5.0 (4 ratings, App Store US)
- Target: Trailer boaters launching from a specific ramp (skiffs, bay boats, pontoons).
- Core: Status per waterway the ramp reaches (river, ICW, nearshore) from NDBC buoys + CO-OPS tides; Best launch window today; NWS marine warnings; Pro: 7-day outlook, Route Check, Trip mode (keeps re-checking and flags deterioration), live cameras
- Differentiators: Ramp as the unit of planning; Trip-mode monitoring while underway
- Worth borrowing: Underway deterioration alerts; Per-waterway status instead of one regional number
- SkipperCast already has: Saved-trip alerts that fire when the assessment changes
- SkipperCast lacks (per repo): Underway 'trip mode' re-checking while on the water; Live camera feeds

### 24. Savvy Navvy
- website: https://www.savvy-navvy.com/pricing
- app_store: https://apps.apple.com/us/app/savvy-navvy-boat-navigation/id1479182650
- Pricing: Premium $99/yr; US charts $129/yr; Premium Plus global $169/yr (App Store US IAP list).
- Rating: 4.7 (8,483 ratings, App Store US)
- Target: Leisure boaters/sailors.
- Core: Simplified charts, auto routing with tide/weather, AIS, tidal stream atlas
- Differentiators: Consumer-grade simplicity
- Worth borrowing: Simplified clean base style
- SkipperCast already has: Phone-first layout
- SkipperCast lacks (per repo): Auto-routing with tide/weather

### 25. Orca
- website: https://getorca.com/
- help_pricing: https://help.getorca.com/en/articles/6541858-subscription-prices-and-functionality
- app_store: https://apps.apple.com/us/app/orca-boat-gps-charts-routes/id1514423198
- Pricing: Orca Plus $44.99; Smart Navigation $89.99–$159.99 (App Store US IAP list).
- Rating: 4.6 (418 ratings, App Store US)
- Target: Sailors/cruisers.
- Core: Vector charts, sail/engine routing, animated weather, instruments, autopilot control
- Differentiators: Modern vector chart rendering
- Worth borrowing: Vector chart typography
- SkipperCast already has: Vector basemap (Protomaps)
- SkipperCast lacks (per repo): Routing, instruments

### 26. Hilton's Realtime-Navigator (RT-Nav)
- website: https://realtime-navigator.com/
- app_store: https://apps.apple.com/us/app/rt-nav/id586307815
- Pricing: 1 week $49.99 · 1 month $99.99 · 1 year $199.99 (App Store US IAP list).
- Rating: 3.0 (8 ratings, App Store US)
- Target: Offshore/tournament captains.
- Core: SST, chlorophyll, true colour, surface currents, altimetry, salinity imagery; Offline navigation over imagery with GPS, waypoints, routes
- Differentiators: Weekly tournament pricing
- Worth borrowing: Short-term (weekly) pass pricing
- SkipperCast already has: Offline trip pack
- SkipperCast lacks (per repo): Offline navigation over imagery; weekly pass pricing

### 27. Wavve Boating
- website: https://www.wavveboating.com/features/
- app_store: https://apps.apple.com/us/app/wavve-boating-gps-map-chart/id1241140495
- google_play: https://play.google.com/store/apps/details?id=com.wavve.boating.gps
- Pricing: $11.99/mo or $69.99/yr (App Store US).
- Rating: 4.7 (6,683 ratings, App Store US)
- Target: Recreational boaters.
- Core: Charts colored by your boat's draft with live tide depth, auto-routing, community spots
- Differentiators: Draft-personalized depth colouring
- Worth borrowing: Recolour base map by vessel draft + current tide
- SkipperCast already has: Depth contours and relief
- SkipperCast lacks (per repo): Recolouring by vessel draft + live tide

### 28. RipVision AI
- website: https://ripvisionai.com/
- Pricing: not shown
- Rating: n/a (web)
- Target: Offshore anglers in Australia, NZ, Fiji, Western Pacific.
- Core: Daily HSI for Southern Bluefin, Yellowfin, Mahi (0–1); NASA MUR SST 0.02°, MODIS chlorophyll, Copernicus SSH, currents with animated flow lines; Hillshade toggle, 50–2000 m isobaths, GEBCO bathymetry
- Differentiators: Publishes every layer's source, range and palette
- Worth borrowing: Layer spec sheet (source, resolution, range, palette) shown in-app
- SkipperCast already has: Per-layer basis sentence with source and age; Relief + contours
- SkipperCast lacks (per repo): Species habitat suitability maps; Animated flow-line trails length control

### 29. ROFFS
- website: https://roffs.com/product/offshore/
- Pricing: $90 per analysis; bundles e.g. 18 for $1,377 (roffs.com).
- Rating: n/a
- Target: Tournament and charter captains.
- Core: Oceanographer-interpreted analysis charts for a requested area/date
- Differentiators: Human expert interpretation
- Worth borrowing: Expert-annotated chart as a premium add-on
- SkipperCast already has: Where to look reasons
- SkipperCast lacks (per repo): Expert-annotated analysis chart product

### 30. Fishbrain
- website: https://fishbrain.com/pro
- app_store: https://apps.apple.com/us/app/fishbrain-fishing-app/id477967747
- google_play: https://play.google.com/store/apps/details?id=com.fishbrain.app
- Pricing: Pro $79.99/yr, $41.99/qtr, $12.99–$14.99/mo (App Store US IAP list).
- Rating: 4.7 (77,363 ratings, App Store US)
- Target: Mass-market anglers (mostly freshwater/inshore).
- Core: Catch social feed, exact catch locations (Pro), Garmin HD depth maps, BiteTime, spot prediction, regulations
- Differentiators: Huge catch dataset
- Worth borrowing: Catch heatmap layer
- SkipperCast already has: Private catch log
- SkipperCast lacks (per repo): Catch-location heatmap, social feed

### 31. Fishing Points
- website: https://fishingpoints.app/premium/
- app_store: https://apps.apple.com/us/app/fishing-points-map-forecast/id1203032512
- Pricing: Premium $9.99/mo or $49.99/yr (App Store US IAP list).
- Rating: 4.7 (31,077 ratings, App Store US)
- Target: Anglers worldwide.
- Core: Fish activity, tide, wave, weather, solunar forecasts up to 3 months; nautical charts; radar; river flow
- Differentiators: Long-range solunar/tide planning
- Worth borrowing: Long-horizon tide calendar
- SkipperCast already has: Tide curve and events, moon phase
- SkipperCast lacks (per repo): Months-ahead tide/solunar calendar

### 32. Aqua Map
- website: https://www.aquamap.app/support/faq
- app_store: https://apps.apple.com/us/app/aqua-map-boating/id919552329
- Pricing: Master $24.99/yr + charts (US & Canada $14.99/yr) (App Store US IAP list).
- Rating: 4.7 (13,895 ratings, App Store US)
- Target: ICW cruisers.
- Core: Charts, USACE survey overlays updated weekly, crowd notes
- Differentiators: USACE surveys
- Worth borrowing: Survey-date stamps on depth data
- SkipperCast already has: Relief and depth contours
- SkipperCast lacks (per repo): USACE survey-date overlays

### 33. Go or No? Marine Boat Weather
- app_store: https://apps.apple.com/us/app/go-or-no-marine-boat-weather/id6787124767
- Pricing: Free, no account, no ads.
- Rating: 1.0 (1 rating, App Store US)
- Target: Small-boat, sail and kayak users wanting one answer.
- Core: 1–10 score + GO/CAUTION/NO-GO adapted to vessel type, length, engines, hp; 'Now vs later' line (e.g. 'Light chop now — choppy by mid-afternoon'); Tap verdict to see reasons, numbers, charts; Dark glare-friendly helm design; NOAA tides; Open-Meteo weather
- Differentiators: Free, privacy-first
- Worth borrowing: One-line 'now vs later' trend sentence; Helm-friendly dark mode
- SkipperCast already has: Verdict with the reason; boat profile
- SkipperCast lacks (per repo): One-line 'now vs later' trend sentence

### 34. Pathr Navigation
- app_store: https://apps.apple.com/us/app/pathr-navigation/id6758675708
- Pricing: Premium $14.99/mo or $99.99/yr (App Store US IAP list).
- Rating: 5.0 (5 ratings, App Store US)
- Target: Recreational boaters.
- Core: Routing using draft/limits, NOAA chart features, AIS, weather overlays, seabed overlays for anchoring
- Differentiators: Seabed type for anchoring
- Worth borrowing: Seabed/bottom-type overlay
- SkipperCast already has: Water route over land-water screen (not navigation)
- SkipperCast lacks (per repo): Draft-aware routing; seabed type for anchoring

### 35. DECKEE
- website: https://deckee.com/
- app_store: https://apps.apple.com/us/app/deckee-boating-maps-weather/id1402262696
- google_play: https://play.google.com/store/apps/details?id=com.deckee.app
- Pricing: Free core; optional Supporters Club (price not captured).
- Rating: 3.2 (19 ratings, App Store US)
- Target: Australian boaters/paddlers.
- Core: Marine maps, ramps, weather, official alerts, live GPS sharing, trip logging
- Differentiators: Government partnerships
- Worth borrowing: Official alerts on map
- SkipperCast already has: Rules and protected areas
- SkipperCast lacks (per repo): Official alert overlays on the map

### 36. Salinity
- website: https://salinity.live/
- x: https://x.com/SalinityLive
- Pricing: Free waitlist; nothing charged today.
- Rating: n/a
- Target: Boat owners with NMEA networks (Florida focus).
- Core: Full-screen bottom relief chart (coming); Engine monitoring that learns each engine's normal (built, not shipped); Tides, weather, regs, MOB alarm, emergency plan; public roadmap with honest statuses
- Differentiators: Listen-only boat-network telemetry
- Worth borrowing: Learned-normal anomaly alerts from telemetry; Two base-map colour modes (Structure vs Classic)
- SkipperCast already has: Bottom relief, tides, rules
- SkipperCast lacks (per repo): Engine/NMEA telemetry anomaly alerts

## Not found / caveats
- **@GulfWire on X** — searched: X user lookup. Result: Handle belongs to an unrelated Arabic Gulf news account, not the GulfWire fishing app. No official X account for the app found.
- **Fish or Pass / RideScore on X** — searched: X user lookup @fishorpass, @ridescoreapp, @solitarylabs; keyword search. Result: No accounts found; no X posts mention them. RideScore's Facebook/Instagram ads are confirmed via AppMarketSpy (4 active US ads).
- **Not checked in this pass** — searched: —. Result: Tides Near Me, BassForecast, Anglers Edge, Seapilot, Salt Strong were not verified in this pass (lower relevance to offshore/subsea mapping). Macoui and Marine Metrics turned up on Product Hunt but were not reviewed.

## X signal
- {"post": "https://x.com/meraloji18127/status/2055932827766538286", "note": "Indie Android app scoring any spot from NOAA SST, EMODnet depth, Open-Meteo (800+ species). Small account; signal that solo devs are building 'score any spot' apps."}
- {"post": "https://x.com/SalinityLive/status/2115920674514522553", "note": "Salinity: listen-only boat-network app (engine/battery telemetry)."}
- {"post": "https://x.com/PPCLAND/status/2117360039170359327", "note": "Coverage of SiriusXM Fish Mapping app at $199/yr without a satellite plan."}
- {"post": "https://x.com/chris_dalke/status/2100575549647196259", "note": "Opinion: 'weather/fishing app market has commoditized; value is in producing new, better data' \u2014 supports SkipperCast's raw-telemetry angle."}

## Method
Web search, App Store US listings (iTunes lookup API: ratings, release dates, IAP prices scraped from apps.apple.com), Google Play URL checks, company websites, X full-archive search via public reads, Reddit and Product Hunt results via web search. Prices are as listed on the cited source on 2026-11-19; App Store IAP lists don't always show billing periods. Effort ratings are estimates.

## Build specs

Agent-buildable specs for each recommendation (rea spec.md/plan.md/tasks.md format) are in [the specs folder](../specs/README.md). [specs.json](../specs/specs.json) is the machine-readable index.
