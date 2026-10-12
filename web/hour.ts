// ?hour= follows the forecast hour (P4-01b). weather-ui.js announces every
// render with a "skippercast:forecast" event (detail.time: the selected hour,
// epoch seconds) and owns the hour through the #detail-hour range input, so
// this reads that input and writes the URL, and on the first forecast selects
// the hour a shared link asks for, if it is inside the timeline.
import {hour, hourParam, parseHour, setParams} from './state.ts';

const HOUR = 3600;

/** The timeline index for `wanted` given the selected time and index, or null outside 0..max. */
export function indexForHour(wanted: number | null, selectedTime: number, selectedIndex: number, max = 168): number | null {
  if (wanted === null || !Number.isFinite(selectedTime)) return null;
  const i = Math.round((wanted - (selectedTime - selectedIndex * HOUR)) / HOUR);
  return i >= 0 && i <= max ? i : null;
}

export function followForecastHour(doc: Document = document): void {
  let applied = false;
  const follow = (event: Event) => {
    const detail = (event as CustomEvent<{time?: number; epoch?: number}>).detail || {};
    const selectedTime = detail.epoch ?? detail.time;
    const input = doc.getElementById('detail-hour') as HTMLInputElement | null;
    if (!input || typeof selectedTime !== 'number' || !Number.isFinite(selectedTime)) return;
    const index = Number(input.value) || 0;
    if (!applied) {
      applied = true;
      const i = indexForHour(parseHour(hour.value), selectedTime, index, Number(input.max) || 168);
      if (i !== null && i !== index) {
        input.value = String(i);
        input.dispatchEvent(new Event('input', {bubbles: true}));
        return;
      }
    }
    // "Now" (index 0) is the default and is not written.
    const next = index === 0 ? null : hourParam(selectedTime);
    if (next !== hour.value) setParams({hour: next});
  };
  // The clock publishes even when neither model can load.
  doc.addEventListener('skippercast:time', follow);
  doc.addEventListener('skippercast:forecast', follow);
}

// The v2 time dock's horizon (FE-12, design § 6): the 169 whole UTC hours from
// the current one, SkipperCast's seven-day timeline (index 0..168 above). The
// coast report adds rows and never shortens it, and a model outage never moves
// the selected hour (v1's coastal-clock.js rule): the horizon depends on the
// clock alone. Hours stay UTC instants grouped by the region's local calendar
// day, so a DST change day has 23 or 25 of them and no offset is guessed.
export const HORIZON_HOURS = 169;
const HOUR_MS = HOUR * 1000;
const formats = new Map<string, Intl.DateTimeFormat>();

/** The local calendar day, hour and short weekday of `date` in `tz`. */
export function localParts(date: Date, tz: string): {day: string; hour: number; weekday: string} {
  let f = formats.get(tz);
  if (!f) formats.set(tz, f = new Intl.DateTimeFormat('en-US', {timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', weekday: 'short'}));
  const p = Object.fromEntries(f.formatToParts(date).map(part => [part.type, part.value]));
  return {day: `${p.year}-${p.month}-${p.day}`, hour: Number(p.hour) % 24, weekday: p.weekday ?? ''};
}

/** One local day of the horizon: "YYYY-MM-DD", its weekday and its hours (epoch ms, ascending). */
export interface HorizonDay {readonly day: string; readonly weekday: string; readonly hours: readonly number[]}

/** The horizon from `now` by local day: today from the current hour, the last day up to 168 hours ahead. */
export function horizonDays(now: Date, tz: string): HorizonDay[] {
  const start = Math.floor(now.getTime() / HOUR_MS) * HOUR_MS;
  const days: {day: string; weekday: string; hours: number[]}[] = [];
  for (let i = 0; i < HORIZON_HOURS; i++) {
    const at = start + i * HOUR_MS, p = localParts(new Date(at), tz), last = days.at(-1);
    if (last?.day === p.day) last.hours.push(at);
    else days.push({day: p.day, weekday: p.weekday, hours: [at]});
  }
  return days;
}

/** The hour of `hours` whose local hour of day is closest to `hourOfDay` (the earlier on a tie). */
export function nearestHour(hours: readonly number[], hourOfDay: number, tz: string): number | null {
  let best: number | null = null, gap = Infinity;
  for (const at of hours) {
    const d = Math.abs(localParts(new Date(at), tz).hour - hourOfDay);
    if (d < gap) { best = at; gap = d; }
  }
  return best;
}

/** What the dock shows: the selected instant, its local day and that day's horizon hours. */
export interface DockTime {
  /** The selected hour, epoch ms. */
  readonly at: number;
  readonly day: string;
  readonly today: string;
  readonly hours: readonly number[];
  /** `at`'s position in `hours`; -1 when ?hour= lies outside the horizon (a stale or far link: kept, never reset). */
  readonly index: number;
}

/**
 * The dock's time for `?day=` and `?hour=`: the hour when it parses (it wins over the day),
 * else the same local hour on a later horizon day the link names, else the current whole hour.
 */
export function dockTime(dayValue: string | null, hourValue: string | null, now: Date, tz: string, days: readonly HorizonDay[] = horizonDays(now, tz)): DockTime {
  const first = days[0]!, seconds = parseHour(hourValue);
  const named = days.find(d => d.day === dayValue && d !== first);
  const at = seconds !== null ? seconds * 1000 : named ? nearestHour(named.hours, localParts(now, tz).hour, tz)! : first.hours[0]!;
  const day = localParts(new Date(at), tz).day;
  const hours = days.find(d => d.day === day)?.hours ?? [];
  return {at, day, today: first.day, hours, index: hours.indexOf(at)};
}

/** The hour after `at` in the horizon from `now`, or null at its end (or outside it). */
export function nextHour(at: number, now: Date): number | null {
  const start = Math.floor(now.getTime() / HOUR_MS) * HOUR_MS, next = at + HOUR_MS;
  return at >= start && next < start + HORIZON_HOURS * HOUR_MS ? next : null;
}

export interface PlayOptions {
  /** Move to the next hour; false at the end of the horizon. */
  step: () => boolean;
  /** Called once when play stops by itself: the end, a hidden page or reduced motion. */
  onStop: () => void;
  doc?: Pick<Document, 'hidden' | 'addEventListener' | 'removeEventListener'>;
  /** The prefers-reduced-motion query; a change to reduce stops play. */
  motion?: Pick<MediaQueryList, 'matches' | 'addEventListener' | 'removeEventListener'> | null;
  every?: number;
}

/**
 * Auto-play: one hour every `every` ms until the horizon ends or the page is hidden. Under
 * prefers-reduced-motion nothing animates: the press steps one hour and stops (design § 13).
 * Returns a function that stops play without calling `onStop`.
 */
export function play({step, onStop, doc = document, motion = null, every = 1000}: PlayOptions): () => void {
  if (motion?.matches || doc.hidden) {
    if (!doc.hidden) step();
    onStop();
    return () => {};
  }
  let timer: ReturnType<typeof setInterval> | undefined;
  const stop = (): void => {
    clearInterval(timer);
    doc.removeEventListener('visibilitychange', hidden);
    motion?.removeEventListener('change', reduced);
  };
  const end = (): void => { stop(); onStop(); };
  const hidden = (): void => { if (doc.hidden) end(); };
  const reduced = (): void => { if (motion?.matches) end(); };
  doc.addEventListener('visibilitychange', hidden);
  motion?.addEventListener('change', reduced);
  timer = setInterval(() => { if (!step()) end(); }, every);
  return stop;
}
