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
import {M_PER_FT, WIND_SPEED} from '../units.ts';
import {units, type Units} from '../unit-choice.ts';

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
const SURF_REASON = /^(\w+) surf(?: \((\d+(?:\.\d+)?) ft(?: at (\d+(?:\.\d+)?) s)?(, offshore estimate)?\))?$/;
const WIND_REASON = /^(\w+) wind(?: \((\d+(?:\.\d+)?) kt(?:, gust (\d+(?:\.\d+)?))?\))?(?: (onshore|offshore|cross-shore))?$/;
const SEAS_REASON = /^(\w+) seas(?: \((\d+(?:\.\d+)?) ft(?: at (\d+(?:\.\d+)?) s)?\))?$/;

/** The verdict's sentences and fragments in `lang` (English by default: the old literals). */
export function verdictCopy(lang: Language = 'en', u: Units = units.value) {
  // SC1222-05: wind and heights print in the chosen units with the tiles' conversion; the numbers given in are always kt and ft.
  const wu = WIND_SPEED[u.wind], metres = u.height === 'm';
  const say = (suffix: string, vars: Readonly<Record<string, string | number>> = {}) => t(id(suffix), lang, {windUnit: wu.label, heightUnit: u.height, ...vars});
  // Numbers arrive already rounded as strings (r0, r1, up1); Spanish only swaps the decimal mark.
  const n = (value: string | number): string => lang === 'es' ? num(Number(value), lang, 3) : String(value);
  const clock = (ms: number, tz: string): string => lang === 'es' ? localClock(ms, tz, lang) : englishClock(ms, tz);
  const wind = (kt: number): string => n(r0(kt * wu.factor));
  const ft1 = (ft: number): string => n(r1(metres ? ft * M_PER_FT : ft));
  /** A seas maximum: rounded UP in the shown unit, so a converted maximum is never below the value the window rule used. */
  const seasMax = (ft: number): string => n(metres ? String(Math.ceil(ft * M_PER_FT * 10 - 1e-9) / 10) : up1(ft));

  /** One charge of the worst hour: "22 kt wind gusting 30", "2.5 ft seas at 11 s", wind chop or a crossing swell. */
  const phrase = (kind: Charge, r: ComfortRating, h: FeedHour): string => {
    if (kind === 'wind') return say('wind', {wind: wind(r.wind)}) + (r.gust !== null && r.gust >= r.wind + 3 ? say('gust', {gust: wind(r.gust)}) : '');
    // The period is GFS-Wave's; name it only when its height is the one shown (WAM's period is not in the feed).
    if (kind === 'seas') return say('seas', {sea: seasMax(r.sea)}) + (finite(h.sea_period) && finite(h.sea) && h.sea >= r.sea ? say('period', {period: n(r0(h.sea_period))}) : '');
    if (kind === 'chop') return say(r.costs.short > 0 ? 'steepChop' : 'chop', {chop: ft1(r.chop ?? 0)});
    const from = compass(h.secondary_from);
    return say('cross', {swell: ft1(h.secondary ?? 0)}) + (from ? say('from', {direction: from}) : '');
  };

  /** A recognised profile reason in `lang`; English is returned as the grader wrote it (its kt and ft numbers converted when other units are chosen). */
  const profileReason = (raw: string): string => {
    // SC2137-09: the spear grader's Choppy band writes "choppy chop"; say it as its own catalogue sentence in both languages (es is unchanged).
    if (raw === 'choppy chop') return say('reason.chopChoppy');
    // Display only: the grader's English decided the reason and its cost; a recognised reason keeps its words and swaps its numbers.
    if (lang === 'en') {
      const match = SURF_REASON.exec(raw) ?? WIND_REASON.exec(raw) ?? SEAS_REASON.exec(raw);
      if (!match || !Object.hasOwn(BANDS, match[1]!.toLowerCase()) && match[1]!.toLowerCase() !== 'unknown') return raw;
      return raw
        .replace(/\((\d+(?:\.\d+)?) kt(, gust )?(\d+(?:\.\d+)?)?/, (all, w, g, gu) => u.wind === 'kt' ? all : `(${wind(Number(w))} ${wu.label}${g ?? ''}${gu === undefined ? '' : wind(Number(gu))}`)
        .replace(/\((\d+(?:\.\d+)?) ft/, (all, h) => metres ? `(${ft1(Number(h))} m` : all);
    }
    // The same numbers for Spanish: unchanged in kt and ft (byte for byte), converted otherwise.
    const windOf = (s: string): string => u.wind === 'kt' ? n(s) : wind(Number(s)), heightOf = (s: string): string => metres ? ft1(Number(s)) : n(s);
    const miss = () => say('reason.fallback', {reason: raw});
    const band = (word: string | undefined): string | null => {
      const key = (word ?? '').toLowerCase();
      return key === 'unknown' ? say('band.unknown') : Object.hasOwn(BANDS, key) ? say(BANDS[key]!) : null;
    };
    const height = (h: string | undefined, p: string | undefined, basis: string): string => h === undefined ? '' : say('reason.detail', {height: heightOf(h), period: p === undefined ? '' : say('reason.period', {period: n(p)}), basis});
    for (const [pattern, key] of FIXED) if (pattern.test(raw)) return say(key);
    let m: RegExpExecArray | null;
    if ((m = SURF_REASON.exec(raw))) {
      const b = band(m[1]);
      return b === null ? miss() : say('reason.surf', {band: b, detail: height(m[2], m[3], m[4] ? say('reason.offshoreEstimate') : '')});
    }
    if ((m = WIND_REASON.exec(raw))) {
      const b = band(m[1]);
      if (b === null) return miss();
      const detail = m[2] === undefined ? '' : say('reason.windDetail', {wind: windOf(m[2]), gust: m[3] === undefined ? '' : say('reason.gust', {gust: windOf(m[3])})});
      return say('reason.wind', {band: b, detail, side: m[4] === undefined ? '' : say(SIDES[m[4]]!)});
    }
    if ((m = SEAS_REASON.exec(raw))) {
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
    calm: (windKt: string | number, seaFt: string | number, until: string): string => say('calm', {wind: wind(Number(windKt)), sea: seasMax(Number(seaFt)), until}),
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
    longPeriod: (height: number, period: number, at: string): string => say('longPeriod', {height: ft1(height), period: n(r0(period)), at}),
    /** A profile's limit sentence: its reasons joined, then "through" the window's end or "at" the worst hour. */
    profileLimit: (reason: string, kind: 'through' | 'at', when: string): string => say(kind === 'through' ? 'profileThrough' : 'profileAt', {reason, [kind === 'through' ? 'until' : 'at']: when}),
  };
}

export type VerdictCopy = ReturnType<typeof verdictCopy>;

// SC2022-04: the lower-exposure window's words (packages/coast daily.ts and assessment.ts write them in English).
// The web side parses the known English forms, as the profile reasons above are parsed: packages/coast keeps its
// strings and shape, the window's times and screening stay on the stored kt and ft, and only this display changes.
const LOWER_FIXED = ['label.surf', 'label.surge', 'label.seas', 'label.boat', 'label.offshore', 'reason.route', 'reason.surf', 'reason.visibility'].map(key => `lower.${key}`);
const NUM = '(\\d+(?:\\.\\d+)?)';
/** The English template of catalogue id `key` as an anchored pattern: each {name} becomes its capture. */
const english = (key: string, captures: Readonly<Record<string, string>> = {}): RegExp =>
  new RegExp(`^${t(key as StringId, 'en').replace(/[.*+?^$()|[\]\\]/g, '\\$&').replace(/\{(\w+)\}/g, (_, name: string) => captures[name] ?? '(.*)')}$`, 's');
const barPattern = () => english('lower.reason.bar', {entrance: '([\\s\\S]+)'});
/** True for the appended bar caution (packages/coast daily.ts): the entrance's name, then the fixed words. */
export const isBarReason = (raw: string): boolean => barPattern().test(raw);
/** Rounded UP in the shown unit, so a displayed limit is never below the stored one (1e-9 absorbs float noise). */
const upTo = (value: number, digits: number) => Math.ceil(value * 10 ** digits - 1e-9) / 10 ** digits;

/** A lower-exposure window label or reason in `lang`; `known` is false for text this file does not recognise (shown as given). */
export function windowCopy(raw: string, lang: Language, shown: {wind: keyof typeof WIND_SPEED; height: 'ft' | 'm'} = {wind: 'kt', height: 'ft'}): {text: string; known: boolean} {
  const say = (suffix: string, vars: Readonly<Record<string, string | number>> = {}) => t(suffix as StringId, lang, vars);
  const fixed = LOWER_FIXED.find(key => t(key as StringId, 'en') === raw) ?? null;
  const bar = fixed === null ? barPattern().exec(raw) : null;
  // "Using your limits (<parts>); the default ..." with <parts> in the producer's own order (limits.ts limitsText).
  const note = fixed === null && bar === null ? english('lower.limits', {limits: '(.+)'}).exec(raw) : null;
  const units = {v: NUM, u: `(?:${WIND_SPEED.kt.label}|ft)`};
  const [pw, pg, ps, px, ...extra] = note ? note[1]!.split(', ') : [];
  const part = (key: string, captures: Readonly<Record<string, string>>, text: string | undefined) => text === undefined ? null : english(key, captures).exec(text);
  const wind = part('lower.limits.wind', units, pw), gust = part('lower.limits.gust', units, pg);
  const seas = part('lower.limits.seas', units, ps), surf = part('lower.limits.surf', units, ps), surge = part('lower.limits.surge', {band: '(low|moderate|strong)'}, px);
  const own = wind && gust && (seas || surf) && (px === undefined || surge) && extra.length === 0 ? {wind: wind[1]!, gust: gust[1]!, surf: !!surf, height: (seas ?? surf)![1]!, surge: surge?.[1] ?? null} : null;
  if (lang === 'en' && (!own || (shown.wind === 'kt' && shown.height === 'ft'))) return {text: raw, known: true};
  if (fixed !== null) return {text: say(fixed), known: true};
  if (bar) return {text: say('lower.reason.bar', {entrance: bar[1]!}), known: true};
  if (!own) return {text: raw, known: false};
  const show = (stored: string, value: number | null): string => lang === 'es' ? num(value ?? Number(stored), lang, 1) : value === null ? stored : String(value);
  const speed = (stored: string) => show(stored, shown.wind === 'kt' ? null : upTo(Number(stored) * WIND_SPEED[shown.wind].factor, 0));
  const height = show(own.height, shown.height === 'ft' ? null : upTo(Number(own.height) * M_PER_FT, 1)), u = WIND_SPEED[shown.wind].label;
  const parts = [say('lower.limits.wind', {v: speed(own.wind), u}), say('lower.limits.gust', {v: speed(own.gust), u}), say(own.surf ? 'lower.limits.surf' : 'lower.limits.seas', {v: height, u: shown.height})];
  if (own.surge) parts.push(say('lower.limits.surge', {band: say(`lower.surge.${own.surge}`)}));
  return {text: say('lower.limits', {limits: parts.join(', ')}), known: true};
}
