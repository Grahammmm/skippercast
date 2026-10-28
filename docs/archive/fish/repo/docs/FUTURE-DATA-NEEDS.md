> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/FUTURE-DATA-NEEDS.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Future data needs · shared SkipperCast coast

SLO Fish Report will become a regional report within SkipperCast. Maintain one reviewed regional release and one reusable rendering engine. This list is a backlog, not a second source catalog.

| Priority | Data needed | Why | Admission requirements |
|---|---|---|---|
| Now | Original numerical bathymetry and masks | Real seabed geometry, depth inspection and contours | Survey hashes, acquisition dates, native resolution, rights, nodata; keep nominal depth when datum is unknown |
| Now | USGS 3DEP elevation and dated NAIP imagery | Coastal terrain and readable geographic context | Published extent, vertical reference and service receipt; land and seabed are not assumed to share a datum |
| Now | Reviewed SkipperCast habitat/species release | Species selection and measured terrain context | Existing complete rights, hash, screening and expiry gates; terrain suitability is not catch probability |
| Now | Existing surface currents | Read direction and strength over the coast | Native wet cells, original issue/observation times and freshness gates; never imply reef-scale or bottom currents |
| Next | Higher resolution measured nearshore surveys | Resolve gaps, rock structure and the surf zone | Original multibeam/lidar/sonar, uncertainty, masks, commercial rights and datum reconciliation |
| Next | Explicit vertical datum transformations | Align land, seabed and tide water level | Local NOAA VDatum coverage and transformation uncertainty; do not apply an arbitrary offset as measurement |
| Next | Reliable measured temperature coverage | Smooth, readable temperature layers with honest gaps | MUR/GOES/VIIRS plus buoys, quality flags and acquisition times; distinguish interpolated display from measurements |
| Next | Cloud fraction, cloud base/top, weather profiles | Weather-driven 3D atmosphere | HRRR, GOES and METAR provenance; satellite pixels alone cannot establish cloud volume |
| Next | Local visibility and turbidity observations | Spearfishing advice | Dated in-water reports or calibrated observations; satellite color is not underwater visibility |
| Later | Historical public charter tracks | Identify likely fishing stops | Licensed AIS history, coverage, harbor/transit exclusion, uncertainty; stopping alone does not establish fishing or success |
| Later | Versioned regional scene assets and update events | Upgrade Fish and SkipperCast together | Atomic release ID, compatible schemas, immutable geometry, rollback and bounded refresh; retain old source clocks on failures |

## Display assumptions for milestone one

- Use nominal depth below a reference surface at zero. Do not claim an aligned chart datum, navigation clearance or actual tide level.
- Exaggerate seabed relief for readability, disclose the factor and offer true scale.
- Use a coarser mesh for overview and load finer meshes near the camera. Mesh spacing is display resolution, not a new survey.
- Measured gaps can show a separately labeled chart-derived estimate when NOAA depth bands support it, as requested by the user. Preserve the original band and mask land. Do not fabricate rocks, habitats, catch rates, temperatures or current observations.
- Show dated aerial imagery as land context. Clouds and water styling are not observations.

## Next evidence to collect

For each proposed source, record the original URL, owner, geography, resolution, date, datum, quality flags, rights, retrieval method, update cadence and cost in the existing SkipperCast source registry. Prioritize the gaps that affect an actual fishing decision.

## Harbor depth context added · 2026-10-06

NOAA ENC Direct provides 1,499 soundings plus depth-area and land polygons. The harbor model is estimated context with original ranges and quality dates, separate from the native surveys. Future improvements should prioritize recent public harbor soundings, higher resolution surf-zone surveys, verified vertical datum metadata, and user-supplied sonar exports with recording times, coordinates, transducer offsets and redistribution permission. The 2009 CSUMB harbor archive is a lead, not an admitted source: its original producer rights need review before commercial use.

## Measured estuary and regional context added · 2026-10-06

- **Admitted:** NOAA 2022 Morro Bay topobathy DEM, all 96 released 1m tiles. Acquisition June 14, 2022; NAVD88 / GEOID12B, original masks retained. NOAA's product STAC assigns NLPL; the No Limit Public License permits reuse and modification. The 0.052m published accuracy test applies to tested open ground, not underwater precision everywhere.
- **Admitted as context:** NOAA ETOPO 2022, native 15 arcseconds (about 400–500m locally), EGM2008. This fills the Monterey–Point Conception corridor and deeper ocean without claiming new fine measurements. NOAA NCEI's own metadata identifies the product as US public domain.
- **Collected:** dated NAIP context across the corridor, plus a 4096px harbor mosaic assembled from four independently georeferenced 2048px original service exports. Original returned bounds and hashes are preserved.
- **Still needed:** recent channel dredging/sounding surveys; a qualified current lidar release for the remaining coast; NOAA VDatum support and uncertainty to reconcile offshore, land, chart and tide references; independently screened habitat packages for Monterey, Big Sur and Point Conception.
- **Not admitted:** unreleased/in-progress 2025 coastal lidar inventory entries and source packages with unresolved commercial rights. Inventory coverage alone does not establish an available dataset.

The +0.8m water plane is an illustrative view, not a measured or predicted tide. See the source receipts and qualifications in `research/coastal-expansion/` and the reproducible compilation steps in the milestone ledger.


## Detailed corridor expansion · 2026-10-06

Admitted regional survey context now includes the reviewed government Monterey producer grid (mixed acoustic 1998–2012 / lidar 2009–2010), USGS 1998 5 m Carmel/Sur shelf grids and NOAA 2008 H11952/H11953 1/2/4/8m depth ladders. The new government-only regional habitat packages add 1,692 original screened physical candidates, about 18.18 km² of deduplicated habitat outlines, beyond the SLO release. Current fish presence remains unmeasured.

Dated USGS 3DEP bare-earth exports cover land throughout the corridor. NOAA's Southern California coastal relief model v2 (2013 edition, 1 arcsecond, roughly 30 m) supplies identified regional seafloor context through native-survey gaps. Both remain separate from habitat grading. This adds no claimed lidar acquisition or precise rock piles.

Still needed: commercially eligible fine bottom measurements and independent substrate evidence through remaining Big Sur / northern Arguello gaps; a separately reviewed northern Monterey fishing-access scope; modern channel soundings; dated coastal lidar outside Morro; vertical transformations with uncertainty; independent species observations. Restricted source geometry remains withheld. Consult source-specific masks, dates and limits before using these layers.

## Shared map homepage · 2026-10-06

The daily SLO report, tide/forecast charts, buoy history and dated fleet evidence now open within the shared map. Next regional bindings need geographically appropriate NWS marine forecasts, tide stations, nearshore wave model points, buoy references, beach advisories and dated local trip evidence for Monterey and Arguello/Conception. SLO data remains a labeled reference until those bindings pass review.

Close-range NAIP detail now has 497 validated 2048-square exports at 2 m scene display spacing, with original intersecting 2022 catalog records. Fifteen requested detail footprints retain existing imagery fallback. Prioritize original dated imagery or measured terrain for genuinely uncovered areas; display enhancement must not become a new accuracy or acquisition-date claim.

## Visual audit: Morro land context and southern imagery · 2026-10-06

The harbor compilation still contains legacy source2 USGS land context sampled from a roughly30m ground export onto2/4/16m display grids. Repeated samples caused the Morro Rock cuboid artifact. Display filtering now removes the dominant blocks without changing native lidar, original heights or source masks. Prioritize a separately reviewed harbor rebuild from already cached source19 USGS3DEP coastal context (approximately16m export spacing, NAVD88 receipt), or better released native topographic lidar for the actual gaps. Its export spacing still does not prove native accuracy. Preserve original fine NOAA lidar and report changed source identities/vertical limits.

The eight-location map audit also found genuine missing/low-detail aerial coverage near Arguello and some other texture footprints. Seek original, georeferenced, dated, commercially eligible imagery for those gaps. Use shaded elevation context until support exists. Remaining coarse shore facets, mixed datum joins and harbor edges need source-aware review; broadening a display filter is not a substitute for new measurements. See `docs/MAP-VISUAL-REVIEW.md`.
