// Cookie-less client telemetry (P4-11): a fixed set of funnel events and
// uncaught errors, batched and sent with navigator.sendBeacon to
// /api/telemetry (server/routes/telemetry.ts), which writes them to Workers
// Analytics Engine when it is bound. See docs/engineering/telemetry.md.
//
// Sends nothing at all when the browser signals Do Not Track or Global Privacy
// Control: no listeners, no queue, no requests. Otherwise nothing that
// identifies a person is kept or sent: no user, session or device id, no
// cookies or storage, no URLs with queries (a script's file name only), and
// error messages are cut short and scrubbed here and again on the server.
//
// Erasable TypeScript only, so the Node tests import it by type stripping.
import {region as currentRegion} from './state.ts';

export const ENDPOINT = '/api/telemetry';
export const FUNNEL = ['port_selected', 'map_viewed', 'forecast_viewed', 'spot_saved', 'offline_saved', 'install'] as const;
export type FunnelEvent = typeof FUNNEL[number];
export type ErrorKind = 'error' | 'rejection';

export type Event =
  | {type: 'funnel'; name: FunnelEvent; region?: string}
  | {type: 'error'; kind: ErrorKind; message: string; source?: string; line?: number; column?: number; request_id?: string};

/** Per page load: at most this many distinct errors and this many events in all. */
export const MAX_ERRORS = 5;
export const MAX_EVENTS = 30;
/** Flush when this many events wait (also the most per beacon; the server's MAX_EVENTS), or FLUSH_MS after the first one. */
export const BATCH_SIZE = 10;
export const FLUSH_MS = 10_000;
/** Keep each beacon well under the server's 4 KiB cap. */
export const MAX_BEACON_BYTES = 3500;
const MESSAGE_CHARS = 200;
const REQUEST_ID = /^[A-Za-z0-9_-]{8,64}$/;
const BUILD = /^(?:[0-9a-f]{10}|dev)$/;

interface PrivacySignals {doNotTrack?: string | null; globalPrivacyControl?: boolean}

/** True when the browser asks not to be tracked (DNT "1"/"yes") or sends Global Privacy Control. */
export function optedOut(nav: PrivacySignals | undefined, win?: {doNotTrack?: string | null}): boolean {
  const dnt = nav?.doNotTrack ?? win?.doNotTrack;
  return nav?.globalPrivacyControl === true || dnt === '1' || dnt === 'yes';
}

/** The file name of a script URL, without directories, query or fragment. */
export function sourceName(url: unknown): string {
  if (typeof url !== 'string') return '';
  const name = url.split(/[?#]/)[0]!.split('/').pop() || '';
  return /^[\w.-]{1,80}$/.test(name) ? name : '';
}

// Same patterns as server/telemetry.ts: a path-like token's query or fragment,
// and coordinate-shaped numbers.
const PATH_QUERY = /((?:[a-z][a-z0-9+.-]*:)?[\w.~%-]*\/[^\s?#'"()<>]*)[?#]\S*/gi;
const COORDINATE = /(?<![\w.])-?\d{1,3}\.\d{3,}(?![\d.])/g;

/** A message without path or URL queries and fragments or coordinates, cut to MESSAGE_CHARS. */
export function cleanMessage(message: unknown): string {
  return String(message ?? '').replace(PATH_QUERY, '$1').replace(COORDINATE, '[coord]').replace(/\s+/g, ' ').trim().slice(0, MESSAGE_CHARS);
}

/** The response's X-Request-Id, only for a response from `origin` (the Worker's own). */
export function requestIdFrom(response: {url: string; headers: {get(name: string): string | null}}, origin: string): string | null {
  try { return response.url && new URL(response.url).origin === origin ? response.headers.get('X-Request-Id') : null; }
  catch { return null; }
}

/** Error details from an Error-like value: message, and the first stack frame's file, line and column. */
export function describe(value: unknown): {message: string; source: string; line: number; column: number} {
  const error = value as {message?: unknown; stack?: unknown} | null | undefined;
  const message = cleanMessage(error && typeof error === 'object' && 'message' in error ? error.message : value);
  const frame = typeof error?.stack === 'string' ? /((?:https?|file):\/\/[^\s)]+?):(\d+):(\d+)/.exec(error.stack) : null;
  return {message, source: sourceName(frame?.[1]), line: frame ? Number(frame[2]) : 0, column: frame ? Number(frame[3]) : 0};
}

export interface TelemetryOptions {
  /** Sends one serialized batch; returns false when the browser refused it. */
  send: (body: string) => boolean;
  build: string;
  /** The region shown now ('' when none). */
  region?: () => string;
  schedule?: (run: () => void, ms: number) => unknown;
}

export interface Telemetry {
  track(name: FunnelEvent, options?: {region?: string; flush?: boolean}): void;
  error(kind: ErrorKind, value: unknown, where?: {source?: unknown; line?: unknown; column?: unknown}): void;
  noteRequestId(id: string | null | undefined): void;
  flush(): void;
  readonly pending: number;
}

/** The batching core, free of browser globals so it can be tested directly. */
export function createTelemetry({send, build, region = () => '', schedule = (run, ms) => setTimeout(run, ms)}: TelemetryOptions): Telemetry {
  const queue: Event[] = [], seen = new Set<string>();
  const safeBuild = BUILD.test(build) ? build : 'dev';
  let total = 0, errors = 0, timer = false, requestId = '';

  function flush(): void {
    timer = false;
    while (queue.length) {
      // Take as many events as fit in one beacon (at least one).
      let count = 0, body = '';
      for (let n = 1; n <= Math.min(queue.length, BATCH_SIZE); n++) {
        const next = JSON.stringify({build: safeBuild, events: queue.slice(0, n)});
        if (n > 1 && next.length > MAX_BEACON_BYTES) break;
        count = n; body = next;
      }
      queue.splice(0, count);
      try { send(body); } catch { /* telemetry never breaks the page */ }
    }
  }
  function push(event: Event, flushNow = false): void {
    if (total >= MAX_EVENTS) return;
    total++; queue.push(event);
    if (flushNow || queue.length >= BATCH_SIZE) flush();
    else if (!timer) { timer = true; schedule(() => { if (timer) flush(); }, FLUSH_MS); }
  }
  return {
    track(name, options = {}) {
      if (!(FUNNEL as readonly string[]).includes(name)) return;
      const where = options.region ?? region() ?? '';
      // A step counts once per page load and region, however often it is shown.
      const key = `f:${name}:${where}`;
      if (seen.has(key)) return;
      seen.add(key);
      push({type: 'funnel', name, ...(where ? {region: where} : {})}, options.flush);
    },
    error(kind, value, where = {}) {
      if (errors >= MAX_ERRORS) return;
      const detail = describe(value);
      const source = sourceName(where.source) || detail.source;
      const line = Number.isInteger(where.line) ? where.line as number : detail.line;
      const column = Number.isInteger(where.column) ? where.column as number : detail.column;
      if (!detail.message && !source) return;
      // Cross-origin scripts report only "Script error."; nothing useful to send.
      if (/^script error\.?$/i.test(detail.message) && !source) return;
      const key = `e:${kind}:${detail.message}:${source}:${line}`;
      if (seen.has(key)) return;
      seen.add(key); errors++;
      push({type: 'error', kind, message: detail.message, ...(source ? {source} : {}), ...(line > 0 ? {line} : {}), ...(column > 0 ? {column} : {}),
        ...(requestId ? {request_id: requestId} : {})});
    },
    noteRequestId(id) { if (id && REQUEST_ID.test(id)) requestId = id; },
    flush,
    get pending() { return queue.length; },
  };
}

let active: Telemetry | null = null;

/** Record a funnel step (no-op until initTelemetry, or when the visitor opted out). */
export function track(name: FunnelEvent, options?: {region?: string; flush?: boolean}): void {
  active?.track(name, options);
}

/**
 * Start telemetry for this page: error listeners, flush on page hide, and the
 * last X-Request-Id seen on a same-origin fetch. Returns null when the
 * browser opted out or cannot send beacons.
 */
export function initTelemetry(): Telemetry | null {
  if (active || typeof window === 'undefined' || typeof navigator === 'undefined') return active;
  if (optedOut(navigator as PrivacySignals, window as {doNotTrack?: string | null})) return null;
  if (typeof navigator.sendBeacon !== 'function') return null;
  const meta = document.querySelector('meta[name="skippercast-build"]')?.getAttribute('content') || 'dev';
  const telemetry = createTelemetry({
    send: body => navigator.sendBeacon(ENDPOINT, body),
    build: meta,
    region: () => currentRegion.value || new URL(location.href).searchParams.get('region') || '',
  });
  active = telemetry;
  addEventListener('error', event => {
    // Resource load failures reach window only in the capture phase; this listener sees script errors.
    if (!(event instanceof ErrorEvent)) return;
    telemetry.error('error', event.error ?? event.message, {source: event.filename, line: event.lineno, column: event.colno});
  });
  addEventListener('unhandledrejection', event => telemetry.error('rejection', event.reason));
  addEventListener('pagehide', () => telemetry.flush());
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') telemetry.flush(); });
  // Remember the last request id the Worker (same origin only) returned, so an error can be matched to its logs.
  const original = window.fetch;
  if (typeof original === 'function') {
    window.fetch = function (...args: Parameters<typeof fetch>) {
      return original.apply(window, args).then(response => {
        try { telemetry.noteRequestId(requestIdFrom(response, location.origin)); } catch { /* opaque response */ }
        return response;
      });
    } as typeof fetch;
  }
  return telemetry;
}
