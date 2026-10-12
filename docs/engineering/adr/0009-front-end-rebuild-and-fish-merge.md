# 0009. Front end: rebuild the shell on ADR 0005's stack behind a flag, self-host the basemap, and merge `fish`

- **Status:** Accepted (2026-10-05; the owner accepted by approving the front-end plan, PR #353, and FE-01 records it here and in ADR 0005)
- **Date:** 2026-10-05

## Context

- ADR 0005 proposed Vite + TypeScript + Preact with MapLibre GL and PMTiles
  and has stayed Proposed since 2026-09-29. Since then Vite builds the
  pages, five Preact islands exist, and MapLibre and PMTiles are vendored
  but used only by a test page and the seafloor reader. The live map is
  still Leaflet over OpenStreetMap raster and the NOAA ENC WMS.
- The app shell is `dist/index.html` (605 lines, three dialogs, 41
  controls in the Options dialog, about a dozen floating panels) with 22
  stylesheets holding 377 distinct hex colours and few token uses; a
  blocking home-port modal precedes the first map.
- The owner's `fish` repository built a second product on SkipperCast's
  data exports with a MapLibre map, canvas fields with animated
  streamlines, gap-aware charts, a profile-aware brief (boat, shore, spear)
  and data sources SkipperCast lacks (nearshore wave model, beach health,
  buoy history with seasonal bands, sandy-shore runs and access points,
  cloud frame loop, aerial imagery). It is single-county, dark only, with
  hard-coded colours and one 2,942-line stylesheet.
- The owner chose concept A (Bridge) for the app and concept D (Open water)
  for the landing, one visual system, and the merge and retirement of
  `fish` ([docs/plans/front-end/](../../plans/front-end/README.md)).

## Decision

1. **Adopt ADR 0005** as written: Vite + TypeScript + Preact + signals for
   the shell, MapLibre GL + PMTiles for the map, URL state as the source of
   truth with no reload on region change. MapLibre and PMTiles become npm
   dependencies bundled by Vite for the new pages.
2. **Build the new shell beside the old one** as two new pages
   (`dist/landing.html` at `/`, `dist/app.html` at `/map`) served by the
   Worker only when the runtime variable `UI_V2` is true or the request
   carries `?ui=v2`; `?ui=v1` forces the old shell. The old shell is deleted
   one release after the flag defaults on.
3. **One visual system** in `web/tokens.css` (dark default, light defined),
   DM Sans and JetBrains Mono self-hosted, a lint that fails on colour
   literals in `web/`, and the contrast check in CI.
4. **Self-host the basemap**: a Protomaps extract of the coastal region
   bounding boxes as one PMTiles archive on R2, served through `/feeds/`,
   styled from the tokens; the ENC chart stays as an optional raster base.
5. **Merge `fish` by porting, not pasting**: its map rendering, charts,
   brief, profile semantics and relief pipeline become typed modules in
   `web/` and `src/skippercast/`; its data sources become SkipperCast
   collectors with catalog entries and data-rights rows; its docs and
   research receipts are archived under `docs/archive/fish/`; the owner then
   archives and deletes the repository.

## Consequences

- (+) One typed shell, one token system, one map engine; the measured
  Leaflet slowness on dense layers goes away; the first-time visitor sees
  live data on a real map at once.
- (+) The flag makes every step reversible; `main` stays deployable.
- (+) `fish`'s capabilities survive in a maintained code base with regions,
  accounts, pipelines and tests; one repository to run.
- (–) Two shells exist for several weeks; shared modules are wrapped rather
  than edited, and tests that import `dist/*.js` constrain deletions.
- (–) A basemap build and R2 archive to refresh; a few new collectors to
  monitor.
- (–) Every screen needs re-verification on phones; the copy lint baseline
  must shrink, never grow.

## Alternatives

- **Migrate in place inside `index.html`**: no flag, but every task risks
  the live site and mixes two visual systems on one page.
- **Hosted vector tiles**: no build step; a key in the client, caps and
  terms outside our control. Kept as the fallback if the extract is too
  large.
- **Keep `fish` as a second product on the same data**: two code bases, two
  Workers, two sets of gates for one owner.

## Addendum (2026-10-07): integrating `packages/coast`

The status above is unchanged. Between 2026-10-06 and 2026-10-07 Codex
merged `fish`'s client into SkipperCast as `packages/coast/` (#385 and
follow-ups), mounted it in the v1 page as terrain presentations (#392),
added the local report and history to v1 Conditions (#393), a bounded
bridge to the Fish Worker (#381), readable report, RSS and information
routes (#395), Fish link aliases in the shared store (#379, #396), one
surface-current choice (#402) and offline snapshots (#405). The renderer is
Three (`three` 0.180 from npm); its 2D is a camera-only top-down view, and
`packages/coast` contains no MapLibre code. Details are in
[design § 3A](../../plans/front-end/design.md#3a-integration-with-packagescoast-2026-10-07).

This amends the decision as follows:

1. **One shell.** The v2 Bridge shell (`web/app/`) remains the single
   public shell for FE-60. Its map stage has three presentations of one
   place, camera, selection and hour: **Chart** (MapLibre GL + PMTiles, as
   decided in item 1, every region) and **Terrain 2D / 3D** (the
   `packages/coast` renderer, where terrain exists). The v1 chart, the v1
   coastal overview and `/coast` retire with the v1 shell.
2. **Item 1** stands for the Chart presentation. `three` joins the npm
   dependencies for the Terrain presentations and loads only by dynamic
   import.
3. **Item 5** is amended: "porting, not pasting" happened as the typed
   `packages/coast` package rather than modules in `web/`. v2 imports its
   models, field mathematics, frame gates and markup instead of porting them
   a second time. The PNG relief pipeline and proxy (plan FE-13, FE-26) are
   dropped: the renderer's SHA-verified terrain is the relief. The `fish`
   collectors still move into SkipperCast before `fish` retires, now with
   output shaped as the `packages/coast` types so the bridge's upstream can
   switch without a client change.
4. **Item 3** extends to `packages/coast` through a token bridge
   (`--coast-*` properties mapped to `web/tokens.css` under an opt-in, with
   today's literals as fallbacks so v1 pages keep their look) and a
   shrink-only token-lint baseline for the package.
5. **One controller.** `web/state.ts` is the single URL, profile and time
   store for both shells; it gains `presentation`, `current` and `habitat`,
   and `web/fish-links.ts` stays the only alias table.

Consequences added: (+) the terrain the owner chose survives with its
evidence gates, and v2 drops a relief pipeline; (+) no second port of
`fish` code. (–) Both agents edit `packages/coast`, `web/state.ts` and the
Worker routes, so the shared files have rules (design § 3A.6) and a
coordination issue; (–) the renderer needs a host-chrome mode (plan FE-79)
before the v2 rail can own its controls; (–) the Fish Worker remains a live
dependency until the collectors and assets move (plan FE-84, FE-85).
Ownership of each side is proposed in
[open-questions Q14](../../plans/front-end/open-questions.md#q14-ownership-boundary-between-the-v2-shell-and-packagescoast)
for the owner to decide.

## Links

- ADR 0005; [docs/plans/front-end/](../../plans/front-end/README.md)
  (design § 3, § 4, § 5, § 14, § 15); `fish/NOTICE.md`; PRs #10, #35, #47,
  #88 cited by ADR 0005.
