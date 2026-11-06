// Pure target-plan presentation. Reviewed source text stays verbatim.
import {t, type Language} from './i18n.ts';
import type {Plan, TargetState} from './species.ts';
type Section = {title: string; text: string};
export type Link = {title: string; href: string};
export type PlanViewModel =
  | {kind: 'plan'; name: string; lifeStage: string; sections: Section[]; confirm: string[]; evidence: {basis: string; links: Link[]}; reviewedAt: string | null}
  | {kind: 'unresearched'; reason: string}
  | {kind: 'withheld'; name: string; reason: string}
  | {kind: 'unknown'; id: string}
  | {kind: 'loading'};
/** The generated fallback sentences in `lang` (English by default). */
export const planCopy = (lang: Language = 'en') => ({
  withheld: t('plan.withheld', lang), unresearched: t('plan.unresearched', lang),
  unknown: t('plan.unknown', lang), loading: t('plan.loading', lang),
});
export const PLAN_COPY = planCopy('en');
const text = (s: unknown): s is string => typeof s === 'string' && s.trim().length > 0;
const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);
export const trustworthy = (p: Plan): boolean => isRecord(p) && p.numeric_bite_model === false;
/**
 * SC2207-01: the safe source links of a plan's `source_links` as the data writes them, `{title, url}`. Each entry needs a
 * nonblank title and an https URL with no credentials; one bad entry never drops its siblings. Titles and URLs stay as given.
 */
export function sourceLinks(input: unknown): Link[] {
  if (!Array.isArray(input)) return [];
  const links: Link[] = [];
  for (const l of input as unknown[]) {
    if (!l || typeof l !== 'object' || Array.isArray(l)) continue;
    const {title, url} = l as {title?: unknown; url?: unknown};
    if (!text(title) || !text(url)) continue;
    try { const u = new URL(url); if (u.protocol === 'https:' && !u.username && !u.password) links.push({title, href: url}); } catch { /* malformed */ }
  }
  return links;
}
// Section titles are code-written; the section bodies are reviewed text and stay as published.
const fields = [['plan.sec.search', 'search_for'], ['plan.sec.habitat', 'habitat'], ['plan.sec.fish', 'presentation'],
  ['plan.sec.fish', 'method'], ['plan.sec.timing', 'timing'], ['plan.sec.change', 'condition_response'], ['plan.sec.caution', 'caution']] as const;
export function planView(plans: Readonly<Record<string, Plan>> | null, id: string, state: TargetState | null,
  unavailable: Readonly<Record<string, string>> = {}, reviewedAt: string | null = null, lang: Language = 'en'): PlanViewModel {
  const copy = planCopy(lang);
  if (!plans) return {kind: 'loading'};
  if (!id.trim() || ['__proto__', 'constructor', 'toString'].includes(id)) return {kind: 'unknown', id};
  if (Object.hasOwn(unavailable, id)) return {kind: 'unresearched', reason: unavailable[id]!};
  if (!Object.hasOwn(plans, id)) return state === 'unresearched' ? {kind: 'unresearched', reason: copy.unresearched} : {kind: 'unknown', id};
  const p = plans[id]!;
  if (!trustworthy(p)) return {kind: 'withheld', name: isRecord(p) && typeof p.name === 'string' ? p.name : id, reason: copy.withheld};
  const links = sourceLinks(p.source_links);
  return {kind: 'plan', name: p.name ?? id, lifeStage: p.life_stage ?? '',
    sections: fields.flatMap(([title, key]) => text(p[key]) ? [{title: t(title, lang), text: p[key]!}] : []),
    confirm: (Array.isArray(p.required_to_confirm) ? p.required_to_confirm : []).filter(text),
    evidence: {basis: text(p.tactics_basis) ? p.tactics_basis : '', links}, reviewedAt};
}
