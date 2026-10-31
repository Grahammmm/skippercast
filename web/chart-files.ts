// The Chart side files the loaded region publishes (region.json `chart_files`, RF0835-2), so the
// land-water index, the poster and the offline pack skip a file the region does not publish
// (Cambria: no 404). Anything unknown fails open: before region.json loads, for another region,
// or when the key is absent or malformed, every file is still requested. App.tsx publishes it;
// this module imports nothing from the app, so leaf modules avoid an import cycle.
// Erasable syntax only: Node tests import it.
import {signal} from '@preact/signals';

/** The published list for the region whose region.json last loaded; `files` is null when it named none. */
export const publishedChartFiles = signal<{readonly region: string; readonly files: readonly string[] | null} | null>(null);

/** A frozen copy of `raw` when it is an array of strings, else null. */
export function chartFilesOf(raw: unknown): readonly string[] | null {
  return Array.isArray(raw) && raw.every(name => typeof name === 'string') ? Object.freeze([...raw] as string[]) : null;
}

/** False only when `region`'s published list is known and lacks `name`; true otherwise (fail open). */
export function chartFileListed(region: string, name: string): boolean {
  const published = publishedChartFiles.peek();
  return !(published?.region === region && Array.isArray(published.files) && !published.files.includes(name));
}
