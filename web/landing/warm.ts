// Warm the app from the landing (#617): after the landing's own first paint,
// fetch the app's first-paint files (precache.json `warm`, scripts/precache.mjs
// appWarm) into the browser cache at low priority, so choosing a port opens
// /map without waiting on its scripts and styles. They are hashed and cached
// for a year (scripts/client-build.mjs), so the app's own requests reuse them.
// Nothing region-specific is fetched here, and nothing at all when the visitor
// asked to save data (save-data.ts). Erasable syntax only: tests/test_landing.mjs
// imports this file by type stripping.
import {saveData} from './save-data.ts';

/** The hashed same-origin paths in a precache.json's `warm` list; anything else is ignored. */
export function warmList(precache: unknown): string[] {
  const list = (precache as {warm?: unknown} | null)?.warm;
  return Array.isArray(list) ? list.filter((p): p is string => typeof p === 'string' && /^\/assets\/[\w.-]+$/.test(p)) : [];
}

/** Fetch the app's first-paint files once; resolves with the paths requested (none under Save-Data or on any failure). */
export async function warmApp(fetchFn: typeof fetch = (...a) => fetch(...a), nav: unknown = globalThis.navigator): Promise<string[]> {
  if (saveData(nav)) return [];
  try {
    const response = await fetchFn('/precache.json', {cache: 'no-cache'});
    const paths = response.ok ? warmList(await response.json()) : [];
    await Promise.all(paths.map(p => fetchFn(p, {priority: 'low'} as RequestInit).then(r => r.blob(), () => null)));
    return paths;
  } catch { return []; }
}
