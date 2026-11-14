// SC-PERF-LAZY-1: whether the map has first painted. Its own file so the chart can set it without importing the ranking code.
import {signal} from '@preact/signals';

/** True once the map has drawn its first idle frame, or could not start (so nothing waits for a map that will not come). */
export const mapFirstIdle = signal(false);
export const markMapIdle = (): void => { if (!mapFirstIdle.peek()) mapFirstIdle.value = true; };

/**
 * SCB-11: false while the page holds the Chart's own downloads (MapLibre, the basemap, the protected areas, the marks) so that
 * they do not share a slow link with the files the first verdict needs; true otherwise. web/app/main.tsx holds it on a page that
 * opens on a region and releases it once the first verdict is on screen (or after MAP_WAIT_MAX_MS). One hold per visit.
 */
export const mapMayLoad = signal(true);
/** The longest the map waits for the first verdict, from the start of the page load. */
export const MAP_WAIT_MAX_MS = 6000;
let held = false;
/** Hold the map's downloads; only the first call of a visit holds, so a released map never waits again. */
export const holdMap = (): void => { if (held) return; held = true; mapMayLoad.value = false; };
export const releaseMap = (): void => { if (!mapMayLoad.peek()) mapMayLoad.value = true; };
/** Run `fn` once, as soon as the map may load (at once when it already may). */
export function whenMapMayLoad(fn: () => void): void {
  if (mapMayLoad.peek()) { fn(); return; }
  let done = false;
  const stop = mapMayLoad.subscribe(may => { if (!may || done) return; done = true; queueMicrotask(() => stop()); fn(); });
}
