# 05. Skipper onboarding and content intake

Stories: SK-1…SK-5, SC-1…SC-5 (SC-6, SC-7 are Next), SP-3 (video), OP-2.
Code: `server/advisor/intake/skippers.ts`, `intake/reports.ts`, the
`register_boat`, `add_crew`, `read_count_board`, `propose_report`,
`edit_report`, `propose_post` tools, and the admin skipper pages (08).

## Becoming a skipper (SK-1)

Trigger: the person says they run a boat ("I'm the captain of the Rita G",
"register my boat", "soy el capitán…") or the engine's `register_boat` tool
is called, or an admin creates the boat and sends the invite.

The registration state machine asks one thing per text, in this order, and
accepts `skip` for optional fields:

| Step | Question (en) | Parse |
| --- | --- | --- |
| name | "What's the boat's name?" | 1–60 chars; strip quotes; title-case preserved |
| port | "Which port does she run out of?" | match against `catalog/home-ports.json` names and aliases (`catalog/advisor/port-aliases.json`: "MB", "Morro", "Avila", "Port San Luis", "PSL"); on no match list the three nearest ports in the region |
| landing | "Which landing? (skip if none)" | free text ≤ 60 |
| instagram | "Your boat's Instagram handle, so we can tag you? (skip if none)" | `@?[a-z0-9._]{1,30}`; stored without `@` |
| booking | "A booking link or phone for the boat page? (skip)" | https URL or a phone (stored as `phone_public`, never as a contact) |

On completion: `boat.create` action, `contact.role='skipper'`,
`contact.boat_id`, a `review.skipper` item with reason `new_skipper` (SK-4),
and the reply: "Got it. {name} is set up. Your reports will show on
skippercast.com/boats/{slug} once the team confirms the boat, usually same
day. Text me a photo of today's count board whenever you're in."

Then, immediately, the consent question (SK-2).

## Consent (SK-2)

Asked once when the boat is created and again only if revoked:
"One more thing: OK for SkipperCast to post your photos and videos on our
Instagram and Facebook, always credited and tagged to {name}? Reply YES."
`yes`/`sí`/`ok` → `consent_photos_at`, `consent_message_id`. Any other reply
→ consent stays null; photos still become reports and boat-page content, but
no social draft is created, and the engine says so once.
"stop posting my photos" / "revoke" → `consent_revoked_at`, every `draft`
or `approved` post for the boat is set `rejected`, posted ones stay (the
runbook tells the admin how to delete on Meta by hand).

## Crew (SK-3)

`add_crew {phone}`: hash the number; if a contact exists, link it; else
create a contact with `role='crew'`, `boat_id`, and send the invite through
the channel: "{skipper display name} added you as crew on {boat}. Text me
the day's count board or catch photos and they'll post under the boat.
Reply STOP to opt out." Crew submissions carry `boat_id` from the contact;
reports and media are credited to the boat, with the crew member's display
name only in the admin view. `remove_crew` sets `removed_at`; the contact
keeps its history but its `boat_id` is cleared and further photos are
treated as an angler's. Only the boat's `owner_contact_id` can add or remove.

## Verification (SK-4)

New boats are `verified_at = null`. Their reports publish (so the skipper
sees value immediately) but render with "unverified" on pages and are
excluded from the daily answer, the daily social post and `get_trips` until
verified. The admin queue item shows the boat fields, the contact's channel
and first messages, and an "approve" button that sets `verified_at`,
`verified_by`, re-renders the boat page and texts the skipper: "{name} is
verified. Your page: skippercast.com/boats/{slug}". Admin can also "reject"
(boat `status='rejected'`; the column is in 02) and the contact is told the
team will reach out.

## The boat page (SK-5)

`GET /boats/<slug>` (08 § pages): name, landing, port, verified badge, the
last 30 days of reports as a table (date, trip, anglers, counts kept/released,
"edited" marker when `version > 1`), the last 12 approved or posted photos
(derived public JPEGs, credited), booking link or phone, Instagram link,
and the "Text SkipperCast for today's report" CTA. Cached at the edge for
5 minutes with the existing `cached()`/`cacheKey()` helpers in
`server/edge-cache.ts`; `cacheKey` has no version slot, so the pages pass
`build: build() + ':' + pagesVersion`, where `pagesVersion` is the
`job_state` key `advisor.pages.version` (one D1 read per request; the
value is bumped on publish, edit and verification, which is the purge).

## Count-board photo → report (SC-1)

1. Media arrives from a skipper/crew contact. The consumer stores it and
   calls `vision.classify(media)` (07). Result `kind='count_board'` →
   `vision.readCountBoard(media)` returns the structured schema in 07.
2. `intake/reports.ts: draftFromBoard(result, contact, boat, now)`:
   - `report_date`: the board's date if read with confidence ≥ 0.8 and
     within 3 days, else today (local).
   - `anglers`, `trip_type` from the board when present.
   - `counts`: each line mapped to `species_key` by `catalog/advisor/species-synonyms.json`
     ("lings" → `lingcod`, "reds"/"vermilion" → `rockfish` with label kept,
     "WSB" → `white-seabass`, "halis" → `halibut`, "crab" → `dungeness`);
     unknown labels keep `species_key='other'` and their label.
   - Unique `(boat_id, report_date, 'count-board')` exists → treat as an edit
     (05 § corrections) instead of a new draft.
3. Reply with the summary and ask for confirmation (unless `auto_publish`):
   ```
   Rita G, Sat Oct 3, full day, 22 anglers:
   45 vermilion, 12 lingcod (2 released), 8 copper, 3 cabezon
   Reply Y to post, or tell me what to fix.
   ```
   Spanish equivalent when `language='es'`. Status `pending_confirm`.
4. `y` → `status='published'`, `verified` frozen from the boat,
   `published_at`, boat `clean_reports += 1` (reset to 0 on any edit before
   confirm), page cache bump, and the daily answer for the port invalidated
   (`inputs_hash` changes). Reply: "Posted. {{link:boat:<slug>}}".
5. The count-board photo itself gets `publish_state='queued'` with a
   `post.draft` (09) only when consent exists; count boards are good Story
   material (SP-4).

A board the vision step cannot read (`confidence < 0.5` or `kind='unknown'`)
gets: "I couldn't read that one. Can you send a clearer shot, or just text
me the numbers (e.g. '22 anglers, 45 vermilion, 12 lings')?"

## Plain-text report (SC-2)

The model's `propose_report` tool receives the parsed structure; the parser
helper `parseCountText(text)` in `intake/reports.ts` is deterministic and is
also tried first by the pre-router when the text matches
`/\b\d+\s*(anglers?|pax|people|personas)\b/i` or at least two
`<number> <species word>` pairs, so most reports never need the model.
Grammar accepted: comma/newline separated `<n> <label>` items, `(<n> rel)`
or `<n> released` suffix, `yesterday|ayer`, `half day|full day|overnight`,
`<n> anglers`. Anything unparsed is kept as `notes`. The same confirmation
flow follows.

## Catch and action photos → social draft (SC-3, OP-2)

`kind in ('fish','action','scenery')` from a skipper/crew contact with
consent → `post.draft` action (09 § drafts). The vision result's
`has_person=true` sets `media.publish_state='queued'` and opens a
`review.media` item with reason `has_person`; the draft cannot be approved
until that review is approved. Reply: "Nice. That's queued for the
SkipperCast feed, tagged @{instagram}. Count board too?" If the boat has no
Instagram handle, the reply asks for it once.

Videos (SP-3): `kind='video'` → if the container is MP4/MOV under 300 MB,
the draft is a Reel candidate; else reply with the upload link. No
transcoding in v1; a video Meta rejects is marked `failed` with the reason
and the admin can download it from the queue.

## Corrections (SC-4)

`parseCorrection(text, report)` recognises `(<label>|<species>) (were|was|is|=|:)?\s*<n>`,
`add <n> <label>`, `remove <label>`, `<n> anglers`, `it was (yesterday|<date>)`,
`half day|full day`. Applies to the most recent report by this boat in the
last 7 days (pending or published). Each change writes an
`advisor_report_edits` row, bumps `version`, resets `confirmed_at` if the
report was pending, and re-renders the page when published. Reply with the
corrected line only: "Updated: 14 lingcod (2 released)." Unparseable
corrections go to the model with the report in context and the `edit_report`
tool.

## Auto-publish (SC-5, Next but designed in)

When `clean_reports >= ADVISOR_AUTO_PUBLISH_AFTER` and `auto_publish=0`,
the next confirmation reply appends: "You've had {n} clean reports. Want me
to post your reports without asking? Reply AUTO." `auto` → `auto_publish=1`;
`ask me` → back to 0. Auto-published reports still send the one-line
summary so corrections stay easy.

## Weekly performance text (SC-7, Next)

Prerequisite: `advisor_post_stats` populated (09 § insights). Cron, Mondays
08:00 local: for each verified boat with activity, text: "Last week on
SkipperCast: {reports} reports, {posts} posts, {views} views, {profile_taps}
profile taps, {link_clicks} link clicks. Keep them coming." Skippers can opt
out with "no weekly".

## As built (TA-I1)

Registration, consent, crew and the verification state are in
`server/advisor/intake/skippers.ts` (the Stage 2 flow `skipperFlow`, registered
in `engine.ts` `STAGE_TWO_FLOWS`), the `register_boat`, `add_crew` and
`remove_crew` tools, and the consumer's new appliers. Where the code differs
from the text above:

- **State.** A pending question is `job_state` `advisor.flow.<contact_id>`,
  JSON `{flow: 'register' | 'consent', step, draft, asked_at, tries?}`, written
  only by the consumer (`flow_set` action). 04's "boat row lacks a required
  field" is not how registration is tracked: the boat row is created only on
  completion, so no half-registered boat ever exists.
- **Start.** The pre-router starts it without a model call on `register
  (my|a|our|the) boat`, `I'm/I am the captain|skipper`, `registrar mi barco`
  and `soy el capitán`; "… of/del <name>" fills the name. The Spanish phrases
  answer in Spanish. `register_boat` starts it with the fields the model
  extracted (invalid ones are dropped and asked again; `ignored` in the
  result); the system texts the next question itself, so the model is told to
  add one line at most. With every field given it completes at once. A
  contact that already owns a boat is told it is set up. Web visitors cannot
  register (the tool refuses; boats register by text).
- **Steps.** name → port → landing → instagram → booking, one per text.
  `skip` (also `none`, `no`, `n/a`, `saltar`, `ninguno`, …) answers the three
  optional steps. A port is a catalog id or name or a `port-aliases.json`
  alias; anything else gets "Reply with a number: 1) … 2) … 3) …" with the
  three ports nearest the contact's home port (else the first port of
  `ADVISOR_REGION_DEFAULT`), and a digit picks one. Three invalid answers to
  one question, or `never mind`/`olvídalo`, cancel the flow. A register flow
  whose question is more than 24 h old is deleted and the message goes on to
  the model (silently).
- **Validation.** Name 1–60 characters, quotes stripped, case kept; landing
  ≤ 60; Instagram `@?[a-z0-9._]{1,30}`, stored lower-case without `@`; booking
  an https URL (no credentials, ≤ 300) or a NANP number, stored in
  `phone_public`. Slug: ASCII from the name, ≤ 40, `-2`, `-3`, … on collision.
- **Completion.** 05's `boat.create` is the `boat_create` action: the boat
  (`status='pending'`, id derived from the message, so a retried message makes
  the same boat and keeps its slug), the contact's `role='skipper'` (an
  `admin-test` contact keeps its role), `boat_id`, and `home_port` when it had
  none; any crew link of that contact ends. Then `review_open` `skipper`
  `new_skipper` (which texts the admin, `notifyAdmin`), the completion text,
  the consent question and the consent flow. A registration done in the other
  language also stores that language.
- **Consent.** `yes`, `y`, `ok`, `sí`, `si`, `claro`, … while the question is
  pending (24 h) record `consent_photos_at` and `consent_message_id` (the
  inbound message id) and clear an earlier revocation. Any other reply:
  "No problem. Your photos will still go on your boat page and reports, but not
  on our social feeds." once, and the message itself goes on (a plain `no`
  gets only that line). Re-asking: a photo from the owner while consent is not
  active asks again when the last ask (or, with no record, the boat's
  creation) is 7 days old or more; the question is appended after the photo's
  reply. `post my photos` / `publica mis fotos` grants it at any time.
  `revoke`, `stop posting my photos`, `no publiques`, … set
  `consent_revoked_at` (the original consent stays on record) and emit
  `post_revoke`, which only logged until TA-S1; it now rejects the boat's draft
  and approved posts (09 § Drafts, As built (TA-S1)). Only the boat's owner can change consent; crew are told so.
- **Crew.** `add_crew` (owner only) hashes and encrypts the number and
  returns `{added: true}` only; it refuses the skipper's own number, a stopped
  or blocked contact, another boat's owner and more than 20 crew. The
  consumer's `crew_add` finds or creates the contact (a new one is an SMS
  contact in the skipper's language with `source='skipper-invite'`), sets
  `role='crew'` and `boat_id` (ending any other crew link), upserts
  `advisor_crew` with `added_by`, and texts the invite through the crew
  contact's own channel ("The skipper" when the skipper has no display name).
  The crew member's reply is a normal turn; their media carry the boat
  (`inbound.ts` already copies `contact.boat_id`). `remove_crew` (owner only)
  sets `removed_at` and clears the contact's `boat_id`, and a `crew` role goes
  back to `angler`. Both appliers re-check ownership.
- **Verification.** `ok <code>` / `no <code>` (08 § text admin) now also text
  the boat's owner: "{name} is verified. Your page: skippercast.com/boats/{slug}"
  or "We couldn't confirm {name} yet. Someone from the SkipperCast team will
  reach out." The shared helpers are `boatsForContact`, `isVerified`,
  `publicBoat` (a verified boat by name with its page link, otherwise "a boat")
  and `consentState`; `get_port_report` uses `publicBoat` on the report's
  frozen `verified`, `get_trips` lists `status='verified'` only. The boat
  page's "unverified" label and the daily answer/social exclusions belong to
  TA-W1, TA-A1 and TA-S1.
- **Brief.** For skippers and crew the contact brief has the boat name, whether
  they own it or crew it, its status (with the "a boat until verified" note
  when not verified) and the photo consent state; a registration in progress
  is listed so the model does not ask the questions itself.

## As built (TA-I2)

Reports are in `server/advisor/intake/reports.ts` (parsers, texts, the D1
writers the consumer runs, and the Stage 2 flow `reportFlow`, registered after
TA-I1's in `engine.ts` `STAGE_TWO_FLOWS`), the `read_count_board`,
`propose_report` and `edit_report` tools, and the consumer's appliers
(`report_draft`, `report_publish`, `report_withdraw`, `report_edit`,
`auto_publish`, `media_queue`, `boat_instagram`, `mark_once`). Where the code
differs from the text above:

- **Who.** Only a phone contact whose `boat_id` is a boat it owns or crews
  (`boatsForContact`). Crew reports carry the boat and their own `contact_id`;
  only the owner can switch AUTO / ASK ME or is asked for the Instagram handle.
- **Pending confirmation.** A report waits for a reply while `pending_confirm`
  and updated in the last 24 h. `y`, `yes`, `ok`, `sí`, `publish`, `post it`,
  `looks good`, `publica`, … publish; `n`, `no`, `don't post`, `cancelar`, …
  withdraw. **`cancel` is not a withdraw word**: 04 lists it, but it is a
  Stage 1 STOP command (04 § commands) and Stage 1 runs first; withdrawing
  would need that table changed, which this task does not do. A parseable
  correction edits and re-asks ("Updated: … Reply Y to post, or tell me what to
  fix."); anything else goes to the model, whose contact brief carries the
  pending report with its `report_id` (or the latest report of the last 7 days).
- **Count text.** The pre-router tries `parseCountText` when 05's trigger
  matches (`<n> anglers|pax|people|personas`, also `pescadores`, `clientes`,
  `fishermen`) or the text parses to two lines with known species. Extra
  grammar: `;`, ` and `/` y `/`&`/`+` separators, items without commas
  (`45 vermilion 12 lings`), `today/hoy`, `3/4 day`, Spanish trip words
  (`medio día`, `día completo`, `nocturno`), `liberados`/`sueltos`, and a bare
  `<n> <label> released` meaning all released. Numbers followed by units
  (`3 hrs`, `58 degrees`, `12 lb`) go to `notes`. While a report is pending, a
  count text without anglers is read as a correction of those lines, not a new
  report.
- **Species keys.** Labels map through `answers/resolve.ts` (species synonyms and
  the catalog) and are filed under the catalog parent (`reportSpeciesKey`:
  vermilion, copper → `rockfish`); cabezon and kelp greenling keep their own
  keys; unknown labels are `other`. The skipper's label is always kept and shown.
- **Uncertain lines.** Lines below the 07 acceptance thresholds
  (`decideAcceptReading`) or with no readable count are stored with
  `uncertain: true` and shown as `12? lingcod` / `? copper`; correcting a line
  clears its mark, and publishing drops every mark. An uncertain line also stops
  auto-publish for that report (it asks first).
- **Same day.** 05 says a same `(boat, day, 'count-board')` report is an edit.
  As built, any live report (pending or published) of the boat for that day,
  **of either source**, takes a new board or text as an edit (one live report
  per boat and day, so a board and a typed report of the same trip never both
  publish); a withdrawn one of the same source comes back as pending. The
  consumer's `insertDraft` does the same if the unique index would collide after
  the engine read (a race). A report the team rejected is not reopened; the
  skipper is told it was held. A published report edited this way stays
  published and the reply shows the updated summary.
- **Publish.** `verified` frozen from `advisor_boats.status='verified'`,
  `confirmed_at`/`published_at`, `job_state` `advisor.pages.version` + 1, and the
  port's `advisor_daily_answers` rows are **deleted** (05 step 4 says the
  `inputs_hash` changes; TA-A1 owns the hash, so deleting makes it regenerate).
  `clean_reports` + 1 only on a confirm of an unedited report (`version = 1`);
  any edit while pending resets it to 0; edits after publishing leave it alone.
- **Corrections.** Applied to the pending report, else the boat's latest of the
  last 7 days (pending or published). Grammar as 05 plus Spanish (`los lingcod
  eran 14`, `quita cabezon`, `fueron 20 personas`, `fue ayer`), several parts per
  text (`lings were 14 and cabezon 4`), `overnight`, and dates as today/yesterday,
  weekday names, M/D, `Oct 2`, `2 de oct` within 7 days. A species word that names
  two lines ("rockfish 50" with vermilion and copper) is ambiguous and goes to the
  model. Moving a report onto a date the boat already has (same source) is
  refused with a message. The reply names the changed lines in the skipper's own
  label ("Updated: 14 lings."); 05's example uses the board's label.
- **Auto-publish (SC-5).** Dark by default only in effect: the offer appears after
  a clean confirm when `clean_reports >= ADVISOR_AUTO_PUBLISH_AFTER` (default 5,
  01) and `auto_publish = 0`, once per boat (`job_state` `advisor.once.autopub.<boat>`);
  `ADVISOR_AUTO_PUBLISH_AFTER=0` never offers. `auto` / `ask me` (es `automático`,
  `pregúntame`) toggle it. An auto-published report gets "Posted: <one line>. Text me
  any fix. <link>", no `confirmed_at`, and does not count as a clean report.
- **Media from a skipper or crew contact.** Each stored item of a media-only
  message in order: `classify` (07) → a count board (`decideCountBoard`) →
  `readCountBoard` → `draftFromBoard` → the confirmation; one report per message.
  An unreadable board (`decideReadingUsable` fails) gets 05's "couldn't read"
  text; vision unavailable asks for the numbers by text. A classification that is
  not a board, fish, action or scenery photo gets a fixed "count board or catch
  photo?" question instead of a model call. `MediaTooLarge` and any file the intake
  rejected (over 300 MB, an unknown container) get the upload link and a log line
  (the TA-M1 wait for `public.jpg` is not built). A photo with a caption goes to the
  model with its `media_id`, so `read_count_board` can read it.
- **Photos and videos.** With consent, `fish`/`action`/`scenery` photos, videos
  and the count-board photo itself are set `publish_state='queued'` with the boat
  as `credit`; `has_person` (or `nsfw`) opens a `review.media` item (`notifyAdmin`
  texts the admin). The `post.draft` rows (09) are TA-S1's: nothing in
  `advisor_posts` is written here, and a video is only logged as a Reel candidate
  (`advisor_reel_candidate`). As built (TA-S1): the consumer's `media_queue`
  applier now also makes the post draft (a video a Reel, the count-board photo a
  Story) with its `post` review; `has_person` holds the draft's approval, not the
  draft (09 § Drafts, As built (TA-S1)). Replies: 05's "Nice. That's queued for the SkipperCast
  feed, tagged @{instagram}. Count board too?"; without a handle the owner is asked
  once (`@handle`, or a bare handle within 24 h, saves it); crew get the untagged
  wording. Without consent nothing is queued and a no-consent line is sent at most
  once per 7 days per boat (`advisor.once.noconsent.<boat>`), a plain thanks
  otherwise. A turn that leaves a report waiting for Y never also carries TA-I1's
  consent re-ask, so the skipper's "Y" cannot answer the wrong question.
- **Tools.** `read_count_board {media_id}` reads one of the contact's own stored
  photos; `propose_report` takes the 04 schema but maps labels to species itself
  (the model's `species_key` is ignored) and accepts `report_date` words within 7
  days; `edit_report {report_id, patch}` takes `patch` as a list of changes
  (`{label, kept?, released?}`, `{label, remove: true}`, or `{field, value}` for
  anglers, trip_type, report_date, notes) rather than 04's untyped object. All
  three produce the same actions and texts as the deterministic path, and the
  system sends the draft or the corrected lines itself.
