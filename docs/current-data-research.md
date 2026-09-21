# Nearshore current data availability: Avila–Cambria

**Checked September 21, 2026, approximately 21:16–21:24 UTC (2:16–2:24 p.m. PDT).** Public, unauthenticated HTTP reads only. No app changes. These are source-availability findings, not a forecast of boat drift or a fishing recommendation.

**Best finding:** NOAA's WCOFS has populated local surface-current forecasts at approximately 4 km resolution and a verified +72-hour endpoint. Finer **1 km observed** HF-radar vectors were populated near Avila, but did not cover Morro Bay–Cambria in the latest sampled hour. The nominal resolution of an available grid must not be mistaken for local coverage.

## Verified sources

| Source | Direct evidence in this check | Resolution / horizon | Use and limit |
| --- | --- | --- | --- |
| **NOAA/NDBC HFR, US West Coast 500 m** | [DAP dataset](https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_500m.html), `.dds` and coordinate data returned 200. | Hourly observed; latest sampled coordinate was Sep 21 20:00 UTC. Latitude extent 37.455486–38.138725° N, longitude −122.59347 to −122.0469°. | This dataset is in the San Francisco region, **not Avila–Cambria**. Do not advertise a local 500 m current layer. |
| **NOAA/NDBC HFR, US West Coast 1 km** | [DAP dataset](https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_1km.html), metadata, coordinates and local velocity/QC subset returned 200. | Hourly observed. Latest sampled local data: Sep 21 19:00 UTC. Metadata says representative of upper **0.5 m**; 1.5 km radial search radius. | In 35.10–35.65° N, −121.20 to −120.65°, **48 of 3,233 sampled grid cells** had paired u/v (denominator includes land). All populated cells were south of 35.15° N, near Avila. None near Morro, Estero or Cambria in that hour. |
| **NOAA/NDBC HFR, US West Coast 2 km** | [DAP dataset](https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_2km.html) returned actual u/v subsets for 17:00–20:00 UTC. | Hourly observed; metadata represents upper **1 m**. | Local paired valid cells: 206 at 17Z, 207 at 18Z, 228 at 19Z; **zero at latest 20Z** in the sampled box. Nearshore northern coverage still poor: at 19Z the nearest populated cell was ~9.9 km from the Morro reference, ~10.9 km from Estero, ~20.7 km from Cambria. Do not transfer these vectors to a nearby small reef as observations there. |
| **NOAA/NDBC HFR, US West Coast 6 km** | [DAP dataset](https://dods.ndbc.noaa.gov/thredds/dodsC/hfradar_uswc_6km.html) returned actual u/v for 17:00–20:00 UTC. | Hourly observed; regional context only. | 40/39/40 locally valid cells at 17/18/19Z; **zero at 20Z**. At 19Z the nearest populated cell was ~3.7 km from Morro, ~4.1 km from Estero, ~8.9 km from Cambria. Useful regional observation, not reef-scale drift. |
| **NOAA WCOFS** | [Sep 21 public catalog](https://opendap.co-ops.nos.noaa.gov/thredds/catalog/NOAA/WCOFS/MODELS/2026/09/21/catalog.html) lists current 03Z run. Thin OPeNDAP reads of `regulargrid.f018.nc` and `regulargrid.f072.nc` returned populated surface u/v, wet masks and actual valid times. | [Official description](https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html): about **4 km** native grid, daily 03Z cycle, 24 h nowcast / **72 h forecast**. Regular grid inspected is 0.04° (~4.45 km N–S, ~3.6 km E–W here). | 112 wet cells with paired surface vectors out of 196 local grid cells at both 21 Sep 21:00Z and **24 Sep 03:00Z**. Better regional forecast resolution than an ~8 km global model, but still cannot resolve a small pile, surf zone or Morro Bay bar. |
| **IOOS / UConn STPS** | [Current NOAA catalog](https://ioos.noaa.gov/models/short-term-predictive-system-stps/) describes West Coast **24 h** surface-current predictions. The catalog links to a [public EDS OceansMap view](https://eds.ioos.us/map/?shortlink=kM40KFuBQuqfpJ_-PstbgA), which returned 200 but requires JavaScript. | +24 h published; exact West Coast grid and current local population **not verified** in bounded checks. | Do not ship as an acquired local forecast yet. A public map exists, but a stable documented machine endpoint, run/valid times and usable local values were not obtained. This is not evidence of a free seven-day fine-grid forecast. |

Sample reference coordinates used only to assess data distance: Morro offshore 35.35, −120.91; Avila offshore 35.15, −120.78; Estero offshore 35.44, −121.01; Cambria offshore 35.56, −121.14. These are research sample locations, not newly recommended fishing waypoints.

## Concrete local examples and retrieval details

- HFR **1 km Avila**, observation Sep 21 **19:00Z**: grid center **35.14056, −120.781975**, ~1.06 km from the Avila sample, u = −0.11 m/s, v = −0.08 m/s, speed ~**0.264 kt toward 234°**. Two radars contributed; HDOP 0.50. The datum is an observed surface-vector estimate, not the boat's expected drift.
- WCOFS **Morro**, forecast valid Sep 21 **21:00Z**, 03Z cycle: wet grid center **35.34, −120.90**, ~1.43 km from the Morro sample; surface u = 0.07730 m/s, v = −0.07092 m/s, ~**0.204 kt toward 132.5°**. Grid bathymetry ~24.2 m. Other tested wet centers near Avila, Estero and Cambria were ~1.1–2.4 km from the sample coordinates. The WCOFS and HFR examples have different times/locations and **are not a matched model-validation comparison**.
- HFR data are packed: u/v and HDOP `scale_factor = 0.01`; u/v `_FillValue = -32767`. DAP's unsigned-byte rendering of the number-of-sites missing value was **129** (signed metadata −127), not 129 contributing radars. Mask missing fields **before scaling**.
- The aggregated HFR metadata's `time_coverage_start/end` did not reliably describe its entire returned time axis. Read actual per-sample `time`, grid coordinates and local masks. Do not use the newest global timestamp when its local cells are missing.
- All tested NDBC/CO-OPS data responses were sent an `Origin: https://skippercast.com` header and returned **no `Access-Control-Allow-Origin`** header. Do not assume a direct browser fetch can read them. A scheduled server collector producing bounded, timestamped JSON on SkipperCast's own origin is the practical integration path.
- For WCOFS, percent-encode DAP brackets. Unescaped `[`/`]` in a raw urllib URL returned HTTP 400 from Tomcat; encoded brackets returned HTTP 200. This is URL syntax, not denied data access.

**Example WCOFS source file:**

`https://opendap.co-ops.nos.noaa.gov/thredds/dodsC/NOAA/WCOFS/MODELS/2026/09/21/wcofs.t03z.20260921.regulargrid.f018.nc`

Append `.dds` / `.das` for schema/attributes, or `.ascii?` with encoded selectors. The successful bounded local query selected:

```text
Latitude[417:1:430][605:1:618],Longitude[417:1:430][605:1:618],
mask[417:1:430][605:1:618],h[417:1:430][605:1:618],
u_eastward[0][0][417:1:430][605:1:618],
v_northward[0][0][417:1:430][605:1:618],time
```

Indices `[0][0]` mean the file's single time and **surface 0 m depth**, verified from the Depth axis. Coordinate/time/bathymetry units were read from `.das`. The file also contains deeper model layers; this research does not validate them as bottom-current observations. Native WCOFS two-dimensional fields are hourly; the regular-grid files tested are three-hourly. Catalog entries and actual valid times should determine availability, not an assumed issue/retrieval equivalence.

## Windage: no defensible generic Parker percentage

[NOAA WebGNOME's FAQ](https://gnome-dev.orr.noaa.gov/doc/faq.html) explicitly identifies its default **1–4% windage as suitable for fresh oil**. It explains that drifting objects' leeway depends on exposed and submerged area, and that ships can move at an angle to the wind. [NOAA's technical notes](https://gnome.orr.noaa.gov/doc/pygnome/tech_notes.html) recommend calibrating an object's behavior using observed positions over time. Neither source supplies a verified coefficient for a 2019 Parker 23 with this user's load, outboard position, gear and sea conditions.

**Recommended implementation:** show modeled/observed **surface-current direction as a provisional setup guide**, with wind independently visible. Leave the boat windage coefficient unset until measured. A short foreground GPS test drift can estimate this boat's actual net motion under present conditions. Name the static reef-alignment geometry separately, show an uncertainty corridor for a projected trajectory, and do not imply the boat will follow a surface vector exactly. Do not derive drift direction/speed from Port San Luis high/low-water times.

## Suggested collector behavior

1. Use HFR only where the local vector and QC are present, recent and within a stated interpolation distance; preserve source grid/time and radar/QC metadata. A missing newest local slice may use a still-fresh older observation, with its actual age shown.
2. Use WCOFS as a **model** for its populated horizon; preserve cycle, valid time, wet mask and grid distance. Do not extrapolate its +72 h endpoint across days four through seven. Any longer-range model remains separately labeled/coarser.
3. Recheck observed vs modeled vectors at matching time/location before estimating local confidence; the available products share observations through assimilation and are not completely independent evidence.
4. Intersect proposed setup corridors with the user's closure mask and depth/land geometry, and require an on-water test drift before treating a line as useful for positioning.

Probe artifacts remain in `/tmp/current-local-*.txt`, `/tmp/current-check-*.txt`, `/tmp/current-wcofs-*.txt`, `/tmp/current-local-results.json`, `/tmp/current-valid-1km-cells.json`, and `/tmp/current-wcofs-results.json`. No unpublished endpoint, credential, signup or paid source was used.
