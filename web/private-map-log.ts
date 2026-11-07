// SCFEAT-CATCH-1: this store is deliberately separate from the account catch API.
// No network, geolocation, URL state or telemetry. A blank means no catch recorded.
import type {ConditionsForecast} from './conditions.ts';
import {markForecast, type MarkForecast, type MarkReading} from './brief/mark-forecast.ts';

export const LOG_KEY = 'skippercast.private-map-log.v1';
const LIMIT = 500;
type Storage = Pick<globalThis.Storage, 'getItem' | 'setItem'>;
type Position = {readonly latitude: number; readonly longitude: number};
type LogMark = {readonly name: string; readonly position?: Position; readonly withheld?: boolean};
export interface MapLogEntry {
  readonly kind: 'catch' | 'blank';
  readonly name: string;
  readonly region: string;
  readonly position: Position;
  readonly positionBasis: 'Selected map position; not live GPS';
  readonly recordedAt: string;
  readonly conditions: {readonly at: number; readonly retrievedAt: number | null; readonly forecast: MarkForecast} | null;
}
const positionOK = (p: Position | undefined): p is Position => !!p && Number.isFinite(p.latitude) && Number.isFinite(p.longitude) && Math.abs(p.latitude) <= 90 && Math.abs(p.longitude) <= 180;

/** Capture time, not the time dock's selected forecast hour. Existing age/unit gates keep stale data as gaps. */
export function createEntry(mark: LogMark, kind: MapLogEntry['kind'], region: string, forecast: ConditionsForecast | null, now: number, tz: string): MapLogEntry | null {
  if (mark.withheld || !positionOK(mark.position) || !region || !Number.isFinite(now)) return null;
  const f = markForecast(forecast, region, {lat: mark.position.latitude, lon: mark.position.longitude}, now, now, tz);
  const retrieved = (forecast?.feed as {retrieved?: unknown} | undefined)?.retrieved;
  return {kind, name: mark.name, region, position: {...mark.position}, positionBasis: 'Selected map position; not live GPS', recordedAt: new Date(now).toISOString(),
    conditions: f ? {at: now, retrievedAt: typeof retrieved === 'number' && Number.isFinite(retrieved) ? retrieved : null, forecast: f} : null};
}

const clockOK = (v: unknown): boolean => typeof v === 'number' && Number.isFinite(new Date(v).getTime());
function readingOK(value: unknown): boolean {
  const r = value as MarkReading | null;
  return !!r && ['Wind', 'Seas', 'Current'].includes(r.label) && typeof r.model === 'string' && typeof r.grid === 'string'
    && (r.value === null || typeof r.value === 'string') && typeof r.gap === 'string' && (r.point === null || typeof r.point === 'string')
    && (r.validAt === null || clockOK(r.validAt)) && (r.issuedAt === null || clockOK(r.issuedAt))
    && (r.cell === null || (!!r.cell && Number.isFinite(r.cell.lat) && Number.isFinite(r.cell.lon) && Number.isFinite(r.cell.km)));
}
function load(storage: Storage): MapLogEntry[] {
  const raw = storage.getItem(LOG_KEY);
  if (raw === null) return [];
  const rows: unknown = JSON.parse(raw);
  if (!Array.isArray(rows) || !rows.every(r => r && (r.kind === 'catch' || r.kind === 'blank') && typeof r.name === 'string' && typeof r.region === 'string' && positionOK(r.position)
    && r.positionBasis === 'Selected map position; not live GPS' && typeof r.recordedAt === 'string' && Number.isFinite(Date.parse(r.recordedAt))
    && (r.conditions === null || (clockOK(r.conditions?.at) && (r.conditions.retrievedAt === null || clockOK(r.conditions.retrievedAt))
      && Array.isArray(r.conditions.forecast?.families) && r.conditions.forecast.families.every((f: {rows?: unknown}) => Array.isArray(f?.rows) && f.rows.every(readingOK)) && readingOK(r.conditions.forecast.current))))) throw Error('Unreadable device log');
  return rows;
}
/** Throws on blocked/corrupt storage so the UI never presents an unreadable log as empty. */
export function readEntries(storage: Storage = globalThis.localStorage): MapLogEntry[] { return load(storage); }
export function saveEntry(entry: MapLogEntry | null, storage?: Storage): 'saved' | 'unavailable' | 'full' {
  if (!entry) return 'unavailable';
  try {
    const target = storage ?? globalThis.localStorage, rows = load(target);
    if (rows.length >= LIMIT) return 'full';
    target.setItem(LOG_KEY, JSON.stringify([...rows, entry]));
    return 'saved';
  } catch { return 'unavailable'; }
}
