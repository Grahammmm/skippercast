// Shore-fishing conditions (issue #542): surf, wind direction, tide phase and
// daylight scored per forecast hour into a verdict, rolled up per day for the
// daily brief.
//
// Every threshold lives in SHORE below with the reasoning behind it. They are
// coarse screening rules for an angler on a sandy beach or low rocks, not
// measurements and not a promise that a beach is safe. A Calmer hour is only
// calmer than the others: breaking surf, access and water quality still need a
// look at the exact beach.
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {Area, ForecastHour, TideEvent, TidePoint} from './types.ts';
import type {NearshoreHour, NearshoreSite} from './enrichment-types.ts';
import {nearshoreAt} from './nearshore.ts';

const HOUR = 3_600_000;
const MINUTE = 60_000;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
/** A usable wave/swell period: finite and above 0 s; anything else is missing. */
const period = (value: unknown): value is number => finite(value) && value > 0;
const round = (value: number, digits = 1) => Number(value.toFixed(digits));
/** A tide, sunrise or sunset time as epoch ms; NaN (unknown) without a `Z` or `±HH:MM` offset, which Date.parse would read as device-local time. */
const instant = (s: unknown): number =>
  typeof s === 'string' && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,3})?)?(Z|[+-]\d{2}:\d{2})$/.test(s) ? Date.parse(s) : NaN;

/**
 * The shore thresholds. Units: feet, seconds, knots, degrees, minutes, feet
 * above the tide station's datum (MLLW).
 */
export const SHORE = {
  surf: {
    /**
     * Upper bounds (exclusive) of Small, Moderate and Large in significant
     * height. Nearshore: a CDIP MOP model point in about 15 m of water, close
     * to what reaches the beach. Most surf fishing is comfortable below 3 ft
     * and workable to 5 ft; past 8 ft the beach itself is the hazard.
     */
    nearshore: {small: 3, moderate: 5, large: 8},
    /**
     * Offshore estimate: the regional forecast's combined seas, always
     * labelled "offshore estimate". Offshore seas overstate the surf at
     * sheltered beaches and understate it at exposed ones, so no single scale
     * fits; these sit a little above the nearshore bands so that typical
     * Central Coast seas (4 to 7 ft) read Moderate to Large, not always Heavy.
     */
    offshore: {small: 3, moderate: 6, large: 9},
  },
  /**
   * Long-period swell carries more energy for its height and arrives in sets
   * that run far up the beach after quiet minutes (sneaker waves). From `fromS`
   * seconds with at least `minFt` of that swell, the hour carries a caution
   * and the score rises; the hour is never Calmer.
   */
  sneaker: {minFt: 1.5, steps: [{fromS: 17, score: 2.5}, {fromS: 14, score: 1.5}]},
  wind: {
    /** Speed bands on sustained wind and gust: Light up to `light`, Breezy up to `breezy`, Strong beyond. */
    light: {wind: 10, gust: 15},
    breezy: {wind: 15, gust: 22},
    /**
     * Onshore: wind blowing from within `onshoreDeg` of the shoreline's
     * seaward bearing (`seawardDeg` below); offshore:
     * from within `offshoreDeg` of the landward bearing. Between them is
     * cross-shore. Onshore wind builds chop on the surf and blows line and
     * spray back at the angler, so a Breezy or Strong onshore hour scores worse.
     */
    onshoreDeg: 60,
    offshoreDeg: 60,
    /**
     * Vetted seaward bearings (degrees true, the direction the beach faces),
     * keyed by county id then area id. Each is the approximate orientation of
     * the coastline read from a chart (NOAA chart 18700), not a survey, and
     * holds only for the open beaches of that stretch. An area missing here
     * gets no wind side: speed only, and the brief says so. The area's
     * forecast point and NWS lookup point (lat/lon, landLat/landLon) are not
     * a shoreline direction and are never used for this.
     */
    seawardDeg: {
      slo: {
        // Morro Strand and the beaches either side of Morro Rock run roughly
        // north-south and face a little south of west.
        central: 260,
        // Cambria to San Simeon the coast runs northwest-southeast, so the
        // beaches face southwest; a northwest wind blows along the shore.
        north: 230,
        // south omitted: Avila faces south and Pismo faces west, so one
        // bearing would be wrong for half the area.
      },
    } as Readonly<Record<string, Readonly<Record<string, number>>>>,
  },
  tide: {
    /**
     * A common surf angler rule of thumb, not a guarantee: the rising tide and
     * the two hours around high (an hour either side) push water and food up
     * the beach. Scored as a mild bonus.
     */
    highMinutes: 60,
    /**
     * Predicted height at or below this reads as a very low tide: rocks and
     * reef are exposed and the incoming water can cut off a way back. A caution
     * for rock access; not scored.
     */
    veryLowFt: 0,
  },
  /** Within this many minutes of sunrise or sunset: a mild dawn or dusk bonus (low light, many fish feed closer in). */
  twilightMinutes: 60,
  /** Verdict score: lower is calmer. Calmer up to `calmer`, Marginal up to `marginal`, Rough above. */
  score: {
    surf: {Small: 0, Moderate: 1, Large: 4, Heavy: 6},
    wind: {Light: 0, Breezy: 1, Strong: 3},
    onshore: 0.75,
    tide: -0.5,
    twilight: -0.25,
    calmer: 1,
    marginal: 3,
  },
  /** Shore windows from a nearshore model allow surf up to this band, with no long-period caution. */
  windowMaxSurf: 'Moderate',
} as const;

export type SurfBand = 'Small' | 'Moderate' | 'Large' | 'Heavy' | 'Unknown';
export type WindBand = 'Light' | 'Breezy' | 'Strong' | 'Unknown';
export type WindSide = 'onshore' | 'offshore' | 'cross-shore' | null;
export type TidePhase = 'rising' | 'falling' | 'high' | 'low' | null;
export type ShoreVerdict = 'Calmer' | 'Marginal' | 'Rough' | 'Unknown';

export const SURF_RANK: Readonly<Record<SurfBand, number>> = {Small: 0, Moderate: 1, Large: 2, Heavy: 3, Unknown: 4};

export type Surf = {band: SurfBand; heightFt: number | null; periodS: number | null; basis: 'nearshore' | 'offshore' | null;
  /** The longest period carrying at least SHORE.sneaker.minFt, or null. */
  longPeriodS: number | null; sneaker: boolean; sneakerScore: number};
export type ShoreWind = {band: WindBand; side: WindSide; windKnots: number | null; gustKnots: number | null; directionDeg: number | null};
export type Tide = {phase: TidePhase; heightFt: number | null; veryLow: boolean; bonus: boolean};
export type ShoreHour = {at: string; surf: Surf; wind: ShoreWind; tide: Tide; twilight: boolean; verdict: ShoreVerdict; score: number | null; reasons: string[]; cautions: string[]};

function band(heightFt: number, basis: 'nearshore' | 'offshore'): Exclude<SurfBand, 'Unknown'> {
  const t = SHORE.surf[basis];
  return heightFt < t.small ? 'Small' : heightFt < t.moderate ? 'Moderate' : heightFt < t.large ? 'Large' : 'Heavy';
}

/** The sneaker step for a long period, or 0. */
export function sneakerScore(periodS: number | null): number {
  if (!finite(periodS)) return 0;
  return SHORE.sneaker.steps.find(step => periodS >= step.fromS)?.score ?? 0;
}

/**
 * Surf at one hour. A fresh nearshore model sample wins; otherwise the
 * offshore forecast's combined seas are an estimate against the lower
 * offshore bands. The long-period check reads every component with enough
 * height, including the offshore swell partition on the nearshore path.
 */
export function surf(hour: ForecastHour | undefined, near?: NearshoreHour): Surf {
  const {minFt} = SHORE.sneaker;
  const longest = (pairs: [number | null | undefined, number | null | undefined][]) => {
    const periods = pairs.filter(([h, p]) => finite(h) && h >= minFt && period(p)).map(([, p]) => p as number);
    return periods.length ? Math.max(...periods) : null;
  };
  const done = (b: SurfBand, heightFt: number | null, periodS: number | null, basis: Surf['basis'], longPeriodS: number | null): Surf => {
    const score = sneakerScore(longPeriodS);
    return {band: b, heightFt, periodS, basis, longPeriodS, sneaker: score > 0, sneakerScore: score};
  };
  if (near && finite(near.waveFt) && near.waveFt >= 0) {
    // The nearshore peak period can be a short local sea while a long-period
    // swell runs underneath; the offshore swell partition still raises the caution.
    return done(band(near.waveFt, 'nearshore'), near.waveFt, period(near.periodS) ? near.periodS : null, 'nearshore', longest([[near.waveFt, near.periodS], [hour?.swellFt, hour?.swellPeriodS]]));
  }
  const height = finite(hour?.waveFt) && hour.waveFt >= 0 ? hour.waveFt : null;
  if (height === null) return done('Unknown', null, null, null, longest([[hour?.swellFt, hour?.swellPeriodS]]));
  return done(band(height, 'offshore'), height, period(hour?.wavePeriodS) ? hour.wavePeriodS : null, 'offshore', longest([[hour?.waveFt, hour?.wavePeriodS], [hour?.swellFt, hour?.swellPeriodS]]));
}

/** The vetted seaward bearing for a county's area (SHORE.wind.seawardDeg), or null when that stretch has none. */
export function seaward(countyId: string | undefined, areaId: string | undefined): number | null {
  // finite() also rejects inherited keys such as "constructor".
  const value = countyId && areaId ? SHORE.wind.seawardDeg[countyId]?.[areaId] : undefined;
  return finite(value) ? value : null;
}

const angle = (a: number, b: number) => Math.abs((((a - b) % 360) + 540) % 360 - 180);

/** Wind band from speed, and the side it blows from when its direction and the shoreline's bearing are known. */
export function shoreWind(hour: Pick<ForecastHour, 'windKnots' | 'gustKnots' | 'windDirectionDeg'> | undefined, seawardDeg: number | null): ShoreWind {
  const wind = finite(hour?.windKnots) ? hour.windKnots : null, gust = finite(hour?.gustKnots) ? hour.gustKnots : null;
  const directionDeg = finite(hour?.windDirectionDeg) ? hour.windDirectionDeg : null;
  if (wind === null) return {band: 'Unknown', side: null, windKnots: null, gustKnots: gust, directionDeg};
  const g = gust ?? wind, {light, breezy, onshoreDeg, offshoreDeg} = SHORE.wind;
  const b: WindBand = wind <= light.wind && g <= light.gust ? 'Light' : wind <= breezy.wind && g <= breezy.gust ? 'Breezy' : 'Strong';
  let side: WindSide = null;
  if (directionDeg !== null && seawardDeg !== null) {
    const off = angle(directionDeg, seawardDeg);
    side = off <= onshoreDeg ? 'onshore' : off >= 180 - offshoreDeg ? 'offshore' : 'cross-shore';
  }
  return {band: b, side, windKnots: wind, gustKnots: gust, directionDeg};
}

/** A plain object, not null or an array, so its fields can be read. */
const plain = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);

/** Predicted tide height at `at` from the curve (nearest well-formed point within an hour), or null. */
function heightAt(at: number, curve: readonly TidePoint[]): number | null {
  let best: TidePoint | undefined, gap = Infinity;
  for (const point of curve as readonly unknown[]) {
    const d = plain(point) && finite(point.heightFt) ? Math.abs(instant(point.at) - at) : NaN;
    if (Number.isFinite(d) && d < gap) {best = point as TidePoint; gap = d;}
  }
  return best && gap <= HOUR ? best.heightFt : null;
}

/** Well-formed high/low events sorted by time; a time listed as both a high and a low becomes one null-type (unknown) boundary. */
function cleanEvents(events: readonly TideEvent[]) {
  const groups = new Map<number, {at: string; heightFt: unknown; type: 'H' | 'L' | null}>();
  for (const e of events as readonly unknown[]) {
    const time = plain(e) && (e.type === 'H' || e.type === 'L') ? instant(e.at) : NaN;
    if (!Number.isFinite(time)) continue;
    const seen = groups.get(time), event = e as TideEvent;
    if (!seen) groups.set(time, {at: event.at, heightFt: event.heightFt, type: event.type});
    else if (seen.type !== event.type) seen.type = null;
  }
  return [...groups].sort(([a], [b]) => a - b).map(([, e]) => e);
}

/**
 * Tide phase from the high and low events around `at`: high within
 * SHORE.tide.highMinutes of a high; otherwise rising before a high and falling
 * before a low; low within the same span of a low. Null without events on both sides,
 * or when a time listed as both a high and a low is within that span or either side.
 */
export function tidePhase(at: number, events: readonly TideEvent[], curve: readonly TidePoint[] = []): Tide {
  const sorted = cleanEvents(events);
  const span = SHORE.tide.highMinutes * MINUTE;
  const near = (type: 'H' | 'L' | null) => sorted.find(e => e.type === type && Math.abs(instant(e.at) - at) <= span);
  const nextEvent = sorted.find(e => instant(e.at) > at), previous = [...sorted].reverse().find(e => instant(e.at) <= at);
  const high = near('H'), low = near('L'), conflict = near(null) || nextEvent?.type === null || previous?.type === null;
  const phase: TidePhase = conflict ? null : high ? 'high' : low ? 'low' : nextEvent && previous ? (nextEvent.type === 'H' ? 'rising' : 'falling') : null;
  const lowEvent = low && finite(low.heightFt) ? low.heightFt : null;
  const heightFt = heightAt(at, curve) ?? (phase === 'low' ? lowEvent : null);
  return {phase, heightFt, veryLow: heightFt !== null && heightFt <= SHORE.tide.veryLowFt, bonus: phase === 'rising' || phase === 'high'};
}

export function isTwilight(at: number, sunrise: string | null, sunset: string | null): boolean {
  const span = SHORE.twilightMinutes * MINUTE;
  return [sunrise, sunset].some(edge => {const t = instant(edge); return Number.isFinite(t) && Math.abs(at - t) <= span;});
}

const ft = (value: number) => `${round(value)} ft`;

/** The verdict from surf, wind, tide and light, with plain reasons and cautions. */
export function shoreVerdict(s: Surf, w: ShoreWind, t: Tide, twilight: boolean): {verdict: ShoreVerdict; score: number | null; reasons: string[]; cautions: string[]} {
  const reasons: string[] = [], cautions: string[] = [];
  if (s.sneaker) cautions.push(`Long-period swell (${s.longPeriodS} s): sneaker waves can run far up the beach without warning; stay off low rocks and keep the ocean in view`);
  if (t.veryLow) cautions.push(`Very low tide (${t.heightFt === null ? 'below datum' : ft(t.heightFt)}): wet rock and reef are exposed; watch your footing and the incoming water if you walk out`);
  if (s.band === 'Unknown') reasons.push('Surf height unknown');
  if (w.band === 'Unknown') reasons.push('Wind unknown');
  if (s.band === 'Unknown' || w.band === 'Unknown') return {verdict: 'Unknown', score: null, reasons, cautions};
  const {score: p} = SHORE;
  const onshore = w.side === 'onshore' && w.band !== 'Light';
  const score = p.surf[s.band] + s.sneakerScore + p.wind[w.band] + (onshore ? p.onshore : 0) + (t.bonus ? p.tide : 0) + (twilight ? p.twilight : 0);
  reasons.push(`${s.band} surf${s.heightFt !== null ? ` (${ft(s.heightFt)}${s.periodS !== null ? ` at ${s.periodS} s` : ''}${s.basis === 'offshore' ? ', offshore estimate' : ''})` : ''}`);
  if (s.sneaker) reasons.push('long-period swell');
  reasons.push(`${w.band.toLowerCase()} wind${w.side ? ` ${w.side}` : ''}`);
  if (t.phase === 'rising') reasons.push('rising tide');
  else if (t.phase === 'high') reasons.push('around high tide');
  else if (t.phase) reasons.push(`${t.phase} tide`);
  if (twilight) reasons.push('dawn or dusk');
  // Long-period swell never reads Calmer, whatever else is in its favour.
  const verdict: ShoreVerdict = score <= p.calmer && !s.sneaker ? 'Calmer' : score <= p.marginal ? 'Marginal' : 'Rough';
  return {verdict, score, reasons, cautions};
}

export type ShoreInputs = {
  hours: readonly ForecastHour[];
  site: NearshoreSite | undefined;
  /** The county and area ids that key SHORE.wind.seawardDeg; a regional place has none. */
  countyId?: string;
  area: Pick<Area, 'id'>;
  tideEvents: readonly TideEvent[];
  tides: readonly TidePoint[];
  sunrise: string | null;
  sunset: string | null;
};

/** The shore reading for each forecast hour. */
export function shoreHours(input: ShoreInputs): ShoreHour[] {
  const sea = seaward(input.countyId, input.area.id);
  return input.hours.map(hour => {
    const at = Date.parse(hour.at);
    const s = surf(hour, input.site ? nearshoreAt(input.site, hour.at) : undefined);
    const w = shoreWind(hour, sea);
    const t = tidePhase(at, input.tideEvents, input.tides);
    const twilight = isTwilight(at, input.sunrise, input.sunset);
    return {at: hour.at, surf: s, wind: w, tide: t, twilight, ...shoreVerdict(s, w, t, twilight)};
  });
}

/** Whether an hour's surf, judged from a nearshore model, fits a shore window; undefined when no nearshore sample judged it. */
export function surfWindowOk(s: Surf): boolean | undefined {
  if (s.basis !== 'nearshore') return undefined;
  return SURF_RANK[s.band] <= SURF_RANK[SHORE.windowMaxSurf] && !s.sneaker;
}

export type ShoreDay = {
  hours: ShoreHour[];
  /** Smallest and largest surf band over daylight hours (all hours when daylight is unknown). */
  surf: {min: SurfBand; max: SurfBand} | null;
  basis: 'nearshore' | 'offshore' | 'mixed' | null;
  /** The longest swell period that triggered the sneaker caution, or null. */
  sneakerPeriodS: number | null;
  /** The calmest daylight hour that is not Rough, earliest first on a tie. */
  best: ShoreHour | null;
  /** False when this stretch of coast has no vetted seaward bearing: every hour's wind is speed only. */
  bearingKnown: boolean;
  /** True when the bearing is known but the forecast gives no wind direction for some hour, so that hour's wind is speed only. */
  windSpeedOnly: boolean;
  /** True when no hour has a tide phase. */
  tideUnknown: boolean;
  /** Times of very low tide among those hours. */
  veryLow: ShoreHour[];
};

/** Roll the hours up for the day, over daylight when sunrise and sunset are known. */
export function shoreDay(hours: ShoreHour[], sunrise: string | null, sunset: string | null, seawardDeg: number | null): ShoreDay {
  const rise = instant(sunrise), set = instant(sunset);
  const lit = Number.isFinite(rise) && Number.isFinite(set) ? hours.filter(h => {const t = Date.parse(h.at); return t >= rise && t + HOUR <= set;}) : hours;
  const scope = lit.length ? lit : hours;
  const known = scope.filter(h => h.surf.band !== 'Unknown');
  const ranks = known.map(h => SURF_RANK[h.surf.band]);
  const bands = Object.keys(SURF_RANK) as SurfBand[];
  const surfRange = known.length ? {min: bands[Math.min(...ranks)]!, max: bands[Math.max(...ranks)]!} : null;
  const bases = new Set(known.map(h => h.surf.basis));
  const basis = !bases.size ? null : bases.size > 1 ? 'mixed' : (bases.has('nearshore') ? 'nearshore' : 'offshore');
  const sneakers = scope.filter(h => h.surf.sneaker).map(h => h.surf.longPeriodS as number);
  const best = scope.filter(h => h.verdict === 'Calmer' || h.verdict === 'Marginal')
    .sort((a, b) => (a.score as number) - (b.score as number) || Date.parse(a.at) - Date.parse(b.at))[0] ?? null;
  return {hours, surf: surfRange, basis, sneakerPeriodS: sneakers.length ? Math.max(...sneakers) : null, best, bearingKnown: seawardDeg !== null,
    windSpeedOnly: seawardDeg !== null && scope.some(h => h.wind.band !== 'Unknown' && h.wind.side === null),
    tideUnknown: !scope.some(h => h.tide.phase !== null), veryLow: scope.filter(h => h.tide.veryLow)};
}

/** "Small", "Small to moderate". */
export function surfText(range: {min: SurfBand; max: SurfBand}): string {
  return range.min === range.max ? range.min : `${range.min} to ${range.max.toLowerCase()}`;
}
