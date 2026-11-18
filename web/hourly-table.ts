// Hour-by-hour conditions table (BF-hourly-table): one row per whole local hour
// of the time dock's day, read through the verdict's own feed reader
// (web/brief/verdict.ts feedReader) and rated by score.ts rateComfort for the
// boat given (the saved boat's factors, as the brief verdict; the reference
// boat when none is passed), so every row carries the score the brief rates with. Wind,
// gusts and the wave partitions are the NOAA family's; the score uses both
// models whatever the view's model chip shows. Visibility is the GFS run's,
// metres to miles; tide comes from the local coast report's series where one
// binds. Rules as forecastRows: gusts below the wind and seas with no
// positive period stay blank. Nothing is filled: a missing value is null.
//
// Erasable syntax only: tests/test_hourly_table.mjs imports it by type stripping.
import type {Series} from '../packages/coast/src/charts/series.ts';
import {feedReader, RUN_MAX_MS} from './brief/verdict.ts';
import {readingsAt, type ConditionsForecast} from './conditions.ts';
import {localParts} from './hour.ts';
import {t, type Language, type StringId} from './i18n.ts';
import {compass} from './landing/readings.ts';
import {sample} from './map/forecast-grid.ts';
import type {ComfortLimits, LimitField} from '../packages/coast/src/limits.ts';
import {rateComfort, REFERENCE_BOAT, type BoatFactors} from './score.ts';
import {M_PER_FT, WIND_SPEED} from './units.ts';
import type {Units} from './unit-choice.ts';

const HOUR = 3_600_000, METRES_PER_MILE = 1609.344;
export const NO_FORECAST = 'No forecast for this day.';
export const LIMITED_NOTE = 'Limited estimate: a model or partition is missing.';

export interface HourlyRow {
  readonly at: string; readonly ms: number;
  readonly wind: number | null; readonly windFrom: number | null; readonly gust: number | null; readonly seas: number | null;
  readonly swell: {readonly h: number | null; readonly period: number | null; readonly from: number | null};
  readonly second: {readonly h: number | null; readonly from: number | null};
  readonly chop: {readonly h: number | null; readonly period: number | null};
  readonly tide: number | null; readonly visibilityMi: number | null;
  readonly score: number | null; readonly limited: boolean;
}

const num = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null;

/** The rows for local day `day` ("YYYY-MM-DD") in `tz`, scored for `boat`; with no forecast or no hour that day, no rows and a note. */
export function hourlyTable(f: ConditionsForecast | null, tide: Series | null, day: string, tz: string, now: Date, boat: BoatFactors = REFERENCE_BOAT): {rows: HourlyRow[]; note: string | null} {
  if (!f) return {rows: [], note: NO_FORECAST};
  const feed = feedReader(f, now), gfs = f.models.gfs_global;
  const issued = num(gfs?.issued), visRun = gfs && issued !== null && now.getTime() - issued * 1000 <= RUN_MAX_MS && issued * 1000 - now.getTime() <= HOUR ? gfs : null;
  const hours = [...new Set(feed.times)].filter(ms => ms % HOUR === 0 && Number.isFinite(new Date(ms).getTime()) && localParts(new Date(ms), tz).day === day).sort((a, b) => a - b);
  const rows = hours.map((ms): HourlyRow => {
    const h = feed.read(ms), rating = rateComfort(h, boat), at = new Date(ms).toISOString();
    const wind = num(h.wind), gust = num(h.gust), period = num(h.sea_period);
    const metres = visRun ? sample(visRun.data, 'visibility', ms / 1000, 'm', visRun.end ? {data_end_time: visRun.end} : null) : null;
    return {
      at, ms, wind, windFrom: wind === null ? null : num(h.wind_from), gust: gust !== null && wind !== null && gust >= wind ? gust : null,
      seas: period !== null && period > 0 ? num(h.sea) : null,
      swell: {h: num(h.swell), period: num(h.swell_period), from: num(h.swell_from)},
      second: {h: num(h.secondary), from: num(h.secondary_from)},
      chop: {h: num(h.chop), period: num(h.chop_period)},
      tide: tide ? readingsAt([tide], at)[0]!.value : null,
      visibilityMi: metres === null ? null : Math.round(metres / METRES_PER_MILE * 10) / 10,
      score: rating?.score ?? null, limited: rating?.limited ?? false,
    };
  });
  return {rows, note: rows.length ? null : NO_FORECAST};
}

const fix = (v: number | null, digits: number, unit: string) => v === null ? '—' : `${v.toFixed(digits)}${unit}`;

/** A row's cells after the time: wind, gust, seas, swell, second swell, chop, tide, visibility, score ("*" marks a limited estimate). */
export function hourlyCells(r: HourlyRow, lang: Language = 'en', windUnit: Units['wind'] = 'kt', heightUnit: Units['height'] = 'ft'): string[] {
  const {factor, label} = WIND_SPEED[windUnit];
  const speed = (v: number | null) => fix(v === null ? null : v * factor, 0, ` ${label}`);
  const height = (v: number | null) => fix(heightUnit === 'm' && v !== null ? v * M_PER_FT : v, 1, ` ${heightUnit}`);
  const from = (value: string, deg: number) => t('hourly.from', lang, {value, dir: t(`compass.${compass(deg)}` as StringId, lang)});
  const swell = r.swell.h === null ? '—' : `${height(r.swell.h)} · ${fix(r.swell.period, 0, ' s')} · ${fix(r.swell.from, 0, '°')}`;
  const chop = r.chop.h === null ? '—' : `${height(r.chop.h)} · ${fix(r.chop.period, 0, ' s')}`;
  const wind = r.wind !== null && r.windFrom !== null ? from(speed(r.wind), r.windFrom) : speed(r.wind);
  const second = r.second.h !== null && r.second.h > 0 && r.second.from !== null ? from(`${height(r.second.h)} ·`, r.second.from) : '—';
  return [wind, speed(r.gust), height(r.seas), swell, second, chop, height(r.tide), fix(r.visibilityMi, 1, ' mi'),
    r.score === null ? '—' : `${r.score.toFixed(1)}${r.limited ? '*' : ''}`];
}

/** Which of wind, gust and seas are over the person's own limits: the strictly-greater, finite-only comparison of packages/coast/src/daily.ts buildDaily's overLimit. `null` (default limits) marks nothing. */
export function overLimits(r: HourlyRow, limits: ComfortLimits | null): Record<LimitField, boolean> {
  const over = (v: number | null, max: number | undefined) => !!limits && v !== null && Number.isFinite(v) && typeof max === 'number' && v > max;
  return {wind: over(r.wind, limits?.wind), gust: over(r.gust, limits?.gust), seas: over(r.seas, limits?.seas)};
}
