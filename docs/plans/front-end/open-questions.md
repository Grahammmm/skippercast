# Open questions for the owner

Each section is one decision the plan had to make on the owner's behalf, or
one that only the owner can make (money, terms, what the public sees, the
`fish` repository). Options are ranked, best first, and the pick is marked
**(recommended)**. Until the owner answers, the build follows the "Plan
assumes" line; the owner overrides by saying so, and the change lands as a
PR that edits this file and the affected dev-plan tasks. Task ids (FE-xx)
refer to [dev-plan.md](dev-plan.md); section numbers to [design.md](design.md).

## Q1. Basemap source

**Context.** The Bridge look needs a quiet vector basemap under relief,
fields and marks. Today the app uses OpenStreetMap raster tiles and the NOAA
ENC WMS. Numbers are estimates until FE-10 measures (§ 4).

1. **Self-hosted Protomaps extract on R2 behind `/feeds/` (recommended).**
   Built on Hermes with `pmtiles extract` (range reads, no planet
   download); about 0.3–2 GB on R2 at cents a month, egress free, origin
   reads edge-cached. One style file in the tokens, day and night variants.
   Risk: build size; mitigated by lowering maximum zoom in preview regions.
2. A hosted vector service (MapTiler Cloud, Stadia, Protomaps API) on a
   free tier with attribution. No build step, but a key in the client,
   request caps and terms that can change.
3. Keep OpenStreetMap raster and the ENC WMS. Zero work; fights the dark
   instrument look, outside our control, and OSM discourages heavy
   production use of its tile servers.

**Owner action:** add the `protomaps-basemap` register row; B6 marks OpenStreetMap commercial use unknown for the tile service, and the self-hosted ODbL extract needs its own confirmation.
**Plan assumes:** option 1 (D10, FE-10). The ENC chart stays as an optional
raster base.
**Blocks:** nothing; FE-10 reports the measured size and this file is
updated if it exceeds 5 GB.

## Q2. URL structure for the landing and the app

**Context.** Shared links today are `/?region=…&view=…#map`. The landing
must be the first thing a new visitor sees, and a returning visitor must
skip it.

1. **`/` landing, `/map` app; `/` with area parameters serves the app;
   saved port redirects from the landing's first module (recommended).**
   Every old link keeps working, the landing has the root URL for search
   and sharing, and the app has a clean path for the service worker.
2. One shell at `/` that renders landing or app from client state. Simpler
   routing, but the landing's first paint carries the app bundle and
   search engines see one mixed page.
3. Landing at `/welcome`, app at `/`. Returning users never redirect, but
   the first-visit URL is the one nobody shares, and the root stays the
   console.

**Plan assumes:** option 1 (§ 7, FE-01, FE-08).
**Blocks:** nothing.

## Q3. Light theme timing

**Context.** Both concepts are dark. `dist/tokens.css` today is light by
default with an inactive dark set; the rebuild inverts that. A light set is
cheap to define and expensive to verify on every screen.

1. **Dark default; a light set defined in `web/tokens.css` and checked for
   contrast from FE-02, with the switch as a backlog task after FE-61
   (recommended).** Keeps every Phase 0–4 task on one theme.
2. Ship the light switch in Phase 0. Doubles the visual checks of every
   later task.
3. Dark only, no light tokens. Cheapest now; costs a full token pass later.

**Plan assumes:** option 1 (§ 5, backlog in dev-plan).
**Blocks:** nothing.

## Q4. Keep the Leaflet build alive during the migration

**Context.** Phases 0–4 take weeks; the public site must keep working and
the Node tests import `dist/*.js` directly.

1. **Two shells side by side behind `UI_V2`; v1 untouched; shared modules
   wrapped, not edited; v1 deleted in FE-61 one release after the flip
   (recommended).** Safe rollback at every step; costs a short period of
   two code paths.
2. Migrate in place, one panel at a time, inside `index.html`. No flag, but
   every task risks the live site and mixes two visual systems on one page.
3. Freeze v1 and build v2 on a separate branch, merge at the end. One big
   merge, reviews lose their value.

**Plan assumes:** option 1 (§ 3, § 14).
**Blocks:** nothing.

## Q5. NAIP aerial imagery: live tiles or stored

**Context.** `fish` requests NAIP tiles live from the USGS ImageServer
(public domain, attribution). The service is outside our control and slow at
times; storing a mosaic for one region at zooms 12–16 is roughly 0.5–2 GB.

1. **Live tiles from the fixed USGS host, off by default, with the
   attribution line; no storage (recommended).** Zero cost and zero
   pipeline; a slow day degrades an optional base only.
2. Cache tiles on R2 as they are requested (a Worker tile proxy). Faster
   repeat views; adds a proxy route, cache rules and storage that grows.
3. Build a region mosaic as raster PMTiles on Hermes. Fastest and
   offline-capable; a GB-scale artefact per region and a build to maintain.

**Plan assumes:** option 1 (§ 9 Aerial, FE-23, FE-45).
**Blocks:** nothing. Revisit if the owner wants aerial in the offline pack.

## Q6. How fleet layers appear publicly

**Context.** Charter fleet activity is built and dark behind
`FLEET_ENABLED` and `FLEET_MAP_ENABLED` (admin only). The Bridge rail has a
"Charter fleet" entry and the landing's readout has a fleet line.

1. **Keep the gating exactly as today: the rail entry and the Fleet view's
   activity part render only for an admin with both flags on; the public
   Fleet view shows charter grounds, the 2024 commercial AIS option and,
   when `FLEET_ENABLED`, the boat directory link; the landing's fleet line
   is the seven-day report count from landing reports (recommended).**
   The rebuild widens nothing; the owner flips the fleet flags separately
   per the charter-fleet plan's Q8.
2. Show aggregate fleet heat publicly in v2 with the privacy knobs on.
   Needs the charter-fleet plan's Q8 answered and the aisstream terms.
3. Hide every fleet mention from the public shell until the flags flip.
   Loses the charter grounds and AIS 2024 layers the public already has.

**Plan assumes:** option 1 (§ 9, FE-24, FE-53).
**Blocks:** nothing.

## Q7. One type family on the landing

**Context.** D6 sets DM Sans plus JetBrains Mono for the app and DM Sans
only at display weight for the landing. The landing's readout strip shows
numbers.

1. **DM Sans only on the landing, with `tabular-nums` for the readout
   numbers; the app keeps the mono for readings (recommended).** Matches
   the brief, one font file on the first paint, and the readout stays
   aligned.
2. Load the mono on the landing too for the readout. One more font on the
   critical path for a strip of six numbers.
3. DM Sans everywhere, drop the mono. Loses the instrument feel of the app's
   readings and ages.

**Plan assumes:** option 1 (§ 5, FE-02, FE-07).
**Blocks:** nothing.

## Q8. Rights of the Coastal Commission inventory and the county beach feed for a paid product

**Context.** `fish` uses California Coastal Commission access points (facts
only: names, ids, coordinates, links) and SLO County beach health statuses.
Both are public pages; neither publishes a commercial-use licence the plan
could cite. D16 puts their rows in `docs/legal/data-rights-register.md`,
which is owner territory.

1. **Add both rows as "facts only; commercial use: owner to confirm" and
   keep them in `KNOWN_BLOCKERS` until confirmed (recommended).** The
   contract test stays honest and the layers can ship in the free edition.
2. Ask both agencies before FE-41 and FE-43. Delays shore features for an
   answer that may be slow.
3. Leave both sources out. Loses the shore profile's access points and the
   beach notices.

**Owner action:** add the rows (§ 11 table) and decide whether to write to
the agencies.
**Plan assumes:** option 1.
**Blocks:** nothing in the build; blocks removing the two sources from the
launch blockers.

## Q9. Accepting the ADRs

**Context.** ADR 0001 says an ADR that needs the owner stays Proposed until
the owner accepts it in the PR or an issue, and agents never mark it
Accepted themselves. ADR 0005 is Proposed; the brief says the owner adopts
it via this plan.

1. **The owner's approval of this plan PR is the acceptance; FE-01 flips
   the status lines of ADR 0005 and ADR 0009 to Accepted, citing the PR
   (recommended).** One owner action, recorded where ADR 0001 wants it.
2. The owner edits the status lines in this PR before merging. Same
   result, more owner typing.
3. Leave both Proposed until FE-60. Builders would implement a Proposed
   decision for months.

**Owner action:** approve this PR (or comment "accept ADR 0005 and 0009").
**Plan assumes:** option 1.
**Blocks:** FE-01's ADR edit only.

## Q10. `slofishreport.com` after `fish` is retired

**Context.** `fish` served SLOFishReport.com from its own Worker. After
FE-62 the content lives in SkipperCast.

1. **Redirect the domain (301) to `skippercast.com/map?region=morro-bay&profile=shore`
   from Cloudflare DNS rules, and keep the domain registered for a year
   (recommended).** Keeps any inbound link working at no build cost.
2. Serve SkipperCast under the second hostname with a county landing.
   Two brands for one product; a hostname registry in the Worker.
3. Let the domain lapse. Loses inbound links.

**Owner action:** set the redirect rule when FE-62 merges.
**Plan assumes:** option 1; nothing in the build depends on it.
**Blocks:** nothing.

## Q11. MapLibre and PMTiles as npm packages or vendored files

**Context.** v1 vendors both under `dist/vendor` with SRI; `fish` imports
them from npm. The CSP has no CDN origin either way.

1. **npm packages bundled by Vite for v2 pages; the vendored copies stay for
   v1 until FE-61 (recommended).** Typed imports, tree shaking, one
   version, and the lockfile pins the bytes.
2. Keep vendoring and import from `dist/vendor` in v2. Keeps SRI on a
   separate tag, but blocks tree shaking and typed imports.

**Plan assumes:** option 1 (§ 3, FE-11).
**Blocks:** nothing.

## Q12. The `?ui=v2` switch: query parameter or cookie

**Context.** The site sets no cookies for visitors (cookie-less telemetry).
A preview switch could persist in a cookie or travel in the URL.

1. **Query parameter only; it applies to that request and the links the
   shell writes (recommended).** No cookie, shareable preview links, no
   silent persistence.
2. A `sc-ui` cookie set by `?ui=`. Persists across pages, but the site
   gains a cookie and the privacy page needs a line.

**Plan assumes:** option 1 (§ 14, FE-01).
**Blocks:** nothing.

## Q13. Relief tiles for preview regions

**Context.** FE-13 and FE-26 port the PNG PMTiles pipeline and proxy and publish Morro Bay
from the three approved USGS grids. The fourteen preview regions have
seafloor candidates but no relief archive.

1. **Morro Bay only in this plan; each further region is a data task with
   its own approved grids (recommended).** Keeps the rebuild's scope to the
   active region.
2. Publish relief for every region with a USGS grid in `catalog/sources.json`
   now. Several GB of builds and reviews before the shell exists.

**Plan assumes:** option 1 (dev-plan backlog).
**Blocks:** nothing.
