# Dynamic marine habitat context

The dynamic habitat pipeline adds dated water-mass information to the species map. It answers where measured or modeled conditions differ, not where a fish is certain to bite. Weather comfort, lawful access, static seabed evidence, environmental support and actual catch observations remain separate claims.

On September 24, 2026, the current regional bindings switched to NOAA CoastWatch's official THREDDS NetCDF subsets: night-only Geo-Polar Blended SST at 0.05° and near-real-time merged NPP/NOAA-20 VIIRS OCI chlorophyll at 0.0375°. The exact source file, sample time, request URL and response hash are recorded. A Morro Bay test subset of the VIIRS product dated September 22 12:00 UTC contained 114 valid cells in 735 requested cells; the other cells stayed missing. These products replace the failing West Coast ERDDAP delivery routes for current collection, but are different analyses and sensors from MUR and MODIS. Historical measurements and method notes below describe the initial September 22 review, not the current binding.

## Sources and first access review

On September 22, 2026, direct public reads returned NOAA CoastWatch MUR and MODIS metadata and the NOAA WCOFS September 22 03Z catalog, variable attributes and source files. HTTP retrieval time is recorded separately from the source clocks. No account or paid service is required.

| Product | Actual resolution and time | Appropriate claim |
| --- | --- | --- |
| [JPL MUR v4.1 via NOAA CoastWatch](https://coastwatch.pfeg.noaa.gov/erddap/info/jplMURSST41/index.html) | Daily 0.01° foundation SST analysis; latest available during review was September 20 09:00 UTC. Retain analysis error and open-sea mask. | Dated surface thermal structure. L4 analysis contains interpolation; a 1 km grid does not establish 1 km independent observation accuracy. It is not a future forecast. |
| [NASA Aqua MODIS R2022 NRT via NOAA CoastWatch](https://coastwatch.pfeg.noaa.gov/erddap/info/erdMH1chla1day_R2022NRT/index.html) | Daily approximately 0.04167° (~4.6 km) ocean color; latest available during review was September 20 12:00 UTC. Cloud/retrieval gaps are retained. | Surface chlorophyll context. No substitution for bait abundance, clarity throughout the water column, harmful-algal-bloom diagnosis or immediate feeding. |
| [NOAA WCOFS](https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html) | Model surface temperature and east/north current on its published 0.04° regular grid (~4 km), NAD83; [three-hour fields to 72 hours](https://tidesandcurrents.noaa.gov/ofs/ofs_faq.html). | Forecast physical water-mass structure at actual populated valid times. Not reef-scale, bottom/bar current, a moving fish school or a 1 km ocean forecast. SST and radar assimilation prevent treating agreement with those inputs as independent validation. |

The register's rights and attribution travel with each source receipt. MUR metadata allows free use and redistribution with its stated limitations; MODIS links NASA's Earth-science data policy; NOAA model data are public. Availability and source dates above describe that review, not a promise about subsequent runs.

The full first Southern California import retained **57,911 valid native MUR pixels out of 77,616 requested cells**, and **3,738 wet WCOFS cells per frame across 24 forecast frames**. WCOFS's actual valid span was September 22 06:00 through September 25 03:00 UTC. MODIS supplied only **12 valid pixels out of 4,512** there, and zero pixels in the Morro Bay and Cambria–San Simeon subsets. The denominators include land/masked cells; they are not ocean-area percentages. Sparse pigment coverage is displayed as a gap, not repaired with a smooth map or another date.

## Reusable pipeline and publication

`src/skippercast/pipeline/habitat_dynamics.py` exposes `run(region_id, output, previous_root=None, now=None)`. It requires approved regional source bindings, including both temperature and currents for WCOFS. New regions supply a footprint and reviewed bindings, not copied coordinates or species conclusions. Native-grid budgets require splitting overly large coastwide requests into regional packages.

1. Resolve approved sources and exact hosts. Query bounded source metadata and regional subsets through the shared HTTP client; retain response hashes, byte limits, HTTP outcomes and retrieval clocks.
2. Keep MUR at stride 1 using bounded tiles. Preserve MODIS's native pixels and WCOFS's native regular grid. Validate units, timestamps, masks, array lengths and coordinates. MUR accepts open-sea mask 1 only. Operational plausibility checks retain temperatures from −2.5 to 40°C, analysis errors from 0 to 10°C, each current component within ±5 m/s and chlorophyll from 0.001 to 100 mg/m³; these decoder screens are not species habitat ranges. Missing cells remain missing; unexpected units or partial downloads fail the source.
3. Compute a centered temperature-gradient magnitude in °C/km only where all four native neighboring cells exist. No smoothing, missing-pixel bridging or fine-resolution reconstruction is applied. For MUR, report whether a directional contrast exceeds the sum of neighboring published analysis errors. Because error covariance is unavailable, that flag is not a statistical confidence interval.
4. Write content-addressed 0.5° JSON tiles first, followed atomically by a small manifest. The browser fetches only tiles needed for the viewport and selected time. Original grid coordinates survive tiling; tile size is a transport choice, not environmental resolution.
5. Cache successful products, including successfully decoded scenes with no usable pixels, for six hours without changing source clocks. On acquisition failure, retain verified previous tile bytes and mark the source retained. Freshness still expires using actual current time. A failure never becomes an empty successful layer. Operational `issues` identify acquisition/decoding failures and stale source clocks; expected masked-scene gaps stay explicit in `coverage_gaps`, source `missing` status and degraded overall coverage without making every scheduled run fail.

The existing regional refresh workflow calls this collector; it does not require a competing scheduler or browser-to-provider grid downloads. Each region writes `habitat-dynamics.json`, `habitat-health.json` and `habitat-tiles/*.json`. The manifest includes rights, request receipts, method version, per-layer fields, all populated frame times, cell coverage, actual resolution and hashed tile descriptors. Preserve those paths in publication.

The first MUR scenes had many valid native gradients but zero contrasts exceeding the conservative summed-error flag. That does not show that fronts are absent: correlated analysis errors and the short two-pixel baseline can suppress this indicator. Displaying a gradient is permissible as uncertain physical analysis; labeling it a verified fish-bearing front is not.

## Planned-date semantics

`frame_for_time` is the shared reference policy. Forecast selection uses the nearest populated native step within 90 minutes and within the actual forecast span. Missing intermediate steps stay unavailable. Forecast data expire 36 hours after their model cycle. No extrapolation fills days four through seven.

MUR analysis remains usable as dated context for up to 72 hours after its sample time; MODIS for 96 hours. Those operational maximum ages are product choices, not validated fish-response periods. An observation may accompany a future trip as **observed context**, retaining its original timestamp; it does not receive the future date or become a future habitat forecast. Selecting a past date cannot make stale evidence current or display an analysis from after that selected time.

The browser must also apply legal-region/MPA screens before presenting any cell as a suggested search area. Environmental rasters are information overlays, never export-qualified spots by themselves. Jurisdiction, boat range, legal method and safety remain independent. Do not infer tide currents from high/low-water predictions.

## Species support, ratings and uncertainty

`species_support` exposes evidence flags and returns `catch_probability: null` and `habitat_score: null`. There is no trained local catch/effort dataset supporting a numeric pelagic success score. Reporting a transparent component is more reproducible than weighting extra variables until a high score appears.

- **Albacore:** NOAA's [2024 HMS habitat synthesis](https://www.fisheries.noaa.gov/s3/2024-10/Amend8-HMS-FMP-AppendixF-June28-Att-2.pdf) describes juvenile eastern-Pacific association with fronts and reports 99% of tagged SST encounters between 12–21°C. This supports a broad, life-stage-specific reference flag. It does not establish an optimum, local presence, absence outside that range, or an adult/deep-water rule.
- **Yellowfin:** [NOAA's species account](https://www.fisheries.noaa.gov/species/pacific-yellowfin-tuna) supplies a broad 64–88°F habitat preference. Apply it as a species-wide reference with local validation still needed; it is too broad to identify the best Southern California temperature.
- **Bluefin:** [NOAA](https://www.fisheries.noaa.gov/species/pacific-bluefin-tuna) and existing regional profiles support mobile, depth-dependent habitat. No single-temperature optimum is assigned. Surface maps omit prey fields and much of bluefin's vertical habitat.
- **Dorado and yellowtail:** expose dated fronts/current context, source-backed ecology and actual floating-material/bait observations when available. No unvalidated numeric optimum or permanent paddy locations are invented.
- **Rockfish and lingcod:** keep these surface layers contextual. Prioritize native bathymetric relief, depth reference, substrate, survey date/uncertainty and identified local fish. Different rockfish species and life stages need separate ecological evidence; SST cannot stand in for bottom temperature or oxygen.

Temperature fronts are candidate water-mass boundaries; chlorophyll, modeled currents, pressure and wind are not independent votes confirming fish. Weather belongs in trip comfort and ability to fish; atmospheric fields should enter a biological model only when a local relationship has been measured and validated.

## Next evidence improvements

Prioritize source quality and independent verification before adding more feeds: source-resolved reef depth/substrate and uncertainty; paired HFR/current observations with geometry masks; archived forecasts before valid time; independent buoy/SST comparisons; species-identified catches and unsuccessful effort; life-stage-aware public survey observations. Sea-surface height, mixed-layer depth and subsurface temperature/oxygen are promising contextual inputs only after actual local coverage, native vertical levels, license and validation are reviewed. A second API distributing the same satellite product is not independent evidence.

Additional primary sources were inspected, including actual Southern California grid downloads where stated:

| Candidate | Decision from September 22 direct reads |
| --- | --- |
| [NOAA-20 VIIRS daily chlorophyll](https://coastwatch.pfeg.noaa.gov/erddap/info/nesdisVHNnoaa20chlaDaily/index.html) | A populated 0.0375° subset was accessible, but its latest source time was **September 2, 2026**. Rejected as current context. The data request redirects to NOAA CoastWatch's central service; future bindings must review that host explicitly. |
| [Merged VIIRS OCI chlorophyll](https://coastwatch.noaa.gov/erddap/info/noaacwNPPN20VIIRSchlociDaily/index.html) | Successful regional read, but latest source time was **September 2, 2021**. Rejected for current use despite its nominal daily label. |
| [NOAA MBON 8-day Seascapes](https://cwcgom.aoml.noaa.gov/erddap/info/noaa_aoml_seascapes_8day/index.html) | A populated 0.05° classification grid was available, latest **June 26, 2026**. Historical water-mass research only; classification probability is not fish probability. |
| [CalCOFI hydrography and ecosystem observations](https://calcofi.org/data/) | Strong lead for depth-specific temperature, oxygen and life-stage-aware ecological validation. Its [fish-egg/larval samples](https://calcofi.org/data/marine-ecosystem-data/fish-eggs-larvae/) cannot become adult recreational catch locations. This turn reviewed documentation, not an imported local survey or continuous forecast. |
| [NOAA EcoCast methodology](https://www.fisheries.noaa.gov/news/new-tool-helps-fisheries-avoid-protected-species-near-real-time) | Useful model-design precedent using animal tracking, satellites and fishery observers. Its swordfish/bycatch scope cannot be relabeled as a locally validated tuna bite model. No current EcoCast grid was imported. |

The three downloaded but stale grid leads have schema-validated discovery records under `catalog/candidates/`; these are research receipts, not published approvals. This prevents a nominally rich, continuous older dataset from silently replacing a sparse but recent observation.

For a future calibrated model, pre-register target, prediction horizon and spatial scale; collect positive and zero-catch search effort; separate environmental suitability from accessibility and fleet behavior; validate on held-out dates and areas with calibration and uncertainty. Compare against simple seasonal/thermal baselines. Do not promote a model that only reproduces fishing effort or reports apparent precision below its least-resolved input.
