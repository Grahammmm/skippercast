# Match a source to a need

For each proposed binding, record:

| Check | Useful evidence |
| --- | --- |
| Authenticity | Publisher domain, catalog identifier/DOI, official documentation linking the service, TLS and returned metadata |
| Geographic fit | Actual dataset footprint, observation coordinates, management area, coast exposure and water depth |
| Scientific fit | Measured vs modeled variable, species and life stage, sampling design, calibration and uncertainty |
| Detail | Native resolution, coordinate error, contour interval, vertical/horizontal datum and missing-data mask |
| Time | Observation/survey time, forecast initialization and valid time, release date, latency and update cadence separately |
| Rights | Exact product's redistribution terms, attribution, commercial restrictions, imagery and database rights separately |
| Operations | Bounded public endpoint, supported format, rate limits, version identifiers, incremental updates and failure behavior |

Choose substitutions by measurement, not file extension. NOAA BAG and a state lidar grid can both satisfy bathymetry only after compatible datum, coverage and precision checks. A smoothed contour layer is regional depth context, not a substitute for native 2 m bathymetry. A trawl catch belongs to a sampled footprint and gear type; it is not an exact rocky-reef catch point. A local harbor reference tide is not an entrance-current measurement. An AIS name match is not independently verified vessel identity.

Retain candidates whose value is real but whose rights or access remain unresolved. Mark why they cannot yet contribute to a public target or rating. Do not copy source articles, screenshots or example seabed photos into the application as local evidence.
