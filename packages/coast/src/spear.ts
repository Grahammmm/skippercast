// Spearfishing conditions (issue #542): surge, a clarity estimate, chop and a
// verdict per forecast hour, rolled up per day for the daily brief.
//
// Every threshold lives in SPEAR below with the reasoning behind it. They are
// coarse screening rules for a free diver on a shallow reef, not measurements
// and not a promise that a spot is safe or clear. Water temperature is shown by
// the brief but never scored here.
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {ChlorophyllReading, ForecastHour, Observation, TideEvent} from './types.ts';
import type {NearshoreHour, NearshoreSite} from './enrichment-types.ts';
import {nearshoreAt} from './nearshore.ts';

const HOUR = 3_600_000;
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const round = (value: number, digits = 1) => Number(value.toFixed(digits));

export type {ChlorophyllReading};

/**
 * The spear thresholds. Units: feet, seconds, knots, percent, mg/m³.
 *
 * Surge energy is H² · T (significant height squared times period, ft²·s),
 * the shape of deep-water wave energy flux. It ranks swells, it does not
 * measure water motion on the bottom.
 */
export const SPEAR = {
  surge: {
    /** Upper bounds of each band in ft²·s. 2 ft at 10 s = 40; 3 ft at 12 s = 108; 4 ft at 15 s = 4² · 15 · 1.5 = 360 (Heavy). */
    low: 40,
    moderate: 110,
    strong: 250,
    /**
     * Long-period swell reaches deeper and pushes harder on a reef for the
     * same height, so its energy is scaled up: ×1.25 from 13 s, ×1.5 from 15 s.
     */
    longPeriod: [{fromS: 15, factor: 1.5}, {fromS: 13, factor: 1.25}],
  },
  chop: {
    /** Light: the same wind and gust limits the generic shore and spear window uses. */
    light: {wind: 8, gust: 12},
    /** Choppy up to here; beyond it, surface swimming and entries are rough. */
    choppy: {wind: 12, gust: 18},
  },
  clarity: {
    /** Chlorophyll above `fair` reads as some green water, above `poor` as green water likely. */
    chlorophyll: {fair: 1.5, poor: 4, maxAgeHours: 96},
    /** Highest rain chance in the prior 72 h: runoff carries silt and nutrients to the coast. */
    rain: {windowHours: 72, fair: 30, poor: 60},
    /**
     * Largest surge energy in the prior 48 h: big swell stirs bottom sediment that takes days to settle.
     * With fewer than `minCoveredHours` of that window sampled (the forecast starts at the current hour and
     * buoys give only the latest reading), yesterday's swell is unchecked and the band is capped at Fair.
     */
    swell: {windowHours: 48, fair: 110, poor: 250, minCoveredHours: 36},
    /** Wind at the hour: chop and surface mixing cloud the top of the water. */
    wind: {fair: 10, poor: 15},
    /** Three fair drivers together read as likely poor. */
    fairToPoor: 3,
  },
  /** A high tide within this many minutes is a mild bonus: deeper water over the reef and easier rock entries for many shore dives. */
  highTideMinutes: 90,
  /** Verdict score: lower is calmer. Calmer up to `calmer`, Marginal up to `marginal`, Rough above. */
  score: {
    surge: {Low: 0, Moderate: 0.75, Strong: 3, Heavy: 6},
    chop: {Light: 0, Choppy: 1.5, Rough: 4},
    clarity: {'Likely good': 0, Fair: 0.5, 'Likely poor': 1.5, Unknown: 0.5},
    highTide: -0.5,
    calmer: 1,
    marginal: 3,
  },
  /** Spear windows from a nearshore model allow surge up to this band. */
  windowMaxSurge: 'Moderate',
} as const;

export type SurgeBand = 'Low' | 'Moderate' | 'Strong' | 'Heavy' | 'Unknown';
export type ChopBand = 'Light' | 'Choppy' | 'Rough' | 'Unknown';
export type ClarityBand = 'Likely good' | 'Fair' | 'Likely poor' | 'Unknown';
export type SpearVerdict = 'Calmer' | 'Marginal' | 'Rough' | 'Unknown';

export const SURGE_RANK: Readonly<Record<SurgeBand, number>> = {Low: 0, Moderate: 1, Strong: 2, Heavy: 3, Unknown: 4};
const CLARITY_RANK: Readonly<Record<ClarityBand, number>> = {'Likely good': 0, Fair: 1, 'Likely poor': 2, Unknown: -1};

export type Surge = {band: SurgeBand; energy: number | null; heightFt: number | null; periodS: number | null; basis: 'nearshore' | 'offshore' | null};
export type Chop = {band: ChopBand; windKnots: number | null; gustKnots: number | null};
export type Clarity = {band: ClarityBand; drivers: string[]; missing: string[]; gaps: string[]};
export type SpearHour = {at: string; surge: Surge; chop: Chop; clarity: Clarity; highTide: boolean; verdict: SpearVerdict; reasons: string[]};

/** H² · T with the long-period factor; null without both numbers. */
export function surgeEnergy(heightFt: number | null | undefined, periodS: number | null | undefined): number | null {
  if (!finite(heightFt) || !finite(periodS) || heightFt < 0 || periodS <= 0) return null;
  const factor = SPEAR.surge.longPeriod.find(item => periodS >= item.fromS)?.factor ?? 1;
  return heightFt * heightFt * periodS * factor;
}

export function surgeBand(energy: number | null): SurgeBand {
  if (energy === null) return 'Unknown';
  return energy < SPEAR.surge.low ? 'Low' : energy < SPEAR.surge.moderate ? 'Moderate' : energy < SPEAR.surge.strong ? 'Strong' : 'Heavy';
}

/**
 * Surge at one hour. A nearshore model sample wins over the offshore forecast;
 * offshore, the larger of the combined sea and the swell partition counts.
 */
export function surge(hour: ForecastHour | undefined, near?: NearshoreHour): Surge {
  const nearEnergy = surgeEnergy(near?.waveFt, near?.periodS);
  if (near && nearEnergy !== null) return {band: surgeBand(nearEnergy), energy: nearEnergy, heightFt: near.waveFt, periodS: near.periodS, basis: 'nearshore'};
  const combined = surgeEnergy(hour?.waveFt, hour?.wavePeriodS), swell = surgeEnergy(hour?.swellFt, hour?.swellPeriodS);
  if (combined === null && swell === null) return {band: 'Unknown', energy: null, heightFt: null, periodS: null, basis: null};
  const useSwell = swell !== null && (combined === null || swell > combined);
  const energy = useSwell ? swell : combined;
  return {band: surgeBand(energy), energy, heightFt: (useSwell ? hour?.swellFt : hour?.waveFt) ?? null, periodS: (useSwell ? hour?.swellPeriodS : hour?.wavePeriodS) ?? null, basis: 'offshore'};
}

export function chop(windKnots: number | null | undefined, gustKnots: number | null | undefined): Chop {
  const wind = finite(windKnots) ? windKnots : null, gust = finite(gustKnots) ? gustKnots : null;
  if (wind === null) return {band: 'Unknown', windKnots: null, gustKnots: gust};
  const g = gust ?? wind, {light, choppy} = SPEAR.chop;
  const band: ChopBand = wind <= light.wind && g <= light.gust ? 'Light' : wind <= choppy.wind && g <= choppy.gust ? 'Choppy' : 'Rough';
  return {band, windKnots: wind, gustKnots: gust};
}

export type ClarityInputs = {
  /** The latest chlorophyll reading near the place, or null. */
  chlorophyll: ChlorophyllReading | null;
  /** The hour being estimated. */
  at: string;
  /** Highest rain chance in the prior window, and the hours of that window the forecast covers. */
  rainPct: number | null;
  rainHoursCovered: number;
  /** Largest surge energy in the prior window, or null with no sample, and the hours of that window with a sample. */
  recentEnergy: number | null;
  recentHoursCovered: number;
  windKnots: number | null;
};

/**
 * A coarse clarity band from the drivers that cloud the water. Chlorophyll and
 * recent swell are required; without either the band is Unknown and says what
 * is missing. Rain and wind add drivers when known.
 */
export function clarity(input: ClarityInputs): Clarity {
  const {clarity: c} = SPEAR;
  const drivers: string[] = [], missing: string[] = [], gaps: string[] = [];
  let fair = 0, poor = 0;
  const at = Date.parse(input.at);
  const chl = input.chlorophyll, chlAge = chl ? (at - Date.parse(chl.sampleAt)) / HOUR : NaN;
  if (!chl || !finite(chl.mgM3)) missing.push('satellite chlorophyll');
  else if (!Number.isFinite(chlAge) || chlAge > c.chlorophyll.maxAgeHours || chlAge < -24) missing.push('a recent chlorophyll reading');
  else {
    const value = round(chl.mgM3);
    if (chl.mgM3 > c.chlorophyll.poor) {poor++; drivers.push(`chlorophyll ${value} mg/m³: green water likely`);}
    else if (chl.mgM3 > c.chlorophyll.fair) {fair++; drivers.push(`chlorophyll ${value} mg/m³: some green water`);}
    else drivers.push(`chlorophyll ${value} mg/m³: low`);
    gaps.push('Clarity estimate: satellite chlorophyll is an offshore area average and may read clearer than the shoreline');
  }
  if (input.recentEnergy === null) missing.push('recent swell');
  else if (input.recentEnergy >= c.swell.poor) {poor++; drivers.push('large swell in the past 2 days: stirred sediment likely');}
  else if (input.recentEnergy >= c.swell.fair) {fair++; drivers.push('moderate swell in the past 2 days');}
  const swellUnchecked = input.recentEnergy !== null && input.recentHoursCovered < c.swell.minCoveredHours;
  if (swellUnchecked) gaps.push('Clarity estimate: swell before the forecast began is unchecked');
  if (input.rainPct === null) gaps.push('Clarity estimate: recent rain unknown');
  else {
    if (input.rainPct >= c.rain.poor) {poor++; drivers.push(`rain chance up to ${Math.round(input.rainPct)}% in the past 3 days: runoff likely`);}
    else if (input.rainPct >= c.rain.fair) {fair++; drivers.push(`rain chance up to ${Math.round(input.rainPct)}% in the past 3 days`);}
    if (input.rainHoursCovered < c.rain.windowHours - 12) gaps.push('Clarity estimate: rain before the forecast began is unchecked');
  }
  if (!finite(input.windKnots)) gaps.push('Clarity estimate: wind unknown');
  else if (input.windKnots >= c.wind.poor) {poor++; drivers.push(`wind ${Math.round(input.windKnots)} kt: surface chop`);}
  else if (input.windKnots >= c.wind.fair) {fair++; drivers.push(`wind ${Math.round(input.windKnots)} kt: some chop`);}
  if (missing.length) return {band: 'Unknown', drivers, missing, gaps};
  // Without most of the swell look-back, a recent big swell may be missed: never read Likely good.
  const band: ClarityBand = poor || fair >= c.fairToPoor ? 'Likely poor' : fair || swellUnchecked ? 'Fair' : 'Likely good';
  return {band, drivers, missing, gaps};
}

/** The verdict from surge, chop, clarity and the high-tide bonus. */
export function spearVerdict(s: Surge, w: Chop, k: Clarity, highTide: boolean): {verdict: SpearVerdict; score: number | null; reasons: string[]} {
  const reasons: string[] = [];
  if (s.band === 'Unknown') reasons.push('Swell height or period unknown');
  if (w.band === 'Unknown') reasons.push('Wind unknown');
  if (s.band === 'Unknown' || w.band === 'Unknown') return {verdict: 'Unknown', score: null, reasons};
  const {score: p} = SPEAR;
  const score = p.surge[s.band] + p.chop[w.band] + p.clarity[k.band] + (highTide ? p.highTide : 0);
  reasons.push(`${s.band} surge${s.basis === 'offshore' ? ' (from offshore swell)' : ''}`, `${w.band.toLowerCase()} chop`, k.band === 'Unknown' ? 'clarity unknown' : `clarity estimate ${k.band.toLowerCase()}`);
  if (highTide) reasons.push('near high tide');
  return {verdict: score <= p.calmer ? 'Calmer' : score <= p.marginal ? 'Marginal' : 'Rough', score, reasons};
}

export type SpearInputs = {
  hours: readonly ForecastHour[];
  /** The whole fresh forecast, for the look-back windows. */
  forecastHours: readonly ForecastHour[];
  site: NearshoreSite | undefined;
  observations: readonly Observation[];
  tideEvents: readonly TideEvent[];
  chlorophyll: ChlorophyllReading | null;
};

/**
 * Largest surge energy over the window before `at` from forecast, nearshore
 * model and buoy samples, and how many hours of that window carry a sample.
 * A sample covers its own hour; a nearshore model sample covers its interval
 * (three hours by default).
 */
export function recentEnergy(at: number, input: Pick<SpearInputs, 'forecastHours' | 'site' | 'observations'>): {energy: number | null; covered: number} {
  const windowHours = SPEAR.clarity.swell.windowHours, from = at - windowHours * HOUR;
  const energies: number[] = [], hours = new Set<number>();
  const add = (time: string, values: (number | null)[], spanHours = 1) => {
    const t = Date.parse(time), known = values.filter(finite);
    if (!Number.isFinite(t) || t < from || t > at || !known.length) return;
    energies.push(...known);
    const centre = Math.floor((at - t) / HOUR), half = Math.floor(spanHours / 2);
    for (let i = centre - half; i <= centre + half; i++) if (i >= 0 && i < windowHours) hours.add(i);
  };
  for (const h of input.forecastHours) add(h.at, [surgeEnergy(h.waveFt, h.wavePeriodS), surgeEnergy(h.swellFt, h.swellPeriodS)]);
  const siteSpan = Math.max(1, Math.round((input.site?.temporalResolutionMinutes ?? 180) / 60));
  for (const h of input.site?.hours ?? []) add(h.at, [surgeEnergy(h.waveFt, h.periodS)], siteSpan);
  for (const o of input.observations) add(o.observedAt, [surgeEnergy(o.waveFt, o.wavePeriodS)]);
  return {energy: energies.length ? Math.max(...energies) : null, covered: hours.size};
}

function recentRain(at: number, hours: readonly ForecastHour[]): {pct: number | null; covered: number} {
  const from = at - SPEAR.clarity.rain.windowHours * HOUR;
  const values = hours.filter(h => {const t = Date.parse(h.at); return Number.isFinite(t) && t >= from && t <= at && finite(h.precipPct);});
  return {pct: values.length ? Math.max(...values.map(h => h.precipPct as number)) : null, covered: values.length};
}

/** The spear reading for each forecast hour. */
export function spearHours(input: SpearInputs): SpearHour[] {
  return input.hours.map(hour => {
    const at = Date.parse(hour.at);
    const s = surge(hour, input.site ? nearshoreAt(input.site, hour.at) : undefined);
    const w = chop(hour.windKnots, hour.gustKnots);
    const rain = recentRain(at, input.forecastHours);
    const swell = recentEnergy(at, input);
    const k = clarity({chlorophyll: input.chlorophyll, at: hour.at, rainPct: rain.pct, rainHoursCovered: rain.covered, recentEnergy: swell.energy, recentHoursCovered: swell.covered, windKnots: hour.windKnots});
    const highTide = input.tideEvents.some(e => e.type === 'H' && Math.abs(Date.parse(e.at) - at) <= SPEAR.highTideMinutes * 60_000);
    const {verdict, reasons} = spearVerdict(s, w, k, highTide);
    return {at: hour.at, surge: s, chop: w, clarity: k, highTide, verdict, reasons};
  });
}

export type SpearDay = {
  hours: SpearHour[];
  /** Lowest and highest surge band over daylight hours (all hours when daylight is unknown). */
  surge: {min: SurgeBand; max: SurgeBand} | null;
  /** The worst known clarity band over those hours; Unknown when none is known. */
  clarity: Clarity;
  /** The calmest of those hours, earliest first on a tie. */
  best: SpearHour | null;
  basis: 'nearshore' | 'offshore' | 'mixed' | null;
};

/** Roll the hours up for the day, over daylight when sunrise and sunset are known. */
export function spearDay(hours: SpearHour[], sunrise: string | null, sunset: string | null): SpearDay {
  const rise = sunrise ? Date.parse(sunrise) : NaN, set = sunset ? Date.parse(sunset) : NaN;
  const daylightKnown = Number.isFinite(rise) && Number.isFinite(set) && rise < set;
  // Empty known daylight is missing coverage, not permission to use night hours.
  const scope = daylightKnown ? hours.filter(h => {const t = Date.parse(h.at); return t >= rise && t + HOUR <= set;}) : hours;
  const known = scope.filter(h => h.surge.band !== 'Unknown');
  const ranks = known.map(h => SURGE_RANK[h.surge.band]);
  const bands = Object.keys(SURGE_RANK) as SurgeBand[];
  const surgeRange = known.length ? {min: bands[Math.min(...ranks)]!, max: bands[Math.max(...ranks)]!} : null;
  const clear = scope.filter(h => h.clarity.band !== 'Unknown').sort((a, b) => CLARITY_RANK[b.clarity.band] - CLARITY_RANK[a.clarity.band])[0];
  const clarityDay = clear?.clarity ?? scope[0]?.clarity ?? {band: 'Unknown', drivers: [], missing: [daylightKnown ? 'daylight forecast hours' : 'forecast hours'], gaps: []};
  const order: Readonly<Record<SpearVerdict, number>> = {Calmer: 0, Marginal: 1, Rough: 2, Unknown: 3};
  const best = scope.filter(h => h.verdict !== 'Unknown' && h.verdict !== 'Rough').sort((a, b) => order[a.verdict] - order[b.verdict] || SURGE_RANK[a.surge.band] - SURGE_RANK[b.surge.band] || Date.parse(a.at) - Date.parse(b.at))[0] ?? null;
  const bases = new Set(known.map(h => h.surge.basis));
  const basis = !bases.size ? null : bases.size > 1 ? 'mixed' : (bases.has('nearshore') ? 'nearshore' : 'offshore');
  return {hours, surge: surgeRange, clarity: clarityDay, best, basis};
}

/** "Low", "Low to moderate". */
export function surgeText(range: {min: SurgeBand; max: SurgeBand}): string {
  return range.min === range.max ? range.min : `${range.min} to ${range.max.toLowerCase()}`;
}

/** "Clarity estimate: fair" or "Clarity unknown". */
export function clarityText(k: Clarity): string {
  return k.band === 'Unknown' ? 'Clarity unknown' : `Clarity estimate: ${k.band.toLowerCase()}`;
}
