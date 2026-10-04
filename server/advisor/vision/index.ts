// Text Advisor vision (docs/plans/text-advisor/07-vision.md): the provider
// interface, the result types, the thresholds every caller decides with, and
// the provider chain.
//
//   visionChain(env, deps).classify(image)
//     -> advisor_media.classification_json has a `classify` result? return it (no provider call)
//     -> the original is over 4.5 MB, or HEIC/HEIF? read the media job's public.jpg instead (TA-M1)
//     -> still over 4.5 MB (no public.jpg yet)? throw MediaTooLarge (the consumer waited for it, TA-M1)
//     -> for each provider in ADVISOR_VISION_PROVIDERS order:
//          skip it while job_state advisor.vision.<name>.down_until is in the future;
//          skip it silently when it is not configured (hermes without HERMES_VISION_URL);
//          call it; on success cache the result under its method key and return;
//          on failure mark it down for 10 minutes and try the next
//     -> every provider failed or was skipped: throw VisionUnavailable
//
// The cache is one JSON object per media row, {classify?, count_board?, fish_id?},
// so a retried queue message never re-runs vision; classify also sets
// advisor_media.has_person (the OP-2 index). Input errors (UnsupportedImage,
// MediaTooLarge) and the Claude daily cap (VisionCapReached) are not provider
// faults: they never mark a provider down. The Worker never decodes images.
import type {Env} from '../../env.ts';
import {advisorSettings} from '../settings.ts';
import {advisorLog} from '../log.ts';
import type {VisionProviderName} from '../types.ts';
import {PROTECTED} from './species.ts';
import type {ProtectedSpecies} from './species.ts';
import {createClaudeVision} from './claude.ts';
import {MediaTooLarge, UnsupportedImage, ProviderNotConfigured, VisionCapReached, VisionUnavailable} from './errors.ts';
import type {ClaudeVisionDeps} from './claude.ts';
// TA-M1: the derived public.jpg an oversized or HEIC original is read through.
import {derivedKey, HEIF_MIMES} from '../media.ts';

// ---- Contract (07 § Interface) --------------------------------------------------

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
/**
 * `orientation`: the JPEG's EXIF Orientation (2-8) when the stored pixels are not
 * upright (intake strips the tag itself, media.ts); absent when upright, and for
 * the media job's public.jpg, which is always upright.
 */
export interface ImageInput {media_id: string; bytes: () => Promise<ArrayBuffer>; mime: string; width?: number; height?: number; orientation?: number}

export {IMAGE_KINDS, MediaTooLarge, UnsupportedImage, ProviderNotConfigured, VisionCapReached, VisionUnavailable} from './errors.ts';

// ---- Thresholds (07 § Thresholds: the single source) ----------------------------

export const THRESHOLDS = Object.freeze({
  /** Route to count-board reading: kind='count_board' at or above this, or text_present below it. */
  countBoardKind: 0.6,
  /** A reading below this overall confidence falls back to asking (05 § count board). */
  readingUsable: 0.5,
  /** Accept a reading without asking: overall at or above this... */
  acceptOverall: 0.8,
  /** ...and every line at or above this; lower lines are marked "?" in the confirmation. */
  acceptLine: 0.7,
  /** Hold for a human (OP-2): has_person with person_confidence at or above this, or nsfw. */
  holdPerson: 0.5,
  /** Fish ID bands: high at or above, medium at or above, else ask for a better photo. */
  fishHigh: 0.85,
  fishMedium: 0.6,
  /** A protected-species candidate at or above this confidence adds the release warning. */
  protectedWarning: 0.3,
  /** Originals larger than this are not sent to any provider (Claude's per-image limit is 5 MB). */
  maxImageBytes: 4.5 * 1024 * 1024,
  /** A provider that failed is skipped for this long. */
  providerDownMs: 10 * 60 * 1000,
});

/** Route to readCountBoard (07 § thresholds row 1). */
export function decideCountBoard(c: Pick<Classification, 'kind' | 'kind_confidence' | 'text_present'>): boolean {
  return (c.kind === 'count_board' && c.kind_confidence >= THRESHOLDS.countBoardKind)
    || (c.text_present && c.kind_confidence < THRESHOLDS.countBoardKind);
}

/** A reading good enough to draft from; below it the skipper is asked to resend or text the numbers. */
export function decideReadingUsable(r: Pick<CountBoardReading, 'overall_confidence'>): boolean {
  return r.overall_confidence >= THRESHOLDS.readingUsable;
}

export interface ReadingDecision {accept: boolean; uncertain: number[]}
/**
 * Accept without asking (07 § thresholds row 2): overall >= 0.8 and every line
 * >= 0.7. `uncertain` lists the line indexes the confirmation marks with "?"
 * (low confidence or an unreadable count).
 */
export function decideAcceptReading(r: Pick<CountBoardReading, 'overall_confidence' | 'lines'>): ReadingDecision {
  const uncertain = r.lines.flatMap((l, i) => l.confidence < THRESHOLDS.acceptLine || l.count === null ? [i] : []);
  return {accept: r.overall_confidence >= THRESHOLDS.acceptOverall && r.lines.length > 0 && uncertain.length === 0, uncertain};
}

/** Hold for a human before anything is published (OP-2). */
export function decideHold(c: Pick<Classification, 'has_person' | 'person_confidence' | 'nsfw'>): boolean {
  return (c.has_person && c.person_confidence >= THRESHOLDS.holdPerson) || c.nsfw;
}

export type FishBand = 'high' | 'medium' | 'ask';
/** 06 § fish ID: high >= 0.85, medium >= 0.6, else ask (also when a better photo is needed or nothing was found). */
export function decideFishBand(f: Pick<FishId, 'candidates' | 'needs_better_photo'>): FishBand {
  const top = f.candidates[0]?.confidence ?? 0;
  if (f.needs_better_photo || !f.candidates.length) return 'ask';
  return top >= THRESHOLDS.fishHigh ? 'high' : top >= THRESHOLDS.fishMedium ? 'medium' : 'ask';
}

/** The protected species among the candidates at >= 0.3 (catalog/advisor/protected.json), in candidate order. */
export function decideProtected(f: Pick<FishId, 'candidates'>, list: readonly ProtectedSpecies[] = PROTECTED): ProtectedSpecies[] {
  const out: ProtectedSpecies[] = [];
  for (const c of f.candidates) {
    const hit = c.species_key && c.confidence >= THRESHOLDS.protectedWarning ? list.find(p => p.key === c.species_key) : undefined;
    if (hit && !out.includes(hit)) out.push(hit);
  }
  return out;
}

// ---- Hermes (TA-V2 builds the client; registered here as a stub) ----------------

/** Placeholder until TA-V2: always reports not-configured, so the chain skips it silently. */
export const hermesStub: VisionProvider = {
  name: 'hermes',
  classify: async () => { throw new ProviderNotConfigured('hermes'); },
  readCountBoard: async () => { throw new ProviderNotConfigured('hermes'); },
  identifyFish: async () => { throw new ProviderNotConfigured('hermes'); },
  health: async () => ({ok: false, detail: 'not-configured'}),
};

// ---- Chain -------------------------------------------------------------------------

export type VisionMethod = 'classify' | 'count_board' | 'fish_id';
type Results = {classify: Classification; count_board: CountBoardReading; fish_id: FishId};

export interface VisionDeps extends ClaudeVisionDeps {
  /** Replace providers by name (tests; TA-V2 passes the Hermes client). */
  providers?: Partial<Record<VisionProviderName, VisionProvider>>;
}
export interface VisionChain {
  classify(image: ImageInput): Promise<Classification>;
  readCountBoard(image: ImageInput): Promise<CountBoardReading>;
  identifyFish(image: ImageInput, region: string): Promise<FishId>;
}

export const downKey = (name: string): string => `advisor.vision.${name}.down_until`;

const INPUT_ERRORS = (e: unknown): boolean => e instanceof MediaTooLarge || e instanceof UnsupportedImage;
const short = (e: unknown): string => String((e as Error)?.message ?? e).slice(0, 200);

/** The cached result for `method`, or null (no DB, no row, nothing cached, unreadable JSON). */
async function cached<M extends VisionMethod>(env: Env, mediaId: string, method: M): Promise<Results[M] | null> {
  if (!env.DB) return null;
  const row = await env.DB.prepare('SELECT classification_json FROM advisor_media WHERE id=?').bind(mediaId).first<{classification_json: string | null}>();
  if (!row?.classification_json) return null;
  try { const all = JSON.parse(row.classification_json); return all && typeof all === 'object' && all[method] && typeof all[method] === 'object' ? all[method] : null; }
  catch { return null; }
}

/** Store `result` under its method key, keeping the other methods' results; classify also sets has_person. */
async function store(env: Env, mediaId: string, method: VisionMethod, result: object): Promise<void> {
  if (!env.DB) return;
  const json = JSON.stringify(result);
  try {
    const base = "COALESCE(CASE WHEN json_valid(classification_json) AND json_type(classification_json)='object' THEN classification_json END,'{}')";
    if (method === 'classify') {
      await env.DB.prepare(`UPDATE advisor_media SET classification_json=json_set(${base},'$.classify',json(?)),has_person=? WHERE id=?`)
        .bind(json, (result as Classification).has_person ? 1 : 0, mediaId).run();
    } else {
      await env.DB.prepare(`UPDATE advisor_media SET classification_json=json_set(${base},'$.${method}',json(?)) WHERE id=?`).bind(json, mediaId).run();
    }
  } catch (error) { advisorLog('warn', 'advisor_vision_cache_failed', {method, reason: short(error)}); }
}

async function downUntil(env: Env, name: string): Promise<number | null> {
  if (!env.DB) return null;
  const v = (await env.DB.prepare('SELECT value FROM job_state WHERE key=?').bind(downKey(name)).first<{value: string}>())?.value;
  const t = v ? Date.parse(v) : NaN;
  return Number.isFinite(t) ? t : null;
}
async function markDown(env: Env, name: string, now: number): Promise<void> {
  if (!env.DB) return;
  const until = new Date(now + THRESHOLDS.providerDownMs).toISOString();
  await env.DB.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at')
    .bind(downKey(name), until, new Date(now).toISOString()).run().catch(() => {});
}
async function clearDown(env: Env, name: string): Promise<void> {
  await env.DB?.prepare('DELETE FROM job_state WHERE key=?').bind(downKey(name)).run().catch(() => {});
}

/** `image` with bytes() read at most once (several providers may need them; R2 is read once). */
function once(image: ImageInput): ImageInput {
  let pending: Promise<ArrayBuffer> | null = null;
  return {...image, bytes: () => (pending ??= image.bytes())};
}

/**
 * The provider chain for this env (07 § Interface). Providers come from
 * ADVISOR_VISION_PROVIDERS order; `deps` injects the fetcher, clock and sleep
 * the Claude provider uses, or whole providers.
 */
export function visionChain(env: Env, deps: VisionDeps = {}): VisionChain {
  const settings = advisorSettings(env);
  const now = deps.now ?? Date.now;
  const registry: Record<VisionProviderName, VisionProvider> = {hermes: hermesStub, claude: createClaudeVision(deps), ...deps.providers};

  async function run<M extends VisionMethod>(method: M, input: ImageInput, call: (p: VisionProvider, image: ImageInput) => Promise<Results[M]>): Promise<Results[M]> {
    const hit = await cached(env, input.media_id, method);
    if (hit) return hit;
    let image = once(input);
    let size = (await image.bytes()).byteLength;
    if (size > THRESHOLDS.maxImageBytes || (HEIF_MIMES as readonly string[]).includes(input.mime)) {
      // TA-M1: the media job's public.jpg (<= 1440 px, sRGB JPEG) stands in for the original.
      const derived = await env.ADVISOR_MEDIA?.get(derivedKey(input.media_id)).catch(() => null);
      if (derived) {
        const buffer = await derived.arrayBuffer();
        image = {media_id: input.media_id, mime: 'image/jpeg', bytes: async () => buffer};
        size = buffer.byteLength;
      }
    }
    if (size > THRESHOLDS.maxImageBytes) {
      advisorLog('info', 'advisor_vision_too_large', {method, bytes: size});
      throw new MediaTooLarge(size);
    }
    const reasons: string[] = [];
    let capped: VisionCapReached | null = null;
    for (const name of settings.visionProviders) {
      const provider = registry[name];
      if (!provider) continue;
      if (name === 'hermes' && !env.HERMES_VISION_URL) continue;          // not configured: skipped silently
      const until = await downUntil(env, name);
      if (until !== null && until > now()) { reasons.push(`${name}: down`); continue; }
      try {
        const result = await call(provider, image);
        if (until !== null) { await clearDown(env, name); advisorLog('info', 'advisor_vision_provider_up', {provider: name}); }
        await store(env, input.media_id, method, result);
        return result;
      } catch (error) {
        if (INPUT_ERRORS(error)) throw error;
        if (error instanceof ProviderNotConfigured) {
          if (name !== 'hermes') advisorLog('warn', 'advisor_vision_not_configured', {provider: name});
          reasons.push(`${name}: not-configured`); continue;
        }
        if (error instanceof VisionCapReached) { capped = error; reasons.push(`${name}: capped`); continue; }
        await markDown(env, name, now());
        advisorLog('warn', 'advisor_vision_provider_down', {provider: name, method, reason: short(error)});
        reasons.push(`${name}: failed`);
      }
    }
    if (capped) throw capped;
    throw new VisionUnavailable(reasons.join(', ') || 'no providers');
  }

  return {
    classify: image => run('classify', image, (p, i) => p.classify(i, env)),
    readCountBoard: image => run('count_board', image, (p, i) => p.readCountBoard(i, env)),
    identifyFish: (image, region) => run('fish_id', image, (p, i) => p.identifyFish(i, env, region)),
  };
}
