# AVISO+ FSLE (Finite-Size Lyapunov Exponents) — Lagrangian fronts

- **id:** `aviso-fsle`
- **Priority:** 20
- **Status:** paid/licensed (registration; free only for scientific/non-profit per handbook)
- **Test download (2026-11-19):** UNTESTED - needs AVISO+ account and licence
- **Provider:** CNES / CLS AVISO+

## What it measures
Ridges of FSLE = Lagrangian coherent structures: where water masses converge (bait lines/fronts).

**Variables:** fsle_max, theta_max (orientation)

## Coverage and timing
- Resolution: 1/25 deg
- Coverage (Central Coast 34.0-37.0N, 123.5-119.5W (Central Coast CA: Monterey Bay to Point Conception)): Global
- Temporal resolution: Daily
- Latency: 20 days (NRT 'routine production')
- Forecast horizon: Observation only

## Format, licence, cost
- Format: NetCDF-4, ~140 MB/file
- Licence / attribution: Handbook: free for scientific studies or non-profit projects only. Product page: 'any purposes as stated in the licence agreement'. Treat as needing a commercial licence check.
- Cost: Free for non-profit; commercial terms unclear

## Endpoints
- https://www.aviso.altimetry.fr/en/data/products/value-added-products/fsle-finite-size-lyapunov-exponents.html
- https://www.aviso.altimetry.fr/en/data/data-access/registration-form.html
- ftp://ftp-access.aviso.altimetry.fr/value-added/lyapunov (authenticated)
- https://www.aviso.altimetry.fr/fileadmin/documents/data/tools/hdbk_FSLE.pdf

## Auth
Register via the AVISO+ form and tick 'Lyapunov Exponents and Orientations products'; sign licence; wait for approval; then authenticated FTP.

**Rate limits:** n/a

## Who uses it
- Apps: Salty Offshore (FSLE)
- SkipperCast layer: Fronts

## Connect and download
```bash
# Alternative we can own: compute FSLE ourselves from CMEMS geostrophic currents (ugos/vgos) with the GPL 'lagrangian' code (bitbucket.org/cnes_aviso/lagrangian) or py-eddy-tracker — no AVISO licence needed, same-day latency.
```

**Cadence:** n/a

**Pipeline fit:** Prefer computing in-house from cmems-sealevel-nrt.

**Sample on box:** none
