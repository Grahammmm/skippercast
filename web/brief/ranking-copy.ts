// SC1137-05: the words web/ranking.ts and web/area-reasons.ts write for the Where to look list, in the page's language.
// Both modules keep their plain English fields (the Run line, the planner, GPX, offline notes, sharing and telemetry read those);
// they also attach catalogue parts, and this file is the one place that turns parts into words. English returns the plain field
// untouched; a list, pick or reason built without parts is shown as it came. Published names and prose are never parts.
// Erasable syntax only (Node tests import this).
import {t, type Language, type StringId} from '../i18n.ts';
import type {CopyVar, MarkCopyPart} from '../mark-copy.ts';
import type {Reason} from '../area-reasons.ts';
import type {Pick, Ranking} from '../ranking.ts';

/** Variables that carry a decimal number the code formatted (3.0, 12.5): Spanish writes the comma. */
const DECIMAL = new Set(['nm', 'm', 'ha']);
const value = (v: CopyVar, lang: string, name: string): string | number => {
  if (typeof v === 'string' || typeof v === 'number') return lang === 'es' && DECIMAL.has(name) ? String(v).replace('.', ',') : v;
  if ('id' in v) return part(v, lang);
  return (v as readonly CopyVar[]).map(x => String(value(x, lang, name))).join('');
};
const part = (p: MarkCopyPart, lang: string): string =>
  typeof p === 'string' ? p : t(p.id, lang, Object.fromEntries(Object.entries(p.vars ?? {}).map(([k, v]) => [k, value(v, lang, k)])));

/** The parts' words in `lang`. */
export const partsText = (parts: readonly MarkCopyPart[], lang: string): string => parts.map(p => part(p, lang)).join('');
const shown = (parts: readonly MarkCopyPart[] | undefined, plain: string, lang: string): string => lang === 'es' && parts ? partsText(parts, lang) : plain;

export const rankingLabel = (r: Ranking, lang: Language): string => shown(r.copy?.label, r.label, lang);
export const rankingBasis = (r: Ranking, lang: Language): string => shown(r.copy?.basis, r.basis, lang);
export const rankingEmpty = (r: Ranking, lang: Language): string => shown(r.copy?.empty, r.empty, lang);
/** The popover's summary: the source's own grammatical sentence in Spanish; English (and a list with no parts) lowercases the label as before. */
export const rankingAbout = (r: Ranking, lang: Language): string =>
  lang === 'es' && r.copy?.about ? partsText(r.copy.about, lang) : t('where.about', lang, {label: rankingLabel(r, lang).toLowerCase()});

export const pickName = (p: Pick, lang: Language): string => shown(p.copy?.name, p.name, lang);
export const pickFit = (p: Pick, lang: Language): string => shown(p.copy?.fit, p.fit, lang);
export const pickReason = (p: Pick, lang: Language): string => shown(p.copy?.reason, p.reason, lang);
/** The straight-from-shore distance (Spear); a routed or plain distance is handled by the list itself. */
export const pickDistance = (p: Pick, lang: Language): string => shown(p.copy?.distance, p.distance, lang);

const REASON: Readonly<Record<NonNullable<Reason['copy']>['key'], StringId>> = {survey: 'ranking.reason.surveyed', clearance: 'ranking.reason.clearance'};
/** A dated reason's text: the sentence the code wrote in Spanish; a published sentence, and English, as they came. */
export const reasonText = (r: Reason, lang: Language): string =>
  lang === 'es' && r.copy && Object.hasOwn(REASON, r.copy.key) ? t(REASON[r.copy.key], lang, r.copy.m === undefined ? {} : {m: r.copy.m}) : r.text;
