// SC0452-09: the words of the day verdict's reasons (web/brief/verdict.ts) in the page's language. Display
// assembly only: every decision (charge order, thresholds, holds, the profile graders' reason costs) is made in
// verdict.ts from the ORIGINAL numbers and English reasons, and this file only phrases the result, so a
// translation can never re-rate a day. The sentences live in catalog/app/strings.json under `verdict.`; the
// English templates reproduce the old literals byte for byte (tests/test_brief_verdict.mjs). Spanish renders the
// same numbers with the same rounding (a printed maximum is never below the value used), the same units, and the
// alert event name verbatim. A reason this file does not know is shown as the model gave it, never as a calmer one.
//
// Erasable syntax only: Node tests import this file by type stripping.
import {localeOf, num, t, type Language, type StringId} from '../i18n.ts';
import type {ComfortRating, FeedHour} from '../score.ts';

export const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
export const r0 = (n: number) => String(Math.round(n));
export const r1 = (n: number) => String(Number(n.toFixed(1)));
/** Seas to 0.1 ft, rounded UP: a printed maximum is never below the value the window rule used (1e-9 absorbs float noise). */
export const up1 = (n: number) => String(Math.ceil(n * 10 - 1e-9) / 10);
export const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const COMPASS = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
export const compass = (deg: number | null) => finite(deg) ? COMPASS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]! : null;

/** The local hour (0-23) of `ms` in `tz`. */
function hourOf(ms: number, tz: string): number {
  const part = new Intl.DateTimeFormat('en-CA', {timeZone: tz, hour: '2-digit', hourCycle: 'h23'}).formatToParts(new Date(ms)).find(p => p.type === 'hour');
  return Number(part?.value);
}

/** "7 am", "noon", "1 pm" in the region's zone. */
export function englishClock(ms: number, tz: string): string {
  const h = hourOf(ms, tz);
  return h === 12 ? 'noon' : h === 0 ? 'midnight' : `${h % 12} ${h < 12 ? 'am' : 'pm'}`;
}

/** The hour in `lang`'s own clock and the region's zone ("7", "13"): no English noon, am or pm. */
export const localClock = (ms: number, tz: string, lang: Language | string): string =>
  new Intl.DateTimeFormat(localeOf(lang), {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(ms)).replace(':00', '').toLowerCase();

export type Charge = 'wind' | 'seas' | 'chop' | 'cross';
export type UnknownKey = 'noForecast' | 'beyond' | 'noDaylight' | 'noBoatWindow' | 'noProfileWindow';

const id = (suffix: string): StringId => `verdict.${suffix}` as StringId;

/** The producers' fixed profile reasons (packages/coast shore-conditions.ts, kayak.ts, spear.ts), by anchored match. */
const FIXED: readonly (readonly [RegExp, string])[] = [
  [/^long-period swell$/, 'reason.longPeriodSwell'], [/^short-period chop$/, 'reason.shortChop'], [/^surf at the launch$/, 'reason.launchSurf'],
  [/^fog alert$/, 'reason.fogAlert'], [/^outside daylight$/, 'reason.outsideDaylight'],
  [/^rising tide$/, 'reason.tideRising'], [/^falling tide$/, 'reason.tideFalling'], [/^high tide$/, 'reason.tideHigh'], [/^low tide$/, 'reason.tideLow'],
  [/^around high tide$/, 'reason.nearHighTide'], [/^near high tide$/, 'reason.nearHighTide'], [/^dawn or dusk$/, 'reason.twilight'],
  [/^clarity unknown$/, 'reason.clarityUnknown'], [/^surf height unknown$/i, 'reason.surfUnknown'], [/^wind unknown$/i, 'reason.windUnknown'],
  [/^seas unknown$/i, 'reason.seasUnknown'], [/^swell height or period unknown$/i, 'reason.swellUnknown'],
];
/** Band words (lower case) to catalogue ids; one band has one Spanish word whichever noun it describes. */
const BANDS: Readonly<Record<string, string>> = {
  small: 'band.small', moderate: 'band.moderate', large: 'band.large', heavy: 'band.heavy', light: 'band.light', low: 'band.light', fresh: 'band.fresh',
  breezy: 'band.breezy', strong: 'band.strong', choppy: 'band.choppy', rough: 'band.rough', 'likely good': 'band.likelyGood', fair: 'band.fair', 'likely poor': 'band.likelyPoor',
};
const SIDES: Readonly<Record<string, string>> = {onshore: 'reason.onshore', offshore: 'reason.offshore', 'cross-shore': 'reason.crossShore'};

/** The verdict's sentences and fragments in `lang` (English by default: the old literals). */
export function verdictCopy(lang: Language = 'en') {
  const say = (suffix: string, vars: Readonly<Record<string, string | number>> = {}) => t(id(suffix), lang, vars);
  // Numbers arrive already rounded as strings (r0, r1, up1); Spanish only swaps the decimal mark.
  const n = (value: string | number): string => lang === 'es' ? num(Number(value), lang, 3) : String(value);
  const clock = (ms: number, tz: string): string => lang === 'es' ? localClock(ms, tz, lang) : englishClock(ms, tz);

  /** One charge of the worst hour: "22 kt wind gusting 30", "2.5 ft seas at 11 s", wind chop or a crossing swell. */
  const phrase = (kind: Charge, r: ComfortRating, h: FeedHour): string => {
    if (kind === 'wind') return say('wind', {wind: n(r0(r.wind))}) + (r.gust !== null && r.gust >= r.wind + 3 ? say('gust', {gust: n(r0(r.gust))}) : '');
    // The period is GFS-Wave's; name it only when its height is the one shown (WAM's period is not in the feed).
    if (kind === 'seas') return say('seas', {sea: n(up1(r.sea))}) + (finite(h.sea_period) && finite(h.sea) && h.sea >= r.sea ? say('period', {period: n(r0(h.sea_period))}) : '');
    if (kind === 'chop') return say(r.costs.short > 0 ? 'steepChop' : 'chop', {chop: n(r1(r.chop ?? 0))});
    const from = compass(h.secondary_from);
    return say('cross', {swell: n(r1(h.secondary ?? 0))}) + (from ? say('from', {direction: from}) : '');
  };

  /** A recognised profile reason in `lang`; English is returned as the grader wrote it. */
  const profileReason = (raw: string): string => {
    if (lang === 'en') return raw;
    const miss = () => say('reason.fallback', {reason: raw});
    const band = (word: string | undefined): string | null => {
      const key = (word ?? '').toLowerCase();
      return key === 'unknown' ? say('band.unknown') : Object.hasOwn(BANDS, key) ? say(BANDS[key]!) : null;
    };
    const height = (h: string | undefined, p: string | undefined, basis: string): string => h === undefined ? '' : say('reason.detail', {height: n(h), period: p === undefined ? '' : say('reason.period', {period: n(p)}), basis});
    for (const [pattern, key] of FIXED) if (pattern.test(raw)) return say(key);
    let m: RegExpExecArray | null;
    if ((m = /^(\w+) surf(?: \((\d+(?:\.\d+)?) ft(?: at (\d+(?:\.\d+)?) s)?(, offshore estimate)?\))?$/.exec(raw))) {
      const b = band(m[1]);
      return b === null ? miss() : say('reason.surf', {band: b, detail: height(m[2], m[3], m[4] ? say('reason.offshoreEstimate') : '')});
    }
    if ((m = /^(\w+) wind(?: \((\d+(?:\.\d+)?) kt(?:, gust (\d+(?:\.\d+)?))?\))?(?: (onshore|offshore|cross-shore))?$/.exec(raw))) {
      const b = band(m[1]);
      if (b === null) return miss();
      const detail = m[2] === undefined ? '' : say('reason.windDetail', {wind: n(m[2]), gust: m[3] === undefined ? '' : say('reason.gust', {gust: n(m[3])})});
      return say('reason.wind', {band: b, detail, side: m[4] === undefined ? '' : say(SIDES[m[4]]!)});
    }
    if ((m = /^(\w+) seas(?: \((\d+(?:\.\d+)?) ft(?: at (\d+(?:\.\d+)?) s)?\))?$/.exec(raw))) {
      const b = band(m[1]);
      return b === null ? miss() : say('reason.seas', {band: b, detail: height(m[2], m[3], '')});
    }
    if ((m = /^(\w+) surge( \(from offshore swell\))?$/.exec(raw))) {
      const b = band(m[1]);
      return b === null ? miss() : say('reason.surge', {band: b, basis: m[2] ? say('reason.surgeBasis') : ''});
    }
    if ((m = /^(\w+) chop$/.exec(raw))) { const b = band(m[1]); return b === null ? miss() : say('reason.chop', {band: b}); }
    if ((m = /^clarity estimate (likely good|fair|likely poor|unknown)$/.exec(raw))) {
      const b = m[1] === 'unknown' ? say('band.unknownFeminine') : band(m[1]);
      return b === null ? miss() : say('reason.clarity', {band: b});
    }
    return miss();
  };

  return {
    clock, phrase, profileReason,
    unknown: (key: UnknownKey): string => say(key),
    /** A grade as a lower-case word ("rough"), for a profile day with no reason to name. */
    gradeWord: (grade: string): string => t(`brief.verdict.${grade}` as StringId, lang).toLowerCase(),
    /** The calm sentence: the window's top wind and seas, through `until`. */
    calm: (wind: string, sea: string, until: string): string => say('calm', {wind: n(wind), sea: n(sea), until}),
    /** The limiting charge at its hour, with the second charge when it costs a point. */
    limit: (first: string, at: string, second: string | null): string => say('charged', {first: cap(first), at, second: second === null ? '' : say('with', {phrase: second})}),
    /** The event name is the alert's own words, shown verbatim. */
    alert: (event: string, limit: string): string => say('alert', {event, limit}),
    noAlertCheck: (): string => say('noAlertCheck'),
    held: (reasons: readonly string[]): string | null => reasons.length ? say('held', {reasons: reasons.join('; ')}) : null,
    partial: (): string => say('partial'),
    missing: (missing: number, total: number, profile = false): string => say(profile ? 'missingProfile' : 'missingForecast', {missing, total}),
    stale: (hours: number): string => say('stale', {hours}),
    alertMissing: (): string => say('alertMissing'),
    bar: (at: string): string => say('bar', {at}),
    longPeriod: (height: number, period: number, at: string): string => say('longPeriod', {height: n(r1(height)), period: n(r0(period)), at}),
    /** A profile's limit sentence: its reasons joined, then "through" the window's end or "at" the worst hour. */
    profileLimit: (reason: string, kind: 'through' | 'at', when: string): string => say(kind === 'through' ? 'profileThrough' : 'profileAt', {reason, [kind === 'through' ? 'until' : 'at']: when}),
  };
}

export type VerdictCopy = ReturnType<typeof verdictCopy>;
