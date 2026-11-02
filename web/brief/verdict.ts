// The day verdict (issue #616, walkthrough slice 1): one word for the morning
// window (Comfortable, Marginal, Rough or Unknown) and one sentence naming
// what limits it, so the brief leads with the answer and the detail folds
// below.
//
// - Boat: the one conditions model (web/score.ts). Every hour from sunrise to
//   noon on the brief's date is rated by rateComfort over the regional
//   dual-model feed (the same feed and point as the Conditions view), for the
//   reference 23 ft boat, and the window takes its worst hour: 7 and above is
//   Comfortable, under 4 Rough, between Marginal (verdictFor). The sentence
//   names the largest charge in that hour (wind, seas, wind chop or a
//   crossing swell). The advisor's comfort word reads the same function.
// - Shore, Spear and Kayak: their own hourly graders (packages/coast
//   shore-conditions.ts, spear.ts, kayak.ts), worst hour in the same window,
//   Calmer read as Comfortable; the sentence leads with the hour's decisive
//   reasons, costed by the grader's own score table (launch surf, fog or
//   darkness before light wind; bonuses such as dawn or tide never named).
// - Never reassuring on thin evidence: an active marine alert makes the day
//   Rough; partial forecast detail, unrated hours, a run older than its tile
//   limit, a missing alert check, a hazardous bar estimate or an hour in the
//   long-period swell rule (score.ts LONG_PERIOD_SWELL) hold a
//   Comfortable window at Marginal and say why; on a Marginal or Rough day a
//   missing alert check is still named. No forecast reads Unknown.
//   Buoy readings never enter the verdict, so a stale buoy cannot raise it.
//
// A comfort heuristic for planning, not a bite or catch forecast and not a
// safety clearance.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {chargedCosts, LONG_PERIOD_SWELL, rateComfort, verdictFor, type ComfortRating, type FeedHour, type Verdict} from '../score.ts';
import {sample} from '../map/forecast-grid.ts';
import type {ConditionsForecast, ModelRun} from '../conditions.ts';
import type {Profile} from '../profile.ts';
import {KAYAK} from '../../packages/coast/src/kayak.ts';
import {SHORE} from '../../packages/coast/src/shore-conditions.ts';
import {SPEAR} from '../../packages/coast/src/spear.ts';
import type {Brief} from './types.ts';

const HOUR = 3_600_000;

export type DayVerdict = 'comfortable' | 'marginal' | 'rough' | 'unknown';
export const VERDICT_WORD: Readonly<Record<DayVerdict, string>> = Object.freeze({comfortable: 'Comfortable', marginal: 'Marginal', rough: 'Rough', unknown: 'Unknown'});
const FROM_SCORE: Readonly<Record<Verdict, DayVerdict>> = Object.freeze({go: 'comfortable', marginal: 'marginal', 'no-go': 'rough', unknown: 'unknown'});

/** The morning window ends at local noon: trips run sunrise to noon. */
export const WINDOW_END_HOUR = 12;
/** Without a sunrise time the window starts at this local hour. */
export const DEFAULT_START_HOUR = 6;
/** A model run older than this holds the verdict at Marginal (the Wind and Swell tiles' stale limit). */
export const RUN_STALE_MS = 18 * HOUR;
/** A model run older than this is not used at all (v1's usable rule, dist/morning-outlook.js). */
export const RUN_MAX_MS = 36 * HOUR;
/** The line packages/coast daily.ts adds to `missing` when the marine alert check is not fresh. */
export const ALERT_CHECK_MISSING = 'Current marine alert check unavailable';
/** A second charge is named only when it costs at least a point. */
const SECOND_COST = 1;

export interface BriefVerdict {
  readonly verdict: DayVerdict;
  /** One sentence: what limits the window, at which hour. */
  readonly limit: string;
  /** Why a Comfortable window is held at Marginal, as one sentence; null when nothing holds it. */
  readonly held: string | null;
  /** The window rated, for example "6 am–noon"; null without one. */
  readonly window: string | null;
  /** The worst hour's comfort score out of 10 (boat only); null otherwise. */
  readonly score: number | null;
  /** What graded it: the comfort score, or the profile's own hourly grader. */
  readonly basis: 'comfort-score' | Exclude<Profile, 'boat'>;
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const r0 = (n: number) => String(Math.round(n));
const r1 = (n: number) => String(Number(n.toFixed(1)));
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
const compass = (deg: number | null) => finite(deg) ? COMPASS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]! : null;

function local(ms: number, tz: string): {date: string; hour: number} {
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-CA', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', hourCycle: 'h23'})
    .formatToParts(new Date(ms)).map(p => [p.type, p.value]));
  return {date: `${parts.year}-${parts.month}-${parts.day}`, hour: Number(parts.hour)};
}

/** "7 am", "noon", "1 pm" in the region's zone. */
export function clockText(ms: number, tz: string): string {
  const h = local(ms, tz).hour;
  return h === 12 ? 'noon' : h === 0 ? 'midnight' : `${h % 12} ${h < 12 ? 'am' : 'pm'}`;
}

/**
 * The hours to rate on `date`: whole hours starting at or after sunrise (or
 * 6 am) and before noon, from the current hour on when the date is today; once
 * the morning has passed, the hours ending by sunset (or 6 pm). Epoch
 * ms, ascending. `covered` says whether the candidates reach the date at all.
 */
export function windowHours(candidates: readonly number[], date: string, tz: string, sunrise: string | null, sunset: string | null, now: Date): {hours: number[]; label: string | null; covered: boolean} {
  const riseMs = sunrise ? Date.parse(sunrise) : NaN, setMs = sunset ? Date.parse(sunset) : NaN;
  const afterRise = (ms: number) => Number.isFinite(riseMs) ? ms >= riseMs : local(ms, tz).hour >= DEFAULT_START_HOUR;
  const beforeSet = (ms: number) => Number.isFinite(setMs) ? ms + HOUR <= setMs : local(ms, tz).hour < 18;
  const from = Math.floor(now.getTime() / HOUR) * HOUR;
  const onDate = [...candidates].filter(ms => local(ms, tz).date === date).sort((a, b) => a - b);
  const on = onDate.filter(ms => ms >= from && afterRise(ms) && beforeSet(ms));
  const label = (hours: number[], end: string) => `${clockText(hours[0]!, tz)}–${end}`;
  const morning = on.filter(ms => local(ms, tz).hour < WINDOW_END_HOUR);
  if (morning.length) return {hours: morning, label: label(morning, 'noon'), covered: true};
  return {hours: on, label: on.length ? label(on, clockText(on.at(-1)! + HOUR, tz)) : null, covered: onDate.length > 0};
}

const usable = (run: ModelRun | undefined, now: Date): run is ModelRun => !!run && finite(run.issued) && now.getTime() - run.issued * 1000 <= RUN_MAX_MS;

/** The feed's hourly epochs (ms) and one FeedHour reader over its usable runs; runs with no issue time or over 36 h old read as missing. */
export function feedReader(f: ConditionsForecast, now: Date): {times: number[]; read: (ms: number) => FeedHour; oldestMs: number | null} {
  const runs = Object.fromEntries(['gfs_global', 'ncep_gfswave016', 'ecmwf_ifs025', 'ecmwf_wam'].map(id => [id, f.models[id]]).filter(([, run]) => usable(run as ModelRun | undefined, now)) as [string, ModelRun][]);
  const clock = (runs.gfs_global ?? runs.ecmwf_ifs025)?.data as {hourly?: {time?: unknown}} | undefined;
  const times = Array.isArray(clock?.hourly?.time) ? (clock!.hourly!.time as unknown[]).filter(finite).map(t => t * 1000) : [];
  const issued = Object.values(runs).map(run => run.issued as number);
  const at = (id: string, key: string, unit: string, epoch: number) => {
    const run = runs[id];
    return run ? sample(run.data, key, epoch, unit, run.end ? {data_end_time: run.end} : null) : null;
  };
  const read = (ms: number): FeedHour => {
    const e = ms / 1000, period = at('ncep_gfswave016', 'wave_period', 's', e), valid = period === null || period > 0;
    return {
      wind: at('gfs_global', 'wind_speed_10m', 'kn', e), gust: at('gfs_global', 'wind_gusts_10m', 'kn', e), wind_from: at('gfs_global', 'wind_direction_10m', '°', e),
      sea: valid ? at('ncep_gfswave016', 'wave_height', 'ft', e) : null, sea_period: valid ? period : null,
      chop: at('ncep_gfswave016', 'wind_wave_height', 'ft', e), chop_period: at('ncep_gfswave016', 'wind_wave_period', 's', e),
      swell: at('ncep_gfswave016', 'swell_wave_height', 'ft', e), swell_period: at('ncep_gfswave016', 'swell_wave_period', 's', e), swell_from: at('ncep_gfswave016', 'swell_wave_direction', '°', e),
      secondary: at('ncep_gfswave016', 'secondary_swell_wave_height', 'ft', e), secondary_from: at('ncep_gfswave016', 'secondary_swell_wave_direction', '°', e),
      other_wind: at('ecmwf_ifs025', 'wind_speed_10m', 'kn', e), other_gust: at('ecmwf_ifs025', 'wind_gusts_10m', 'kn', e), other_sea: at('ecmwf_wam', 'wave_height', 'ft', e),
    };
  };
  return {times, read, oldestMs: issued.length ? now.getTime() - Math.min(...issued) * 1000 : null};
}

type Charge = 'wind' | 'seas' | 'chop' | 'cross';

/**
 * What the score took off one rated hour, by charge, largest first (score.ts chargedCosts: the
 * smaller of the wind and wave burdens at its overlap share, the unpicked one of seas and chop at
 * nothing); wind chop carries the short-chop penalty too. Ties keep wind, seas, chop, cross order.
 */
export function charges(r: ComfortRating): {kind: Charge; cost: number}[] {
  const taken = chargedCosts(r.costs);
  const list: {kind: Charge; cost: number}[] = [
    {kind: 'wind', cost: taken.wind}, {kind: 'seas', cost: taken.seas},
    {kind: 'chop', cost: taken.chop + taken.short}, {kind: 'cross', cost: taken.crossing},
  ];
  return list.filter(c => c.cost > 0).sort((a, b) => b.cost - a.cost);
}

function phrase(kind: Charge, r: ComfortRating, h: FeedHour): string {
  if (kind === 'wind') return `${r0(r.wind)} kt wind${r.gust !== null && r.gust >= r.wind + 3 ? ` gusting ${r0(r.gust)}` : ''}`;
  // The period is GFS-Wave's; name it only when its height is the one shown (WAM's period is not in the feed).
  if (kind === 'seas') return `${r1(r.sea)} ft seas${finite(h.sea_period) && finite(h.sea) && h.sea >= r.sea ? ` at ${r0(h.sea_period)} s` : ''}`;
  if (kind === 'chop') return `${r1(r.chop ?? 0)} ft of ${r.costs.short > 0 ? 'short, steep ' : ''}wind chop`;
  const from = compass(h.secondary_from);
  return `a ${r1(h.secondary ?? 0)} ft cross swell${from ? ` from the ${from}` : ''}`;
}

/** Said when the date's daylight hours have all passed. */
export const NO_DAYLIGHT = 'No daylight left on this day.';
/** Added to the limit sentence when the alert check is missing and the day is not held for it. */
export const NO_ALERT_CHECK = 'No current marine alert check.';

const heldSentence = (reasons: string[]): string | null => reasons.length ? `Held at Marginal: ${reasons.join('; ')}.` : null;

/** Hours of the bar estimate in the window that read hazardous, as "7 am". */
function barHazard(brief: Brief, hours: readonly number[], tz: string): string | null {
  const hit = (brief.bar?.hazardous ?? []).map(h => Date.parse(h.at)).filter(ms => hours.some(at => Math.abs(at - ms) < HOUR)).sort((a, b) => a - b)[0];
  return hit === undefined ? null : `the bar estimate reads hazardous at ${clockText(hit, tz)}`;
}

/** The first rated hour in the long-period swell rule (score.ts LONG_PERIOD_SWELL, which keeps it out of every window), named; the rougher model's seas count. */
export function longPeriodHour(rows: readonly {ms: number; hour: FeedHour}[], tz: string): string | null {
  for (const {ms, hour} of [...rows].sort((a, b) => a.ms - b.ms)) {
    const heights = [hour.sea, hour.other_sea].filter(finite), periods = [hour.sea_period, hour.swell_period].filter(finite).filter(p => p >= LONG_PERIOD_SWELL.period);
    const h = heights.length ? Math.max(...heights) : NaN;
    if (h >= LONG_PERIOD_SWELL.height && periods.length) return `long-period swell (${r1(h)} ft at ${r0(Math.max(...periods))} s) at ${clockText(ms, tz)}`;
  }
  return null;
}

/** The boat verdict from the comfort score over the regional forecast. */
export function boatVerdict(brief: Brief, forecast: ConditionsForecast | null, now: Date, tz: string): BriefVerdict {
  const unknown = (limit: string, window: string | null = null): BriefVerdict => ({verdict: 'unknown', limit, held: null, window, score: null, basis: 'comfort-score'});
  if (!forecast) return unknown('No forecast for this day yet.');
  const feed = feedReader(forecast, now);
  const {hours, label, covered} = windowHours(feed.times, brief.date, tz, brief.sunrise, brief.sunset, now);
  if (!hours.length) return unknown(covered ? NO_DAYLIGHT : feed.times.length ? 'The forecast does not reach this day yet.' : 'No forecast for this day yet.');
  const rows = hours.map(ms => ({ms, hour: feed.read(ms)})).map(row => ({...row, rating: rateComfort(row.hour)}));
  const rated = rows.filter((row): row is typeof row & {rating: ComfortRating} => row.rating !== null);
  if (!rated.length) return unknown('No wind and seas forecast for this window.', label);
  // The limit comes from the hour that rates worst before any cap, so a capped hour never names a charge it does not carry.
  const worst = rated.reduce((a, b) => b.rating.uncapped < a.rating.uncapped ? b : a);
  const score = Math.min(...rated.map(row => row.rating.score));
  const alert = brief.alerts[0];
  let verdict = alert ? 'rough' : FROM_SCORE[verdictFor({conditions: worst.rating.uncapped})];
  const list = charges(worst.rating);
  const at = clockText(worst.ms, tz);
  let limit: string;
  if (verdict === 'comfortable' || !list.length) {
    const wind = Math.max(...rated.map(row => row.rating.wind)), sea = Math.max(...rated.map(row => row.rating.sea));
    limit = `Wind to ${r0(wind)} kt and seas to ${r1(sea)} ft through ${label!.split('–')[1]}.`;
  } else {
    const [first, second] = list;
    limit = `${cap(phrase(first!.kind, worst.rating, worst.hour))} at ${at}${second && second.cost >= SECOND_COST ? `, with ${phrase(second.kind, worst.rating, worst.hour)}` : ''}.`;
  }
  if (alert) limit = `${alert.event} in effect. ${limit}`;
  const reasons: string[] = [];
  if (rated.some(row => row.rating.limited)) reasons.push('forecast detail is partial');
  if (rated.length < rows.length) reasons.push(`${rows.length - rated.length} of ${rows.length} hours have no forecast`);
  if (feed.oldestMs !== null && feed.oldestMs > RUN_STALE_MS) reasons.push(`the forecast run is ${Math.floor(feed.oldestMs / HOUR)} h old`);
  if (brief.missing.includes(ALERT_CHECK_MISSING)) reasons.push('the marine alert check is unavailable');
  const bar = barHazard(brief, hours, tz);
  if (bar) reasons.push(bar);
  const swell = longPeriodHour(rated, tz);
  if (swell) reasons.push(swell);
  const held = verdict === 'comfortable' && reasons.length ? heldSentence(reasons) : null;
  if (held) verdict = 'marginal';
  else if (!alert && brief.missing.includes(ALERT_CHECK_MISSING)) limit = `${limit} ${NO_ALERT_CHECK}`;
  // Under an alert the day is Rough whatever the hours score, so no score is shown.
  return {verdict, limit, held, window: label, score: alert ? null : score, basis: 'comfort-score'};
}

type GradedHour = {at: string; verdict: string; reasons: readonly string[]; surf?: {sneakerScore?: number}};
const GRADE: Readonly<Record<string, DayVerdict>> = {Calmer: 'comfortable', Marginal: 'marginal', Rough: 'rough'};
const RANK: Readonly<Record<DayVerdict, number>> = {comfortable: 0, marginal: 1, rough: 2, unknown: -1};

const band = (r: string) => { const w = r.split(/\s/)[0] ?? ''; return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase(); };
const pick = (table: Readonly<Record<string, number>>, key: string): number => table[key] ?? 0;

/**
 * What one reason string costs its hour, from the grader's own score table
 * (packages/coast kayak.ts KAYAK, shore-conditions.ts SHORE, spear.ts SPEAR).
 * Reasons that cap the hour at Rough on their own (kayak fog or darkness) cost
 * the most; bonuses (tide, dawn or dusk, near high tide) cost below zero and
 * are never named as a limit.
 */
export function reasonCost(profile: Exclude<Profile, 'boat'>, reason: string, hour: {surf?: {sneakerScore?: number}}): number {
  const r = reason.toLowerCase();
  if (profile === 'kayak') {
    if (r === 'fog alert' || r === 'outside daylight') return Infinity;
    if (/^\w+ wind\b/.test(r)) return pick(KAYAK.score.wind, band(reason)) + (r.endsWith(' offshore') ? (band(reason) === 'Light' ? KAYAK.offshore.lightPenalty : KAYAK.offshore.penalty) : 0);
    if (/^\w+ seas\b/.test(r)) return pick(KAYAK.score.seas, band(reason));
    if (r === 'short-period chop') return KAYAK.score.chop;
    if (r === 'surf at the launch') return KAYAK.launch.score;
    return 0;
  }
  if (profile === 'shore') {
    if (/^\w+ surf\b/.test(r)) return pick(SHORE.score.surf, band(reason));
    if (r === 'long-period swell') return hour.surf?.sneakerScore ?? 0;
    if (/^\w+ wind\b/.test(r)) return pick(SHORE.score.wind, band(reason)) + (r.endsWith(' onshore') && band(reason) !== 'Light' ? SHORE.score.onshore : 0);
    if (/tide$/.test(r)) return SHORE.score.tide;
    if (r === 'dawn or dusk') return SHORE.score.twilight;
    return 0;
  }
  if (/^\w+ surge\b/.test(r)) return pick(SPEAR.score.surge, band(reason));
  if (/^\w+ chop$/.test(r)) return pick(SPEAR.score.chop, band(reason));
  if (r.startsWith('clarity estimate ')) { const k = reason.slice('clarity estimate '.length); return pick(SPEAR.score.clarity, k.charAt(0).toUpperCase() + k.slice(1)); }
  if (r === 'clarity unknown') return SPEAR.score.clarity.Unknown;
  if (r === 'near high tide') return SPEAR.score.highTide;
  return 0;
}

/**
 * The reasons that limit a graded hour: those that cost it something, most costly first, at most
 * two. A calmer hour keeps the graders' order (it describes the hour; nothing limits it).
 */
export function limitReasons(profile: Exclude<Profile, 'boat'>, hour: {reasons: readonly string[]; surf?: {sneakerScore?: number}}, grade: DayVerdict): string[] {
  if (grade === 'comfortable') return hour.reasons.slice(0, 2);
  const costed = hour.reasons.map((r, i) => ({r, i, cost: reasonCost(profile, r, hour)})).filter(x => x.cost > 0);
  return costed.length ? costed.sort((a, b) => b.cost - a.cost || a.i - b.i).slice(0, 2).map(x => x.r) : hour.reasons.slice(0, 1);
}

/** The Shore, Spear or Kayak verdict from the profile's own hourly grader. */
export function profileVerdict(brief: Brief, now: Date, tz: string): BriefVerdict {
  const p = brief.profile as Exclude<Profile, 'boat'>;
  const graded: readonly GradedHour[] = (p === 'shore' ? brief.shore?.hours : p === 'spear' ? brief.spear?.hours : brief.kayak?.hours) ?? [];
  const byMs = new Map(graded.map(h => [Date.parse(h.at), h]));
  const {hours, label, covered} = windowHours([...byMs.keys()].filter(Number.isFinite), brief.date, tz, brief.sunrise, brief.sunset, now);
  const rows = hours.map(ms => ({ms, hour: byMs.get(ms)!, grade: GRADE[byMs.get(ms)!.verdict] ?? 'unknown' as DayVerdict}));
  const rated = rows.filter(row => row.grade !== 'unknown');
  if (!rated.length) return {verdict: 'unknown', limit: rows.length ? 'Wind or seas unknown for this window.' : covered ? NO_DAYLIGHT : 'No forecast for this day yet.', held: null, window: label, score: null, basis: p};
  const worst = rated.reduce((a, b) => RANK[b.grade] > RANK[a.grade] ? b : a);
  const alert = brief.alerts[0];
  let verdict: DayVerdict = alert ? 'rough' : worst.grade;
  const why = cap(limitReasons(p, worst.hour, worst.grade).join(', ') || VERDICT_WORD[worst.grade].toLowerCase());
  let limit = verdict === 'comfortable' ? `${why} through ${label!.split('–')[1]}.` : `${why} at ${clockText(worst.ms, tz)}.`;
  if (alert) limit = `${alert.event} in effect. ${limit}`;
  const reasons: string[] = [];
  if (rated.length < rows.length) reasons.push(`${rows.length - rated.length} of ${rows.length} hours are unknown`);
  if (brief.missing.includes(ALERT_CHECK_MISSING)) reasons.push('the marine alert check is unavailable');
  const held = verdict === 'comfortable' && reasons.length ? heldSentence(reasons) : null;
  if (held) verdict = 'marginal';
  else if (!alert && brief.missing.includes(ALERT_CHECK_MISSING)) limit = `${limit} ${NO_ALERT_CHECK}`;
  return {verdict, limit, held, window: label, score: null, basis: p};
}

/** The brief's verdict for its profile; null before there is a brief. */
export function briefVerdict(brief: Brief | null, forecast: ConditionsForecast | null, now: Date, tz: string): BriefVerdict | null {
  if (!brief) return null;
  return brief.profile === 'boat' ? boatVerdict(brief, forecast, now, tz) : profileVerdict(brief, now, tz);
}
