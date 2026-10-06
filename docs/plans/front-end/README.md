# Front-end rebuild and the `fish` merge

Status: **Planned** (2026-10-05). No code yet. The plan replaces the Leaflet
app shell with the "Bridge" instrument console (concept A), adds the "Open
water" landing page (concept D), moves the map to MapLibre GL and PMTiles as
[ADR 0005](../../engineering/adr/0005-front-end-preact-vite-maplibre.md)
proposed, and merges the owner's `fish` repository (SLOFishReport.com) into
SkipperCast so that `fish` can be retired. Everything ships behind `UI_V2`
(a runtime Worker variable, default off) with a `?ui=v2` switch, so the
current site keeps working until the owner flips the flag.

This folder is written for an implementing agent that has not seen the
conversation that produced it. The structure follows
[docs/plans/charter-fleet/](../charter-fleet/README.md).

| Document | What it specifies |
| --- | --- |
| [user-stories.md](user-stories.md) | Who the rebuild serves (first-time visitor, boat angler, shore angler, spearfisher, returning user, owner), numbered stories with acceptance notes, MVP or Later, and the story-to-phase map |
| [design.md](design.md) | Research findings verified in both code bases, architecture, basemap strategy with cost, the token system, app shell and landing, state and profiles, every map layer, the brief and charts, data ingest for the `fish`-only sources, copy and claims policy, testing, flags, the `fish` retirement checklist, costs and risks |
| [dev-plan.md](dev-plan.md) | Phases 0–5 and PR-sized tasks `FE-xx` with size, dependencies, files, build notes, acceptance criteria and owner asks |
| [open-questions.md](open-questions.md) | Decisions the plan had to make, each with ranked options and the pick the build assumes; the owner overrides by saying so |

The architecture decision is recorded in
[ADR 0009](../../engineering/adr/0009-front-end-rebuild-and-fish-merge.md).

## How to use this plan

1. Work through [dev-plan.md](dev-plan.md) in phase order. Each task is one
   PR on its own branch `claude/fe-<task-id>`, sized for one builder
   subagent (at most about 400 changed lines excluding generated files) and
   reviewed independently, as [AGENTS.md](../../../AGENTS.md) requires.
2. Before each task, re-read the [design.md](design.md) section it cites;
   the dev plan is terse and the design holds the detail.
3. Until Phase 5, nothing changes for a visitor unless `UI_V2=true` is set on
   the Worker or the request carries `?ui=v2`. Merging to `main` never
   changes the live site's default shell before the owner flips the flag.
4. When a document and the code disagree, fix the document in the same PR.
5. Steps marked **Owner** (flags, data-rights rows, R2 uploads, archiving
   and deleting `fish`) need the owner. Do the engineering around them, stop
   at the owner step, and report exactly what is needed with the link.
6. Code may be copied from `fish`: same owner, and `fish`'s `NOTICE.md`
   records that it reuses SkipperCast data exports. Every copied module is
   ported into `web/` as typed TypeScript with the token system, never pasted
   as-is, and every data source it brings needs a `catalog/sources.json`
   entry with rights fields (the commercial-sources contract test rejects
   entries without them).
7. Copy follows the voice guide in [design.md § 12](design.md#12-copy-voice-and-claims):
   specific, sourced, aged, never promising fish. `node scripts/check_copy.mjs`
   stays green and its baseline only shrinks.

## Decisions already made (D1–D16)

Recorded from the owner's brief of 2026-10-05. These are settled; do not
reopen them in a task PR. [design.md](design.md) and
[dev-plan.md](dev-plan.md) cite them by number.

- **D1.** The app adopts concept **A · Bridge** (dark navy instrument
  console) and the public landing page adopts concept **D · Open water**,
  with **one visual system** shared by both: the same tokens, type, icons and
  map styling.
- **D2.** The `fish` repository's features are merged into SkipperCast and
  `fish` is retired afterwards. Deleting the repository is an owner step at
  the end (dev-plan FE-62); until then `fish` stays read-only reference.
- **D3.** Voice and craft follow the creator persona: grew up fishing,
  became an intelligence analyst who gathers and verifies information, then
  a data scientist and visualist who makes clear, beautiful data
  visualisation. Every number shows its source and age; nothing promises fish.
- **D4.** A first-time visitor must understand the value of the data within
  seconds: the landing shows live, sourced readings on a real map before any
  sign-in, port choice or explanation.
- **D5.** Tokens (dark, default): bg `#07131d`, panel `#0e1d2b`, panel2
  `#122535`, line `#223849`, text `#e6eff4`, muted `#8ba5b7`, mint `#69e0bc`,
  blue `#73bfff`, coral `#ff9c86`, amber `#eabd76`. Landing ground `#020b12`.
  Depth ramp `#7fd9c8 → #2b9c9c → #1f5f8f → #1d2f6e`. Surface temperature ramp
  `#244f9d, #188eb5, #39c6c2, #a6dda0, #efd477, #f18a65`. Current
  streamlines animated dashed `#dffcf6`, fast `#fff0bf`. MPA fill `#e8a877` at
  0.08 with dashed `#e8b584` outline. Fleet layers amber.
- **D6.** Type: DM Sans for text and JetBrains Mono for readings in the app;
  the landing uses DM Sans only, at display weight. Both self-hosted (SIL OFL).
- **D7.** App shell (desktop): masthead (brand, location in mono, views Coast
  / Conditions / History / Fleet, freshness dot, sign in); a command bar with
  the Boat / Shore / Spear profile switch, target species, area and time
  window; a 332 px brief column (headline sentence for the day, four stat
  tiles wind / swell / water / tide with source and age, tide sparkline, a
  ranked "where to look" list with habitat fit, one honest caveat) beside a
  full map. Map chrome is limited to the selected-mark card, a layer rail
  (Seafloor, Currents, Water temp, Swell, Charter fleet, Clouds), one legend
  and one time dock (day chips, play, hour slider, readout).
- **D8.** App shell (mobile): the map fills the screen; brand and profile
  switch at the top; one bottom sheet with the headline, the four tiles, the
  top pick and the hour slider; a four-tab nav.
- **D9.** Landing: near-black ground, full-screen night map with a glowing
  shelf and streamlines, headline "Know the water before you leave the
  dock.", one input "Where are you launching?", profile pills, a live readout
  strip (wind, swell, water, tide, fleet line, freshness), layer dots on the
  right edge, minimal nav (Fleet, Reports, How it's built, Sign in).
- **D10.** Architecture: ADR 0005 is adopted (Vite + TypeScript + Preact +
  signals; MapLibre GL + PMTiles), recorded in ADR 0009. The basemap is
  self-hosted PMTiles on R2 served through `/feeds/` (design § 4), cost near
  zero.
- **D11.** The blocking home-port modal goes. The port chooser becomes the
  landing's input plus "use my location"; first run is reduced to the
  profile choice.
- **D12.** Profiles Boat / Shore / Spear are first-class state (URL and
  stored), with `fish`'s `experience.ts` semantics: species defaults, depth
  limits 60 ft (spear) and 300 ft (boat), the sandy-shore habitat swap for
  shore runs, and profile caveats in the brief.
- **D13.** Copy: analyst's voice; one footer disclaimer line per page plus a
  one-sentence "basis" per layer and per tile, never a disclaimer on every
  card. Must pass `scripts/check_copy.mjs`.
- **D14.** Phasing: Phase 0 tokens, shell and landing behind `UI_V2`; Phase 1
  map engine and core layers; Phase 2 profiles, brief and charts; Phase 3 the
  `fish` data sources; Phase 4 fleet, advisor and the remaining features into
  the new shell; Phase 5 flip the flag, delete the old CSS and JS, retire
  `fish`.
- **D15.** Tasks are at most about 400 changed lines excluding generated
  files, ids `FE-xx`, branches `claude/fe-xx`, each with files, build,
  acceptance and owner asks.
- **D16.** Data rights: every `fish`-only source (NAIP, CDIP, beach health,
  NDBC history, ESI shore runs and access points, GOES, the NOAA CUSP
  shoreline) and the Protomaps basemap get a row in
  `docs/legal/data-rights-register.md` with the rights note carried from
  `fish`'s `NOTICE.md`; the rows are listed in design § 11 for the owner to
  add, since `docs/legal/` is owner territory.

## Status log

Append a dated line when a phase starts or finishes; keep the older lines.

- 2026-10-05: plan written (Claude Fable 5.1) after reading both code bases;
  claims in design § 2 were checked against the files they cite. No code yet.
- 2026-10-05: Phase 0 started (FE-01: `UI_V2` flag, shell routing, placeholder
  pages, ADR 0005 and 0009 Accepted).
- 2026-10-05: FE-02 added the tokens, fonts, contrast extension and token
  lint.
- 2026-10-05: FE-05 added the desktop app shell (`web/app/`, `/map` behind
  `UI_V2`) with a placeholder map stage and the brief's empty state.
