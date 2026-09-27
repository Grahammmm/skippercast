# Point Buchon survey records needed for 300 ft qualification

Status: **research request prepared; not sent**. This is the specific acquisition gap after the [original valid-beam screen](../dist/data/point-buchon-2007-ncei-valid-beam-overlap.json) and [bounded CARIS inspection](../dist/data/point-buchon-2007-caris-prefix-lead.json). No spot or depth has been promoted.

Ask NCEI and the original CARIS survey custodian for a targeted extract or documented access path for the 2007 `PointBuchon` (`NEW2833`) and `PointBuchon_Control` (`NEW2834`) surveys. Prioritize processed GSF lines `PB129-2245.gsf.mb121` and `MB299-1555.gsf.mb121`, then the other 43 [depth-envelope candidates](../dist/data/point-buchon-2007-ncei-line-index.json). Request:

1. The **actual vertical reference** used for processed depths, the tidal/ellipsoid separation model and epoch, tide-gauge or GPS-height control, sign convention, and processing steps linking CARIS depths to the archived GSF. `TIDE_COMPENSATED=YES` and `TIDAL_DATUM=UNKNOWN` in the GSF are insufficient.
2. Per-line or gridded **total propagated vertical and horizontal uncertainty**, coverage/valid masks, beam rejection method, and definitions of the GSF error arrays and CARIS `TPE` member. Identify whether the provided uncertainties include sound speed, tide, navigation, positioning and gridding errors, and their confidence level.
3. The horizontal reference and realization/epoch, any vessel offsets and layback applied, a processed sounding or surface export for the selected lines, and terms allowing derived research summaries and public fishing maps.

Ask USGS/CSUMB separately for the published `Bathymetry_OffshorePointBuchon` grid's output vertical datum, horizontal realization/epoch, source-to-output processing crosswalk, total uncertainty surface or bound, and the native 5 m deep-water cells. The 2007 NCEI surveys and the 2008 Fugro Pelagos/USGS grid are separate lineages; agreement at sampled pixel centers does not prove a shared datum or rock-scale registration.

On receipt, pin original bytes and metadata, decode valid beams, transform the source to MLLW with a documented error budget, compare cellwise against independently classified substrate, and re-screen the **entire** proposed fishing and transit footprint against current MPAs, federal/security restrictions and NOAA chart hazards. Only then consider a 1–3 habitat-fit rank. Catch likelihood needs separate effort-based observations, including unsuccessful trips.
