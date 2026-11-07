# MAPLAYER-SST-1: private SST-2 overlay

This is a sibling of the MAPSTYLE test page, **not the live app map**.
No code under `web/`, `server/`, `dist/` or the product pipeline is changed.

## Run locally

1. Put an existing region's published `habitat-dynamics.json` and its referenced
   `habitat-tiles/sst-analysis-*.json` files beneath
   `var/maplayer-sst-1/<region>/`. Preserve their original bytes and tile hashes.
   Use a single frozen `conditions` revision, not a mixture of refreshes.
2. Reuse the private MAPSTYLE medium base archive at
   `var/seafloor/tiles/morro-bay-seafloor-deep-medium.pmtiles`. It is the
   MAPSTYLE-2 medium artifact; never copy it into `dist/` or a public build.
3. Build the offline preview:

   ```sh
   python3 research/scripts/map_style/build_sst.py --input var/maplayer-sst-1/morro-bay
   python3 research/scripts/map_style/serve_range.py 18771
   ```

4. Open `http://127.0.0.1:18771/research/scripts/map_style/sst-test.html`.
   `?zoom=9.5&lon=-121.15&lat=35.35` and
   `?zoom=11.5&lon=-121.02&lat=35.35` reproduce the evidence cameras.
   Installed `node_modules` supplies MapLibre and PMTiles, as on the base test page.

The builder reads no region configuration and makes no network requests. It accepts
another sector's matching metadata and tiles via `--input`; `--output` must remain
under this checkout's `var/`. The current test-page camera and medium base are Morro
Bay-specific; other sectors require their own reviewed seafloor base and camera.

## Source, style and limits

The merged `catalog/layer-inventory.json` identifies the active source as **NOAA
Geo-Polar Blended night SST**, a daily **0.05° (~5 km) L4 foundation analysis**.
MUR is not the current source. `catalog/station-locations.json` locates point
stations; this overlay does not substitute buoy readings for satellite cells.
The underlying analysis may already interpolate observations. It is surface-only,
not bottom temperature, habitat, or fish presence; error support is not a confidence
interval. Attribute NOAA CoastWatch / GHRSST.

`layers.py::sst(2)` supplies the exact 13 turbo colours sampled at 0.04–0.96,
52–66°F boundaries, 0.82 fill opacity and white/black strong-break symbol. Source
Celsius values convert to Fahrenheit without smoothing or upsampling. Colours are
1°F bands; the endpoint colours saturate (<53°F and ≥65°F share the end bins).
Click a cell for its actual Fahrenheit value, including out-of-ramp values.

Unlike the illustrative study's smoothed synthetic 10 m temperature field, break
contours use the **published native temperature gradient**, converted from °C/km
to °F/km, at the same **1.2°F/km** threshold. Marching squares requires four
adjacent valid gradient cells; missing corners and ambiguous saddles yield no
segment. This intentionally avoids implying fine-scale break positions. A missing
temperature cell stays transparent; no nearest-fill, coastline extrapolation or
interpolation is added. Cell rectangles are clipped to the region bounds, not a
new fine-resolution coastline. Nearshore land/coastal masks remain the provider's
coarse mask; the seafloor base has separate survey gaps.

A zero break count means no qualifying break is resolved, **not** that no fronts
exist at sea. The base relief can visually suggest fine texture under an SST band;
that texture is seafloor, not fine-scale SST. The analysis can exceed 66°F and
saturate the chosen ramp. The preview intentionally preserves G's selected ramp.

## Freshness and refresh plan

The data time is the layer's `sample_at`, and every tile must contain exactly one
matching frame. File modification time, retrieval time and page load time never
substitute for it. The page recomputes age every minute and hides/disables the SST
overlay for future/invalid times or age beyond the source's 72 h limit. Missing
private JSON leaves the seafloor visible and the toggle disabled with an error.
Stale retained output remains explicitly marked in the offline JSON.

Reuse the existing daily-data and habitat refresh producers listed in the
inventory; do not add a duplicate timer or new source acquisition. For this private
preview, rerun the builder after copying one newly completed, hash-verified
`conditions` snapshot. No automatic refresh job or live publishing is installed.
Evidence and the exact real input receipt live in AgentOrange's private
`reports/maplayer-sst-1/` directory outside this repository.

**RESEARCH PREVIEW — NOT FOR NAVIGATION.** Medium base: 10 m survey, mixed
vertical references, tan where no survey exists. Neither this page nor its data
belongs in a public build; MAPSTYLE-1's publication guard is unchanged.
