// The Boat brief's entrance current line (SC-TIDAL-1): flood, ebb or slack at the harbor entrance, when it turns, and the
// bar caution that adds the swell to the ebb. Words and the WCOFS read only; the arithmetic is packages/coast
// entrance-current.ts, and nothing here fetches anything: tide events and the bar hours come from the brief, the WCOFS
// sample from the regional forecast the brief already loaded (the same feed and the same forecast gate as the mark card,
// web/brief/mark-forecast.ts), so an old or absent forecast says so instead of being filled.
//
// Erasable syntax only: tests/test_entrance_current.mjs imports this file by type stripping.
import type {BarBand} from '../../packages/coast/src/bar-conditions.ts';
import {CURRENT, entranceReading, entranceTurns, offshoreFlow} from '../../packages/coast/src/entrance-current.ts';
import type {EntranceReading, OffshoreFlow, OffshoreSample} from '../../packages/coast/src/entrance-current.ts';
import type {ConditionsForecast} from '../conditions.ts';
import {forecastTime} from '../map/frames.ts';
import {localeOf, num, t} from '../i18n.ts';
import type {Language} from '../i18n.ts';
import type {Brief} from './types.ts';

const HOUR = 3_600_000;
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

type Feed = {retrieved?: unknown; currents?: {status?: unknown; source?: unknown; issued_at?: unknown; points?: unknown}};
/** A WCOFS sample that can be real: five finite numbers, speed of zero or more, a bearing in 0-360 (mark-forecast.ts possibleSample). */
const possible = (s: unknown): s is number[] => Array.isArray(s) && s.length >= 5 && s.slice(0, 5).every(finite) && s[3]! >= 0 && s[4]! >= 0 && s[4]! <= 360;

export type OffshoreRead = {sample: OffshoreSample | null; gap: 'status' | 'old' | 'none' | null};

/**
 * The WCOFS sample at the regional forecast point nearest the hour `at` (epoch ms), through the forecast gate (a run at most 36 h old, a feed
 * retrieved at most 6 h ago, a listed hour within 90 minutes of `at`). Never interpolated; a gap says which part failed.
 */
export function offshoreRead(forecast: ConditionsForecast | null, region: string | null, at: number, now: number): OffshoreRead {
  const feed = forecast && region && forecast.region === region ? forecast.feed as Feed | undefined : undefined;
  const c = feed?.currents;
  if (!feed || !c || c.status !== 'ok' || c.source !== 'wcofs' || !Array.isArray(c.points)) return {sample: null, gap: 'status'};
  const issued = typeof c.issued_at === 'string' ? Date.parse(c.issued_at) : NaN;
  const row = (c.points as unknown[]).find(p => (p as {point_id?: unknown})?.point_id === forecast!.point.id) as {samples?: unknown} | undefined;
  const samples = (Array.isArray(row?.samples) ? row.samples : []).filter(possible);
  const hr = forecastTime([...new Set(samples.map(s => s[0]! * 1000))].sort((a, b) => a - b), issued, finite(feed.retrieved) ? feed.retrieved : NaN, new Date(at), new Date(now));
  if (hr === null) return {sample: null, gap: 'old'};
  const s = samples.find(x => x[0]! * 1000 === hr);
  return s ? {sample: {speedKn: s[3]!, towardDeg: s[4]!, validAt: hr}, gap: null} : {sample: null, gap: 'none'};
}

/** "8 am", "8:25 am" in the region's zone (Spanish: the locale's own clock). */
export const clockText = (ms: number, tz: string, lang: Language | string = 'en'): string =>
  new Intl.DateTimeFormat(localeOf(lang), {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(ms)).replace(':00', '').toLowerCase();

const BAND_ID: Readonly<Record<BarBand, 'tile.detail.bar.clear' | 'tile.detail.bar.caution' | 'tile.detail.bar.hazardous' | 'tile.detail.bar.unknown'>> =
  {'No bar flag': 'tile.detail.bar.clear', Caution: 'tile.detail.bar.caution', Hazardous: 'tile.detail.bar.hazardous', Unknown: 'tile.detail.bar.unknown'};

export interface EntranceCurrentView {
  readonly name: string;
  readonly title: string;
  /** Flood, ebb or slack and the turn, or why it is not judged. */
  readonly timing: string;
  /** The turns of the day's window, or ''. */
  readonly turns: string;
  /** Ebb with swell: the bar band, never calmer than the worst source. */
  readonly caution: string;
  readonly band: BarBand;
  /** Why the caution is higher than the bar hour's own (WCOFS ebb), or ''. */
  readonly why: string;
  /** What the WCOFS forecast says, or why it is missing. */
  readonly wcofs: string;
  readonly basis: string;
  readonly foot: string;
  readonly reading: EntranceReading;
}

export interface ViewInput {brief: Brief; forecast: ConditionsForecast | null; region: string | null; tz: string; now: Date; lang?: Language | string}

/**
 * The line for a Boat brief at a regulated bar, at `now` when it falls inside the brief's bar hours and otherwise at the first hour
 * (named, so a future day never reads as now); null when the brief has no bar.
 */
export function entranceCurrentView({brief, forecast, region, tz, now, lang = 'en'}: ViewInput): EntranceCurrentView | null {
  const bar = brief.bar;
  if (!bar) return null;
  const times = bar.hours.map(h => Date.parse(h.at)).filter(finite);
  const title = t('entrance.title', lang, {name: bar.entrance.name}), foot = t('entrance.foot', lang);
  const tideTile = brief.tiles.find(x => x.id === 'tide'), swellTile = brief.tiles.find(x => x.id === 'swell');
  const station = tideTile?.source && tideTile.source !== 'No source' ? tideTile.source : t('entrance.station', lang);
  const basis = t('entrance.basis', lang, {station, min: CURRENT.slackMin});
  const start = times.length ? Math.min(...times) : NaN, end = times.length ? Math.max(...times) + HOUR : NaN;
  if (!times.length) {
    const reading = entranceReading({at: now.getTime(), entrance: bar.entrance, tideEvents: [], tideFresh: false, swellFresh: false, barHour: null, offshore: {kind: 'missing', reason: 'none'}});
    return {name: bar.entrance.name, title, timing: t('run.entrance.noHours', lang), turns: '', caution: t('entrance.caution.noSwell', lang), band: reading.band, why: '', wcofs: '', basis, foot, reading};
  }
  const nowMs = now.getTime(), isNow = nowMs >= start && nowMs < end, at = isNow ? nowMs : start;
  const barHour = bar.hours.find(h => { const x = Date.parse(h.at); return at >= x && at < x + HOUR; }) ?? null;
  const tideFresh = tideTile?.state === 'fresh', swellFresh = swellTile?.state === 'fresh';
  const read = offshoreRead(forecast, region, at, nowMs);
  const offshore: OffshoreFlow = offshoreFlow(read.sample, bar.entrance, read.gap ?? 'none');
  const reading = entranceReading({at, entrance: bar.entrance, tideEvents: brief.tideEvents, tideFresh, swellFresh, barHour, offshore});
  const clock = (ms: number) => clockText(ms, tz, lang), lead = isNow ? '' : t('entrance.forHour', lang, {time: clock(at)});

  const tm = reading.timing;
  const timing = lead + (tm.state === 'unknown' ? t(tm.reason === 'stale-tide' ? 'entrance.staleTide' : 'entrance.noTide', lang)
    : t(tm.phase === 'slack' ? `entrance.slack.${tm.turnsTo}` as const : tm.phase === 'ebb' ? 'entrance.ebb' : 'entrance.flood', lang,
      {turn: clock(tm.turnAt), from: clock(tm.slackFrom), until: clock(tm.slackUntil)}));
  const list = tideFresh ? entranceTurns(brief.tideEvents, start, end).map(e => t(e.type === 'H' ? 'entrance.turn.H' : 'entrance.turn.L', lang, {time: clock(e.at)})) : [];
  const turns = list.length ? t('entrance.turns', lang, {list: list.join('; ')}) : '';

  const swellText = reading.swellFt === null ? '' : reading.periodS === null ? t('entrance.swell', lang, {height: num(reading.swellFt, lang, 1)})
    : t('entrance.swell.period', lang, {height: num(reading.swellFt, lang, 1), period: num(reading.periodS, lang, 0)});
  const band = t(BAND_ID[reading.band], lang);
  // A retained Hazardous reading stays in words beside the stale warning (stale data never reads calmer than the worst source).
  const flowText = t(reading.flow === 'ebb' ? 'entrance.caution.ebb' : reading.flow === 'flood' ? 'entrance.caution.flood' : tm.state === 'ok' ? 'entrance.caution.slack' : 'entrance.caution.unknown', lang, {swell: swellText, band});
  const caution = reading.why.includes('swell-stale') ? (swellText && reading.band === 'Hazardous' ? `${flowText} ${t('entrance.caution.staleNote', lang)}` : t('entrance.caution.staleSwell', lang))
    : reading.why.includes('swell-missing') || !swellText ? t('entrance.caution.noSwell', lang)
    : flowText;
  const whyId = reading.why.includes('wcofs-ebb') ? 'entrance.why.wcofsEbb' : reading.why.includes('wcofs-missing') ? 'entrance.why.wcofsMissing' : reading.why.includes('slack-ebb') ? 'entrance.why.slackEbb' : null;
  const why = whyId ? t(whyId, lang) : '';

  const kn = offshore.kind === 'missing' ? '' : num(offshore.speedKn, lang, 1), deg = offshore.kind === 'missing' ? '' : num(Math.round(offshore.towardDeg), lang, 0);
  const wcofs = offshore.kind === 'missing' ? t('entrance.wcofs.missing', lang, {why: t(`entrance.gap.${read.gap ?? 'none'}` as const, lang)})
    : t(`entrance.wcofs.${offshore.kind}` as const, lang, {kn, deg});
  return {name: bar.entrance.name, title, timing, turns, caution, band: reading.band, why, wcofs, basis, foot, reading};
}
