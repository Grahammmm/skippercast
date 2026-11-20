# CeNCOOS ERDDAP shore stations (Cal Poly Pier, Morro Bay, Monterey Bay)

- **id:** `cencoos-erddap-stations`
- **Priority:** 10
- **Status:** can ingest now (free/open)
- **Test download (2026-11-19):** PASS
- **Provider:** CeNCOOS (Central & Northern California Ocean Observing System) / Axiom Data Science

## What it measures
In-water sensors: water temperature, salinity, chlorophyll fluorescence, turbidity, dissolved oxygen, pH at piers and bays.

**Variables:** sea_water_temperature, sea_water_practical_salinity, mass_concentration_of_chlorophyll_in_sea_water, sea_water_turbidity, mass_concentration_of_oxygen_in_sea_water_corrected, fractional_saturation_of_oxygen_in_sea_water, sea_water_ph_reported_on_total_scale_external (+ _qc_agg flags)

## Coverage and timing
- Resolution: Point stations
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Central Coast: san-luis-bay-cal-poly-pier-shore (CPXC1), edu_calpoly_marine_morro, morro-bay-bs1, monterey-bay-aquarium-seawate, many Monterey Bay sites
- Temporal resolution: ~1-10 min
- Latency: Minutes (morro sample last 2026-11-19T17:10Z)
- Forecast horizon: Observation only

## Format, licence, cost
- Format: CSV / JSON / NetCDF via ERDDAP tabledap
- Licence / attribution: IOOS data are free and open; credit CeNCOOS and the station operator (Cal Poly CCPE).
- Cost: Free

## Endpoints
- https://erddap.cencoos.org/erddap/index.html
- https://erddap.cencoos.org/erddap/tabledap/san-luis-bay-cal-poly-pier-shore.html
- https://erddap.cencoos.org/erddap/tabledap/edu_calpoly_marine_morro.html
- https://erddap.cencoos.org/erddap/search/index.html?searchFor=Morro+Bay

## Auth
None

**Rate limits:** ERDDAP; poll no faster than every 10 min.

## Who uses it
- Apps: Fish or Pass (credits SCCOOS; same IOOS system, Central Coast is CeNCOOS territory)
- SkipperCast layer: Subsurface / in-situ ground truth (pier water temp, upwelling events, low-oxygen and red-tide flags)

## Connect and download
```bash
S=$(date -u -d '3 days ago' +%Y-%m-%dT00:00:00Z)
# NOTE: URL-encode >= as %3E%3D or ERDDAP returns 500
curl -g -o pier.csv "https://erddap.cencoos.org/erddap/tabledap/san-luis-bay-cal-poly-pier-shore.csv?time,sea_water_temperature,sea_water_practical_salinity,mass_concentration_of_chlorophyll_in_sea_water,sea_water_turbidity&time%3E%3D$S"

```

**Cadence:** Every 30 min; keep 30 days.

**Pipeline fit:** Fits the station/observation path used for NDBC (point time series → D1). Check the *_qc_agg columns: sample pier temps ~20 degC look high for November, so trust only QC-passed values.

**Sample on box:** samples/cencoos_calpoly_pier_shore.csv (194 KB, 2026-11-16..19) and samples/cencoos_morro_bay_wq.csv (20 KB)
