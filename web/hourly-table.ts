// Hour-by-hour conditions table (BF-hourly-table): one row per whole local hour
// of the time dock's day, read through the verdict's own feed reader
// (web/brief/verdict.ts feedReader) and rated by score.ts rateComfort for the
// reference boat, so every row carries the score the brief rates with. Wind,
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
import {sample} from './map/forecast-grid.ts';
import {rateComfort} from './score.ts';

const HOUR = 3_600_000, METRES_PER_MILE = 1609.344;
export const NO_FORECAST = 'No forecast for this day.';
export const LIMITED_NOTE = 'Limited estimate: a model or partition is missing.';

export interface HourlyRow {
  readonly at: string; readonly ms: number;
  readonly wind: number | null; readonly gust: number | null; readonly seas: number | null;
  readonly swell: {readonly h: number | null; readonly period: number | null; readonly from: number | null};
  readonly chop: {readonly h: number | null; readonly period: number | null};
  readonly tide: number | null; readonly visibilityMi: number | null;
  readonly score: number | null; readonly limited: boolean;
}

const num = (v: unknown): number | null => typeof v === 'number' && Number.isFinite(v) ? v : null;

/** The rows for local day `day` ("YYYY-MM-DD") in `tz`; with no forecast or no hour that day, no rows and a note. */
export function hourlyTable(f: ConditionsForecast | null, tide: Series | null, day: string, tz: string, now: Date): {rows: HourlyRow[]; note: string | null} {
  if (!f) return {rows: [], note: NO_FORECAST};
  const feed = feedReader(f, now), gfs = f.models.gfs_global;
  const issued = num(gfs?.issued), visRun = gfs && issued !== null && now.getTime() - issued * 1000 <= RUN_MAX_MS ? gfs : null;
  const hours = [...new Set(feed.times)].filter(ms => ms % HOUR === 0 && localParts(new Date(ms), tz).day === day).sort((a, b) => a - b);
  const rows = hours.map((ms): HourlyRow => {
    const h = feed.read(ms), rating = rateComfort(h), at = new Date(ms).toISOString();
    const wind = num(h.wind), gust = num(h.gust), period = num(h.sea_period);
    const metres = visRun ? sample(visRun.data, 'visibility', ms / 1000, 'm', visRun.end ? {data_end_time: visRun.end} : null) : null;
    return {
      at, ms, wind, gust: gust !== null && wind !== null && gust >= wind ? gust : null,
      seas: period !== null && period > 0 ? num(h.sea) : null,
      swell: {h: num(h.swell), period: num(h.swell_period), from: num(h.swell_from)},
      chop: {h: num(h.chop), period: num(h.chop_period)},
      tide: tide ? readingsAt([tide], at)[0]!.value : null,
      visibilityMi: metres === null ? null : Math.round(metres / METRES_PER_MILE * 10) / 10,
      score: rating?.score ?? null, limited: rating?.limited ?? false,
    };
  });
  return {rows, note: rows.length ? null : NO_FORECAST};
}

const fix = (v: number | null, digits: number, unit: string) => v === null ? '—' : `${v.toFixed(digits)}${unit}`;

/** A row's cells after the time: wind, gust, seas, swell, chop, tide, visibility, score ("*" marks a limited estimate). */
export function hourlyCells(r: HourlyRow): string[] {
  const swell = r.swell.h === null ? '—' : `${fix(r.swell.h, 1, ' ft')} · ${fix(r.swell.period, 0, ' s')} · ${fix(r.swell.from, 0, '°')}`;
  const chop = r.chop.h === null ? '—' : `${fix(r.chop.h, 1, ' ft')} · ${fix(r.chop.period, 0, ' s')}`;
  return [fix(r.wind, 0, ' kt'), fix(r.gust, 0, ' kt'), fix(r.seas, 1, ' ft'), swell, chop, fix(r.tide, 1, ' ft'), fix(r.visibilityMi, 1, ' mi'),
    r.score === null ? '—' : `${r.score.toFixed(1)}${r.limited ? '*' : ''}`];
}
