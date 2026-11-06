// SC0922-09: display-only wording for a mark. A producer may attach `copy` parts to a ChartMark; the card
// resolves them in the page's language at render. English returns the mark's own strings untouched, and a
// mark with no metadata is shown exactly as it is. Nothing here changes a mark's identity or decisions.
// Erasable syntax only (Node tests import this).
import {t, type StringId} from './i18n.ts';
import type {ChartMark} from './map/coastline.ts';

/** A variable of a catalogue string: a value, another catalogue string (with its own variables), or a list of those joined in order. */
export type CopyVar = string | number | {readonly id: StringId; readonly vars?: Readonly<Record<string, CopyVar>>} | readonly CopyVar[];
export type MarkCopyPart = string | {readonly id: StringId; readonly vars?: Readonly<Record<string, CopyVar>>};
export type MarkCopyFields = Partial<Readonly<Record<'name' | 'kind' | 'reading' | 'source' | 'basis' | 'rules' | 'regulationsLabel', readonly MarkCopyPart[]>>>;

const value = (v: CopyVar, lang: string): string | number =>
  typeof v === 'string' || typeof v === 'number' ? v : 'id' in v ? render({id: v.id, vars: v.vars}, lang) : (v as readonly CopyVar[]).map(x => String(value(x, lang))).join('');
const render = (p: {readonly id: StringId; readonly vars?: Readonly<Record<string, CopyVar>>}, lang: string): string =>
  t(p.id, lang, Object.fromEntries(Object.entries(p.vars ?? {}).map(([k, v]) => [k, value(v, lang)])));
const join = (parts: readonly MarkCopyPart[], lang: string): string =>
  parts.map(p => typeof p === 'string' ? p : render(p, lang)).join('');

/** The text of parts in `lang`. */
export const copyText = (parts: readonly MarkCopyPart[], lang: string): string => join(parts, lang);
/** SC0922-10: a catalogue part for producers (a plain object; nothing is resolved until the card renders). */
export const cp = (id: StringId, vars?: Readonly<Record<string, CopyVar>>): MarkCopyPart => vars ? {id, vars} : {id};
/** Parts for several pieces in order with `sep` between them; a piece that is empty is left out (as the producers' own joins do). */
export function joinParts(items: readonly (readonly MarkCopyPart[] | string | false | null | undefined)[], sep: string): MarkCopyPart[] {
  const out: MarkCopyPart[] = [];
  for (const item of items) {
    const parts = typeof item === 'string' ? (item.trim() ? [item] : []) : item || [];
    if (!parts.length) continue;
    if (out.length) out.push(sep);
    out.push(...parts);
  }
  return out;
}

export interface MarkDisplay {
  readonly name: string; readonly kind: string; readonly reading: string; readonly source: string; readonly basis: string;
  readonly rules: string | undefined; readonly regulationsLabel: string | undefined; readonly terms: readonly (string | undefined)[];
}

/** The mark's display fields in `lang`; the raw fields for English or when no descriptor is attached. */
export function resolveMarkCopy(mark: ChartMark, lang: string): MarkDisplay {
  const c = lang === 'es' ? mark.copy : undefined, pick = (key: keyof MarkCopyFields, raw: string): string => c?.[key] ? join(c[key]!, lang) : raw;
  return {
    name: pick('name', mark.name), kind: pick('kind', mark.kind), reading: pick('reading', mark.reading), source: pick('source', mark.source),
    basis: pick('basis', mark.basis), rules: mark.rules === undefined ? undefined : pick('rules', mark.rules),
    regulationsLabel: mark.regulations ? pick('regulationsLabel', mark.regulations.label) : undefined,
    terms: (mark.terms ?? []).map((_, i) => lang === 'es' && mark.copyTerms?.[i] ? join(mark.copyTerms[i]!, lang) : undefined),
  };
}

// SC1352-05: Spanish display forms for station and ring readings, formatted when the descriptor is built (a
// language change only picks the descriptor; nothing is refetched). Exactly one decimal, as the English toFixed(1).
const esOne = new Intl.NumberFormat('es', {minimumFractionDigits: 1, maximumFractionDigits: 1, useGrouping: false});
export const esDecimal = (n: number): string => esOne.format(n);
/** An instant as a Spanish date and clock time in `tz` (a midnight boundary stays visible); the raw text when it is not an instant or the zone is unknown. */
export function esStamp(at: unknown, tz: string, zoneName = false): string {
  const ms = typeof at === 'string' || typeof at === 'number' ? Date.parse(String(at)) : NaN;
  if (!Number.isFinite(ms)) return String(at);
  try {
    return new Intl.DateTimeFormat('es', {timeZone: tz, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, ...(zoneName ? {timeZoneName: 'short'} : {})}).format(new Date(ms));
  } catch { return String(at); }
}
