# 0002. Build our own forecasts from NOAA and ECMWF open data

- **Status:** Accepted
- **Date:** 2026-09-29 (records decisions merged in PRs #4, #6, #51 and #54)

## Context

- The app's wind, wave and ensemble numbers came from the Open-Meteo API. Its free tier is licensed for non-commercial use only, which rules it out for a paid product (guide finding A4, P0-10).
- The models behind it are published directly: NOAA GFS, GFS-Wave and GEFS as U.S. public domain on AWS open data, and ECMWF IFS and WAM as open data under CC BY 4.0. Both allow commercial use with attribution.
- A forecast people plan trips on should be reproducible: which cycle, which bytes, what failed.

## Decision

SkipperCast builds and serves its own forecasts from the model publishers' open data, with no runtime dependency on Open-Meteo:

- `skippercast.forecast.build` reads only the needed GRIB fields by byte range, retries with backoff, keeps the previous generation on failure, and publishes tiles with an upstream receipt ([forecast-data.md](../../forecast-data.md)). PR #4.
- The app requests wind and waves from those tiles through the Worker (`/api/om/*` answers in Open-Meteo's response shape, so client changes stayed small). PR #6.
- The 31-member GEFS wind ensemble is read from NOAA's GEFS bucket instead of Open-Meteo's ensemble API. PR #51.
- The remaining calls are removed: currents come from NOAA WCOFS, the hourly SST layer is dropped, and the legacy monitor calls our `/api/om`. PR #54.

## Consequences

- (+) The forecast is commercially usable and its provenance is recorded per cycle.
- (+) Tiles are cached at the edge and in R2 ([ADR 0003](0003-r2-system-of-record.md)), so user traffic does not scale provider requests.
- (–) SkipperCast now operates a GRIB pipeline: storage, compute minutes and upstream format changes are ours to handle.
- (–) ECMWF data must be credited wherever it appears.
- (–) The hourly SST forecast and Météo-France currents are gone until an owned source replaces them.

## Alternatives

- **Open-Meteo commercial plan:** simplest, but a recurring cost and no per-cycle receipt.
- **NOAA NWS point forecasts only:** no marine wave spectra, no ECMWF comparison, and no ensemble.

## Links

- [forecast-data.md](../../forecast-data.md), [data-rights register](../../legal/data-rights-register.md).
- PRs #4, #6, #51, #54; guide P0-10.
