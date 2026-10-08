# User stories: front-end rebuild and the `fish` merge

Who the rebuild serves and what each must be able to do. Each story has an
acceptance note, a scope (**MVP** is built in this plan; **Later** is
designed for, not built) and the [dev-plan.md](dev-plan.md) phase that
delivers it. [design.md](design.md) holds the technical detail.

Phases and task ids (FE-xx) follow dev-plan.md:

| Phase | Theme | Tasks |
| --- | --- | --- |
| P0 | Foundations behind `UI_V2`: flag and routing, tokens and fonts, icons, state v2, desktop and mobile shells, landing, port chooser and first run | FE-01 – FE-09 |
| P1 | One map stage and its layers: the coast embed and MapStage (Chart, Terrain 2D, Terrain 3D), basemap and style, MapLibre engine and layer registry, currents, water temperature, habitat and marks, MPAs, swell field and nearshore rings, time dock and legend, charter grounds and commercial AIS, clouds, aerial, fleet activity, terrain options and overlays, landing night map (FE-13 and FE-26 dropped 2026-10-07) | FE-10 – FE-27, FE-70 – FE-73, FE-79 – FE-82 |
| P2 | Profiles, brief and charts: the coast data client, markup host and token bridge, Boat / Shore / Spear, the brief adapter, Conditions view, tide curve, "where to look", History view, shore runs, the brief column | FE-30 – FE-37, FE-74 – FE-77 |
| P3 | `fish` data sources into SkipperCast collectors and the bridge's retirement: nearshore wave model, beach health, buoy history, shore runs and access points, cloud frame index, aerial source config, snapshots and assets | FE-40 – FE-45, FE-84, FE-85 |
| P4 | Remaining features into the new shell: account and alerts, trip planner and offline pack, reports and catch cards, Fleet view, species plans and regulations, advisor entry, Fish and coast links, home memory, readable pages | FE-50 – FE-55, FE-78, FE-83, FE-86 |
| P5 | Flip the flag, delete the old shell, retire `fish` | FE-60 – FE-62 |

If dev-plan.md changes its phases, it wins; fix this file.

Ground rules for every story: `UI_V2` defaults off until Phase 5; every
displayed reading shows its source and age; habitat fit is a physical match
and is never written as a catch chance; fleet activity stays "inferred from
movement"; no story adds a paid service.

## First-time visitor

**US-V1. See the value in seconds.** As someone who has never heard of
SkipperCast, I want the first screen to show me real conditions for a real
piece of coast, so that I understand what the site is for before I read
anything.
- Acceptance: `/` with `UI_V2` on renders the landing (concept D) with a
  live readout strip (wind, swell, water, tide, a fleet line, freshness)
  from the active region's published feeds, each reading with its source and
  age, over the night map with the shelf and streamlines. Largest
  Contentful Paint under 2.5 s on a throttled mobile profile against the
  built site (design § 13). No modal, cookie banner or sign-in gate.
- MVP. P0 (FE-07, static shoreline), P1 (FE-25, live night map); readings from the P2 brief model (FE-31).

**US-V2. Say where I launch.** As a first-time visitor, I want to type my
harbor or use my location and land on the map for that port, so that I never
face a list of regions I do not know.
- Acceptance: the "Where are you launching?" input matches
  `data/home-ports.json` entries as I type; "Use my location" picks the
  closest port within 75 nm (the existing `closestPort` rule) and says when
  none is close enough; choosing navigates to `/map?region=<id>&view=…`
  with the port saved locally. Keyboard and screen-reader operable.
- MVP. P0 (FE-08).

**US-V3. Pick how I fish, once.** As a first-time visitor, I want to choose
Boat, Shore or Spear and have the whole app follow that choice, so that I am
never shown offshore reefs when I fish from the sand.
- Acceptance: the profile pills on the landing and the switch in the app
  set `?profile=` and a stored preference; the species list, depth limit,
  "where to look" list and brief caveats follow design § 8. First run has
  no other step.
- MVP. P0 (FE-08, FE-09), P2 (FE-30).

**US-V4. Understand how it is built.** As a careful visitor, I want one page
that explains where every number comes from, so that I can decide how much to
trust it.
- Acceptance: the landing nav's "How it's built" opens the sources page
  restyled with the tokens; each layer's "basis" sentence links there.
- MVP. P0 (FE-07) links; the page restyle is P4 (FE-54).

## Boat angler

**US-B1. Read the day in one column.** As a boat angler, I want a headline
sentence for the day, the four readings I check every morning (wind, swell,
water, tide) with their age, a tide curve, and a short ranked list of where
to look, so that I can decide in a minute whether and where to go.
- Acceptance: the brief column (desktop) or sheet (mobile) renders design
  § 10's brief: headline from the rules table, four tiles with source and
  age, tide sparkline with high and low events, "where to look" ranked by
  habitat fit for the target species within the profile's depth limit, and
  one caveat. Readings older than their freshness limit show as stale, never
  as current.
- MVP. P2 (FE-31, FE-37, FE-33, FE-34).

**US-B2. See the seafloor as relief.** As a boat angler, I want the bottom
drawn as shaded relief with depth colour, so that I can read structure the
way I read my sounder.
- Acceptance: where terrain exists, the Terrain 2D and 3D presentations
  show the `packages/coast` relief with its source coverage, measured and
  modelled labels and gaps left open, and the Seafloor entry's options set
  relief, water and contours; in Chart, seafloor candidates and reef marks
  draw with the survey's name and year in the legend. Switching
  presentation keeps place, target and hour. Panning a dense region stays
  responsive (design § 13 budget).
- MVP. P1 (FE-71, FE-80, FE-14); FE-13 and FE-26 dropped 2026-10-07.

**US-B3. See currents move.** As a boat angler, I want surface currents drawn
as flowing streamlines for the selected hour, so that I can see where the
water is going without decoding arrows.
- Acceptance: the Currents layer draws animated dashed streamlines from
  the native WCOFS forecast frame or HF-radar observation frame nearest the
  selected hour, within the age gates ported from `fish`; gaps stay blank;
  the legend shows the speed range; the basis sentence states the product
  and its resolution. Motion stops under `prefers-reduced-motion`.
- MVP. P1 (FE-15, FE-12).

**US-B4. Scrub the day.** As a boat angler, I want one time control that
moves the map layers and the brief together, so that the picture at 7 am
and at 2 pm are the same kind of picture.
- Acceptance: the time dock's day chips, play button and hour slider set
  `?hour=`; currents, water temperature, swell, clouds, the tiles and the
  chart cursor follow it; observations keep their own time and say so.
- MVP. P1 (FE-12), P2 (FE-32).

**US-B5. Keep what works today.** As a returning boat angler, I want the
trip planner, GPX export, offline pack, regulations, species search plans,
charter grounds and commercial AIS areas in the new shell, so that nothing I
rely on disappears when the flag flips.
- Acceptance: each feature in design § 2's inventory has a home in the
  new shell (table in design § 6) and its existing tests pass against the
  new entry points before FE-60.
- MVP. P1 (FE-21), P4 (FE-51, FE-54).

## Shore angler

**US-S1. See the beach on its own terms.** As a shore angler, I want the map
and the list to show sandy-shore runs and public access points for
surfperch and halibut, so that the app is about my water.
- Acceptance: with `profile=shore` the "where to look" list and the map
  show the ESI sandy-shore runs with their access points and the species
  guidance, each with source year and the access review date; the depth
  limit and reef marks are hidden; the caveat says offshore seas are not
  breakers at the beach.
- MVP. P2 (FE-36) on the bridge's shore-habitat data (FE-74); FE-43 moves the import into SkipperCast.

**US-S2. Know the beach is open.** As a shore angler, I want county beach
health notices on the brief, so that I do not fish a posted beach.
- Acceptance: notices from the county feed for the selected area show on
  the brief with the county link and the fetch age; absent sample dates are
  stated as absent, never invented.
- MVP. P2: the coast report's water-quality binding (FE-74), read by the brief adapter (FE-31) and rendered by FE-37; FE-41 moves the collector into SkipperCast.

## Spearfisher

**US-P1. Shallow water first.** As a spearfisher, I want the depth limit at
60 ft, the nearshore wave model in the swell tile and a visibility caveat,
so that the brief answers my question rather than a boat's.
- Acceptance: `profile=spear` sets the 60 ft limit, the swell tile prefers
  the nearest fresh nearshore model site, the headline rules use the spear
  variants, and the caveat states that visibility is unverified.
- MVP. P2 (FE-30, FE-31, FE-37) on the coast report's nearshore sites (FE-74); rings on the map in FE-27; FE-40 moves the collector into SkipperCast.

## Returning user (any profile)

**US-R1. Open straight to my port.** As a returning user, I want `/` to take
me to my saved port and profile, so that the landing is a one-time thing.
- Acceptance: with a saved port and no area parameters, `/` replaces
  itself with `/map?region=…&profile=…` before the landing's readings load;
  shared links with area parameters always open the app at that place.
- MVP. P0 (FE-01, FE-08).

**US-R2. The hour-by-hour picture.** As a returning user, I want a Conditions
view with wind, gusts, offshore and nearshore seas, tide, air and cloud on
one time axis with night shaded, so that I can plan the window.
- Acceptance: the stacked gap-aware chart from design § 10 with the shared
  cursor; gaps stay blank; each row keeps its own unit and scale; quiet
  windows shaded; scrolls sideways on mobile.
- MVP. P2 (FE-32).

**US-R3. A longer view.** As a returning user, I want buoy history with
seasonal bands, so that I can judge whether today is unusual.
- Acceptance: the History view shows the recent 45 days of hourly means
  for a station and metric over the recorded monthly 10th, median and 90th
  percentile bands, with sample counts and missing coverage shown.
- MVP. P2 (FE-35) on the coast history snapshot (FE-74); FE-42 moves the collector into SkipperCast.

**US-R4. One legend, one rail.** As a returning user, I want layers to be a
single rail of six toggles with one legend, so that the map is readable on a
phone.
- Acceptance: the layer rail lists Seafloor, Currents, Water temp, Swell,
  Charter fleet, Clouds (and Aerial as a base toggle); one legend shows the
  active ramps; `?layers=` round-trips. Every other control from today's
  Options dialog has either a home in design § 6's table or is removed with
  a line in the PR.
- MVP. P1 (FE-20).

**US-R5. Sign in where I expect it.** As an account holder, I want sign in,
my boat and my alerts reachable from the masthead, so that accounts work the
same in the new shell.
- Acceptance: the masthead's sign-in opens the existing passkey flow;
  boat profile and trip alerts render in the tokens; account tests pass.
- MVP. P4 (FE-50).

## Owner

**US-O1. Flip without a deploy.** As the owner, I want the new shell on or
off by one Worker variable, with `?ui=v2` to preview, so that I decide when
the public sees it.
- Acceptance: `UI_V2` through `scripts/wrangler_config.mjs` and the deploy
  workflow like `FLEET_ENABLED`; `?ui=v2` and `?ui=v1` override per request;
  the default shell is byte-identical to today while the flag is off.
- MVP. P0 (FE-01).

**US-O2. No hidden costs.** As the owner, I want the basemap and every new
source to cost nothing beyond the existing Cloudflare and Hermes bill, with
any paid option listed for my decision.
- Acceptance: design § 16 holds the estimate; paid options only in
  [open-questions.md](open-questions.md).
- MVP. P1 (FE-10).

**US-O3. Retire `fish` safely.** As the owner, I want a checklist that
proves every `fish` capability is live in SkipperCast before I archive and
delete the repository, and its research receipts kept.
- Acceptance: design § 15's checklist is ticked in FE-62's PR with links;
  `docs/archive/fish/` holds the docs and research listed there; the owner
  archives, then deletes, the repository.
- MVP. P5 (FE-62), after the bridge reads SkipperCast storage (FE-84, FE-85).

**US-O4. Fleet stays dark until I say.** As the owner, I want the charter
fleet layers in the new shell to keep their admin gating, so that the
rebuild does not widen what the public sees.
- Acceptance: the Charter fleet rail entry renders only when
  `/api/fleet/map/filters` answers for an admin with both fleet flags on;
  the Fleet view shows the public directory only when `FLEET_ENABLED` is
  on; copy keeps "inferred from movement".
- MVP. P1 (FE-24), P4 (FE-53).

## Later (designed for, not built)

- **US-L1. Light theme.** Tokens define a light set from day one; a theme
  switch and the second contrast pass are a backlog task (open-questions Q3).
- **US-L2. Second active region in the landing.** The landing input already
  lists every port; preview regions open with their existing preview banner.
- **US-L3. Admin restyle.** `web/admin` keeps its current look until the
  public shell is done; a token pass is backlog.
