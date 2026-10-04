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
  (`prompts/daily.ts`), output ≤ 480 chars, in both languages (TA-A1: one
  call with a forced tool whose input is `{en, es}`), e.g.:
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
- Cron (`daily-answers` slot at 05:30 local) pre-generates every active
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
   A yelloweye or cowcod candidate at confidence ≥ 0.3 (any band, the 07
   threshold; settled in TA-I3: "any confidence" would warn on every red fish)
   adds "If it's a yelloweye or cowcod it must be released — use a
   descending device."
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



## As built (TA-I3)

The fish-ID flow is `server/advisor/answers/fishid.ts` (`identify`,
`answerFor`, the rules lines), the angler's media path and the AC-1 replies are
`server/advisor/intake/anglers.ts` (the Stage 2 flow `anglerFlow`, registered
after TA-I2's in `engine.ts` `STAGE_TWO_FLOWS`), and `identify_fish` and
`share_angler_photo` replace their stubs. Where the code differs from the text
above:

- **Who.** Any contact that is not a skipper or crew. A skipper's or crew's
  media still go through TA-I2's `reportFlow`, which runs first; a skipper with
  no boat gets the plain acknowledgement, never the angler path.
- **Media-only.** The first stored image is classified (07); `kind='fish'` runs
  `identifyFish` with the contact's region (home port, else
  `ADVISOR_REGION_DEFAULT`). No chat model call. Anything else (a deck, a
  sunset, a person) gets "Nice shot. Want me to ID a fish, or can we share this
  with credit?" and records the offer; a reply of `id` / `identify it` /
  `qué pez` then runs the fish ID on that photo. A video gets "Nice shot" too
  (nothing to identify). Vision down: "I can't read photos right now…"; over
  4.5 MB or a rejected file: the upload link.
- **Reply shapes** (strings `fishid_*`, en and es). High: "That's a {name}.
  {cue}." Medium: "Looks like a {name}, could be a {second}: check for {cue}
  ({name}) against {cue} ({second})." The cue pair is the two species'
  `lookalikes.json` cues that share a feature word (the jaw against the jaw),
  else the first of each; names come from the catalog (Spanish: the first
  Spanish synonym, "colorado"). The cues are English, so a Spanish reply leaves
  them out until TA-A6. Ask: "Not sure from this one. {reason}: can you send a
  side-on shot with the fins spread?" with a reason per `reason` code (blurry,
  partial, several fish, no fish, too far; else "I can't tell it apart from its
  look-alikes"). A top candidate under 0.6 is "ask" even without
  `needs_better_photo`.
- **Protected.** `decideProtected` at **≥ 0.3** (step 4 above now says so);
  only `must_release` species (yelloweye, cowcod, bronzespotted) add the line,
  in every band including "ask"; canary (`must_release: false`, a sub-bag
  species) does not.
- **Rules (ID-2).** `lookupRules` for the top candidate (its own row, else its
  group's, so a vermilion with only a rockfish row quotes the rockfish row):
  "Rules ({source_name}, checked {Mon D}): {size min/max}, bag {n} (or no take),
  open {Apr 1} to {Dec 31} (or open all year), {depth limit}. Double-check
  before you keep it: {{link:rules:<key>}}". A stale row (in review or past
  `review_due`) is never quoted with numbers: "this rule is due for review, so
  double-check with CDFW before you keep it: <link>". No row: "I have no
  reviewed rule for it, so check the current CDFW rules…". A medium ID whose
  second candidate has a different rule adds "If it's a {second}: …" (or "its
  rule is due for review: double-check"). The ask band quotes no rule. The
  reply is capped at 480 characters like a model reply.
- **AC-1 offer.** "Nice fish. Can we share this photo on SkipperCast with
  credit? Reply YES if so." as a second text, only when the top candidate is
  ≥ 0.6 and the contact is not a skipper or crew. The offer is `job_state`
  `advisor.share.<contact_id>` (`{step: 'offered' | 'credit', media_id,
  asked_at, id_offered?}`, written by the consumer's `share_state` action), good
  for 24 h. `yes`, `y`, `sure`, `ok`, `sí`, `si`, `claro`, `dale`, … within 24 h
  share; any other message deletes the offer and goes on as usual ("else
  ignore"). The photo stays `private` until then.
- **Sharing.** A yes: the `angler_share` action (the contact's own photo with no
  boat, `private` → `queued`), a `review.media` item with reason `angler_photo`
  (which texts the admin), and the credit. The credit is asked once per contact:
  "How should we credit you? A first name is fine, or 'anonymous'." The reply is
  read by `parseCredit` (1–4 words of letters, ≤ 40 characters, "call me Joe",
  "me llamo Lupe", `anonymous`/`anónimo`) and stored on `advisor_media.credit`;
  a later shared photo reuses the contact's last credit without asking. A reply
  that is not a name leaves the photo queued with no credit and goes on. The
  post draft (`kind photo`, caption style `angler`) is TA-S1's.
- **Tools.** `identify_fish {media_id}` (the contact's own image) returns the
  band, the candidates, `must_release`, the rules summaries, `reply` (the same
  deterministic text, which the model is told to send as it is) and, when
  eligible, a `share_offer` note; a current rules row in its result satisfies
  the engine's rules guard like `get_rules`. A photo with a caption now reaches
  the model with its `media_id` for anglers too. `share_angler_photo {media_id,
  consent}` (anglers only): false clears the offer; true runs the same share
  actions and the system sends the credit question itself.
- **Forget me** also deletes the contact's `advisor.share.` row.

## As built (TA-A1)

The daily answer is `server/advisor/answers/reports.ts` (`portForQuestion`,
`dailyInputs`, `currentInputsHash`, `dailyAnswer`, `composeDaily`, the
`daily-answers` slot job `pregenerateDaily` and the pre-router `dailyFlow`),
with the template in `server/advisor/prompts/daily.ts`. Where the code differs
from the text above:

- **Inputs and hash.** `dailyInputs(env, port, date)` collects, in a fixed
  order: the port's `published` skipper reports dated from three days before
  `date` through `date` (id, version, date, counts; a verified boat by name,
  any other as `"a boat"`, so the name never reaches the model), the landing
  reports the daily feed holds for the port with the ladder label per region
  target (`answers/confidence.ts`), today's advisories and the 06:00–14:00
  conditions (wind, seas, period, the comfort word), the region's rules for
  its targets (`open` today, `stale`), and whether each feed loaded.
  `currentInputsHash` is the sha256 of that JSON. A publish or an edit (new
  version) changes it; a pending report, another port's report or one older
  than three days does not. Publishing also deletes the port's rows (TA-I2),
  so the next question regenerates in any case.
- **One call, both languages.** `record_daily_answer` is forced
  (`tool_choice`), `temperature: 0`, its input `{en, es}`; the prompt asks for
  ≤ 420 characters each so the resolved link fits inside 480 (the cap is
  applied after link resolution, `capReply`). The prompt is given the facts
  as JSON plus the conditions sentence and date words already written in both
  languages, so the model does not restate numbers on its own. The pick was
  made on the recorded fixtures, not a live eval: `scripts/advisor/eval.mjs`
  does not run the daily prompt yet.
- **What is stored.** A model answer is kept only when both languages pass
  `acceptable`: no markdown, no `%`, "percent", "probab…", "chance", "odds",
  "por ciento", "probabilidad"; no rule number (the rules-guard pattern); no
  follow offer ("text you when", "want me to", "te aviso", "quieres que");
  with no skipper report, the landing's ladder label (kept in English in both
  languages, the only confidence words) and, in English, "no skipper
  reports". Anything else (an HTTP error, no API key, the global LLM cap, a
  refused answer) stores `composeDaily`, the same facts in the fixed
  `daily_*` strings (en and es). The composed answer stays for the day until
  the hash changes; it is a correct answer, only plainer.
- **The two fallbacks.** No skipper report but landing reports: "No skipper
  reports from the last three days. The landing reports {n} trips with
  {species} this week; recent reported activity: {label}." (or the model's
  wording with the same parts). Nothing at all: "No reports from the last
  three days for {port} yet." and the conditions, with no model call and no
  link (the follow offer is FR-3, Next). Advisories always lead, the event in
  capitals ("SMALL CRAFT ADVISORY posted for today.").
- **Failed feeds.** A feed that fails to load changes the hash but is not new
  information: when a row exists for today, it is served as it is, so a
  passing R2 or GitHub error never replaces a good answer with "Today's
  forecast isn't in yet". With no row, the degraded answer is made and stored,
  and the next read with both feeds back regenerates it.
- **Slot.** `SLOTS` has `daily-answers` at 05:30 America/Los_Angeles (01 §
  cron slots; the name replaces `advisor-digest` above). It runs
  `pregenerateDaily` for every port in `catalog/home-ports.json` whose region
  (the build's `REGIONS`) has `status: active`, today Morro Bay and Port San
  Luis, and throws when any port failed so `runSlot` releases the claim and
  the next tick retries (ports already stored are cache hits). Slot jobs now
  receive the cron deps (`CronDeps.daily`: feeds and fetcher, for tests).
- **Pre-router.** `dailyFlow`, the last Stage 2 flow (after TA-I3's), answers
  a text-only message that is exactly "what's biting", "what is biting",
  "how's the fishing", "qué está picando" or "cómo está la pesca" (after
  folding case, accents and punctuation; optional "hey/hola", an optional
  port after out of/at/in/en/de…, an optional today/hoy/lately), with the port
  from the text or `portForQuestion`. Only ports of active regions; a preview
  region's port, a species ("for lingcod") or any other qualifier goes to the
  model. A stored current answer costs no model call at all; a missing or
  stale one costs the one generation call, shared by everyone asking about
  that port today (the chat model is never called). The reply is in the
  turn's language. A contact (role `angler`) with no home port gets "Which
  port do you fish out of most? I'll keep my answers to it." once
  (`mark_once` `homeport.<contact_id>`, deleted by forget me); the model's
  `update_profile` saves the answer. Intents: `reports.daily.cache|model|composed`.
- **Elsewhere.** `get_port_report` returns `daily: {text, source:
  'stored'|'composed', note}`: the stored answer when current, else the
  composed one without a second model call and without storing it. The
  situation brief carries today's stored answer for the home port (else the
  region default's first port) when one exists. `rulesGuard`,
  `statesRuleNumber` and `stripMarkdown` moved to `reply.ts` (re-exported by
  `engine.ts`).
- **Cost note.** The hash includes the window's wind and seas, so a forecast
  update that changes those numbers regenerates the port's answer on the
  next question (one call per port per change).


## As built (TA-A2)

The planning brief is `server/advisor/answers/planning.ts` (`tripConditions`,
`planningBrief`, `advisoryLine`, `seasonFor`, `leadsWithAdvisory`, `fit`).
Where the code differs from § "Is Saturday worth going" above:

- **Exposure.** No `plan_trip` tool: `get_conditions` takes an optional
  `species` and then returns the brief as its `planning` field (the smaller
  change: one tool, one call, the `conditions` intent, no registry or role
  change). Without `species` it returns what it did (TA-E2), plus
  `advisory_line`. The signature is `planningBrief(env, {port, date, species,
  startHour?, endHour?}, {now, language, deps, contact, settings})`; 06's
  `boatType?` is not taken (the person's boat is unknown by text, so the
  comfort word stays the reference boat's).
- **Dates.** As TA-E2 (`parseTripDate`): English and Spanish weekdays, today/hoy,
  tomorrow/mañana, pasado mañana, this weekend/fin de semana (two days; on a
  Sunday only Sunday), `next <weekday>`, ISO. Beyond seven days the result has
  `beyond_horizon: true`, no conditions and no advisories, and `horizon_line`
  ("The forecast only reaches 7 days out, so I can't call the weather for Thu
  yet. Ask me again closer to the day."); the season and recent activity still
  come back.
- **Advisory first.** `advisory_line` is written in the reply language from the
  alerts that overlap each day's window: "SMALL CRAFT ADVISORY posted for Sat
  and Sun." / "SMALL CRAFT ADVISORY (aviso del NWS) para el sábado y el
  domingo." (gale first; the NWS event name stays English, in capitals). The
  closer is `planning.closer` ("Check the latest NWS forecast before you go." /
  "Revisa el pronóstico más reciente del NWS antes de salir."). The engine
  backstop is in 04 § As built (TA-A2).
- **Season.** `lookupRules` for the species (its own row, else its group's:
  a vermilion uses the rockfish row), checked with `seasonOpen` on every trip
  date: `open`, `closed` (on any of the dates) or `no_rule`, with `stale` and a
  line in the reply language. The lines carry no number (the season dates,
  sizes and limits are `get_rules`' to quote), so a planning call does not
  satisfy the rules guard; a stale row's line says "double-check"; no row says
  to check the current CDFW rules. The note puts a closed season right after
  the advisory.
- **Recent activity.** `dailyInputs` for the port and today (TA-A1's inputs:
  published skipper reports of three days, a verified boat by name, any other
  as "a boat"), narrowed to the species' count lines (at most three reports),
  and the landing's trips for the species in the seven days before today,
  labelled "reported by the landing". The brief reads each feed once (a
  per-call memo around the feed reader), so the conditions, the inputs and the
  ladder share one read.
- **Confidence.** One ladder word for the species asked about, not the region
  target: the landing's `reportEvidence` for the feed species the catalog files
  it under (vermilion → rockfish; `reef` stays the lingcod-and-rockfish group),
  so lingcod trips are not rockfish evidence. A published skipper report of the
  species in the three days lifts Insufficient to Low (positive reports exist,
  coverage weaker: `docs/bite-evidence.md`'s Low), never to Moderate. Dungeness
  is always Insufficient (boat reports are no crab evidence). The brief carries
  the word and `confidence_phrase` ("recent reported activity: Low" /
  "actividad reciente reportada: Low"; the word stays English, as in TA-A1) and
  no other confidence word; the prompt says to use the phrase exactly once.
- **Size.** The engine passes the model at most 4000 characters of a tool
  result (`TOOL_RESULT_MAX`, now in `tools/tool.ts`); a longer JSON would be cut
  and no longer parse, so `fit` drops the advisory headlines first, then the
  oldest skipper reports, then count lines past three.
- **Prompt.** RULES OF EVIDENCE has the planning order (advisory_line first, a
  closed season, conditions and comfort, the season line, reports with date and
  boat, `confidence_phrase` exactly once, the closer last; `horizon_line` past
  seven days); the planning few-shots (en, es) call `get_conditions` with the
  species.
