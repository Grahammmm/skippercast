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

## Upstream integration remains separate

Per the conductor's explicit fixture admission on t_fee137be, no live cache or
C1/C2/C4/C5 file is read/mutated here. C1 t_229826b7 and C5 t_27a764f7 are now
reviewed upstream work, but neither is a terrain-RGB/MVT viewer export. The
default fixture is NOT an adapter for C1's EPSG:3310 COG; the C5 rights adapter
is described below.

The integration lane must consume admitted C2 tile exports and adapt the C5
`schema_version=1` source inventory (`source_id`, `name`, `source_url`, sha256,
`contributed_cells`, explicit `rights {license, terms_url, attribution,
csumb_involved}`), keeping only actual contributors and all rights flags.
Preserve C5's needs_permission/GEBCO/no-endorsement conditions and link its
complete rights page. Do not infer commercial permission or equate a fixture
licence with a real source's licence. Do not import research tooling from
product code. C6 region look + redaction/rights/review gates still precede any
publication. No R2 upload, source download, merge or deploy is performed here.

## C5 rights adapter (t_68a03f26, fixture acceptance only)

`adaptC5Rights` in `packages/coast/src/coast3d/mvp-rights.ts` turns a C5
`schema_version=1` inventory plus a C3 tile base into a presentation manifest.
It re-applies C5's contributor rules in product TypeScript (it does not import
`research/`): `contributed_cells` must be a nonnegative integer (missing, string,
boolean or fractional usage fails); only rows with `contributed_cells > 0` are
kept; each kept row needs name, HTTPS `source_url`, lowercase sha256 and a
complete `rights` object with an explicit boolean `csumb_involved`. Any failure
rejects the whole inventory. Name, credit, licence, hash, terms link and cell
count are copied verbatim. Per-source datum/spacing is not in the C5 schema, so
it is `null` and the tile export's datum/spacing comes from the tile base.

Permission is never inferred. Every row is `review_required`; CSUMB rows (flag
true, or CSUMB / Seafloor Mapping Lab / California State University, Monterey
Bay named in any field) become `needs_permission`. The manifest carries the
not-for-navigation, review, no-endorsement (GEBCO/IHO/IOC), CSUMB and GEBCO
caveats, the inventory's byte SHA-256 and a relative link to the complete C5
rights page. `validateMvpManifest` rejects an adapted manifest that drops a
CSUMB hold, invents one, loses a hash, terms link or required caveat, mixes in
unadapted rows or points the rights page off-directory. The rights page path
must pass `isLocalAssetPath`: the raw token must be a plain relative path of
`[A-Za-z0-9._-]` segments joined by `/` (so no scheme, `?`, `#`, `%`,
backslash, whitespace or control character that the URL parser would strip or
rewrite), and it must then pass the viewer's own `localAsset` rule. Traversal
(including encoded dot segments), query/fragment, absolute, scheme-qualified
and remote paths, and padded or tab/CR/LF-bearing names fail in the
adapter, the validator and the CLI alike; nothing is normalised. The CLI also refuses an `--output`
that resolves to the linked rights page (or an input), before writing anything.
The viewer shows the
unresolved permission in the persistent banner, outside the collapsible panel.

Reproduce (the C5 page is built by the unmodified C5 tool from PR #828 at
399731982d1d, read with `git show`; nothing in the C5 branch is changed):

    git show 399731982d1d1413a63e14a0ee1cd52538250a3b:research/scripts/coast_mvp/coast_rights.py > /tmp/coast_rights.py
    python3 /tmp/coast_rights.py --manifest research/scripts/coast_mvp/fixtures/rights-adapter/inventory.json \
      --output research/scripts/coast_mvp/fixtures/viewer-demo/rights.html
    node research/scripts/coast_mvp/adapt_rights.mjs \
      --inventory research/scripts/coast_mvp/fixtures/rights-adapter/inventory.json \
      --tile-base research/scripts/coast_mvp/fixtures/rights-adapter/tile-base.json \
      --rights-page rights.html --output research/scripts/coast_mvp/fixtures/viewer-demo/rights-adapted.json
    node --test tests/test_coast_mvp_rights.mjs
    C3_SCREENSHOTS=/absolute/task-owned/output node research/scripts/coast_mvp/capture_rights.mjs

The inventory is synthetic (`fixture_only: true`, repeated-digit hashes, invented
cell counts) and reuses the existing C3 synthetic tile; no tiles were generated.
The adapter writes atomically and leaves the previous manifest on failure. The
browser capture (`?manifest=rights-adapted`) checks that every attribution,
licence, hash and link survives, that unused rows are absent, that the banner
still shows `needs_permission` with the panel collapsed, and that the linked C5
page pins the same inventory hash. Evidence: `viewer-evidence/rights-*.png` and
`rights-acceptance.json`. Real C1/C2 exports still need coordinator admission;
none were read or reproduced here.
