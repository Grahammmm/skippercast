// The Hermes vision provider (docs/plans/text-advisor/07-vision.md § Hermes
// provider; TA-V2): a client for the owner's local classifier, reached at
// HERMES_VISION_URL (a Cloudflare Tunnel or Tailscale Funnel) with
// `Authorization: Bearer HERMES_VISION_TOKEN`.
//
//   POST {url}/v1/vision/classify      multipart: `image` (the file) + `meta` (a JSON text field)
//   POST {url}/v1/vision/count-board   meta = {media_id, region, orientation?}
//   POST {url}/v1/vision/fish-id       meta = {media_id, region, species_keys, orientation?}
//   GET  {url}/v1/health               -> {ok: true, models: {...}}
//
// Every answer goes through the same validators as the Claude provider
// (vision/validate.ts): confidences clamped, a species_key outside the keys
// sent becomes null with its label kept. `model` comes from the X-Vision-Model
// response header; `ms` is measured here. A non-2xx status (503 included), a
// timeout (20 s), a body that is not JSON, or one without the method's
// required field is a provider error, so the chain marks Hermes down for 10
// minutes and asks the next provider. The image reaching this file is what
// the chain read through intake/reports.ts imageOf: the metadata-stripped
// original, or the media job's public.jpg for an oversized or HEIC original;
// HEIC and anything over 4.5 MB are refused here before any request, as the
// Claude provider refuses them. Logs carry the method, outcome, status and
// milliseconds only (never the image, a label or the media id).
import type {Env} from '../../env.ts';
import {advisorLog} from '../log.ts';
import {defaultRegionTargets, speciesForTargets} from './species.ts';
import {MediaTooLarge, ProviderNotConfigured, UnsupportedImage} from './errors.ts';
import {parseClassification, parseCountBoard, parseFishId} from './validate.ts';
import type {ResultMeta} from './validate.ts';
import type {ImageInput, VisionMethod, VisionProvider} from './index.ts';

export const HERMES_TIMEOUT_MS = 20_000;
export const HERMES_HEALTH_TIMEOUT_MS = 10_000;
/** The same 4.5 MiB as THRESHOLDS.maxImageBytes (index.ts imports this file, so the value is repeated; a test pins them equal). */
export const HERMES_IMAGE_LIMIT = 4.5 * 1024 * 1024;
/** The formats the intake keeps besides HEIC (media.ts sniff); HEIC is converted by the media job first. */
export const HERMES_IMAGE_MIMES: readonly string[] = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
export const HERMES_PATHS: Readonly<Record<VisionMethod, string>> = Object.freeze({classify: '/v1/vision/classify', count_board: '/v1/vision/count-board', fish_id: '/v1/vision/fish-id'});
/** The field a response must carry to count as an answer (an empty `{}` is a fault, not an "unknown" photo). */
export const REQUIRED_FIELD: Readonly<Record<VisionMethod, string>> = Object.freeze({classify: 'kind', count_board: 'lines', fish_id: 'candidates'});
const MODEL = /^[\w.:@/+-]{1,100}$/;
const EXT: Record<string, string> = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif', 'image/webp': 'webp'};

type Fetcher = (url: string, init: RequestInit) => Promise<Response>;
export interface HermesVisionDeps {
  fetcher?: Fetcher;                       // default: fetch
  now?: () => number;                      // epoch ms; default Date.now
  regionTargets?: (region: string) => readonly string[] | null;
}

/** The `meta` field: what the image is and, for fish ID, the only species keys Hermes may answer with. */
export interface HermesMeta {media_id: string; region: string | null; species_keys?: string[]; orientation?: number}

/**
 * HERMES_VISION_URL as a base for the paths: https only, no credentials, query
 * or fragment, trailing slashes dropped (a path prefix is kept); null otherwise.
 */
export function hermesBase(env: Pick<Env, 'HERMES_VISION_URL'>): string | null {
  const raw = (env.HERMES_VISION_URL ?? '').trim();
  if (!raw || raw.includes('?') || raw.includes('#')) return null;
  let url: URL;
  try { url = new URL(raw); } catch { return null; }
  if (url.protocol !== 'https:' || url.username || url.password) return null;
  return (url.origin + url.pathname).replace(/\/+$/, '');
}

/** Whether both secrets are set and the URL is usable (the admin Health "configured" line). */
export const hermesConfigured = (env: Pick<Env, 'HERMES_VISION_URL' | 'HERMES_VISION_TOKEN'>): boolean => Boolean(hermesBase(env) && env.HERMES_VISION_TOKEN?.trim());

/** The multipart body: the image as a file part named `image`, the meta as a JSON text field named `meta`. */
export function hermesForm(mime: string, buffer: ArrayBuffer, meta: HermesMeta): FormData {
  const form = new FormData();
  form.append('image', new Blob([buffer], {type: mime}), `image.${EXT[mime] ?? 'bin'}`);
  form.append('meta', JSON.stringify(meta));
  return form;
}

/** The model a response names in X-Vision-Model, or 'unknown' when it is missing or not a plain id. */
export function visionModel(response: Response): string {
  const v = (response.headers.get('x-vision-model') ?? '').trim();
  return MODEL.test(v) ? v : 'unknown';
}

export function createHermesVision(deps: HermesVisionDeps = {}): VisionProvider {
  const fetcher: Fetcher = deps.fetcher ?? ((url, init) => fetch(url, init));
  const now = deps.now ?? Date.now;
  const regionTargets = deps.regionTargets ?? defaultRegionTargets;

  function config(env: Env): {base: string; token: string} {
    const base = hermesBase(env), token = env.HERMES_VISION_TOKEN?.trim();
    if (!base) throw new ProviderNotConfigured('hermes', 'HERMES_VISION_URL is not an https URL');
    if (!token) throw new ProviderNotConfigured('hermes', 'no HERMES_VISION_TOKEN');
    return {base, token};
  }

  /** One method call: checks, the multipart POST, the JSON body and its required field. */
  async function call(env: Env, method: VisionMethod, image: ImageInput, meta: Omit<HermesMeta, 'media_id' | 'orientation'>): Promise<{input: unknown; meta: ResultMeta}> {
    const {base, token} = config(env);
    if (!HERMES_IMAGE_MIMES.includes(image.mime)) throw new UnsupportedImage(image.mime);
    const buffer = await image.bytes();
    if (buffer.byteLength > HERMES_IMAGE_LIMIT) throw new MediaTooLarge(buffer.byteLength);
    const orientation = image.orientation && image.orientation > 1 && image.orientation <= 8 ? image.orientation : undefined;
    const body = hermesForm(image.mime, buffer, {media_id: image.media_id, ...meta, ...(orientation ? {orientation} : {})});
    const started = now();
    let outcome = 'error', status = 0;
    try {
      const response = await fetcher(base + HERMES_PATHS[method], {method: 'POST', signal: AbortSignal.timeout(HERMES_TIMEOUT_MS),
        headers: {authorization: `Bearer ${token}`, accept: 'application/json'}, body});
      status = response.status;
      if (!response.ok) throw Error(`hermes HTTP ${response.status}`);
      let data: unknown;
      try { data = await response.json(); } catch { outcome = 'invalid'; throw Error('hermes returned no JSON'); }
      if (!data || typeof data !== 'object' || Array.isArray(data) || !(REQUIRED_FIELD[method] in data)) { outcome = 'invalid'; throw Error(`hermes response has no ${REQUIRED_FIELD[method]}`); }
      outcome = 'ok';
      return {input: data, meta: {provider: 'hermes', model: visionModel(response), ms: now() - started}};
    } catch (error) {
      if ((error as Error)?.name === 'TimeoutError') outcome = 'timeout';
      throw error;
    } finally {
      advisorLog(outcome === 'ok' ? 'info' : 'warn', 'advisor_vision_call', {provider: 'hermes', method, outcome, status, ms: now() - started});
    }
  }

  return {
    name: 'hermes',
    async classify(image, env) {
      const {input, meta} = await call(env, 'classify', image, {region: null});
      return parseClassification(input, meta);
    },
    async readCountBoard(image, env) {
      const {input, meta} = await call(env, 'count_board', image, {region: null});
      return parseCountBoard(input, meta);
    },
    async identifyFish(image, env, region) {
      const keys = speciesForTargets(regionTargets(region)).map(s => s.key);
      const {input, meta} = await call(env, 'fish_id', image, {region, species_keys: keys});
      return parseFishId(input, new Set(keys), meta);
    },
    async health(env) {
      let cfg: {base: string; token: string};
      try { cfg = config(env); } catch { return {ok: false, detail: 'not-configured'}; }
      try {
        const response = await fetcher(cfg.base + '/v1/health', {method: 'GET', signal: AbortSignal.timeout(HERMES_HEALTH_TIMEOUT_MS),
          headers: {authorization: `Bearer ${cfg.token}`, accept: 'application/json'}});
        if (!response.ok) return {ok: false, detail: `HTTP ${response.status}`};
        const data = await response.json<{ok?: unknown; models?: unknown}>().catch(() => null);
        if (!data || data.ok !== true) return {ok: false, detail: 'health did not report ok'};
        const models = data.models && typeof data.models === 'object' && !Array.isArray(data.models)
          ? Object.entries(data.models as Record<string, unknown>).map(([k, v]) => `${k}=${String(v)}`).join(', ').slice(0, 200) : '';
        return {ok: true, detail: models || 'ok'};
      } catch (error) {
        return {ok: false, detail: (error as Error)?.name === 'TimeoutError' ? 'timeout' : 'unreachable'};
      }
    },
  };
}
