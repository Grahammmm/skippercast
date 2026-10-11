# Changelog

- Preserve original classified-habitat source files in per-reach recovery so a clean publishing worker can verify them; report publication failures with code locations without logging data or exception payloads.

- Extend the reviewed San Simeon bedrock outlines across the remaining eligible native SCC03 footprint, retaining uncertain terrain and nonexportable area labels.

- Separate measured reef trip exports from research-coordinate references with explicit session opt-in and per-point evidence labels; preserve saved selections and all spatial/publication checks.

## Unreleased

- In the new map preview (`?ui=v2`), the Conditions view shows the seven-day forecast as one stacked chart (wind, gusts, offshore seas, air and cloud from the NOAA or ECMWF models, plus nearshore waves and the tide curve where a local coast report covers the area), a summary for the selected hour, each source's clock, the day's tide events and the profile's before-you-go notes with the CDFW rules link. Dragging the chart moves the hour the map and the time dock show; on a phone the chart scrolls sideways.
- In the new map preview (`?ui=v2`), the brief's "Where to look" lists the top four places inside the profile's depth limit, with distance from the harbor, nominal depth range, habitat fit and one terrain reason: the reviewed coastal terrain habitat where it covers the region, else the survey reef atlas marks that pass the protected-area check, each list labelled by its source and never mixed. Tapping a place selects it on the map and opens its card. A ranked place is a place to look; fish presence is unverified.
- In the new map preview (`?ui=v2`), the brief column and the phone sheet now show the day's brief from the region's daily feed: the headline and summary, the Wind, Swell, Water and Tide tiles with their source and age (a reading past its limit is marked stale and says how old it is; a missing one reads unavailable), the lower-exposure window, the profile's caveat, a beach notice and fleet line when there is one, and whether a local coast report covers the area.

- In the new map preview (`?ui=v2`), the Shore profile draws Morro Bay's NOAA ESI 2006 sandy-shore runs on the Chart with their public access points. Each run is ranked by its access and rules review clocks, the protected-area check and whether a fresh nearshore model sample covers its area; an expired review holds it, a run inside a protected area is blocked, and its card shows the review dates, method guidance and the official CDFW rules link. The ranking orders places to check; fish presence is unverified.
- In the new map preview (`?ui=v2`), Terrain 2D and 3D no longer show the classic terrain panels: seabed relief, water, depth contours, source coverage and reefs and pins are options of the Seafloor layer, a tapped terrain reading or reef opens the shared card with its measured or modelled label and source date and a link to the terrain sources, and zoom, reset and top view sit with the map's zoom buttons.
- Charter fleet admin: the outreach lead score's landing-report volume and reporting-frequency inputs now fill in, because each AIS processing run pairs a boat's trips with its published skipper reports and with the daily landing reports for the same boat, port and day (#345).
- In the new map preview (`?ui=v2`), an admin whose fleet flags are on gets the classic map's fleet activity layers under Charter fleet (activity stops, trip tracks and heat cells, each off by default and loaded for the map's view); every card and the legend's status line say the activity is inferred from movement. Nobody else sees the options.
- In the new map preview (`?ui=v2`), Terrain 2D and 3D now show the marine protected areas, the screened reef marks and, with Charter fleet on, the charter-reported grounds, in the same colours as the Chart: tapping an area or ground opens the same card as on the Chart, and tapping a reef mark selects it. Charter fleet no longer reads "Chart only" there; commercial AIS still draws on the Chart only.
- In the new map preview (`?ui=v2`), Charter fleet draws the Morro Bay charter-reported grounds (Pecho Rock and Diablo coast) as hatched outlines, with the classic map's rules: lingcod and rockfish only, within the profile's depth, and only while the protected-area check is current; a ground's card gives its reported trips, latest report and survey depths. Its option adds the 2024 commercial AIS cells (Global Fishing Watch, July and September 2024) as a heat fill, off by default, with the same wording as the classic map: apparent activity, depth and species unknown.
- In the new map preview (`?ui=v2`), "Show ranked spots on map" now draws the trip plan's ranked reefs on the Chart as numbered pins in the planner's order, as the classic map does: nearby spots share one pin ("1 +4") that zooms in when tapped, a pin opens its card with the rank, habitat fit and evidence confidence and "Review & export", and the pins go when the plan is cleared, the protected-area check is stale or the reef data changes (#495).
- In the new map preview (`?ui=v2`), the target menu lists the profile's species, the region's species search plans that fit Boat, Shore or Spear, and, where the region has coastal terrain, the terrain's own targets, each under its own name; a target the link names that the profile does not list stays chosen.
- In the new map preview (`?ui=v2`), Swell also draws the bound coast report's nearshore model sites (CDIP MOP, Morro Bay and Cambria) as rings sized by modelled wave height, only while each site's model run is under 48 hours old and its retrieval under 3 hours, at the sample nearest the dock's hour; a ring opens the site's card with height, period, direction, the sample time and the run's age, labelled as model output, not a buoy observation.
- In the new map preview (`?ui=v2`), each profile keeps its own map layers: switching between Boat, Shore and Spear restores that profile's last choice or its defaults, and the Boat default now draws Currents (the WCOFS forecast) when a link names no source; the landing's Currents dot opens with Currents on. The rail gains one Base choice (Night, Chart detail, and Aerial where offered), so a link's chart base can be chosen again; in 2D and 3D the entries that draw only on the Chart read "Chart only" and cannot be switched, and the legend shows a colour key only while its layer draws, saying why otherwise.
- In the new map preview (`?ui=v2`), reef marks are checked again in the browser against the current protected-area boundaries and the region's closures, as the current map does: a mark inside one, or every mark while that check is unavailable or more than 36 hours old, is withheld; a linked withheld mark's card and the legend say why and link the official CDFW or NOAA page.
- A region opened on the Guide, Conditions or Export tab now shows its opening view when you choose Map. Before, the map moved by half its size, and on a wide screen near Morro Bay that could send you to the Central Coast overview instead (#496).
- In the new map preview (`?ui=v2`), Swell on the Chart draws NOAA GFS-Wave's primary swell for the dock's hour as a colour field of height (one fixed 0–15 ft scale at every hour) with dashed period lines and short strokes showing the way it travels, on Morro Bay's and Cambria's offshore forecast grid: the legend gives the hour's height, period and direction, the model run, its age and the valid hour, as a model forecast and not a buoy observation; a click reads the model there; outside the grid stays blank, and a run over 36 hours old, an hour outside the run or a region without a grid draws nothing and says why.
- In the new map preview (`?ui=v2`), a reef mark's card adds it to the trip, and the account menu opens the trip plan and GPX (the classic map's day planner, the same draft, checks and GPX bytes) and "Save for offline": the region's pack now also keeps this app and its base map at zoom 8–12, and the coastal readings save with each source's own time. The offline shell no longer stores the new map's files for classic-map visitors.
- In the new landing (`?ui=v2`), a live night map loads once the page has painted: the Morro Bay CUSP coastline glow and the latest fresh surface-current frame as animated streamlines, with the footer crediting the basemap and giving the currents' source and age. The Currents dot previews them, they stand still under reduced motion, and without WebGL the static shoreline stays. The readings strip now names the area it reads ("Morro Bay & Avila area").
- In the new map preview (`?ui=v2`), Water temp on the Chart draws the coast report's daily sea-surface temperature analysis for Morro Bay and Cambria as a colour field with half-degree Fahrenheit contours labelled at whole degrees: the legend gives the range in °F, the product (NASA JPL MUR or NOAA Geo-Polar Blended, as the report names it), the analysis date and age and the analysis error; a click reads the temperature and its error; land and missing cells stay blank, and an analysis over 72 hours old, or one whose grid cannot be drawn, draws nothing and says why.
- In the new map preview (`?ui=v2`), the Chart offers an Aerial base where the region's package lists one (Morro Bay): the USDA NAIP natural-colour mosaic served by USGS, labelled in the rail and the map credit with the dates it was flown (13–29 May 2022), never as current conditions; its tiles are requested from USGS only while Aerial is on.
- In the new map preview (`?ui=v2`), the Chart draws the atlas reef marks with their habitat fit ("fits lingcod habitat 3 of 3"), survey habitat and geology outlines; one card shows the selected mark, outline or coastal habitat with its source, age and what its build screened, and a shared `?spot=` or `?habitat=` stays the one selection across Chart, 2D and 3D.
- In the new map preview (`?ui=v2`), the Seafloor layer draws the region's screened seafloor candidates and surveyed cells on the Chart, coloured by terrain grade or the target's species fit, with a legend naming the surveys and years; a held, updating or expired publication draws nothing and says why, and a click opens a candidate's nominal depth, survey, basis and source credits.
- In the new map preview (`?ui=v2`), the Chart always outlines the region's marine protected areas from CDFW ds582 (and southern California's NOAA groundfish exclusion areas) with a faint fill and dashed edge, names them from zoom 11, and credits ds582 (CC BY 4.0). A clicked area shows its name, designation, regulation section and snapshot date, with Regulations linking the official CDFW or NOAA page. The legend gives the snapshot date, or says the boundaries are partial, incomplete or did not load, so an area without an outline is never presented as unprotected.
- In the new map preview (`?ui=v2`), Currents on the Chart draws the chosen surface-current source as dashed, animated streamlines for Morro Bay and Cambria (the local WCOFS forecast or HF radar packet): the rail's source select sets `?current=`, a click reads speed and direction with the frame's time and age, land and gaps stay blank, a missing frame draws nothing and says why with the last valid time, and the motion stops when the page is hidden and stands still under reduced motion.
- Publish the Morro Bay region's ESI 2006 sandy-shore runs and Coastal Commission beach approaches as a candidate region file (reviews pending owner confirmation), with dated source, access and rules reviews that no import renews.
- The sources page now also answers at `/sources` (`/sources.html` keeps working), and the new landing, the readable report, methods and about pages and the new map's brief link there; the landing's “How it’s built” link no longer returns “Not found”.
- The readable coastal report, methods and about pages (`/report`, `/methodology`, `/about`) use the new dark visual system with self-hosted fonts and add a "How it’s built" link to the sources page; their text is unchanged.
- In the new map preview (`?ui=v2`), the masthead's sign in opens an account menu: passkey sign in, boat presets and the exact-boat sheet, saved-trip alerts, and the offline notes, GPX and offline pack entries.
- In the new map preview (`?ui=v2`), the time dock covers the full seven-day forecast: eight day chips, the chosen day's hours as exact UTC times, play that stops at the last hour and pauses when the page is hidden, and under reduced motion a "Next hour" step instead of play; the terrain follows the dock's hour.
- In the new map preview (`?ui=v2`), Clouds loops over observed GOES infrared frames on the Chart: only times NOAA nowCOAST lists, at most 90 minutes old and only on today's date (other days show none), each frame labelled in the legend with when it was observed and how long ago, with a toggle that holds the loop; it stops while the page is hidden and never plays under reduced motion.
- In the new map preview (`?ui=v2`), the Chart is a MapLibre map over the self-hosted basemap with the region's NOAA CUSP coastline, a nautical scale and north-up controls; `?base=chart` adds the NOAA ENC chart from zoom 10, a failing source is named in the legend while the rest keeps drawing, and a clicked shoreline segment opens the mark card with its source date. The MapLibre test page `/map-test.html` is removed.
- In the new map preview (`?ui=v2`), the map stage switches between Chart, 2D and 3D: the reviewed coastal terrain loads on the first 2D or 3D choice and follows the profile's depth limit, the target, the hour, the surface-current source and the selected habitat; a region without terrain, or a browser without graphics, stays on the chart and says why.
- Add the new landing page behind `UI_V2`: the Morro Bay shoreline drawn from NOAA CUSP, live wind, swell, water and tide with each source, age and stale state, the port question with Boat / Shore / Spear, links into the map's layers, and a saved port opening the map directly.

- Mapping batches can hand off one completed terrain/imagery slice for website 3D rendering, with exact display acceptance and explicit blocked prerequisites.

- Add stopped-run audits and skill learning between bounded mapping experiment rounds.

- Add bounded preflight and progress checks for coastal mapping runs.

- Text Advisor pages and the web chat use the new dark visual system, and the new app's masthead links to the chat while the advisor is on (both stay off until enabled).

### Internal

- Publish the GOES longwave frame times from nowCOAST's WMS capabilities each live cycle (`conditions/goes-times.json`, a `packages/coast` `CloudImage`: acquisition times only, newest frame at most 90 minutes old) for the v2 cloud loop (FE-44).

- Collect the CDIP nearshore model for five SLO sites (Pismo Beach Pier to San Simeon Beach) each live cycle into `conditions/regions/morro-bay/nearshore.json`, with site identity and coordinate checks, native three-hour times and publisher quality masks, in the coast report's `NearshoreSite` shape (FE-40).

- Collect SLO County beach water-contact statuses (status text, advisory text and the county link; no sample date invented) into the conditions feed about hourly, in the shape the coast report reads (FE-41).

- Collect NDBC 46215 and 46028 recorded history (SHA-checked annual archives, monthly p10/median/p90 with counts and coverage, 45-day hourly means) into the data feed for the History view (FE-42).

- Bound mapping investigation by a shared operating allowance, downstream readiness and verified public progress; preserve scientific and release gates.

- Finish moving `packages/coast/panel.css` onto the token bridge (FE-77b): its last 95 colour literals become `var(--coast-…, v1 value)`, so the file has no token-lint baseline entry left, and v2's `CoastMarkup` host drops `web/app/coast-markup.css`, which no longer changed anything. The v1 report dialog computes the same colours on every tab (browser check against values recorded from `main`).

- Move the first half of `packages/coast/panel.css` onto the token bridge (FE-77a): its colour aliases become `var(--coast-…, v1 value)` and lines 1–1,472 follow, so the rules they hold read `web/tokens.css` under `data-coast-theme="tokens"` (FE-77b converts the rest). The v1 report dialog computes the same colours on every tab (browser check against values recorded from `main`).

- Bridge `packages/coast` to the v2 tokens (FE-76): `coast.css` and the series chart write colours as `var(--coast-…, v1 literal)`, `tokens-bridge.css` maps them to `web/tokens.css` only under `data-coast-theme="tokens"`, the 3D viewer reads `DEFAULT_COAST_PALETTE`, and the token lint now covers `packages/coast` with its own shrink-only baseline. v1 pages compute the same colours (browser check against values recorded from `main`).

- Add an overlay API to the coast embed (FE-81): `setOverlay` drapes GeoJSON fills, lines and points on the terrain in draw order with colours named by role from a host `overlayPalette`, `removeOverlay` frees them, and `onOverlayPick` reports the overlay and feature ids of a click. v1 passes no overlays and is unchanged.

## 0.7.0 — 2026-10-07

- Explicitly save and delete public coastal report, current and measured-history snapshots for offline use, with saved time and original source clocks.

- Add an opt-in bounded reader for authenticated original regular BAG cells.

### Internal

- Bound explicit coastal snapshot storage and preserve publication/private exclusions, source expiry and completed-pack replacement semantics.

- Preserve original BAG cell values, uncertainty and source registration; keep the reader private-only and separate from EPSG:3310 production processing.

## 0.6.0 — 2026-10-07

- Add isolated reference-grid routing for explicitly selected scope configs while keeping the Central Coast pipeline as the default.

- Share one explicit surface-current source choice across the coastal chart, native 2D/3D and Conditions. Off clears vectors; missing coverage or source hours remain gaps without provider substitution.

### Internal

- Preserve retained Central Coast grid and physical-cache identities; keep noncentral screening, processing and publication held until their scope contracts are complete.

- Validate exact current-product identity, original frame and source clocks, finite wet-cell values and source expiry; suppress delayed replies and preserve readable return state.

## 0.5.0 — 2026-10-07

- Record verified NOAA reuse terms and original coordinate/depth references for two southern survey candidates.

- Connect the Central Coast overview to shared terrain presentation, profile, target and UTC time. Preserve independent model forecasts, original source expiry, explicit package handoffs and geographic gaps in local readings.

### Internal

- Preserve candidate status, source IDs and hashes, unknown acquisition lineage and source-specific terrain, regional, camera and hazard-review gates for the H11879 2 m and H11880 1 m records.

- Verify exact restored source identities, earliest publication expiry, unsupported UTC selections, stale replies and malformed model cache admission.

## 0.4.0 — 2026-10-07

- Prevent early confidence UI imports from capturing another region’s forecast coordinates. Keep unit helpers independent of regional data; withhold current readings when the selected sample is absent.

- Normalize legacy Fish place/species/profile/hour links before startup, retain unsupported selections explicitly, and share saved-home save/forget behavior with native coast preferences. Keep exact public geography and profile through port handoffs and browser history.

- Add a readable coastal source report without JavaScript, original-clock SLO RSS, and canonical methods/about/privacy entry routes. Retain shared public selection and private request boundaries; fix profile-only changes after lazy local report loading.

- Bring original local Boat/Shore/Spear readings, buoy history, dated fleet facts and source receipts into Conditions with the shared place and UTC hour. Preserve distinct native species and source horizons; unsupported methods and regions remain explicit gaps.

- Expand one unranked SCC06 bedrock outline into a reviewed adjoining native window, with a new geometry-derived identifier; retain unknown terrain grades and species fits and exclude precise exports.

- Added the native coastal 2D/3D terrain as a presentation in the working chart workspace, sharing target, location and seven-day forecast time while retaining chart, planning, legal and account tools.

- Add four unranked SCC06 bedrock interpretations from one reviewed native window, with an explicitly reidentified SCC05 boundary after source-priority exclusion; retain unknown terrain grades and species fits and exclude precise exports.

- Add a reusable coastal-map skill with bounded subagents, tested model-setting records, honest visual enhancement, desktop/mobile acceptance and protected live-release checks.

- Keep coastal zoom controls clear of the species selector at medium phone and narrow tablet widths.

- Add an explicit conservative canonical occupied-subtraction option for reviewed original bedrock: remove bounded reprojection residuals without tolerating retained overlap, modifying prior geometry or activating a source.
- Bring the shared Monterey–Point Conception 2D/3D coast renderer and SLO daily report into SkipperCast at `/coast`, reachable from map options. Preserve original terrain evidence, habitat expiry, source clocks, existing chart/trip/account tools and shared location/target/hour links. Keep the existing homepage until full workspace parity. Fix coastal subrequests for the actual Cloudflare redirect API while continuing to reject every redirect.

- Add Fish link compatibility to the shared v2 state: preserve the fishing profile, target, place and whole-hour timestamps while giving explicit SkipperCast choices precedence. Legacy UI remains the live default until feature integration is verified.

- Define a bounded overnight mapping contract with exclusive worker claims, compact model briefs, release preflight and outcome-based checkpoints; distinguish the documented protocol from automated enforcement.
- Add a bounded read-only coastal data bridge for the Fish integration. Preserve public snapshot clocks and habitat release checks, isolate private storage and accounts, and reject foreign-region bindings, unsafe paths and inexact byte ranges. The current homepage remains active.

- Recognize one authenticated legacy San Simeon physical inventory in private window planning across screen-only refreshes, without fabricating a quarantine audit or changing publication checks.

- Document recovery of replaced scoped seafloor publication runs: retain unverified region scopes, inspect actual prepare matrices, refresh omitted regions with the existing workflow and verify each regional live readback.

- Extend reviewed San Simeon geology over 17 depth-qualified native SCC05 windows, preserving prior habitat, uncertain lithology, current spatial holds and private projection conflicts. Interpreted outlines remain unranked and nonexportable.

- Add reviewed exposed-bedrock outlines from two native SCC06 depth windows near Cambria, retaining prior habitat, current whole-polygon spatial exclusions and separate producer rights. These interpreted areas remain unranked and nonexportable.

- Enable reviewed Offshore Monterey exposed-bedrock outlines over existing native Monastery/Cypress depth at nominal25–300ft. Preserve original geology units, prior native areas, current whole-polygon exclusions and separate CSUMB noncommercial terms; leave uncertain terrain unranked and precise exports disabled.

- Add an explicit audited San Simeon geology profile for additional native survey pairs. Keep existing profile behavior unchanged, retain original PolygonZ geometry and invalid-source holds, and use strict unrepaired representations with private recovery. This code change activates no source.

- Support an explicit reviewed Monterey original-geology profile for unranked bedrock habitat. Preserve prior native features and source units; retain invalid derived representations privately with authenticated recovery and publication reconstruction. This code change enables no source, new ranks or precise exports.

- Enable reviewed original San Simeon exposed-bedrock habitat from two disjoint native depth windows, retaining source units, current habitat exclusions and whole-polygon spatial screens. These areas are unranked and receive no new measurement or precise fishing export.

- Extend reviewed SCC06 exposed-bedrock habitat to one additional disjoint native depth window, preserving prior features and current whole-polygon screens. The interpreted area remains unranked and nonexportable.

- Add explicit reviewed original-geology admission for unranked bedrock habitat, using bounded native depth windows, current canonical habitat exclusions, retained source units and separate producer rights. Preserve legacy rugose-rock outputs; bedrock map details keep rugosity, boulder size and species fit unknown. No source is enabled by this code change.

- Add the v2 port chooser and first run behind `UI_V2` (`web/ports.ts`, `web/landing/PortInput.tsx`, `web/app/FirstRun.tsx`): the command bar's area group gains a port button and "Use my location", which open the chooser as a dialog (search over the home ports by name, the featured ports first, Enter for the top match, the 75 nm nearest-port rule with v1's privacy line, "Explore the coast"); a choice saves the port under the key v1 reads and swaps the region without a reload; `/map` with no area opens the saved port or the landing. First run is now the Boat / Shore / Spear choice only, shown once over the map (never modal, never when the link names a profile); the home-port modal does not return in v2. Nothing changes without the flag or `?ui=v2`.
- Add the v2 mobile app shell at `/map` behind `UI_V2` (under 1,024 px, `web/app/Mobile.tsx`): the map fills the screen under a top strip with the brand and location card, a layers button and the full-width Boat / Shore / Spear switch; one bottom sheet with peek, half and full detents moved by drag and keyboard holds the time window, freshness, headline, four tiles in a row, "where to look", the tide curve slot, the day, target and area menus and the disclaimer line, with the hour slider at its top edge; the layers button swaps the sheet to the rail with the legend; a selected mark's card takes the sheet's peek; a four-tab nav (Coast / Conditions / History / Fleet) sits under the sheet. No horizontal scroll from 320 px; 44 px targets. Nothing changes without the flag or `?ui=v2`.
- Add the v2 desktop app shell at `/map` behind `UI_V2` (`web/app/`, concept A · Bridge): masthead with the region's name and centre, the Coast / Conditions / History / Fleet views as `?view=` links, the freshness dot and sign in (the v1 passkey dialog); a command bar with the Boat / Shore / Spear switch, target, area and a read-only time-window readout (the dock sets it; FE-12 brings the forecast horizon); a 332 px brief column in its empty state (headline, four tiles reading "—" with their source line and basis, tide curve slot, "where to look", the profile's caveat, one disclaimer line); and a map stage with the layer rail, one legend (hidden under 1,024 px until FE-06), the time dock and the selected-mark card, every control writing the address. The map itself and the readings arrive with later tasks; nothing changes without the flag or `?ui=v2`.
- Fix the fleet OSINT run (`fleet-osint.yml`) so that when some batches fail, the finished batches' profiles are still ingested before the job fails; previously the research step aborted on the runner's exit 1 and skipped Ingest, leaving finished profiles out of the registry.
- Start the front-end rebuild behind `UI_V2` (off; [plan](docs/plans/front-end/README.md), ADR 0009 and ADR 0005 accepted): with the Worker variable on or `?ui=v2` on the request, `/` serves the new landing page (or the new app when the link names an area) and `/map` the new app, both placeholders for now; `?ui=v1` forces the current shell. With the flag off and no switch nothing changes: `/` is the current site and `/map` is 404.
- Add the v2 icon set and UI primitives (`web/ui/`: 40 stroke icons, 31 ported from `fish`; Button, Chip and Segmented, Tile, Popover, Rail, Dock with Range, and the three-detent Sheet), styled from tokens only with 44 px targets and keyboard operation. Nothing visible changes until a v2 page uses them behind `UI_V2`.
- Add the v2 design tokens (`web/tokens.css`: dark default, light set, DM Sans and JetBrains Mono self-hosted under `web/fonts/`), extend the contrast check to both token files and add `scripts/check_tokens.mjs`, which fails CI on colour or font literals under `web/`. Nothing visible changes until a v2 page loads the tokens behind `UI_V2`.
- Add the charter fleet's weekly OSINT run (`fleet-osint.yml`, dark behind `ENABLE_FLEET`): batch manifests are researched by a pinned, headless Claude Code session with the `charter-osint` agent on the owner's runner, using the Claude subscription only (the run stops if an API key is set), with fetches to off-limits hosts refused, then validated and ingested; boats whose operator asked for removal are never researched or updated.
- Add the charter fleet's Labelling view to the admin behind `FLEET_ENABLED` (off): pick a trip (`#fleet-labels`), see its segments on a small track map and a speed strip, all marked inferred from movement, and label time ranges as in port, transit, fishing drift or fishing troll with a basis; each label records its labeller. `python -m skippercast.fleet.ais validate` copies labelled trips' raw positions to `validation/` (exempt from retention while labelled) and reports fishing and per-label precision and recall with a confusion table.
- Add fleet admin Coverage (`#fleet-coverage`: boats by port and class, % with MMSI, AIS seen or not seen in 30 days, single-source boats, completeness by field group, recent runs) and AIS health (`#fleet-ais`: last message age, 24 h reconnects and drops, gaps over 10 minutes, 7- and 30-day uptime, processor and watch list) views, admin only behind `FLEET_ENABLED` (off).
- Limit verified classified-policy updates to complete affected regions, including previous scopes and neighbors; uncertain changes retain the full-coast planner.
- Bind every coastal region's charter identity coverage to the new charter fleet registry (`fleet-registry`, superseding `operator-identities`) and show it as registry counts only; with the registry still empty, each region now reads "missing". Add the fleet pipeline's `discover`, `resolve`, `ingest`, `refresh` and `run` steps and `coverage-status` (all dark behind `FLEET_ENABLED`).
- Add the fleet pipeline's `plan-agent` step, which writes OSINT batch manifests of at most 20 boats from registry data only (new, stale or incomplete boats), and `ingest --profiles`, which validates each OSINT profile, refuses and lists invalid ones, and stores the rest as `osint` facts, trips and conflict reviews; a value missing from a newer profile never replaces an older one, and Google ratings are never stored.
- Add admin-only charter fleet activity layers to the map behind `FLEET_MAP_ENABLED` (off): activity stops sized by dwell, trip tracks coloured by segment and a heat layer, with boat, port, class, trip type, activity, date and season filters; every card says the activity is inferred from movement.
- Add the charter fleet's Fleet review and Vessels views to the admin behind `FLEET_ENABLED` (off): decide registry reviews, browse vessels by port, class, status, profile, AIS and completeness, and open a vessel's fields, facts, offerings, changes and trips; a field edit is recorded as an admin fact and pinned, and a removal request shows as keeping the boat off public pages.
- Add the charter fleet's Operators view to the admin behind `FLEET_ENABLED` (off): operators ranked by a 0-100 lead score shown with its parts and missing inputs, consent recorded with who, when and how, notes and outreach drafts that are never sent from SkipperCast (approve, discard, or log as sent by the owner), and do-not-contact blocking new drafts.
- Enable reviewed, unranked original 5 m Monterey rock habitat in r01 with prior-survey native exclusions, neighboring planning holds and fresh spatial screens; no new measurement, ranking or precise fishing export.

- Deduplicate interpreted habitat from overlapping survey pairs in reviewed source order, preserving earlier native outlines and rejecting stale publication receipts after a priority change.

- Enable reviewed, unranked Point Conception rock habitat in r08 with original NOAA/USGS attribution and fresh whole-polygon spatial holds; no new measurement, ranking or precise fishing export.

- Enable reviewed, unranked Point Estero rock habitat in Cambria r02, with fresh whole-polygon spatial holds and no new measurement, ranking or precise fishing export.

- Bound nonlinear map-coordinate conversion with collinear native-edge vertices when needed; preserve measured boundaries, original legal screens and existing fidelity limits.

- Add opt-in whole-polygon holds against verified neighboring planning footprints for classified habitat releases; preserve original native boundaries and recheck holds before publication.

- Verify current native dependencies and retain producer rights for survey footprints used by the opt-in classified habitat mode; keep original depth and rock interpretation authoritative.

- Scope classified habitat processing to reviewed reaches and add an opt-in paired-survey footprint mode, preserving original depth/class masks, existing rankings and publication checks.

- Show charter fleet boats on `/boats/<slug>` behind `FLEET_ENABLED` (off): class, landing, size, trips with prices as listed and the date, booking and website links through `/go/`, the business phone, photo links with credit, the Google rating with its link while under 30 days old, and dated sources; nothing from AIS, NOAA planning data or low-confidence facts, and out of search until the operator agrees. Advisor boat pages are unchanged while the flag is off.

- Preserve original native classified habitat boundaries while validating bounded shell/hole map representations; keep original areas and current spatial screening authoritative.

- Add a separate screened, unranked publisher-interpreted rugose-rock habitat area layer. These Tier1 areas receive no terrain/species rank or precise fishing export; original source pairs require explicit reviewed opt-in.

- Add a bounded private probe for reviewed rugose-rock habitat beyond existing terrain outlines; distinguish habitat expansion from new survey coverage in the coastal mapping skill.

- Harden the Text Advisor before launch: crew join only after replying YES (and only verified boats can invite), texts to numbers that never wrote to us are capped per number, per sender, per address and per day, the web chat has its own AI budget, unconfirmed boats' pages show no links, morning Stories trust only iMessage or upload-link photos from the owner or confirmed crew, upload and data links keep their token out of URLs and logs, the relay keeps messages at most 30 days and off iCloud, and every advisor secret has a rotation procedure (with a phone-number re-key script).

- Let the Text Advisor read photos with the owner's own Hermes vision service when it is set up, falling back to Claude whenever Hermes is slow or down, with a conformance script the Hermes side runs first; admin Health shows each vision provider's setup, skips and last answer.

- Get the Text Advisor ready to launch: a preflight script that checks a deployment against the launch checklist, a live prompt eval that also covers the daily answers and post captions, a runbook for unanswered messages, and the owner's launch to-do with the exact switch-on order.

- Delete Text Advisor data on schedule, every Sunday: message text after 180 days, photos nobody approved or posted after 90 days, team review notes 90 days after the decision, unlinked web chats 90 days after their last message, and data copies after 7 days; the privacy notice now says so.

- Read each published post's Instagram and Facebook numbers every night (Stories hourly while they are up) and show them on the post's card with the chats its link started; the admin Funnel gains a social section.

- Answer Instagram direct messages and comment keywords (RIG, REPORT, ID, BOATS, in English and Spanish) once Meta approves the app: one private reply per keyword comment, DM answers within Meta's 24-hour window, public answers to questions only when switched on, and a privacy-notice section for the Text Advisor awaiting review.

- Post the morning Stories automatically: each verified boat's count board from the day before (once its photo has no hold) and a conditions card for the day.

- Draft a daily "what's biting" post from yesterday's verified boat reports and a Sunday roundup carousel of the week's catch photos for the team to approve, and schedule approved posts into a weekly posting calendar shown in the admin Posts view.

- Strip text-advisor videos of their camera metadata (location included) before they can be approved, posted or served: the media runner copies each video without metadata with ffmpeg, and the public video link only ever serves that copy.

- Keep text-advisor photos upright: intake still strips all EXIF but keeps the JPEG's orientation value, so derived images are turned the right way, vision is told when a photo is rotated, and a sideways original is never shown on a page.

- Remember bounded completed seafloor discovery tests in an expiring private checkpoint. Keep changed or damaged evidence actionable, preserve separate recovery scopes, and avoid treating duplicate leads as new mapping work.

- Refine Big Sur habitat outlines with the original BSS08 2 m rough/smooth terrain layer. Preserve measured depth, uncertainty, credited noncommercial terms and spatial screening; this adds no new surveyed area.

- Show spatially screened measured rough-bottom patches as limited-confidence,
  unranked search areas when surrounding data cannot support a terrain grade.
  Keep detailed rankings, source-quality holds and precise fishing exports separate.

- Inspect geographic seafloor grids with their original angular registration and explicit ground-spacing ranges. Preserve native values and masks, existing metric-adapter guards and caches; interpolated DEM pixels remain unqualified for measured habitat.

- Reject acquisition-gap snapshots that omit or change surveys already used by the map. Check native source bindings before requests, preserve private physical work, and resume through unchanged measurement/rights-only refreshes without repeating source queries.

- Keep private sonar-grid medians consistent with their checked contributor depth ranges when the official readers print different precision. Preserve strict integrity checks, original outputs and source/publication holds.

- Add bounded no-fill point-bin diagnostics with independent statistic checks before lidar ingestion. Keep useful shallow measurements for future shore-fishing and spearfishing research without claiming ranked or published fishing locations.

- Let bounded original-sonar triage use a pinned private native-gap snapshot on a processing host without copying the raster cache. Preserve topology, depth/quality checks and publication holds; this screening tool adds no mapped area by itself.

- Recover the measured seafloor layer automatically after temporary publication updates, with bounded retries and expiry checks; preserve screening holds and manual layer-off choices.

- Refine Cambria/Point Estero habitat with original SCC04–06 native terrain classes, retaining measured depth, existing rankings and all source/publication restrictions. No new surveyed area is claimed.

- Refine San Simeon/Cambria habitat with the original SCC01–03 native terrain classes, preserving measured depth, producer terms and all spatial screens. Source qualification adds no new surveyed area.

- Qualify the original 2 m Monastery Beach–Cypress Point grid for the measured habitat pipeline; preserve mixed 2000–2006 dates, unknown datum and credited noncommercial terms. Source qualification alone adds no published fishing locations.

- Seafloor: complete the remaining Arguello permanent spatial review so all 33 Monterey–Point Conception reaches can be screened. Reuse physical terrain; retain all 32 affected candidates as MPA exclusions, including four security overlaps. No new measured coverage or public fishing locations is claimed.

- Add an isolated government-only seafloor input scope for separately reviewed commercial releases, retaining indirect calibration, whole-polygon screening and publication gates.

- Make browser map checks independent of live boundary-feed timing, retaining the production MPA gates and testing that unavailable current checks still withhold fishing targets.

- Qualify SCC26–28 native depth for credited noncommercial mapping, retaining MPA, security and edge-support holds while refining all affected habitat calibration.

- Refine Avila habitat with the original native terrain classes, retaining measured depth and Block J's private quality hold.

- Recover missing feed worktrees after runner cleanup so recurring source discovery can load its inputs, while preserving locked and unrelated worktrees.

- Bind original PGE Mid native terrain classes to reviewed depth, preserving measured support and existing source holds while refining habitat calibration and extraction.

- Bind original PGE South native terrain classes to reviewed depth, preserving measured support and existing source holds while refining habitat calibration and extraction.

- Bind five original SCC rough-terrain grids to their native depth sources. Preserve measured coverage, tighten eligible habitat boundaries and retain all private source/spatial holds; local screening gains 89 connected outlines while habitat area decreases by 3.057 km².

- Add source-bound native rough-terrain support for habitat calibration and extraction, preserving measured depth, existing quality holds and current publication checks.

- Preserve four original PGE South native grids as private physical sources: 111.052 km² of additional selected support and ranked candidates remain available for artifact review, with no new public fishing targets.

- Hold Avila Block J habitat pending native artifact review, retain its measured depth privately, and recompute affected public source selection and shared thresholds without changing scientific rules.

- Retain valid measured depth while keeping habitat from sources with unresolved artifact or interpretation reviews out of public maps and fishing exports.

- Apply reviewed USGS seafloor classes to thirteen SCC depth grids; preserve measured coverage and remove sediment-backed terrain candidates without claiming independent fish evidence.

- Add original 2 m Point Lobos survey support: 4.019 km² of additional selected measured coverage, ranked habitat and whole-polygon MPA screening; retain unknown datum and credited noncommercial terms.

Release reviewed Avila and SCC16 native source rows and complete the spatial-screen scope for three Avila/Pismo/northern Arguello reaches, preserving physical-first processing and whole-polygon exclusions.

Qualify seven original PGE_Mid native grids, adding 33.91 km² of selected shallow survey support across two Morro reaches while preserving native resolution, producer rights and final spatial screening.

- Seafloor: qualify existing SCC13–15 native 2 m grids; local processing adds 445 screened areas and 4.721851 km² of habitat across three bounded reaches and their shared northern boundary.

- Seafloor: qualify seven existing SCC09–12 native grids, adding 59 screened areas and 1.002481 km² of habitat across three Morro reaches in local validation; public release remains subject to the production pipeline.

- Permit the reviewed NOAA Point Lobos original archive through the native seafloor importer while retaining checksum, format and producer-use checks.

- Seafloor: qualify six existing Big Creek/Lopez Point native grids with preserved source identities and reviewed metadata corrections. Complete the intervening Big Sur reach screen; local results contain 284 passing habitat areas with all 184 held areas private. This releases existing measured support and does not claim new sonar coverage.

- Seafloor: qualify native Kasler, Soberanes and Yankee Point 2 m depth grids. Three Monterey reaches gain 24.490 km² of selected measured support and 240 net screened habitat areas in local validation, with source datum conflicts and protected-area holds retained. Production publication is verified separately.

- Seafloor: qualify native 2 m Grimes Point bathymetry and release the existing Slate Rock source under credited noncommercial terms. Two Big Sur reaches gain 416 net locally screened habitat areas. Report Grimes Point's new survey footprint separately from Slate Rock's existing private coverage; retain nominal NAVD88 depths and all publication screens.

- Seafloor: qualify original Hurricane Point, Cooper Point and Point Sur 2 m grids. Three local reaches gain 62.910 km² of selected measured support, 410 physical candidates and 46 net screened areas; the two Big Sur reaches increase from 1 to 126 screened areas. Keep source datum limitations explicit and all MPA holds private; production is verified separately.

- CI: run the complete check suite once per PR revision, preserve main and bot-dispatch checks, and cancel obsolete PR revisions so mapping work does not compete with duplicate checks.

- Seafloor: group up to three regional reaches per worker to reduce runner startup and queue overhead. Preserve exact reach assignments, sequential native validation, independent recovery receipts and complete-region publication checks; a failed reach does not stop its neighbors.

- Seafloor: use the original USGS Point Conception seafloor-character grid with seven NOAA depth products. Preserve shared survey lineage, unknown classifier accuracy and anthropogenic classes; exclude interpreted sediment from reef extraction. Local results refine 843 screened areas to 788 without adding measured bathymetric coverage.

- Seafloor: qualify original NOAA H11952 1 m shallow bathymetry near Point Conception. Local processing adds 4.353 km² of selected survey support while replacing coarser habitat classifications; candidate counts and published area may decrease with finer evidence.

- Seafloor: qualify 13 original SCC01–08 native grids for credited noncommercial use and screen Cambria–San Simeon r01. Reuse three verified private terrain caches, including categorical-row numeric normalization; local screening yields 611 areas across three reaches, 513 above the prior public subset. Production is verified separately.

- Seafloor: qualify credited noncommercial SCC17–25 depth grids and screen three Point Sal–Purisima reaches, retaining native 2 m measurements, private holds and the paid-deployment gate. Local validation yields 1,471 eligible habitat areas; production publication is verified separately.

- Seafloor: explicitly migrate verified legacy numeric-only cache identities without recalculating terrain or changing habitat geometry/ranks; retain complete private recovery and require fresh screening before release.
- Seafloor: declare the current noncommercial deployment profile and block incompatible paid deployments before writes; retain original producer credits and permission requirements.

- Trips: a launch-point catalog (`catalog/launch-points.json`, from the California DBW Boating Facilities records) builds `dist/regions/<id>/launch-points.json` for every published region; Morro Bay's public ramp, the Port San Luis ramp and Olde Port Beach are the first entries.
- Trips: a saved trip now carries its plan (launch point, up to three target species, spots, legs, window, exports taken and a status) through migration 0005 and `PATCH /api/trips`; the one-tap alert save is unchanged.

- Operations: the deploy no longer needs `VAPID_*` GitHub secrets; when they are unset it keeps the Web Push pair in the private backup bucket (`secrets/vapid.json`), generated once on the first deploy and reused after that, so alerts work on a fresh account with no manual key step.
- Seafloor: allow reviewed CSUMB originals from NOAA's Ventresca archive under the existing hash-bound noncommercial producer contract. Retain attribution and for-profit/navigation restrictions; unreviewed sources and cruises remain blocked. No catalog source or map is released by this change alone.
- Reconcile seventeen existing BSS native survey records with the newer coastal source stack while preserving prior sources and screened-cache evidence; use their reviewed noncommercial contract during the owner-authorized personal-use phase.

- Qualify six original SCC10–13 native depth grids; refine five private Morro Bay reaches with 347 net habitat candidates, retaining the measured coverage decrease and release holds.

- Qualify original SCC07–09 native 2 m/5 m bands: add 14.833 km² of private measured Point Estero/northern Morro coverage and 46 net habitat candidates, retaining native depth limits and release holds.

- Qualify cached native 5 m SCC03/04 shelf bands: add 2.191 km² of private measured coverage near the 300 ft limit; retain the 12-candidate net reduction and unchanged suitability rubric.

- Qualify original SCC26–28 native grids: add 36.624 km² of private measured Arguello coverage and 608 net habitat candidates; preserve source ownership, 1–3 rankings and release holds.

- Inspect native Avila–Pismo and southern Arguello grids: add 104.209 km² of private measured coverage and 2,005 net habitat candidates, retaining missing/conflicting metadata and release holds.

- Seafloor: inspect SCC06/14/24 native grids; add 56.29 km² selected coverage and 363 net private candidates, including first measured habitat in Arguello r05. Identify original Morro–Avila survey leads for the remaining southern gap.
- Seafloor: inspect native SCC05/15/23 and the deeper 5 m SCC05 companion; add 44.70 km² selected coverage and 81 net private habitat candidates, preserving source ownership and publication holds.
- Inspect native SCC04/16/22 grids and add private ranked Cambria/Arguello shelf coverage, preserving datum, mixed survey dates and publication holds.
- Seafloor: privately qualify native SCC03/17/21 and fill two previously empty Cambria/Conception reaches, updating three neighbors. Add 63.53 km² net measured coverage and 946 physical candidates; publication and incomplete-rank holds remain.

- Seafloor: privately qualify native SCC02/18/20 original grids and process their actual shallow intersections. Add 72.54 km² net measured coverage and 978 physical habitat candidates in the San Simeon approach and Arguello/Conception area; retain publication and ranking holds.

- Seafloor: privately qualify nine native Big Creek, Slate Rock and SCC grids. Four local reaches gain 69.54 km² of measured depth coverage and 824 physical habitat candidates; producer release qualification and spatial screening remain required before map/export publication.

- Seafloor: open explicitly selected native ArcInfo grids inside original NOAA ZIP-in-tar survey bundles, with bounded extraction and checked private recovery. Preserve native pixels and reject unsafe containers; source qualification and public screening remain separate.
- Seafloor: publish regions independently with retained batch identities for failed-job retries. Reconcile the ledger separately without downloading original surveys; retain scientific checks, report failed regions and log publication stages rather than timing out the entire coast in one job.

- Seafloor: transfer checked private physical results after rights-only source promotion without recalculating terrain. Preserve candidate geometry and rankings, reject scientific changes/corruption and keep publication held until the normal runner applies a fresh screen.

- Map and export: show original survey producer credits in reef details and retain their use restrictions in waypoint, outline and offline notes. New credited publications reject incomplete notices before export; existing government-only publications remain compatible.

- Seafloor: preserve original CSUMB noncommercial use terms and producer credit in tile and canonical-export metadata; unknown rights and for-profit release remain blocked. No source or fishing location is promoted by this contract change.

- Export: compress full canonical reef boundaries for mobile transfer, preserving every coordinate and hash/current-screen checks. Bound both compressed and decoded sizes so large Morro Bay surveys can load without weakening the limits.
- Fixed: trip-alert push notifications were never deliverable on Cloudflare because the deploy did not upload the VAPID key pair. The deploy now requires `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` (GitHub secrets) and uploads them, the smoke test checks that `/api/session` serves the public key, and a Worker without keys leaves alerts pending without claiming receipts, so the first check after the keys arrive sends them (an earlier version marked them held, which is never retried). The key check runs before any Wrangler command, so a missing key stops the job without a deploy and a rollback.
- Seafloor: allow checked native sources to advance private physical mapping while publication rights remain unqualified; isolate recovery/output caches and keep public maps, exports and ledger unchanged.

- Seafloor: read original CSUMB gzip-tar grids from the reviewed NOAA archive with bounded extraction and private recovery; preserve native values and retain source-specific rights review.

- Operations: every scheduled data workflow and CI reads its runner from a repository variable (`DATA_RUNNER`, `CI_RUNNER`; default `ubuntu-latest`), and `scripts/runner/setup.sh` turns one Ubuntu box into four self-hosted runners, so the jobs cost no billed minutes once the repository is private. Costs and steps in [docs/operations/runners.md](docs/operations/runners.md).
- Seafloor: screen southern Monterey/Carmel/PointSur whole habitat outlines;904 candidates pass locally, with MPAs excluded and changed Monterey rules holding publication for review.
- Map: show current screened survey habitat automatically for reef targets, preserve manual off, color by selected species fit and show actual regional publication counts.

- Seafloor: process original Carmel/Point Sur5m surveys in three new reaches; add85.27km² selected measured footprint and836 supported habitat ranks, held privately for spatial screening.

- Seafloor: include full H11953 depth-band footprints and native 1 m nearshore detail; +13.08 km² valid coverage. Existing relative extraction changes screened outlines, with limitations documented.
- Seafloor: read original USGS ArcInfo GRID archives at native spacing with bounded extraction and checked recovery; unlock older shelf surveys without claiming new published coverage.

- Seafloor: rescreen cached Cambria and southern Conception habitat; 1,112 additional candidates pass the expanded permanent planning scope, subject to production and trip-time checks.

- Seafloor: retain native H11953 4 m/8 m depth bands; add 65.71 km² valid survey footprint near Arguello and 475 spatially screened habitat candidates, pending production verification.

- Seafloor: extend Morro and Arguello permanent planning screens; exclude the Morro entrance channel and Vandenberg Zone 4, releasing 1,880 additional habitat candidates locally pending publication.
- Export: select up to 20 distinct best available lingcod/rockfish reefs within 300 ft, display trip priorities and a documented habitat evidence percentage, and put both in chartplotter waypoint and outline names. Export full screened survey geometry with fresh revision and whole-reef checks; restore saved selections only against that same current publication. [Ranking and export process](docs/product/ranked-reef-export.md).

- Seafloor: process southern Morro and eastern Cambria native intersections; add 89.68 km² measured coverage and 601 supported ranks in three private reaches.

- Seafloor: qualify three native NOAA Point Conception depth bands; add 76.32 km² measured coverage and 979 supported habitat ranks in three private reaches, preserving 2/4/8 m spacing.

- Seafloor: verify reviewed scientific raster content across lossless GeoTIFF encodings while retaining original/cache checksums; retain exact worker failure reasons during batch aggregation.

- Operations: `/api/daily` counts only edge-cache misses against its per-IP limit, so several people behind one address (carrier NAT, a marina's Wi-Fi) are no longer refused the cached regulation and closure checks.
- Internal: the conditions score, its tuned thresholds and the go / marginal / no-go verdict now live in one module, `web/score.ts`, shared by the Tomorrow card, the meteogram, the search plans and the coming trip planner. Ratings are unchanged: a 150-case golden fixture generated from the previous code passes exactly (`tests/test_score.mjs`).
- Seafloor: qualify the native Point Buchon survey and paired substrate; add 76.98 km² measured coverage and 1,131 supported habitat ranks in two private reaches, preserving the 80 m fine-resolution boundary.

- Seafloor: process the remaining two qualified Monterey native intersections; add 27.72 km² of measured coverage and 62 ranked habitat candidates, held privately until spatial screening.

- Seafloor: qualify the original Monterey 2 m producer product and paired substrate; add three measured physical reaches with 672 ranked habitat candidates, held privately until Monterey spatial screening.

- Seafloor: process oversized native habitat windows in bounded tiles without downsampling; join habitat across tile edges and preserve reach-wide thresholds. Morro Bay r01 has measured coverage and private ranked candidates pending its spatial screen.

- Add a daily seafloor rollout planner, reusable physical-stage cache, explicit survey promotion and per-reach failure recovery; keep legal screening as the final publication stage.

- Map startup ([P4-05], first slice): with production's live MPA check, Morro Bay's map downloads 3.6 MB of JSON at startup instead of 7.3 MB (`scripts/measure_startup.mjs --stub-mpa`). The uncertainty feed and the daily fishing evidence now load when Conditions opens, and the map reads only the regulation checks (and, when the live MPA query fails, the MPA record) of the daily feed through the new `/api/daily?region=&part=` endpoint (per-IP limited, saved in offline packs), falling back to the full feed. The map, atlas and protected-area screen load in parallel behind a loading skeleton, and a bottom-left **Legend** chip explains the visible layers and marker meanings. CI budgets the committed static startup JSON (`scripts/startup-budget.json`).
- Front end ([P4-04]): the spot sheet leads with the spot's name and answer (grade label and depth), then confidence badges (Depth, Terrain, Fish: Qualified ✓ / Estimated ~ / Unknown ?) and a freshness pill for the spot's own nearshore buoy that re-judges its age every minute. Research-only targets keep a short "Research-only" marker on the answer line, write depth as "~N ft (estimated)" and open the depth badge's why. The research-only and "mapped habitat candidate" caveats moved word for word into the badges' one-tap "why" (`web/disclaimers.ts`); the target id, rank and coordinates moved under the stats and the seabed view's Relief/From above toggle sits under the image, so the Morro Bay spot sheet shows 60 words above the fold with the research-only why open (70 before, with the caveat above the name).
- Development ([P4-04]): copy lint (`node scripts/check_copy.mjs`, CI `check` job) fails on two consecutive "not" sentences and on GFS/ECMWF/MLLW/datum outside a disclosure; caveat sentences may name methods and generated region wording is not linted; the 54 existing findings are listed in `scripts/copy-lint-baseline.json`, which can only shrink (editing a listed sentence is recorded with `--update`).
- Operations: the research inventory workflow keeps its carried state after a degraded run, and NOAA BAG HEAD checks retry `429 Too Many Requests` (honouring `Retry-After`, four workers) instead of reporting a rate-limited rescan as degraded.
- Operations ([P4-11]): cookie-less client telemetry. The app counts a fixed set of funnel steps (port selected, map viewed, forecast viewed, spot saved, offline pack saved, installed) and reports uncaught errors with the page build and last request id, batched through `navigator.sendBeacon` to `POST /api/telemetry` and written to Workers Analytics Engine when `ENABLE_ANALYTICS` is on. Nothing is sent under Do Not Track or Global Privacy Control; no ids, cookies, IPs or query strings. The daily Operations report shows the funnel and top client errors ([docs/engineering/telemetry.md](docs/engineering/telemetry.md)).
- Testing ([P4-09a]): browser tests with Playwright and axe (`pnpm e2e`, CI job `e2e`) run eight flows at phone and laptop size against the built site under `wrangler dev`; serious or critical accessibility violations fail the build.
- Front end ([P4-01b]): TypeScript and Preact foundation. A signals store (`web/state.ts`) owns region, coast, view, target and hour in the URL: opening the site with a saved port, choosing the first port, and choosing a port in the region already shown no longer reload the page (the forecast hour and target are kept), and `?hour=` links open that forecast hour. The header outlook badge, the meteogram card and the offline freshness banner are Preact components; `pnpm typecheck` covers `web/`.
- Build ([P4-01a]): Vite 8 bundles the client (`vite.config.mjs`); first load of the map drops from 84 script and stylesheet requests (242 KB gzip) to 22 (169 KB). Hashed files live in `/assets/` with a year's immutable caching; pages, `/sw.js`, vendored libraries (with SRI), data and the offline precache keep their contract. `scripts/fingerprint.mjs` is retired and `check_client.mjs` checks the Vite manifest.
- Operations: optional Workers Analytics Engine metrics (repository variable `ENABLE_ANALYTICS=true`): one data point per request (route pattern, status, latency, cache), LLM call, queue batch and cron run, with no personal data; a daily **Operations report** workflow summarises the last 24 hours. A failed cron step now fails the cron invocation.
- Operations: saved-trip checks can run on Cloudflare Queues (repository variable `ENABLE_QUEUES=true`): the Worker cron queues one message per owner after each live publication, with retries and a dead-letter queue, removing the 2,500-trip ceiling. Off by default; `/api/jobs/check` stays as the manual trigger and fallback.
- Development: Python tests run under pytest in layers (`tests/unit`, `tests/contract`, `tests/integration`, `tests/gis`; claims pins in `research/tests`) with `gis`/`claims`/`network` markers, JUnit and slowest-test summaries in CI, and the full survey-science run fails on any skip outside the private-cache allowlist.
- Docs: the README is rewritten as a short product page with a screenshot, coverage list and three-command start; datum and withdrawn-claim details now live in `docs/product/data-confidence.md`. The architecture doc no longer describes ChatGPT Sites hosting.
- Docs: `docs/product/data-confidence.md` is the single reference for grades, coverage states, freshness, depth datums and withdrawn claims.
- Docs: 39 dated rollout, source-request and research logs moved to `docs/archive/` (indexed in `docs/archive/README.md`); `docs/README.md` now links the engineering, operations and legal documents.
- Worker in TypeScript with Hono ([P3-01]): `server/` is strict TypeScript (`pnpm typecheck` in CI) routed by Hono (`server/app.ts`, `server/routes/`, `server/middleware/`). Routes, statuses, headers and cookies are unchanged; every response now carries `X-Request-Id`, JSON errors repeat it as `request_id`, and `HEAD` is answered like `GET` without a body.
- Operations: the daily data job now runs and publishes product feeds only; its NOAA BAG/ENC and USGS catalog research inventories moved to `research-daily.yml` (artifacts only), the monthly research workflows are renamed `research-substrate.yml` / `research-fish-survey.yml`, and 22 research-only catalog pins moved to `research/catalog/`.
- Smaller deploy: 206 audit receipts (3.1 MB) moved from `dist/data/` to `research/receipts/` with a sha256 manifest; the app never loaded them, and they are no longer uploaded with the site.
- Repository: the ~240 dated audit, screening, triage, discovery and one-off builder scripts moved from `scripts/` to `research/scripts/` (history kept); `scripts/` now holds only the product tools that workflows, the build and deploy run.
- Docs: architecture decision records 0002 (own NOAA/ECMWF forecasts), 0003 (R2 as feed system of record), 0005 (front-end direction, proposed) and 0006 (passkey accounts; billing proposed).
- Trip alerts use your saved boat: the form's wind, gust and sea limits start from it, the boat is saved with the trip (D1 migration 0003 adds four nullable columns), and the evening-before and morning-of checks judge wind chop against that boat and name it in the alert.
- First run: harbor, then boat (four quick choices, exact boat or skip), then tomorrow's one-word answer for that harbor and boat, with the reasoning and caveats behind a "Why?" tap.
- Seafloor habitat layer (Map options → Map layers): screened Morro Bay habitat candidates from original surveys, colored by terrain grade or by lingcod / rockfish-reef physical fit, with optional survey coverage cells. Shown only while the screening publication is current; the service worker never caches it.
- Accounts: create a SkipperCast account and sign in with a passkey (Face ID, Touch ID or device PIN; no password or email) from Guide → Your account. Saved trip alerts, comfort feedback and AI boat lookup use it; you can add or remove passkeys, sign out, export your records and delete the account.
- Contracts: feeds and generated region files are validated against `schemas/` before they are written (`ContractError`, `SKIPPERCAST_VALIDATE=off` emergency switch), and region validation uses the region schema plus cross-reference checks.
- Operations: `refresh_regions.py --run-manifest` records each regional refresh (per-region and per-source status, input/output sha256, exit status) at `var/runs/refresh-<kind>/<run_id>.json`; `skippercast.report` renders a region table and `publish_r2.py var/runs runs` uploads manifests to R2 `runs/`.
- Pipeline: every source request in `src/` goes through one HTTP client (`skippercast.http.Session`: host allowlist, DNS-pinned public addresses, bounded bodies, jittered retries honouring Retry-After, receipts, optional ETag cache); the `/usr/bin/curl` TLS fallbacks are replaced by the optional `tls` extra (`truststore`).
- Offline: a service worker now keeps the app shell and the latest public data, and "Save for offline" (Guide → Offline trip pack) stores a region's data, rules, forecast and NOAA chart tiles; saved data shows an "Offline — showing data saved …" banner. Install prompt and a one-time iOS Add to Home Screen hint.
- Fixed: every Cloudflare deploy since the gated workflow was rolled back by a false smoke-test failure (curl | grep -q under pipefail).
- Operations: the `conditions` and `data` feed branches, like `forecasts`, are now one parentless commit replaced on each publish (with a lease against concurrent publishers), and each deploy sets R2 lifecycle rules (run manifests 7 days, history backstops after the pipeline's own 90/30-day retention).
- Security: the live workflow is split into `refresh` (contents write), `notify` (OIDC identity for saved-trip checks, runs beside it and cannot fail a cycle) and `next` (dispatch only) jobs, and data workflows prefer an R2-only `R2_PUBLISH_TOKEN` over the deploy token.
- Tomorrow card on the Conditions tab: for the next three days, go / marginal / no-go per two-hour window for your saved boat, the one factor that limits the day in words, GFS–ECMWF agreement as confidence and the latest comfortable back-at-dock time. Caveats sit behind a "Why?" tap.
- Performance and abuse protection: the model API, forecast/intelligence/habitat endpoints and R2 feeds are edge-cached (`X-SC-Cache`), and `/api/om` (60/min) and `/feeds/` (300/min) are rate-limited per IP on Cloudflare.
- Security: every Worker response now carries HSTS, an enumerated Content-Security-Policy (moved from the page meta tag), frame-ancestors 'none', Permissions-Policy and COOP; vendored scripts and styles are pinned with SRI.
- Operations: data retention now runs on the Cloudflare cron as well as the trip-check job; `request_limits.expires_at` is indexed (migration 0001).
- AI boat lookup: a global daily cap (`BOAT_LOOKUP_GLOBAL_DAILY_LIMIT`, default 500), a `BOAT_LOOKUP_ENABLED` kill switch, and one usage log line per lookup with billed tokens and searches.
- Worker hardening: request errors are typed (only validation failures return their message), `/api/events/ack` validates the event id, and public `/api/health` no longer discloses which bindings and secrets exist.
- Development: shared `skippercast.util` time and file-hash helpers replace duplicated copies; CI runs `ruff check src` for syntax errors and undefined names.
- Development: `pip install -e ".[survey]"` (and `ocean`, `sst`, `publish`, `test`, `seafloor`, `dev`) installs pinned optional tools; `SKIPPERCAST_ROOT` points installed code at a checkout.
- Operations: R2 upload failures now fail the live and daily jobs, each `latest.json` records `published_at` and `run_id`, publishes are verified on the public `/feeds/` route, and the freshness monitor checks that route first.
- Operations: one region's refresh error no longer blocks the others; it is recorded as `status: failed` in the regional index, and the job fails only for the default region or a majority.
- Contracts: JSON Schemas in `schemas/` for regions, catalogs, jurisdictions, the daily, live and intelligence feeds, region indexes, coverage and forecast tiles, with `python -m skippercast validate` and CI validation of every committed file.
- Operations: structured JSON logging (`skippercast.log`), run manifests (`skippercast.runs`) and `python -m skippercast.report` step summaries; the forecast tile builder logs structured records and can write a run manifest.
- Conditions: surface currents and drift guides now use NOAA WCOFS samples from the regional pipeline (about 4 km, first 72 hours) instead of the browser's Open-Meteo request; the hourly sea-temperature weather layer is removed until an own source exists, and the legacy monitor requests SkipperCast's /api/om.
- Forecast range & uncertainty: the 31-member GEFS wind ensemble is now read directly from NOAA's GEFS open data on AWS once per cycle instead of Open-Meteo's non-commercial ensemble API.
- Web app: installable icons (PNG, maskable, Apple touch), faster startup via module preloading, a friendly retry card when the app fails to start, one combined notice when several optional layers fail, and neutral boat wording instead of the owner's boat name.

- Internal: removed duplicate and unused client files (including the unused 2.3 MB og.png), renamed -vN modules to canonical names, and made check_web.py reject -vN names in dist/.
- Internal: design tokens (colour, type, spacing, radius, elevation, z-scale, motion; light and inactive dark) in dist/tokens.css with a CI contrast check; screens are unchanged.

- Legal: a data-rights register records, for every source and runtime service, whether a paid product may use it; a CI gate fails if a new asset depends on a source not cleared for commercial use. See [data-rights register](docs/legal/data-rights-register.md).
- Draft terms of use, privacy notice and licences pages (pending review by counsel), linked from About, the Guide and Sources.
- Contributing: outside contributors must sign off commits (Developer Certificate of Origin), checked on every pull request; licensing options are laid out for the owner in [ADR 0004](docs/engineering/adr/0004-licensing.md).
- Governance: issue templates, CODEOWNERS, weekly Dependabot updates, a security policy, a production dependency audit in CI, and CI actions pinned to commit SHAs.
- CI: scheduled data and survey workflows run third-party actions pinned to commit SHAs.
- Operations: runbooks for a stale feed, an R2 outage, a D1 restore and secret rotation, plus an incident-response process; the stale-feed issue now links its runbook. See [incident response](docs/operations/incident-response.md).
- Conditions: a 7-day meteogram (wind and gust, seas, tide, hourly score band, model disagreement, now marker, provisional hatch after 72 h) opens the view; tap, drag or arrow keys pick the hour shared with the scrubber.
- Rules card: a first row now shows Open/Closed (or Check rules), bag, size, depth where the reviewed rules state it, the verified date and one official link; the full detail stays below.
- Security: the Cloudflare Worker no longer trusts ChatGPT identity headers; private features there return 401 until SkipperCast has its own sign-in.
- Fixed: trip-alert push notifications could never be enabled because the build renamed the service worker away from `/sw.js`.
- Seafloor runner setup now installs the schema validator and checks the manifest before processing or publishing.

- Tuna search overlays use the regional offshore footprint, reject uniform water and stale frames, support uncertainty-screened satellite fronts, and explain species-aware 1–3 search priorities separately from boat comfort.
- Boat profile: enter your boat (optionally looked up with AI and confirmed) and comfort and drift-control ratings scale to its length, weight, hull and layout. See [boat profile](docs/boat-profile.md).
- Search plans for five Central Coast preview regions now include their surveyed habitat footprints (575 in total); they had been built before those inputs existed.
- Map engine test pages (`/map-test.html`, `/map-test-leaflet.html`) compare MapLibre with PMTiles vector tiles against today's Leaflet map on one layer. See [map engine test](docs/archive/map-engine-test.md).

### Internal

- Give the seafloor planner an explicit acquisition action when no new reach is selected, while preserving freshness work and unverified growth. Shorten the mapping skill and retain detailed source/release recipes and historical evidence in linked references.

- Release process: version tags publish GitHub Releases whose notes are the matching CHANGELOG section; see [release process](docs/operations/release-process.md).
- Seafloor runner setup now installs the schema validator and checks the manifest before processing or publishing.
- Seafloor publication: regional PMTiles, private survey recovery and a scheduled main-only workflow with checksum, restriction-expiry and public HTTP Range checks. The first Morro Bay archive contains 1,006 screened candidates; live acceptance follows a successful post-merge dispatch.
- Seafloor spatial screening: current CDFW, NOAA federal-area and reviewed security boundaries now qualify whole habitat polygons for tier 2. Missing, stale, changed or overlapping evidence stays held; publication follows separately.
- Seafloor habitat: reusable original-substrate joins, rough-bottom extraction, A/B/C terrain grades and source-cited 1–3 species planning fits. Three Morro Bay reaches now have private review outputs, including a real survey seam; legal screening still gates publication and export.
- Seafloor coverage: original-survey footprints now qualify planning cells and produce mask-aware terrain summaries for the first Morro Bay reaches. The ledger separates classified-cell area from actual selected survey area; habitat publication remains pending.
- Seafloor ingestion: reusable USGS GeoTIFF and regular NOAA BAG adapters, hash-verified private caching and native-resolution drafts. Two survey windows are qualified for processing; habitat coverage totals remain unchanged.
- Seafloor pipeline: reproducible Central Coast reach/grid baseline and a coverage-ledger CLI. All new tiers remain unprocessed until original surveys are ingested; the reference band is explicitly provisional. See [seafloor pipeline](docs/seafloor.md).
- Published feeds (live conditions, daily data, forecast tiles) now load through the site's `/feeds/` route, ready to be served from Cloudflare R2; the site can deploy to its own Cloudflare account. See [Cloudflare](docs/cloudflare.md).
- The live conditions feed is monitored hourly and reports when it stops refreshing.
- Hosting: SkipperCast runs only on its own Cloudflare Worker; ChatGPT Sites packaging, its origin and its identity headers are gone, `CUSTOM_DOMAINS` attaches skippercast.com and www.skippercast.com as custom domains (www redirects to the apex), and workers.dev stays on as staging.

## 0.3.0 — 2026-09-20

- Mobile-first map with Map, Spots, Forecast, and Guide navigation; no long page scroll to reach the map or weather.
- Compact spot cards expand into accessible detail sheets with persistent map and GPX actions; wide screens retain a docked list and detail panel.
- Collapsible filters, a reset action, 44-pixel map-marker hit areas, safe-area spacing, and readable mobile forecast comparisons.
- Direct single-spot GPX downloads for mobile and embedded browsers, with reproducible generation and checks for all 132 files.

## 0.2.1 — 2026-09-20

- Visible A/B/C terrain-grade definitions and practical context for points, reef outlines, and drift alignments.
- Per-target explanations of all four grading factors, weighted points, and capped contributions.
- Dated AIS evidence summary with eight sampled archive dates, source URLs, counts, hashes, and explicit lack of verified local sportfishing-charter tracks.

## 0.2.0 — 2026-09-20

- Public browser map with target search, habitat grades, depth filters, reef outlines, and optional drift alignments.
- Notes and GPX export for each selected target, plus the complete reviewed atlas downloads.
- On-demand ECMWF and NOAA wind/wave comparisons at three offshore samples, with missing-data, disagreement, coverage, and freshness notices.
- Model metadata, NWS advisory lookup, source attribution, and links to current rules and entrance information.
- Browser forecast and GPX tests, asset consistency checks, and vendored Leaflet with its license.

The app displays evidence for review; automated trip qualification and alert delivery remain separate integrations.

## 0.1.0 — 2026-09-20

Initial public research release:

- Portable forecast collector and alert lifecycle logic, with explicit operator-review boundaries.
- Public USGS-derived atlas: 132 habitat candidates, 107 outlines, 31 optional drift alignments.
- Reproducible GPX, GeoJSON, and offline notes from the included public data.
- Personal-use source license and separate third-party source notices.
- Offline tests, CI, contributor guide, and onboarding documentation.

The existing personal forecast deployment and full private research atlas are not migrated or replaced by this release. This initial research release did not include a hosted application.
