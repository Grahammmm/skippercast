// SC1407-06 (#1762 M4): one live CDFW ds582 boundary read for the map's mark screen (web/map/marks.ts) and the planner's
// screen (dist/protected-areas.js) when both ask the exact same query URL at the same time. Only a read still in flight is
// shared: the entry is dropped as soon as it settles (answer, HTTP error, transport error, timeout or broken JSON), so a
// later refresh() always asks the network again and a finished answer is never handed to a new check. A URL that differs in
// any way (bounds, fields, output, parameter order) is a different read. The reader decides nothing about the data: each
// screen keeps its own checks (validMpas with its minimum, validMPAs) and its own fallback. `checkedAt` is the time the
// response arrived (fetch resolved, before the body is parsed), so a slow parse or a later consumer never renews it.

const TIMEOUT_MS = 20000;

/**
 * A reader with its own in-flight reads.
 * @param {{fetchFn?: typeof fetch, now?: () => number}} [options]
 * @returns {(url: string) => Promise<{readonly data: any, readonly checkedAt: string}>}
 */
export function createLiveMpaReader({fetchFn = (...a) => fetch(...a), now = Date.now} = {}) {
  /** @type {Map<string, {promise: Promise<{readonly data: any, readonly checkedAt: string}> | null}>} */
  const pending = new Map();
  return url => {
    if (typeof url !== 'string') return Promise.reject(new TypeError('live MPA read needs a URL string'));
    const held = pending.get(url);
    if (held?.promise) return held.promise;
    const entry = {promise: null};
    pending.set(url, entry);
    entry.promise = (async () => {
      const controller = new AbortController(), timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
      try {
        const response = await fetchFn(url, {signal: controller.signal});
        const checkedAt = new Date(now()).toISOString();
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        return Object.freeze({data, checkedAt});
      } finally {
        // Dropped before the answer settles, so nothing that runs after it can join this read.
        clearTimeout(timer);
        if (pending.get(url) === entry) pending.delete(url);
      }
    })();
    return entry.promise;
  };
}

/** The page's reader: the map and the planner import this one, so their concurrent identical reads meet here. */
export const readLiveMpa = createLiveMpaReader();
