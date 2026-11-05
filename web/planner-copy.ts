// SC0707-10: the planner's words in the chosen language. `plannerText` is a bounded presentation adapter for the planner's
// English model messages (web/planner.ts, the export contract, planner-alerts): it maps a COMPLETE known message, or an anchored
// whole-message template, to its catalogue Spanish and never rewrites part of a sentence. The finite set is the catalogue's `pm.*`
// ids, so English is read from the catalogue and there is no second copy here. English returns the input verbatim.
// Names, source text, URLs, file names and draft values are only ever captured as variables, never translated.
// Erasable syntax only: Node tests import this file by type stripping.
import {placeRefused, PLANNING_MARGIN_M, type PlaceVerdict} from '../dist/geo-screen.js';
import {exportEvidenceLabel, protectedHitReading} from '../dist/trip-export.js';
import {localeOf, num, STRINGS, t, type Language, type StringId} from './i18n.ts';
import {verdictLine} from './waypoint-placement.ts';

type Rule = {id: StringId; re: RegExp; names: string[]; weight: number};
const exact = new Map<string, StringId>();
const rules: Rule[] = [];
const escape = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
for (const id of Object.keys(STRINGS)) {
  if (!id.startsWith('pm.')) continue;
  const en = STRINGS[id]!.en, names = [...en.matchAll(/\{(\w+)\}/g)].map(m => m[1]!);
  if (!names.length) { exact.set(en, id as StringId); continue; }
  const source = en.split(/(\{\w+\})/).map(piece => /^\{\w+\}$/.test(piece) ? '([\\s\\S]*?)' : escape(piece)).join('');
  rules.push({id: id as StringId, re: new RegExp(`^${source}$`), names, weight: en.replace(/\{\w+\}/g, '').length});
}
rules.sort((a, b) => b.weight - a.weight);

/** `text` as one known message in `lang`, or null. Variables named `m_*` hold nested known messages. */
function match(text: string, lang: Language): string | null {
  const id = exact.get(text);
  if (id) return t(id, lang);
  for (const rule of rules) {
    const found = rule.re.exec(text);
    if (!found) continue;
    const vars: Record<string, string> = {};
    rule.names.forEach((name, i) => { const raw = found[i + 1]!; vars[name] = name.startsWith('m_') ? part(raw, lang) ?? raw : raw; });
    return t(rule.id, lang, vars);
  }
  return null;
}

/** A nested message: one known message, or known sentences in a row; its outer spacing is kept. Null when any sentence is unknown. */
function part(text: string, lang: Language): string | null {
  const core = text.trim();
  if (!core) return text;
  const lead = text.slice(0, text.length - text.trimStart().length), trail = text.slice(text.trimEnd().length);
  const whole = match(core, lang);
  if (whole !== null) return lead + whole + trail;
  const pieces = core.split(/(?<=\.)(\s+)/);
  if (pieces.length < 3) return null;
  const out = pieces.map((p, i) => i % 2 ? p : match(p, lang));
  return out.some(p => p === null) ? null : lead + out.join('') + trail;
}

/** The planner's English message in `lang`. English and an empty message pass through; an unknown technical message keeps its detail inside the Spanish wrapper. */
export function plannerText(text: string, lang: Language = 'en'): string {
  if (lang !== 'es' || text === '') return text;
  return match(text, lang) ?? t('planner.unknown', lang, {detail: text});
}

/** The line a refused screen verdict adds ("Dentro de X"), read from its fields; null when it is not refused. English is `verdictLine` itself. */
export function plannerVerdict(v: PlaceVerdict, lang: Language = 'en'): string | null {
  if (lang !== 'es') return verdictLine(v);
  if (!placeRefused(v)) return null;
  if (!v.screened) return t('pm.verdict.unchecked', lang);
  const named = v.name !== null && v.name !== undefined;
  if (v.inside) return named ? t('pm.verdict.inside', lang, {name: v.name!}) : t('pm.verdict.insideFallback', lang);
  const n = Math.round(v.distanceM ?? 0);
  return named ? t('pm.verdict.near', lang, {n, name: v.name!}) : t('pm.verdict.nearFallback', lang, {n});
}

/** A protected-area hit's reading from its fields (inside, reef), not from translated words. */
export function hitReading(h: {inside: boolean; reef: boolean}, lang: Language = 'en'): string {
  if (lang !== 'es') return protectedHitReading(h) as string;
  return h.inside ? t('planner.hit.inside', lang) : t(h.reef ? 'planner.hit.reefNear' : 'planner.hit.near', lang, {n: PLANNING_MARGIN_M as number});
}

/** The export class of a target: measured reef or research coordinate. */
export function evidenceLabel(target: {canonical_habitat?: boolean} | undefined, lang: Language = 'en'): string {
  if (lang !== 'es') return exportEvidenceLabel(target) as string;
  return t(target?.canonical_habitat === true ? 'planner.evidence.measured' : 'planner.evidence.research', lang);
}

/** A habitat fit (3, 2, 1) as a word; anything else is Unknown. */
export const fitText = (fit: number | undefined, lang: Language = 'en'): string => t(`planner.fit.${fit === 3 || fit === 2 || fit === 1 ? fit : 0}` as StringId, lang);

const CATEGORIES = ['reef', 'wreck', 'bait', 'hazard', 'other'];
/** A waypoint category by its stable value; an unknown value is shown as it was stored. */
export const categoryText = (category: string, lang: Language = 'en'): string => CATEGORIES.includes(category) ? t(`planner.category.${category}` as StringId, lang) : category;

/** A distance with one decimal: English keeps toFixed(1), Spanish reads the platform's format. */
export const nmText = (n: number, lang: Language = 'en'): string => lang === 'es' ? num(n, lang, 1) : n.toFixed(1);
/** A count with thousands separators, as the page's locale writes it. */
export const countText = (n: number, lang: Language = 'en'): string => lang === 'es' ? n.toLocaleString(localeOf(lang)) : n.toLocaleString();
