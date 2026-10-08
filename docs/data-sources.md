# Data sources and processing

Source and licensing review: **September 20, 2026**. Source dates below describe historical surveys or releases, not the age of the fishery or current conditions. [NOTICE](../NOTICE.md) records attribution; [LICENSE](../LICENSE) applies to original SkipperCast material, not to underlying public-domain facts or separately licensed datasets.

## What the public atlas contains

The [Avila–Point Estero edition](../atlas/avila-point-estero-2026-09-20/) is a subset of earlier personal Avila–Cambria research. It preserves the retained target positions and includes only targets whose terrain inputs come from the three USGS releases below.

| Terrain source | Habitat targets | Partial reef outlines | Drift alignments |
| --- | ---: | ---: | ---: |
| Point Buchon / Avila | 40 | 35 | 10 |
| Morro Bay | 47 | 42 | 9 |
| Point Estero / Cayucos | 45 | 30 | 12 |
| **Published total** | **132** | **107** | **31** |

These are **habitat candidates**, not verified fishing spots. Scores compare mapped relief, rough-rock coverage, detrended terrain complexity, and nearby usable habitat. A large mapped patch does not establish large boulders, fish presence, or catch success. Reef outlines are partial processed footprints, not complete reef boundaries. Drift lines describe a possible alignment over structure; actual wind and current determine whether a boat can follow it. They are not passage routes.

The retained surveys were collected in **2008**. The reviewed original raster metadata does **not establish the output vertical datum** for these three releases. Earlier MLLW and 200-foot qualification claims were withdrawn on September 27, 2026. Nominal raster values are historical research context, not chart-depth screening. Source resolution, survey age, classification error, and the later processing all limit precision. The original datasets explicitly are not intended for navigation.

## USGS terrain data

Each inspected bathymetry, seafloor-character, and CMECS metadata file below identifies the USGS-produced data as U.S. public-domain information and requests source credit and proper metadata. The project license does not restrict those underlying data. The three survey releases combine USGS work with CSUMB and other collaborators; this finding is based on the **specific release metadata**, not an assumption that every government-hosted file is public domain.

Credit **U.S. Geological Survey**, **California State University Monterey Bay Seafloor Mapping Lab**, and the **University of California Center for Integrated Spatial Research** for the bathymetry and seafloor-character inputs. CMECS metadata additionally identifies USGS as the dataset originator. SkipperCast's target selection, scores, habitat clipping/simplification, and proposed alignments are subsequent processing and do not imply endorsement.

| Release | Citation | Published version |
| --- | --- | --- |
| [Point Buchon](https://doi.org/10.5066/P9KBGELE) | Cochrane, G.R., Cole, A., and Sherrier, M., 2022, *Bathymetry, backscatter intensity, and benthic habitat offshore of Point Buchon, California*. U.S. Geological Survey data release. | 1.1, January 2024 |
| [Morro Bay](https://doi.org/10.5066/P9HEZNRO) | Cochrane, G.R., Cole, A., Sherrier, M., and Roca-Lezra, A., 2022, *Bathymetry, backscatter intensity, and benthic habitat offshore of Morro Bay, California*. U.S. Geological Survey data release. | 1.1, January 2024 |
| [Point Estero](https://doi.org/10.5066/P9ZSTUK1) | Cochrane, G.R., Cole, A., Sherrier, M., and Hallahan, S., 2022, *Bathymetry, backscatter intensity, and benthic habitat offshore of Point Estero, California*. U.S. Geological Survey data release. | 1.1, November 2023 |

Exact official metadata:

| Area | Bathymetry | Seafloor character | CMECS habitat/geology |
| --- | --- | --- | --- |
| Point Buchon | [XML](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9KBGELE/134dbdd47ee649b1863acc6cfa6ed0e6/Bathymetry_OffshorePointBuchon_metadata.xml) | [XML](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9KBGELE/ac4288bd38594e1fa6e89e139995ab73/SeafloorCharacter_OffshorePointBuchon_metadata.xml) | [XML](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9KBGELE/3bb89ac0e56a4c55a51e8faf88d5b6e1/CMECS_OffshorePointBuchon_metadata.xml) |
| Morro Bay | [XML](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9HEZNRO/137e935afcd24506b6c8a2d23ff7a6d4/Bathymetry_OffshoreMorroBay_metadata.xml) | [XML](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9HEZNRO/99111880d0194352899672cd4d7690ac/SeafloorCharacter_OffshoreMorroBay_metadata.xml) | [XML](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9HEZNRO/0eac5e868c4b477ab371eb96536ba6b7/CMECS_OffshoreMorroBay_metadata.xml) |
| Point Estero | [XML](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9ZSTUK1/cfefab299c38493c87398393e6a5597a/Bathymetry_OffshorePointEstero_metadata.xml) | [XML](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9ZSTUK1/0f75d175cc2046f38c45b6ac26a9be92/SeafloorCharacter_OffshorePointEstero_metadata.xml) | [XML](https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9ZSTUK1/88171328f12a4876b6158d71ff8a4ad1/CMECS_OffshorePointEstero_metadata.xml) |

The [USGS copyright policy](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits) also explains the exceptions for third-party content and protected agency identifiers. No agency logos or source-site screenshots are needed to use this atlas.

## Protected areas and legal screening

**California Marine Protected Areas [ds582]**, California Department of Fish and Wildlife, Marine Region GIS Lab, is licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). See the [official metadata](https://filelib.wildlife.ca.gov/public/BDB/GIS/BIOS/metadata/DS0582.html) and [BIOS citation guidance](https://wildlife.ca.gov/Data/BIOS/Citing-BIOS).

The regional MPA geometry was checked September 20, 2026. SkipperCast selected regional features, projected them for distance calculations, and used buffered closures to screen targets and complete drift/area geometries. The planning margin is not a legal boundary. The underlying CC BY rights remain intact. Current regulations, seasonal restrictions, species rules, and the vessel's full drift still need separate review before a trip.

The Diablo Canyon security restriction is a separate legal source: [33 CFR 165.1155](https://www.ecfr.gov/current/title-33/part-165/section-165.1155). A dataset download date or an atlas label does not certify that a location remains lawful to fish.

## Material excluded from this edition

| Source | Why it is excluded | Effect on public output |
| --- | --- | --- |
| [CSUMB Block05, Cambria](https://www.ngdc.noaa.gov/ships/ventresca/SCC_Block05_mb.html) | The actual bathymetric grid metadata leaves access and use constraints to the California Coastal Conservancy and CSUMB Seafloor Mapping Lab. No general redistribution grant was established in this review. NOAA hosting alone does not settle third-party rights. | 11 targets, 10 outlines, and 2 alignments from the earlier private atlas are omitted, along with direct derivative imagery. The public atlas does not claim full Avila–Cambria coverage. |
| [Ecotrust/CDFW DS1091 charter grounds](https://filelib.wildlife.ca.gov/public/BDB/GIS/BIOS/metadata/DS1091.html) | Official metadata and the [ArcGIS item](https://www.arcgis.com/home/item.html?id=805ef4f796334d6fba4138ca8a275924) direct users to contact Ecotrust about use. Public access did not establish redistribution permission. | No raster tiles, sampled values, per-target overlap/value classifications, historical-ground labels, or maps displaying that layer are published here. Terrain scores do not depend on it. |

The Cambria constraints were inspected in the bathymetric-grid metadata included in the [original additional-products archive](https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/SCC_Block05/multibeam/data/version2/products/SCC_Block05_additional_products.tar.gz). DS1091 describes 2011 fishing grounds from 2012 captain interviews; it would not establish present charter use or catch success even if redistribution permission were obtained.

The original personal atlas remains a separate edition. Permission uncertainty is not a finding that the sources are unusable under every circumstance; it limits what this repository distributes now.

## Published charter trip reports

The [charter-ground register](charter-grounds.md) documents three named grounds from 45 single-ground trips in a 601-trip, 173-day public-report sample (April 1–September 20, 2026). Sources are landing-reported facts on SoCalFishReports, with the provider relationship linked from operator pages. The public JSON includes concise date/boat/ground/species facts and source references, not copied articles, media or raw pages. No permission to republish the publisher's expressive material is claimed.

Search outlines are new editorial geographic interpretations clipped to the reviewed USGS depth grids and dated closures; they are not the publisher's fishing boundaries or exact charter stops. Underlying public-domain and CDFW data retain their existing terms and attribution. These outlines are separate from the withheld DS1091 layer. The layer does not add an AIS bonus or change any terrain grade.

## AIS evidence

The [NOAA MarineCadastre AIS archive](https://hub.marinecadastre.gov/pages/vesseltraffic) is a free public research source, but it is **not plain CC0**. Its [official repository](https://github.com/ocm-marinecadastre/ais-vessel-traffic) and the inspected 2024 broadcast-point and vessel-track readmes say [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/); NOAA's [MarineCadastre AIS FAQ](https://coast.noaa.gov/data/marinecadastre/ais/faq.pdf) (June 2026 edition, reviewed October 4, 2026) adds the U.S. Coast Guard's conditions for the underlying NAIS "Level C (Historical Data)":

- "These data are intended for coastal and ocean planning purposes only." This is the FAQ's answer to "Can I use these data for regulatory or enforcement purposes?"; its answer to whether the data can be used for a commercial product is the Navigation Center passage below. SkipperCast takes the conservative reading of both.
- "Yes, you may release derived products built from these data. Please cite your data source to promote transparency." The FAQ's citation form is "NOAA Office for Coastal Management. ([Year]). [Title of Dataset]. Marine Cadastre. https://marinecadastre.gov."
- Quoting the USCG Navigation Center: "The historical data are generally considered public domain. All provided data may not be used for purposes other than those intended for the disclosure." It continues: "Foreign governments, Federal, State, local and tribal government agencies, and non-governmental entities shall not retransmit or redistribute AIS information (real-time or stored) in any form other than those intended for the disclosure as approved, and shall not charge a fee for its usage."
- Work consisting predominantly of U.S. government material must carry the 17 U.S.C. § 403 notice identifying that material and stating it is not subject to U.S. copyright.

SkipperCast therefore uses MarineCadastre AIS for research, verification and internal backfill only, cites it as above, and keeps it and anything derived from it off any paid surface ([charter fleet plan](plans/charter-fleet/README.md), decision D9). How these conditions apply to a paid SkipperCast is **owner/counsel to confirm**; the [data-rights register](legal/data-rights-register.md#charter-fleet-registry-and-ais) records the review. Credit NOAA Office for Coastal Management and acknowledge the U.S. Coast Guard Navigation Center; consult each downloaded product's metadata rather than assuming all archives have identical terms.

The expanded September 20 audit screened eight complete 2026 UTC-day broadcast files: April 18, May 16, June 13, June 20, and June 27–30. It processed 78,069,787 nationwide records and retained 28,664 regional records with 51 distinct MMSI identifiers. June 27–30 is a continuous four-UTC-day block; the other dates are isolated samples. The geographic inventory covers Avila–Cambria, while the public habitat layer ends at Point Estero. Complete file processing does not establish complete reception, vessel identity, or fleet coverage.

Exact normalized-name screening found zero matches to the researched local fleet. No local sportfishing charter identity has been verified, so **no target is labeled an AIS-confirmed charter hotspot**. Missing or changed names and reception gaps can hide trips. Eight dates are not a season census, and absent matches do not establish absent charter activity. A vessel position, speed, or AIS fishing category alone does not prove fishing effort or catch success.

The [public AIS research summary](../dist/data/ais-evidence.json) includes the sample dates, original daily archive URLs, retrieval times, aggregate counts, integrity hashes, screened names, and limitations. At retrieval, the [checked 2026 daily index](https://noaaocm.blob.core.windows.net/ais/csv2/csv2026/index.html) listed broadcasts through June 30. Later file modification dates do not extend that broadcast coverage; other NOAA products may have different availability. Raw nationwide archives and regional vessel trajectories are not bundled in this release.

Operator descriptions for Angler, Papagallo II, and Bonnie Marietta did not support classifying those name leads as recreational bottom-fishing activity. The linked official operator pages and the identity caveat are in the research summary. Sparse 2018–2024 PMEL inventory samples are useful only as identity leads; at most one retained position per vessel per UTC day cannot reconstruct stops. Geographic extraction from 2024/2025 monthly track files did not complete and contributes no local track evidence.

A proposed repeated-visit screen would first require independent vessel/MMSI and sportfishing-role verification, then full-trip review, reporting-gap checks, suitable legal habitat, and slow bouts of at least 15 minutes on at least three distinct dates with no gap over 10 minutes. This is an unimplemented research heuristic, not proof of fishing or catch. AIS remains a separate evidence layer and contributes no points to the terrain score.

## Forecast and observation services

Wind and wave forecasts now come from SkipperCast's own tiles, built directly from NOAA GFS/GFS-Wave (public domain) and ECMWF IFS/WAM open data ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), credit ECMWF). Both allow commercial use. Method, sampling and known differences: [forecast data](forecast-data.md). The GEFS wind ensemble is read directly from NOAA's GEFS open data on AWS (public domain), and the app's surface currents come from NOAA WCOFS (public domain) through the regional pipeline. SkipperCast no longer calls the Open-Meteo API at runtime; the Open-Meteo notes below are kept for older archived responses and research comparisons.

[Open-Meteo](https://open-meteo.com/en/licence) is the access service for several forecast models; it is not another independent weather model. Comparisons retain **ECMWF IFS versus NOAA GFS** for wind and **ECMWF WAM versus NOAA GFS Wave** for seas. Model initialization, publication/availability, grid coordinates, units, and populated coverage are needed to interpret a response. Retrieval time is not forecast issue time.

Open-Meteo API data use [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): preserve appropriate provider credit, link the license, and identify processing or changes. Its [free API terms](https://open-meteo.com/en/terms) separately restrict access to noncommercial use and set request limits. Open-Meteo's server source is AGPL; calling its API with an independently written client does not by itself license that client under AGPL.

Official [NWS marine forecasts](https://forecast.weather.gov/MapClick.php?TextType=2&zoneid=PZZ645), [NDBC observations](https://www.ndbc.noaa.gov/station_page.php?station=46215), and [NOAA tides](https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=9412110) provide additional evidence. They answer different questions: current buoy observations do not verify a seven-day forecast, and Port San Luis tide predictions are not Morro Bay entrance-current predictions. Consult provider terms and metadata before redistributing particular responses or graphics. Provider pages, charts, full forecast archives, account configurations, and private alert records are not part of this repository's license grant.

Recorded buoy history (`ndbc-history`, candidate pending owner confirmation) comes from NOAA NDBC standard-met annual archives and 45-day realtime files for 46215 and 46028, fetched only from `www.ndbc.noaa.gov` with a SHA-256 recorded per file. NDBC data are U.S. government works (commercial use allowed); credit NOAA National Data Buoy Center, and CDIP/Scripps for 46215, without implied endorsement. The monthly bands and hourly means are SkipperCast aggregations that keep counts and missing coverage. They describe recorded conditions, not a climatology, forecast or catch probability. Method: [recorded buoy history](live-conditions.md#recorded-buoy-history-fe-42).

## Species and detailed marine views

The [species research](species-research.md) records the ecology sources, interpretation limits, dated seasonal review, and new soft-bottom method. The connected sediment regions derive only from the already-reviewed USGS releases; those source rights and credits remain unchanged. No commercial chart tiles, proprietary weather tiles, private catches, or charter trajectories were added.

[NOAA's ENC display service](https://www.nauticalcharts.noaa.gov/data/gis-data-and-services.html) supplies chart images for the visible map at runtime, with attribution. No offline chart cache is bundled; a user's offline trip pack stores that region's chart images at zoom 8–12 on their own device (capped at 1,500 tiles). SkipperCast's own NOAA/ECMWF forecast service supplies the wind and wave models, and NOAA WCOFS the surface currents (nearest three-hour snapshot, first 72 hours). The app has no hourly sea-surface temperature forecast of its own yet; the habitat layers show NOAA WCOFS temperature forecasts and dated satellite analyses. NOAA tide predictions and the separately dated water-level observation come from station 9412110.

## Basemap and shoreline (v2 Chart, FE-10)

The v2 Chart basemap is a self-hosted extract of the [Protomaps basemap](https://docs.protomaps.com/basemaps/downloads), vector tiles built from OpenStreetMap ([ODbL](https://www.openstreetmap.org/copyright)) and Natural Earth. `scripts/basemap/build_basemap.sh` reads only the byte ranges it needs from a dated Protomaps daily planet build: zooms 0–10 over the California coast and zooms 11–14 inside each active and preview region's `bounds` (`scripts/basemap/regions.py`). The merged archive `tiles/basemap/ca-coast-<build>.pmtiles` and its manifest (size, SHA-256, source build and BLAKE3 hash, boxes) are published to R2 by the dispatch-only `basemap.yml` workflow and read through `/feeds/`. The first measured build (Protomaps 20261008) is 180.3 MiB. Credit: "© OpenStreetMap contributors, © Protomaps". The whole archive is publicly downloadable from `/feeds/tiles/basemap/`, so it is redistributed as an ODbL derivative database: the attribution and ODbL notice stay with it and the extract itself is offered under the [ODbL](https://opendatacommons.org/licenses/odbl/1-0/) (share-alike). Commercial use awaits the owner's register row (`protomaps-basemap` is a candidate source, [register B6](legal/data-rights-register.md#b6--openstreetmap-tile-service)). It is not a nautical chart.

The Chart coastline is NOAA National Geodetic Survey's [Continually Updated Shoreline Product](https://nsde.ngs.noaa.gov/more.html) (CUSP), imported per region by `scripts/shoreline/import_cusp.py` from NOAA's zoom-12 shoreline tiles into `catalog/shoreline/<region>.geojson`; the platform build checks it and copies it to `dist/regions/<id>/shoreline.geojson`. Each feature keeps its source date (`source_date`), horizontal accuracy (`HOR_ACC`), creator and citation. Only NOAA-created features are kept (U.S. government public domain; CUSP also carries outside contributors, which are counted for review, not published). Tiles NOAA does not serve are listed as unavailable. Lines are quantised to the tile grid (about 2 m at 35° N), separately from source accuracy, and may be generalised from NOAA's source vectors. Morro Bay (imported 2026-10-08): 3,750 lines from 29 served tiles, source dates 1994–2010. These are historical mean-high-water lines, not a live or tidal shoreline, a legal boundary or a chart.

Aerial imagery (`usgs-naip`, candidate pending owner confirmation) is the USDA NAIP natural-colour mosaic from the fixed [USGS The National Map ImageServer](https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer), requested live by the browser only when a viewer selects the aerial base; SkipperCast stores no tiles. NAIP is U.S. government public-domain imagery (commercial use allowed); credit "USGS / USDA · NAIP aerial imagery (dated mosaic)" ([USGS copyrights and credits](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)) without implied endorsement. Only the NAIP-only service is used: USGS's mixed imagery services carry third-party restrictions and are never substituted without review. The host is the one `packages/coast` `mapSourceHosts` allows, and `tests/test_naip_source.mjs` keeps the catalog and `naipSource()` in step. A region offers the aerial base only after its coverage is checked; `regions/<id>/region.json` `basemap.aerial` records the check date and the acquisition window the publisher's catalog listed (Morro Bay, checked 2026-10-08: 2022 NAIP, flown 13–29 May 2022). USGS can load a newer NAIP year at any time, so the label stays "dated mosaic" and the window is re-checked with each region review. The imagery shows land and shore at about 0.6 m; open water is blank, and the mosaic is neither live satellite imagery nor a view of the seafloor. Selecting it sends ordinary tile requests from the viewer's browser directly to USGS.

## Daily species evidence

The [daily pipeline research and source register](bite-evidence.md) documents the rolling local charter-report sample, NASA/NOAA satellite grids, IOOS surface radar, buoy observations, tide predictions, advisories, forecast archives and legal-page change checks. Source timestamps, missing cells and failed reads remain explicit. The data branch updates independently of static habitat releases; no unsupported bite probability or charter GPS position is inferred.
