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

[Open-Meteo API data](https://open-meteo.com/en/licence) are provided under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Credit Open-Meteo and the underlying providers: ECMWF for IFS/WAM and NOAA for GFS/GFS Wave. SkipperCast collects, compares, and summarizes model responses; it does not generate those models. Preserve model names, units, issue/availability information, and any changes when sharing derived forecasts. The [free API's noncommercial access terms and rate limits](https://open-meteo.com/en/terms) are separate from the data license. Open-Meteo's AGPL server-code license does not by itself apply to SkipperCast's independently written API client.

[NOAA MarineCadastre's AIS repository](https://github.com/ocm-marinecadastre/ais-vessel-traffic) and its inspected 2024 point/track documentation identify their content as [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Credit NOAA Office for Coastal Management and acknowledge the U.S. Coast Guard Navigation Center. The public archive is a research source, not proof that a vessel was fishing or caught fish. Large raw AIS archives are not bundled here.

Other retrieved forecasts, observations, rules, charts, service responses, and dependencies retain their own terms. Merely linking to or querying a service neither relicenses its content nor establishes a right to redistribute all of it. No agency, data provider, chartplotter vendor, or dependency author is represented as endorsing SkipperCast.

See [data sources and processing](docs/data-sources.md) for dataset metadata, the published subset, and remaining limitations.

## Web map dependencies

The static app bundles Leaflet 1.9.4 under its BSD 2-Clause license, preserved in [LEAFLET-LICENSE.txt](dist/vendor/LEAFLET-LICENSE.txt). Exact downloaded asset hashes are recorded in [the vendor manifest](scripts/web-vendor-sha256.json). The SkipperCast license does not replace Leaflet's terms.

The browser base map is © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright), under ODbL; standard tile access follows the [OSMF tile policy](https://operations.osmfoundation.org/policies/tiles/). Tiles are requested for the visible map, not redistributed in this repository or bulk-cached. The map is geographic context, not a nautical chart. Open-Meteo forecast data retain the attribution and terms above.

## Published charter-ground facts

The separate charter-report layer attributes concise dated trip facts to SoCalFishReports and the reporting boats/landings, with original links in `dist/data/charter-grounds.json`. Reports are not independently observed catches. Raw pages, articles, photos and audio are not redistributed. The publisher retains rights in its material. Search outlines are new geographic interpretations using the already credited USGS surveys and dated CDFW/restricted-area screens; they are not reported tracks or the withheld DS1091 ground layer. See `docs/charter-grounds.md`.

## Daily public evidence

The daily pipeline and evidence panel use separately attributed provider facts. MUR sea-temperature data were provided by JPL under support by NASA MEaSUREs; source metadata permits free use and redistribution. Aqua MODIS chlorophyll is NASA GSFC Ocean Biology Processing Group data under NASA's data policy. NOAA IOOS/HFRNet provides surface radar currents through NOAA CoastWatch ERDDAP; its dataset metadata permits free use and redistribution. Native units, source dates, metadata links and missing cells are retained; compact regional sampling and confidence notes are SkipperCast processing. No provider endorsement is implied.

NDBC, NWS and NOAA CO-OPS supply observational, advisory and tide facts. Open-Meteo supplies access to explicitly named NOAA/ECMWF model data under CC BY 4.0 and its noncommercial API access terms. Public landing catch facts link back to SoCalFishReports; articles, images and raw report pages are not redistributed. CDFW and harbor-page checks publish source links and content hashes, not copied page content or automatic legal advice. See [the daily evidence research](docs/bite-evidence.md) for exact datasets, use limits and collection behavior. The personal-use project license does not relicense these underlying data.

## Historical commercial fishing effort

`dist/data/commercial-ais-effort.geojson` and its companion metadata derive from © Global Fishing Watch. 2025. [Global AIS-based Apparent Fishing Effort Dataset v3.0](https://doi.org/10.5281/zenodo.14982712), licensed separately under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). SkipperCast extracted regional July/September 2024 records, selected repeat-day cells and excluded MPAs. Non-commercial source-data terms remain in force; the SkipperCast personal-use license does not relicense this dataset. Source classifications are provisional, coverage is incomplete, and apparent effort is not verified catch or charter identity.
