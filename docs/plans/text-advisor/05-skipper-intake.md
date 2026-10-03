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
(boat stays, flagged `rejected` in a `status` column added to the boat in
0006: `pending`, `verified`, `rejected`) and the contact is told the team
will reach out.

## The boat page (SK-5)

`GET /boats/<slug>` (08 § pages): name, landing, port, verified badge, the
last 30 days of reports as a table (date, trip, anglers, counts kept/released,
"edited" marker when `version > 1`), the last 12 approved or posted photos
(derived public JPEGs, credited), booking link or phone, Instagram link,
and the "Text SkipperCast for today's report" CTA. Cached at the edge for
5 minutes; purged on publish, edit and verification by bumping a
`advisor.pages.version` value in `job_state` that is part of the cache key
(the existing `cached()`/`cacheKey()` helpers in `server/edge-cache.ts`).

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
