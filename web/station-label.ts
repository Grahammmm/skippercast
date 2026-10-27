// Which station a feed source's reading actually came from (#554 station
// failover). A configured buoy or tide role names `station` on its source,
// and `fallback_for` (the primary's id) only when a backup station served
// the data. Source ids stay tied to the primary, so `buoy-46053` may carry
// 46054's readings: every label and official link must come from here, never
// from the region's configured name for the primary. A source without these
// fields (every feed before #554, and unconfigured roles) reads exactly as it
// did: the caller's station id.
//
// Erasable syntax only: Node tests and dist/*.js import this file.

export interface StationSource {
  readonly station?: unknown;
  readonly fallback_for?: unknown;
  readonly data?: unknown;
}

export interface SourceStation {
  /** The station the reading came from. */
  readonly id: string;
  /** The primary station's id when a backup served the reading; null otherwise. */
  readonly backupFor: string | null;
}

const ident = (value: unknown): string | null => typeof value === 'string' && /^[A-Za-z0-9_-]{1,16}$/.test(value.trim()) ? value.trim() : null;

/**
 * The station behind `source`: its `station`, or (for a backup without one)
 * its data's station. A declared backup without either identity returns null;
 * only sources without a valid `fallback_for` may use `fallback` (the caller's
 * existing choice). Null when nothing eligible names a station.
 */
export function sourceStation(source: StationSource | null | undefined, fallback?: string | null): SourceStation | null {
  const primary = ident(source?.fallback_for);
  const dataStation = ident((source?.data as {station?: unknown} | null | undefined)?.station);
  const id = ident(source?.station) ?? (primary ? dataStation : ident(fallback ?? null));
  if (!id) return null;
  return {id, backupFor: primary && primary !== id ? primary : null};
}

/** "46054 (backup for 46053)", or just "46053" for a primary or legacy source. */
export const stationText = (s: SourceStation): string => s.backupFor ? `${s.id} (backup for ${s.backupFor})` : s.id;

/** NDBC's official station page. */
export const ndbcStationURL = (id: string): string => `https://www.ndbc.noaa.gov/station_page.php?station=${encodeURIComponent(id)}`;
/** CO-OPS official station home page (observed water level). */
export const tideStationURL = (id: string): string => `https://tidesandcurrents.noaa.gov/stationhome.html?id=${encodeURIComponent(id)}`;
/** CO-OPS official tide prediction page for the station. */
export const tidePredictionURL = (id: string): string => `https://tidesandcurrents.noaa.gov/noaatidepredictions.html?id=${encodeURIComponent(id)}`;

/**
 * Two roles read the same physical station because a backup is in use (for
 * example the nearshore backup 46054 is also the offshore primary). Regions
 * that configure one buoy for both roles without failover keep their legacy
 * labels, so this is true only when either side is a backup.
 */
export function sharedStation(a: SourceStation | null | undefined, b: SourceStation | null | undefined): boolean {
  return !!a && !!b && a.id === b.id && !!(a.backupFor || b.backupFor);
}
