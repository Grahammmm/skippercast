> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `research/visual-cleanup/coast-audit.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../../README.md) and [front-end design § 15](../../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# Representative live coast visual audit

Inspected https://fish-report.g4651.workers.dev/ on 2026-10-06 at approximately 19:34–19:36 America/Los_Angeles. Browser 2, dedicated temporary tab 1. No viewport override; screenshots are 1280×720. Selected test Morro/boat defaults only at setup. No source data or application changes. Water was temporarily disabled for one diagnostic, then restored.

## Result

All eight selected coast locations rendered in 2D and 3D. The main recurring artifacts are coarse stepped shoreline edges, rectangular imagery differences, and missing land imagery at Arguello. The screenshots show default location frames, with Water & channels, Depth contours, and Reefs & species pins enabled; water transparency 0.5 and relief ×5.

| Area | Visible result | Evidence |
|---|---|---|
| Monterey | 2D has thin pale horizontal and vertical rectangular lines across land: horizontal around y525 beginning x505; vertical around x1175. Default 3D canyon relief looks continuous. | monterey-2d.jpg, monterey-3d.jpg |
| Carmel | Strong coarse stair steps in the shoreline south of the bay, clearest 2D around x650–715/y420–590 and the bottom edge. 3D has coarse vertical shoreline faces. Pins render without obvious collisions. | carmel-2d.jpg, carmel-3d.jpg |
| Point Sur | Wide pale cyan shoreline band, coarse stairs southeast of the point; thin rectangular line around y508. Many pale offshore speckles. Band and speckles remain visible in 3D. | point-sur-2d.jpg, point-sur-3d.jpg |
| Big Sur | Same broad cyan band and stepped coast, especially toward the southeast/right. Pale horizontal line over inland imagery near y219. Offshore speckles continue from Point Sur. | big-sur-2d.jpg, big-sur-3d.jpg |
| Cambria | Fuzzy land imagery and flat-looking nearshore water at the default frame; smaller shoreline steps. Habitat pins appear mainly south of center. No obvious large seam in this view. | cambria-2d.jpg, cambria-3d.jpg |
| Avila | A sharply bounded central land imagery patch is much clearer than its blurred neighbors. Rectangular boundary is obvious in both perspectives. Many offshore pale speckles southwest of the point. | avila-2d.jpg, avila-3d.jpg |
| Arguello | Most severe imagery issue: broad cream/untextured coastal land swath, with abrupt inland boundary against textured land. Thin rectangular lines offshore; speckles and stepped coast southeast. | arguello-2d.jpg, arguello-3d.jpg |
| Conception | Coarse stepped coastal outline on both west and east sides, plus the cream untextured Arguello swath immediately northwest. Fine imagery patch has an abrupt boundary. | conception-2d.jpg, conception-3d.jpg |

## Reproduction and interpretation

Select the named area in Explore a coastal location, then toggle 2D/3D. Default camera frames reproduce the listed artifacts; no special orbit or zoom is required. Screenshot coordinates are approximate and relative to the 1280×720 images.

One diagnostic disabled Water & channels at Conception. The broad pale cyan band becomes smaller, while dark rectangular coastal geometry and the cream imagery gap persist. This indicates both a water-overlay contribution and a terrain/imagery contribution. See conception-3d-water-off.jpg. Browser warning/error logs returned no entries (bounded last 12 entries).

Local source pointers, to be investigated rather than treated as confirmed diagnoses:

- `src/coast3d/viewer.ts:83` selects one imagery asset using the grid center. `:89` can fall back to a different selected asset after texture failure, and `:76` samples only within the selected image extent. A tile whose center selects an image can therefore have parts outside that image extent; overview imagery fallback for each fragment is worth checking. This may explain broad untextured swaths and rectangular detail boundaries.
- `src/coast3d/viewer.ts:49–50` uses nearest-filtered tile coverage cells. The coverage discard logic at `:70–71`, neighboring terrain boundaries, and LOD edge handling are candidates for thin rectangular lines.
- `src/coast3d/viewer.ts:75` clips water using interpolated source height. Inspect the relationship among physical source height, display elevations, and geometry spacing before addressing pale coastal bands or offshore speckles. Do not alter source depths to hide a display artifact.

The deep Monterey/Carmel canyon relief was not classified as a defect. Cambria's lower detail may reflect source coverage or default scale. Native gaps must retain source labels and unknown depths. Non-SLO areas correctly show Local forecasts are not integrated for this map area yet; no recommendation to fabricate regional forecasts.

Scope: a bounded representative default-frame audit, not a navigation or depth validation. All eight areas were checked in both perspectives, with 17 saved screenshots. UI panels cover part of the coast at this viewport and the control panel scrolls internally; no complete missing control or broken layout was observed.
