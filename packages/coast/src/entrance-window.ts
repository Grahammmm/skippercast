import type {BarHour, Entrance} from './bar-conditions.ts';

const HOUR = 3_600_000;
export type EntranceWindow = {departBy: number | null; returnBy: number | null; best: number | null; reason: string; judged: boolean};
export type EntranceWindowOptions = {entrance: Entrance; sunrise?: number | null; sunset?: number | null; formatHour?: (at: string) => string};

/** Longest contiguous non-hazardous run; ties go to the earlier run.
 * Each verdict covers [at, at + 1 hour); a single hour is enough.
 * Epoch arithmetic preserves elapsed hours across midnight and DST.
 */
export function entranceWindow(hours: readonly BarHour[], opts: EntranceWindowOptions): EntranceWindow {
  const empty = (reason: string, judged: boolean): EntranceWindow => ({departBy: null, returnBy: null, best: null, reason, judged});
  let previous = -Infinity;
  const timed = hours.map(hour => {
    const at = typeof hour.at === 'string' && /(Z|[+-]\d{2}:\d{2})$/.test(hour.at) ? Date.parse(hour.at) : NaN;
    if (!Number.isFinite(at)) throw new Error('entrance-window: invalid hour time');
    if (at === previous) throw new Error('entrance-window: duplicate hour time');
    if (at < previous) throw new Error('entrance-window: out-of-order hour time');
    previous = at;
    return {hour, at};
  });
  for (const bound of [opts.sunrise, opts.sunset]) {
    if (bound != null && !Number.isFinite(bound)) throw new Error('entrance-window: invalid daylight time');
  }
  if (opts.sunrise != null && opts.sunset != null && opts.sunset <= opts.sunrise) throw new Error('entrance-window: reversed daylight');
  type Run = {start: number; end: number; hours: BarHour[]};
  let current: Run | null = null, longest: Run | null = null;
  for (const {hour, at} of timed) {
    const start = Math.max(at, opts.sunrise ?? -Infinity), end = Math.min(at + HOUR, opts.sunset ?? Infinity);
    if (hour.band === 'Hazardous' || end <= start) {current = null; continue;}
    if (current && current.end === start) {current.end = end; current.hours.push(hour);}
    else current = {start, end, hours: [hour]};
    if (!longest || current.end - current.start > longest.end - longest.start) {
      longest = {start: current.start, end: current.end, hours: [...current.hours]};
    }
  }
  if (!longest) return empty(timed.length ? 'No window today.' : 'Entrance not judged: no hourly readings.', timed.length > 0);
  const missing = longest.hours.some(h => h.band === 'Unknown' || h.tide.stage === null
    || h.swell.heightFt === null || h.swell.periodS === null || h.swell.basis === null);
  if (opts.entrance.seawardDeg === null) return empty('Entrance not judged: wind against the ebb not judged (no seaward bearing).', false);
  if (missing) return empty('Entrance not judged: tide or swell driver missing in the window.', false);
  const cautions = longest.hours.filter(h => h.band === 'Caution');
  return {departBy: longest.start, returnBy: longest.end, best: longest.start, judged: true,
    reason: cautions.length ? `Caution hours: ${cautions.map(h => opts.formatHour ? opts.formatHour(h.at) : h.at).join(', ')}.` : 'No bar flag in this window.'};
}
