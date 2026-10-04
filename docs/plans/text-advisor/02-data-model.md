# 02. Data model, storage, retention and privacy

All tables are D1 (SQLite) through Drizzle, declared in `db/schema.ts` and
migrated with `pnpm db:generate --name <name>` (drizzle-kit; without
`--name` it invents a random file name). `tests/test_migrations.mjs`
fails if the schema and the committed migrations disagree, so **never
hand-write a migration**. Ids are `text` primary keys: random 16-byte
base64url for user-facing rows, deterministic hashes where idempotency needs
them (noted per table). Times are ISO-8601 UTC strings except where an integer
epoch is needed for an index-driven expiry, matching the existing tables.

Migrations land in steps so each PR is small and each phase can deploy
without the later tables:

| Migration | Tables | Phase |
| --- | --- | --- |
| `0006_advisor_core` | `advisor_contacts`, `advisor_boats`, `advisor_crew`, `advisor_messages`, `advisor_media`, `advisor_reports`, `advisor_report_edits`, `advisor_reviews`; `users.role` | 1 (channel + intake) |
| `0007_advisor_media_ref` | `advisor_media.provider_ref` (TA-C1; not in the original plan) | 1 |
| `0008_advisor_answers` | `advisor_rules`, `advisor_daily_answers` | 3 (angler answers) |
| `0009_advisor_media_derived` | `advisor_media.derived_at`, `derived_error` (TA-M1; not in the original plan) | 4 (media job) |
| `0010_advisor_media_orientation` | `advisor_media.orientation` (found in the TA-M1 review; not in the original plan) | 4 (media job) |
| `0011_advisor_social` | `advisor_posts`, `advisor_post_stats`; `advisor_contacts.ig_sid` | 5 (social) |

Column conventions: `*_at` ISO strings; `*_json` columns hold JSON text and
are validated on read by a small parser in `server/advisor/types.ts`
(never trusted); booleans are `integer` 0/1 like `trips.enabled`.

## `users` (existing): one new column

| Column | Type | Notes |
| --- | --- | --- |
| `role` | text, nullable | `'admin'` or null. Set only by `scripts/advisor/grant-admin.mjs`. Never exposed by `/api/session` beyond `is_admin: boolean`. |

## `advisor_contacts`

One row per person (phone number) or web visitor.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | random |
| `phone_hash` | text, unique, nullable | `HMAC-SHA256(K_hash, e164)` hex, where `K_hash = HKDF-SHA256(ADVISOR_PHONE_KEY, info 'hash')`. Null for web-only contacts. |
| `phone_enc` | text, nullable | `base64(iv ‖ AES-GCM(K_enc, e164))`, `K_enc = HKDF-SHA256(ADVISOR_PHONE_KEY, info 'enc')`, 12-byte random iv. Decrypted only to send. |
| `web_session` | text, unique, nullable | the `sc_adv` cookie value's sha256 for web visitors |
| `ig_sid` | text, unique, nullable | Instagram-scoped user id for DM contacts (added in 0011) |
| `channel` | text | last channel used: `imessage`, `sms`, `web`, later `whatsapp` |
| `role` | text | `angler` (default), `skipper`, `crew`, `admin-test` |
| `boat_id` | text, nullable | the boat a skipper or crew member posts for |
| `display_name` | text, nullable | what they asked to be called, 1–60 chars, control chars stripped |
| `language` | text | `en` (default) or `es`; set from the first message, updated when they switch for two consecutive messages |
| `home_port` | text, nullable | a `catalog/home-ports.json` port id |
| `targets_json` | text, nullable | array of species keys from `catalog/species.json` |
| `source` | text, nullable | first-touch attribution: `instagram`, `facebook`, `web`, `qr`, `skipper-invite`, `direct` (from the pre-filled first message, see 08) |
| `status` | text | `active`, `stopped` (texted STOP; no outbound), `blocked` (admin) |
| `messages_today` | integer | rolling counter reset by date in `messages_day` |
| `messages_day` | text, nullable | `YYYY-MM-DD` (America/Los_Angeles) the counter belongs to |
| `last_seen_at` | text | |
| `last_error_notice_at` | text, nullable | throttles the "something went wrong" text |
| `created_at` | text | |
| `updated_at` | text | |

Indexes: unique `contact_phone_hash (phone_hash)`, unique `contact_web_session (web_session)`,
`contact_boat (boat_id)`, `contact_seen (last_seen_at)`. SQLite unique indexes allow
any number of nulls, so web-only and phone-only contacts coexist.

## `advisor_boats`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | random |
| `slug` | text, unique | URL slug for `/boats/<slug>`, from the name, ASCII, max 40 |
| `name` | text | boat name as the skipper gave it (1–60) |
| `landing` | text, nullable | landing or harbor name |
| `port` | text | home-port id |
| `region` | text | region id (derived from the port) |
| `instagram` | text, nullable | handle without `@`, validated `^[a-z0-9._]{1,30}$` |
| `booking_url` | text, nullable | https only |
| `phone_public` | text, nullable | a number the skipper wants on the boat page (not the contact's) |
| `owner_contact_id` | text, nullable | the skipper's contact; null after the owner's "forget me" |
| `status` | text | `pending` (default), `verified`, `rejected` (SK-4) |
| `verified_at` | text, nullable | SK-4; set by admin |
| `verified_by` | text, nullable | users.id of the admin |
| `consent_photos_at` | text, nullable | SK-2; "yes" by text, recorded with the message id in `consent_message_id` |
| `consent_message_id` | text, nullable | |
| `consent_revoked_at` | text, nullable | |
| `auto_publish` | integer | SC-5; 0 default |
| `clean_reports` | integer | consecutive confirmed-without-edit reports, for SC-5 |
| `created_at`, `updated_at` | text | |

Indexes: unique `boat_slug (slug)`, `boat_port (port)`, `boat_owner (owner_contact_id)`.

## `advisor_crew`

| Column | Type | Notes |
| --- | --- | --- |
| `boat_id` | text | |
| `contact_id` | text | |
| `added_by` | text | contact id of the skipper |
| `added_at` | text | |
| `removed_at` | text, nullable | SK-3 removal keeps the row for audit |

PK `(boat_id, contact_id)`; index `crew_contact (contact_id)`.

## `advisor_messages`

Every inbound and outbound message on every channel.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | inbound: random; outbound: `sha256(in_message_id + ':' + action_index)[:32]` (idempotent) |
| `contact_id` | text | |
| `direction` | text | `in` or `out` |
| `channel` | text | `imessage`, `sms`, `web`, `instagram_dm`, `instagram_comment` |
| `provider_id` | text, nullable | BlueBubbles message guid, Twilio MessageSid, IG message id; unique with `channel` |
| `body` | text, nullable | the text; stored in full, max 4,000 chars; nulled by retention |
| `media_json` | text, nullable | inbound: array of `advisor_media.id`; outbound: array of the R2 keys it attaches (so a `held` row can be sent later, TA-C1) |
| `intent` | text, nullable | the engine's classification for inbound (`report.count_board`, `fishid`, `advice.rig`, …) |
| `status` | text | in: `queued`, `processing`, `done`, `held` (`ADVISOR_REPLIES_ENABLED=false`), `dropped`, `failed`; out: `sending`, `sent`, `failed`, `held`, `unknown` |
| `error` | text, nullable | short reason, no payloads |
| `in_reply_to` | text, nullable | for outbound: the inbound message id |
| `tokens_in`, `tokens_out` | integer, nullable | summed model usage for this turn (also goes to analytics) |
| `created_by` | text, nullable | null for the engine; `users.id` when an admin replied from the queue |
| `created_at` | text | |
| `sent_at` | text, nullable | |

Indexes: `message_contact_time (contact_id, created_at)`, `message_status (status)`,
unique `message_provider (channel, provider_id)`.

## `advisor_media`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | random |
| `contact_id` | text | |
| `message_id` | text, nullable | |
| `boat_id` | text, nullable | copied from the contact at intake so a removed crew member's photos stay with the boat |
| `kind` | text | `image`, `video`, `audio` |
| `mime` | text | after sniffing, not the provider's claim |
| `bytes` | integer | |
| `width`, `height` | integer, nullable | |
| `r2_key` | text | `advisor/media/<contact_id>/<id>.<ext>` |
| `sha256` | text | of the stored bytes; duplicates within a contact are linked, not re-stored |
| `exif_stripped` | integer | 1 once the original has been rewritten without metadata |
| `classification_json` | text, nullable | the vision result (07 § result schema) |
| `has_person` | integer, nullable | copied out of the classification for the OP-2 index |
| `publish_state` | text | `private` (default), `queued` (in a review), `approved`, `posted`, `rejected` |
| `credit` | text, nullable | the credit line to use when posted ("Capt. X / Boat Y") |
| `provider_ref` | text, nullable | added in `0007_advisor_media_ref` (TA-C1): the channel's attachment reference (BlueBubbles attachment guid, later a Twilio media URL) |
| `derived_at`, `derived_error` | text, nullable | added in `0009_advisor_media_derived` (TA-M1): when the `advisor-media` job wrote `advisor/derived/<id>/`, or gave up on the item (then `derived_error` holds its short reason) |
| `orientation` | integer, nullable | added in `0010_advisor_media_orientation`: a JPEG's EXIF Orientation (1-8) read before intake stripped the EXIF; null for other formats. The media job applies it; 2-8 makes the item pending and keeps `/media` from serving the original |
| `created_at` | text | |

The webhook (TA-C1) writes one placeholder row per attachment before anything
is downloaded: `r2_key=''`, `sha256=''`, `bytes` and `mime` as the provider
claims them, `provider_ref` set, `publish_state='private'`. TA-C4's download
fetches by `provider_ref`, then fills `r2_key`, `sha256`, the sniffed `mime`
and the real `bytes`; a row whose `r2_key` is still `''` has not been
downloaded.

As built (TA-C4, `server/advisor/media.ts`): `kind` also takes `unknown` for a
rejected file (an unrecognised type, a JPEG/PNG whose marker or chunk walk
fails, a JPEG/PNG over 24 MB, anything over 300 MB, or a download that still
failed after the retries); such a row has `publish_state='rejected'`,
`mime='application/octet-stream'`, `r2_key=''` and nothing in R2. The table
has no error column, so a download given up on is recorded on the inbound
`advisor_messages.error` as `fetch-failed` (the handler still runs). A
duplicate within the contact gets its own row whose `r2_key` points at the
first row's object. Upload-link rows have `provider_ref` null.

Indexes: `media_contact (contact_id)`, `media_publish (publish_state)`, `media_boat (boat_id)`.

## `advisor_reports`

A skipper's (or crew's) fish report for one trip date.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | random |
| `boat_id` | text | |
| `contact_id` | text, nullable | who sent it (null after "forget me") |
| `region`, `port` | text | |
| `report_date` | text | `YYYY-MM-DD` local; defaults to today, parsed from text ("yesterday") |
| `trip_type` | text, nullable | `half-day`, `full-day`, `overnight`, free text ≤ 30 |
| `anglers` | integer, nullable | |
| `counts_json` | text | array of `{species_key, label, kept, released}`; `species_key` from `catalog/species.json` or `other`; `label` is the skipper's word |
| `source` | text | `count-board`, `text`, `voice` (Next), `admin` |
| `media_id` | text, nullable | the count-board photo |
| `status` | text | `draft`, `pending_confirm`, `published`, `rejected`, `withdrawn` |
| `verified` | integer | boat verified at publish time (frozen) |
| `notes` | text, nullable | skipper's free-text notes, ≤ 280 |
| `version` | integer | incremented by every edit |
| `confirmed_at`, `published_at` | text, nullable | |
| `created_at`, `updated_at` | text | |

Indexes: `report_port_date (port, report_date)`, `report_boat_date (boat_id, report_date)`,
`report_status (status)`. Unique `report_boat_day_source (boat_id, report_date, source)` keeps a
retry from creating a second draft for the same day; a second real report the
same day becomes an edit (SC-4).

## `advisor_report_edits`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | random |
| `report_id` | text | |
| `contact_id` | text, nullable | |
| `message_id` | text, nullable | the "lings were 14" text |
| `patch_json` | text | JSON Patch-like list of `{field, from, to}` |
| `created_at` | text | |

Index `edit_report (report_id)`.

## `advisor_reviews`

The admin queue (OP-1). One row per thing needing a human.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | deterministic `sha256(kind + ':' + ref_id + ':' + reason)[:32]` so repeats update rather than duplicate |
| `kind` | text | `media` (person in photo, angler submission), `report` (flagged or unverified-boat first report), `post` (every social draft until auto-approval exists), `skipper` (new registration), `conversation` (refusal, abuse, low confidence), `rule` (change-watch flagged a page) |
| `ref_id` | text | the row in the kind's table |
| `reason` | text | short code: `has_person`, `angler_photo`, `new_skipper`, `unverified_boat`, `owner_forgotten`, `refused`, `low_confidence`, `rules_without_tool`, `tool_loop`, `rule_source_changed`, `social_draft` |
| `status` | text | `open`, `approved`, `edited`, `rejected` |
| `note` | text, nullable | admin note |
| `opened_at`, `decided_at` | text | |
| `decided_by` | text, nullable | users.id |

Indexes: `review_open (status, opened_at)`.

## `advisor_rules` (migration 0008)

The only source of regulations the advisor may quote (OP-6).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | random |
| `region` | text | region id, or `*` for statewide |
| `jurisdiction` | text | a `jurisdictions/*.json` id: `california-central`, `california-southern`, `california-san-francisco`, `california-mendocino`, `california-northern` |
| `species_key` | text | from `catalog/species.json` or `catalog/advisor/species-extra.json` (sub-species such as `vermilion`, `canary`, `yelloweye`, `cowcod`, `cabezon`, each with a `parent` catalog key) |
| `species_label` | text | |
| `size_min_in` | real, nullable | minimum length, inches |
| `size_max_in` | real, nullable | slot upper bound |
| `bag_limit` | integer, nullable | per angler per day |
| `bag_notes` | text, nullable | sub-limits ("no more than 1 copper") |
| `season_open`, `season_close` | text, nullable | `MM-DD` or ISO dates; both null = year-round |
| `depth_limit_ft` | integer, nullable | groundfish depth constraint |
| `area_notes` | text, nullable | MPA or area text |
| `gear_notes` | text, nullable | |
| `source_name`, `source_url` | text | the CDFW page |
| `reviewed_at` | text | when a human last confirmed the row against the source |
| `review_due` | text | `reviewed_at + 90 days`, or the season end if sooner |
| `status` | text | `active`, `review` (source changed or past due), `retired` |
| `updated_by`, `updated_at` | text | |

Indexes: `rule_lookup (region, species_key, status)`, `rule_due (review_due)`.
Seeded by `scripts/advisor/import-rules.mjs` from `dist/data/regulations*.json`
(each imported row starts as `review` until an admin marks it `active`, so
nothing is quotable before a human has looked).

As built (TA-A0): `scripts/advisor/import-rules.mjs` reads each
`jurisdictions/<id>.json`'s `regulations_asset` (four files under
`dist/data/` plus `dist/regions/southern-california/regulations.json` for
`california-southern`) and any other `dist/data/regulations*.json`, and
writes one row per jurisdiction and species with `region='*'` (the files are
per management area, not per region; `lookupRules` matches a region through
its `region.json` `jurisdiction_id`). The rockfish entry also yields rows for
the sub-species its text names (the copper, canary and vermilion/sunset
sub-limits, the no-retention species, cabezon and greenling in the group
limit); a name with no catalog or species-extra key (quillback, sunset) is
`species_key='other'` with the label kept. `size_min_in` and `bag_limit` are
read only when the text leads with the number; the full sentences go to
`bag_notes`, `gear_notes` and `area_notes`. A closed season (no window) is
`season_open`/`season_close` null with `bag_limit` 0 and an `area_notes`
starting "Closed:". `review_due` is 90 days, or the season end when that is
sooner and not yet past. Ids are `sha256(jurisdiction|region|species_key|label
for other)[:32]`; each statement is an upsert that changes a row only when
its imported content changed, and then puts it back into `review` (a
`retired` row stays retired). `updated_by` is `import-rules`.
`server/advisor/answers/rules.ts` has `lookupRules` (a sub-species also gets
its parent group's rows, marked `applies_as: 'group'`; region rows before
`*` rows) and `markJurisdictionForReview` (for TA-A4).

## `advisor_daily_answers` (migration 0008)

The "one answer per port per day" cache (FR-1).

| Column | Type | Notes |
| --- | --- | --- |
| `key` | text PK | `<port>:<YYYY-MM-DD>` |
| `text_en`, `text_es` | text | ≤ 480 chars each |
| `inputs_hash` | text | sha256 of the report ids, conditions snapshot and rules used; regenerate when it changes |
| `generated_at` | text | |

## `advisor_posts` (migration 0011; TA-M1 took 0009 and 0010)

A social post in any state.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | text PK | random, or deterministic for daily posts: `sha256('daily:' + region + ':' + date)[:32]` |
| `kind` | text | `photo`, `carousel`, `reel`, `story`, `daily`, `roundup` |
| `region` | text | |
| `boat_id` | text, nullable | credited boat |
| `media_json` | text | ordered `advisor_media.id`s, or for `daily` the rendered graphic's media id |
| `caption` | text | final caption (≤ 2,200, ≤ 30 hashtags, ≤ 20 mentions) |
| `collaborators_json` | text, nullable | up to 3 IG usernames (SP-7) |
| `user_tags_json` | text, nullable | `[{username, x, y}]` |
| `targets_json` | text | which surfaces: `["instagram","facebook"]`, Stories: `["instagram_story","facebook_story"]` |
| `status` | text | `draft`, `approved`, `scheduled`, `publishing`, `posted`, `partial` (one surface failed), `failed`, `rejected` |
| `scheduled_for` | text, nullable | |
| `ig_container_id`, `ig_media_id`, `fb_post_id`, `fb_story_id` | text, nullable | |
| `collab_status` | text, nullable | `invited`, `accepted`, `declined` |
| `error` | text, nullable | |
| `created_by` | text | `engine` or users.id |
| `approved_by`, `approved_at`, `posted_at` | text, nullable | |
| `created_at`, `updated_at` | text | |

Indexes: `post_status_time (status, scheduled_for)`, `post_boat (boat_id)`.

## `advisor_post_stats` (migration 0011)

| Column | Type | Notes |
| --- | --- | --- |
| `post_id` | text | |
| `platform` | text | `instagram`, `facebook` |
| `day` | text | `YYYY-MM-DD` of the fetch |
| `views`, `reach`, `likes`, `comments`, `saved`, `shares`, `follows`, `profile_visits`, `link_taps` | integer | 0 when the metric is unavailable for that media type |
| `raw_json` | text | the insights response, trimmed to metric values |
| `fetched_at` | text | |

PK `(post_id, platform, day)`.

## Reusing `job_state`

Advisor cron state uses the existing `job_state` table with keys prefixed
`advisor.`: `advisor.relay` (`up`/`down`, last ping), `advisor.calendar.last_run`,
`advisor.insights.last_run`, `advisor.rules.last_watch`. No new table.
As built (TA-M1): `advisor.media.dispatched_at` (the media job's dispatch
throttle, an ISO time) and `advisor.graphic.<id>` (one graphic request and its
result as JSON, 09 § Derived images "As built").

## R2: `ADVISOR_MEDIA` (bucket `skippercast-advisor-media`, private)

```
advisor/media/<contact_id>/<media_id>.<ext>           original, EXIF stripped (JPEG/PNG), never served raw
advisor/derived/<media_id>/public.jpg                  1440 px max, sRGB JPEG, for pages and Meta
advisor/derived/<media_id>/story.jpg                   1080×1920 with the "Text SkipperCast" footer baked in
advisor/derived/<media_id>/thumb.jpg                   320 px for the admin queue
advisor/posts/<post_id>/daily.jpg                      the daily "what's biting" graphic
advisor/exports/<contact_id>/<date>.json               a "send me my data" export, 7-day lifecycle
```

Served only through `GET /media/<media_id>.jpg` (public derived files, when
`publish_state` allows) and `GET /api/admin/media/<id>` (admin, originals).

As built (TA-M1): the job also writes graphics to the `out_key` a request
names (`advisor/posts/<post_id>/<name>.jpg`, roundup slides as
`<name>-<n>.jpg`), and every object it writes carries the metadata
`source-sha256`, `width` and `height` (derived media also `source-width` and
`source-height`), which make a rerun idempotent. It reaches the bucket over
the S3 API with `R2_ADVISOR_TOKEN`, a GitHub secret scoped to this bucket.

As built (TA-C4): `<ext>` is the sniffed type's: `jpg`, `png`, `gif`, `webp`,
`heic`, `heif`, `mp4`, `mov`, `m4a`, `aac`, `amr` or `caf`. The
`advisor/derived/*` files come from the `advisor-media` runner job (TA-M1,
09 § Derived images "As built"); until it writes `public.jpg`, `GET /media/<id>.jpg`
(and `.png`) falls back to the stripped original when its stored type matches
the extension. A HEIC, GIF, WebP, video or audio original (stored as received,
`exif_stripped=0`) is never served, so it becomes public only through its
derived JPEG; `GET /media/<id>.mp4` (09) is not built yet (TA-S1 adds it with
the Meta publishing that needs it). The JPEG walk drops everything after EOI as
well, because an iPhone's MPF secondary image sits there with its own EXIF.
Files over 24 MB that are stored as received go to R2 as a multipart upload
(10 MB parts) hashed on the way, so a 300 MB video never sits in the Worker's
128 MB; their duplicate check runs after the upload and deletes the new copy.
The Worker never returns an R2 URL. Image processing is split: the Worker
strips metadata at intake without decoding (a JPEG marker walk that drops
every APPn segment except APP0, and drops PNG `eXIf`/`tEXt` chunks), so no
original with GPS data is ever stored; resizing, the Story footer and the
generated graphics are done by the `advisor-media` runner job (Python +
Pillow on the self-hosted runner, 09 § derived images), which writes the
derived files back to R2 and reports to the Worker. Video is never
transcoded: a video that is not a Meta-acceptable MP4 is held and the skipper
gets the upload link (SP-3), which accepts up to 300 MB.

## Retention and deletion

Runs weekly from `advisorCron` (Sunday 09:00 UTC slot) and is idempotent.

| Data | Rule |
| --- | --- |
| Inbound/outbound message bodies | `body` nulled after 180 days; row kept for counts |
| Media originals | deleted after 90 days unless referenced by a `published` report or a `posted`/`approved` post |
| Derived public images | kept while the referencing report/post exists |
| Reviews | deleted 90 days after `decided_at` |
| Daily answers | deleted after 30 days |
| Post stats | kept 2 years (matches Meta's own window) |
| Web-only contacts | deleted after 90 days of inactivity |

**STOP** (FC-4): `status='stopped'`; no outbound of any kind; an inbound
`START` reactivates. Twilio enforces STOP on SMS itself and still forwards the
message, so the handler runs on both channels. (Forwarding is unverified as of
TA-C2; see 03 § Twilio adapter, "As built".)

**"forget me"** (FC-4, `forgetContact` in `server/advisor/contacts.ts`): R2
first (originals under `advisor/media/<contact_id>/`, each of its media's
`advisor/derived/<media_id>/` files and any `advisor/exports/<contact_id>/`), so
a failure leaves D1 intact and the call can be retried; then in one D1 batch,
delete the contact's messages, media rows, reviews (those whose `ref_id` is the
contact, one of its messages or one of its media), report edits and crew rows
where it is the member (`added_by` on other crew rows stays as an opaque id);
null `advisor_reports.media_id` where it pointed at the contact's media; set
`advisor_reports.contact_id` to null (the boat's published reports are the
boat's business record); if the contact owns a boat, the boat stays but its
`owner_contact_id` is set to null and the admin queue gets a `skipper`
review item `owner_forgotten`. The contact row itself is deleted; a later
text from the same number starts fresh. Reply with one confirmation text
before deleting the contact (the send needs the number).

**"send me my data"**: writes the export to R2 and texts a signed link valid
24 hours (`GET /api/advisor/export/<token>`).

## Privacy invariants (tested in `tests/test_advisor_privacy.mjs`)

- No table stores a phone number in clear. `phone_enc` decrypts only inside
  `channels/*.send()`; the decrypted value never reaches logs or analytics.
- `server/analytics.ts` points written by the advisor contain only route
  patterns, intents, outcomes, counts and timings.
- `console.log` lines in `server/advisor/` go through `advisorLog()` which
  strips anything matching an E.164 pattern or a 10-digit run before writing
  (`\+\d{10,15}` or `\+?1?\d{10}`, in every string at any depth, keys included).
  A number written with separators ("805-555-0100") is not matched, so a
  message body is never a log field.
- `check_repository.py`'s private-material scan is extended (task TA-C5): over
  `tests/fixtures/advisor/` and `docs/plans/text-advisor/` it rejects any
  E.164 match `\+1\d{10}` except the fictional `+1555` series
  (`\+1555\d{7}` and `+1\d{3}555\d{4}`), and any Instagram handle not in
  `catalog/advisor/fixture-handles.json`. No bare 10-digit rule (it would hit
  repository ids and timestamps).
