# 07. Vision: providers, contracts and schemas

Story OP-8, used by SC-1, SC-3, ID-1, OP-2, SP-3. Code: `server/advisor/vision/`.

No image reading exists in this repository today. The owner's Hermes machine
will provide a local classifier (privacy and cost); Claude vision is the
fallback and the reference implementation. Both sit behind one interface,
so the rest of the advisor never knows which answered.

## Interface (`vision/index.ts`)

```ts
export type ImageKind = 'count_board' | 'fish' | 'action' | 'scenery' | 'video' | 'document' | 'unknown';
export interface Classification {
  kind: ImageKind; kind_confidence: number;            // 0..1
  has_person: boolean; person_confidence: number;
  has_fish: boolean;
  text_present: boolean;                               // helps route to count-board reading
  nsfw: boolean;                                       // held for review when true
  provider: 'hermes' | 'claude'; model: string; ms: number;
}
export interface CountBoardReading {
  boat_name: string | null; date_text: string | null; date_iso: string | null; date_confidence: number;
  trip_type: string | null; anglers: number | null;
  lines: {label: string; count: number | null; released: number | null; confidence: number}[];
  notes: string | null; overall_confidence: number;    // 0..1
  provider: 'hermes' | 'claude'; model: string; ms: number;
}
export interface FishId {
  candidates: {species_key: string | null; label: string; confidence: number; cues: string[]}[]; // sorted desc, max 3
  needs_better_photo: boolean; reason: string | null;  // 'blurry' | 'partial' | 'multiple_fish' | 'no_fish' | ...
  provider: 'hermes' | 'claude'; model: string; ms: number;
}
export interface VisionProvider {
  name: 'hermes' | 'claude';
  classify(image: ImageInput, env: Env): Promise<Classification>;
  readCountBoard(image: ImageInput, env: Env): Promise<CountBoardReading>;
  identifyFish(image: ImageInput, env: Env, region: string): Promise<FishId>;
  health(env: Env): Promise<{ok: boolean; detail: string}>;
}
export interface ImageInput {media_id: string; bytes: () => Promise<ArrayBuffer>; mime: string; width?: number; height?: number}
```

`vision/index.ts: visionChain(env)` reads `ADVISOR_VISION_PROVIDERS`
(`hermes,claude` default) and returns an object with the same three methods
that tries each provider in order. A provider is skipped for 10 minutes
after a failure (state in `job_state` key `advisor.vision.<name>.down_until`),
so a dead Hermes costs one failed call, not one per message. Each result is
cached in `advisor_media.classification_json` keyed by method name, so a
retried message never re-runs vision. The Worker never decodes images: a
provider receives the metadata-stripped original. An original over 4.5 MB
(the Claude per-image limit is 5 MB; a 48 MP iPhone JPEG can exceed it) is
not sent; the consumer dispatches the media job (09), waits for `public.jpg`
(≤ 1440 px) by re-queueing the message with `retry({delaySeconds: 30})` up
to 4 times, and classifies from that. The skipper's reply arrives after the
job runs, normally under a minute.

Global cap `ADVISOR_GLOBAL_DAILY_VISION` applies to the Claude provider only.

## Hermes provider (`vision/hermes.ts`): the contract Hermes must implement

Hermes is reached at `HERMES_VISION_URL` (a Cloudflare Tunnel in front of a
small HTTP service on the Hermes machine, or a Tailscale Funnel; the owner
chooses) with `Authorization: Bearer <HERMES_VISION_TOKEN>`. The service is
not in this repository; this section is the spec the owner hands to the
Hermes side. If Hermes cannot meet it, the chain runs Claude-only and
nothing else changes.

```
POST /v1/vision/classify        body: multipart `image` (jpeg/png) + json `meta` {media_id, region}
  -> 200 Classification (fields above except provider/model/ms, which the client fills from headers X-Vision-Model and timing)
POST /v1/vision/count-board     same input -> 200 CountBoardReading
POST /v1/vision/fish-id         same input + meta.region -> 200 FishId; species_key must come from the enum the client sends in meta.species_keys (from catalog/species.json)
GET  /v1/health                 -> 200 {ok: true, models: {...}}
```

Rules: respond within 20 s or return 503; never store the image beyond the
request (the owner's privacy preference: these images are customer content,
not farm/house records, so a cloud fallback is acceptable, but the local
service still must not keep them); return `confidence` honestly (the
advisor's thresholds assume calibrated-ish 0..1); `species_key` must be
one of the keys sent, or null with the free-text `label`.

A conformance script `scripts/advisor/vision-conformance.mjs` posts the
fixture images under `tests/fixtures/advisor/vision/` to a URL and checks
the response shapes and thresholds, so the Hermes side can test itself.

## Claude provider (`vision/claude.ts`)

Raw `fetch` to the Messages API, model `ADVISOR_VISION_MODEL`, one request
per method, image sent as base64 `image` content block, `max_tokens: 600`,
and a tool-use "schema" trick: define one tool whose `input_schema` is the
result schema and force `tool_choice: {type: 'tool', name: ...}` so the
model's answer is already structured JSON (no JSON-in-prose parsing).
Prompts (`prompts/vision.ts`):

- **classify**: "Classify this photo for a fishing-report service…" with the
  kind definitions (a count board is a whiteboard, chalkboard, printed sheet
  or screen listing catch counts, boat and date; `action` is people fishing,
  a deck, a fish being landed; `fish` is a single fish or a few fish shown for
  identification). `has_person` is true for any recognisable face or body;
  a hand holding a fish is `has_person=false` unless a face is visible.
- **count board**: transcribe every line; map obvious abbreviations but keep
  the original label; numbers that are unreadable are null with low
  confidence; never invent a boat name or date.
- **fish ID**: the species list for the region is in the prompt with 2–3
  cues each (from `catalog/advisor/lookalikes.json`); ask for the top three
  candidates with calibrated confidence; `needs_better_photo` when the fish is
  partial, blurry, or several fish are shown.

Usage goes to `recordLlm(env, 'advisor:vision:<method>', outcome, usage)`.
Fixtures: `tests/fixtures/advisor/vision/*.json` recorded responses, plus
four synthetic test images (as built; six were planned), generated SVG→PNG
in the repo under 50 KB each (a drawn count board, a drawn fish silhouette,
a blank, a photo-like scene with a stick figure), so the pipeline runs end
to end offline. No real customer photos ever enter the repo.

## Thresholds (single source: `vision/index.ts` `THRESHOLDS`)

| Decision | Rule |
| --- | --- |
| route to count-board reading | `kind='count_board' && kind_confidence >= 0.6`, or `text_present && kind_confidence < 0.6` (try it; a reading with `overall_confidence < 0.5` falls back to asking) |
| accept a reading without asking | `overall_confidence >= 0.8` and every line `confidence >= 0.7`; lower → the confirmation text marks uncertain lines with `?` ("12? lingcod") |
| hold for human (OP-2) | `has_person && person_confidence >= 0.5`, or `nsfw` |
| fish ID high / medium / ask | `>= 0.85` / `>= 0.6` / else |
| protected species warning | any candidate `species_key in ('yelloweye','cowcod','canary'…)` per `catalog/advisor/protected.json` with `confidence >= 0.3` |

## EXIF and derived images

Metadata is stripped in the consumer before storage and before any provider
sees the image (TA-C4): a JPEG marker walk drops every APPn segment except
APP0 (JFIF) and an APP2 segment whose payload starts with `ICC_PROFILE`
(kept so Display P3 photos do not shift colour; EXIF, GPS, XMP and
everything else go) without decoding; PNG `eXIf`, `tEXt`, `iTXt`, `zTXt`
and `tIME` chunks are dropped the same way (as built, TA-C4: COM segments and
anything after the JPEG's EOI go too, and a file whose walk fails is rejected,
not stored). The sniffer accepts `image/heic` and
`image/heif` (iMessage can deliver HEIC when the sender's camera format is
High Efficiency): a HEIC is stored and routed to the media job for
conversion before any provider sees it. Providers receive the
stripped original (iPhone JPEGs are 2–4 MB, within the Claude image limit;
the client sends `width`/`height` from the JPEG SOF header so a provider can
decline absurd sizes). Derived images (`public.jpg` ≤ 1440 px, `thumb.jpg`
320 px, `story.jpg` 1080×1920 with the "Text SkipperCast" footer baked in)
are produced by the `advisor-media` runner job (09 § derived images) with
Pillow from the layout spec in `catalog/advisor/graphics.json`. HEIC from
iPhones arrives as JPEG via Messages on iMessage; a HEIC from the upload page
is converted by the job (`pillow-heif` on the runner) or, failing that, the
person is asked for a JPEG. Species keys in results are `catalog/species.json`
keys or `catalog/advisor/species-extra.json` keys (02).

## As built (TA-V1)

- **Modules.** `vision/index.ts` holds the contract types, `THRESHOLDS`, the
  `decide*` functions and `visionChain`; the error classes and `IMAGE_KINDS`
  live in `vision/errors.ts` (re-exported by `index.ts`) so `claude.ts` can
  import them without a circular import; `vision/species.ts` builds the
  per-region species list from `catalog/species.json`, `catalog/targets.json`
  and the three `catalog/advisor/` files, bundled into the Worker as JSON
  imports (about 80 KB, mostly `species.json`).
- **Signature.** `visionChain(env, deps)` takes injectable deps (`fetcher`,
  `now`, `sleep`, `regionTargets`, and `providers` by name, which TA-V2 uses
  for the Hermes client). `identifyFish(image, region)` takes the region id;
  the species list comes from that region's `species` targets, and every key
  the advisor knows when the region is unknown.
- **Thresholds as functions.** `decideCountBoard`, `decideReadingUsable`
  (the `overall_confidence < 0.5` fallback), `decideAcceptReading` (returns the
  line indexes to mark with `?`, including unreadable counts), `decideHold`,
  `decideFishBand` (`needs_better_photo` or no candidates is always `ask`) and
  `decideProtected`. `THRESHOLDS` also holds `maxImageBytes` (4.5 MiB) and
  `providerDownMs` (10 minutes).
- **Protected warning.** 06 § fish ID says a yelloweye or cowcod candidate
  "at any confidence" adds the warning; the table above says `>= 0.3`. TA-V1
  implements the table (`>= 0.3`); TA-I3 settled it: the reply uses `>= 0.3`
  (06 now says so). `protected.json` lists yelloweye, cowcod, bronzespotted
  and (since TA-A3) quillback with `must_release: true` and canary with
  `must_release: false` (a sub-bag species); all five trigger the warning, and
  the notes defer to the rules table. TA-A3 checked the list against CDFW's
  groundfish summary (06 § As built (TA-A3)).
- **Cache.** `classification_json` is `{classify?, count_board?, fish_id?}`,
  written with SQLite `json_set` so one method never overwrites another; a
  corrupt value is ignored and replaced. Only `classify` sets `has_person`.
- **Chain failures.** A provider error marks it down (`job_state`
  `advisor.vision.<name>.down_until`, an ISO time) and the next is tried; a
  success after the window clears the key. Input errors (`UnsupportedImage`,
  `MediaTooLarge`) are thrown at once and never mark a provider down; so are
  `ProviderNotConfigured` (no `ANTHROPIC_API_KEY`; Hermes without
  `HERMES_VISION_URL` is skipped before it is called, and the TA-V1 Hermes
  entry is a stub that always reports `not-configured`) and
  `VisionCapReached`, which the chain rethrows when no provider answered.
  Otherwise the chain throws `VisionUnavailable`. The image bytes are read
  once per chain call, whatever the number of providers.
- **Over 4.5 MB.** The chain throws `MediaTooLarge` and logs
  `advisor_vision_too_large`; dispatching the media job and re-queueing until
  `public.jpg` exists is TA-M1's consumer path (10 lists that test under
  TA-V1; it moves to TA-M1; see "As built (TA-M1)" below). The Claude provider
  also refuses anything over its own 5 MiB limit.
- **Claude request.** `temperature: 0`, a 60 s `AbortSignal.timeout`, one
  retry after 2 s on HTTP 429 or 529 (both attempts count as turns in the
  `llm` point). The tool schemas carry `enum`s (image kinds; for fish ID the
  region's species keys plus `null`; the `reason` codes) so the model is
  steered to valid values, and the parser validates every field anyway. The
  analytics feature names use the cache keys: `advisor:vision:classify`,
  `advisor:vision:count_board`, `advisor:vision:fish_id`. The global cap key
  is `global:vision:<UTC day number>` in `request_limits`, counted before the
  request, as the boat lookup does. A response without the forced
  `tool_use` block is recorded with outcome `invalid`.
- **Validation.** Confidences are clamped to 0..1 (non-numbers become 0);
  booleans must be `true`; `date_iso` must be a real `YYYY-MM-DD` date; counts
  must be non-negative integers (a digit string is accepted); lines without a
  label are dropped and at most 40 kept; fish candidates without a label are
  dropped, an unknown `species_key` becomes null with its label kept, cues
  are trimmed to 3, candidates sorted by confidence and trimmed to 3; no
  candidates forces `needs_better_photo` with reason `no_fish`.
- **Species keys.** `catalog/advisor/species-extra.json` adds the rockfish
  species (parent `rockfish`), cabezon and kelp greenling (no catalog parent;
  `target: 'reef'`), bronzespotted and quillback (for `protected.json`), and
  `california-halibut` and `king-salmon` as synonyms (`same_as_parent`) of
  `halibut` and `salmon`, which the species list canonicalises away.
  White seabass, Pacific halibut, albacore, bluefin, yellowtail, Dungeness and
  lingcod already have catalog keys and are not repeated.
  `catalog/advisor/lookalikes.json` covers those keys with 2–3 cues each
  (and the same cues in Spanish, `cues_es`, since TA-A6). Since TA-A3 every
  fish key has an entry and each cites its own CDFW or NOAA Fisheries page
  (06 § As built (TA-A3)).
- **Fixtures.** Four synthetic PNGs, not six: `count-board.png`, `fish.png`,
  `blank.png`, `deck-person.png` (≤ 256 px, about 1 KB each), rendered by
  `scripts/advisor/make-fixture-images.mjs` from inline SVG with its own
  rasteriser (rect, circle, ellipse, line, polygon, and text in a 5×7 bitmap
  font whose `y` is the glyph top) and PNG encoder; `--check` verifies the
  committed files and the test re-renders them. Their SHA-256 is pinned in
  `scripts/web-vendor-sha256.json`, which `check_repository.py` requires for
  every binary file; the script updates those entries. The recorded responses
  (`classify-*.json`, `count-board.json`, `fish-id*.json`) are hand-written to
  the tool-use response shape, each with `_source` and `_image`.

## As built (TA-M1)

- **The wait.** The consumer does it before the handler, not after a
  `MediaTooLarge`: once the message's media are stored, if any of them is an
  image over 4.5 MB or a HEIC/HEIF without `derived_at`
  (`media.ts` `awaitingDerived`) and `GITHUB_TOKEN` is set, it dispatches the
  job (`requestMediaJob`, at most once a minute), marks the message `queued`
  with error `media-derive` and calls `retry({delaySeconds: 30})`. It waits on
  the first **three** deliveries, not four: the advisor queue's `max_retries`
  is 3 (`scripts/wrangler_config.mjs`), so a fourth retry would send the
  message to the dead-letter queue; the fourth delivery always runs the
  handler (`DERIVED_WAITS`, tested against the queue config). An inline turn
  (web chat, no queue) never waits.
- **Reading `public.jpg`.** `visionChain` reads the original; when it is over
  4.5 MB or HEIC/HEIF it reads `advisor/derived/<id>/public.jpg` instead (as
  `image/jpeg`) when that exists. Still over the limit, `MediaTooLarge` as
  before, and the intake answers with the upload link (log
  `advisor_media_too_large`). A HEIC with no `public.jpg` still reaches the
  provider as HEIC, which refuses it (`UnsupportedImage`), as before.
- **Derived files.** As 09 § Derived images "As built (TA-M1)": `public.jpg`
  at most 1440 px on the long side, quality 88, converted to sRGB through the
  embedded ICC profile and written without EXIF or a profile; `thumb.jpg`
  320 px; `story.jpg` 1080 x 1920.
