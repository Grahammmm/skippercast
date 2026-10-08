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
// - Readings are withdrawn by packages/coast's own per-reading rules (for
//   example the 3 h fetch age of nearshore and beach readings, the 6 h
//   current-field rule), as v1 does. The whole-snapshot limit here is only a
//   backstop for a snapshot nothing has replaced.
// - Expiry hides, never refreshes. Past its limit a snapshot becomes null
//   with status 'expired' and no request follows. Only refresh() or a new
//   place requests again. Besides the expiry timer, which stalls in
//   throttled or suspended tabs, a clock signal ticks on focus, pageshow and
//   visibilitychange and on every setPlace and load, and the snapshot and
//   status signals read it, so a returning tab withholds an expired snapshot
//   at once.
// - A newer snapshot is never replaced by an older one (a saved offline copy
//   arriving after a fresher network read), and an expired reply never hides
//   an unexpired snapshot.
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
 * Backstop: how long after its own generatedAt a snapshot may be shown at all
 * (owner decision, PR #425). Basis: report 3 h, packages/coast's fetch-age
 * rule for nearshore and beach readings (presentation.ts freshNearshore);
 * ocean 6 h, its current-field rule (state/current-layer.ts); history 36 h,
 * measured records that stay valid longer.
 */
export const SNAPSHOT_LIMIT_MS: Readonly<Record<CoastProduct, number>> = {report: 3 * HOUR, ocean: 6 * HOUR, history: 36 * HOUR};
/**
 * The report limit for a saved offline copy (X-SC-Offline, the offline packs
 * of PR #405): a day, so a pack saved before a trip still opens; its readings
 * still pass the per-reading rules.
 */
export const OFFLINE_REPORT_LIMIT_MS = 24 * HOUR;
export const snapshotLimit = (product: CoastProduct, savedAt: string | null): number =>
  product === 'report' && savedAt !== null ? OFFLINE_REPORT_LIMIT_MS : SNAPSHOT_LIMIT_MS[product];
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
  /** generatedAt plus snapshotLimit(); the snapshot is hidden from then on. */
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
/** Events that tick the clock; the default is `window` when there is one. */
export type CoastDataOptions = {clockEvents?: EventTarget | null};
const CLOCK_EVENTS = ['focus', 'pageshow', 'visibilitychange'] as const;

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
  const saved = savedAt !== null && Number.isFinite(Date.parse(savedAt)) ? savedAt : null;
  const expires = generated + snapshotLimit(product, saved);
  if (expires <= now) return 'expired';
  return {product, data: body, generatedAt: body.generatedAt, receivedAt: new Date(now).toISOString(), savedAt: saved, expiresAt: new Date(expires).toISOString()};
}

const allStatus = (status: CoastStatus): Statuses => ({report: status, ocean: status, history: status});
const live = (snapshot: CoastSnapshot | null, now: number): snapshot is CoastSnapshot => snapshot !== null && Date.parse(snapshot.expiresAt) > now;
const placeKey = (context: CoastReportContext, binding: ReportBinding): string => JSON.stringify([context.regionId, binding.localAreaId]);

export function createCoastData(options: CoastDataOptions = {}): CoastData {
  const cache = signal<Cache>({report: null, ocean: null, history: null});
  const status = signal<Statuses>(allStatus('unbound'));
  const binding = signal<ReportBinding | null>(null);
  const wanted = new Set<CoastProduct>();
  const requests = new Map<CoastProduct, {controller: AbortController; done: Promise<void>}>();
  const timers = new Map<CoastProduct, ReturnType<typeof setTimeout>>();
  let place: string | null = null;
  let alive = true;
  // The time the signals judge expiry by; computeds cache, so they must read a signal, not Date.now().
  const clock = signal(Date.now());
  const tick = (): void => { clock.value = Date.now(); };
  const events = options.clockEvents !== undefined ? options.clockEvents : typeof window === 'undefined' ? null : window;
  for (const type of CLOCK_EVENTS) events?.addEventListener(type, tick);

  const setStatus = (product: CoastProduct, next: CoastStatus): void => { status.value = {...status.value, [product]: next}; };
  const setCache = <P extends CoastProduct>(product: P, snapshot: CoastSnapshot<P> | null): void => { cache.value = {...cache.value, [product]: snapshot}; };
  // Each read checks the clock too: a stalled expiry timer must not show an expired snapshot.
  const admitted = <P extends CoastProduct>(product: P) => computed<CoastSnapshot<P> | null>(() => {
    const snapshot = cache.value[product] as CoastSnapshot<P> | null;
    return binding.value && live(snapshot, clock.value) ? snapshot : null;
  });
  const shownStatus = computed<Statuses>(() => {
    const shown = {...status.value};
    for (const product of COAST_PRODUCTS) if (shown[product] === 'ready' && !live(cache.value[product], clock.value)) shown[product] = 'expired';
    return shown;
  });

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
    batch(() => { tick(); setCache(product, null); if (binding.value && status.value[product] !== 'loading') setStatus(product, 'expired'); });
  }

  /** Hide every snapshot already past its limit (timers may have stalled). */
  function sweep(): void {
    tick();
    for (const product of COAST_PRODUCTS) if (cache.value[product] && !live(cache.value[product], clock.value)) expire(product);
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
      const held = cache.value[product];
      batch(() => {
        tick();
        if (typeof outcome === 'object') {
          // Keep the newer snapshot: an older copy (a saved offline pack) never replaces a fresher one.
          if (!live(held, Date.now()) || Date.parse(outcome.generatedAt) >= Date.parse(held.generatedAt)) setCache(product, outcome);
          setStatus(product, 'ready');
        } else if (outcome === 'expired') {
          // An expired reply never hides a snapshot that is still within its limit.
          if (live(held, Date.now())) setStatus(product, 'ready');
          else { setCache(product, null); setStatus(product, 'expired'); }
        } else setStatus(product, outcome);
      });
      expire(product);
    })();
    return entry.done;
  }

  function setPlace(context: CoastReportContext | null): ReportBinding | null {
    if (!alive) return null;
    sweep();
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
    sweep();
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
    for (const type of CLOCK_EVENTS) events?.removeEventListener(type, tick);
    abortAll();
    for (const timer of timers.values()) clearTimeout(timer);
    timers.clear();
    batch(() => { binding.value = null; status.value = allStatus('unbound'); cache.value = {report: null, ocean: null, history: null}; });
  }

  return {
    coastReport: admitted('report'), coastOcean: admitted('ocean'), coastHistory: admitted('history'),
    coastStatus: shownStatus, coastBinding: binding, setPlace, load, refresh, destroy,
  };
}

/** The v2 shell's client. Tests and secondary mounts create their own. */
export const coastData = createCoastData();
export const {coastReport, coastOcean, coastHistory, coastStatus, coastBinding} = coastData;
