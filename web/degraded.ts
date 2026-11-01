// SC-LAUNCH-4: the Worker's cost ceiling (server/cost-ceiling.ts) answers
// past its daily budget with saved copies and free fallbacks instead of
// reading R2, and marks every such response X-SC-Degraded: cost-ceiling; a
// saved copy also carries X-SC-Last-Known-At, when it was last served live.
// watchDegraded wraps a fetch so any response with that mark publishes
// `degraded`, which the masthead and the mobile sheet show as a notice
// (DegradedNotice, web/app/Masthead.tsx). installDegradedWatch wraps the
// page's own fetch once, so every reader is covered without each one knowing
// about the ceiling: the feeds, the brief, the Chart and the PMTiles ranges
// the map reads on the main thread. The state lasts for the page: the
// ceiling holds until the UTC day ends.
//
// Erasable syntax only: the node tests import it by type stripping.
import {signal} from '@preact/signals';

export const DEGRADED_HEADER = 'X-SC-Degraded';
export const LAST_KNOWN_HEADER = 'X-SC-Last-Known-At';

/** Null while every response is live; else the oldest saved copy's time (ISO), or null when none was a saved copy. */
export type Degraded = {since: string | null} | null;
export const degraded = signal<Degraded>(null);

/** Publish the cost-ceiling mark of `response`, if it has one; the oldest saved copy wins. */
export function noteResponse(response: Pick<Response, 'headers'> | null | undefined): void {
  const headers = response?.headers;
  if (!headers || typeof headers.get !== 'function' || headers.get(DEGRADED_HEADER) !== 'cost-ceiling') return;
  const at = headers.get(LAST_KNOWN_HEADER), time = at ? Date.parse(at) : NaN;
  const since = Number.isFinite(time) ? new Date(time).toISOString() : null;
  const current = degraded.peek();
  if (current && (!since || (current.since && current.since <= since))) return;
  degraded.value = {since: since ?? current?.since ?? null};
}

const wrapped = new WeakSet<typeof fetch>();

/** `fetchFn`, publishing the cost-ceiling mark of every response it returns; the response itself is untouched. */
export function watchDegraded(fetchFn: typeof fetch): typeof fetch {
  if (wrapped.has(fetchFn)) return fetchFn;
  const watched = ((...args: Parameters<typeof fetch>) => fetchFn(...args).then(response => { noteResponse(response); return response; })) as typeof fetch;
  wrapped.add(watched);
  return watched;
}

/** Wrap `scope.fetch` once (the page's, by default). */
export function installDegradedWatch(scope: {fetch?: typeof fetch} = globalThis): void {
  if (typeof scope.fetch !== 'function') return;
  const original = scope.fetch;
  scope.fetch = watchDegraded((...args: Parameters<typeof fetch>) => original.apply(scope, args));
}

/** The notice's words for `state`; null while live. `time` formats a saved copy's ISO time. */
export function degradedText(state: Degraded, time: (iso: string) => string = localTime): string | null {
  if (!state) return null;
  const saved = state.since ? `some readings are saved copies from ${time(state.since)}` : 'some readings are saved copies';
  return `Live data is paused for today to keep SkipperCast free; ${saved}.`;
}

function localTime(iso: string): string {
  try { return new Date(iso).toLocaleString(undefined, {weekday: 'short', hour: 'numeric', minute: '2-digit'}); } catch { return iso; }
}
