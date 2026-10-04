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
   highlights "Reports", "Fish ID", "Tips" (content for the highlights is in
   TA-S6).
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

Video: no processing. Validity checks are done by the job with `ffprobe`
when present on the runner (container, codec, duration, size) and the
result is stored on the media row; a video that fails gets `failed` with a
reason the admin can see.

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

## Stories (SP-4)

Cron 07:00 local: for each verified boat's count-board photo from the
previous day with consent, and for the daily conditions card (a generated
graphic), publish a Story to IG and the Page. The "Text SkipperCast"
footer with the number is baked into `story.jpg` by the media job because
the API cannot add stickers. Stories need no admin approval once the source
photo's review (if any) is approved; a `has_person` hold blocks them like
any other media.

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

## Next

- SO-3 tips/forecast posts: a template per weekday from `catalog`
  strategies and the forecast feed, through the same draft and approval path.
- SP-11 TikTok and YouTube Shorts: a `targets_json` extension and two more
  clients; needs their developer apps.
- SP-12 regional accounts: `META_*` secrets become per-region in a
  `catalog/advisor/accounts.json` map.
- SP-13 contest: a `review.media` reason `contest_entry` and a monthly cron.
