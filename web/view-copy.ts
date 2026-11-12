// Spanish presentation for the Conditions and History views: the catalogue-backed copy the shared
// renderers take (packages/coast/src/ui/copy.ts) and the finite label mappings of the Conditions view.
// Display only: no row, source clock, value or URL is changed, and English keeps the renderers' own text
// (coastCopy is undefined for en).
import type {Series} from '../packages/coast/src/charts/series.ts';
import {COAST_COPY_KEYS, type CoastCopy} from '../packages/coast/src/ui/copy.ts';
import {localeOf, t, type Language, type StringId} from './i18n.ts';
import type {Profile} from './profile.ts';

export {COAST_COPY_KEYS};
const ROW_IDS: Readonly<Record<string, StringId>> = {
  Wind: 'conditions.row.wind', Gusts: 'conditions.row.gusts', 'Offshore seas': 'conditions.row.offshore', Nearshore: 'conditions.row.nearshore',
  Tide: 'conditions.row.tide', Air: 'conditions.row.air', Cloud: 'conditions.row.cloud',
};
const CAVEAT_IDS: Readonly<Record<Profile, StringId>> = {boat: 'conditions.caveat.boat', shore: 'conditions.caveat.shore', spear: 'conditions.caveat.spear', kayak: 'conditions.caveat.kayak'};
// The English texts the feed and conditions.ts publish, read from the catalogue's own English values.
const NEARSHORE_SOURCE = t('conditions.source.nearshore', 'en', {name: ''});
const FEED_SOURCE = t('conditions.source.feed', 'en');

// `n` rounded the way English prints it (toFixed), then localized: Intl rounds the binary float itself and can
// disagree with toFixed at a decimal tie (60.05 -> 60.0 vs 60,1), so the language never changes the digits.
const localized = (n: number, digits: number, lang: Language, useGrouping: boolean): string =>
  new Intl.NumberFormat(localeOf(lang), {minimumFractionDigits: digits, maximumFractionDigits: digits, useGrouping}).format(Number(n.toFixed(digits)));

/** `n` with exactly `digits` decimals in `lang` (English: toFixed, as the views always printed it). */
export const fixed = (n: number, digits: number, lang: Language): string =>
  lang === 'en' ? n.toFixed(digits) : localized(n, digits, lang, false);

/** `date` in `tz` and `lang`; a zone name is the region's short name ("PDT") in every language, never "GMT-7". */
export function localTime(date: Date, tz: string, lang: Language, options: Intl.DateTimeFormatOptions): string {
  const format = (locale: string) => new Intl.DateTimeFormat(locale, {timeZone: tz, ...options}).formatToParts(date);
  if (lang === 'en') return new Intl.DateTimeFormat(localeOf(lang), {timeZone: tz, ...options}).format(date);
  const zone = options.timeZoneName ? format('en-US').find(p => p.type === 'timeZoneName')?.value : undefined;
  return format(localeOf(lang)).map(p => p.type === 'timeZoneName' && zone ? zone : p.value).join('');
}

/** The renderers' host copy in `lang`: undefined for English (their own text), the catalogue for anything else. */
export function coastCopy(lang: Language): CoastCopy | undefined {
  if (lang === 'en') return undefined;
  return {
    text: (key, vars) => t(key, lang, vars),
    time: (at, tz, options) => Number.isFinite(Date.parse(at)) ? localTime(new Date(at), tz, lang, options) : t('history.timeNA', lang),
    number: (n, digits, group = false) => localized(n, digits, lang, group),
    age: (at, now) => {
      const minutes = Math.round((now.getTime() - Date.parse(at)) / 60000);
      if (!Number.isFinite(minutes) || minutes < 0) return t('history.age.unavailable', lang);
      if (minutes < 2) return t('history.age.now', lang);
      if (minutes < 60) return t('history.age.min', lang, {n: minutes});
      if (minutes < 1440) return t('history.age.hour', lang, {n: Math.floor(minutes / 60)});
      return t('history.age.day', lang, {n: Math.floor(minutes / 1440)});
    },
  };
}

/** The History view's renderer copy. */
export const historyCopy = (lang: Language): CoastCopy | undefined => coastCopy(lang);

/** The Conditions view's chart copy and the display labels of its built-in rows, source clocks and profile caveats. */
export function conditionsCopy(lang: Language) {
  return {
    chart: coastCopy(lang),
    /** A row's display label; an unknown label (a model or provider name) stays as published. */
    row: (label: string): string => Object.hasOwn(ROW_IDS, label) ? t(ROW_IDS[label]!, lang) : label,
    /** Rows relabelled for display; the raw rows (Tide is picked from them first) are never mutated. */
    rows: (rows: readonly Series[]): Series[] => rows.map(r => ({...r, label: Object.hasOwn(ROW_IDS, r.label) ? t(ROW_IDS[r.label]!, lang) : r.label})),
    source: (label: string): string =>
      label === FEED_SOURCE ? t('conditions.source.feed', lang)
        : label.startsWith(NEARSHORE_SOURCE) ? t('conditions.source.nearshore', lang, {name: label.slice(NEARSHORE_SOURCE.length)}) : label,
    kind: (kind: 'run' | 'fetched' | 'retrieved' | null): string => t(kind === null ? 'conditions.kind.unavailable' : `conditions.kind.${kind}`, lang),
    caveat: (profile: Profile): string => t(CAVEAT_IDS[profile], lang),
  };
}
