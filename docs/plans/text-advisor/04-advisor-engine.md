# 04. The advisor engine

`server/advisor/engine.ts` exports one function:

```ts
export async function runTurn(input: {env: Env; contact: Contact; message: StoredInbound; now: number; deps: EngineDeps}): Promise<EngineResult>
```

`EngineDeps` carries injectable `fetcher`, `vision`, `clock` and `random` so
every test runs offline and deterministic, the same way `lookupBoat` takes a
`fetcher`. `EngineResult` is `{actions: Action[]; intent: string; usage: LlmUsage; model: string | null}`.

The consumer applies the actions (01 § request flow). The engine never
touches D1 for writes itself except through the tool executors, which return
actions rather than writing, so a crash before the apply step leaves nothing
half-done.

## Stage 0: guards (no model call)

In order; the first that applies ends the turn.

0. `ADVISOR_REPLIES_ENABLED=false` → store, mark the inbound `held`, no
   model call, no reply (the soft kill switch, 11).
1. `contact.status === 'blocked'` → drop silently.
2. Daily cap (OP-3): `messages_today >= ADVISOR_DAILY_MESSAGES_PER_CONTACT`
   → one reply per day: "You've hit today's limit with me. Back tomorrow, or
   see skippercast.com/<port>." Record `intent = 'capped'`.
3. Global LLM cap reached → "I'm swamped right now. Try again in a bit, or
   see skippercast.com." (`intent = 'global_cap'`). Checked with the same
   `request_limits` UPSERT…RETURNING idiom as `routes/boat.ts`.
4. Group chat → "I only work in one-to-one chats. Text me directly." once
   per group per day.

## Stage 1: commands and language (no model call)

Exact-match commands after trimming and lower-casing, in any language listed:

| Input | Action |
| --- | --- |
| `stop`, `stopall`, `unsubscribe`, `cancel`, `end`, `quit`, `alto`, `parar` | set `stopped`; reply "Done. You won't hear from me unless you text START." (es: "Listo…") |
| `start`, `unstop`, `yes` (when stopped), `empezar` | set `active`; reply the welcome |
| `help`, `ayuda`, `?` | the help text (what you can ask, STOP, "forget me", link) |
| `forget me`, `delete my data`, `olvídame`, `borra mis datos` | ask "Reply DELETE to erase everything I have about this number. This can't be undone." then on `delete` run the 02 § forget-me procedure |
| `send me my data`, `export`, `mis datos` | export action |

Language: `detectLanguage(text)` is a stopword-ratio heuristic over `en`/`es`
(≥ 3 Spanish function words and more Spanish than English → `es`). A single
message switches the reply language; the contact's stored `language` changes
after two consecutive messages in the other language (FC-6). Media-only
messages inherit the stored language.

## Stage 2: deterministic flows (no model call, or a vision call only)

Some states are a state machine, not a conversation, and must not depend on
the model doing the right thing:

- **Pending confirmation** (`advisor_reports.status = 'pending_confirm'` for
  this contact's boat, created in the last 24 h): `y`, `yes`, `ok`, `sí`,
  `publish` → publish; `n`, `no`, `cancel` → withdraw; a message that parses
  as a correction (05 § corrections) → apply and re-confirm; anything else
  falls through to the model with the pending report in context.
- **Registration in progress** (`contact.role='skipper'` and the boat row
  lacks a required field): the intake flow asks the next missing field
  (05 § registration) and parses the answer; "skip" is allowed for optional
  fields.
- **Consent prompt outstanding** (boat has no `consent_photos_at` and a photo
  just arrived): the consent question is asked once per 7 days; `yes` records
  it with the message id.
- **Media-only message from a skipper or crew contact** → intake: vision
  reads it (07); a count board becomes a report draft, a catch/action photo
  becomes a social draft (05). No chat model call unless the vision result is
  ambiguous (`kind='unknown'`), in which case the model asks what it is.
- **Media-only message from an angler** → fish ID flow (06) when the image
  classifies as `fish`; otherwise "Nice shot. Want me to ID a fish, or can we
  share this with credit?" (AC-1).
- **Upload-link request** (`send me a link`, `link`, or an SMS skipper's
  photo under 200 KB) → mint the upload token (03) and reply with it.

Each flow records its own `intent` (`report.count_board`, `report.text`,
`consent.yes`, `skipper.register.<field>`, `fishid`, …).

## Stage 3: the model turn

Everything else goes to Claude (`ADVISOR_MODEL`) with tools. Request shape
(raw `fetch` to the Messages API, `anthropic-version: 2023-06-01`, same
headers and `pause_turn` handling as `lookupBoat`):

- `system`: `prompts/system.ts` (below) + the **contact brief** (role, boat,
  language, home port, targets, display name, whether a report is pending,
  whether they are a new contact) + the **situation brief** (today's date and
  weekday in America/Los_Angeles, the region, the port's daily answer if
  generated, active advisories headline, relay channel capabilities).
- `messages`: the last 12 turns or 48 hours of this contact's conversation,
  whichever is smaller, as alternating user/assistant text; images are not
  replayed (vision results are summarized as text in the user turn: "[photo:
  classified as count board, 22 anglers…]").
- `tools`: the set below, filtered by role (anglers never see skipper tools;
  nobody sees admin tools).
- `max_tokens: 700`, `temperature: 0.3`.
- Loop: at most 4 tool rounds, 30 s total; a fifth `tool_use` is not
  executed: the last text is the reply or, if none, "Let me check on that and
  get back to you" plus a `review.conversation` action with reason `tool_loop`.

The reply is the final assistant text, post-processed: strip markdown, cap
at 3 SMS segments unless the intent is a list, append at most one link (the
model emits links as `{{link:port:morro-bay}}` placeholders that
`links.ts` resolves to real URLs, so it cannot invent URLs), and run the
**rules guard**: a regex sweep for numbers next to `inch`, `"`, `limit`,
`bag`, `season`, `closed`, `open` in a reply where no `get_rules` tool was
called → replace the sentence with "Check the current CDFW rules for that:
{{link:rules}}" and open a `review.conversation` with reason
`rules_without_tool`. This guard is a hard backstop for principle 4; the
prompt is the first line of defence and the tests cover both.

### Tools (`server/advisor/tools/*.ts`)

Each file exports `{name, description, input_schema, run(input, ctx) => Promise<{result: unknown; actions?: Action[]}>}`.
`ctx` has the env, contact, message, deps and a read-only D1 handle. Results
are compact JSON; descriptions tell the model when to use the tool and what
it may not do without it.

| Tool | Who | Reads / proposes |
| --- | --- | --- |
| `update_profile` | all | `{display_name?, home_port?, targets?, language?}` → `contact.update` action. The model is told to ask for home port and targets *once*, naturally, on the first substantive question (FC-2). |
| `get_port_report` | all | `{port}` → daily answer text (FR-1), latest 5 skipper reports (date, boat, counts, verified), landing-report confidence from the daily feed (`landing-reports`, labelled as such), freshness. Never a catch probability (FR-4). |
| `get_conditions` | all | `{port, date}` → wind, gust, seas, period, swell direction for the trip window from the regional forecast feed (`readFeed` of `forecast`/`intelligence` as `server/trips.ts` does), plus the small-craft/gale status from NWS alerts in the daily feed (AD-4). |
| `get_rules` | all | `{species_key, region}` → active `advisor_rules` rows with source and reviewed date; rows in `review` state come back flagged `stale: true` and the model must say "double-check" (ID-2, OP-6). |
| `get_species` | all | `{species_key}` → `catalog/species.json` claims (habitat, depth, season notes, look-alikes from `catalog/advisor/lookalikes.json`). |
| `get_strategy` | all | `{species_key, region}` → `primary-strategies.json` / `search-methods.json` summary: rig, bait or lure, line, weight, depth band, general areas and named public grounds from `charter-grounds.json`. Never a coordinate (AD-1, AD-2). |
| `get_trips` | all | `{port}` → verified boats with trip types, landing, booking link, boat page link (AD-3). |
| `identify_fish` | all | `{media_id}` → vision fish ID result (07): species candidates with confidence, cues, and a `needs_better_photo` flag (ID-1, ID-3). |
| `read_count_board` | skipper, crew | `{media_id}` → structured counts (07) → `report.draft` action (05). |
| `propose_report` | skipper, crew | `{report_date?, anglers?, trip_type?, counts:[…], notes?}` from plain text (SC-2) → `report.draft` action. |
| `edit_report` | skipper, crew | `{report_id, patch}` (SC-4) → `report.edit` action. |
| `propose_post` | skipper, crew | `{media_id, hint?}` (SC-3) → `post.draft` action (09 § drafts). |
| `register_boat` | all (makes them a skipper) | `{name, landing?, port, instagram?, booking_url?}` (SK-1) → `boat.create` action and the consent question (SK-2). |
| `add_crew` / `remove_crew` | skipper | `{phone}` (SK-3) → `crew.add` sends the invite text to the crew number through the channel; crew is linked when they reply. The phone goes straight to hashing; the model never sees it echoed back. |
| `share_angler_photo` | angler | `{media_id, consent: boolean}` (AC-1) → review item `angler_photo` when consent is yes. |
| `send_upload_link` | all | → `{url}` (03). |
| `send_contact_card` | all | → `card.send` action (FC-3). |
| `offer_text_link` | web only | asks for the phone, `{phone}` → the 6-digit code flow (03 § web). |
| `escalate` | all | `{reason}` → `review.conversation`; reply "I've flagged this for the team." |

Admin actions (verify a skipper, approve a post, change a rule, publish)
have no tool. The engine proposes; `routes/admin.ts` decides.

### Intent recording

`intent` is the pre-router's label when a Stage 1–2 path answered, otherwise
the first tool called (`report.*`, `fishid`, `rules`, `conditions`,
`strategy`, `trips`, `profile`), or `chat` when no tool was used, or
`refused` when the model used the refusal template. The funnel dashboard
groups on it (OP-5).

## The system prompt (`prompts/system.ts`)

Written in full in the task that builds the engine (TA-E1) and reviewed by
the owner in that PR; the required content is:

- **Identity and voice.** "You are SkipperCast, a professional fishing
  advisor for the California Central Coast, texting from the dock. Friendly,
  direct, short. You sound like an experienced captain who respects people's
  time." Never claims to be human; if asked, says it is SkipperCast's
  automated advisor with a team behind it.
- **Format.** Plain text, no markdown, no emoji unless the person uses them,
  under 480 characters unless listing trips or boats, one question at a time,
  one link at most, placeholders only for links.
- **Rules of evidence.** Reports are dated and attributed; say how fresh
  (FR-4). Never state odds or a bite score. Never give a skipper's spot;
  general areas and depths only. Regulations only from `get_rules`; if the
  tool returns nothing or `stale`, say to check CDFW and give the rules link.
  Safety: if `get_conditions` shows an advisory, lead with it (AD-4).
- **Honesty.** "Not sure" beats a guess (ID-3). Confidence words map to the
  tool's numbers (`high ≥ 0.85`, `medium ≥ 0.6`, else ask for another angle).
- **Scope** (OP-4). Fishing, boats, the coast, SkipperCast. Off-topic or
  unsafe requests: one line, "I only do fishing. Ask me what's biting, send a
  fish photo, or ask how to rig for something." Harassment or threats:
  "I'm going to stop here." and `escalate`.
- **Language.** Reply in `{{language}}`. Spanish replies use the same
  register (tú), fishing terms as local crews use them.
- **Skippers.** Treat them as customers: thank them, confirm what you'll do
  with the content, and tell them where it will show (their boat page, the
  SkipperCast feed with their boat tagged).
- **Onboarding.** For a new contact, answer first, then ask the one question
  that improves future answers (home port, then targets). Never ask both at
  once. Never ask again once stored.
- **Funnel.** When the text can't hold the answer (maps, charts, all boats),
  link to the matching page (WH-1). When a web visitor asks for something
  worth keeping, offer to text it (WH-2).

Few-shot examples (`prompts/examples.ts`): six short exchanges covering a
first contact, a "what's biting", a trip-planning question with an advisory,
a fish ID with rules, a rig question, and a refusal. Spanish versions of the
first three.

## Spend and caps

- Per contact per day: `ADVISOR_DAILY_LLM_PER_CONTACT` model calls (a turn
  with 3 tool rounds counts once) and `ADVISOR_DAILY_MESSAGES_PER_CONTACT`
  inbound messages.
- Global per day: `ADVISOR_GLOBAL_DAILY_LLM`; vision separately
  (`ADVISOR_GLOBAL_DAILY_VISION`, Claude provider only).
- Prompt caching: the system prompt and tool definitions are marked
  `cache_control: {type: 'ephemeral'}` so repeated turns pay the cached rate.
- Daily answers (FR-1) are generated once per port per day by cron and
  served from `advisor_daily_answers`; a "what's biting" needs no model call
  when the cached answer exists and the question has no qualifier (the
  pre-router matches `what's biting|how's the fishing|qué está picando` +
  optional port name; TA-A1 adds `cómo está la pesca`, 06 § As built (TA-A1)).
- Every model call writes an `llm` analytics point (`feature =
  'advisor:' + intent`, `outcome`, model, tokens, turns) and one
  `console.log` line, like `recordLookupUsage`.

## Tests (`tests/test_advisor_engine.mjs`, `test_advisor_tools.mjs`, `test_advisor_prompts.mjs`)

- Guards and commands: table-driven, no fetcher.
- Deterministic flows: a pending report + `y`, + a correction, + nonsense.
- Model turns: a fake fetcher replays recorded responses from
  `tests/fixtures/advisor/engine/<case>.json` (request → response pairs,
  including a tool-use round). Cases: the six few-shots plus `rules_without_tool`
  (guard fires), `tool_loop` (a fifth tool_use → escalate), `pause_turn`, HTTP 529.
- Prompt tests: the system prompt contains each required phrase above; no
  fixture contains a non-fictional phone number (the 02 § privacy regex),
  enforced by `test_advisor_privacy.mjs`.
- An opt-in live eval `scripts/advisor/eval.mjs` (needs `ANTHROPIC_API_KEY`,
  never in CI) runs the fixture prompts against the real model and prints a
  diff for a human to judge before changing prompts.

## As built (TA-E1)

`server/advisor/engine.ts` exports `runTurn` and `engineHandler` (the
consumer's `Handler`, wired in `server/index.ts`, `inbound.ts`'s inline runner
and the web chat route). Where the code differs from the text above:

- **Signature.** `runTurn({env, contact, message, now, deps, signal})`:
  `contact` and `message` are the D1 rows (`AdvisorContactRow`,
  `AdvisorMessageRow`), and `signal` is the consumer's 45 s hard stop. The
  consumer passes `deps.engine` (`EngineDeps`: `fetcher`, `clock`, `random`,
  `sleep`; `vision` is reserved for TA-I2/I3).
- **Writes.** The engine writes only counters before replying: the
  `request_limits` caps and `advisor_contacts.messages_today/messages_day`
  (recomputed from today's inbound rows, so a retried message counts once).
  Everything else is an action.
- **Stage order.** Soft switch, blocked, stopped (only START gets through),
  then the commands, then the daily message cap, then Stage 2, then the LLM
  caps and the model. STOP, START, HELP, forget me and the data export work
  past the daily cap (carriers require STOP and HELP to work). The per-contact
  LLM cap (`ADVISOR_DAILY_LLM_PER_CONTACT`) and the global cap are counted
  just before the model call, with the `request_limits` UPSERT…RETURNING idiom
  (keys `advisor-llm:<contact>:<day>` and `global:advisor-llm:<day>`, UTC
  day). Each capped reply goes out once a day; the global one ("swamped")
  every time.
- **Group chats** never reach the engine: the adapters drop them (03 §
  BlueBubbles "As built"), so stage 0 step 4 has no code.
- **No API key.** Without `ANTHROPIC_API_KEY` the model turn answers the
  warm-up text (intent `unconfigured`), as the stub did.
- **Commands.** `server/advisor/intents.ts` `COMMANDS`: the 04 table, plus
  `olvidame` (no accent), `borrar` (the Spanish DELETE the Spanish prompt asks
  for) and the upload-link words (`send me a link`, `link`, `mándame un
  enlace`, `enlace`). `yes` is START only for a stopped contact. DELETE runs
  forget only when the contact's previous inbound message (within 24 h) was
  answered with the forget prompt (`intent = 'forget.ask'`). On Twilio SMS the
  engine skips its own STOP confirmation (Twilio sends one and refuses ours
  with 21610). HELP is the runbook's wording, word for word.
- **Language.** `detectLanguage` returns `null` when it cannot tell (short or
  mixed text); `null` keeps the stored language. A message in a `¿`/`¡`/`ñ`
  with one Spanish word and no English one also counts as Spanish. A Spanish
  command (`alto`, `ayuda`, …) is answered in Spanish.
- **Welcome.** The first reply to a brand-new phone contact (no earlier
  message) starts with the welcome ("… Msg & data rates may apply. Reply HELP
  for help, STOP to opt out.") and the contact card (a file on iMessage, the
  `/contact.vcf` link on SMS), once. Web visitors get neither.
- **Stage 2.** Built here: the text admin fallback (08), the web phone-link
  code (03 § web), the upload link, and media-only messages, which get a short
  acknowledgement until TA-I2/I3. `STAGE_TWO_FLOWS: Flow[]` is the extension
  point TA-I1 (registration, consent) and TA-I2 (pending confirmation,
  corrections, count text) push into; registered flows run after the built-in
  ones and before the model.
- **Stage 3.** The system is two blocks: the prompt with few-shots (one per
  reply language, `cache_control: ephemeral`) and the contact + situation
  brief (uncached). The last tool definition carries `cache_control`, so the
  tool list is cached with the prompt. History is the last 12 rows or 48 h,
  whichever is fewer; failed outbound rows are skipped; consecutive same-role
  rows are joined so the turns alternate; photos are `[photo]` notes. 429 and
  529 are retried once after 2 s; any other HTTP error throws, so the consumer
  retries the message. `pause_turn` is continued up to 3 times and its text is
  joined to the continuation. The 30 s budget ends the loop like a fifth
  `tool_use`: the last text, or "Let me check on that and get back to you."
  with a `conversation` review (reason `tool_loop`, or `model_timeout` for the
  budget).
- **Post-processing order.** Strip markdown → rules guard (only when no
  `get_rules` call returned data; an `unavailable` stub does not count) →
  links (the first valid placeholder becomes a URL, the rest are dropped with
  their "see"/":" lead-in) → the 480-character cap (sentence boundaries, the
  link kept at the end) unless the intent is `trips`. The guard removes every
  rule-like sentence and puts the CDFW line in place of the first.
- **Intent.** `refused` when the reply starts with the refusal or the abuse
  line (en or es); otherwise the first tool's intent, else `chat`. Stage 0–2
  intents: `held`, `blocked`, `stopped`, `capped`, `global_cap`, `stop`,
  `start`, `help`, `forget.ask`, `forget`, `export`, `upload_link`, `media`,
  `empty`, `unconfigured`, `admin.*`, `link.*`.
- **Tools.** Every tool in the table exists in `server/advisor/tools/`, with
  its final name, roles and `input_schema`; the shared types are in
  `tools/tool.ts` (so tool files never import the registry). Built here:
  `update_profile`, `escalate` (reasons `refused`, `abuse`,
  `prompt_injection`, `low_confidence`, `complaint`, `needs_human`),
  `send_upload_link`, `send_contact_card`, `offer_text_link`. The data tools
  (TA-E2, `identify_fish` TA-I3) and skipper tools (TA-I1/I2/I3) are stubs
  answering `{unavailable: true, reason: 'not built yet'}`. Crew see the
  report tools but not `add_crew`/`remove_crew`; `share_angler_photo` is for
  anglers only; `admin-test` contacts see the angler set.
- **New actions** (`types.ts`), applied by the consumer: `set_status`
  (`applyStop`/`applyStart`), `forget` (the confirmation text, then
  `forgetContact`), `export` (`exportContact` → R2
  `advisor/exports/<contact_id>/<local date>.json` → a text with
  `GET /api/advisor/export/<token>`, token
  `base64url(contact_id|key|expiry|HMAC(upload subkey))`, 24 h, in
  `server/advisor/exports.ts`), `send_file` (inline bytes or an R2 key;
  BlueBubbles attaches it through the new `OutboundMessage.files`, every other
  channel gets the caption and the fallback link), `link_start`, `link_merge`
  and `admin_review`.
- **Web phone link.** `offer_text_link` checks the number (`e164`), 3 codes per
  web visitor per day (`request_limits`), and returns a `link_start` action
  with the phone hash, the encrypted number, `sha256(code)` and the expiry
  (10 minutes). The consumer creates (or finds) the phone contact, stores
  `{code_hash, expires_at, phone_contact_hash, phone_contact_id}` in
  `job_state` `advisor.link.<web contact id>`, and texts the code through the
  phone contact's own channel (the outbound row stores the text with the code
  masked). Six digits from that web visitor then run the check (5 guesses a
  day); a match merges: messages, media and reviews move to the phone contact,
  the web session moves to it (so the chat keeps working, and the web route
  reports `linked: true`), the web contact and the `job_state` row are
  deleted.
- **Text admin.** `ok|no <6 hex>` from the contact whose id is
  `ADVISOR_ADMIN_CONTACT_ID` and whose role is `admin-test`, for exactly one
  open `skipper` or `media` review. `skipper`/`new_skipper` sets
  `advisor_boats.status` `verified` (with `verified_at`) or `rejected`; other
  skipper reasons only decide the review. `media` sets `publish_state`
  `approved`/`rejected`. `notifyAdmin(env, review)` texts that contact for each
  newly opened `skipper` or `media` review, through its own channel.
- **Strings.** Every engine text is in `catalog/advisor/strings.json` (en and
  es), read through `server/advisor/strings.ts` `t(language, key, vars)`.
- **Eval.** `scripts/advisor/eval.mjs` runs the fixture messages against the
  live model (needs `ANTHROPIC_API_KEY`; never in CI) and prints recorded vs
  live replies with the format checks.

## As built (TA-E2)

- The data tools replace their stubs (06 § As built (TA-E2)); `identify_fish`
  and the skipper tools are still stubs. `EngineDeps.feeds` (the feed reader)
  is new, for offline tests.
- Prompt: RULES OF EVIDENCE now tells the model to end a reply with "General
  areas only; I don't share anyone's numbers." when `get_strategy` returns
  `first_time: true`, to leave out any field a tool left empty, and to say
  "the boats I work with so far" when `get_trips` returns `few: true`; the
  three are in `REQUIRED_PHRASES`. The owner should read the two new lines.
- The recorded `whats-biting` and `trip-planning-advisory` fixtures now run
  the real tools on `tests/fixtures/feeds/` (the alert moved to the test day):
  the first cites the landing's report with its Low label; the second starts
  with "SMALL CRAFT ADVISORY" and has no percentage.


## As built (TA-I1)

- `STAGE_TWO_FLOWS` starts with the skipper flow (`intake/skippers.ts`;
  05 § As built (TA-I1)). Registration in progress is tracked in `job_state`
  `advisor.flow.<contact_id>`, not by a boat row missing a field (Stage 2's
  second bullet above): the boat is created only when registration completes.
- `FlowContext.carry` is new: actions a flow needs whatever answers the turn
  (deleting a stale flow, the one-time consent decline line, a consent re-ask
  after a photo). They go after the language update on the model path and
  after the acknowledgement of a media-only message.
- When a tool already texted (register_boat's next question) and the model
  adds no text, no "not understood" filler is sent.
- New actions: `boat_create` (05's `boat.create`), `flow_set`, `consent`,
  `post_revoke` (logs until TA-S1), `crew_add`, `crew_remove`; the contact
  brief lists the boat, ownership or crew, status and consent.

## As built (TA-I3)

- `STAGE_TWO_FLOWS` ends with the angler flow (`intake/anglers.ts`; 06 § As
  built (TA-I3)): the media-only angler path (classify, then the fish ID or
  "Nice shot…") and the AC-1 pre-router (YES within 24 h of the offer, the
  credit reply, `id` after "Nice shot"). No model call on these paths; the
  intents are `fishid.high|medium|ask|unavailable`, `media.nice_shot`,
  `photo.share`, `photo.credit`.
- A photo with a caption goes to the model with its `media_id` for every role
  (TA-I2 did this for skippers and crew only), so `identify_fish` and
  `share_angler_photo` can read it.
- An `identify_fish` result with a current (not stale) rules row counts as a
  usable rules call for the rules guard.
- `capReply` and `REPLY_MAX` moved to `server/advisor/reply.ts` (re-exported
  by `engine.ts`) so the fish-ID answer is capped the same way.
- New actions: `share_state` (the offer in `job_state`) and `angler_share`.

## As built (TA-A1)

- `STAGE_TWO_FLOWS` ends with the daily pre-router (`answers/reports.ts`
  `dailyFlow`; 06 § As built (TA-A1)): the plain "what's biting" forms, with
  an optional port of an active region, are answered from
  `advisor_daily_answers` with no chat model call (one shared generation call
  when today's answer is missing or stale), then the home-port question once.
  Intents `reports.daily.cache|model|composed`.
- The situation brief's "today's port answer" line carries the stored answer
  for the home port (else the region default's first port) when one exists.
- `get_port_report` returns `daily` (`{text, source, note}`), never starting a
  second model call inside a turn.
- `rulesGuard`, `statesRuleNumber` and `stripMarkdown` live in `reply.ts`.
- The `whats-biting` engine fixture now asks a nuanced question ("any
  lingcod?"), since the plain one never reaches the model; the stage 3 caps
  test does the same.


## As built (TA-A2)

- `get_conditions` takes `species` and returns the planning brief (06 § As
  built (TA-A2)); it always returns `advisory_line` in the reply language when
  there is an advisory.
- **Advisory backstop** (AD-4), after the rules guard and before links: when a
  turn's first `get_conditions` result had `lead_with_advisory` and the reply's
  first sentence does not name one of its events in capitals ("SMALL CRAFT
  ADVISORY"; a Spanish "Hay SMALL CRAFT ADVISORY…" passes), the engine puts
  `advisory_line` in front and logs `advisor_advisory_backstop`. Deterministic,
  like the rules guard; no review is opened. The 480-character cap keeps
  sentences from the start, so the advisory survives it.
- `TOOL_RESULT_MAX` (4000) lives in `tools/tool.ts`; the engine and the
  planning brief share it.
- New engine fixtures `trip-planning-brief` (the reply leads; no backstop) and
  `trip-planning-backstop` (the reply does not lead; the line is put first and
  logged); the model-turn runner checks `expect.log` / `expect.log_not`.
