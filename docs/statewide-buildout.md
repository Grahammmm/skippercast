# California coast buildout ledger

SkipperCast now divides the outer coast into the five CDFW ocean browsing regions and **19 smaller discovery sectors**. The sector boundaries are approximate latitude bands for organizing source work. They are not legal lines, navigable areas, fishing grounds or proof of survey coverage. San Francisco Bay and offshore islands need their own local legal/habitat treatment; the existing Southern California package has island focus areas but only a qualified subset of bottom.

`catalog/coastal-sectors.json` is the reviewed sector index. `src/skippercast/platform/sectors.py` verifies that the bands meet without gaps or overlaps and publishes `dist/data/coastal-sectors.json`. A sector records the number of **already published point candidates**, but never calls its whole rectangle mapped. The shared coastal guide can zoom to each sector and shows source-status text. The Northern, Mendocino and San Francisco coast groups still have no detailed regional fishing package; selecting them must not borrow Morro Bay spots or forecast samples.

## Survey discovery is running, qualification is separate

The official [NOAA NCEI NOS survey-footprint service](https://gis.ngdc.noaa.gov/arcgis/rest/services/web_mercator/nos_hydro_dynamic/MapServer) provides intersecting surveys with BAG products. `scripts/discover_noaa_surveys.py` queries every sector, validates complete pages, records exact request URLs, retrieval time and response SHA-256, and retains the previous dated result on a failed query. The existing daily workflow runs it when the last **complete** scan is 30 days old, publishes `survey-discovery.json` on the `data` branch and reports degraded coverage. A saved snapshot is a dated fallback. The first complete scan on September 23, 2026 found **183 distinct survey IDs** across the 19 sectors; one survey may intersect several sectors. This is a catalog lead count, not 183 usable high-resolution grids.

To promote one lead, the add-region skill must inspect its original BAG and descriptive report, acquisition date, local footprint and native cells; confirm horizontal/vertical reference, depth, product uncertainty, masks, resolution and rights; then bind any separately verified substrate. The survey compiler checks the full footprint against current MPA/groundfish exclusions and the region's depth allowance. NOAA's survey polygon alone cannot identify rocks, fish or safe passage. [USGS California Seafloor Mapping Program](https://www.usgs.gov/centers/pcmsc/science/california-seafloor-mapping-program) map blocks and groundtruth are a second discovery path, with each product's own terms and scale reviewed. The [NOAA Bathymetric Data Viewer](https://www.ncei.noaa.gov/maps/bathymetry/) is another official access path, not an independent measurement when it serves the same survey.

## What is ready and what remains

| Coverage | Current state | Next gate |
| --- | --- | --- |
| Statewide browsing | Five coast groups, 19 selectable sectors, regional species candidates and official CDFW links | Local package for each harbor/coast stretch; local menus must be evidence-backed. |
| Protected areas | Statewide CDFW MPA polygons checked by the existing daily source job and shown in the browse map | Screen every new complete target/export geometry against the current authoritative polygon set. |
| Regulations | Daily source checks for five CDFW ocean pages; reviewed Central and Southern jurisdiction packages | New jurisdiction/notice packages, hash-bound human review for Northern, Mendocino, San Francisco and any Bay/island special rules. No automatic open-season claim from a checked page. |
| Bottom | 132 Central Coast point candidates and 11 survey-qualified Southern island reef patches in partial packages; northern areas remain discovery only | Ingest original local surveys and substrate, then qualify depth and exclusions. Never turn all survey leads into spots. |
| Ocean conditions | Shared two-model wind/wave and observation/ensemble/surface-water adapters for three existing packages | Add genuine local forecast points, buoy/tide/advisory contexts, test actual provider coverage and watch first scheduled receipts. |
| Species and methods | Coast-level candidate lists; detailed ecology, rule cards and starter methods in existing regional packages | Add locally supported species dossiers and legal cards per package. Catch probability needs identified catch **and unsuccessful effort**, date, position and independent validation. |
| Charter/commercial activity | Limited sourced activity context in existing mapped areas | Verify vessel identity, archive coverage and loiter methods before publishing any new fleet location. AIS does not prove a catch. |

The rollout unit is a **bounded regional package**, not all California at once. Prioritize a working northern harbor package, then repeat the same gate for adjacent sectors. A preview may expose dated context but must withhold unqualified fishing coordinates, open-season badges and precise bottom images. The site can help a fisherman choose *where to investigate*; it cannot know exactly where a mobile fish is at a chosen future time without fresh observations and a validated species model.

## Reproducible commands

```bash
PYTHONPATH=src python -m skippercast.platform.build
python scripts/discover_noaa_surveys.py --output var/survey-discovery.json --previous dist/data/noaa-survey-discovery.json --max-age-days 30
PYTHONPATH=src python -m skippercast.platform needs --region <new-package-id>
python scripts/build_primary_strategies.py
python scripts/check_web.py
python scripts/check_repository.py
```

Use `$skippercast-discover-data` to resolve each sector's needs, `$skippercast-ingest-data` to import approved local products, and `$skippercast-add-region` to compile, test and release the package. The established daily and 30-minute workflows discover non-draft packages automatically. Their source and publication health must be checked before claiming the new area updates reliably.
