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
  optional port name).
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
