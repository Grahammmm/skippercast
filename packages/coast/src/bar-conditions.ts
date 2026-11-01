// Harbour bar / entrance check for the boat brief (issue #542): tide phase,
// swell height and period, and wind against the ebb, read per forecast hour
// into a bar band, rolled up per day.
//
// Basis. 33 CFR 165.1196 (Regulated Navigation Areas; Harbor Entrances along
// the Coast of Northern California; a copy is in
// tests/fixtures/seafloor-security/165.1196.xml) names four regulated bars:
// Humboldt Bay, Noyo River, Crescent City Harbor and Morro Bay. The Coast
// Guard restricts or closes them using "sea state, winds, wave period, and
// tidal currents", and announces it on VHF-FM channels 16 and 22A. NOAA Coast
// Pilot 7 (California) warns of breakers at these entrances in heavy swell,
// and USCG bar-crossing guidance describes the mechanism used here: an ebb
// current running out against incoming swell steepens the waves and makes
// them break on the bar, worst near the strongest ebb, and long-period swell
// breaks there with little warning. The thresholds below are this module's
// own screening choices, not values from either source.
//
// This is a rough screening estimate from forecasts and tide predictions,
// not an official bar report. It never says a bar is safe: the best band is
// "No bar flag", and every reading tells the skipper to check the Coast
// Guard bar status or harbor patrol. Every threshold lives in BAR below with
// its reasoning; they are rules of thumb, not measurements at the bar.
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {ForecastHour, TideEvent} from './types.ts';
import type {NearshoreHour, NearshoreSite} from './enrichment-types.ts';
import {nearshoreAt} from './nearshore.ts';

const HOUR = 3_600_000;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const round = (value: number, digits = 1) => Number(value.toFixed(digits));

export type Entrance = {
  /** Display name, e.g. "Morro Bay entrance". */
  name: string;
  /**
   * The direction the entrance opens to sea (degrees true), or null when
   * there is none (Morro Bay's is a shoreline proxy, not a vetted channel bearing). Used only to tell when wind blows in against the
   * ebb; null means that driver is not judged and the brief says so.
   */
  seawardDeg: number | null;
};

/**
 * The bar thresholds. Units: feet (significant height), seconds, knots,
 * degrees, fractions of the high-to-low interval.
 */
export const BAR = {
  /**
   * The regulated bars of 33 CFR 165.1196, keyed by county id then area id.
   * The coast report keys Morro Bay as slo/central; regional briefs key a
   * region by its own id twice (web/brief/model.ts regionalReport). Only the
   * four bars the regulation names are here: no other port in the region
   * list gets a bar check.
   */
  entrances: {
    // Morro Bay: 260 is a shoreline proxy, not a vetted channel or entrance
    // bearing. It is the open-ocean side of Morro Strand (shore-conditions.ts
    // SHORE.wind.seawardDeg 260, read from NOAA chart 18700).
    slo: {central: {name: 'Morro Bay entrance', seawardDeg: 260}},
    'morro-bay': {'morro-bay': {name: 'Morro Bay entrance', seawardDeg: 260}},
    // The other three: no bearing, so wind against the ebb is not judged there.
    'humboldt-bay-cape-mendocino': {'humboldt-bay-cape-mendocino': {name: 'Humboldt Bay entrance', seawardDeg: null}},
    'fort-bragg-point-arena': {'fort-bragg-point-arena': {name: 'Noyo River entrance', seawardDeg: null}},
    'crescent-city': {'crescent-city': {name: 'Crescent City Harbor entrance', seawardDeg: null}},
  } as Readonly<Record<string, Readonly<Record<string, Entrance>>>>,
  /**
   * Swell height thresholds by basis. Nearshore: a CDIP MOP model point in
   * about 15 m of water, close to what reaches the entrance. Offshore: the
   * regional forecast's combined seas, labelled "offshore estimate"; set a
   * little higher because offshore seas are not the height on the bar.
   * - `ebbCaution`: on any ebb, swell from here is a caution (ebb steepening).
   * - `caution`: a caution on any tide; on the middle of the ebb, hazardous.
   * - `hazardous`: hazardous on any tide.
   * For scale, 33 CFR 165.1196 calls a bar unsafe for a vessel when the wave
   * height in the entrance reaches length/10 + freeboard (4 ft for a 20 ft
   * boat with 2 ft of freeboard).
   */
  swell: {
    nearshore: {ebbCaution: 2, caution: 4, hazardous: 8},
    offshore: {ebbCaution: 3, caution: 6, hazardous: 10},
  },
  /**
   * Long-period swell: from `fromS` seconds with at least `minFt` of that
   * swell, sets can break on the bar after quiet minutes. A caution on any
   * tide; with an ebb and swell from the `caution` height, hazardous.
   */
  longPeriod: {fromS: 14, minFt: 2},
  /**
   * The middle of the ebb, as a fraction of the time from high water to the
   * next low: the ebb current is usually strongest around mid-ebb. Tide
   * predictions are heights at a station, not currents at the entrance, so
   * this is a proxy and the brief says so.
   */
  midEbb: {from: 0.25, to: 0.75},
  /**
   * Wind against the ebb: wind from within `deg` of the entrance's seaward
   * bearing (blowing in, against the outgoing current) at `knots` or more
   * during an ebb. A caution, never hazardous on its own.
   */
  windAgainst: {deg: 60, knots: 10},
} as const;

export type BarBand = 'No bar flag' | 'Caution' | 'Hazardous' | 'Unknown';
export const BAR_RANK: Readonly<Record<BarBand, number>> = {'No bar flag': 0, Caution: 1, Unknown: 2, Hazardous: 3};

/** Where the hour sits in the tide: ebb (high to low), flood (low to high), or unknown without events either side. */
export type BarTide = {stage: 'ebb' | 'flood' | null; midEbb: boolean; fraction: number | null};
export type BarSwell = {heightFt: number | null; periodS: number | null; basis: 'nearshore' | 'offshore' | null;
  /** The longest period carrying at least BAR.longPeriod.minFt, or null. */
  longPeriodS: number | null};
export type BarHour = {at: string; band: BarBand; tide: BarTide; swell: BarSwell; windAgainst: boolean; reasons: string[]};

/** The regulated entrance for this county and area, or null. */
export function entranceFor(countyId: string | undefined, areaId: string | undefined): Entrance | null {
  // Object.hasOwn also rejects inherited keys such as "constructor".
  const county = countyId && Object.hasOwn(BAR.entrances, countyId) ? BAR.entrances[countyId] : undefined;
  return county && areaId && Object.hasOwn(county, areaId) ? county[areaId]! : null;
}

/** Ebb or flood from the high and low events either side of `at`, and whether it is mid-ebb. */
export function barTide(at: number, events: readonly TideEvent[]): BarTide {
  const unknown: BarTide = {stage: null, midEbb: false, fraction: null};
  if (!Number.isFinite(at)) return unknown;
  // Keep a conflicting timestamp as an unknown boundary, rather than dropping
  // it and inventing a wider bracket. Exact same-type duplicates can collapse.
  const groups = new Map<number, 'H' | 'L' | null>();
  for (const event of events) {
    if (!event || typeof event !== 'object' || Array.isArray(event) || typeof event.at !== 'string'
      || (event.type !== 'H' && event.type !== 'L')) continue;
    const time = Date.parse(event.at);
    if (!Number.isFinite(time)) continue;
    if (!groups.has(time)) groups.set(time, event.type);
    else if (groups.get(time) !== event.type) groups.set(time, null);
  }
  const sorted = [...groups].sort(([a], [b]) => a - b);
  const previous = [...sorted].reverse().find(([time]) => time <= at), next = sorted.find(([time]) => time > at);
  if (!previous || !next || previous[1] === null || next[1] === null || previous[1] === next[1]) return unknown;
  const fraction = (at - previous[0]) / (next[0] - previous[0]);
  const stage = previous[1] === 'H' ? 'ebb' : 'flood';
  return {stage, midEbb: stage === 'ebb' && fraction >= BAR.midEbb.from && fraction <= BAR.midEbb.to, fraction: round(fraction, 2)};
}

/** Swell at the hour: a fresh nearshore sample wins, else the offshore seas as an estimate. */
export function barSwell(hour: ForecastHour | undefined, near?: NearshoreHour): BarSwell {
  const {minFt} = BAR.longPeriod;
  const longest = (pairs: [number | null | undefined, number | null | undefined][]) => {
    const periods = pairs.filter(([h, p]) => finite(h) && h >= minFt && finite(p)).map(([, p]) => p as number);
    return periods.length ? Math.max(...periods) : null;
  };
  if (near && finite(near.waveFt) && near.waveFt >= 0) {
    return {heightFt: near.waveFt, periodS: finite(near.periodS) ? near.periodS : null, basis: 'nearshore', longPeriodS: longest([[near.waveFt, near.periodS], [hour?.swellFt, hour?.swellPeriodS]])};
  }
  const height = finite(hour?.waveFt) && hour.waveFt >= 0 ? hour.waveFt : null;
  const longPeriodS = longest([[hour?.waveFt, hour?.wavePeriodS], [hour?.swellFt, hour?.swellPeriodS]]);
  if (height === null) return {heightFt: null, periodS: null, basis: null, longPeriodS};
  return {heightFt: height, periodS: finite(hour?.wavePeriodS) ? hour.wavePeriodS : null, basis: 'offshore', longPeriodS};
}

const angle = (a: number, b: number) => Math.abs((((a - b) % 360) + 540) % 360 - 180);

/** Wind blowing in against the outgoing ebb, strong enough to count; false when the bearing or direction is unknown. */
export function windAgainstEbb(hour: Pick<ForecastHour, 'windKnots' | 'windDirectionDeg'> | undefined, tide: BarTide, seawardDeg: number | null): boolean {
  const {deg, knots} = BAR.windAgainst;
  return tide.stage === 'ebb' && seawardDeg !== null && finite(hour?.windKnots) && hour.windKnots >= knots
    && finite(hour?.windDirectionDeg) && angle(hour.windDirectionDeg, seawardDeg) <= deg;
}

const ft = (value: number) => `${round(value)} ft`;

/** The bar band from tide, swell and wind, with plain reasons. Never better than "No bar flag". */
export function barBand(tide: BarTide, swell: BarSwell, windAgainst: boolean): {band: BarBand; reasons: string[]} {
  const reasons: string[] = [];
  const tideText = tide.stage === 'ebb' ? (tide.midEbb ? 'mid-ebb' : 'ebb') : tide.stage === 'flood' ? 'flood' : null;
  if (swell.heightFt === null || swell.basis === null) {
    reasons.push('Swell unknown');
    if (!tideText) reasons.push('tide phase unknown');
    return {band: 'Unknown', reasons};
  }
  const t = BAR.swell[swell.basis], h = swell.heightFt;
  const long = swell.longPeriodS !== null && swell.longPeriodS >= BAR.longPeriod.fromS;
  const ebb = tide.stage === 'ebb';
  reasons.push(`${ft(h)}${swell.periodS !== null ? ` at ${swell.periodS} s` : ''} swell${swell.basis === 'offshore' ? ' (offshore estimate)' : ''}`);
  if (long) reasons.push(`long-period swell (${swell.longPeriodS} s)`);
  reasons.push(tideText ? `${tideText} tide` : 'tide phase unknown');
  if (windAgainst) reasons.push('wind blowing in against the ebb');
  const hazardous = h >= t.hazardous || (tide.midEbb && h >= t.caution) || (ebb && long && h >= t.caution);
  if (hazardous) return {band: 'Hazardous', reasons};
  const caution = h >= t.caution || (ebb && h >= t.ebbCaution) || long || windAgainst || (tide.stage === null && h >= t.ebbCaution);
  if (caution) return {band: 'Caution', reasons};
  // Small swell but no tide phase: the ebb cannot be ruled out, so no "No bar flag".
  return {band: tide.stage === null ? 'Unknown' : 'No bar flag', reasons};
}

export type BarInputs = {
  hours: readonly ForecastHour[];
  site: NearshoreSite | undefined;
  entrance: Entrance;
  tideEvents: readonly TideEvent[];
};

/** The bar reading for each forecast hour. */
export function barHours(input: BarInputs): BarHour[] {
  return input.hours.map(hour => {
    const at = Date.parse(hour.at);
    const tide = barTide(at, input.tideEvents);
    const swell = barSwell(hour, input.site ? nearshoreAt(input.site, hour.at) : undefined);
    const against = windAgainstEbb(hour, tide, input.entrance.seawardDeg);
    return {at: hour.at, tide, swell, windAgainst: against, ...barBand(tide, swell, against)};
  });
}

export type BarDay = {
  entrance: Entrance;
  hours: BarHour[];
  /** The worst band over the day's hours (Unknown ranks below Hazardous, above Caution), or null without hours. */
  worst: BarBand | null;
  hazardous: BarHour[];
  caution: BarHour[];
  basis: 'nearshore' | 'offshore' | 'mixed' | null;
  /** True when no hour has a tide stage. */
  tideUnknown: boolean;
};

export function barDay(entrance: Entrance, hours: BarHour[]): BarDay {
  const bands = hours.map(h => h.band);
  const worst = bands.length ? bands.reduce((a, b) => BAR_RANK[b] > BAR_RANK[a] ? b : a) : null;
  const bases = new Set(hours.map(h => h.swell.basis).filter(b => b !== null));
  const basis = !bases.size ? null : bases.size > 1 ? 'mixed' : (bases.has('nearshore') ? 'nearshore' : 'offshore');
  return {entrance, hours, worst, hazardous: hours.filter(h => h.band === 'Hazardous'), caution: hours.filter(h => h.band === 'Caution'), basis,
    tideUnknown: hours.length > 0 && !hours.some(h => h.tide.stage !== null)};
}

/**
 * The bar hours a trip leaving at `start` and returning at `end` crosses: the
 * departure hour [start, start + 1 h) and the return hour [end - 1 h, end].
 */
export function crossingHours(day: BarDay, start: string, end: string): BarHour[] {
  return crossingCheck(day, start, end).hours;
}

export type CrossingCheck = {hours: BarHour[]; departure: BarHour | null; return: BarHour | null; known: boolean};

/**
 * The crossing hours with the readings at each end: `departure` is the earliest reading in [start, start + 1 h),
 * `return` the latest in [end - 1 h, end]. `known` is false when either end has no reading, either time is not a
 * date, or the window does not end after it starts: such a window is never read as a clear bar.
 */
export function crossingCheck(day: BarDay, start: string, end: string): CrossingCheck {
  const from = Date.parse(start), to = Date.parse(end);
  const at = (h: BarHour) => Date.parse(h.at);
  const hours = day.hours.filter(h => {const t = at(h); return (t >= from && t < from + HOUR) || (t >= to - HOUR && t <= to);});
  const leaving = hours.filter(h => at(h) >= from && at(h) < from + HOUR).sort((a, b) => at(a) - at(b));
  const back = hours.filter(h => at(h) >= to - HOUR && at(h) <= to).sort((a, b) => at(b) - at(a));
  const departure = leaving[0] ?? null, ret = back[0] ?? null;
  return {hours, departure, return: ret, known: Number.isFinite(from) && Number.isFinite(to) && to > from && departure !== null && ret !== null};
}

/** The standing line every bar reading carries. */
export const BAR_CHECK = 'This is a rough estimate rather than an official bar report: check the Coast Guard bar status (VHF 16 or 22A) or the harbor patrol before crossing.';
