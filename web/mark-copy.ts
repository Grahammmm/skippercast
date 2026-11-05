// SC0922-09: display-only wording for a mark. A producer may attach `copy` parts to a ChartMark; the card
// resolves them in the page's language at render. English returns the mark's own strings untouched, and a
// mark with no metadata is shown exactly as it is. Nothing here changes a mark's identity or decisions.
// Erasable syntax only (Node tests import this).
import {t, type StringId} from './i18n.ts';
import type {ChartMark} from './map/coastline.ts';

export type MarkCopyPart = string | {readonly id: StringId; readonly vars?: Readonly<Record<string, string | number>>};
export type MarkCopyFields = Partial<Readonly<Record<'name' | 'kind' | 'reading' | 'source' | 'basis' | 'rules' | 'regulationsLabel', readonly MarkCopyPart[]>>>;

const join = (parts: readonly MarkCopyPart[], lang: string): string =>
  parts.map(p => typeof p === 'string' ? p : t(p.id, lang, p.vars)).join('');

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
