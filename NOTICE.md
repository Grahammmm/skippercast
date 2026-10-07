# Licenses and attribution

Reviewed September 20, 2026.

SkipperCast's original copyrightable code and documentation use the [SkipperCast Personal Use License 1.0](LICENSE), identified as `LicenseRef-SkipperCast-Personal-1.0`. It permits personal use and free sharing under its terms. It is a **source-available license**, not an OSI-approved open-source license.

That license does not replace third-party licenses or restrict public-domain information, underlying facts, or rights users already have. In particular, it does not turn USGS data or CDFW's CC BY data into personal-use-only material. Original SkipperCast interpretation and code must be distinguished from their source data.

## Atlas sources

The public [Avila–Point Estero atlas](atlas/avila-point-estero-2026-09-20/) contains 132 habitat targets, 107 partial reef outlines, and 31 optional drift alignments derived from these USGS releases:

- [Point Buchon](https://doi.org/10.5066/P9KBGELE), version 1.1, January 2024.
- [Morro Bay](https://doi.org/10.5066/P9HEZNRO), version 1.1, January 2024.
- [Point Estero](https://doi.org/10.5066/P9ZSTUK1), version 1.1, November 2023.

Credit: U.S. Geological Survey; California State University Monterey Bay Seafloor Mapping Lab; and the University of California Center for Integrated Spatial Research. The inspected bathymetry and seafloor-character metadata identify these USGS-produced datasets as U.S. public-domain material and request preservation of metadata and source attribution. SkipperCast selected targets, calculated habitat scores, clipped and simplified habitat footprints, and inferred structure alignments. Those interpretations are not USGS recommendations or verified catch sites. These source data are not intended for navigation.

California marine protected area screening uses **California Marine Protected Areas [ds582]**, credited to the **California Department of Fish and Wildlife, Marine Region GIS Lab**. The [official metadata](https://filelib.wildlife.ca.gov/public/BDB/GIS/BIOS/metadata/DS0582.html) licenses the dataset under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/). Regional selection, projection, buffering, and exclusion screening are SkipperCast processing steps. The GIS layer is a visual representation; current regulations define the legal boundaries.

Cambria's direct CSUMB Block05 derivatives and Ecotrust's DS1091 charter-ground annotations are excluded from this public edition because the inspected source terms do not establish general redistribution permission. Their publicly accessible hosting is not treated as a license. The [source record](docs/data-sources.md) identifies the excluded material and links to its terms.

## Forecast and AIS sources

SkipperCast's wind and wave forecasts are built from NOAA GFS and GFS-Wave data (U.S. public domain) and ECMWF IFS and WAM open data. ECMWF open data are licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/): credit ECMWF as the source. SkipperCast subsets, interpolates and converts units; see [forecast data](docs/forecast-data.md). The 31-member GEFS wind ensemble is read directly from [NOAA GEFS open data on AWS](https://registry.opendata.aws/noaa-gefs/) (U.S. public domain). Surface currents in the app come from [NOAA WCOFS](https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html) (U.S. public domain). SkipperCast no longer queries the Open-Meteo API at runtime.

[NOAA MarineCadastre's AIS repository](https://github.com/ocm-marinecadastre/ais-vessel-traffic) and its inspected 2024 point/track documentation identify their content as [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Credit NOAA Office for Coastal Management and acknowledge the U.S. Coast Guard Navigation Center. The public archive is a research source, not proof that a vessel was fishing or caught fish. Large raw AIS archives are not bundled here.

Other retrieved forecasts, observations, rules, charts, service responses, and dependencies retain their own terms. Merely linking to or querying a service neither relicenses its content nor establishes a right to redistribute all of it. No agency, data provider, chartplotter vendor, or dependency author is represented as endorsing SkipperCast.

See [data sources and processing](docs/data-sources.md) for dataset metadata, the published subset, and remaining limitations.

Whether each source may be used in a paid product is tracked separately in the [data-rights register](docs/legal/data-rights-register.md); several sources above are not yet cleared for commercial use.

## Web map dependencies

The static app bundles Leaflet 1.9.4 under its BSD 2-Clause license, preserved in [LEAFLET-LICENSE.txt](dist/vendor/LEAFLET-LICENSE.txt). Exact downloaded asset hashes are recorded in [the vendor manifest](scripts/web-vendor-sha256.json). The SkipperCast license does not replace Leaflet's terms.

The v2 pages self-host two typefaces under `web/fonts/` (Latin subsets of the variable fonts, as served by Google Fonts), both under the [SIL Open Font License 1.1](https://openfontlicense.org/) with no Reserved Font Name: DM Sans, Copyright 2014 The DM Sans Project Authors ([DM-SANS-OFL.txt](web/fonts/DM-SANS-OFL.txt)), and JetBrains Mono, Copyright 2020 The JetBrains Mono Project Authors ([JETBRAINS-MONO-OFL.txt](web/fonts/JETBRAINS-MONO-OFL.txt)). The font files' hashes are in the vendor manifest; no font is requested from Google at runtime.

The browser base map is © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), under ODbL; standard tile access follows the [OSMF tile policy](https://operations.osmfoundation.org/policies/tiles/). Tiles are requested for the visible map, not redistributed in this repository or bulk-cached. The map is geographic context, not a nautical chart. Open-Meteo forecast data retain the attribution and terms above.

## Published charter-ground facts

The separate charter-report layer attributes concise dated trip facts to SoCalFishReports and the reporting boats/landings, with original links in `dist/data/charter-grounds.json`. Reports are not independently observed catches. Raw pages, articles, photos and audio are not redistributed. The publisher retains rights in its material. Search outlines are new geographic interpretations using the already credited USGS surveys and dated CDFW/restricted-area screens; they are not reported tracks or the withheld DS1091 ground layer. See `docs/charter-grounds.md`.

## Daily public evidence

The daily pipeline and evidence panel use separately attributed provider facts. MUR sea-temperature data were provided by JPL under support by NASA MEaSUREs; source metadata permits free use and redistribution. Aqua MODIS chlorophyll is NASA GSFC Ocean Biology Processing Group data under NASA's data policy. NOAA IOOS/HFRNet provides surface radar currents through NOAA CoastWatch ERDDAP; its dataset metadata permits free use and redistribution. Native units, source dates, metadata links and missing cells are retained; compact regional sampling and confidence notes are SkipperCast processing. No provider endorsement is implied.

NDBC, NWS and NOAA CO-OPS supply observational, advisory and tide facts. Open-Meteo supplies access to explicitly named NOAA/ECMWF model data under CC BY 4.0 and its noncommercial API access terms. Public landing catch facts link back to SoCalFishReports; articles, images and raw report pages are not redistributed. CDFW and harbor-page checks publish source links and content hashes, not copied page content or automatic legal advice. See [the daily evidence research](docs/bite-evidence.md) for exact datasets, use limits and collection behavior. The personal-use project license does not relicense these underlying data.

## Historical commercial fishing effort

`dist/data/commercial-ais-effort.geojson` and its companion metadata derive from © Global Fishing Watch. 2025. [Global AIS-based Apparent Fishing Effort Dataset v3.0](https://doi.org/10.5281/zenodo.14982712), licensed separately under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). SkipperCast extracted regional July/September 2024 records, selected repeat-day cells and excluded MPAs. Non-commercial source-data terms remain in force; the SkipperCast personal-use license does not relicense this dataset. Source classifications are provisional, coverage is incomplete, and apparent effort is not verified catch or charter identity.

`dist/data/noaa-federal-areas.json` derives from the [NOAA Fisheries West Coast Groundfish Conservation Area GIS service](https://maps.fisheries.noaa.gov/server/rest/services/WCR_SFD_GCA/NOAA_Fisheries_West_Coast_Region_Groundfish_Conservation_Area_service/MapServer). SkipperCast retains the service and layer URLs, response digests, retrieval time and links to controlling 50 CFR text. NOAA describes the GIS boundaries as approximate; legal text and current notices govern.

## Shared coastal renderer

The Central Coast Three.js renderer and report components are ported from the owner-authorized Fish application at commit `4ac5e0cabb369c97beba5db639856b855fda347a`. Its public coastal bridge retains original source attribution, rights, dates, native sample inspection, publication checks and modeled-context distinctions; see [coastal service](docs/coastal-service.md). No new survey admission is made by copying the renderer.

Three.js 0.180.0 is MIT licensed ([retained notice](dist/vendor/THREE-LICENSE.txt)). SunCalc 2.1.0 is BSD 2-Clause licensed ([retained notice](dist/vendor/SUNCALC-LICENSE.txt)). These notices remain separate from the SkipperCast license. The coastal interface uses the already self-hosted DM Sans font under the retained SIL OFL notice above.
