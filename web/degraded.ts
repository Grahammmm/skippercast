// SC-LAUNCH-4: the Worker's cost ceiling (server/cost-ceiling.ts) answers
// past its daily budget with saved copies and free fallbacks instead of
// reading R2, and marks every such response X-SC-Degraded: cost-ceiling; a
// saved copy also carries X-SC-Last-Known-At, when it was last served live.
// watchDegraded wraps a fetch so any response with that mark publishes
// `degraded`, which the masthead and the mobile sheet show as a notice
// (DegradedNotice, web/app/Masthead.tsx). installDegradedWatch wraps the
// page's own fetch once, so every reader is covered without each one knowing
// about the ceiling: the feeds, the brief, the Chart and the PMTiles ranges
// the map reads on the main thread. The ceiling holds until the UTC day ends;
// only a verified live feed on a later day retires the old notice. A
// Last-Known-At before 2020 or more than SKEW_MS past the page's clock is no
// time, so it cannot date the notice.
//
// Erasable syntax only: the node tests import it by type stripping.
import {signal} from '@preact/signals';
import {localeOf, type Language} from './i18n-core.ts';

export type DegradedTranslate = (id: 'shared.degraded.saved' | 'shared.degraded.savedAt', lang?: Language, vars?: Readonly<Record<string, string | number>>) => string;

export const DEGRADED_HEADER = 'X-SC-Degraded';
export const LAST_KNOWN_HEADER = 'X-SC-Last-Known-At';
/** The earliest believable saved-copy time, and how far past the page's clock one may be (clock skew). */
export const EARLIEST = Date.UTC(2020, 0, 1), SKEW_MS = 5 * 60_000;

/** Null when there is no active notice; else the marked day's oldest saved-copy time (ISO), if known. */
export type Degraded = {since: string | null} | null;
export const degraded = signal<Degraded>(null);

type ObservedResponse = Pick<Response, 'headers'> & Partial<Pick<Response, 'status' | 'type' | 'url'>>;
const utcDay = (ms: number): number => Math.floor(ms / 86_400_000);
let markedDay = -Infinity;
// An older in-flight mark cannot restore a notice after a verified recovery.
let recoveredDay = -Infinity;

/** The Worker's live path, not a static asset, saved copy, or cached public read. */
function liveRefresh(response: ObservedResponse, now: number, day: number): boolean {
  const {headers, status, type, url} = response;
  if (type !== 'basic' || (status !== 200 && status !== 206) || !url) return false;
  if (headers.has(LAST_KNOWN_HEADER) || headers.has('X-SC-Offline') || headers.has('X-SC-Saved-At')) return false;
  const age = headers.get('Age');
  if (age !== null && age !== '0') return false;
  const date = Date.parse(headers.get('Date') ?? '');
  if (utcDay(date) !== day || date > now + SKEW_MS) return false;
  let path: string;
  try { path = new URL(url).pathname; } catch { return false; }
  const cache = headers.get('X-SC-Cache');
  // Mirror the positive provenance already emitted by server/feeds.ts and server/routes/public.ts.
  if (path.startsWith('/feeds/')) return headers.get('X-Feed-Source') === 'r2' && cache !== 'hit';
  return status === 200 && cache === 'miss' && /^\/api\/(daily|forecast|intelligence|habitat)$/.test(path);
}

/** Publish marks by UTC budget day; retire a prior day's mark only on a live refresh. */
export function noteResponse(response: ObservedResponse | null | undefined, now: number = Date.now(), startedAt = now): void {
  const headers = response?.headers;
  if (!response || !headers || typeof headers.get !== 'function') return;
  const mark = headers.get(DEGRADED_HEADER);
  const day = utcDay(startedAt);
  const current = degraded.peek();
  if (mark !== 'cost-ceiling') {
    if (mark === null && current && day > markedDay && day === utcDay(now) && liveRefresh(response, now, day)) {
      recoveredDay = day;
      degraded.value = null;
    }
    return;
  }
  if (day < recoveredDay || (current && day < markedDay)) return;
  const at = headers.get(LAST_KNOWN_HEADER), time = at ? Date.parse(at) : NaN;
  const since = Number.isFinite(time) && time >= EARLIEST && time <= now + SKEW_MS ? new Date(time).toISOString() : null;
  if (current && day === markedDay && (!since || (current.since && current.since <= since))) return;
  markedDay = day;
  degraded.value = {since};
}

const wrapped = new WeakSet<typeof fetch>();

/** `fetchFn`, publishing the cost-ceiling mark of every response it returns; the response itself is untouched. */
export function watchDegraded(fetchFn: typeof fetch): typeof fetch {
  if (wrapped.has(fetchFn)) return fetchFn;
  const watched = ((...args: Parameters<typeof fetch>) => {
    const startedAt = Date.now();
    return fetchFn(...args).then(response => { noteResponse(response, Date.now(), startedAt); return response; });
  }) as typeof fetch;
  wrapped.add(watched);
  return watched;
}

/** Wrap `scope.fetch` once (the page's, by default). */
export function installDegradedWatch(scope: {fetch?: typeof fetch} = globalThis): void {
  if (typeof scope.fetch !== 'function') return;
  const original = scope.fetch;
  scope.fetch = watchDegraded((...args: Parameters<typeof fetch>) => original.apply(scope, args));
}

/** The notice's words for `state` in `lang` (English when omitted); null while live. `time` formats a saved copy's ISO time. */
export function degradedText(state: Degraded, t: DegradedTranslate, time?: (iso: string) => string, lang?: Language): string | null {
  if (!state) return null;
  return state.since ? t('shared.degraded.savedAt', lang ?? 'en', {time: (time ?? ((iso: string) => localTime(iso, lang)))(state.since)}) : t('shared.degraded.saved', lang ?? 'en');
}

// No language keeps the legacy browser-locale clock; a chosen language formats in its own locale.
function localTime(iso: string, lang?: Language): string {
  try { return new Date(iso).toLocaleString(lang ? localeOf(lang) : undefined, {weekday: 'short', hour: 'numeric', minute: '2-digit'}); } catch { return iso; }
}
