> **Historical archive (copied 2026-10-11, SkipperCast FE-62).** This is `docs/3D-COAST-MILESTONE.md` from the retired Fish (SLO Fish Report) repository at commit `68d7b44` (2026-10-06). It records how Fish worked and what was checked at the time, is not maintained, and may describe services, data and claims that no longer exist. SkipperCast's own documentation is the live truth: start at the [archive index](../../README.md) and [front-end design § 15](../../../../plans/front-end/design.md#15-retiring-fish). Links to Fish code, configuration or data that were not archived are shown as plain text, and identifiers that could not be published were redacted.

# 3D Coast milestone

## Objective

Ship a beautiful, usable Morro Bay–Point Estero scene inspired by the tilted, shaded nautical terrain in Chris Dalke's reference. Build the numerical terrain viewer as an independent module for the planned SkipperCast integration.

## Acceptance

- Numerical survey geometry, masked gaps, readable depth colors and contours.
- Land elevation and dated imagery, with nominal datum assumptions disclosed.
- Habitat/species selection through existing reviewed release gates.
- Surface currents retain native coverage and clocks.
- Orbit, zoom, reset, depth inspection and usable desktop/mobile layouts.
- Type checks, meaningful geometry tests, build and actual browser inspection.
- Save code and publication evidence; do not claim a domain deployment until verified.

## Decisions

Use a standalone Three.js scene with metre-based local coordinates and data-driven geometry. Keep the report and existing 2D map available. Defer volumetric weather until measured weather inputs and performance have been qualified. Do not modify another active SkipperCast checkout or perform the whole repository merge in this milestone.

## Progress

- Reviewed existing survey hashes, numerical caches, habitat gates and current freshness selection.
- Added the future data backlog.
- Compiled 69 numerical terrain tiles, with hash-checked 32 m / 8 m meshes and source identity masks.
- Added USGS land relief and NAIP imagery; verified their published export extents match.
- Built the independent Three.js viewer, 30 ft contours, depth labels, nearest-sample inspection, species filters, reviewed habitat outlines and surface-current arrows blended only inside complete wet source cells.
- Verified desktop and 390 × 844 responsive layouts in the actual browser, including reef navigation, species selection, contours, true-scale relief and the mobile drawer.
- Type checks, all 203 tests and the production build pass. Tests include nodata/seam geometry, projection round trips, original asset hashes and depth masks.
- Fresh ocean collector succeeded at 2026-10-06T20:34Z with original NOAA receipts and observation clocks intact.
- Dependency audit found no Three.js advisory. Existing development-only Wrangler/Miniflare/sharp advisories are outside this renderer change.

## Publication and remaining work

The first milestone is complete and published at https://fish-report.g4651.workers.dev/coast-3d. Implementation commit `bc7a42ab9031ce91c9aa164d0286c3eeb3ffe27a` passed GitHub Actions run `37528779542`. Cloudflare version `776edde3-50fd-4051-ab0e-89c1932bcd55` served that clean build, and the live numerical manifest matched the compiled manifest byte for byte. The actual live browser loaded all terrain, 13 screened reef footprints and the current forecast without console errors. Live reef navigation returned a nominal 189 ft nearest display sample.

The source review found 67 supported WCOFS display-arrow locations versus no complete 1 km radar quads over the measured scene. The overview therefore prefers fresh WCOFS, explicitly labeled as a 4 km forecast; radar remains a fallback. No source gaps are extrapolated.

The custom domain still requires the previously pending DNS handoff. The full SkipperCast repository merge, shared automated scene publication and measured volumetric weather are subsequent work. The viewer and geometry contract are separated from the report wrapper for that integration.

Local evidence: `artifacts/coast3d/publication-receipt.json`, `live-overview.png`, `tests.log`, `deployment.log` and `provenance.json` in the published scene assets.

## Rebuilding the derived assets

Run `scripts/build-coast3d.py` with the existing GIS Python. It reads the approved numerical cache under `artifacts/government-engine`, validates original archive and COG hashes through the existing bathymetry importer, and reads the bounded official land exports plus service/export metadata from `artifacts/coast3d`. It never downloads or edits another SkipperCast checkout. Generated assets are committed so ordinary web builds do not require GIS dependencies. A changed source requires reviewed collection and a complete replacement scene release; do not mix manifests and old geometry.

## Harbor and shared perspective follow-up · 2026-10-06

Objective: open at Morro Bay Harbor, show species pins, add public chart-derived estimated depth context in survey gaps, and let 2D/3D change only the camera while retaining layers, selected species and inspected points.

Acceptance: complete NOAA chart extracts; measured data stays primary; modeled depth retains its chart range and source class; no interpolation across land; reviewed species pins; one shared 2D/3D scene; actual desktop/mobile checks; save and publish.

Decisions: the user authorized chart-supported estimation and requested all available public depth sources. NOAA ENC soundings, depth-area ranges and land polygons are available. Chart source dates and quality are retained. No own-vessel recording or commercial chart copying is assumed. Chart estimation cannot create rock geometry or fish-presence claims.

Progress: collected 1,499 chart soundings (579 in the harbor vicinity), 144 depth areas, 229 land areas and 18 quality areas using bounded complete pagination. Returned local datum features are empty; a zero-reference display assumption remains explicit. Building a separate estimated mesh and shared camera/pin controls.

Implementation and local verification: 68 chart context tiles, 1,499 original chart soundings, 396,607 bounded sounding estimates and 35,668 range-only estimates on the 16 m display grid. The index buffers exclude triangles that cross charted land. The native survey hashes and files remain unchanged. The chart compiler reads the persisted reviewed extracts in `research/noaa-enc-morro-bay`; new collector results go to `artifacts/harbor` for review before replacement. A new native survey identity withdraws the old chart model until it is recompiled against that release.

The explorer now has orthographic 2D and perspective 3D cameras over one scene. Species, chart model, current layer and selected readings/pins survive the camera toggle. The existing daily report dashboard remains available through its own navigation. Report navigation now names the shared explorer “Coast 2D / 3D”.

Local checks: 204 Node tests, four GIS model tests, both TypeScript configurations and production build passed. Actual desktop and 390 × 844 browser checks passed for home framing, a harbor chart estimate (~4 ft, original 0–6 ft chart band), native reef inspection, selected pin persistence, species filtering, layer toggles and the mobile drawer. Console error/warning inspection returned no entries. Publication verified.

Publication: implementation revision `3dd5c95dfa6a2493d0fa8150f0158e6d6df84331` passed GitHub Actions `37538608224` and was published as Cloudflare version `836857e8-2956-4d0c-a296-60ec87150f05`. The live release is clean, both manifests and provenance match locally compiled bytes, and all eight harbor overview/fine binary assets match their hashes. Actual live 2D/3D depth inspection preserves the same chart-derived harbor reading and band. The harbor/pin/shared-camera follow-up is complete on the live preview. See `research/noaa-enc-morro-bay/publication-receipt.json`; screenshots are in `artifacts/harbor/live-harbor.png` and `mobile-2d.png`. The custom-domain DNS handoff and complete repository merger remain separate future work.

## Coastal expansion and shoreline standard · 2026-10-06

Objective: integrate measured Morro Bay lidar, render a clear water surface and harbor channels, improve source transitions and shoreline geometry, begin the Monterey–Point Conception corridor, add deeper public bathymetric context, and restore reviewed species/reef outlines, rankings and evidence detail in one shared 2D/3D scene.

Acceptance: native NOAA lidar tiles and masks qualified; regional deep ocean context has original source/datum/scale; terrain and imagery cover the corridor; dynamic tiles are bounded by camera distance and GPU budget; detailed SLO survey and habitat assets remain authoritative in their support; rankings use existing physical species fit and evidence fields; no unsupported fish probabilities; high-resolution shoreline/water visual checks at harbor and regional limits; typechecks/tests/build/desktop/mobile/live publication.

Decisions: retain source dates, masks and distinct datums. Any blending of terrain across unmatched height references is display context only and must not change exported or inspected native values. Standardize smooth normals, consistent edge sampling, source-aware colors, water depth readability, hierarchical tile detail and surfaced evidence limits. Preserve the established source release gates and other SkipperCast worktrees.

Progress: NOAA 2022 harbor DEM sample verified at native 1m, NAVD88. Preparing bounded complete collection and regional context source review.

### Mapping standard and implementation

1. Keep a complete regional model behind streamed measured detail. Missing survey pixels retain their source masks and receive separately identifiable model/chart context.
2. Use the same scene, source classes, species filtering, rankings, evidence and selection for both cameras. Perspective changes do not change data admission.
3. Prefer a land/bottom survey sharing one vertical reference at the shoreline. Preserve original source values. Datum reconciliation requires a reviewed transformation; a visual offset is never treated as a measurement.
4. Blend only the presentation. Continuous display triangles and limited boundary smoothing (1.5m for lidar, 8m elsewhere) soften seams while raw nearest displayed samples remain inspectable. Do not erase large elevation differences or invent rocks.
5. Show channels using depth-aware translucent water and finer lidar contours. Label the +0.8m water surface as illustrative. Mesh refinement does not add source precision.
6. Stream bounded nearby terrain, refine valid lidar first, share geometry between water and bottom, and dispose obsolete geometry. Keep a bounded imagery cache and release unused textures.
7. Render original qualified habitat evidence. Rank species fit, then physical terrain score. Disclose grade, survey date/resolution, support, missing independent corroboration, nominal datum and original screening expiry. Never present these scores as catch probability.
8. Bind derived full-context geometry to exact reviewed archive/export hashes and original expiry. Recheck all regional publication HEADs. If the source edition changes, withdraw old full context and allow only independently reviewed current curated details until recompilation. Rights/screening failures withdraw reefs immediately.
9. Use physical sandy-shore context for surfperch/halibut without reef-fit inference. Preserve dated access/legal review clocks and identify expired legal review.

### Reproducible collection and compilation

Committed scene assets build without GIS software in Cloudflare or GitHub CI. Source rebuilding uses Python with rasterio, numpy, scipy, shapely, pyproj and Pillow, plus the existing reviewed government engine cache and original USGS COG receipts. Run the following stages from Fish with that GIS runtime:

- `scripts/collect-coast-terrain.py`: resumable bounded original NOAA lidar/ETOPO collection; source hashes and original retrieval receipts.
- `scripts/collect-coast-imagery.py`: official NAIP exports within the service's 2048px request limit; georeferenced regional images and harbor mosaic.
- `scripts/build-regional-coast.py` (automatically calls `scripts/build-coast-overview.py`): horizontal-only reprojection, original native samples/masks, complete model context, source classes, gzip assets and manifest.
- `node scripts/build-coast-habitat.mjs`: revalidate the government release and extract unchanged canonical habitat and physical scores matching the public release pins.
- `scripts/build-coast-habitat-display.py`: hash-bound context simplification with original geometry retained whenever inverse projection would invalidate an outline. Three such outlines were retained in this edition.
- `scripts/verify-regional-coast.py`: finite background coverage and original lidar value comparison within one native cell of an independent projection lookup. This accounts for horizontal operation choices at cell boundaries; it does not claim new survey accuracy.
- `npm run check`, `npm test`, `npm run build`; then actual desktop/mobile browser checks and normal reviewed publication.

### Verification before publication

- All 96 released NOAA DEM tiles collected. Tile 088 is not a released DEM; it is not silently generated.
- 3,468 main tiles, 54 harbor refinement tiles, a wider continuous full-coast overview, 43 original/mosaic imagery assets and a georeferenced NAIP overview atlas compiled.
- 87 sampled lidar values and 15 native USGS survey values matched original measurements within one native cell; 3,469 background grids are finite. Numerical source values are not vertically transformed.
- 2,868 original screened polygons retain physical scores, source evidence and source bindings. Display simplification retained three original outlines to avoid invalid inverse-projected geometry.
- 212 Node tests pass, including bounded decoding, source-class validation, source binding/expiry, original ranking order and raw-reading preservation during display smoothing. Type checks and production build pass.
- Desktop and 390×844 phone interaction checks passed for perspective switching, ranked evidence retention, depth filtering, shore context and Monterey/Point Conception coverage. No browser errors observed in those checks. Final publication receipts remain pending until live verification.

- Chart-channel browser verification found a halfway rounding mismatch in the original band lookup. The lookup now uses the compiler's round-to-even rule and requires an exact match to the original chart depth before attaching its band/method. A regression test covers those ties.

- Full-coast QA exposed the finite background rectangle and missing coverage east of the first ETOPO tile. A second original adjacent ETOPO tile now supplies the wider background with actual masks and no zero-filled gaps. A geographically aligned, downsampled NAIP atlas adds dated land imagery in the overview. Native measured sources and their hashes are unchanged.

- Live verification found cracks between adjacent display levels of detail on inland ridges. Rendering-only edge skirts now hide those gaps. Their vertices preserve original surface normals and are excluded from depth inspection; original measurements, masks, source classes and habitat scores remain unchanged.

### Initial live publication and final seam correction

- Main implementation `6ef48dd3da5929ba058abafa1d4a571ebdf8b95c` passed GitHub Actions 37545633744 and published as Cloudflare version `56ecafd6-a7da-4621-bf7f-bcca5ce0274d`.
- Actual live release metadata was clean and matched the commit. Live terrain manifest, full reef context, wide overview and NAIP atlas matched expected byte counts and SHA-256 hashes. The live browser admitted 1,853 lingcod candidates from the complete screened context, streamed 84 terrain tiles and reported no browser errors.
- The live visual check exposed inland gaps at the boundary between coarse background and streamed terrain. Both the detailed edges and the exposed parent edges now have noninspectable rendering covers. Neutral shading keeps those covers from producing dark edge shadows. White gaps disappeared in the local visual check, and the original 9ft / 6–12ft chart reading remained unchanged. Corrected-commit publication is the last step.

### Completed · 2026-10-06

The corrected implementation `a3a0f7776c02f98387d7188ceeca55cad89203f4` passed GitHub Actions 37547874331 and is live as Cloudflare version `3f1ff04f-36fc-493d-aab3-844f4ffb2105`. The exact clean live commit was verified. Final desktop and 390×844 phone checks admitted the complete reviewed context, displayed 1,853 lingcod candidates, retained working controls and perspective switching, and produced no observed browser errors. Final screenshots and deployment logs are saved under `artifacts/coastal-lidar/`; the committed evidence summary is `research/coastal-expansion/verification.json`.

This completes the requested visual refinement, measured Morro lidar integration, continuous Monterey–Point Conception terrain context and restoration of the existing screened fishing evidence. Detailed fish habitat outside the reviewed SLO packages still needs qualified regional source data. Datum reconciliation and current tide-driven water level remain future data work, as recorded in `docs/FUTURE-DATA-NEEDS.md`. No other SkipperCast worktree was changed.

## Detailed Monterey–Point Conception expansion · 2026-10-06

Objective: extend the shared coastal scene with authenticated regional survey terrain and newly screened physical habitat beyond SLO, retaining the continuous regional backdrop and camera-only 2D/3D toggle.

Acceptance: positive newly usable surveyed terrain and screened habitat in Monterey/Carmel/Point Sur and Point Conception; exact original source hashes, dates, masks, rights and datum limits; unchanged scientific grading and whole-polygon exclusions; geographically bounded release contracts; bounded streaming; actual desktop/mobile regional readback; checks, CI and exact live publication.

Decision: use an isolated `artifacts/corridor-engine` copy of the pinned government engine. Other SkipperCast worktrees are read-only caches. Restrictive CSUMB inputs remain excluded before processing. Native valid/nodata masks do not establish an unknown interpolation mask. The existing northern legal limit remains unchanged; terrain north of that limit does not acquire a fishing permission claim.

Progress: original government Monterey, 1998 Carmel/Sur shelf grids and NOAA H11952/H11953 depth ladders located in existing caches. Copying pinned originals and rebuilding region-specific receipts under the same government-only scope. Independent source review is in progress.

Next action: prove a bounded positive Monterey batch, complete the compatible region batches, extend terrain source descriptors and regional release gates, then verify and publish.


### Verified regional result

- New government-only native-survey processing produced 904 Monterey/Carmel/Point Sur and 788 Arguello/Conception screened polygons. The canonical union adds about 18.18 km² of physical habitat outlines beyond the original SLO package. All 24 regional reach receipts and scientific implementation hashes passed independent preparation. Empty or unreviewed reaches remain explicit.
- Original survey depth ladders and source masks were verified. A separate display compiler added 11 source-specific survey descriptors, 38 dated numerical USGS 3DEP exports and the original NOAA 2013 1-arcsecond coastal relief subset. Model and land context do not enter habitat processing or measurement credit.
- All 7,149 compiled terrain assets have finite heights, exact hashes and valid source classes. All 11 new COG dataset masks agree with their nodata values; 55 independent original-value comparisons passed. Existing 7,622,263 SLO chart/survey/lidar samples preserve exact source IDs and values.
- Independent review found and resolved a Monterey archive extent mismatch and stale source explanation. Regional bounds now come from each validated original PMTiles header, including complete planning context.
- All 217 Node tests, both TypeScript configurations and the build pass. Four-region atomic promotion, missing-fourth-archive withdrawal and partial-region rejection have explicit tests.
- Actual local four-region HEADs returned 200; exact ranges returned 206; wrong If-Match returned 412. All rendered context bindings match the selected private release. The standard Wrangler preview encountered a process-launch error; a local-only preview using the actual bundled Worker and existing programmatic bindings is available at port 8790.

Remaining acceptance: complete actual regional desktop/mobile interactions, final independent diff review, exact CI/deployment and live archive/visual readback. No other SkipperCast worktree was changed.

### Browser and final review

Actual local desktop checks passed for Morro, Monterey, Carmel and Conception: source-bound species pins, regional labels, complete ranked context, source explanation and the camera-only 2D/3D transition. On a 390 × 844 viewport, location/species selection, layers panel, water visibility, source coverage, source dialog and 2D/3D controls passed. Point Sur and Big Sur retain source-qualified context. Console inspection found no warnings or errors in these checks.

Settled views revealed conspicuous streaming-boundary curtains. A display-only 256 m inner band now meets the parent surface; exterior corners are re-pinned after intersecting bands. Three independent actual-method regression tests prove matched edges, unchanged raw readings, repeatable morphs and skirts. The source dialog distinguishes this transition from bounded source-boundary smoothing. A 1025-square regional parent uses the same authenticated NOAA model and dated USGS land exports; the wider original ETOPO background is retained. Its exact hash, finite values, bounds and source IDs were independently verified. No habitat scores or scientific inputs changed.

Independent reviewer approved the final source, pipeline, regional contract and render changes. Final code has 217 passing tests, both TypeScript checks and the production build. Next: exact main CI, approved Fish Worker deployment, atomic four-region private release and actual live readback.

Whole-coast and relief-slider browser checks also passed after excluding outer overview/background skirts on initial load and slider rebuild. A dedicated regression preserves this behavior while retaining normal streamed-tile skirts.

### Publication readback

Main revision `90f2a52c19357507c5a132f8ebf7ef334e5aeaa5` passed GitHub Actions run `37553942181` and deployed as Cloudflare version `51808b4f-1454-4ceb-89e8-24f256c51f73`. Exact live terrain manifest and checked asset hashes passed. Private R2 promotion selected four regions and all 4,560 outlines. Every regional HEAD returned 200, exact original byte range 206 and wrong If-Match 412. Render context archive/export hashes match the selected release.

Live visual readback exposed excessively broad 5% aerial-tile edge fading, producing pale bands. Tightened this presentation fade to 0.2%; source pixels, terrain readings and scientific habitat data are unchanged. Final live desktop/mobile acceptance follows this small styling release.

### Complete

Final mapping implementation `36bcbdb8de4aa3c3f4861f585e6bf21e182172f6` passed GitHub Actions `37554657515` and deployed as version `558260dd-0ba9-4c9e-b2c6-1c533ba7325a`. Exact live client JavaScript, HTML and terrain manifest match the clean build. All four source-bound archives again passed HEAD/range/If-Match readback after this deployment.

Actual live Monterey reef selection retained identical depth, score and source evidence in 2D and 3D. Direct mobile Point Conception loading passed at 390 × 844, with 63 streamed tiles, a source-bound rockfish pin, location/species selection and source-overlay panel controls. Console readback had no warnings or errors. The aerial fade refinement visibly removed the broad pale land bands. Source/geometry/native masks, raw values and habitat science remain unchanged.

The requested expansion is complete and live. Continuous terrain context spans Monterey to Point Conception; admitted fine survey terrain and 1,692 additional screened outlines enrich the original SLO coverage, for 4,560 total outlines. Fine habitat gaps through parts of Big Sur and northern Arguello remain explicitly modeled/held. There is no claim of continuous native survey coverage or current fish abundance. Detailed publication evidence is in `research/coastal-expansion/corridor-publication-verification.json`.

Repeatable display build order: reviewed originals and complete land/model collection → `scripts/extend-corridor-terrain.py` → `scripts/build-corridor-overview.py` → canonical reef context → native/region checks → reviewed private release promotion. The regional parent and broad ETOPO background remain separate source-bound assets.

## Habitat hierarchy, sharper imagery and report integration · 2026-10-06

Objective: replace large reef labels with small selectable indicators; show source-qualified habitat areas at broad zoom and individual reefs at closer zoom; improve dated land imagery at close range; integrate the existing fishing-report data into the shared map landing experience.

Acceptance: zoom hierarchy, selection details and keyboard/mobile controls; holes and original habitat gates retained; bounded high-resolution imagery with original footprints/dates/hashes and fallback; forecast/tide/buoy/catch/source clocks retained; SLO data never relabeled as Monterey or Conception forecasts; build/tests, actual desktop/mobile readback, merged main and live publication.

Decision confirmed by the owner: the shared map is the homepage. The original report remains available at `/report`; its assessments, charts, source clocks and history are reused in the map's expandable daily report.

Next: build the habitat fill/pin hierarchy, collect bounded sharper official NAIP imagery, reuse existing report assessments and charts, then verify and publish.

### Implemented and locally verified

- The shared 2D/3D map now serves `/`; the original full report remains at `/report`. Root routing retains the original security headers and a full-report fallback if the map asset is unavailable.
- Broad views fill admitted habitat polygons and preserve holes. Closer views reveal small selectable reef pins. Selection exposes original depth, physical score, species fit, source date and screening. The camera toggle preserves these facts. Rights, source binding, expiry and withdrawal gates are unchanged.
- The compact homepage report reuses existing daily assessments and original clocks: method, supported day, hourly wind/gust, seas/period, Port San Luis MLLW tide, dated buoy temperature and qualified planning window. Expandable panels reuse the existing forecast/tide charts, 65 annual buoy baselines, original dated fleet counts and source explanations. Current overlays track the selected forecast time only where existing frame gates permit it.
- SLO report geography is bound to Morro, Cambria and Avila. Other map locations explicitly say local forecasts are not integrated. SLO reference reports keep their SLO location, independently of the displayed map.
- The bounded official NAIP collector validated 497 of 512 requested 2048-square coastal image exports, at 2 m scene display spacing. All 1,424 intersecting publisher catalog records retain their original 2022 dates, receipts, exact footprints and image hashes. Fourteen footprints had no image support; one export still failed after a bounded transient retry. Original imagery remains the fallback. At close range, new detail selection is limited to three textures on mobile or eight on desktop. This does not claim current imagery or 2 m positional accuracy.
- All original terrain, source descriptors, native readings, wide imagery and habitat assets are unchanged. Exact manifest comparison and all 497 image hashes, decoded dimensions, footprints and catalogs passed. See `research/map-homepage/imagery-verification.json`.
- Actual local desktop/mobile checks passed: populated daily metrics; hour/day/method controls; spear default/depth; compact pin selection; broad zoom without pins; identical selected reef facts in 2D/3D; outside-SLO coverage explanation; forecast/tide charts; buoy cards; history metric control; dated fleet records; source navigation. Source clocks were copied exactly from already-published snapshots into local test storage only. Console readback had no warnings/errors.

Local validation passed all 223 Node tests, both TypeScript configurations and the production build. Broad-view habitat color is intentionally stronger than close-view outlines so surveyed areas remain readable as individual pins withdraw.

Next: save final presentation and acceptance evidence, exact GitHub CI, authorized Fish Worker deployment and actual live desktop/mobile readback.

### Regional navigation integration

A final integration check found that global ranked reefs could move the camera out of SLO while retaining the preceding report location. A shared, source-region-limited place resolver now updates the title, location selector, URL and report event when ranked reefs or original shore contexts are selected. Monterey/Sur and Arguello/Conception selections never acquire a SLO forecast binding. Reset also restores Morro in the URL. Actual local Point Sur and Hearst/San Simeon jumps passed; two regressions cover the source-region resolver and the actual selection method while preserving selected reef facts.

All 225 tests, both TypeScript configurations and the build pass. Initial homepage publication `2906700a418e1adfdbd15596db1b7c172cdc00b2` passed CI `37558660489` and uploaded all 497 detail images as Cloudflare version `b7fef9f6-2a46-42c3-b4a0-6afbb8e815f8`. The geography refinement is the remaining release step; no original imagery, terrain or habitat data changed.

### Live implementation verified

The regional navigation implementation `fc14fd3e468b3084a1ee9f57dcfae081d8e6ab1e` passed exact CI `37559614015` and deployed as Cloudflare version `242d06b1-46b9-4d9b-bb1c-a79f26c9ee96`. Exact live homepage HTML, common client/CSS, terrain/imagery manifest, detailed imagery receipts and three geographically separated image hashes match the clean build. Full report and health/report/ocean/history APIs returned 200. All four private habitat HEADs returned 200 with their original byte counts and ETags; all render archive/export hashes match the selected approved release `4c24f963f09bf300ff51014affa680ef522bdf4444c9f3567c588b5e5f33740b`. Verification compares that selected consumer release, not the different preparation-manifest ID.

Actual live ranked selection moved Morro to Point Sur, changed the report coverage notice, and preserved original 125–182 ft / score93 / fit3 facts in both perspectives. Browser console readback had no warnings or errors. A 640 × 360 browser window revealed that the map's controls could be squeezed; a 440 px minimum map height now keeps them usable, with natural page scrolling. The local short-window check confirmed scene440 / page622, while normal desktop and portrait-phone dimensions retain their existing height.

Final action: publish this small height safeguard, confirm live desktop/mobile interactions and save the runtime receipt. The source datasets and scientific interpretation are unchanged.

### Return-visit cache correction

A real browser return visit exposed a routing error: the map asset's `304 Not Modified` response was treated as a missing map and fell through to the original report. An independent live ETag request reproduced it (first200/shared map; conditional200/old report). Root routing now preserves secured304 responses and the original ETag instead. The root-route regression checks body/status/security/ETag preservation and retains the genuine missing-map fallback. All 225 tests, both TypeScript checks and build pass. This cache correction and the short-window height safeguard are the final publication changes; scientific data and all other map/report behavior remain unchanged.

### Complete: shared map homepage

Final product implementation `036375d6998463e10556446ae55bb5ea26ecc87f` passed exact CI `37560510258` (225 tests, both TypeScript configurations and build) and deployed as Cloudflare version `e7e24079-73ca-4743-972f-3d4f93afef2f`. Exact live map/client/styles/data receipts and sampled imagery hashes passed. All four unchanged habitat bindings passed again, as did the retained full report and live data APIs. Conditional homepage requests correctly return304 with the same opaque map validator; real browser return visits retain the shared map. Strong habitat If-Match gates remain unchanged.

Actual final live desktop1280×800 and mobile390×844 checks passed. Mobile method/day selection, forecast/tide charts and history work within the shared map. Ranked navigation updates the actual region and preserves selected facts in both perspectives. Browser console readback had no warnings or errors. The short-window safeguard keeps the map at least440px tall; portrait and normal desktop layouts retain their intended height.

The requested pin hierarchy, sharper land imagery and shared-map homepage are complete and live. The full report remains at `/report`. Original terrain and habitat science, source footprints, rights and clocks remain unchanged. Outside SLO, local forecast integration and finer native survey gaps remain explicit future data needs. Publication evidence: `research/map-homepage/publication-verification.json`; local source/imagery checks are beside it. Browser proof images are in the local ignored `artifacts/corridor/` directory.

This final evidence update changes documentation only; the product implementation above is the verified release.

## First-visit home setup · October 6

Objective: ask for home county/port/site and fishing method on first arrival, remember those choices in this browser, and open the shared map with relevant daily facts.

Implemented: a keyboard-accessible entry dialog, county-specific sites within the existing corridor, boat/shore/spear cards, and a versioned first-party preference cookie lasting at most one year. Returning bare homepage visits apply the saved place and mode before starting the report or map. Explicit shared-link locations/methods override this visit only. New saves clear obsolete dates/hours/species; current daily coverage selects the date. Home & style supports editing and removing the cookie. Map home/reset returns to the saved coast. Blocked or inaccessible cookies allow the chosen view for the visit, without claiming it was remembered. Preferences contain no identity or precise device location. Static homepage responses remain identical across visitors, preserving cache isolation and the existing304 fix.

Boat summaries prioritize forecast wind/seas; shore summaries prioritize tide and local modeled swell; spear summaries prioritize dated visibility and buoy temperature. Missing/stale visibility stays unknown, missing nearshore models stay unknown, and future days do not inherit buoy observations as forecasts. Original source clocks and data gates remain intact. Outside SLO, local report coverage remains explicitly unavailable with a separately labeled SLO reference.

Checks so far: all229 Node tests, both TypeScript configurations and build passed. Actual local desktop first arrival, Avila/spear save and return, mobile edit and Monterey/shore coverage passed. Entry graphics are decorative contour artwork, not geographic data. Remaining: final local edit/remove/shared-link/home-button checks, exact CI and authorized live publication/readback.

### Complete: first-visit preferences published

Implementation `a6863e8537fe0d8939f536c50303856d57bfe072` passed exact CI `37562247580` (all229 tests, both TypeScript configurations and build), and deployed as Cloudflare version `4dd172ce-e3c5-4235-9c06-494c4864a9e1`. Live HTML/client/styles match the clean build exactly. Live privacy text, original security headers, conditional304 and health/report/full-report endpoints passed. Requests with and without the preference cookie receive identical static HTML; no visitor-specific server cache variant is created.

Actual desktop1280×800 and mobile390×844 flows passed: first arrival waits for choices before creating the map canvas; Avila/spear saves and returns directly with Cabezon and60ft habitat depth; mobile edit changes to Morro/boat with Lingcod and300ft depth; method summaries display relevant original data and unknown gaps. Removing the saved test home restores entry on the next visit. No console warnings/errors or mobile horizontal overflow were observed. Test production preferences were removed so the browser is ready for the user's own selection. Detailed evidence is in `research/home-preferences/publication-verification.json`; screenshots are in the ignored local artifacts directory.

The requested entry and personalized home are complete and live at the existing Fish Worker URL. Non-SLO local forecast integration remains the previously documented data gap. This final evidence commit changes documentation only.

## Subagent coast artifact cleanup · October 6

Objective: inspect the maps across the corridor and remove visible rendering defects such as the supplied Morro Rock/harbor block and stripe screenshot. Two independent subagents reviewed numeric terrain/rendering and eight representative coast locations in both perspectives. Findings and17 baseline screenshots are saved in `artifacts/corridor/visual-audit/`.

Confirmed causes: raw coarse source2 land context has repeated height steps inside fine Morro lidar gaps; original cross-source differences exceed40m; mixed-resolution neighbors previously skipped seam matching; closed tile borders retained deep skirts; visual water clipping used raw elevations despite display morphs; a single center-selected aerial image could leave parts of a rendered tile without fallback.

Changes in review: bounded coarse-context presentation filtering and fine-support joins; deterministic neighbor welding including mixed-detail and same-detail edges; closed-skirt withdrawal; separate displayed height for water/color/contours while original sourceHeight and native inspection remain unchanged; per-fragment overview imagery fallback and96m detail-edge blend; suppress mixed-source contour interval artifacts. Original terrain assets, habitat inputs, masks, source dates and raw heights are unchanged. All235 current tests and both TypeScript checks pass.

Remaining: inspect the completed context filter in the actual close Morro view; check Arguello and a northern coast; publication, exact CI, live readback and saved acceptance. Broad source/imagery gaps require better original datasets and are not claimed repaired by smoothing.

### Primary defect verified locally

The first boundary-only repair did not remove Morro Rock's interior cubes. Independent review identified512 large same-source2 steps in the repeated coarse raster. A bounded32m same-source context filter now removes the dominant staircase, before joining nearby fine measurements. The actual final close3D screenshot shows a continuous Rock summit and western slope; the independent visual reviewer confirms the primary checkerboard is gone. Full native survey/lidar vertices stay raw. Original height and mask hashes match in12 actual test grids. At4m Rock-east context, >20m context edges fall206→0; west549→4. Residual sharp joins and coarse shore facets are retained rather than claiming new measurements.

Decoded immutable grids reuse their filtered display arrays during relief/seam redraws. Decorative curtain skirts are disabled from first tile display and remain disabled across detail/relief changes. Native inspection excludes skirt geometry and still returns original data.

All237 Node tests, both TypeScript configurations and production build passed. Actual close Morro3D and2D checks have no console warnings/errors. Arguello's genuine imagery gap remains context; the imagery renderer now uses an overview fallback for supported pixels and feathers detail edges. Publication and final live readback remain.

### Live cleanup verified

Implementation `4ac5e0cabb369c97beba5db639856b855fda347a` passed exact GitHub CI `37563678743` (237tests, both TypeScript configurations and build), then deployed as Cloudflare version `27277b92-688b-404b-8859-cf5c6a6a86f7`. Live homepage/client/styles match the clean build. The unchanged regional manifest and original2m Morro terrain binary match their original hashes. All public/data assets are unchanged versus the preceding implementation. Original security, conditional304, health/report and full report passed.

Actual live desktop1280x800 and phone390x844 show the Rock as a continuous surface rather than repeated cubes. Both perspectives render; selecting the Rock returns original USGS3DEP context (117ft elevation at35.36999N120.86905W), with original datum/precision limits. Phone map remains610px tall with no horizontal overflow. Browser logs contain no warnings/errors. Original terrain and habitat data remain intact.

A diagnostic correction to the baseline audit: PointSur's pale offshore speckles disappear when the habitat layer is disabled. These are original habitat polygons and were intentionally retained. Remaining broad shore bands, coarse native shore facets and genuine imagery gaps are documented; the release does not claim the entire coastline is artifact-free. The primary supplied MorroRock defect, tile closure and imagery fallback/blending are repaired. Future data priorities and the repeatable subagent map review are saved in the project docs. Evidence: `research/visual-cleanup/publication-verification.json`. This final evidence update changes documentation only.
