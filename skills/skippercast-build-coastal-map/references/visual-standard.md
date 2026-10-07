# Coastal visual standard

## Art direction that supports decisions

Aim for a quiet, continuous coastal relief map: depth color, directional lighting,
recognizable channels and compact habitat marks. Use the user's references when
available. Relief-map inspiration informs color, contrast and interaction, not
license rights or numerical fidelity. Preserve the established renderer unless a
measured limitation justifies changing it.

The first view should make the home harbor/coast recognizable, show relevant
conditions and offer one obvious target selector. Keep most of the ocean visible.
Use a short information hierarchy: daily summary → map/layers → selected feature
with source, native depth range, confidence and ranking rationale. Control density
must fit desktop and mobile without blocking species or zoom interaction.

## Keep numerical and visual surfaces separate

Native numeric grids, support masks and source evidence are authoritative for
inspection and habitat analysis. Rendering may use tile interpolation, lighting,
color ramps, restrained ambient occlusion and optional vertical exaggeration.
Expose true scale and the exaggeration factor. Shading can accentuate supported
bottom features; do not add procedural rock piles, photorealistic reef texture or
AI-generated geometry that looks like measured structure.

Display smoothing cannot change native sample depths, valid measurement area,
substrate or ranks. Chart-derived and regional-model context retain their labels,
sampling scale and separate support. A coarse cell rendered with many triangles
is still coarse data. Avoid importing visual interpolation back into science.

### Terrain and shoreline

- Render bathymetry, land and water with consistent datum/scale conventions.
  Native positive/negative height and wet/dry masks must remain inspectable.
- Morro's tidal estuary contains shallow water and channels; do not classify all
  positive elevations as dry land or all chart NoData as a vertical wall.
- Remove artifacts at their actual cause: invalid samples, mask handling, datum,
  tile overlap, mixed levels of detail, imagery alignment or shoreline definition.
  Inspect a bounded native window before broad shader tuning.
- Use supported overlap/edge constraints for continuous normals and tile seams.
  Keep source boundaries accessible. Do not smear a known gap into a measured reef.
- Across source resolutions, blend only the display where scientifically compatible.
  Otherwise show labeled estimated/model context rather than a hidden transition.
- Maintain coastline silhouettes, island/cliff shapes and channel connectivity.
  Prioritize harbor, Morro Rock, estuary edges and reef detail before panorama polish.

### Land imagery

Use licensed georeferenced imagery with sufficient native resolution for the
intended zoom, cache identity and controlled level-of-detail streaming. Verify
pixel scale, acquisition date, orthorectification/offsets and seam alignment.
Upsampling is a display improvement, not new image detail. Prefer better original
imagery over synthetic sharpening that invents docks, rocks or shoreline shapes.
Fallback imagery/context can keep the scene continuous while remaining labeled.

### Depth and habitat

Choose a readable depth palette with restrained bands; use contours selectively
by zoom. Avoid contour clutter, excessive shiny highlights and relief settings
that turn small native errors into apparent cliffs. Large-scale channels/reef
edges should be recognizable with and without habitat overlays.

At regional zoom, show a restrained colored habitat region only when supported
by reviewed geometry; explain its level of confidence. Aggregate existing eligible
polygons without manufacturing coverage or smoothing through exclusions. Clusters
must not imply measured habitat across gaps/MPAs. At local zoom show small pins
or indicators for individual eligible reefs. Show outlines/details on selection;
avoid always-on pill labels covering the seabed. Keep IDs stable across zoom and
2D/3D, distinguish selected/hover states and handle dense marks accessibly.

Ranks mean reviewed habitat/terrain fit, not observed fish or chance of a catch.
Lower-confidence search areas remain separate from precise ranked/exportable spots.

### Marine overlays

Currents: continuous-looking flow can use interpolation inside complete supported
wet cells, but retain mask edges, physical vector direction/speed and original
sampling scale. Screen-density/particle count can rise at zoom; measurement
resolution cannot. Do not interpolate across land, missing islands or expired
feeds. Keep useful legends/inspection and a reduced-motion/static option.

Temperature: blend display colors within admitted valid cells; retain cloud/quality
and land masks, time and units. Do not fill missing SST with a confident nearby
value. Clouds: present source-scale coverage and timestamp; avoid treating cloud
imagery as evidence of underwater visibility. Keep the surface layers visually
compatible with bottom relief, and make opacity/legends understandable.

## Verify actual screens, not only code

Pick the views affected by the change; for a major map release inspect:

| View | Observable check |
| --- | --- |
| Home harbor in 2D and 3D | Same data and selection; water/channels visible, coherent land/water alignment |
| Shoreline close-up | No stair-step cliffs, NoData walls, tile gaps or stretched imagery |
| Offshore reef local zoom | Compact pins, selectable evidence, contours and structure legible |
| Regional zoom/endpoints | Continuous labeled context, honest coverage, no dense label wall |
| Desktop and mobile | No horizontal overflow/control overlap; map stays usable; target and zoom work |
| Missing/expired source | Layer withdraws or shows the admitted fallback; clocks/labels remain honest |

Use actual supported browser interactions. Only one agent owns a browser surface
at a time; stop if the user takes control. Save screenshots with view/location,
build and changed layer; link the source receipts and native sample comparison.
A screenshot cannot prove depth correctness, data freshness or complete interaction
parity. A browser service-policy failure leaves visual acceptance pending; do
supported recovery once per changed condition, continue independent work and do
not bypass security or claim source inspection substitutes for visual inspection.

Performance checks are bounded to a concrete risk: loading and switching place,
streamed tile completion, responsive controls, memory/draw workload if changed,
cleanup of source/listeners and a clear graphics-failure state. Reuse existing
performance budgets; do not add an always-on telemetry service or unrelated audit.
