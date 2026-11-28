// The Chart side files the loaded region publishes (region.json `chart_files`, RF0835-2), so the
// land-water index, the poster and the offline pack skip a file the region does not publish
// (Cambria: no 404). Anything unknown fails open: before region.json loads, for another region,
// or when the key is absent or malformed, every file is still requested. App.tsx publishes it;
// RF0850-2: on a region change App.tsx first marks the list pending, and the Chart's coastline and
// contours wait for it (chartFilesPending) rather than ask; a failed region.json read fails open.
// This module imports nothing from the app, so leaf modules avoid an import cycle.
// Erasable syntax only: Node tests import it.
import {signal} from '@preact/signals';

/** The published list for the region whose region.json last loaded; `files` is null when unknown.
 * `pending` (RF0850-2): App.tsx is loading this region's region.json, so its list is not known yet. */
export const publishedChartFiles = signal<{readonly region: string; readonly files: readonly string[] | null; readonly pending?: boolean} | null>(null);

/** RF0850-2: true while `region`'s region.json is loading. It reads the signal, so an effect that asks
 * runs again once the list is published (or the load fails, and every file fails open). */
export function chartFilesPending(region: string): boolean {
  const published = publishedChartFiles.value;
  return published?.region === region && published.pending === true;
}

// Match the chart_files enum in schemas/region.schema.json.
export const CHART_FILE_NAMES: readonly string[] = Object.freeze([
  'depth-contours-overview.geojson',
  'depth-contours.geojson',
  'land-water-lines.json',
  'land-water.json',
  'poster.svg',
  'shoreline-overview.geojson',
  'shoreline.geojson',
]);

/** A frozen copy of a valid manifest list, or null if the whole list is unknown. */
export function chartFilesOf(raw: unknown): readonly string[] | null {
  if (!Array.isArray(raw)) return null;
  const names = new Set<string>();
  for (const name of raw) {
    if (typeof name !== 'string' || !CHART_FILE_NAMES.includes(name) || names.has(name)) return null;
    names.add(name);
  }
  return Object.freeze([...names]);
}

/** Terrain-only regions (Monterey, Santa Cruz): false only when `region`'s published list is known and names
 * neither contour file, so the menu shows Depth lines as not published. Reads the signal: a view re-renders when
 * the list arrives. Unknown, pending or another region's list fails open (true). */
export function contoursPublished(region: string | null): boolean {
  const published = publishedChartFiles.value;
  return !(region && published?.region === region && !published.pending && Array.isArray(published.files)
    && !published.files.includes('depth-contours.geojson') && !published.files.includes('depth-contours-overview.geojson'));
}

/** False only when `region`'s published list is known and lacks `name`; true otherwise (fail open). */
export function chartFileListed(region: string, name: string): boolean {
  const published = publishedChartFiles.peek();
  return !(published?.region === region && Array.isArray(published.files) && !published.files.includes(name));
}
