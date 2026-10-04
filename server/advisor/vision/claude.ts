// The Claude vision provider (docs/plans/text-advisor/07-vision.md § Claude
// provider): one Messages API request per method, the image as a base64
// content block, and one forced tool whose input_schema is the result schema,
// so the answer arrives as structured tool input (no JSON-in-prose parsing).
// Every field is validated before it leaves this file: confidences clamped to
// 0..1, species keys limited to the list the prompt offered (a bad key becomes
// null with its label kept), at most three candidates sorted by confidence.
//
// Spend guards: ADVISOR_GLOBAL_DAILY_VISION through request_limits
// (key global:vision:<day>, the boat-lookup UPSERT ... RETURNING idiom), a 60 s
// timeout, one retry after 2 s on HTTP 429/529. Each request writes an `llm`
// analytics point, feature advisor:vision:<method>, and one log line with token
// counts only (never the image, a label or the media id).
import type {Env} from '../../env.ts';
import {recordLlm} from '../../analytics.ts';
import type {LlmUsage} from '../../analytics.ts';
import {advisorSettings} from '../settings.ts';
import {advisorLog} from '../log.ts';
import {classifyPrompt, countBoardPrompt, fishIdPrompt} from '../prompts/vision.ts';
import {speciesForTargets} from './species.ts';
import type {VisionSpecies} from './species.ts';
import {IMAGE_KINDS, MediaTooLarge, ProviderNotConfigured, UnsupportedImage, VisionCapReached} from './errors.ts';
import type {Classification, CountBoardReading, FishId, ImageInput, ImageKind, VisionMethod, VisionProvider} from './index.ts';

export const API = 'https://api.anthropic.com/v1/messages';
export const MAX_TOKENS = 600;
export const TIMEOUT_MS = 60_000;
export const RETRY_DELAY_MS = 2_000;
/** The Messages API per-image limit (bytes of the decoded image). */
export const CLAUDE_IMAGE_LIMIT = 5 * 1024 * 1024;
export const IMAGE_MIMES: readonly string[] = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];

type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
export interface ClaudeVisionDeps {
  fetcher?: Fetcher;                       // default: fetch
  now?: () => number;                      // epoch ms; default Date.now
  sleep?: (ms: number) => Promise<void>;   // the 429/529 back-off; default setTimeout
  /** A region's target list (region.json `species`); default: the build-injected REGIONS. */
  regionTargets?: (region: string) => readonly string[] | null;
}

// ---- Tool schemas (the result types of 07 § Interface, minus provider/model/ms) --

const conf = {type: 'number', minimum: 0, maximum: 1};
const nullableString = {type: ['string', 'null']};

const CLASSIFY_TOOL = {
  name: 'record_classification',
  description: 'Record what kind of photo this is and whether people, fish or text are visible.',
  input_schema: {
    type: 'object', additionalProperties: false,
    required: ['kind', 'kind_confidence', 'has_person', 'person_confidence', 'has_fish', 'text_present', 'nsfw'],
    properties: {
      kind: {type: 'string', enum: [...IMAGE_KINDS]}, kind_confidence: conf,
      has_person: {type: 'boolean'}, person_confidence: conf,
      has_fish: {type: 'boolean'}, text_present: {type: 'boolean'}, nsfw: {type: 'boolean'},
    },
  },
};

const COUNT_BOARD_TOOL = {
  name: 'record_count_board',
  description: 'Record the transcription of a fishing count board.',
  input_schema: {
    type: 'object', additionalProperties: false,
    required: ['boat_name', 'date_text', 'date_iso', 'date_confidence', 'trip_type', 'anglers', 'lines', 'notes', 'overall_confidence'],
    properties: {
      boat_name: nullableString, date_text: nullableString,
      date_iso: {type: ['string', 'null'], description: 'YYYY-MM-DD, only when unambiguous'}, date_confidence: conf,
      trip_type: nullableString, anglers: {type: ['integer', 'null'], minimum: 0},
      lines: {type: 'array', items: {
        type: 'object', additionalProperties: false, required: ['label', 'count', 'released', 'confidence'],
        properties: {label: {type: 'string'}, count: {type: ['integer', 'null'], minimum: 0}, released: {type: ['integer', 'null'], minimum: 0}, confidence: conf},
      }},
      notes: nullableString, overall_confidence: conf,
    },
  },
};

function fishTool(keys: readonly string[]) {
  return {
    name: 'record_fish_id',
    description: 'Record the most likely species for the fish in the photo.',
    input_schema: {
      type: 'object', additionalProperties: false,
      required: ['candidates', 'needs_better_photo', 'reason'],
      properties: {
        candidates: {type: 'array', maxItems: 3, items: {
          type: 'object', additionalProperties: false, required: ['species_key', 'label', 'confidence', 'cues'],
          properties: {species_key: {type: ['string', 'null'], enum: [...keys, null]}, label: {type: 'string'}, confidence: conf, cues: {type: 'array', items: {type: 'string'}, maxItems: 3}},
        }},
        needs_better_photo: {type: 'boolean'},
        reason: {type: ['string', 'null'], enum: ['blurry', 'partial', 'multiple_fish', 'no_fish', 'too_far', 'other', null]},
      },
    },
  };
}

// ---- Validation -------------------------------------------------------------------

export const clamp01 = (v: unknown): number => typeof v === 'number' && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : 0;
const bool = (v: unknown): boolean => v === true;
function str(v: unknown, max: number): string | null {
  if (typeof v !== 'string') return null;
  const s = v.replace(/\s+/g, ' ').trim();
  return s ? s.slice(0, max) : null;
}
function int(v: unknown, max: number): number | null {
  const n = typeof v === 'string' && /^\d+$/.test(v.trim()) ? Number(v) : v;
  return typeof n === 'number' && Number.isInteger(n) && n >= 0 && n <= max ? n : null;
}
function isoDate(v: unknown): string | null {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
  const d = new Date(v + 'T00:00:00Z');
  return Number.isFinite(d.getTime()) && d.toISOString().slice(0, 10) === v ? v : null;
}
const obj = (v: unknown): Record<string, unknown> => v && typeof v === 'object' && !Array.isArray(v) ? v as Record<string, unknown> : {};
const list = (v: unknown): unknown[] => Array.isArray(v) ? v : [];

type Meta = {provider: 'claude'; model: string; ms: number};

export function parseClassification(input: unknown, meta: Meta): Classification {
  const i = obj(input);
  const kind = (IMAGE_KINDS as readonly unknown[]).includes(i.kind) ? i.kind as ImageKind : 'unknown';
  return {kind, kind_confidence: clamp01(i.kind_confidence), has_person: bool(i.has_person), person_confidence: clamp01(i.person_confidence),
    has_fish: bool(i.has_fish), text_present: bool(i.text_present), nsfw: bool(i.nsfw), ...meta};
}

export const MAX_BOARD_LINES = 40;
export function parseCountBoard(input: unknown, meta: Meta): CountBoardReading {
  const i = obj(input);
  const lines = list(i.lines).flatMap(raw => {
    const l = obj(raw), label = str(l.label, 60);
    return label ? [{label, count: int(l.count, 100000), released: int(l.released, 100000), confidence: clamp01(l.confidence)}] : [];
  }).slice(0, MAX_BOARD_LINES);
  return {boat_name: str(i.boat_name, 80), date_text: str(i.date_text, 40), date_iso: isoDate(i.date_iso), date_confidence: clamp01(i.date_confidence),
    trip_type: str(i.trip_type, 40), anglers: int(i.anglers, 1000), lines, notes: str(i.notes, 300), overall_confidence: clamp01(i.overall_confidence), ...meta};
}

const REASON = /^[a-z_]{1,24}$/;
export function parseFishId(input: unknown, allowed: ReadonlySet<string>, meta: Meta): FishId {
  const i = obj(input);
  const candidates = list(i.candidates).flatMap(raw => {
    const c = obj(raw), key = typeof c.species_key === 'string' && allowed.has(c.species_key) ? c.species_key : null;
    const label = str(c.label, 60) ?? (typeof c.species_key === 'string' ? str(c.species_key, 60) : null);
    if (!label) return [];
    return [{species_key: key, label, confidence: clamp01(c.confidence), cues: list(c.cues).flatMap(q => { const s = str(q, 80); return s ? [s] : []; }).slice(0, 3)}];
  }).sort((a, b) => b.confidence - a.confidence).slice(0, 3);
  const needs = bool(i.needs_better_photo) || candidates.length === 0;
  const reason = typeof i.reason === 'string' && REASON.test(i.reason) ? i.reason : needs ? (candidates.length ? 'other' : 'no_fish') : null;
  return {candidates, needs_better_photo: needs, reason, ...meta};
}

// ---- Request ----------------------------------------------------------------------

/** Base64 of the bytes, in chunks (String.fromCharCode has an argument limit). */
export function base64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer); let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

const ORIENTATION_MEANING: Record<number, string> = {
  2: 'mirrored left to right', 3: 'upside down', 4: 'mirrored top to bottom', 5: 'mirrored and turned 90 degrees',
  6: 'turned 90 degrees: rotate it clockwise to view it upright', 7: 'mirrored and turned 90 degrees', 8: 'turned 90 degrees: rotate it counter-clockwise to view it upright',
};

/**
 * The prompt for one image: as given when its pixels are upright, else with one
 * sentence naming the EXIF orientation (2-8) that intake stripped, so a sideways
 * count board or fish is read the right way up. (The media job's upright
 * public.jpg usually does not exist yet when vision runs at intake, so the hint
 * is the reliable fix; the chain's public.jpg stand-in carries no orientation.)
 */
export function orientedPrompt(prompt: string, orientation: number | undefined): string {
  if (!orientation || orientation === 1 || !ORIENTATION_MEANING[orientation]) return prompt;
  return `${prompt}\n\nThe image may be rotated; orientation tag ${orientation} (${ORIENTATION_MEANING[orientation]}).`;
}

export function buildRequest(model: string, tool: {name: string}, prompt: string, mime: string, data: string) {
  return {model, max_tokens: MAX_TOKENS, temperature: 0, tools: [tool], tool_choice: {type: 'tool', name: tool.name},
    messages: [{role: 'user', content: [{type: 'image', source: {type: 'base64', media_type: mime, data}}, {type: 'text', text: prompt}]}]};
}

const count = (v: unknown): number => typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : 0;
const FEATURE: Record<VisionMethod, string> = {classify: 'advisor:vision:classify', count_board: 'advisor:vision:count_board', fish_id: 'advisor:vision:fish_id'};

/** The build-injected region manifests' target list, or null (tests without REGIONS, unknown region). */
function defaultRegionTargets(region: string): readonly string[] | null {
  const all = typeof REGIONS === 'undefined' ? null : REGIONS;
  return all && Object.hasOwn(all, region) ? all[region]!.species : null;
}

/** Count one Claude vision call against the global daily cap; throws VisionCapReached past it. */
export async function takeVisionCall(env: Env, limit: number, now: number): Promise<number> {
  if (!env.DB) throw new ProviderNotConfigured('claude', 'no-db');
  const day = Math.floor(now / 86400000);
  const row = await env.DB.prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1 RETURNING count')
    .bind('global:vision:' + day, (day + 2) * 86400).first<{count: number}>();
  const n = row?.count ?? Infinity;
  if (n > limit) { advisorLog('warn', 'advisor_vision_global_cap', {day, limit}); throw new VisionCapReached(limit); }
  return n;
}

export function createClaudeVision(deps: ClaudeVisionDeps = {}): VisionProvider {
  const fetcher: Fetcher = deps.fetcher ?? ((url, init) => fetch(url, init));
  const now = deps.now ?? Date.now;
  const sleep = deps.sleep ?? (ms => new Promise<void>(resolve => setTimeout(resolve, ms)));
  const regionTargets = deps.regionTargets ?? defaultRegionTargets;

  /** One method call: checks, cap, request (with one 429/529 retry), tool input, usage. */
  async function call(env: Env, method: VisionMethod, image: ImageInput, tool: {name: string}, prompt: string): Promise<{input: unknown; meta: Meta}> {
    const settings = advisorSettings(env);
    if (!env.ANTHROPIC_API_KEY) throw new ProviderNotConfigured('claude');
    if (!IMAGE_MIMES.includes(image.mime)) throw new UnsupportedImage(image.mime);
    const buffer = await image.bytes();
    if (buffer.byteLength > CLAUDE_IMAGE_LIMIT) throw new MediaTooLarge(buffer.byteLength, 'over the Claude per-image limit');
    await takeVisionCall(env, settings.globalDailyVision, now());
    const body = JSON.stringify(buildRequest(settings.visionModel, tool, orientedPrompt(prompt, image.orientation), image.mime, base64(buffer)));
    const usage: LlmUsage = {model: settings.visionModel, turns: 0, input_tokens: 0, output_tokens: 0, web_search_requests: 0};
    const started = now();
    let outcome = 'error';
    try {
      let response: Response | null = null;
      for (let attempt = 0; attempt < 2; attempt++) {
        if (attempt) await sleep(RETRY_DELAY_MS);
        response = await fetcher(API, {method: 'POST', signal: AbortSignal.timeout(TIMEOUT_MS),
          headers: {'x-api-key': env.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}, body});
        usage.turns!++;
        if (response.status !== 429 && response.status !== 529) break;
      }
      if (!response!.ok) throw Error(`vision HTTP ${response!.status}`);
      const data = await response!.json<{content?: {type: string; name?: string; input?: unknown}[]; usage?: Record<string, unknown>; model?: string}>();
      usage.input_tokens! += count(data.usage?.input_tokens) + count(data.usage?.cache_creation_input_tokens) + count(data.usage?.cache_read_input_tokens);
      usage.output_tokens! += count(data.usage?.output_tokens);
      const block = (data.content ?? []).find(b => b.type === 'tool_use' && b.name === tool.name);
      if (!block) { outcome = 'invalid'; throw Error('vision returned no tool input'); }
      outcome = 'ok';
      return {input: block.input, meta: {provider: 'claude', model: settings.visionModel, ms: now() - started}};
    } finally {
      recordLlm(env, FEATURE[method], outcome, usage);
      advisorLog(outcome === 'ok' ? 'info' : 'warn', 'advisor_vision_call', {method, outcome, model: usage.model, turns: usage.turns, input_tokens: usage.input_tokens, output_tokens: usage.output_tokens, ms: now() - started});
    }
  }

  return {
    name: 'claude',
    async classify(image, env) {
      const {input, meta} = await call(env, 'classify', image, CLASSIFY_TOOL, classifyPrompt());
      return parseClassification(input, meta);
    },
    async readCountBoard(image, env) {
      const {input, meta} = await call(env, 'count_board', image, COUNT_BOARD_TOOL, countBoardPrompt());
      return parseCountBoard(input, meta);
    },
    async identifyFish(image, env, region) {
      const species: VisionSpecies[] = speciesForTargets(regionTargets(region));
      const keys = species.map(s => s.key);
      const {input, meta} = await call(env, 'fish_id', image, fishTool(keys), fishIdPrompt(species));
      return parseFishId(input, new Set(keys), meta);
    },
    async health(env) {
      return env.ANTHROPIC_API_KEY ? {ok: true, detail: 'configured'} : {ok: false, detail: 'not-configured'};
    },
  };
}
