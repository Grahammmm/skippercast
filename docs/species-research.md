# Species, sea state, and search areas

Research review: **September 21, 2026**. Scope: recreational boat fishing off the Central California coast; bottom-habitat candidates within 200 feet, with separately labeled offshore tuna search references. This is a literature-informed search guide, not a fitted catch model.

## What “good conditions” can mean

Three questions need separate answers: does the bottom or water mass fit the species, can the angler present the gear effectively, and will the boat have a comfortable trip? A rocky reef's A/B/C grade answers only the first question for a subset of bottom fish. The web comfort screen addresses an hour of modeled wind and waves. Neither answers whether fish are feeding or whether a complete trip qualifies for the personal monitor's 9/10 recommendation.

No reviewed primary source establishes one transferable combination of temperature, tide, wind, and swell that maximizes recreational catches across these species off Morro Bay. The implementation therefore avoids invented temperature optima, bite percentages, bottom-current speeds, and solunar scores. Its operational suggestions are explicitly field-search guidance, not findings of a local catch-rate experiment.

## Species findings and implementation decisions

| Target | Evidence-based habitat context | Map implementation | Practical condition to seek |
| --- | --- | --- | --- |
| Lingcod | Rocky reefs and kelp are important habitats, although the species also uses other bottom types. | 115 existing reef candidates meet an author-selected preference of ≥3 m local relief and ≥60% rough cover. The A/B/C terrain formula is unchanged. | Enough control to keep a near-bottom presentation over the structure and reset the drift. |
| Rockfish | Different species occupy reefs, kelp, midwater, low-relief bottom, and sediment interfaces. “Rock cod” is not one ecological niche. | All 132 published rocky targets remain available. This does not claim to map every rockfish habitat. | Use sonar at multiple heights; reliable presentation matters more than an unsupported universal tide rule. |
| California halibut | CDFW describes an inner-shelf/estuarine ambush predator, with most angler catches in 10–90 ft. | Nine soft-sediment search windows whose whole surveyed depth range is ≤100 ft; no reef grade. The 100-ft selection cutoff is our planning choice. | Manageable drift and motion for a consistent bottom presentation; verify bait and visibility locally. |
| Chinook salmon | Ocean-foraging, migratory fish; older Chinook feed on other fish. | Three coastal forecast/search circles replace reef pins. They are constructed reference areas, not sightings or historic grounds. | Controllable trolling and an acceptable return, informed by current forage and legal-season reports. |
| Albacore tuna | Temperature and oceanic fronts influence distribution; juveniles migrate widely, with timing affected by ocean conditions. | Nine offshore search sectors and the modeled SST layer. Neither is a detected front or a fish location. | Investigate water-mass changes alongside actual bait/fish evidence; inspect the exposed return window. |
| Pacific bluefin tuna | Highly mobile predators with a broad thermal/geographic range. | The same offshore geographic references as albacore, with different guidance. No unsupported species-specific fixed coordinates. | Fresh fish/forage observations and sea conditions that support the longer trip. |
| Dungeness crab | Soft-sediment habitat is relevant; access and gear restrictions are independent of substrate. | Eighteen soft-bottom windows within the depth ceiling, without a catch rank. | Conditions that permit controlled gear deployment and retrieval; the model does not predict trap movement. |

Primary ecology sources: [CDFW fish life histories](https://wildlife.ca.gov/Conservation/Marine/Life-History-Fish), [CDFW California halibut research](https://wildlife.ca.gov/Conservation/Marine/Nearshore), [NOAA Chinook salmon](https://www.fisheries.noaa.gov/species/chinook-salmon), [NOAA albacore](https://www.fisheries.noaa.gov/species/pacific-albacore-tuna), [NOAA Pacific bluefin](https://www.fisheries.noaa.gov/species/pacific-bluefin-tuna), and [CDFW Dungeness monitoring/habitat](https://marinespecies.wildlife.ca.gov/dungeness-crab/monitoring/).

### Evidence we deliberately did not overextend

- NOAA's [ocean indicators for juvenile salmon](https://www.fisheries.noaa.gov/west-coast/science-data/local-physical-indicators) concern food-web conditions and survival. They are not a local adult-Chinook catch-temperature model. Freshwater spawning or egg-survival temperatures are not used as ocean-fishing targets.
- NOAA's [albacore](https://www.fisheries.noaa.gov/inport/item/80237) and [bluefin essential-fish-habitat definitions](https://www.fisheries.noaa.gov/inport/item/80247) are broad management habitat descriptions. Essential habitat is not a hotspot. The app does not assign a tuna school to a management polygon.
- A [2026 primary study of commercial Dungeness effort](https://journal.wildlife.ca.gov/2026/05/22/identifying-highly-used-dungeness-crab-fleet-fishing-areas-off-central-and-northern-california-to-inform-entanglement-risks-of-large-whales/) modeled fishing behavior from vessel loggers. Commercial effort depends on operational variables as well as environment. Its effort surface is not a recreational crab catch-probability surface, and no coordinates from that study are republished as local crab spots.
- Surface temperature and surface currents cannot establish seabed temperature, bottom drift, or Morro Bay entrance currents. Missing bait, chlorophyll, thermocline, fish observations, and bottom currents remain explicit gaps.
- The historical AIS research has not verified local sportfishing-charter identities or target visits. It adds no species score or hotspot label.

## New soft-bottom geometry

`scripts/build_species_habitat.py` reads the existing research manifest and the original numerical bathymetry and seafloor-character rasters. It uses only the three public USGS releases documented in [the source register](data-sources.md); Cambria derivatives remain excluded. The retained output contains 12 Morro Bay windows and 6 Point Estero windows. No Point Buchon window met the complete selection and validation procedure; the app does not fill that gap with guessed coordinates.

The inspected release metadata defines class 1 as fine-grained, soft, flat sediment; class 2 combines coarse sediment and flat rock; class 3 represents rugged rock. Class 2 is therefore not silently treated as sand. The analysis finds 200-m-radius search windows inside class-1 neighborhoods, spaces centers by at least 1.3 km within each release, and tests every included native-raster pixel using an all-touched polygon mask. It requires complete depth/classification coverage, ≥95% native class 1, native depths 25–195 ft MLLW, and no intersection with the September 16 closure screen buffered by 505 m. Circles are partial windows, not full sediment boundaries. Actual water depths can differ from recorded survey depths because of water level and sediment movement.

The published data record each window's coordinate, surveyed depth range, soft-sediment percentage, source, year, datum, and geometry. Credit USGS, CSUMB Seafloor Mapping Lab, and University of California Center for Integrated Spatial Research. Their source data retain their public-domain status; SkipperCast's selection is subsequent analysis. A dated spatial screen does not certify current access for each species.

## Sea-state interpretation

NOAA's [wave definitions](https://www.ndbc.noaa.gov/faq/wavecalc.shtml) distinguish significant height, dominant period, and average period. Significant height approximates the average height of the highest third of waves; individual waves can be larger. Height alone cannot describe short chop, crossing swell, boat heading, or entrance behavior.

The app shows combined significant seas and separate available swell/chop components. Arrows point in the travel direction; numeric wave/wind directions state where they come **from**. Current direction is **toward**. The wave sketches encode reported height and period schematically. They do not animate a predicted sequence of actual waves or simulate a Parker's motion. The cycles-per-minute annotation is simply 60 divided by the displayed period.

The [provider's GFS adapter](https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Gfs/GfsWaveVariable.swift) maps the headline period/direction to primary-wave fields, while the [ECMWF adapter](https://github.com/open-meteo/open-meteo/blob/main/Sources/App/Ecmwf/EcmwfVariable.swift) uses mean wave period/direction. The UI labels this difference rather than treating the periods as interchangeable. The ECMWF WAM 0.25 feed does not provide the same component detail as GFS; unavailable components stay blank. Model grids also differ.

The disclosed comfort thresholds are preferences, not biological optima or a validated small-craft safety model: wind ≤8 kt, gusts ≤12 kt, combined seas ≤3 ft, and chop ≤1 ft. Missing critical values, inconsistent gusts/components, material model disagreement, unavailable run metadata, and stale data lower confidence. Alerts and a fog/thunderstorm signal override calm numbers. A “calmer signal” still requires whole-trip and entrance review. The screen does not produce the monitor's 9/10 score.

NOAA [Port San Luis tide predictions](https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9412110) are displayed in feet MLLW and Pacific time. A recent measured water level remains timestamped as an observation when the forecast slider moves into the future. High/low water is not equated with slack current. The [NOAA API](https://api.tidesandcurrents.noaa.gov/api/dev) supplies predictions and observations separately.

## Maps, time, and legal scope

[NOAA's Chart Display Service](https://www.nauticalcharts.noaa.gov/data/gis-data-and-services.html) provides detailed ENC-derived chart images, refreshed by NOAA weekly. Its display service is a planning basemap, not a certified onboard navigation product. Display labels follow the service's configured units; habitat, wave, and tide cards explicitly use feet. Street tiles remain a selectable fallback.

The slider covers the current forecast hour through 168 elapsed hours ahead. Dates ≥72 hours ahead are marked provisional. Each model is requested separately at 13 public reference coordinates so its own returned grid is retained. [Open-Meteo's published coverage and definitions](https://open-meteo.com/en/docs/marine-weather-api) guide the unit and coverage checks. Coarse weather circles are regional samples, not continuous high-resolution fields. Data are cached in the page session for an hour; refresh is available. Unpopulated forecasts are never extended.

Rules reviewed September 21: the [Central Region summary](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central) and [salmon page](https://wildlife.ca.gov/Fishing/Ocean/Regulations/Salmon) schedule local salmon access through September 30 subject to an earlier harvest closure; local Dungeness is closed with a scheduled November 7 reopening. These dated notes do not authorize future fishing. [Whale-risk restrictions](https://wildlife.ca.gov/Conservation/Marine/Whale-Safe-Fisheries), MPAs, species rules, and health closures must be checked for the trip date. Neither the timeline nor species selection recalculates legal permission.

NWS [PZZ645](https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=PZZ645) covers coastal waters out to 10 nautical miles; [PZZ670](https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=PZZ670) covers the adjacent 10–60-nm offshore zone. Both active-alert feeds are checked. The offshore distance/time annotation is only a straight-line lower bound from the harbor entrance at the configured 20 kt planning cruise speed, not a charted route or a predicted arrival time. Harbor travel, detours, search time, fuel planning, and a slower return are additional.
