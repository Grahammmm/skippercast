// Kayak-fishing conditions (issue #542): wind, offshore drift, seas and chop,
// surf at the launch, daylight and fog alerts scored per forecast hour into a
// verdict, rolled up per day for the daily brief.
//
// Every threshold lives in KAYAK below with the reasoning behind it. They are
// coarse screening choices for a paddler fishing near the coast, not
// measurements and not a promise that the water is safe. A Calmer hour is only
// calmer than the others: the launch, the drift and the paddle back still need
// a local check.
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {Alert, ForecastHour} from './types.ts';
import type {NearshoreSite} from './enrichment-types.ts';
import {nearshoreAt} from './nearshore.ts';
import {SHORE, shoreWind, surf, type Surf, type WindSide} from './shore-conditions.ts';

const HOUR = 3_600_000;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const round = (value: number, digits = 1) => Number(value.toFixed(digits));

/** The kayak thresholds. Units: knots, feet, seconds. */
export const KAYAK = {
  /**
   * Wind is the main limit: a kayak drifts fast, and paddling back into wind
   * tires the angler long before the boat would notice. Bands on sustained
   * wind and gust (both must fit): Light up to `light`, Moderate up to
   * `moderate`, Fresh up to `fresh`, Strong beyond. Calmer needs Moderate or
   * less, so sustained 10 kt and gusts 15 kt at most: stricter than the boat
   * profile, a screening choice rather than a published limit.
   */
  wind: {light: {wind: 8, gust: 12}, moderate: {wind: 10, gust: 15}, fresh: {wind: 14, gust: 20}},
  /**
   * Offshore wind (blowing from the land out to sea) is the classic kayak
   * hazard: the water near shore looks flat while the wind carries the kayak
   * out and the paddle back is upwind. Read from the forecast direction
   * against the vetted shoreline bearing in SHORE.wind.seawardDeg; where that
   * stretch of coast has none, wind is judged on speed only and the brief says
   * so. Any offshore hour carries a caution and is capped at Marginal, so it
   * is never the calmest hour; above Light it scores `penalty`, which puts a
   * Moderate offshore hour past Marginal.
   */
  offshore: {penalty: 2.5, lightPenalty: 0.5},
  /**
   * Combined seas from the regional forecast (significant height): Small below
   * `small`, Moderate below `moderate`, Large below `large`, Heavy beyond.
   * Stricter than the boat's 4 ft window rule because a kayak sits a foot off
   * the water.
   */
  seas: {small: 2, moderate: 3, large: 4.5},
  /**
   * Short-period chop: seas of `minFt` or more at `maxPeriodS` seconds or
   * less are steep and slap a kayak around; scored on top of the seas band.
   */
  chop: {minFt: 2, maxPeriodS: 8},
  /**
   * Long-period swell matters mainly where the kayak launches and lands
   * through surf. The launch beach's surf comes from the shore estimate
   * (shore-conditions.ts `surf`: the fresh nearshore model, else the offshore
   * seas labelled an estimate); at or above the Small limit of its scale
   * (SHORE.surf, 3 ft on both) the hour carries a launch caution and scores
   * `score`.
   */
  launch: {score: 1.5},
  /**
   * Fog: the brief's inputs carry no visibility forecast, so the cap reuses
   * the marine alert check. An alert in force at the hour whose event matches
   * `alert` caps the hour at Rough: a kayak is hard to see, and landmarks for
   * the paddle back disappear.
   */
  fog: {alert: /fog|visibility|smoke/i},
  /** Verdict score: lower is calmer. Calmer up to `calmer`, Marginal up to `marginal`, Rough above. */
  score: {
    wind: {Light: 0, Moderate: 1, Fresh: 3, Strong: 6},
    seas: {Small: 0, Moderate: 1, Large: 3, Heavy: 6},
    chop: 1,
    calmer: 1,
    marginal: 3,
  },
} as const;

export type KayakWindBand = 'Light' | 'Moderate' | 'Fresh' | 'Strong' | 'Unknown';
export type SeasBand = 'Small' | 'Moderate' | 'Large' | 'Heavy' | 'Unknown';
export type KayakVerdict = 'Calmer' | 'Marginal' | 'Rough' | 'Unknown';

export const KAYAK_WIND_RANK: Readonly<Record<KayakWindBand, number>> = {Light: 0, Moderate: 1, Fresh: 2, Strong: 3, Unknown: 4};

export type KayakWind = {band: KayakWindBand; side: WindSide; windKnots: number | null; gustKnots: number | null};
export type KayakSeas = {band: SeasBand; heightFt: number | null; periodS: number | null; chop: boolean};
export type KayakHour = {
  at: string; wind: KayakWind; seas: KayakSeas; launch: Surf;
  /** Surf at the launch at or above the caution line. */
  launchCaution: boolean;
  /** False outside sunrise to an hour before sunset; null when sunrise or sunset is unknown. */
  daylight: boolean | null;
  fog: boolean;
  verdict: KayakVerdict; score: number | null; reasons: string[]; cautions: string[];
};

/** Wind band from sustained wind and gust, and the side it blows from where the shoreline bearing is known. */
export function kayakWind(hour: Pick<ForecastHour, 'windKnots' | 'gustKnots' | 'windDirectionDeg'> | undefined, seawardDeg: number | null): KayakWind {
  const side = shoreWind(hour, seawardDeg).side;
  const wind = finite(hour?.windKnots) ? hour.windKnots : null, gust = finite(hour?.gustKnots) ? hour.gustKnots : null;
  if (wind === null) return {band: 'Unknown', side: null, windKnots: null, gustKnots: gust};
  const g = gust ?? wind, {light, moderate, fresh} = KAYAK.wind;
  const band: KayakWindBand = wind <= light.wind && g <= light.gust ? 'Light' : wind <= moderate.wind && g <= moderate.gust ? 'Moderate'
    : wind <= fresh.wind && g <= fresh.gust ? 'Fresh' : 'Strong';
  return {band, side, windKnots: wind, gustKnots: gust};
}

/** Combined seas band and whether they are short-period chop. */
export function kayakSeas(hour: Pick<ForecastHour, 'waveFt' | 'wavePeriodS'> | undefined): KayakSeas {
  const height = finite(hour?.waveFt) && hour.waveFt >= 0 ? hour.waveFt : null;
  const period = finite(hour?.wavePeriodS) ? hour.wavePeriodS : null;
  if (height === null) return {band: 'Unknown', heightFt: null, periodS: period, chop: false};
  const {small, moderate, large} = KAYAK.seas;
  const band: SeasBand = height < small ? 'Small' : height < moderate ? 'Moderate' : height < large ? 'Large' : 'Heavy';
  return {band, heightFt: height, periodS: period, chop: period !== null && height >= KAYAK.chop.minFt && period <= KAYAK.chop.maxPeriodS};
}

/** Whether the launch surf reaches the caution line of its own scale. */
export function launchCaution(s: Surf): boolean {
  return s.basis !== null && s.heightFt !== null && s.heightFt >= SHORE.surf[s.basis].small;
}

/** Whether a fog or visibility alert is in force at `at`. */
export function fogAt(at: number, alerts: readonly Pick<Alert, 'event' | 'effective' | 'expires'>[]): boolean {
  return alerts.some(alert => {
    if (!KAYAK.fog.alert.test(alert.event)) return false;
    const from = alert.effective ? Date.parse(alert.effective) : -Infinity, to = alert.expires ? Date.parse(alert.expires) : Infinity;
    // Unreadable clocks count as in force, as the alert check does.
    return (Number.isNaN(from) || from <= at) && (Number.isNaN(to) || to > at);
  });
}

const ft = (value: number) => `${round(value)} ft`;

/** The verdict from wind, seas, launch surf, daylight and fog, with plain reasons and cautions. */
export function kayakVerdict(w: KayakWind, s: KayakSeas, launch: Surf, daylight: boolean | null, fog: boolean): {verdict: KayakVerdict; score: number | null; reasons: string[]; cautions: string[]} {
  const reasons: string[] = [], cautions: string[] = [];
  const offshore = w.side === 'offshore';
  const atLaunch = launchCaution(launch);
  if (offshore) cautions.push('Offshore wind: it carries a kayak away from shore and makes the paddle back upwind; stay close in or wait');
  if (atLaunch) cautions.push(`Surf at the launch (${ft(launch.heightFt as number)}${launch.basis === 'offshore' ? ', offshore estimate' : ''}): launching and landing through breaking waves can capsize a kayak; choose a sheltered launch`);
  if (atLaunch && launch.sneaker) cautions.push(`Long-period swell (${launch.longPeriodS} s): sets can break bigger than the average at the launch`);
  if (fog) cautions.push('Fog or visibility alert: a kayak is hard to see and landmarks for the paddle back disappear');
  if (daylight === false) cautions.push('Outside daylight: a kayak needs daylight to be seen and to see the way back');
  if (w.band === 'Unknown') reasons.push('Wind unknown');
  if (s.band === 'Unknown') reasons.push('Seas unknown');
  if (w.band === 'Unknown' || s.band === 'Unknown') return {verdict: 'Unknown', score: null, reasons, cautions};
  const {score: p} = KAYAK;
  const score = p.wind[w.band] + (offshore ? (w.band === 'Light' ? KAYAK.offshore.lightPenalty : KAYAK.offshore.penalty) : 0)
    + p.seas[s.band] + (s.chop ? p.chop : 0) + (atLaunch ? KAYAK.launch.score : 0);
  reasons.push(`${w.band.toLowerCase()} wind${w.windKnots !== null ? ` (${round(w.windKnots)} kt${w.gustKnots !== null ? `, gust ${round(w.gustKnots)}` : ''})` : ''}${w.side ? ` ${w.side}` : ''}`);
  reasons.push(`${s.band.toLowerCase()} seas (${ft(s.heightFt as number)}${s.periodS !== null ? ` at ${s.periodS} s` : ''})`);
  if (s.chop) reasons.push('short-period chop');
  if (atLaunch) reasons.push('surf at the launch');
  if (fog) reasons.push('fog alert');
  if (daylight === false) reasons.push('outside daylight');
  // Fog and darkness cap the hour at Rough, whatever the wind and seas; offshore wind of any strength caps it at Marginal.
  const verdict: KayakVerdict = fog || daylight === false ? 'Rough' : score <= p.calmer && !offshore ? 'Calmer' : score <= p.marginal ? 'Marginal' : 'Rough';
  return {verdict, score, reasons, cautions};
}

export type KayakInputs = {
  hours: readonly ForecastHour[];
  /** The fresh nearshore model site for the launch beach's surf, if any. */
  site: NearshoreSite | undefined;
  /** The vetted shoreline bearing (shore-conditions.ts `seaward`), or null. */
  seawardDeg: number | null;
  alerts: readonly Pick<Alert, 'event' | 'effective' | 'expires'>[];
  sunrise: string | null;
  sunset: string | null;
};

/** The kayak reading for each forecast hour. */
export function kayakHours(input: KayakInputs): KayakHour[] {
  const rise = input.sunrise ? Date.parse(input.sunrise) : NaN, set = input.sunset ? Date.parse(input.sunset) : NaN;
  const known = Number.isFinite(rise) && Number.isFinite(set);
  return input.hours.map(hour => {
    const at = Date.parse(hour.at);
    const w = kayakWind(hour, input.seawardDeg), s = kayakSeas(hour);
    const launch = surf(hour, input.site ? nearshoreAt(input.site, hour.at) : undefined);
    const daylight = known ? at >= rise && at + HOUR <= set : null;
    const fog = fogAt(at, input.alerts);
    return {at: hour.at, wind: w, seas: s, launch, launchCaution: launchCaution(launch), daylight, fog, ...kayakVerdict(w, s, launch, daylight, fog)};
  });
}

/** Whether an hour fits a kayak window: not Rough, no offshore wind and no launch caution; undefined for hours the reading does not cover. */
export function kayakWindowOk(hour: KayakHour | undefined): boolean | undefined {
  if (!hour) return undefined;
  return hour.verdict !== 'Rough' && hour.verdict !== 'Unknown' && hour.wind.side !== 'offshore' && !hour.launchCaution;
}

export type KayakDay = {
  hours: KayakHour[];
  /** Lightest and strongest wind band over daylight hours (all hours when daylight is unknown). */
  wind: {min: KayakWindBand; max: KayakWindBand} | null;
  /** Daylight hours with offshore wind. */
  offshore: KayakHour[];
  /** Daylight hours with surf at the launch at or above the caution line. */
  launch: KayakHour[];
  /** Where the launch surf came from over those hours. */
  launchBasis: 'nearshore' | 'offshore' | 'mixed' | null;
  /** True when a fog or visibility alert covers any of those hours. */
  fog: boolean;
  /** True when some hour's seas are short-period chop. */
  chop: boolean;
  /** The calmest daylight hour that is not Rough and has no offshore wind, earliest first on a tie. */
  best: KayakHour | null;
  /** False when this stretch of coast has no vetted shoreline bearing: offshore wind cannot be told apart. */
  bearingKnown: boolean;
  /** True when the bearing is known but some hour has no wind direction. */
  windSpeedOnly: boolean;
  /** True when sunrise or sunset is unknown, so daylight was not checked. */
  daylightUnknown: boolean;
};

/** Roll the hours up for the day, over daylight when sunrise and sunset are known. */
export function kayakDay(hours: KayakHour[], seawardDeg: number | null): KayakDay {
  const daylightUnknown = hours.some(h => h.daylight === null);
  const lit = hours.filter(h => h.daylight !== false);
  const scope = lit.length ? lit : hours;
  const known = scope.filter(h => h.wind.band !== 'Unknown');
  const bands = Object.keys(KAYAK_WIND_RANK) as KayakWindBand[];
  const ranks = known.map(h => KAYAK_WIND_RANK[h.wind.band]);
  const launch = scope.filter(h => h.launchCaution);
  const bases = new Set(scope.map(h => h.launch.basis).filter(basis => basis !== null));
  const best = scope.filter(h => h.daylight !== false && h.wind.side !== 'offshore' && (h.verdict === 'Calmer' || h.verdict === 'Marginal'))
    .sort((a, b) => (a.score as number) - (b.score as number) || Date.parse(a.at) - Date.parse(b.at))[0] ?? null;
  return {
    hours, wind: known.length ? {min: bands[Math.min(...ranks)]!, max: bands[Math.max(...ranks)]!} : null,
    offshore: scope.filter(h => h.wind.side === 'offshore'), launch,
    launchBasis: !bases.size ? null : bases.size > 1 ? 'mixed' : bases.has('nearshore') ? 'nearshore' : 'offshore',
    fog: scope.some(h => h.fog), chop: scope.some(h => h.seas.chop), best, bearingKnown: seawardDeg !== null,
    windSpeedOnly: seawardDeg !== null && scope.some(h => h.wind.band !== 'Unknown' && h.wind.side === null), daylightUnknown,
  };
}

/** "Light", "Light to fresh". */
export function kayakWindText(range: {min: KayakWindBand; max: KayakWindBand}): string {
  return range.min === range.max ? range.min : `${range.min} to ${range.max.toLowerCase()}`;
}
