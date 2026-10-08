// Coast data client for v2 (FE-74, design § 3A.2).
//
// Loads the local SLO report, ocean and history snapshots through the
// existing coastal bridge (packages/coast coastFetch: /api/coast/report,
// /api/coast/ocean, /api/coast/history). No new endpoint.
//
// Rules:
// - Admission: a snapshot is shown only while resolveReportBinding binds the
//   selected place (Morro Bay and Cambria today). The caller builds the
//   context with web/overview-context.ts overviewReportContext; outside a
//   binding every signal is null and nothing is requested.
// - Requests belong to a place. A change of binding aborts them, and a late
//   response for a superseded place is discarded. Hour, profile and target
//   changes within one place keep the snapshots and the requests.
// - Original clocks are kept: the payload is never rewritten; generatedAt is
//   the snapshot's own clock, receivedAt and savedAt (X-SC-Offline, a saved
//   offline copy) are reported beside it.
// - Expiry hides, never refreshes. Past SNAPSHOT_LIMIT_MS after its
//   generatedAt a snapshot becomes null with status 'expired' and no request
//   follows. Only refresh() or a new place requests again.
//
// Snapshots are county-wide, so a loaded snapshot is cached across places and
// admitted again when the user returns to a bound place, until it expires.
import {batch, computed, signal, type ReadonlySignal} from '@preact/signals';
import {coastFetch} from '../packages/coast/src/transport.ts';
import {resolveReportBinding, type CoastReportContext, type ReportBinding} from '../packages/coast/src/state/report-binding.ts';
import type {Report} from '../packages/coast/src/types.ts';
import type {OceanData} from '../packages/coast/src/ocean-types.ts';
import type {HistoryBundle} from '../packages/coast/src/history-types.ts';

export type CoastProducts = {report: Report; ocean: OceanData; history: HistoryBundle};
export type CoastProduct = keyof CoastProducts;
export const COAST_PRODUCTS: readonly CoastProduct[] = ['report', 'ocean', 'history'];

const HOUR = 3_600_000;
/**
 * How long after its own generatedAt each snapshot may be shown. The report
 * limit matches packages/coast's 3 h fetch-age rule for nearshore and beach
 * readings, the ocean limit its 6 h current-field rule; history holds
 * measured records, so it keeps a longer limit.
 */
export const SNAPSHOT_LIMIT_MS: Readonly<Record<CoastProduct, number>> = {report: 3 * HOUR, ocean: 6 * HOUR, history: 36 * HOUR};
/** A generatedAt further ahead of the device clock than this is refused. */
export const CLOCK_SKEW_MS = 5 * 60_000;
export const REQUEST_TIMEOUT_MS = 20_000;
const MAX_TIMER = 2 ** 31 - 1;

export type CoastSnapshot<P extends CoastProduct = CoastProduct> = {
  product: P;
  /** The payload exactly as the bridge returned it. */
  data: CoastProducts[P];
  /** The snapshot's own assembly clock. */
  generatedAt: string;
  /** When this client received it. */
  receivedAt: string;
  /** When a saved offline copy was saved (X-SC-Offline); null for a network read. */
  savedAt: string | null;
  /** generatedAt plus the product's limit; the snapshot is hidden from then on. */
  expiresAt: string;
};

/**
 * What the shell and brief render for a product.
 * - unbound: the selected place has no local report binding (signal null).
 * - idle: bound, not requested yet. loading: a request is in flight.
 * - ready: a snapshot is admitted.
 * - error: the bridge failed or timed out. invalid: the response failed its
 *   identity or clock checks. Both keep an earlier unexpired snapshot.
 * - expired: the snapshot passed its limit and is hidden (signal null).
 */
export type CoastStatus = 'unbound' | 'idle' | 'loading' | 'ready' | 'error' | 'invalid' | 'expired';
type Statuses = Readonly<Record<CoastProduct, CoastStatus>>;
type Cache = {readonly [P in CoastProduct]: CoastSnapshot<P> | null};

export type CoastData = {
  coastReport: ReadonlySignal<CoastSnapshot<'report'> | null>;
  coastOcean: ReadonlySignal<CoastSnapshot<'ocean'> | null>;
  coastHistory: ReadonlySignal<CoastSnapshot<'history'> | null>;
  coastStatus: ReadonlySignal<Statuses>;
  coastBinding: ReadonlySignal<ReportBinding | null>;
  /** Select a place (null: none). Returns its binding; requests only when the binding changes. */
  setPlace(context: CoastReportContext | null): ReportBinding | null;
  /** Ask for products for the current and later bound places. Idempotent: fetches only an idle product. */
  load(...products: CoastProduct[]): Promise<void>;
  /** Request again (an explicit retry); defaults to every product asked for. */
  refresh(...products: CoastProduct[]): Promise<void>;
  destroy(): void;
};

const isObject = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value);
const arrays = (body: Record<string, unknown>, keys: readonly string[]): boolean => keys.every(key => Array.isArray(body[key]));

/** The bridge's identity checks (server/coast-data.ts) plus the shape packages/coast reads. */
export function validSnapshot<P extends CoastProduct>(product: P, body: unknown): body is CoastProducts[P] {
  if (!isObject(body) || body.schemaVersion !== 1 || body.countyId !== 'slo' || typeof body.generatedAt !== 'string' || !Number.isFinite(Date.parse(body.generatedAt))) return false;
  if (product === 'report') return arrays(body, ['forecasts', 'observations', 'tides', 'tideEvents', 'alerts', 'sources', 'catches']) && isObject(body.visibility);
  if (product === 'ocean') return arrays(body, ['currents', 'sources']);
  return arrays(body, ['stations']) && typeof body.recentWindowDays === 'number' && Number.isFinite(body.recentWindowDays) && body.recentWindowDays > 0;
}

/** A snapshot of `body`, or why it cannot be shown at `now` (epoch ms). */
export function admitSnapshot<P extends CoastProduct>(product: P, body: unknown, savedAt: string | null, now: number): CoastSnapshot<P> | 'invalid' | 'expired' {
  if (!validSnapshot(product, body)) return 'invalid';
  const generated = Date.parse(body.generatedAt);
  if (generated > now + CLOCK_SKEW_MS) return 'invalid';
  const expires = generated + SNAPSHOT_LIMIT_MS[product];
  if (expires <= now) return 'expired';
  const saved = savedAt !== null && Number.isFinite(Date.parse(savedAt)) ? savedAt : null;
  return {product, data: body, generatedAt: body.generatedAt, receivedAt: new Date(now).toISOString(), savedAt: saved, expiresAt: new Date(expires).toISOString()};
}

const allStatus = (status: CoastStatus): Statuses => ({report: status, ocean: status, history: status});
const placeKey = (context: CoastReportContext, binding: ReportBinding): string => JSON.stringify([context.regionId, binding.localAreaId]);

export function createCoastData(): CoastData {
  const cache = signal<Cache>({report: null, ocean: null, history: null});
  const status = signal<Statuses>(allStatus('unbound'));
  const binding = signal<ReportBinding | null>(null);
  const wanted = new Set<CoastProduct>();
  const requests = new Map<CoastProduct, {controller: AbortController; done: Promise<void>}>();
  const timers = new Map<CoastProduct, ReturnType<typeof setTimeout>>();
  let place: string | null = null;
  let alive = true;

  const setStatus = (product: CoastProduct, next: CoastStatus): void => { status.value = {...status.value, [product]: next}; };
  const setCache = <P extends CoastProduct>(product: P, snapshot: CoastSnapshot<P> | null): void => { cache.value = {...cache.value, [product]: snapshot}; };
  const admitted = <P extends CoastProduct>(product: P) => computed<CoastSnapshot<P> | null>(() => binding.value ? cache.value[product] as CoastSnapshot<P> | null : null);

  function abortAll(): void {
    for (const {controller} of requests.values()) controller.abort();
    requests.clear();
  }

  function expire(product: CoastProduct): void {
    clearTimeout(timers.get(product));
    timers.delete(product);
    const snapshot = cache.value[product];
    if (!alive || !snapshot) return;
    const remaining = Date.parse(snapshot.expiresAt) - Date.now();
    if (remaining > 0) { timers.set(product, setTimeout(() => expire(product), Math.min(remaining, MAX_TIMER))); return; }
    batch(() => { setCache(product, null); if (binding.value && status.value[product] !== 'loading') setStatus(product, 'expired'); });
  }

  function request(product: CoastProduct): Promise<void> {
    requests.get(product)?.controller.abort();
    const entry = {controller: new AbortController(), done: Promise.resolve()};
    requests.set(product, entry);
    setStatus(product, 'loading');
    entry.done = (async () => {
      let outcome: CoastSnapshot | 'invalid' | 'expired' | 'error';
      try {
        const signal = AbortSignal.any([entry.controller.signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]);
        const response = await coastFetch('/api/' + product, {signal});
        outcome = response.ok ? admitSnapshot(product, await response.json(), response.headers.get('X-SC-Offline'), Date.now()) : 'error';
      } catch { outcome = 'error'; }
      // A response for a superseded place (or a destroyed client) is discarded.
      if (!alive || requests.get(product) !== entry) return;
      requests.delete(product);
      batch(() => {
        if (typeof outcome === 'object') { setCache(product, outcome); setStatus(product, 'ready'); }
        else {
          if (outcome === 'expired') setCache(product, null);
          setStatus(product, outcome);
        }
      });
      expire(product);
    })();
    return entry.done;
  }

  function setPlace(context: CoastReportContext | null): ReportBinding | null {
    if (!alive) return null;
    const next = context ? resolveReportBinding(context) : null;
    const key = context && next ? placeKey(context, next) : null;
    if (key === place) return binding.value;
    place = key;
    abortAll();
    batch(() => {
      binding.value = next;
      status.value = next ? {report: cache.value.report ? 'ready' : 'idle', ocean: cache.value.ocean ? 'ready' : 'idle', history: cache.value.history ? 'ready' : 'idle'} : allStatus('unbound');
    });
    if (next) for (const product of wanted) if (!cache.value[product]) void request(product);
    return next;
  }

  async function load(...products: CoastProduct[]): Promise<void> {
    const pending: Promise<void>[] = [];
    for (const product of products) {
      wanted.add(product);
      if (!alive || !binding.value) continue;
      const inFlight = requests.get(product);
      if (inFlight) pending.push(inFlight.done);
      else if (status.value[product] === 'idle') pending.push(request(product));
    }
    await Promise.all(pending);
  }

  async function refresh(...products: CoastProduct[]): Promise<void> {
    if (!alive || !binding.value) return;
    await Promise.all((products.length ? products : [...wanted]).map(product => { wanted.add(product); return request(product); }));
  }

  function destroy(): void {
    alive = false;
    abortAll();
    for (const timer of timers.values()) clearTimeout(timer);
    timers.clear();
    batch(() => { binding.value = null; status.value = allStatus('unbound'); cache.value = {report: null, ocean: null, history: null}; });
  }

  return {
    coastReport: admitted('report'), coastOcean: admitted('ocean'), coastHistory: admitted('history'),
    coastStatus: status, coastBinding: binding, setPlace, load, refresh, destroy,
  };
}

/** The v2 shell's client. Tests and secondary mounts create their own. */
export const coastData = createCoastData();
export const {coastReport, coastOcean, coastHistory, coastStatus, coastBinding} = coastData;
