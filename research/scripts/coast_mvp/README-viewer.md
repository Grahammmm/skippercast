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
    pnpm check
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

## Upstream integration remains separate

Per the conductor's explicit fixture admission on t_fee137be, no live cache or
C1/C2/C4/C5 file is read/mutated here. C1 t_229826b7 and C5 t_27a764f7 are now
reviewed upstream work, but neither is a terrain-RGB/MVT viewer export. This
fixture is NOT an adapter for C1's EPSG:3310 COG nor C5's rights schema.

The integration lane must consume admitted C2 tile exports and adapt the C5
`schema_version=1` source inventory (`source_id`, `name`, `source_url`, sha256,
`contributed_cells`, explicit `rights {license, terms_url, attribution,
csumb_involved}`), keeping only actual contributors and all rights flags.
Preserve C5's needs_permission/GEBCO/no-endorsement conditions and link its
complete rights page. Do not infer commercial permission or equate a fixture
licence with a real source's licence. Do not import research tooling from
product code. C6 region look + redaction/rights/review gates still precede any
publication. No R2 upload, source download, merge or deploy is performed here.
