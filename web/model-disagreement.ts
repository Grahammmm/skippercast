// Model disagreement in words (BF-model-disagreement-plain): when NOAA and ECMWF
// are far apart in a day's morning window (6 am to noon local, the verdict's
// default window), the Conditions view says so in one sentence naming the day,
// the quantity and both values. THRESHOLDS are display thresholds only; they
// change nothing in the score, which already takes the rougher model
// (web/score.ts rateComfort). A model missing for the window gives no item: it
// is never read as agreement (the feed-gap wording covers missing models).
import {dateKey} from '../packages/coast/src/daily.ts';
import {DEFAULT_START_HOUR, feedReader, WINDOW_END_HOUR} from './brief/verdict.ts';
import {FAMILIES, type ConditionsForecast} from './conditions.ts';
import type {FeedHour} from './score.ts';

export const THRESHOLDS = Object.freeze({windKt: 6, seaFt: 2, hours: 2});
export interface Disagreement {readonly date: string; readonly quantity: 'wind' | 'seas'; readonly noaa: number; readonly ecmwf: number; readonly hours: number}

const DAY = 86_400_000, EPS = 1e-9;
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const QUANTITIES = [
  {quantity: 'wind', a: 'wind', b: 'other_wind', limit: THRESHOLDS.windKt},
  {quantity: 'seas', a: 'sea', b: 'other_sea', limit: THRESHOLDS.seaFt},
] as const;
const localHour = (ms: number, tz: string) =>
  Number(new Intl.DateTimeFormat('en-US', {timeZone: tz, hour: '2-digit', hourCycle: 'h23'}).formatToParts(new Date(ms)).find(p => p.type === 'hour')!.value);

/** Each of the next `days` local dates (from today) whose morning window has the models apart for THRESHOLDS.hours or more; at most one item a day. */
export function disagreements(forecast: ConditionsForecast, now: Date, tz: string, days = 3): Disagreement[] {
  const {times, read} = feedReader(forecast, now), today = dateKey(now, tz), out: Disagreement[] = [];
  for (let i = 0; i < days; i++) {
    const date = new Date(Date.parse(`${today}T12:00:00Z`) + i * DAY).toISOString().slice(0, 10);
    const rows = times.filter(ms => dateKey(new Date(ms), tz) === date && localHour(ms, tz) >= DEFAULT_START_HOUR && localHour(ms, tz) < WINDOW_END_HOUR)
      .sort((x, y) => x - y).map(ms => read(ms));
    let best: {item: Disagreement; rel: number} | null = null;
    for (const {quantity, a, b, limit} of QUANTITIES) {
      const pairs = rows.map((h: FeedHour) => [h[a], h[b]]).filter((p): p is [number, number] => finite(p[0]) && finite(p[1]));
      const apart = pairs.filter(([x, y]) => Math.abs(x - y) >= limit - EPS);
      if (apart.length < THRESHOLDS.hours) continue;
      const [noaa, ecmwf] = apart.reduce((m, p) => Math.abs(p[0] - p[1]) > Math.abs(m[0] - m[1]) ? p : m);
      const rel = Math.abs(noaa - ecmwf) / limit;
      if (!best || rel > best.rel) best = {item: {date, quantity, noaa, ecmwf, hours: apart.length}, rel};
    }
    if (best) out.push(best.item);
  }
  return out;
}

/** "today", "tomorrow" (the brief's leadDayText rule), else the weekday name, "Thursday". */
export function dayWord(date: string, now: Date, tz: string): string {
  const today = dateKey(now, tz), next = new Date(Date.parse(`${today}T12:00:00Z`) + DAY).toISOString().slice(0, 10);
  if (date === today) return 'today';
  if (date === next) return 'tomorrow';
  return new Date(`${date}T12:00:00Z`).toLocaleDateString('en-US', {timeZone: 'UTC', weekday: 'long'});
}

/** One plain sentence for an item; values rounded as the chart rounds them (kt whole, ft one decimal). */
export function sentence(item: Disagreement, now: Date, tz: string): string {
  const unit = item.quantity === 'wind' ? 'kt' : 'ft', v = (n: number) => `${Number(n.toFixed(unit === 'ft' ? 1 : 0))} ${unit}`;
  return `Models disagree about ${dayWord(item.date, now, tz)} morning: ${item.quantity} ${v(item.noaa)} (${FAMILIES.gfs.label}) vs ${v(item.ecmwf)} (${FAMILIES.ecmwf.label}). The score uses the rougher.`;
}
