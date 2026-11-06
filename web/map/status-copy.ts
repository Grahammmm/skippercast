// SC1352-02: display-only wording for a layer's status (the rail's short note, the legend's longer reason and its
// stamp). A producer keeps its English strings and may attach a `StatusCopy` beside them: catalogue ids plus raw
// values (a product name, an ISO instant and its zone, a number). The rail and legend resolve it in the page's
// language at render, so a language change needs no refetch. English, a missing descriptor or bad metadata return
// the producer's own string untouched. Erasable syntax only (Node tests import this).
import {localeOf, STRINGS, t, type StringId} from '../i18n.ts';
import {copyText, type MarkCopyPart} from '../mark-copy.ts';

/** A value in a status template: raw text or number, another catalogue string, or a date, clock time, decimal or age to format. */
export type StatusVar = string | number
  | {readonly id: StringId; readonly vars?: Readonly<Record<string, StatusVar>>}
  | {readonly day: string | number; readonly tz: string}
  | {readonly clock: string | number; readonly tz: string}
  | {readonly num: number; readonly digits: number}
  | {readonly age: number}
  | {readonly moment: string | number; readonly tz: string; readonly form: 'hour' | 'run' | 'dated'};
export type StatusPart = string | {readonly id: StringId; readonly vars?: Readonly<Record<string, StatusVar>>};
/** The pieces of a status, each as catalogue parts: `note` (rail), `reason` (legend), `stamp` (legend). */
export type StatusCopy = Partial<Readonly<Record<'note' | 'reason' | 'stamp', readonly StatusPart[]>>>;

/** A catalogue part for a status descriptor. */
export const sp = (id: StringId, vars?: Readonly<Record<string, StatusVar>>): StatusPart => vars ? {id, vars} : {id};

const HOUR = 3_600_000;
const formats = new Map<string, Intl.DateTimeFormat>();
const format = (locale: string, tz: string, kind: 'day' | 'clock'): Intl.DateTimeFormat => {
  const key = `${locale}|${tz}|${kind}`;
  let f = formats.get(key);
  if (!f) formats.set(key, f = new Intl.DateTimeFormat(locale, kind === 'day' ? {timeZone: tz, month: 'short', day: 'numeric'}
    : {timeZone: tz, hour: 'numeric', minute: '2-digit', hour12: true}));
  return f;
};

const wformats = new Map<string, Intl.DateTimeFormat>();
/** "Tue 2 pm" (`hour`), "Oct 8, 5 pm" (`run`) or "Thu Oct 9, 3 pm" (`dated`) in the zone and language: the forms the current, swell and wind layers print. */
function moment(locale: string, tz: string, at: string | number, form: 'hour' | 'run' | 'dated'): string {
  const key = `${locale}|${tz}`;
  let f = wformats.get(key);
  if (!f) wformats.set(key, f = new Intl.DateTimeFormat(locale, {timeZone: tz, weekday: 'short', hour: 'numeric', hour12: true}));
  const when = new Date(at), p = Object.fromEntries(f.formatToParts(when).map(part => [part.type, part.value]));
  const hour = `${p.hour} ${(p.dayPeriod ?? '').toLowerCase()}`, day = format(locale, tz, 'day').format(when);
  return form === 'hour' ? `${p.weekday} ${hour}` : form === 'run' ? `${day}, ${hour}` : `${p.weekday} ${day}, ${hour}`;
}

/** The variable as the text or number the template takes, in `lang`; throws on a value that cannot be formatted. */
function resolveVar(v: StatusVar, lang: string): string | number {
  if (typeof v === 'string' || typeof v === 'number') return v;
  const locale = localeOf(lang);
  if ('id' in v) return t(v.id, lang, Object.fromEntries(Object.entries(v.vars ?? {}).map(([k, x]) => [k, resolveVar(x, lang)])));
  if ('day' in v) return format(locale, v.tz, 'day').format(new Date(v.day));
  if ('clock' in v) {
    const p = Object.fromEntries(format(locale, v.tz, 'clock').formatToParts(new Date(v.clock)).map(part => [part.type, part.value]));
    return `${p.hour}:${p.minute} ${(p.dayPeriod ?? '').toLowerCase()}`;
  }
  if ('moment' in v) return moment(locale, v.tz, v.moment, v.form);
  if ('num' in v) return new Intl.NumberFormat(locale, {minimumFractionDigits: v.digits, maximumFractionDigits: v.digits, useGrouping: false}).format(v.num);
  const h = Math.floor(Math.max(0, v.age) / HOUR);
  return h < 1 ? t('map.status.common.underHour', lang) : h < 72 ? t('map.status.common.hours', lang, {n: h}) : t('map.status.common.days', lang, {n: Math.floor(h / 24)});
}

const mark = (p: StatusPart, lang: string): MarkCopyPart =>
  typeof p === 'string' ? p : {id: p.id, vars: Object.fromEntries(Object.entries(p.vars ?? {}).map(([k, v]) => [k, resolveVar(v, lang)]))};

/** The parts in `lang` (also `en`, which the tests use to pin the catalogue to the producers' English); throws on a bad value. */
export const statusIn = (parts: readonly StatusPart[], lang: string): string => copyText(parts.map(p => mark(p, lang)), lang);

/** True when every catalogue id in the parts, nested ones included, exists. The browser's lookup returns an unknown id as text instead of throwing, so this is checked first. */
function known(parts: readonly StatusPart[]): boolean {
  const okVar = (v: StatusVar): boolean => typeof v !== 'object' || !('id' in v) || okId(v.id, v.vars);
  const okId = (id: string, vars?: Readonly<Record<string, StatusVar>>): boolean => Object.hasOwn(STRINGS, id) && Object.values(vars ?? {}).every(okVar);
  return parts.every(p => typeof p === 'string' || okId(p.id, p.vars));
}

/** `raw` shown in `lang`: `translated` is true only when a Spanish descriptor resolved; otherwise the producer's own string, unchanged. */
export function statusText(raw: string, parts: readonly StatusPart[] | undefined, lang: string): {readonly text: string; readonly translated: boolean} {
  if (lang !== 'es' || !parts?.length || !known(parts)) return {text: raw, translated: false};
  try {
    const text = statusIn(parts, lang);
    return text.trim() ? {text, translated: true} : {text: raw, translated: false};
  } catch { return {text: raw, translated: false}; }
}
/** The text of `statusText`. */
export const resolveStatusText = (raw: string, parts: readonly StatusPart[] | undefined, lang = 'en'): string => statusText(raw, parts, lang).text;

/** A short note with its longer reason. */
export const pair = (note: StatusPart, reason: StatusPart): StatusCopy => ({note: [note], reason: [reason]});
