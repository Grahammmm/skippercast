// SC0922-13: the Reports page's words in the page's language. Display only: the loaded sections, their source
// clocks, counts and links are never changed or re-fetched here; a language change re-renders from the raw
// metadata web/reports.ts keeps beside each English text. English keeps its original strings (the catalogue's
// English values reproduce them; catchCopy is undefined for English so catchSheet keeps its own text).
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {CatchCopy} from '../packages/coast/src/ui/catches.ts';
import {localeOf, t, type Language} from './i18n.ts';
import type {Evidence, EvidenceRow, ReasonKind} from './reports.ts';
import {DEFAULT_ZONE} from './zone.ts';

const DAY_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/** A report date in `lang`: a bare date is a civil date (read in UTC), a timestamp is an instant in `timeZone` (the loaded region's, else the default); anything else "date unavailable". */
export function reportDay(iso: string | null | undefined, lang: Language, timeZone: string = DEFAULT_ZONE): string {
  const at = iso ? Date.parse(DAY_ONLY.test(iso) ? `${iso}T12:00:00Z` : iso) : NaN;
  return Number.isFinite(at)
    ? new Intl.DateTimeFormat(localeOf(lang), {month: 'short', day: 'numeric', year: 'numeric', timeZone: DAY_ONLY.test(iso ?? '') ? 'UTC' : timeZone}).format(at)
    : t('reports.dateNA', lang);
}

/** "1 reported trip" / "2 reported trips" (one only for exactly 1); whole templates, never a noun glued to a number. */
export const countPhrase = (kind: 'trips' | 'boats' | 'days', n: number, lang: Language): string => t(`reports.${kind}.${n === 1 ? 'one' : 'other'}`, lang, {n});

const REASON_IDS = {stale: 'reports.reason.stale', coverage: 'reports.reason.coverage', none: 'reports.reason.none', strong: 'reports.reason.strong', thin: 'reports.reason.thin'} as const satisfies Record<ReasonKind, string>;
const CONFIDENCE_IDS: Readonly<Record<string, 'reports.conf.insufficient' | 'reports.conf.low' | 'reports.conf.moderate'>> = {Insufficient: 'reports.conf.insufficient', Low: 'reports.conf.low', Moderate: 'reports.conf.moderate'};

export interface EvidenceText {
  readonly confidence: string;
  /** null: no presentation metadata, so the English reason must be shown labelled as English. */
  readonly reason: string | null;
}
/** The confidence word and reason of `evidence` in `lang`. English is the producer's own text. */
export function evidenceCopy(evidence: Evidence, lang: Language): EvidenceText {
  if (lang !== 'es') return {confidence: evidence.confidence, reason: evidence.reason};
  const id = Object.hasOwn(CONFIDENCE_IDS, evidence.confidence) ? CONFIDENCE_IDS[evidence.confidence] : undefined;
  const kind = evidence.reasonKind;
  return {
    confidence: id ? t(id, lang) : evidence.confidence,
    reason: kind && Object.hasOwn(REASON_IDS, kind) ? t(REASON_IDS[kind], lang, {coverage: evidence.coverage ?? 0}) : null,
  };
}

export interface RowText {readonly catches: string; readonly where: string; readonly translated: boolean}
/** One evidence row's catch and place lines in `lang`; `translated` false when the row lacks the raw facts (English kept, labelled by the view). */
export function rowCopy(row: EvidenceRow, lang: Language): RowText {
  if (lang !== 'es' || !row.items) return {catches: row.catches, where: row.where, translated: lang !== 'es'};
  return {
    catches: row.items.map(c => t(c.released ? 'reports.catch.released' : 'reports.catch.reported', lang, {n: c.count, species: c.label})).join(' · '),
    where: row.ground ? t('reports.where.ground', lang, {ground: row.ground}) : t('reports.where.port', lang, {port: row.port ?? t('reports.where.portFallback', lang)}),
    translated: true,
  };
}

/** How long ago `at` was in `lang`: catches.ts ageLabel's thresholds, the catalogue's words. */
function age(at: string, now: Date, lang: Language): string {
  const minutes = Math.round((now.getTime() - Date.parse(at)) / 60000);
  if (!Number.isFinite(minutes) || minutes < 0) return t('reportCatch.age.na', lang);
  if (minutes < 2) return t('reportCatch.age.now', lang);
  if (minutes < 60) return t('reportCatch.age.min', lang, {n: minutes});
  if (minutes < 1440) return t('reportCatch.age.hour', lang, {n: Math.floor(minutes / 60)});
  return t('reportCatch.age.day', lang, {n: Math.floor(minutes / 1440)});
}

/** catchSheet's host copy: undefined for English (the renderer's own text), the catalogue for anything else. */
export function catchCopy(lang: Language): CatchCopy | undefined {
  if (lang === 'en') return undefined;
  return {
    text: (key, vars) => t(key, lang, vars),
    date: day => new Intl.DateTimeFormat(localeOf(lang), {timeZone: 'UTC', month: 'short', day: 'numeric'}).format(new Date(Date.parse(day + 'T00:00:00Z'))),
    age: (at, now) => age(at, now, lang),
  };
}
