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
six synthetic test images (generated SVG→PNG in the repo under 50 KB each:
a drawn count board, a drawn fish silhouette, a blank, a photo-like scene
with a stick figure) so the pipeline runs end to end offline. No real
customer photos ever enter the repo.

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
everything else go) without decoding; PNG `eXIf`, `tEXt`, `iTXt` and `zTXt`
chunks are dropped the same way. The sniffer accepts `image/heic` and
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
