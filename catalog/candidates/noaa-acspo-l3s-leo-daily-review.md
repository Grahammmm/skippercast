# Skill 1 review: NOAA ACSPO L3S observed SST

Decision: adopt-with-limits (owner disposition on task t_7eaa1d53, 2026-10-23).

Authorship provenance: the historical research/proposal was prepared by the research-grok worker. The 2026-10-23 disposition, evidence-boundary corrections and offline validation were authored by actual runtime gpt-6.1-sol (profile sol-escalation), using prior Astra availability receipts. The initial proposal commit inherited an unrelated Fable git identity; that label is not evidence of Fable authorship or independent review. This signed follow-up records the actual author without rewriting history. Independent review of the full proposal remains required from actual Opus 5.5 (opus-coder).

The owner approved the observed-layer direction with stated coverage gaps and cloud masking. This is not evidence of restored service, measured delivery latency, cleared commercial/redistribution rights, or publication readiness. Bulk downloads remain held. The linked implementation task may proceed with offline fixtures within those limits; live collection and public activation must still satisfy the existing source, rights, freshness and review gates.

The original three-date provider-axis acceptance item remains **not demonstrated**. No replacement measurement is claimed. The last admitted check, 2026-10-23T13:52:42–45Z, returned HTTP 404 text/html for CDaily, PMDay, PMNight and KDaily, not time-axis CSV. Each response was 34,988 bytes with SHA256 `f93b382123420fe9b7e44711bc707a4375aca48c75717110a69307f38a6ca523`. Raw responses and request receipts are retained in the task workspace's `.acspo-diagnosis/run-1089/`. No additional network probe was made for this disposition. Earlier checks attributed the failure to IPv6; the latest receipts show working IPv4 and upstream HTML 404s instead.

Adopt `noaacwLEOACSPOSSTL3SnrtCDaily` (degrees C) as the proposed observed 1-day sea-temperature field for the 15 California regions in this review's original scope. Do not mark the catalog entry approved. Do not ingest in this card. The proposed `catalog/sources.json` object is in the JSON block under "Source-entry proposal" below with `review_status` `candidate`. It is not inserted into `catalog/sources.json`. An approved entry's license must be one of public-domain, CC0-1.0, CC-BY-4.0, CC-BY-NC-4.0 or facts-only (`schemas/source.schema.json`). This license string is none of those. Owner adoption of the product direction does not supply that missing rights mapping.

Checked 2026-10-20. `coastwatch.noaa.gov` ERDDAP time-constraint requests did not return from this host. Live reads that did return are named below. A prior note on this card cited a NEFSC end of 2026-10-17T12:00:00Z. That claim is withdrawn: the live NEFSC info page read on 2026-10-20 ends 2026-03-15T12:00:00Z.

## Historical provider research (2026-10-20)

The following metadata findings and citations are retained from the prior research worker's note, not re-fetched on 2026-10-23. The saved 2026-10-23 availability receipts establish failure, not the contents of the unavailable dataset metadata. Per-variant metadata/rights confirmation and three-date axis measurements remain incomplete; adoption does not promote those unknowns to verified facts.

- Product page, live extract: https://coastwatch.noaa.gov/cwn/products/acspo-global-002o-gridded-super-collated-sst-and-thermal-fronts-low-earth-orbiting.html
- STAR variable list, live: https://www.star.nesdis.noaa.gov/pub/socd2/coastwatch/sst/nrt/l3s/leo/data_description.txt
- AOML CoastWatch DAS and DDS, live, dataset `noaacwLEOACSPOSSTL3SnrtCDaily`: https://cwcgom.aoml.noaa.gov/erddap/griddap/noaacwLEOACSPOSSTL3SnrtCDaily.das
- NEFSC info page, live, dataset `noaa_coastwatch_acspo_v2_nrt`, sourceUrl `https://coastwatch.noaa.gov/erddap/griddap/noaacwLEOACSPOSSTL3SnrtCDaily`: https://comet.nefsc.noaa.gov/erddap/info/noaa_coastwatch_acspo_v2_nrt/index.html
- NASA CMR granules, live, collection C2805339147-POCLOUD, the `metadata_link` on the AOML DAS: https://cmr.earthdata.nasa.gov/search/granules.json?concept_id=C2805339147-POCLOUD&page_size=3&sort_key=-start_date
- AOML's info pages for `noaacwLEOACSPOSSTL3SnrtKDaily`, `PMDay` and `PMNight` returned an HTTP error. Those three IDs are not on the AOML node.

Indexed CoastWatch ERDDAP pages were not used as a time-axis measurement. A 2025-07-20 Wayback copy was not used.

## Provider facts

Institution NOAA/NESDIS/STAR for the Daily line. Id `L3S_LEO_DY-STAR-v2.81`. Processing level L3S. Product version "L2 algorithm V2.80; L3 algorithm V4.6.9". Collation version 2.11.0. Platforms on the live DAS: MetOp-B, MetOp-C, N20, N21. Sensors AVHRR and VIIRS. Grid 0.02 degree, WGS84, latitude -89.99 to 89.99, longitude -179.99 to 179.99, 9000 by 18000. SST variable `sea_surface_temperature`, standard name `sea_surface_subskin_temperature`, units degree_C, fill -327.68, valid -2 to 40. Comment: SSTs are a weighted average of contributing pixels.

License attribute, quoted from the live DAS: "GHRSST protocol describes data use as free and open". Acknowledgement, quoted: "Please acknowledge the use of these data with the following statement: These data were provided by Group for High Resolution Sea Surface Temperature (GHRSST) and the National Oceanic and Atmospheric Administration (NOAA)."

The live product page says NRT ERDDAP access is best effort, most recent release, last 90 days, source STAR. It lists two Daily datasets: `noaacwLEOACSPOSSTL3SnrtKDaily` (Kelvin) and `noaacwLEOACSPOSSTL3SnrtCDaily` (degrees Celsius). Reanalysis is a different delayed science-quality line (`noaacwLEOACSPOSSTL3SCDaily` / `SKDaily`) and is not this dataset. PO.DAAC overwrites NRT with that reanalysis after about 2 months. Daily DOI 10.5067/GHLDY-3S281.

The product page's indexed overview, same URL, says the family is PM, AM and Daily, and that Daily combines PM and AM, day and night, into one grid normalized to 1:30am viewing conditions. The live extract of the page confirmed the data-access table and did not return that overview paragraph, so the 1:30am sentence is from the indexed text of the official page, not from the table extract.

KDaily is the Kelvin label of the same Daily NRT line. Do not ingest it as well as CDaily. Its time axis was not read separately.

Variant disposition (all four exact NRT axis endpoints returned 404 in the saved 2026-10-23 check):

| Exact dataset ID | Evidence scope and disposition |
| --- | --- |
| `noaacwLEOACSPOSSTL3SnrtCDaily` | Historical NOAA DAS supplies the Daily rights, attribution, grid and quality metadata summarized above. Only this Celsius line is proposed for adoption. Live axis/freshness remains unmeasured. |
| `noaacwLEOACSPOSSTL3SnrtKDaily` | Official product-page access table labels the Kelvin Daily line. No separate axis or per-variant metadata verification; not a second independent source and not selected. |
| `noaacwLEOACSPOSSTL3SnrtPMDay` | Historical official indexed lead only; no working per-variant metadata/axis read. Do not extend the Daily rights/grid/quality finding to this variant as independently verified. Not selected. |
| `noaacwLEOACSPOSSTL3SnrtPMNight` | Same per-variant evidence gap as PMDay; no working metadata/axis read. Not selected. |

PM and AM are separate files, not the Daily grid. The product page's sample names are `LEO_AM_D`, `LEO_AM_N`, `LEO_PM_D`, `LEO_PM_N` and `LEO_Daily`. OSPO serves AM and PM operational files for the last 15 days. STAR serves the research Daily line. Search indexes list ERDDAP ids `noaacwLEOACSPOSSTL3SnrtPMDay` and `PMNight` (institution NOAA/NESDIS/OSPO, degrees C). Those ids are not in the product page's ERDDAP link list, AOML does not serve them, and their time axes were not measured live. They are day and night orbit slices. They are not a 1-day composite and not a 3-day composite.

## Latency

The product page publishes a latency. Latency group: "0 Hours <= 24 Hours (NRT)". Latency details: "24 hours". That figure is not marked est.

The CoastWatch ERDDAP time axis itself was not returned from this host, so the three historical dates below are the provider granule names in the GHRSST catalog the DAS links to, not three ERDDAP `time[(last)]` rows. The granule id encodes the 12:00:00Z reference time. CMR feed time 2026-10-20T18:30:37Z. Catalog insertion lag is not ERDDAP delivery latency. Ages and lags below are approximate (est.; rounded to minutes), not provider-published latency figures.

- 20261017120000, reference 2026-10-17T12:00:00Z, catalogued 2026-10-19T01:56:58Z. Insert lag 37 hours 57 minutes. Age at the read: 78 hours 31 minutes.
- 20261018120000, reference 2026-10-18T12:00:00Z, catalogued 2026-10-19T22:56:58Z. Insert lag 34 hours 57 minutes. Age at the read: 54 hours 31 minutes.
- 20261019120000, reference 2026-10-19T12:00:00Z, catalogued 2026-10-20T03:56:59Z. Insert lag 15 hours 57 minutes. Age at the read: 30 hours 31 minutes.

Two of the three catalog inserts were later than 24 hours; that does not measure when the central ERDDAP delivered them. No 2026-10-20 granule was reported in that catalog read. The proposed 72-hour maximum reference-time age is a conservative application policy, not a measured service guarantee. Withhold missing, failed or stale data; a successful HTTP response, catalog insertion, or recent fetch must not reset the observation's age. No current freshness claim is supported by these historical dates.

AOML's local copy, DAS history 2026-10-20T18:28:26Z, reports `time` length 364, `actual_range` 1760616000 to 1791979200 seconds since 1970-01-01T00:00:00Z, and `time_coverage_end` 2026-10-14T12:00:00Z. Axis length and endpoints do not prove uniformly spaced or gap-free rows; no intermediate dates are inferred here. Use AOML as a historical metadata check, not as the live source or a substitute axis measurement.

NEFSC's copy points at the central griddap but its live `time_coverage_end` is 2026-03-15T12:00:00Z (`time_coverage_start` 2025-03-17T12:00:00Z). Do not use it for freshness.

## Clouds and quality

Clouds are missing pixels, not filled values. SST fill is -327.68 degree_C.

`quality_level` flag values 0, 1, 2, 3, 4, 5 mean no_data, bad_data, not_used, not_used, not_used, best_quality. The DAS comment says level 5 is clear-sky and is the level recommended for operational use. The STAR description says the same. L2P bit 15 marks SST as not valid or degraded when quality is below 5. An observed layer keeps only quality_level 5 and draws every other pixel as a gap.

`sst_front_position` is 1 or 0 only inside the valid clear-sky domain, fill -128. `sst_gradient_magnitude` is calculated only where SST is valid, in kelvin per kilometre. Neither fills a cloud.

## 1-day and 3-day

1-day means one CDaily grid. The reference time is 12:00:00Z. The grid combines the day's AM and PM, day and night, inputs. Pixel time offset is `sst_dtime`. It is not a single overpass, and it is not gap-filled.

3-day is not a provider product in this family. If a 3-day view is built, it means: for each 0.02 degree cell, the mean of valid quality_level 5 SST from three consecutive CDaily reference days ending on the newest reference day; if none of those three days is clear, the cell stays empty. Missing days are not replaced by older days. Exclude fill/non-finite/invalid SST even if a quality flag is present. Do not fill from an analysis product. Label it as an application-derived 3-day window, with the contributing-day count and oldest/newest contributing reference times available for each cell. The newest input must meet the 72-hour policy; state that individual contributions can be older within the window. Do not call a PM day or PM night file a 1-day or 3-day composite.

## California coverage

The published grid contains every region box below. This is envelope containment, west/south/east/north as stored in `regions/<id>/region.json`, read during the 2026-10-20 research and rechecked locally for this disposition. These are the original 15 regions, not a claim about all subsequently added packages. No cell inside a box was read, so land and cloud gaps are unmeasured; envelope overlap is not measured usable-water coverage.

- crescent-city: -124.75, 41.55, -124.05, 42.0
- humboldt-bay-cape-mendocino: -124.8, 40.166666666666664, -123.9, 40.95
- shelter-cove-north-mendocino: -124.8, 39.45, -123.6, 40.166666666666664
- fort-bragg-point-arena: -124.4, 38.958333333333336, -123.25, 39.45
- point-arena-bodega: -124.2, 38.4, -122.85, 39.0
- bodega-point-reyes: -123.7, 37.95, -122.7, 38.5
- point-reyes-pigeon: -123.3, 37.18333333333333, -122.28, 37.95
- santa-cruz-monterey-bay: -122.75, 36.6, -121.6, 37.18333333333333
- monterey-point-sur: -122.35, 36.3, -121.65, 36.625
- big-sur-coast: -122.2, 35.9, -121.45, 36.3
- south-big-sur-san-simeon: -122.0, 35.66, -121.2, 35.9
- cambria-san-simeon: -121.95, 35.45, -120.95, 35.66
- morro-bay: -121.95, 34.95, -120.55, 35.85
- point-arguello-conception: -121.25, 34.45, -120.35, 35.07
- southern-california: -121, 32.5, -117.05, 34.45

## Source-entry proposal

This object is a proposal, not a discovery-candidate document or an operational catalog entry.

```json
{
  "id": "noaa-acspo-l3s-leo-daily",
  "name": "NOAA ACSPO L3S-LEO near-real-time daily SST",
  "provider": "NOAA/NESDIS/STAR; NOAA CoastWatch",
  "needs": ["sea-temperature"],
  "documentation_url": "https://coastwatch.noaa.gov/cwn/products/acspo-global-002o-gridded-super-collated-sst-and-thermal-fronts-low-earth-orbiting.html",
  "adapter": "erddap-grid",
  "review_status": "candidate",
  "reviewed_at": "2026-10-23",
  "adoption_decision": {
    "decision": "adopt-with-limits",
    "authority": "Owner disposition on task t_7eaa1d53, 2026-10-23",
    "scope": "Observed-layer direction with stated coverage gaps and cloud masking; offline implementation only until remaining gates clear",
    "bulk_downloads_approved": false,
    "provider_axis_latency_measured": false,
    "publication_approved": false
  },
  "rights": {
    "license": "GHRSST protocol describes data use as free and open",
    "attribution": "Group for High Resolution Sea Surface Temperature (GHRSST) and NOAA. Also acknowledge NOAA CoastWatch when the CoastWatch service is used.",
    "terms_url": "https://coastwatch.noaa.gov/erddap/info/noaacwLEOACSPOSSTL3SnrtCDaily/index.html",
    "commercial_use": "unknown",
    "attribution_required": true,
    "commercial_note": "The file license string is free and open under the GHRSST protocol, with acknowledgement requested. It is not a catalog public-rights value, so this entry must not be approved."
  },
  "authenticity": {
    "basis": "NOAA CoastWatch product page, STAR data description, AOML ERDDAP DAS, and the GHRSST collection linked from that DAS",
    "transport": "HTTPS; official NOAA CoastWatch, STAR and the dataset's own CMR metadata link"
  },
  "coverage_note": "Global 0.02 degree WGS84 grid, lat -89.99 to 89.99, lon -179.99 to 179.99. The envelope contains all 15 California region boxes. Cloud and land gaps were not sampled.",
  "limitations": [
    "Owner approved adopt-with-limits as an observed-layer direction, not rights clearance, restored service or public activation. Bulk downloads remain held. Candidate only: do not bind a live region until the license string is mapped and independent review approves it.",
    "Observed field: keep quality_level 5 only. Fill -327.68 degree_C and every other quality level are gaps, not values to interpolate.",
    "1-day means one CDaily grid (dataset noaacwLEOACSPOSSTL3SnrtCDaily), reference time 12:00:00Z. It is not one satellite overpass.",
    "No provider 3-day composite: an application-derived mean of valid quality_level 5 SST over three consecutive CDaily reference days ending on the newest day. Missing days stay missing; retain per-cell contributing count and oldest/newest times. No clear valid input means a gap.",
    "Do not also ingest noaacwLEOACSPOSSTL3SnrtKDaily. The product page labels it as the Kelvin form of the same Daily line.",
    "PM day and night files are orbit-time slices, not the 1-day or 3-day view.",
    "Published latency is 24 hours. Provider-axis latency over three dates per variant remains unmeasured; historical catalog insertion is not delivery latency. Proposed application policy: withhold past 72 hours from the newest input reference time, not retrieval time; disclose older contributions in a derived 3-day view.",
    "Last admitted axis check 2026-10-23T13:52:42-45Z: CDaily, PMDay, PMNight and KDaily each returned HTTP 404 HTML, not CSV. No source restoration established, no extra retry admitted. Missing/failed/stale input must remain unavailable.",
    "Fetch noaacwLEOACSPOSSTL3SnrtCDaily from coastwatch.noaa.gov. On 2026-10-20 the AOML copy lagged by six days and the NEFSC copy's metadata ended 2026-03-15."
  ],
  "dataset_id": "noaacwLEOACSPOSSTL3SnrtCDaily",
  "allowed_hosts": ["coastwatch.noaa.gov"],
  "max_age_hours": 72,
  "request": {
    "base_url": "https://coastwatch.noaa.gov/erddap",
    "dataset": "noaacwLEOACSPOSSTL3SnrtCDaily",
    "variables": ["sea_surface_temperature", "quality_level", "sst_front_position"],
    "stride": 1,
    "max_age_hours": 72
  }
}
```

## Decision

adopt-with-limits.

Reason: the owner has adopted the observed-layer direction with limits; CDaily's advertised 0.02 degree global envelope contains the original 15 region boxes. Keep the catalog proposal candidate until rights mapping and independent review are complete, and retain the GHRSST/NOAA acknowledgement. Preserve cloud/land gaps and mask invalid SST and all quality levels except 5. Use only the application-derived 3-day semantics above, never a fictitious provider composite. Do not ingest the Kelvin twin or substitute PM slices. Enforce the proposed 72-hour reference-time age policy and fail closed while the central source is unavailable. Provider-axis latency remains unmeasured; the owner decision is not scientific evidence. No bulk downloads, ingestion, live activation or publication is performed by this review. Final decision: adopt-with-limits.
