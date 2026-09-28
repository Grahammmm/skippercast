# Morro Bay tuna search overlay

Research reviewed September 28, 2026. Implementation: `ocean-transition-v2` in
`dist/search-plan-data.js`. This is an environmental search shortlist, not a
calibrated catch prediction. No current Morro Bay tuna catch coordinates were
verified during this review.

## Which fish, which conditions?

**Albacore:** investigate the offshore side of coastal upwelling, especially
warm oceanic water beside a temperature front and a transition away from
chlorophyll-rich coastal water. Nieto et al. (2017) found associations with SST,
chlorophyll and fronts using 1988–2011 fishery data; substantial seasonal and
annual variation remains. Its broad Northeast Pacific model is not a calibrated
Morro Bay bite model. [Original NOAA-hosted manuscript and metadata](https://repository.library.noaa.gov/view/noaa/62817).

Small-sample tagging supports active use of submesoscale fronts, but does not
supply a universal front-strength threshold or guarantee fish at an edge.
[Snyder et al. 2017](https://aslopubs.onlinelibrary.wiley.com/doi/10.1002/lol2.10049).

**Pacific bluefin:** temperature alone is a weak selection rule. Use environmental
boundaries to narrow a search, then prioritize actual bait and fish marks and
credible dated local reports. Bluefin use different depths; surface products
cannot describe their entire habitat. [NOAA species account](https://www.fisheries.noaa.gov/species/pacific-bluefin-tuna),
[original electronic-tagging study](https://spo.nmfs.noaa.gov/sites/default/files/pdf-content/2005/1032/domeier.pdf).

Practical search sequence (planning guidance, not experimentally optimized gear):
1. Compare dated temperature and chlorophyll layers; choose a reachable boundary.
2. Cross the boundary while watching surface temperature, sounder bait/marks,
   working birds and feeding activity. Floating kelp alone is not a tuna sighting.
3. For albacore, search with trolling presentations and investigate strikes or
   concentrated bait with appropriate bait/tackle. For bluefin, match presentation
   and tackle to observed school depth and fish size; do not assume surface fish.
4. Log unsuccessful effort as well as catches, time, coordinates, species,
   temperature, depth of marks and method. This is needed to validate rankings.
5. Keep boat weather, harbor entrance, fuel reserve and return route separate from
   the environmental ranking. Twenty knots is a planning cruise speed, not a
   guaranteed offshore transit speed. No offshore range has been assumed.

## Data and update path

Existing regional bindings → scheduled `live-conditions.yml` habitat refresh →
`habitat_dynamics.py` → hash-checked regional ocean tiles → freshness/time gates →
visible native cells → candidate strips → whole-polygon protected-area screening
→ top three outlined search areas and click-through rationale.

- NOAA WCOFS provides temperature and surface velocity. NOAA documents a daily
  03Z cycle and a 72-hour forecast horizon. The adapter uses the published regular
  output grid, not an invented finer grid. Temperature and velocity from this
  model are not independent evidence. [NOAA OFS FAQ](https://www.tidesandcurrents.noaa.gov/ofs/ofs_faq.html).
- Satellite SST analysis supports dated front inspection with reported analysis
  errors. Analysis is not a direct observation at every pixel. Source bindings
  determine the actual product/resolution; do not label every region as MUR.
- VIIRS chlorophyll adds a separate dated visual context layer. It measures an
  optical productivity proxy, not bait biomass. Do not fill clouds with invented
  values or treat a composite as an instantaneous photograph.
  [NOAA product documentation](https://oceanwatch.noaa.gov/cwn/products/noaa-msl12-ocean-color-near-real-time-viirs-multi-sensor-snpp-noaa-20-daily-merge.html).
- Wind/waves retain the existing independent boat-condition score. Current
  velocity is not boat drift, bottom current, or demonstrated convergence.
- No new cron, paid service, invented catch record or AIS-derived fish claim is
  introduced. Existing scheduled feed operation must still be monitored.

## Transparent ranking

Three adjacent populated cells define each rectangular search strip; masked gaps
are never bridged. Offshore uses `region.bounds`, not shallow `fishing_bounds`.
Uniform water is not promoted merely because it is the best available cell.

Thresholds below are **display heuristics requiring field validation**, not
literature-derived biological optima:

- Require temperature contrast / strip-center distance >= 0.02 °C/km.
- Priority 1: >=0.05 °C/km plus either >=0.1 m/s modeled endpoint velocity
  difference or satellite contrast exceeding twice the largest reported error.
- Priority 2: other supported temperature transitions.
- Priority 3: outside the species profile's broad albacore reference envelope.
  The envelope is not an optimum or proof of absence. Bluefin has no fixed cutoff.
- All fish-location confidence remains Low. Model flow differences can represent
  shear or rotation and are explicitly not labeled convergence.
- Satellite strips require all three errors and a supported contrast, retain
  their acquisition/analysis date, and are usable only within 48 hours of the
  selected time. Forecast frames must be within 90 minutes of selected time;
  upstream freshness/availability gates also apply. No seven-day extrapolation.

## Limits and next validation

This release does not fuse chlorophyll into the numeric rank, verify bait,
identify an optimal seasonal departure date, or prove a current local tuna bite.
The rectangular strips are search windows, not traced biological boundaries.
Only visible fetched cells are ranked, so this is not a coastwide optimum.

Next: time-match independent ocean-color boundaries to SST fronts; calculate
velocity divergence on complete native neighbor stencils rather than endpoint
changes; compare with held-out, effort-normalized local catch and no-catch logs.
Evaluate against a simple temperature-only baseline before increasing confidence.
Expand the Morro Bay ocean domain only with verified feed coverage and explicit
user boat-range preferences. Keep these settings regional and versioned.
