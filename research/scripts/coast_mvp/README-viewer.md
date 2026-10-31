# C3 local viewer (fixture acceptance only)

Not for navigation. Synthetic demonstration, not measured Central Coast bathymetry.
Review required; no semantic acceptance, commercial clearance or publication.

`CoastMvpViewer` is an explicitly selected local viewer, exported by
`packages/coast/src/coast3d/viewer.ts`. The existing Three.js `CoastViewer`,
production routes and its custom binary regional release are unchanged. The
MVP uses the already-pinned MapLibre dependency to decode standard terrain-RGB
and MVT and drape the contours on exaggerated 3D terrain; it does not convert
upstream rasters or duplicate C1/C2 work. A local Vite page is the only entry.

## Reproduce

From the repository root, using Node >=22.18 and the existing pnpm toolchain:

    pnpm install --offline --frozen-lockfile
    python3 research/scripts/coast_mvp/make_viewer_fixture.py
    pnpm typecheck
    node --test tests/test_*.mjs
    pnpm build
    pnpm exec vite --config research/scripts/coast_mvp/vite.viewer.config.mjs

Open http://localhost:5179/research/scripts/coast_mvp/viewer-preview.html.
The preview sets MapLibre 6's module worker URL with Vite's `?worker&url`;
production consumers must use their own existing MapLibre worker bootstrap.
The preview server binds localhost only, serves the task checkout, and does not
start/restart any existing service or use the live cache. Stop it after use.

With that server running, in a separate terminal:

    C3_SCREENSHOTS=/absolute/task-owned/output node research/scripts/coast_mvp/capture_viewer.mjs

This runs real headless Chromium/SwiftShader, blocks non-local page requests,
checks both tile formats return 200, verifies negative decoded terrain elevation
(dividing out display exaggeration), queries decoded MVT features at each of
three camera poses, verifies warnings/attribution, and proves hiding contours
changes canvas pixels. Output includes three actual screenshots and a JSON
receipt recording actual cameras, decoded feature counts, elevation, requests
and page errors. Feature counts can include renderer subdivisions; they are not
counts of distinct input contours. The Python fixture has 43 distinct contours.
Screenshots are not scientific QA or C6/G visual acceptance.

## Explicit fixture interface, not a canonical manifest

`fixtures/viewer-demo/manifest.json` is a C3-only presentation manifest, validated
in product TypeScript. Required fields are typed by `MvpManifest` in `mvp.ts`:

- `schemaVersion: 1`, region, synthetic boolean; WGS84 bounds and center.
- Camera zoom, XYZ tileZoom, tileSize (256 or 512), relative terrain/contours
  templates (`{z}/{x}/{y}.png` and `.mvt`), and contourLayer.
- Every used source: unique id, label, source URL (HTTPS or null for a fixture),
  explicit attribution, license, datum, resolutionM, permissionRequired.
- Terrain uses Mapbox terrain-RGB: elevation m = -10000 + (R*65536+G*256+B)*0.1.
  The MVT layer is `contours`, with numeric `depth_ft` positive down. Every
  100-ft line is emphasised. No remote styles, glyphs, sprites or basemap.

Attribution uses text nodes, never manifest HTML. Missing rights fails loading;
unresolved for-profit permission is visibly flagged. The warning is persistent,
not inside the collapsible source panel. A non-synthetic manifest is still
explicitly labelled unreviewed. No schema field grants publication clearance.

The generator is stdlib-only and deterministic. It creates one XYZ tile at
12/671/1616 with an analytic slope and waves; datum is arbitrary, not geodetic.
A single finite tile can show its coverage boundary/skirt when zoomed far out
or tilted toward the edge. The initial view and three acceptance views stay
inside it; source spacing remains 31.1 m regardless of camera zoom. It does not
model a coastline, repair holes or claim source continuity.

## Load a local W11A adapter manifest

W11B now validates and displays the optional W11A provenance/rights group.
The original fixture remains the default. With the local server running, open:

    http://localhost:5179/research/scripts/coast_mvp/viewer-preview.html?manifest=var/w11b/c2/viewer-manifest.json

The `manifest` parameter must be a repo-root-relative `.json` path; remote URLs,
absolute paths, traversal, encoded separators, query strings and fragments are
rejected. Tile paths stay under the manifest directory. Generate the adapter
manifest locally using `README-manifest.md`; this page acquires no sources.
For synthetic adapter browser evidence, use:

    C3_MANIFEST=var/w11b/c2/viewer-manifest.json C3_SCREENSHOTS=var/w11b/adapter node research/scripts/coast_mvp/capture_viewer.mjs

The panel shows source terms links, datum notes, rights status, navigation and
limitations. The additive group is all-or-nothing: malformed hashes, missing
provenance and cleared publication flags fail loading. Measured previews also
require every source's permission hold, even without the additive group.
CSUMB-involved contributors remain `needs_permission`; unknown terms remain
held. Hashes pin supplied bytes, not scientific or legal acceptance. C6 region
look + redaction/rights/review gates still precede publication. No source
download, live cache, R2 upload or production route change is part of this path.

## Production release manifests (M9, off by default)

Production loads only a release manifest (`admitRelease` in `mvp.ts`): reviewed,
no `publicationHeld` key, a navigation notice, limitations, provenance and every
source cleared with a `catalog/sources.json` `catalogId`, else it is refused with
its reason before any tile request; regions are listed in `web/map/c2-releases.ts`
(off, empty). The preview loads held manifests only; no producer writes `reviewed`.
