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
  migration 0009, unique) runs through the same engine with
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
