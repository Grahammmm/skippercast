// SC2252-05: the regional model forecast at each planned stop's arrival hour, as text lines for the trip plan. Pure: no fetch, storage,
// score or side effect. Each stop calls the mark card's own reader (web/brief/mark-forecast.ts markForecast) at that stop's arrival
// instant from web/trip-times.ts, with one captured `now` for every stop, so both NOAA and ECMWF read exactly as the mark card reads them
// and keep their own runs. The values are the regional forecast point's, not a reading at the stop or the reef: stops at different
// places honestly read the same point. Nothing here rates, ranks or clears a stop; a person's own limits only add the brief's words for
// a value over one. The lines live in the rendered plan only (never the draft, GPX, alert snapshot, share link or offline notes).
//
// Requests: the plan asks the shared loader (web/brief/Brief.tsx ensureRegionalForecast, the mark card's own) once per opening and
// region, with the region's own centre. A plan of six stops makes one GET /api/forecast?region=<id> when that region's forecast is not
// cached, shared with any mark card or brief asking at the same time; zero when it is cached; none per stop, redraw, edit or reorder.
//
// Erasable syntax only: tests import it by type stripping.
import type {ConditionsForecast, Family} from './conditions.ts';
import {hourText, markForecast, runText, type MarkReading} from './brief/mark-forecast.ts';
import type {ComfortLimits} from '../packages/coast/src/limits.ts';
import {num, t, type Language} from './i18n.ts';
import {fixed} from './view-copy.ts';
import type {TripTimes} from './trip-times.ts';

/** One model row at the arrival hour: a value (with the hour and run it was read from), no forecast for the hour, or another gap with its reason. */
export type ArrivalCell =
  | {state: 'value'; validAt: number; issuedAt: number | null; sampled: NonNullable<MarkReading['sampled']>}
  | {state: 'no-hour'}
  | {state: 'gap'; reason: string};
export interface ArrivalFamily {family: Family; label: string; wind: ArrivalCell; seas: ArrivalCell; /** The brief's words for each value over the person's own limit; [] without own limits. */ over: string[]}
export interface StopArrival {id: string; arriveAt: number; families: ArrivalFamily[]; line: string}
export interface TripArrivalForecast {/** The regional forecast point every value is read at. */ point: string; stops: Map<string, StopArrival>}

export interface TripForecastInput {
  forecast: ConditionsForecast | null; region: string; stops: readonly {id: string; lat: number; lon: number}[]; times: TripTimes;
  now: number; zone: string; language: Language;
  /** The active profile's own saved limits; null when the person has none (defaults get no marker). */
  ownLimits: ComfortLimits | null;
}

const round = Math.round;
function cell(r: MarkReading): ArrivalCell {
  if (r.value !== null && r.sampled && r.validAt !== null) return {state: 'value', validAt: r.validAt, issuedAt: r.issuedAt, sampled: r.sampled};
  return r.gapKind === 'outside-hours' || r.gapKind === 'no-hour' ? {state: 'no-hour'} : {state: 'gap', reason: r.gap};
}

/** A value over the person's own limit, in the brief's words (packages/coast/src/daily.ts overLimit); strictly over, on the unrounded numbers. */
function overWords(f: {wind: ArrivalCell; seas: ArrivalCell}, limits: ComfortLimits | null, lang: Language): string[] {
  if (!limits) return [];
  const w = f.wind.state === 'value' ? f.wind.sampled : null, s = f.seas.state === 'value' ? f.seas.sampled : null, out: string[] = [];
  // Only the placeholder is localized (Spanish decimal comma, no grouping); the comparisons below stay on the raw numbers and English keeps its number as is.
  const shown = (n: number): string | number => lang === 'en' ? n : num(n, lang, 1);
  if (w && w.windKn !== null && w.windKn > limits.wind) out.push(t('planner.forecast.overWind', lang, {n: shown(limits.wind)}));
  if (w && w.gustKn !== null && w.gustKn > limits.gust) out.push(t('planner.forecast.overGust', lang, {n: shown(limits.gust)}));
  if (s && s.seasFt !== null && s.seasFt > limits.seas) out.push(t('planner.forecast.overSeas', lang, {n: shown(limits.seas)}));
  return out;
}

const source = (c: Extract<ArrivalCell, {state: 'value'}>, at: number, zone: string, lang: Language): string =>
  [c.validAt !== at ? t('markForecast.valid', lang, {hour: hourText(c.validAt, zone, lang)}) : '', c.issuedAt !== null ? t('markForecast.src.run', lang, {run: runText(c.issuedAt, zone, lang)}) : ''].filter(Boolean).join(' · ');

function cellText(c: ArrivalCell, kind: 'wind' | 'seas', at: number, zone: string, lang: Language): string {
  if (c.state === 'no-hour') return `${t(kind === 'wind' ? 'planner.forecast.windWord' : 'planner.forecast.seasWord', lang)}: ${t('planner.forecast.noHour', lang)}`;
  if (c.state === 'gap') return t('planner.forecast.gap', lang, {what: t(kind === 'wind' ? 'planner.forecast.windWord' : 'planner.forecast.seasWord', lang), reason: c.reason});
  const v = c.sampled, src = source(c, at, zone, lang);
  const body = kind === 'wind'
    ? t('planner.forecast.wind', lang, {speed: round(v.windKn!)}) + (v.gustKn !== null ? t('planner.forecast.gusts', lang, {gust: round(v.gustKn)}) : '')
    : t('planner.forecast.seas', lang, {height: fixed(lang === 'en' ? v.seasFt! : Number(v.seasFt!.toFixed(1)), 1, lang), period: round(v.periodS!)});
  return src ? `${body} (${src})` : body;
}

/**
 * The forecast at each stop's arrival: keyed by stop id, for ready times only (null otherwise, or when the region's feed or its
 * regional point is not there). Stops join their arrival by id, never by position or name.
 */
export function tripStopForecast(input: TripForecastInput): TripArrivalForecast | null {
  const {forecast, region, stops, times, now, zone, language: lang, ownLimits} = input;
  if (times.state !== 'ready') return null;
  const arrivals = new Map(times.stops.map(s => [s.id, s.arriveAt]));
  let point: string | null = null;
  const out = new Map<string, StopArrival>();
  for (const stop of stops) {
    const at = arrivals.get(stop.id);
    if (at === undefined) continue;
    const f = markForecast(forecast, region, {lat: stop.lat, lon: stop.lon}, at, now, zone, lang);
    if (!f) return null;
    point = f.point;
    const families = f.families.map(fam => {
      const wind = cell(fam.rows[0]!), seas = cell(fam.rows[1]!);
      return {family: fam.family, label: fam.label, wind, seas, over: overWords({wind, seas}, ownLimits, lang)};
    });
    const text = families.map(fam => {
      const parts = `${cellText(fam.wind, 'wind', at, zone, lang)}; ${cellText(fam.seas, 'seas', at, zone, lang)}`;
      return `${fam.label}: ${parts}${fam.over.length ? ` · ${fam.over.join(', ')} ${t('planner.forecast.yourLimits', lang)}` : ''}`;
    }).join(' | ');
    out.set(stop.id, {id: stop.id, arriveAt: at, families, line: t('planner.forecast.line', lang, {values: text})});
  }
  return point === null ? null : {point, stops: out};
}
