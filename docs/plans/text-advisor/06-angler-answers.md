# 06. Angler answers: reports, planning, fish ID, rules, advice, safety

Stories: FR-1, FR-2, FR-4, ID-1…ID-3, AD-1…AD-4, AC-1, WH-1 (FR-3, AC-2 are
Next). Code: `server/advisor/answers/*.ts` and the tools in 04.

## "What's biting out of Morro Bay" (FR-1)

`answers/reports.ts`:

- `portForQuestion(text, contact)`: a port named in the text (aliases file)
  else the contact's home port else `ADVISOR_REGION_DEFAULT`'s first port.
- `dailyAnswer(env, port, date, language)`: read `advisor_daily_answers`;
  if missing or `inputs_hash` differs from `currentInputsHash(port, date)`,
  generate it. Inputs: published reports for the port from the last 3 days
  (verified boats only; unverified counted as "another boat reports…" without
  the name), the `landing-reports` confidence and species from the daily
  feed (`readFeed` of `data` → `reports[]`, the same records `dist/bite-evidence.js`
  uses, with the Insufficient/Low/Moderate label computed by
  `answers/confidence.ts`, a server re-implementation of the ladder in
  `web/confidence.ts`; `server/` does not import from `web/`, so the test
  pins both to the same fixtures), the live conditions summary (wind, seas,
  advisories) for today, and the active rules with any `stale` flags.
- Generation is one model call with a fixed template prompt
  (`prompts/daily.ts`), output ≤ 480 chars, in both languages (two calls, or
  one call asked for both in JSON; TA-A1 picks after testing), e.g.:
  ```
  Morro Bay, Sat Oct 3: 3 boats reported Fri—limits of rockfish for most
  trips (vermilion, copper), lingcod 8–14 per boat, a few cabezon. Seas 4–5 ft
  at 9 s, wind light until noon. Rockfish open; check depth limits.
  Full picture: skippercast.com/ports/morro-bay
  ```
  Never a probability. When no skipper reports exist in 3 days, say so and
  fall back to the landing-report confidence label with its source named
  ("the landing reports…"). When nothing exists at all: "No reports from the
  last three days for Morro Bay yet. Conditions: … Want me to text you when
  one comes in?" (the follow offer is Next, FR-3; in v1 the answer stops at
  the conditions).
- Cron (`advisor-digest` slot at 05:30 local) pre-generates every active
  port's answer so the first text of the day is instant; the `inputs_hash`
  check regenerates during the day when a report is published.

The pre-router answers these without a chat model call when the question is
the plain form; the model's `get_port_report` tool returns the same answer
plus the raw latest reports for a nuanced question.

## "Is Saturday worth going for rockfish" (FR-2, AD-4)

`answers/planning.ts: planningBrief(env, {port, date, species, boatType?})`:

1. Date parsing: weekday names (en/es), "tomorrow/mañana", "this weekend"
   (→ both days), ISO dates; beyond the forecast horizon (7 days) → say so.
2. Conditions for the day's fishing window (06:00–14:00 local unless the
   person said otherwise): from the regional forecast feed the trip checker
   already reads: `server/trips.ts` exports only the `FeedCache` type, so
   `answers/planning.ts` calls `readFeed(region.intelligence_feed)` and the
   daily feed itself with its own small parsers (tested against the same
   fixtures `tests/test_trip_queue.mjs` uses): wind, gusts, seas, swell
   period and direction, and the comfort rubric word for the reference boat,
   computed by `answers/comfort.ts` (a server copy of the few lines of
   `web/score.ts` it needs, pinned by test to `web/score.ts` fixtures; the
   person's own
   boat is unknown by text; say "for a mid-size center console"). Never a
   catch number.
3. Advisories: NWS alerts for the port's zones from the daily feed; a Small
   Craft Advisory, Gale, or hazardous seas statement is the first sentence
   of the reply, in capitals on the word only ("SMALL CRAFT ADVISORY posted
   for Sat…"), and the reply ends with "Check the latest NWS forecast before
   you go." (AD-4). Hazardous bar conditions for Morro Bay use the
   `Morro Bay Harbor` daily check only as "harbor page updated"; the advisor
   never says the bar is open or closed.
4. Season and rules: `get_rules` for the species; closed season → say so
   first; `stale` → "double-check".
5. Recent activity: the daily answer's report summary for the port.
6. Confidence: one phrase from a fixed ladder tied to evidence coverage, the
   same words `docs/bite-evidence.md` uses ("recent reported activity:
   Moderate / Low / Insufficient"); the model is told these are the only
   confidence words allowed.

The tool returns the facts; the prompt composes them. Tests assert that a
reply built from a feed fixture with an advisory starts with the advisory
and contains no digit followed by `%`.

## Freshness (FR-4)

Every report the advisor mentions carries its date ("Fri" / "3 days ago")
and the boat name (or "a boat" when unverified). `get_port_report` refuses
to return reports older than 14 days; the daily answer says "no reports in
the last 3 days" rather than reaching further back.

## Fish ID (ID-1, ID-2, ID-3)

`answers/fishid.ts: identify(env, media, contact)`:

1. `vision.identifyFish(media)` (07) → `{candidates: [{species_key, label, confidence, cues}], needs_better_photo, reason}`.
2. Confidence ≥ 0.85 → "That's a {label}. {one cue}." Then rules.
   0.6–0.85 → "Looks like a {label}, could be {second label}: {distinguishing
   cue}. {how to tell}." Then rules for the top candidate, with "if it's a
   {second}, {its key rule}" when the rules differ.
   < 0.6 or `needs_better_photo` → "Not sure from this one. {reason}: can
   you send a side-on shot with the fins spread?" and no rules.
3. Rules (ID-2): `get_rules(species_key, contact region)` → "Rules
   ({source_name}, checked {reviewed_at date}): {size}, {bag}, {season}.
   Double-check before you keep it: {{link:rules:<species>}}". `stale` rows
   add "this rule is due for review" and the `check CDFW` link replaces the
   numbers.
4. Look-alike cues come from `catalog/advisor/lookalikes.json` (vermilion vs
   canary vs yelloweye; lingcod vs cabezon; bocaccio vs chilipepper; California
   vs Pacific halibut; white seabass vs croaker), authored once by the owner
   and the agent from CDFW's identification pages, each cue with its source.
   A yelloweye or cowcod candidate at any confidence adds "If it's a
   yelloweye or cowcod it must be released — use a descending device."
5. The photo is kept as `publish_state='private'`; the AC-1 offer
   ("can we share this with credit?") is appended only when the ID
   confidence was ≥ 0.6 and the contact is not a skipper (their photos flow
   through intake).

## Rigging and area advice (AD-1, AD-2)

`answers/advice.ts` backs `get_strategy`. Source data: `catalog/targets.json`,
`catalog/primary-strategies.json`, `catalog/search-methods.json`,
`dist/data/charter-grounds.json` (named public grounds), `catalog/species.json`
depth bands, and the region's `dist/regions/<id>/search-plans.json` for the
species' general areas. The tool output is a compact object:
`{rig, bait_or_lure, line, weight, depth_band_ft, season_note, areas: [{name, kind: 'reef'|'bank'|'edge', general_depth_ft}], source_notes}`.
"Areas" are named public grounds and broad descriptions ("the inshore reefs
north of the rock in 60–120 ft"); the tool never returns coordinates, and
`search-plans.json` spot names that are not public ground names are
excluded by an allowlist (`catalog/advisor/public-grounds.json`). AD-2
replies end with "General areas only; I don't share anyone's numbers." the
first time a contact asks.

## Trips for newcomers (AD-3)

`get_trips(port)` lists verified boats from `advisor_boats` with their
landing, booking link and boat page, plus the trip types seen in their
reports (`trip_type` distinct values, last 60 days). With fewer than two
verified boats the reply says "the boats I work with so far" and links the
port page. SkipperCast never recommends one boat over another; order is by
most recent report.

## Angler photos (AC-1)

When an angler agrees to share: `share_angler_photo` → `publish_state='queued'`,
`review.media` reason `angler_photo`, `credit` = the display name the angler
gives (asked once: "How should we credit you? A first name is fine, or
'anonymous'"). Approved angler photos become a `post.draft` of kind `photo`
with no boat, caption style `angler`. AC-2 (where it was caught) is Next and
is stored only as a free-text `notes` tip on the media row, never as a
report.

## Links in replies (WH-1)

`links.ts` resolves placeholders to `ADVISOR_PUBLIC_BASE` paths:
`{{link:port:<id>}}` → `/ports/<id>`, `{{link:species:<key>}}` →
`/species/<key>`, `{{link:boat:<slug>}}` → `/boats/<slug>`,
`{{link:rules}}`/`{{link:rules:<species>}}` → `/species/<key>#rules` or
the regulations page, `{{link:map:<port>}}` → the app with `?region=` set,
`{{link:home}}` → `/`. Unknown placeholders are dropped. Every link carries
`?s=txt` so the funnel dashboard can attribute site visits to the advisor
(the existing telemetry reads the `s` parameter into `source`; TA-W1 adds
that one line in `web/telemetry.ts` if it is not already there).

## As built (TA-E2)

The data tools are in `server/advisor/tools/` with their helpers in
`server/advisor/answers/`; `answers/reports.ts`, `planning.ts` and
`fishid.ts` (the daily answer, the planning brief and the fish-ID flow) are
TA-A1, TA-A2 and TA-I3. Where the code differs from the text above:

- **Feeds.** `answers/feeds.ts` reads the region's `daily_feed` and
  `intelligence_feed` with `readFeed`, with the checks `routes/public.ts`
  applies; `EngineDeps.feeds` replaces the reader in tests (the engine and tool
  tests serve `tests/fixtures/feeds/`). A feed that fails to load is
  `available: false` / `advisories_checked: false`, never a guess.
- **Confidence ladder.** The Insufficient/Low/Moderate rule lives in
  `dist/bite-evidence.js` (`reportEvidence`), not in `web/confidence.ts` (that
  file holds the map's depth, terrain and fish badges). `answers/confidence.ts`
  copies `reportEvidence` and the test pins it to `dist/bite-evidence.js` on the
  `tests/test_evidence.mjs` feeds and the daily fixture. Landing reports are
  matched to a port through `landing_names` in
  `catalog/advisor/port-aliases.json` (the feed calls Port San Luis "Avila
  Beach").
- **Comfort.** `answers/comfort.ts` copies only the comfort half of
  `web/score.ts` (`hourScores`, `limitedScores`, `verdictFor`) for the reference
  boat; the test pins it to `web/score.ts` on the 150 golden cases in
  `tests/fixtures/score-golden.json`. The word is `comfortable`, `bumpy`,
  `rough` or `unknown` (never "go"), "for a mid-size center console". The
  window's score is its roughest hour.
- **get_port_report** `{port}` → `daily: null` (TA-A1), up to five
  `published` skipper reports from the last 14 days, newest first (a verified
  boat by name with a `{{link:boat:<slug>}}`, an unverified one as "a boat"),
  and `landing`: the port's landing reports of the last seven days with the
  ladder per region target (`label: 'reported by the landing'`),
  `freshness`, `catch_probability: null`.
- **get_conditions** `{port, date?, start_hour?, end_hour?}`: the forecast
  point is the port's `forecast_point` in `catalog/home-ports.json`; wind and
  gusts from GFS, seas as the higher of GFS-Wave and ECMWF WAM, swell from
  GFS-Wave; `advisories` (small craft, gale, storm, hazardous seas, high surf,
  special marine) from `sources['alerts-<zone>']` for every zone in the
  region's `marine_zones` that overlaps the window, gale first, listed before
  the numbers with `lead_with_advisory`. Date words: English and Spanish
  weekdays, today/hoy, tomorrow/mañana, pasado mañana, this weekend/fin de
  semana (two days; on a Sunday, Sunday only), `next <weekday>`, ISO. More
  than 7 days ahead → `beyond_horizon: true` and no numbers; a past date is
  an error.
- **get_species** `{species_key}`: catalog claims (a sub-species gets its
  parent group's, marked `about`), the depth note, cues and look-alikes from
  `lookalikes.json`, the `protected.json` note. No rule.
- **get_strategy** `{species_key, region?}` (`answers/advice.ts`): `rig`,
  `bait_or_lure`, `line`, `weight` come only from the catalog text; the
  catalogs have no line or weight specs, so those are usually `null` and the
  prompt says not to fill them in. `depth_band_ft` is the span of the
  allowlisted grounds' `general_depth_ft` (rounded charter-grounds depths;
  nominal, datum unverified), `areas` only names in
  `catalog/advisor/public-grounds.json` (Morro Bay: Pecho Rock, Diablo coast,
  Morro Bay coast), each with a broad description. The region's
  `search-plans.json` names (fetched from `ASSETS` when bound) pass through the
  same allowlist, so `SC-AREA-*` and the habitat names never come out;
  `publicOnly()` also drops any sentence with a coordinate-like number.
  `first_time` is true when the contact has no earlier inbound message with
  intent `strategy`; the prompt then ends the reply with the AD-2 line.
- **get_trips** `{port}`: verified boats only, ordered by latest published
  report, trip types from published reports of the last 60 days, `https`
  booking links only, `few: true` under two boats.
- **Names.** `answers/resolve.ts` resolves ports (ids, catalog names,
  `port-aliases.json`; Cayucos → Morro Bay) and species (keys, names,
  `species-synonyms.json` in English and Spanish) whole-word, accent- and
  case-insensitively, longest phrase first; every data tool accepts either.

