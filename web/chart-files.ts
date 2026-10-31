// The Chart side files the loaded region publishes (region.json `chart_files`, RF0835-2), so the
// land-water index, the poster and the offline pack skip a file the region does not publish
// (Cambria: no 404). Anything unknown fails open: before region.json loads, for another region,
// or when the key is absent or malformed, every file is still requested. App.tsx publishes it;
// RF0850-2: on a region change App.tsx first marks the list pending, and the Chart's coastline and
// contours wait for it (chartFilesPending) rather than ask; a failed region.json read fails open.
// This module imports nothing from the app, so leaf modules avoid an import cycle.
// Erasable syntax only: Node tests import it.
import {signal} from '@preact/signals';

/** The published list for the region whose region.json last loaded; `files` is null when it named none.
 * `pending` (RF0850-2): App.tsx is loading this region's region.json, so its list is not known yet. */
export const publishedChartFiles = signal<{readonly region: string; readonly files: readonly string[] | null; readonly pending?: boolean} | null>(null);

/** RF0850-2: true while `region`'s region.json is loading. It reads the signal, so an effect that asks
 * runs again once the list is published (or the load fails, and every file fails open). */
export function chartFilesPending(region: string): boolean {
  const published = publishedChartFiles.value;
  return published?.region === region && published.pending === true;
}

/** A frozen copy of `raw` when it is an array of strings, else null. */
export function chartFilesOf(raw: unknown): readonly string[] | null {
  return Array.isArray(raw) && raw.every(name => typeof name === 'string') ? Object.freeze([...raw] as string[]) : null;
}

/** False only when `region`'s published list is known and lacks `name`; true otherwise (fail open). */
export function chartFileListed(region: string, name: string): boolean {
  const published = publishedChartFiles.peek();
  return !(published?.region === region && Array.isArray(published.files) && !published.files.includes(name));
}
