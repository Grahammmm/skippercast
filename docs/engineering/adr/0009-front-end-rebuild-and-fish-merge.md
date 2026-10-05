# 0009. Front end: rebuild the shell on ADR 0005's stack behind a flag, self-host the basemap, and merge `fish`

- **Status:** Proposed — owner decision required (the owner accepts by approving the front-end plan PR; FE-01 then records Accepted here and in ADR 0005)
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

## Links

- ADR 0005; [docs/plans/front-end/](../../plans/front-end/README.md)
  (design § 3, § 4, § 5, § 14, § 15); `fish/NOTICE.md`; PRs #10, #35, #47,
  #88 cited by ADR 0005.
