> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/SURFACE-LAYER-DESIGN.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Ocean field visualization

## Design references

Reviewed both live references in the supported browser, including palettes and map settings:

- [Relief Fiddler](https://mite-shiru.co.jp/maps/labo/relief_fiddler/): continuous color ramps, fine boundaries, compact scale and adjustable contextual shading.
- [Relief World](https://relief.bertspaan.nl/world?lang=en): restrained map chrome, contextual labels, continuous scale and contours. Inspected its seafloor setting as well.

The ocean rendering applies those visual principles to existing reviewed marine data. No reference tiles, styles, terrain geometry or source code were copied.

## Temperature

MUR remains a dated daily surface analysis, native 0.01 degrees and sampled at 0.02 degrees. The display blends temperature and analysis error only inside complete adjacent ocean-sample quads. It adds 0.5°F contour lines, sparse values that stay readable at any zoom, and click readings with original analysis time and error. The color range uses rounded extrema of the complete accepted analysis, stays fixed while panning, and appears in the legend.

Missing cells and areas outside the sampled grid stay transparent. Feathering works inward from unsupported edges; it never fills the gap. Invalid replacement grids hide previous imagery and contours rather than assigning the new timestamp to old colors. Freshness remains 72 hours with original clocks, including retained analyses after retrieval failures. Future selected days do not make this analysis a forecast.

## Currents

Each selected product keeps its existing native frame and time selection. WCOFS forecasts and HF-radar observations are not blended across products or across times. The renderer blends the east/north velocity components within complete adjacent wet-cell quads, then derives speed and direction. Native resolution, sample stride, original validity time and limitations remain available.

The color range adapts to the selected native frame; the legend updates with it. Flow paths use screen-spaced seeds and bounded midpoint integration through the supported field. Paths stop at gaps; the overview land mask clips paths. Their motion illustrates direction, not a measured particle trajectory or travel speed. Fixed screen spacing keeps them legible as the user zooms. Original samples remain faint dots, and clicking supported water opens the interpolated reading.

Textures are at most 1024 pixels on their longest dimension. They upload as decoded canvases through the installed MapLibre ImageSource API, avoiding encoded-image round trips and needing no CSP changes. Paths are cached until a frame, camera or viewport changes. Fine rendering adds no reef, harbor-bar, dive-entry or subsurface current measurements.

## Clouds

GOES longwave infrared remains the existing NOAA acquisition-pinned WMS product. Requests now use 512×512 tiles, maximum requested zoom 9, bilinear source resampling, smooth overzoom, stronger monochrome contrast and an outlined shoreline over bright imagery. These display settings do not add satellite resolution. Native source gaps remain unfilled. The resampling request uses the documented [GeoServer WMS interpolation parameter](https://docs.geoserver.org/main/en/user/services/wms/vendor/#interpolations).

Playback uses only actual available acquisition times. Cloud imagery remains a current observation, expires after 90 minutes, and is withheld on future dates. It does not predict fishing visibility or imply that warm infrared pixels are cloud free.

## Verification

See `research/surface-layers-2026-10-03.json` and its screenshot directory. The full suite passes 195 tests, including linear/vector interpolation, opposing-vector direction, missing columns, invalid grids, bounded contours and compatibility with all bundled reviewed current grids. Both TypeScript configurations and the production build pass.

Actual browser checks covered desktop 1440×1000, mobile 390×844 and narrow mobile 320×780; several zooms; temperature/current click details; motion on/off; cloud playback/pause; future cloud withdrawal; and radar withdrawal on a future day. Independent review checked inward feathering and the rejected-SST replacement fix. Existing habitat geometry, sources, gates and parallel data upgrade contract are unchanged.
