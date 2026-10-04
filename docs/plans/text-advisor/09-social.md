# 09. Social: Instagram and Facebook Page

Stories: SO-1, SO-2, SO-4, SO-5, SP-1, SP-3…SP-10 (SP-2 merged into SO-4;
SO-3, SP-11, SP-12, SP-13 are Next). Code: `server/advisor/social/*.ts`,
admin Posts view (08), the `advisor-media` runner job.

Facts this design rests on (Meta developer docs, checked 2026-10-03; the
implementing agent re-checks the changelog before TA-S1 because Meta moves
these):

- Publishing is two steps: `POST /<ig-user-id>/media` (container) then
  `POST /<ig-user-id>/media_publish`. Media must be at a public HTTPS URL
  Meta can fetch. Quota 50 API posts per 24 h (read
  `GET /<ig-user-id>/content_publishing_limit`). Containers expire in 24 h;
  **Instagram has no API scheduling**: our cron publishes at the scheduled time.
- Stories (`media_type=STORIES`) are supported but bare: no caption,
  stickers, links or collaborators. The "text us" call to action must be
  drawn into the image (SP-4).
- Reels: `media_type=REELS`, MP4/MOV, H.264/HEVC, 9:16 recommended, 3 s–15
  min, ≤ 300 MB; status polled on the container.
- `collaborators` (≤ 3 usernames) on feed images, carousels and Reels; the
  invitee must accept in-app (SP-7); not on Stories.
- Facebook Page: `POST /<page-id>/photos`, `/videos`, `/feed`,
  `/photo_stories`, `/video_stories`, `/video_reels`; Page posts *can* be
  scheduled by Meta (`published=false&scheduled_publish_time`). There is no
  API switch to auto-crosspost IG → FB; we post to both.
- Owner-only publishing and insights need no app review: an app in
  Development mode with Standard Access works for accounts that hold a role
  on the app. **Public comment and DM automation (SP-8, SP-9) needs the app
  Live, Advanced Access for `instagram_manage_comments` /
  `instagram_manage_messages`, and Business Verification.**
- Tokens: with the Facebook-Login route (IG professional account linked to
  the Page), `GET /me/accounts` yields a **Page token that does not expire**;
  it serves both the Page and the IG account. We use that route, so there is
  no refresh job. Insights use `views` (impressions is gone), `reach`,
  `saved`, `shares`, `follows`, `profile_visits`, `profile_activity`.

## Setup (owner tasks TA-O4, TA-O5; engineering provides `scripts/advisor/meta-token.mjs`)

1. Instagram: convert `@skippercast` (or the chosen handle) to a
   **Business** account (Stories publishing needs Business, not Creator).
   Bio per SP-1: the offer in one line, link `https://skippercast.com/text?s=ig`,
   highlights "Reports", "Fish ID", "Tips": the copy to paste is in § Instagram
   profile below (TA-S5).
2. Facebook: a Page "SkipperCast", link the IG account to it (Page settings
   › Linked accounts).
3. Meta developer app "SkipperCast Publisher" (type Business), products
   Instagram Graph API + Webhooks + Facebook Login for Business. Add the
   owner as app admin. Stay in Development mode for phases S1–S3.
4. Run `node scripts/advisor/meta-token.mjs`: opens the Facebook Login
   dialog with scopes `pages_show_list, pages_read_engagement,
   pages_manage_posts, pages_manage_metadata, pages_messaging,
   instagram_basic, instagram_content_publish, instagram_manage_comments,
   instagram_manage_messages, instagram_manage_insights, business_management`,
   exchanges for a long-lived token, calls `/me/accounts`, prints the Page
   id, the Page token and the linked IG user id, and verifies the IG account
   is `BUSINESS`. The owner puts them in GitHub secrets (`META_PAGE_ID`,
   `META_PAGE_TOKEN`, `META_IG_USER_ID`), plus `META_APP_ID`,
   `META_APP_SECRET`, `META_VERIFY_TOKEN`.
5. For SP-8/SP-9 (phase S4): Business Verification (legal entity documents),
   App Review submission with the screencast the task produces, then switch
   the app to Live and turn on `ADVISOR_INBOX_ENABLED`. Until then, inbound
   DMs and comments from the public are not delivered to us; the code is
   complete and tested against fixtures.

## Media that Meta fetches

Meta GETs `image_url`/`video_url` without auth, so the Worker serves
`GET /media/<media_id>.jpg` and `GET /media/<media_id>.mp4` for media with
`publish_state in ('approved','posted')` and `GET /media/post/<post_id>/<name>`
for generated graphics, with `Content-Type` set and no bot blocking
(`robots.txt` disallows indexing `/media/`; the security headers every
response carries do not affect a fetch). URLs stay valid at least 24 h after
the container is created.

## Derived images and graphics: the `advisor-media` runner job

Image work that needs a decoder (resizing, the Story footer, the daily
graphic, the roundup carousel) does **not** run in the Worker. It runs as a
GitHub Actions job on the owner's self-hosted runner (`DATA_RUNNER`), the
same place the data jobs run, in Python with Pillow:

- `.github/workflows/advisor-media.yml`: `workflow_dispatch` only (no
  schedule: a 15-minute schedule falling back to GitHub-hosted runners would
  burn minutes), `runs-on: ${{ vars.DATA_RUNNER }}` with a job-level
  `if: vars.ENABLE_ADVISOR == 'true' && vars.DATA_RUNNER != ''`. The Worker
  triggers it on demand through `dispatchWorkflow(env, 'advisor-media.yml')`
  (exported from `server/watchdog.ts`, 01 § touch points) whenever media or
  a graphic request becomes pending, and the cron re-dispatches every 15
  minutes while anything is still pending, so a new approved photo is
  processed within a minute.
- `scripts/advisor/media_job.py` (Python, stdlib + Pillow, under `scripts/`
  since it is product code, not research): lists pending work from
  `GET /api/advisor/jobs/media` with a GitHub OIDC token requested for
  `audience: <public_origin>/api/advisor/jobs` (TA-M1 parameterises
  `server/job-auth.ts` and adds `advisor-media.yml` to
  `deployments/production.json` `scheduler.workflows`), downloads originals
  from R2 with `R2_ADVISOR_TOKEN` (scoped to the private media bucket; an
  owner step in TA-M1), writes
  `public.jpg`, `thumb.jpg`, `story.jpg`, daily and roundup graphics,
  uploads them, and `POST /api/advisor/jobs/media-done` with the keys and
  dimensions. Templates: `dist/advisor/story-template.svg` is rendered by
  Pillow's drawing calls from a JSON spec (`catalog/advisor/graphics.json`:
  fonts, colours, layout boxes), not by an SVG rasteriser, to keep
  dependencies at Pillow only.
- The Worker strips EXIF itself at intake (JPEG marker walk, no decode) so
  originals are safe before the job runs; pages show the original (stripped)
  until `public.jpg` exists.

Video: no transcoding. Validity checks are done by the job with `ffprobe`
when present on the runner (container, codec, duration, size) and the
result is stored on the media row; a video that fails gets `failed` with a
reason the admin can see. (As built below: the job strips every video's
container metadata with ffmpeg; the validity checks are still not built.)

### As built (TA-M1)

- **Pending work.** `server/advisor/media.ts` `mediaJobWork`: stored images
  (not rejected) whose new `derived_at` column (migration
  `0009_advisor_media_derived`, with `derived_error`) is null and that either
  vision cannot take as stored (over 4.5 MB, or HEIC/HEIF) or are `queued`,
  `approved` or `posted`. A private everyday photo is left alone. Oldest first,
  25 media and 10 graphics per call; the job asks again until the list holds
  only items it already tried.
- **Graphic requests.** `requestGraphic(env, id, {kind, media_ids?, data,
  out_key})` writes `job_state` `advisor.graphic.<id>` as
  `{..., status: 'pending', requested_at}` and dispatches the job; a rerun with
  the same id renders again. `kind` is `daily`, `story` or `roundup`; `out_key`
  must be `advisor/posts/<post_id>/<name>.jpg`; `data` is at most 16 KB of
  JSON; `media_ids` at most 10 (the job uses each one's `public.jpg`, else its
  original). Done: `status: 'done'`, `keys: {public, slides?}` (roundup slides
  are `<out_key stem>-<n>.jpg`), `width`, `height`, `done_at`; failed:
  `status: 'failed'`, `error`. `graphicState(db, id)` reads it. The layouts are
  deliberately plain: `daily` is a 1080 x 1350 card (title from `data.title` or
  `port` + `date`, `lines: [{label, value}]`, a note from `conditions` and
  `confidence`); `story` is 1080 x 1920 (`title`, `lines`, the first photo);
  `roundup` is a cover card (`title`, `lines`) plus one 1080 x 1350 slide per
  photo with `captions[i]`. Every image carries the footer band.
- **Endpoints.** `GET /api/advisor/jobs/media` and `POST
  /api/advisor/jobs/media-done` (`server/routes/advisor.ts`, behind the gate),
  authorised by `verifyJobToken(token, deployment, {audiencePath:
  '/api/advisor/jobs', workflows: ['advisor-media.yml']})`; 240 requests a
  minute per run (`jti`). The done report for a media item must name exactly
  its `advisor/derived/<id>/{public,thumb,story}.jpg` keys (story optional);
  `source_width`/`source_height` fill the row's size only when intake could
  not read it (HEIC). With `error` the item is given up (`derived_at` and
  `derived_error` set), so it leaves the list and a waiting message falls back
  to the upload link.
- **Dispatch.** `requestMediaJob` claims `job_state`
  `advisor.media.dispatched_at` with an UPSERT-with-WHERE (at most once a
  minute) and calls `dispatchWorkflow(env, 'advisor-media.yml')`; it runs after
  intake stores an image over 4.5 MB or a HEIC, when a photo is put in the
  feed queue, when a media review is approved by text, from `requestGraphic`,
  and from the consumer while a message waits. `advisorCron` calls
  `mediaJobTick` every tick: while anything is pending it dispatches again,
  at most once per 14.5 minutes (a tick 15 minutes later is never skipped). A
  failed dispatch keeps the claim; the next tick retries. Without
  `GITHUB_TOKEN` nothing is dispatched.
- **The job.** `scripts/advisor/media_job.py` (stdlib + Pillow + pillow-heif,
  the `advisor` extra). R2 access is the S3 API with SigV4 written in the
  standard library (tested against AWS's published vectors), with the
  credentials `scripts/publish_r2.py` derives from an API token (key id = token
  id, secret = SHA-256 of the token), here `R2_ADVISOR_TOKEN`. Every object it
  writes carries `x-amz-meta-source-sha256` (the original's sha256, or a digest
  of the graphic request) and its size, so a rerun reports an unchanged item
  without decoding it. The OIDC audience is `deployments/production.json`
  `public_origin` + `/api/advisor/jobs`; requests go to `ADVISOR_PUBLIC_BASE`.
  The token is re-requested every four minutes. Decoding failures are given up
  (`decode-failed: ...`, `original-missing`); network and R2 errors leave the
  item pending and make the run exit 1.
- **Layouts.** `catalog/advisor/graphics.json` (colours from
  `dist/tokens.css`, Pillow's built-in scalable font unless `fonts.ttf` names a
  committed file). No `dist/advisor/story-template.svg` was made: the JSON spec
  is the template. The footer reads "Text SkipperCast" and the number from the
  repository variable `ADVISOR_NUMBER` as (805) 555-0100, or
  `skippercast.com/text` without one.
- **Video.** Not processed: no `ffprobe` probing was built, so no skip reason
  for it was allow-listed (09 above; a later task can add it).
- **Orientation.** Found in review: intake stripped every APP1 segment,
  including the EXIF Orientation tag, so a JPEG whose camera relied on that
  tag was stored and derived sideways. Fixed as below.

### As built (orientation)

- **Intake.** `stripJpegMetadata` reads the Orientation tag (1-8) from the
  first EXIF APP1 before dropping it; the value goes on the row
  (`advisor_media.orientation`, migration `0010_advisor_media_orientation`;
  null for anything but a JPEG) and the R2 object's custom metadata
  `orientation`. The stored bytes still carry no EXIF.
- **Pending work.** `mediaJobWork` also lists images with `orientation > 1`
  (private ones too), and each work item (and each graphic's photo) carries
  `orientation`. Intake dispatches the job when it stores such a JPEG.
- **The job.** `decode` applies the stored value with the same transpose table
  as `ImageOps.exif_transpose` (2 mirror, 3 180, 4 flip, 5 transpose, 6 rotate
  270, 7 transverse, 8 rotate 90), since the stored original has no EXIF for
  Pillow to read; without a stored value (HEIC and other originals stored as
  received) it still applies the file's own EXIF. `public.jpg`, `thumb.jpg`,
  `story.jpg` and a graphic's fallback to the original are upright. Each
  derived object records `x-amz-meta-orientation`, and the unchanged-item
  shortcut requires it to match, so files derived sideways before this change
  are rendered again.
- **`/media`.** Prefers `public.jpg` as before; a stripped JPEG with
  orientation 2-8 is never served as the original (404 until `public.jpg`
  exists), since its pixels are sideways without the tag.
- PNG `eXIf` orientation is not read (PNG rows have a null orientation).

### As built (video privacy)

Raised with TA-S2: video originals kept the camera's container metadata, so the
public `.mp4` could carry a position (00 principle 7). Fixed:

- **The job.** `media.ts mediaJobWork` adds `videos`: every stored video that is
  not rejected and has no `derived_at`, private ones too (so a video is clean
  before anyone reviews it), oldest first, 5 a call; `mediaJobPending` counts
  them. `media_job.py derive_video` streams the original from R2 to a temporary
  file, finds its video stream with `ffprobe`, and runs `ffmpeg -i in
  -map_metadata -1 -map_metadata:s -1 -map_chapters -1 -dn -sn -c copy
  -fflags +bitexact -movflags +faststart -f mp4 out` (stream copy, never a
  transcode; `-tag:v hvc1` for HEVC; data tracks such as QuickTime timed
  metadata and subtitles dropped; no encoder tags). It then checks the result
  twice: `location_tags` over `ffprobe -show_format -show_streams` (any
  format or stream tag naming `location`, `xyz`, `ISO6709` or `gps`) and
  `file_location_atoms`, a box walk of every top-level box but `mdat` that finds
  a `©xyz` or `loci` atom and any leaf box (QuickTime `keys` included) naming
  `com.apple.quicktime.location` or ISO 6709. Anything left gives the video up
  (`location-left: ...`). The clean file goes to `advisor/derived/<id>/video.mp4`
  (`video/mp4`, `x-amz-meta-source-sha256`, `x-amz-meta-stripped: 1`, its width
  and height), and `media-done` reports `{media_id, keys: {video}, width?,
  height?}`; a rerun on the same original copies nothing. Without `ffmpeg` or
  `ffprobe` on the runner the video is reported `no-ffmpeg`
  (docs/operations/runners.md lists ffmpeg as a requirement; the workflow warns
  when it is missing). The original stays private in R2, as every original does.
- **`/media/<id>.mp4`** serves only `video.mp4`, as `video/mp4` with the same
  range support, for an approved or posted video with `derived_at` and no
  `derived_error`; the original is never served, whatever its type.
- **Holds.** `media.ts videoHold` names why a video is not ready (waiting for
  the job; no ffmpeg; another failure). `decideReview` refuses to approve or
  edit a media review of such a video (409 with that text, shown on the queue
  card as "Held"); rejecting always works. `approvalHold` refuses a post with
  such a video, so its draft card shows the same reason. The publisher waits for
  a pending copy (dispatches the job, the post stays `approved`, outcome
  `deferred`) and fails the post when stripping failed. The text admin's
  "ok <code>" on such a video changes nothing.
- **Tests.** `tests/test_advisor_video_privacy.mjs` (the work list, `media-done`,
  the holds, the publisher, `/media/<id>.mp4` never serving an original) and
  `tests/unit/test_advisor_media_job.py` (`location_atoms` on crafted MP4 bytes
  with a `©xyz` atom, a QuickTime `keys` location, a `loci` atom, malformed
  boxes; `location_tags`; the command; `no-ffmpeg`; and, with ffmpeg present, a
  real clip carrying `©xyz` and one carrying a `keys` location stripped clean,
  else skipped with the allow-listed reason "ffmpeg and ffprobe are not
  installed ...").

## Drafts (SO-1, SP-3)

`social/drafts.ts: draftFromMedia(media, boat, report?, language)` creates an
`advisor_posts` row:

- `kind`: `photo` for a still, `reel` for a video, `story` for a count board
  (SP-4) or any still the skipper marks "story".
- Caption by a fixed template plus one short model call (`prompts/caption.ts`,
  ≤ 120 tokens, cached by media id): one line about the catch in the
  SkipperCast voice, the boat credit line "Aboard {boat} out of {port}", the
  report numbers when a report from the same day exists ("Limits of
  rockfish, 12 lings for 22 anglers"), the CTA "Text SkipperCast for today's
  report: {{number}}", hashtags from `catalog/advisor/hashtags.json` by
  region and species (≤ 12), and the boat's `@handle` in the caption (the
  mention) as well as `collaborators_json` (SP-7) and a `user_tags_json`
  tag at the image centre when the boat has a handle (SO-5).
- `targets_json`: `["instagram","facebook"]` for photos and reels,
  `["instagram_story","facebook_story"]` for stories.
- `status='draft'` and a `review.post` item (every draft needs one
  approval in v1; auto-approval is a later owner decision).
- Angler photos (AC-1): credit line "Photo: {credit}", no collaborators.

### As built (TA-S1)

- **Where.** `server/advisor/social/drafts.ts` (`ensureMediaDraft`,
  `draftFromMedia`, the caption parts, `revokeBoatPosts`,
  `rejectPostsForMedia`), `server/advisor/prompts/caption.ts`,
  `catalog/advisor/hashtags.json`, `server/advisor/admin/posts.ts` (the card,
  the list and the decision), `tools/propose_post.ts`, the Posts view
  (`web/admin/posts.tsx`, `post-card.tsx`, `posts-form.ts`) and
  `scripts/advisor/backfill-drafts.mjs`.
- **One draft per media item.** The post id is `sha256('post:media:' +
  media_id)[:32]`, so a retried message, a second `propose_post` or the backfill
  finds the row instead of drafting again; its review is `kind='post'`, reason
  `social_draft` (02's deterministic review id), inserted only while the post is
  a draft. `created_by` is `engine`, or the admin's `users.id` for an angler
  draft made by approving the share.
- **When.** `ensureMediaDraft` runs from the consumer's `media_queue` applier
  (05's catch, action and scenery photos, videos and the count-board photo; a
  retry of a photo already queued still makes the missing draft), from the new
  `post_draft` action (`propose_post` on a photo already queued), from a media
  review approved or edited (an angler's shared photo, 06 § Angler photos; a
  boat photo with no draft yet) and from the backfill. It drafts a boat's photo
  or video only while it is `queued` or `approved`, the boat is not `rejected`
  and photo consent is active (re-checked at apply time); an angler's photo
  only once the team approved the share. A private photo is never drafted.
- **Kind and surfaces.** A video is a `reel`, a photo classified `count_board` a
  `story` (no caption, no collaborators, no tags, targets
  `["instagram_story","facebook_story"]`), any other still a `photo`
  (`["instagram","facebook"]`). "Any still the skipper marks story" is not
  built: there is no text command for it yet.
- **Caption.** Lines: the model line; the credit, "Aboard {boat} (@{handle}) out
  of {port}." (the mention; without a handle "Aboard {boat} out of {port}.") or
  for an angler "Photo: {credit}" ("Photo: a SkipperCast angler" when the credit
  is missing or anonymous); the boat's published report of the photo's local
  day as "Trip total: 45 vermilion, 12 lings for 22 anglers." (kept lines, at
  most four, uncertain ones left out; 09's "Limits of rockfish" wording is not
  derivable from the counts); "Text SkipperCast for today's report:
  (805) 555-0100" (`ADVISOR_NUMBER`, else `skippercast.com/text`); then, after a
  blank line, the hashtags: brand, `angler` for an angler's photo, the region's,
  then each species (the photo's fish ID top candidate at ≥ 0.6, and the
  report's kept species) followed by its report parent, at most 12. Every
  string is in `catalog/advisor/strings.json` (`caption_*`, en and es). The
  feed language is English (`FEED_LANGUAGE`); Spanish captions work through the
  same strings when a Spanish account exists. `captionProblem` enforces 2,200
  characters (code points), 30 hashtags and 20 mentions; a generated caption is
  cut to 2,200.
- **The model line.** `prompts/caption.ts`: the facts JSON (kind, species
  names, boat, port, the report line, the skipper's note), a forced tool
  `record_caption_line` with `{line}` (≤ 150 characters), `max_tokens` 120,
  temperature 0.4, 15 s timeout, under the global LLM cap, recorded as LLM
  feature `advisor:caption`. The model sees facts only, not the image. A line
  with a `#`, `@`, link, `%`, odds word or a number the facts do not contain is
  refused. A good line is cached in `job_state` `advisor.caption.<media id>`
  (`{line, language}`); without `ANTHROPIC_API_KEY`, past the cap, on an error
  or a refused line the fixed line is "{species} on deck." or "Fresh from the
  water." (not cached, so a later draft of the same photo can try again).
- **Collaborators and tags.** With a handle: `collaborators_json` `[handle]`
  (photos and reels) and `user_tags_json` `[{username: handle, x: 0.5, y: 0.5}]`
  (photos only). Angler photos get neither.
- **Holds on approval** (`admin/posts.ts approvalHold`, answered 409 with the
  reason): a photo of the post rejected or gone, a media review of it still
  open, a `has_person` photo whose media review has not approved it, a boat
  whose photo consent is no longer active, and a boat that is not verified (05
  § Verification excludes unverified boats from the social feed; this applies
  it to every boat post, not only the daily post).
- **Decisions** (the queue and the Posts view share `POST
  /api/admin/reviews/<review id>`): approve (optional `patch.scheduled_for`, a
  time in the next 60 days) sets `status='approved'`, `approved_by`,
  `approved_at`, and the post's `queued` photos `approved` (they become public
  for the pages and Meta's fetch; pages version bumped, the media job asked for
  `public.jpg`); edit takes `caption`, `targets` (a subset of the kind's),
  `collaborators` (≤ 3 usernames, none on a story), `user_tags` (≤ 20, x and y
  0-1, photos only) and `scheduled_for`, then approves (review `edited`);
  reject sets `rejected`. Only a `draft` can be decided. The text admin never
  decides a post (its kinds are skipper and media).
- **Revocation and rejection.** `post_revoke` (05 § Consent) sets every `draft`
  or `approved` post of the boat to `rejected` with `error='consent_revoked'`
  and closes its open review; posted ones stay. Rejecting a photo's media
  review does the same to its unposted posts (`error='media_rejected'`). "Forget
  me" deletes the contact's unposted posts (any status but `posted`, `partial`,
  `publishing`), their reviews and cached caption lines.
- **propose_post.** Skippers and crew, their own photo or video of their boat:
  refuses a rejected photo, a rejected boat and missing consent (the result says
  how to give it), says when a post exists; otherwise `media_queue` (a private
  photo, plus the `has_person`/`nsfw` media review its classification calls for)
  or `post_draft` (already queued), each with the optional `hint` (≤ 200
  characters), which reaches the prompt as a fact.
- **Backfill.** `node scripts/advisor/backfill-drafts.mjs [--apply] [--local]`:
  candidates are image and video media `queued` or `approved` (TA-S1 adds
  `approved`, so a photo whose `has_person` review was approved before this
  task is not missed), each run through `ensureMediaDraft`. The dry run lists
  what it would draft; `--apply` drafts through `wrangler d1 execute --json`
  (bindings inlined as SQL literals); a second run changes nothing. With
  `ANTHROPIC_API_KEY` in the owner's environment the captions get model lines.
- **Not built here.** Publishing, "post now", the schedule slots, the calendar
  grid, per-post stats and `GET /media/<id>.mp4` are TA-S2, TA-S4 and TA-S7.
- **Tests.** `tests/test_advisor_social_drafts.mjs`; `e2e/admin.spec.ts` opens
  the Posts view on the angler draft its approved share made, with axe.

## Daily "what's biting" post (SO-2) and weekly roundup (SP-5)

- Cron 06:30 local on days with at least one published verified report from
  the previous day: `social/daily-post.ts` builds the data (port, boats, top
  counts, conditions line, the confidence word), requests the graphic from
  the media job (`kind='daily'`), writes the caption (template, no model),
  and creates the draft with deterministic id `daily:<region>:<date>` so
  reruns update rather than duplicate. One approval posts it to IG + FB.
- Weekly roundup (SP-5): Sundays, a carousel of up to 10 approved catch
  photos from the week, by port and species, boats tagged as collaborators
  (3 max per Meta; the rest mentioned in the caption). Same draft path.

### As built (TA-S4)

- **Where.** `server/advisor/social/daily-post.ts` (the daily post and the
  roundup), `social/graphics.ts` (posts published from generated graphics),
  `social/calendar.ts` with `catalog/advisor/calendar.json`, the `daily-post`
  and `weekly-roundup` slots and `calendarTick` in `cron.ts`, `GET
  /media/post/<post_id>/<name>` (`routes/advisor.ts`), `GET
  /api/admin/posts/calendar` and `/api/admin/posts/<id>/graphics/<name>`
  (`routes/admin.ts`), the week grid (`web/admin/posts.tsx WeekCalendar`) and
  `tests/test_advisor_social_daily.mjs`.
- **The daily post.** Slot `daily-post`, 06:30 Pacific, for every active region
  (status `active` in its region.json): the reports of the previous local day
  with `status='published'`, `verified=1` and the boat still `verified`, one per
  boat (its latest). None: no post. Otherwise the facts: the place (the port's
  name, or the region's name when boats of several ports reported), each boat's
  kept counts (at most four lines; uncertain ones left out) and anglers, the top
  five counts summed by label, today's conditions line at the port with the most
  boats (`answers/reports.ts conditionsText` over `dailyInputs`, advisories
  first) and the confidence word: the best ladder label (Moderate, Low, else
  Insufficient) among the landing reports' targets with trips, never a number;
  without the daily feed the word is left out, without the forecast the
  conditions line too. The caption is a template (`catalog/advisor/strings.json`
  `daily_post_*`, no model): "What's biting out of {place}, {date}:", one line
  per boat ("Rita G: 45 vermilion, 12 lingcod for 22 anglers."), the conditions,
  "Landing reports, last 7 days: {word}.", the call to action and the hashtags
  (region and species). The draft's id is `sha256('daily:<region>:<date>')[:32]`
  with the posting day's local date, `media_json` `[]`, targets Instagram and the
  Page, its `post` review as for any draft. The card: `requestGraphic(kind:
  'daily')` with the post's id, `out_key advisor/posts/<id>/daily.jpg`, data
  `{title, port, date, lines: [Top counts, a line per boat (four at most)],
  conditions, confidence}`.
- **Reruns.** A rerun (the slot retried, or by hand) updates the same draft's
  caption and asks for the card again only when its data changed; a post that is
  no longer a draft is never changed. Writing a region's daily draft supersedes
  any older daily post of the region still in draft or approved without a time
  (`rejected`, `error='superseded'`, its review closed), so yesterday's card
  never goes out late. The same applies to roundups.
- **The roundup.** Slot `weekly-roundup`, Sundays 17:00: images approved or
  posted in the last 7 days, classified `fish` (a catch), with no open photo
  review; a boat's only while the boat is verified, in the region and has photo
  consent, an angler's (an approved share) when their home port is in the region.
  Grouped by (port, species from the fish ID), the largest group first and the
  newest photo first in each, taken round robin, at most **9** (the cover card
  makes Meta's carousel limit of 10; 09 said up to 10 photos). Caption: "This
  week out of {place}: {n} catches from {b} boats.", a line per port with its
  species, "Aboard: {boats}.", "Also aboard: @x." for handles past the three
  collaborators (the boats with the most photos), "Photos: {credits}." for
  anglers, the call to action and hashtags. `media_json` holds the photos (they
  are held like any post's photos, and each photo's boat must be verified with
  consent: `approvalHold` now checks every photo's boat, not only the post's),
  `collaborators_json` up to three handles, the graphic `kind: 'roundup'` with the
  photos, `{title, lines: [{label: port, value: "n · species"}], captions}`.
- **Holds and publishing.** A daily post, a roundup, or a Story with no photo
  uses its graphic (`graphics.ts usesGraphic`): approval is held while the
  graphic is pending ("the graphic is still being made") or failed; the
  publisher defers (dispatching the job) while it is pending. A daily post goes
  out as one image (`image_url` and the Page's `/photos` `url` =
  `/media/post/<id>/daily.jpg`), a roundup as a carousel of the cover and slides
  with its collaborators on the parent and a multi-photo Page post, a Story card
  as `STORIES` and a Page photo Story. Its photos go `posted` with it.
- **`/media/post/<post_id>/<name>`.** Served while the post is `approved`,
  `publishing`, `posted` or `partial` (Meta fetches during `publishing`; 10 said
  approved or posted), and only a name the graphic's done state lists. Admins
  preview any post's graphics at `/api/admin/posts/<id>/graphics/<name>`; the post
  card shows them (`graphics`).
- **The calendar.** `catalog/advisor/calendar.json`: `{lead_hours: 48, slots:
  [{id, weekdays, time_local, kind, region, capacity}]}` (09's `{weekday, ...}`
  became a `weekdays` list and a `capacity`): Stories 07:00 daily (10), the daily
  post 08:00 daily (drafted at 06:30, it needs the team's approval first),
  photos 11:00 and 17:00 on weekdays, a Reel Fridays 12:00, the roundup Sundays
  18:30 (drafted at 17:00). `calendarTick` runs on every 15-minute tick before
  `publishDue`: each slot instance in the next 48 h whose time fewer posts hold
  than its capacity takes the oldest approved post of its kind and region
  without `scheduled_for` (by `approved_at`), setting `scheduled_for` to the
  slot's local time in the region's zone (`zonedInstant`, DST-safe). A daily post
  or roundup fills only its own date's slot, and one approved after that slot
  passed goes out at once the same day. Empty slot instances are returned and
  logged (`advisor_calendar_empty`) when the set changes. **Behaviour change
  from TA-S2:** `publishDue` no longer posts an unscheduled approved post whose
  kind and region have calendar slots; it waits for its slot ("Post now" still
  posts at once; "Clear time" hands it back to the calendar). A kind without
  slots (a carousel) still goes out within 15 minutes.
- **The week grid.** `GET /api/admin/posts/calendar?start=` returns the 7 days
  from a Monday with each slot instance, its posts and whether it is empty or
  past, and the day's other scheduled or posted posts. The Posts view shows it
  above the list (7 columns, one on a narrow screen; empty slots marked, the
  count of empty slots ahead), with previous, this and next week.
- **Not built here.** Posting into an empty slot automatically (SO-3 tips posts
  are Next); the owner fills one by approving or posting by hand.

## Publishing (SO-4, SO-5, SP-7)

`social/publish.ts: publish(env, post)`, run by cron for `approved` posts
whose `scheduled_for <= now` (or immediately for "post now"), idempotent on
`status`:

1. `status='publishing'`.
2. Instagram: container per kind (image, `REELS`, `STORIES`, or `CAROUSEL`
   with children), poll `status_code` once per 10 s up to 5 min for video,
   then `media_publish`; store `ig_container_id`, `ig_media_id`. Quota check
   first; if the quota is exhausted, `scheduled_for += 1h`, status back to
   `approved`.
3. Facebook: `/photos` with `url` and `message` (or `/video_reels` three-phase
   upload for reels, `/photo_stories` for stories); store `fb_post_id`.
4. All targets ok → `posted`, `posted_at`; one failed → `partial` with
   `error`; the admin can retry the failed surface only.
5. Collab: after IG publish, read the media's `collaborators` status when
   the API exposes it (the Dec-2025 changelog added invite endpoints; TA-S3
   confirms the exact field) and store `collab_status`.
6. `recordPublish(env, kind, outcome, ms)` analytics point; the skipper is
   texted once per post: "Posted: {ig permalink}. Tagged @{handle}." using
   `GET /<ig_media_id>?fields=permalink`.

Graph API client (`social/meta.ts`): raw `fetch`, `appsecret_proof`
(HMAC-SHA256 of the token with the app secret) on every call, 20 s timeout,
error bodies logged with `code`/`subcode` only, a tiny retry on 5xx and on
code 4 / 17 / 32 (rate limits) with backoff, and a `fetcher` injection for
tests. Fixtures in `tests/fixtures/advisor/meta/`.

### As built (TA-S0)

- **Client.** `server/advisor/social/meta.ts`. `GRAPH_VERSION` is `v26.0` (the
  versions page, checked 2026-10-04: released 2026-07-29), `GRAPH_BASE`
  `https://graph.facebook.com/v26.0`. `graph(cfg, method, path, params)` adds
  `access_token` and `appsecret_proof` (lowercase hex HMAC-SHA256 of the token
  keyed with `META_APP_SECRET`) to the query of a GET or the
  `application/x-www-form-urlencoded` body of a POST, with a 20 s timeout. It
  retries an HTTP 5xx or error code 4, 17, 32 or 613 (613 added to 09's list:
  Meta's "calls within one hour" limit) up to three tries in all, waiting 2 s
  then 8 s; a network failure or timeout is retried only for a GET (a POST may
  have been applied). Failures throw `MetaError` and log `advisor_meta_error`
  with `edge` (the path's last word, or `node` for an id), `status`, `code`,
  `subcode`, `fbtrace_id`, `attempt` and `retrying` only: never the URL, the
  body, Meta's message (it can echo parameters) or a token. `cfg.attempts`
  lowers the tries (the health read uses 1); `fetcher` and `sleep` are injected
  by tests. Ids are checked against `^[\w.-]{1,64}$` before they reach a path.
- **Helpers.** `igContainer` (kinds `image`, `reel` = `REELS`, `story` =
  `STORIES` with an image or video, `carousel_item`, `carousel` = `CAROUSEL`
  with 2-10 children; captions dropped for stories and carousel items,
  `collaborators` (≤ 3) only on images, Reels and carousels, `user_tags` only
  on images and carousel items; media URLs must be https), `igContainerStatus`
  (`fields=status_code,status`), `igPublish` (`media_publish creation_id`),
  `igPublishingLimit` (`content_publishing_limit?fields=quota_usage,config`,
  parsed to `{quota_usage, quota_total, quota_duration}`), `igPermalink`,
  `fbPhoto` (`/photos` with `url`, `message`, and `published=false` plus
  `scheduled_publish_time` when scheduled), `fbVideoReel` (the 3-phase upload:
  `video_reels upload_phase=start`, then `POST
  rupload.facebook.com/video-upload/v26.0/<video_id>` with the headers
  `Authorization: OAuth <token>` and `file_url`, then `upload_phase=finish
  video_state=PUBLISHED description`), `fbPhotoStory` (an unpublished `/photos`
  then `/photo_stories photo_id`) and `pageInfo` (`id,name,
  instagram_business_account{id,username}`). The rupload call is the one
  request without `appsecret_proof`: that host is not the Graph API and takes
  the token as an `Authorization` header only.
- **Config.** `metaConfigured(env)` needs `META_APP_SECRET`, `META_PAGE_TOKEN`,
  `META_IG_USER_ID` and `META_PAGE_ID`; the Page token serves both surfaces on
  the Facebook-Login route, so `META_IG_TOKEN` stays declared in `env.ts` and
  unused. The deploy (`deploy-cloudflare.yml`, `cloudflare_deploy.sh`) uploads
  `META_APP_ID`, `META_APP_SECRET`, `META_VERIFY_TOKEN`, `META_IG_USER_ID`,
  `META_PAGE_ID` and `META_PAGE_TOKEN` as Worker secrets, each only when set.
- **Token script.** `scripts/advisor/meta-token.mjs` reads `META_APP_ID` and
  `META_APP_SECRET` from the environment (never argv), prints the Facebook Login
  dialog URL (`v26.0/dialog/oauth`, the scopes of step 4, `response_type=code`,
  a random `state`) with Meta's `https://www.facebook.com/connect/login_success.html`
  as the redirect (it must be in the app's Valid OAuth Redirect URIs;
  `--redirect-uri` overrides), takes the pasted landing address (the `state`
  must match) or a bare code, exchanges it for a short-lived and then a
  long-lived user token, lists `/me/accounts` with the proof, picks the only
  Page or `--page <id>`, and prints `META_PAGE_ID`, `META_PAGE_TOKEN` and
  `META_IG_USER_ID`. It checks `content_publishing_limit` with the Page token
  (proves `instagram_content_publish`), asks for `account_type` and fails on
  anything but `BUSINESS`; Meta does not document that field for the IG User
  node on this route, so when it is refused the script says so and asks the
  owner to confirm Business in the Instagram app. `debug_token` reports whether
  the Page token expires (`expires_at: 0`). Nothing is written to disk.
- **Health.** `GET /api/admin/health` `meta` is `{configured, quota_usage,
  quota_total, checked_at, error}`: not configured makes no call; otherwise one
  `content_publishing_limit` read (one try) at most every 10 minutes, cached in
  `job_state` `advisor.meta.quota` (failures too, as `error: 'unavailable'`), so
  the banner's once-a-minute health read does not spend Meta's rate limit.
  There is no token expiry line: the Page token does not expire.
- **Schema.** Migration `0011_advisor_social` (02): `advisor_posts`,
  `advisor_post_stats`, `advisor_contacts.ig_sid` with the unique index
  `contact_ig_sid`.
- **Tests.** `tests/test_advisor_meta.mjs` with the recorded responses in
  `tests/fixtures/advisor/meta/` (placeholder ids and tokens only).

### As built (TA-S2)

- **Where.** `server/advisor/social/publish.ts` (`publish`, `publishDue`),
  `fbFeed` added to `social/meta.ts`, the admin actions in
  `server/advisor/admin/posts.ts` (`postNow`, `schedulePost`, `retryPost`) and
  their routes, the `/media` route (`server/routes/advisor.ts`), `PostActions`
  in `web/admin/post-card.tsx`, `tests/test_advisor_social_publish.mjs`.
- **When.** `advisorCron` runs `publishDue` on every 15-minute tick (not a daily
  slot), only while `ADVISOR_SOCIAL_ENABLED=true` and `metaConfigured`: posts in
  `publishing` (a video still processing) first, then `approved` posts whose
  `scheduled_for` is past or null, oldest due first, at most 5 a tick, one after
  the other. An approved post without a time therefore goes out within 15
  minutes; TA-S4's calendar fills `scheduled_for`. The admin's "Post now" runs
  the same `publish` in the request.
- **One run** (`publish(env, postId, deps, {retry})`): a lease in `job_state`
  `advisor.publish.lock.<post id>` (10 minutes, an UPSERT that takes only an
  expired lock), so the cron and "Post now" never run one post at once. A post
  that is not `publishing` is checked again with `approvalHold` (consent
  revoked, the boat unverified, a photo rejected or under review): a hold sets
  `failed` with the reason. Every image needs `derived_at`: without it the media
  job is dispatched and the post stays `approved` (`deferred`); a photo the job
  gave up on (`derived_error`) fails the post. Then `status='publishing'`.
- **Media URLs.** `${ADVISOR_PUBLIC_BASE}/media/<id>.jpg` (the derived
  `public.jpg`) for feed images and carousel items, `/media/<id>.story.jpg` (the
  derived 1080 x 1920 `story.jpg`, no fallback to the original) for Stories, and
  `/media/<id>.mp4` for videos: an `approved` or `posted` video's original (MP4
  or MOV, served with its own type, `video/mp4` or `video/quicktime`) with
  single-range support (`206` with `Content-Range`, `416` past the end) through
  an R2 range get.
- **Instagram.** The quota is read first on every run that still needs
  Instagram (`content_publishing_limit`; `quota_total` 50 when Meta omits it):
  used up -> `scheduled_for = max(scheduled_for, now) + 1 h` (from now when the
  time is past, so a past post is not tried every tick), status back to
  `approved`, nothing sent to either surface. Containers: `image` (caption),
  `REELS` (`video_url`, `share_to_feed=true`, caption), `STORIES` (`image_url`
  story.jpg, or `video_url` for a video), carousel (`is_carousel_item` children,
  `VIDEO` for a video item, then `CAROUSEL` with the children and the caption).
  `ig_container_id` is written the moment Meta returns it, and carousel
  children as they are made (`job_state` `advisor.publish.<post id>`
  `ig_children`), so a rerun never makes a second container. Every container's
  `status_code` is read before `media_publish` (images are normally `FINISHED`
  on the first read): every 10 s, at most 30 reads in a run without a bound,
  6 in a cron run and 1 for "Post now" and retry; still `IN_PROGRESS` -> the post
  stays `publishing` and the next tick reads it again, until 30 minutes after
  the container was made (09's 5 minutes is the poll inside one run; a tick is
  15 minutes). `ERROR` or `EXPIRED` (or the deadline) fails the surface and
  clears the container, so a retry makes a new one; `PUBLISHED` on a stored
  container fails the surface with "check Instagram" and keeps it. After
  `media_publish`: `ig_media_id`, the permalink and the skipper's text.
- **Facebook.** One photo: `/photos` with `url` and `message` (`fb_post_id` is
  the returned `post_id`, else the photo id). Several photos: each uploaded with
  `published=false` (ids kept in `advisor.publish.<post id>` `fb_photos`), then
  `POST /<page-id>/feed` with `message` and `attached_media[i]={"media_fbid"}`
  (`fbFeed`); a video item fails the Page side (the Page's multi-photo post
  takes photos only). A Reel: `fbVideoReel` with the `.mp4` URL and the caption
  as `description`. A Story: `fbPhotoStory` with `story.jpg`, stored as
  `fb_story_id`; a video Story to the Page is not built (no `video_stories`
  helper). Meta's own Page scheduling is not used: our cron posts both surfaces
  at the time.
- **Outcome.** Every targeted surface with its id -> `posted`, `posted_at`, the
  post's media `posted`, the progress state deleted; one done and one failed ->
  `partial`, both failed -> `failed`, with `error` as `instagram: ...;
  facebook: ...` (the MetaError text: edge, HTTP status, Meta's code and
  subcode; never a token, URL or Meta's message). Instagram and the Page run in
  the same tick, so a Page post goes out while an Instagram video is still
  processing. A failed surface is not tried again by the cron (its error is in
  the progress state); the admin retry clears those errors and runs only the
  surfaces without an id. `recordPublish(env, {kind, outcome, ms})` once per run
  (outcomes `posted`, `partial`, `failed`, `pending`, `deferred`, `quota`,
  `held`, `error`).
- **The skipper's text.** After Instagram publishes and the permalink is read:
  the boat's owner (an `active` contact; not with `ADVISOR_REPLIES_ENABLED`
  off) gets `social_posted` "Posted: {link}" or `social_posted_tagged` "Posted:
  {link}. Tagged @{handle}." when the boat's handle is a collaborator, a user
  tag or a mention in the caption (strings in en and es). The outbound id is
  `outboundId(post id, 'posted')`, so it is sent once whatever reruns. A crew
  member who sent the photo is not texted; an angler's photo texts no one.
- **Admin.** `POST /api/admin/posts/<id>/publish` (an `approved` post: its
  `scheduled_for` cleared, published now), `/schedule` `{scheduled_for: ISO |
  null}` (an `approved` post; future and within 60 days, the approve decision's
  check; null posts it on the next tick) and `/retry` (a `partial` or `failed`
  post). Post now and retry answer 409 while `ADVISOR_SOCIAL_ENABLED` is off or
  the Meta secrets are missing. Each answers `{post, outcome?, error?}`. The
  Posts view's non-draft cards show `PostActions`: a time field with "Save
  time", "Clear time" and "Post now" for an approved post, "Retry the failed
  part" for a partly posted or failed one, and "Published to" with the surfaces
  that have an id.
- **Not built here.** `GET /media/post/<post_id>/<name>` for generated graphics
  (10 lists it under TA-S2; no post references a graphic until TA-S4 builds the
  daily post, so the route goes with it), the `scheduled` status (unused:
  `approved` with a time is the schedule), video Stories to the Page and the
  `ffprobe` checks on videos.
- **Privacy note.** Video originals are not metadata-stripped at intake (TA-C4
  strips JPEG and PNG only), so the public `.mp4` could carry the camera's
  location atoms. Resolved by the video privacy fix (§ Derived images, As built
  (video privacy)): `.mp4` now serves only the job's stripped copy.
- **Tests.** `tests/test_advisor_social_publish.mjs`: photo, carousel, a Reel
  `IN_PROGRESS` across two ticks with one container, a Story, the quota, partial
  failure and the retry of the failed surface only, idempotent reruns (a stored
  container, the lease, carousel children), the skipper's text in en and es,
  the switch off, derived files, holds, the admin routes, the cron hook and the
  `/media` story and video routes with ranges.

### As built (TA-S3)

- **Containers.** `publish.ts` `tagsOf(post)` reads `collaborators_json` (valid
  usernames, at most 3) and `user_tags_json` (`{username, x, y}` with x and y
  0-1, at most 20); a Story takes neither. Collaborators go on a photo's image
  container, a Reel and a carousel's parent container; user tags on a photo's
  image container, or on a carousel's first image item (the post's tags carry no
  item index). `meta.ts igContainerParams` still drops anything Meta does not
  take for that container kind.
- **Status on publish.** A post published to Instagram with collaborators gets
  `collab_status='invited'` with its `ig_media_id`; otherwise it stays null.
- **The invite read.** Meta's IG Media node has a `collaborators` edge
  ("users who are added as collaborators on an Instagram Media object",
  Instagram API with Facebook Login only; the IG Media reference, checked
  2026-10-04). Its fields come from Ayrshare's documentation of the same call
  (Meta's edge page could not be fetched from here):
  `GET /<ig-media-id>/collaborators?fields=id,username,invite_status`, where
  `invite_status` is `Accepted`, `Pending` or `Declined`, and only accounts that
  allow collaborator tagging are listed. The Dec 2025 collaboration-invite
  endpoints appear to be the invitee's side (tools built on them list and answer
  invites sent to the account), which a publisher does not need. If the first
  live read shows other field names, `igCollaborators` is the one place to
  change.
  `meta.ts igCollaborators` reads the edge (lower-case usernames; an unknown
  status is null). `publish.ts collabTick`, called by `advisorCron` on every
  tick, runs at most hourly (`job_state` `advisor.collab.checked_at`): posted or
  partial posts with an `ig_media_id`, `collab_status='invited'` and
  `posted_at` in the last 14 days, oldest first, 20 a run, one try each. The
  post's status from its own collaborators: any `Pending`, unknown or not listed
  -> stays `invited`; else any `Declined` -> `declined`; else `accepted`. A
  failed read changes nothing and is logged with Meta's codes only. After 14
  days an unanswered invite stays `invited`.
- **Admin.** The post card shows "Collaboration invite" with the status
  (invited, accepted, declined); `collab_status` is in the post's JSON.
- **Tests.** `tests/test_advisor_social_publish.mjs` (TA-S3 section): the
  parameters on each container kind, bad stored values dropped, no status
  without collaborators or Instagram, `igCollaborators` parsing, the status
  rule, the hourly read with its window, a failed read and the switch.

## Stories (SP-4)

Cron 07:00 local: for each verified boat's count-board photo from the
previous day with consent, and for the daily conditions card (a generated
graphic), publish a Story to IG and the Page. The "Text SkipperCast"
footer with the number is baked into `story.jpg` by the media job because
the API cannot add stickers. Stories need no admin approval once the source
photo's review (if any) is approved; a `has_person` hold blocks them like
any other media.

### As built (TA-S5)

- **Where.** `server/advisor/social/stories.ts` (`morningStories`), the
  `morning-stories` slot in `cron.ts` (07:00 Pacific), `tests/test_advisor_social_stories.mjs`.
- **When.** Only while `ADVISOR_SOCIAL_ENABLED=true` and the Meta secrets are
  set: these Stories are approved by the engine, so they are made only when they
  can go out that morning (with the switch off nothing piles up for later).
- **Count boards.** For each active region, each boat that is `verified` with
  active photo consent and has a photo classified `count_board` taken during the
  previous local day (`queued`, `approved` or `posted`; the boat's latest): the
  photo's Story post is TA-S1's draft (`sha256('post:media:' + id)[:32]`; made
  now through `ensureMediaDraft` when missing). While it is a draft and
  `approvalHold` finds nothing (no open photo review, a `has_person` photo only
  once its review approved it, the photo not rejected, consent active, the boat
  verified), the engine approves it: `status='approved'`, `approved_by` null,
  `approved_at`, `scheduled_for` = today's Stories slot (07:00 from the
  calendar), the photo `queued` -> `approved` (Meta fetches its `story.jpg`, the
  photo above the "Text SkipperCast" band, 1080 x 1920) and the open `post`
  review closed as `approved` with the note `auto: story`. A held one stays a
  draft for the team; a post already approved or posted is left alone.
- **The conditions card.** One Story per region a day with no photo
  (`media_json` `[]`), id `sha256('story:conditions:<region>:<date>')[:32]`,
  inserted `approved` at the slot's time with no review (it is made from public
  forecast data), and `requestGraphic(kind: 'story')` with `{title: "Today out of
  {region name}", lines: [the conditions line with any advisory first, "Landing
  reports: {word}"]}` (the 1080 x 1920 card with the footer band). Without a
  forecast and without an advisory there is no card that day.
- **Publishing.** The existing path: `calendarTick` counts them in the Stories
  slot, `publishDue` posts them (the card once the job has rendered it:
  `STORIES` with `/media/post/<id>/story.jpg` and the Page photo Story from the
  same URL; a count board with `/media/<id>.story.jpg`). No caption, no
  collaborators, no tags, as Meta's Stories require.
- **Profile.** § Instagram profile below: the bio, the highlight covers and the
  three highlight scripts as copy the owner pastes (TA-O4).

## Instagram profile (SP-1; TA-S5)

Copy for the owner to paste when setting up the account (§ Setup step 1). It
states only what the service does today: reports come from skippers, answers
describe reported activity with the confidence word, never odds, and rules
come with their source.

**Name field:** `SkipperCast | Fishing reports`

**Bio** (Instagram allows 150 characters; this is 91):

> Central Coast fishing reports from the boats. Text us what's biting, rules or a fish photo.

**Link:** `https://skippercast.com/text?s=ig` (label it "Text SkipperCast"; the
`s=ig` source tags the first message `[via ig]`, 03 § deep links).

**Highlight covers.** Three covers, 1080 x 1920, made in any editor from the
site's tokens (`dist/tokens.css`): the deep field `#082e3b`, a centred kelp
`#54dacb` line icon about 400 px wide, no text on the cover (Instagram prints
the highlight's name under it).

| Highlight | Name under it | Icon |
| --- | --- | --- |
| Reports | `Reports` | a clipboard with three ticked lines (a count board) |
| Fish ID | `Fish ID` | a rockfish outline with a magnifying glass |
| Tips | `Tips` | a lingcod jig, or a hook and a knot |

**Highlight scripts.** Each frame is one Story (1080 x 1920, text on the deep
field, the "Text SkipperCast" band at the bottom as on every generated Story).
Post them as Stories once, then add them to the highlight.

*Reports* (4 frames)

1. "Fishing reports from the boats themselves. Skippers text us their counts after each trip."
2. "Every morning we post what the boats brought in: species, counts and anglers, boat by boat."
3. "Text 'what's biting' any time for the latest out of your port, with today's wind and seas."
4. "We describe what was reported, not odds. Text SkipperCast: link in bio."

*Fish ID* (4 frames)

1. "Not sure what you caught? Text us a photo."
2. "We name the likely species and the look-alikes to check, with the features that tell them apart."
3. "Size and bag limits come from our rules table with the CDFW source and the date we last checked it. Always confirm before you keep a fish."
4. "Text a photo to SkipperCast: link in bio."

*Tips* (4 frames)

1. "Ask us how to rig for lingcod, rockfish or halibut out of your port."
2. "Planning Saturday? Text the day and we'll send the forecast window and any advisory."
3. "Looking for a trip? We list the boats that report to us, with their booking links."
4. "Text SkipperCast: link in bio."

## Content calendar (SP-6)

`social/calendar.ts`: a weekly cadence in `catalog/advisor/calendar.json`
(`{weekday, time_local, kind, region}` slots: daily post every morning,
Stories at 07:00, two photo posts on weekdays at 11:00 and 17:00, one Reel
on Fridays, the roundup on Sundays). The cron fills each upcoming slot (48 h
ahead) with the oldest `approved` draft of the matching kind that has no
`scheduled_for`; empty slots stay empty in v1 (SO-3 tips posts are Next) and
the admin calendar shows them so the owner can post something by hand.

## Inbox: DMs and comment keywords (SP-8, SP-9; dark until Meta approval)

- Webhooks `GET/POST /api/advisor/inbound/meta` : the `hub.challenge`
  handshake with `META_VERIFY_TOKEN`; `X-Hub-Signature-256` checked with the
  app secret; events deduplicated by message/comment id in
  `advisor_messages.provider_id` (channels `instagram_dm`,
  `instagram_comment`). Subscribe the IG account with
  `POST /<ig-user-id>/subscribed_apps?subscribed_fields=messages,comments`.
- DMs: a contact keyed by IGSID (`advisor_contacts.ig_sid`, added in
  migration 0011, unique) runs through the same engine with
  `channel='instagram_dm'`; replies go to `POST /<ig-user-id>/messages`
  within the 24-hour window; every third reply ends with the "continue by
  text" line and the `text?s=igdm` link.
- Comments: `comments` webhook → keyword match (`catalog/advisor/keywords.json`:
  `RIG`, `REPORT`, `ID`, `BOATS` → a canned private reply with the matching
  guide link and the text-us link); exactly one private reply per comment
  (Meta's limit), via `POST /<ig-user-id>/messages` with
  `recipient.comment_id`. Non-keyword comments that are questions get the
  engine's answer as a public reply (`POST /<comment-id>/replies`) only when
  `ADVISOR_INBOX_PUBLIC_REPLIES=true`; default off.
- Off (`ADVISOR_INBOX_ENABLED=false`): the webhook verifies and acks and
  writes nothing.

### As built (TA-S6)

- **Where.** `server/advisor/social/inbox.ts` (handshake, signature, payload,
  keywords, questions), `server/advisor/channels/instagram.ts` (the adapter and
  `commentChannel`), `catalog/advisor/keywords.json`, the routes in
  `server/routes/advisor.ts`, the `comment_reply` action in `consumer.ts`, the
  comment path and the DM line in `engine.ts`, `igSendMessage`,
  `igCommentReply` and `igSubscribeApps` in `social/meta.ts`, "Subscribe
  webhooks" in the Health view (`POST /api/admin/meta/subscribe`),
  `tests/test_advisor_instagram.mjs` and the owner's runbook
  [advisor Meta App Review](../../operations/runbooks/advisor-meta-app-review.md).
  Meta's docs could not be fetched from the build environment: the request
  shapes below are those this plan and Meta's Instagram messaging docs name
  (Graph `v26.0`); the first live call in the runbook's step 5 confirms them.
- **Webhook.** `GET` answers `hub.challenge` as text when `hub.mode=subscribe` and
  `hub.verify_token` equals `META_VERIFY_TOKEN` (constant time), else `403`.
  `POST` reads the raw body (at most 256 KB, else `400`) and checks
  `X-Hub-Signature-256` (`sha256=` + hex HMAC-SHA256 with `META_APP_SECRET`,
  WebCrypto verify) before parsing; missing or wrong is `401`. Then, with
  `ADVISOR_INBOX_ENABLED` off or the Meta secrets missing, `200 {}` and nothing
  written. Both share the other webhooks' per-IP limiter and sit behind the
  advisor gate (`TEXT_ADVISOR_ENABLED`), so the owner turns the advisor on
  before Meta can verify the URL.
- **Payload.** `object: "instagram"`; entries for another account than
  `META_IG_USER_ID` are skipped. `messaging[].message` with text or image
  attachments is a DM (`instagram_dm`, `provider_id` the `mid`); echoes, events
  from our own id, `read`, `reaction`, deleted, unsupported and text-less shares
  are skipped. Image attachments become media placeholders like any channel's;
  the consumer downloads them through the Instagram adapter, which fetches only
  `https` URLs on `fbsbx.com`, `fbcdn.net` or `cdninstagram.com` (not a redirect
  elsewhere). `changes[]` with `field: comments` is a comment
  (`instagram_comment`, `provider_id` the comment id, `to` the post's media id);
  ours (from `META_IG_USER_ID`, which includes our public replies) are skipped.
- **Only comments that need an answer are stored** (`classifyComment`): the first
  word, after `@mentions`, emoji and punctuation, folded to lower case without
  accents, is a keyword word (`catalog/advisor/keywords.json`: RIG rig, rigs,
  rigging, aparejo, aparejos, montaje; REPORT report, reports, reporte,
  reportes, informe; ID id, identify, identificar, identifica, especie; BOATS
  boats, boat, barcos, barco, lanchas, botes), or, with
  `ADVISOR_INBOX_PUBLIC_REPLIES=true`, a question (`?` or `¿`, or a question
  word first) that is not a Stage 1 command. Everything else is never written,
  so a comment that needs nothing leaves no trace. Stored messages go through
  `storeInbound` (deduplicated by channel and provider id, so Meta's retries
  change nothing) and the queue like a text.
- **Contacts.** `findOrCreateContact(db, null, {igSid, channel})` upserts on the
  unique `ig_sid`; no phone key is needed. Source on the first message: `igdm` or
  `igcomment` (02's `instagram` became these two, next to TA-C6's `ig` for the
  bio link). `channelFor` returns the Instagram adapter for a contact with an
  `ig_sid` and no number, and the consumer's address for it is the IGSID. A
  person who later texts us is a separate phone contact (there is no linking).
- **DMs.** The engine runs as for a text: the channel line in the brief says
  "Instagram direct message (1,000 characters a message)"; there is no texting
  welcome (rates, HELP, STOP) and no contact card; Stage 1 commands work by DM
  (STOP, START, HELP, forget me, send me my data). Replies split at 1,000
  characters (`splitForChannel`, `INSTAGRAM_CHUNK`). `send` posts
  `POST /<ig-user-id>/messages` with `recipient={"id": IGSID}` and
  `message={"text": ...}`, then one `{"attachment": {"type": "image", "payload":
  {"url": ".../media/<id>.jpg"}}}` per media key (approved or posted media only,
  at most 4, else `media-not-public`). Before any call it checks Meta's 24-hour
  window against the contact's last inbound DM (`advisor_messages.created_at`);
  outside it the row is `failed` with `outside-window` and Meta is not called.
  Meta's own refusal (code 10, subcode 2018278) maps to the same; another 4xx is
  `failed` `meta-<status>-<code>`; a 5xx or network failure is `unknown` (one try:
  a POST that failed may have been delivered).
- **"Continue by text".** `runTurn` wraps the turn for `instagram_dm`: when this
  is the contact's third, sixth, ... answered DM (distinct `in_reply_to` of
  outbound `instagram_dm` rows that did not fail, this message excluded so a
  retry counts the same), the last text gets a blank line and `igdm_continue`
  ("Easier by text? Keep going with us by text message:" and
  `{{link:text:igdm}}` = `/text?s=igdm`). Not on commands, guards or caps, and not
  without `ADVISOR_NUMBER` (`/text` needs it). `links.ts` gained `text:<source>`,
  `chat` (the web chat) and `boats:<port>` (the port page's boats section), and
  `resolveLinks` a visit source argument.
- **Keyword replies.** The engine's comment path (after Stage 0: replies on, not
  blocked or stopped) answers a keyword with one action `comment_reply` `private`:
  the keyword's string (`comment_rig`, `comment_report`, `comment_id`,
  `comment_boats`, en and es by the matched word's language) with `{guide}` and
  `{text}` links, visit source `ig`: RIG the species page of a species named in
  the comment (else lingcod), REPORT the port page of a port named (else the
  region default's first port), ID the web chat (`/chat.html`), BOATS the port
  page's `#boats-title`; `{text}` is `/text?s=ig`. Intent `comment.keyword.<key>`.
- **One private reply per comment.** The consumer's `comment_reply` applier works
  only on the comment's own inbound row and sends through `commentChannel`
  (`POST /<ig-user-id>/messages` with `recipient={"comment_id": ...}`) under the
  fixed outbound key `comment:private`: with the inbound row unique per comment
  id, a retried or redelivered comment never sends a second one, and the channel
  refuses a second send in one turn (`one-reply`). Meta's 7-day limit for a
  private reply is checked against the comment row's time (`outside-window`).
- **Public replies** (`ADVISOR_INBOX_PUBLIC_REPLIES=true` only): a question
  comment skips the commands and Stage 2 flows and goes to the model with the
  read-only data tools only (`get_port_report`, `get_conditions`, `get_rules`,
  `get_species`, `get_strategy`, `get_trips`) and the brief's channel line "a
  public reply to an Instagram comment under our post: one or two short
  sentences, nothing personal, no questions back". The answer becomes one
  `comment_reply` `public` (`POST /<comment-id>/replies`, key `comment:public`);
  a refusal, an empty answer or a turn that ran out of tools or time posts
  nothing (`comment.unanswered`, its review kept); the daily caps answer nothing
  publicly. A question stored while the switch was on is not answered after it
  is turned off (`comment.ignored`).
- **Untrusted text.** DM and comment text reaches the model only as the user turn
  under the same system prompt as a text; a comment can at most produce the one
  reply under itself.
- **Subscribing.** Health shows the inbox switches and whether
  `META_VERIFY_TOKEN` and `META_APP_SECRET` are set; "Subscribe webhooks" calls
  `POST /<ig-user-id>/subscribed_apps` with `subscribed_fields=messages,comments`
  (one try; `409` without the secrets, `502` with Meta's codes on failure).
- **Not built.** Video, audio and sticker attachments in DMs (ignored), linking an
  Instagram contact to a phone contact, hiding or deleting comments, Meta's
  `HUMAN_AGENT` tag (7-day window), story mentions and replies.
- **Owner steps.** Business Verification, App Review, the Instagram "Allow access
  to messages" toggle, Live, then `ADVISOR_INBOX_ENABLED=true`: the runbook. The
  privacy notice section (`dist/privacy.html#text-advisor`) is a draft for the
  owner and counsel to approve.

## Insights (SP-10, SC-7 feed)

Cron 03:00 local: for every `posted` post from the last 30 days, fetch IG
`insights` (FEED: `views, reach, likes, comments, saved, shares, follows,
profile_visits, profile_activity`; REELS adds `ig_reels_avg_watch_time`;
STORY: `views, reach, replies, follows, profile_visits`, fetched before the
24 h expiry) and FB post insights (`post_impressions_unique`, reactions,
comments, shares), upserting `advisor_post_stats` by day. "Chats started"
per post is computed from contacts whose first message carried
`[via ig:<post_id>]` (the per-post CTA links are `text?s=ig&p=<post_id>`),
and website visits from telemetry `s=ig&p=`. The admin Posts view and the
funnel use these.

### As built (TA-S7)

- **Where.** `server/advisor/social/insights.ts` (`collectInsights`,
  `storyInsightsTick`, `postStats`), `igMediaInsights`, `fbPostReach`,
  `fbPostCounts` and `parseInsights` in `social/meta.ts`, the `insights` slot and
  the tick in `cron.ts`, `stats` on the post card (`admin/posts.ts`,
  `web/admin/post-card.tsx` `PostStatsTable`), `social` in the Funnel
  (`admin/funnel.ts`, `web/admin/funnel.tsx`), migration
  `0012_advisor_source_post`, `tests/test_advisor_insights.mjs`. Meta's docs could
  not be fetched from the build environment; the metric names are this plan's,
  and the test fixtures are written in the documented response shapes.
- **The slot.** `insights`, 03:00 Pacific, while the Meta secrets are set (no
  other switch: it only reads): posts `posted` or `partial` with `posted_at` in the
  last 30 days, newest first, at most 100. Instagram (`ig_media_id`):
  `GET /<media>/insights?metric=` FEED `views,reach,likes,comments,saved,shares,
  follows,profile_visits,profile_activity` for photos, carousels, daily posts and
  roundups; REELS the same plus `ig_reels_avg_watch_time`; STORY
  `views,reach,replies,follows,profile_visits`. The Page (`fb_post_id`, not for a
  Story: a Page photo Story has no post insights): `GET /<post>/insights?metric=
  post_impressions_unique` and `GET /<post>?fields=shares,reactions.summary(
  total_count).limit(0),comments.summary(total_count).limit(0)` (09's "reactions,
  comments, shares"; a post with no `shares` field has 0). `job_state`
  `advisor.insights.last_run` holds the run's counts.
- **Stories.** Meta keeps a Story's insights only while it is up, so every cron
  tick, at most hourly (`job_state` `advisor.insights.stories_at`, an
  UPSERT-with-WHERE claim), reads the Stories posted less than 24 hours ago; the
  last read before expiry is the final count. Neither the tick nor the slot reads
  a Story 24 hours or more after it was posted.
- **Rows.** `advisor_post_stats` by (post, `instagram`|`facebook`, the local day of
  the read), an UPSERT: Meta's values are lifetime totals, so the latest row is the
  count and the rows by day its growth. Instagram fills `views`, `reach`, `likes`,
  `comments` (a Story's `replies`), `saved`, `shares`, `follows`,
  `profile_visits`; the Page `reach` (unique impressions), `likes` (reactions),
  `comments`, `shares`. `link_taps` stays 0: no media metric gives it (a profile's
  link taps are an account metric). `raw_json` is `{metrics, notes?}`: every value
  read, `profile_activity` and `ig_reels_avg_watch_time` included.
- **Tolerance.** Meta refuses the whole set (code 100) when one metric does not
  apply; then each metric is asked alone, and one still refused counts 0 with the
  note `<metric>: unavailable` (a metric missing from an answer: `not returned`).
  Any other failure (an expired Story, a deleted post, the token, rate limits after
  the client's retries) skips that surface of that post: nothing is written, so an
  earlier row is never replaced by zeros, and the run counts it `failed`.
- **Chats started.** TA-C6 parsed `[via ig:<post_id>]` but kept only the source:
  migration `0012_advisor_source_post` adds `advisor_contacts.source_post_id`
  (indexed), set with `source` on the contact's first inbound message. `/text`
  takes `p`: with `s=ig` and `p` matching `^[\w-]{1,64}$` the marker is
  `[via ig:<p>]` (`intents.ts` accepts `ig:` with up to 64 characters, so a
  32-character post id fits). The per-post link is
  `<ADVISOR_PUBLIC_BASE>/text?s=ig&p=<advisor_posts.id>`; a link carrying the
  Instagram media id instead counts for the post too. Nothing writes the link into
  captions yet (Instagram captions do not link); it is for the owner's Story link
  stickers, the bio while a post is pinned, or Page posts.
- **Website visits per post** are not counted: page telemetry
  (`server/telemetry.ts`) records the visit source `s` (so `s=ig` visits are in
  the Funnel's page table) but not a post id. Carrying `p` would change the
  telemetry contract; left for a later task.
- **Admin.** A posted or partly posted post's card has `stats`: the latest row per
  surface (the columns above, `day`, `fetched_at`, `notes`) and `chats`; the card
  shows a table with one column per metric, the chats started and the notes. The
  Funnel's `social` (D1): posts published in the window, the latest readings of
  those posts summed per surface and per post kind, `chats_from_posts` (contacts
  whose first message named one of them), `chats_from_instagram` (new contacts
  with source `ig`, `igdm` or `igcomment`) and `site_visits_per_post: null`; no
  post id leaves the API.
- **SC-7** (the weekly skipper text) can read these rows; it is not built here.

## Next

- SO-3 tips/forecast posts: a template per weekday from `catalog`
  strategies and the forecast feed, through the same draft and approval path.
- SP-11 TikTok and YouTube Shorts: a `targets_json` extension and two more
  clients; needs their developer apps.
- SP-12 regional accounts: `META_*` secrets become per-region in a
  `catalog/advisor/accounts.json` map.
- SP-13 contest: a `review.media` reason `contest_entry` and a monthly cron.
