// Client telemetry (P4-11): a small, cookie-less batch of funnel events and
// client errors from web/telemetry.ts, validated strictly and written to
// Workers Analytics Engine (server/analytics.ts) as two more kinds:
//
//   client_event  blob2 event (a repeated event and region in one batch is written once), blob3 region id ('' none, 'other' unknown), blob4 page build,
//                 blob5 visit source (txt|ig|fb|qr, the page URL's `s`; absent when none; TA-W1)
//                 double1 count (always 1)
//   client_error  blob2 kind (error|rejection), blob3 message (scrubbed, 96 chars),
//                 blob4 source file basename, blob5 page build, blob6 request-id hash
//                 (16 hex of sha256, the same form as `request` points)
//                 double1 line, double2 column
//
// Nothing identifies a person: the payload has no user, session or device id,
// the Worker never reads the IP for it (only the rate limiter keys on it, as on
// every public route), URLs lose their query and fragment, and any field not
// listed here is rejected rather than ignored.
import {writePoint} from './analytics.ts';
import {regionById} from './config.ts';
import {hash} from './http.ts';
import {ClientError} from './errors.ts';
import type {Env} from './env.ts';

export const FUNNEL_EVENTS = ['port_selected', 'map_viewed', 'forecast_viewed', 'spot_saved', 'offline_saved', 'install',
  // TA-W1: the Text Advisor's public pages (08 § Telemetry).
  'advisor_port_view', 'advisor_species_view', 'advisor_boat_view', 'advisor_cta'] as const;
export type FunnelEvent = typeof FUNNEL_EVENTS[number];
/** TA-W1: visit sources a funnel event may carry (the page URL's `s`: advisor texts, Instagram, Facebook, the QR code). */
export const SOURCES = ['txt', 'ig', 'fb', 'qr'] as const;
export const ERROR_KINDS = ['error', 'rejection'] as const;
/** Largest accepted body, in bytes; a full client batch is well under half of it. */
export const MAX_BODY = 4096;
/** Events per batch: the client's BATCH_SIZE (web/telemetry.ts). */
export const MAX_EVENTS = 10;
export const MESSAGE_MAX = 96;

export type ClientEvent =
  | {type: 'funnel'; name: FunnelEvent; region: string; source: string}
  | {type: 'error'; kind: typeof ERROR_KINDS[number]; message: string; source: string; line: number; column: number; request_id: string};
export interface Batch {build: string; events: ClientEvent[]}

const BUILD = /^(?:[0-9a-f]{10}|dev)$/;
const REQUEST_ID = /^[A-Za-z0-9_-]{8,64}$/;
const isObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const invalid = (): never => { throw new ClientError('invalid telemetry'); };

function only(value: Record<string, unknown>, allowed: readonly string[]): void {
  for (const key of Object.keys(value)) if (!allowed.includes(key)) invalid();
}
function text(value: unknown, max: number, optional = true): string {
  if (value === undefined || value === null) return optional ? '' : invalid();
  if (typeof value !== 'string' || value.length > max) return invalid();
  return value;
}
function position(value: unknown): number {
  if (value === undefined || value === null) return 0;
  if (!Number.isInteger(value) || (value as number) < 0 || (value as number) > 10_000_000) return invalid();
  return value as number;
}

/** Remove what could identify a person, a place or a query: URL and path queries and fragments, emails, coordinates, long numbers. */
// A path-like token (absolute URL, /relative/path or dir/file) and the query or
// fragment after it, which is dropped. Kept in step with web/telemetry.ts.
export const PATH_QUERY = /((?:[a-z][a-z0-9+.-]*:)?[\w.~%-]*\/[^\s?#'"()<>]*)[?#]\S*/gi;
// Decimal degrees and similar (35.3658, -120.851): a position is never sent.
export const COORDINATE = /(?<![\w.])-?\d{1,3}\.\d{3,}(?![\d.])/g;
export function scrub(message: string): string {
  return message
    .replace(PATH_QUERY, '$1')
    .replace(/[^\s@'"()<>]+@[^\s@'"()<>]+\.[a-z]{2,}/gi, '[email]')
    .replace(COORDINATE, '[coord]')
    .replace(/\d{6,}/g, '#')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, MESSAGE_MAX);
}

/** The file name of a script URL or path, without directories, query or fragment; '' if it is not a plain name. */
export function basename(source: string): string {
  const name = source.split(/[?#]/)[0]!.split('/').pop() || '';
  return /^[\w.-]{1,80}$/.test(name) ? name : '';
}

/** A validated batch; throws ClientError on any unknown field, type or value. */
export function parseBatch(body: unknown): Batch {
  if (!isObject(body)) return invalid();
  only(body, ['build', 'events']);
  const build = text(body.build, 16, false);
  if (!BUILD.test(build)) invalid();
  const list = body.events;
  if (!Array.isArray(list) || list.length < 1 || list.length > MAX_EVENTS) return invalid();
  const events = list.map((event): ClientEvent => {
    if (!isObject(event)) return invalid();
    if (event.type === 'funnel') {
      only(event, ['type', 'name', 'region', 'source']);
      if (!(FUNNEL_EVENTS as readonly unknown[]).includes(event.name)) invalid();
      const region = text(event.region, 64), source = text(event.source, 8);
      if (source && !(SOURCES as readonly string[]).includes(source)) invalid();
      return {type: 'funnel', name: event.name as FunnelEvent, region: region === '' ? '' : regionById(region) ? region : 'other', source};
    }
    if (event.type === 'error') {
      only(event, ['type', 'kind', 'message', 'source', 'line', 'column', 'request_id']);
      if (!(ERROR_KINDS as readonly unknown[]).includes(event.kind)) invalid();
      const requestId = text(event.request_id, 64);
      if (requestId && !REQUEST_ID.test(requestId)) invalid();
      return {type: 'error', kind: event.kind as typeof ERROR_KINDS[number], message: scrub(text(event.message, 512)),
        source: basename(text(event.source, 512)), line: position(event.line), column: position(event.column), request_id: requestId};
    }
    return invalid();
  });
  // A funnel step counts once per page and region; drop repeats within a batch.
  const seen = new Set<string>();
  return {build, events: events.filter(event => {
    if (event.type !== 'funnel') return true;
    const key = event.name + '\0' + event.region + '\0' + event.source;
    if (seen.has(key)) return false;
    seen.add(key); return true;
  })};
}

/** Write the batch to Analytics Engine; a no-op without the binding. */
export async function recordBatch(env: Pick<Env, 'ANALYTICS'> | undefined, batch: Batch): Promise<number> {
  if (!env?.ANALYTICS) return 0;
  for (const event of batch.events) {
    // TA-W1: blob5 is the visit source, written only when the event has one.
    if (event.type === 'funnel') writePoint(env, 'client_event', {blobs: [event.name, event.region, batch.build, ...(event.source ? [event.source] : [])], doubles: [1]});
    else writePoint(env, 'client_error', {blobs: [event.kind, event.message, event.source, batch.build, event.request_id ? (await hash(event.request_id)).slice(0, 16) : ''],
      doubles: [event.line, event.column]});
  }
  return batch.events.length;
}
