// Fish ID for anglers (docs/plans/text-advisor/06-angler-answers.md § Fish ID,
// ID-1, ID-2, ID-3; 07 § thresholds): vision's identifyFish, then one of three
// reply shapes composed here from catalog/advisor/strings.json, with no model
// call:
//
//   high   (>= 0.85)  "That's a {label}. {cue}."                   then the rules (Spanish cues: lookalikes.json cues_es, TA-A6)
//   medium (>= 0.6)   "Looks like a {label}, could be a {second}:   then the rules, and
//                      check for {cue} ({label}) or {cue} ({second})."  "If it's a {second}: ..." when they differ
//   ask    (else, or needs_better_photo)
//                     "Not sure from this one. {reason}: can you send a side-on shot with the fins spread?"
//
// Any candidate of a must-release species (catalog/advisor/protected.json:
// yelloweye, cowcod, bronzespotted) at confidence >= 0.3 adds the release line,
// whatever the band (decideProtected; 06 now says ">= 0.3", not "any
// confidence"). Rules come only from the rules table (answers/rules.ts); a stale
// row is never quoted with numbers, only "due for review: double-check" and the
// rules link. The photo stays private; the AC-1 share offer is added by the
// caller (fishid is shared by the engine's media path and identify_fish).
import {decideFishBand, decideProtected, THRESHOLDS} from '../vision/index.ts';
import type {FishId, FishBand} from '../vision/index.ts';
import {PROTECTED, speciesCues, speciesName, canonicalSpecies} from '../vision/species.ts';
import type {ProtectedSpecies} from '../vision/species.ts';
import {lookupRules} from './rules.ts';
import type {Rule} from './rules.ts';
import {t} from '../strings.ts';
import type {StringKey} from '../strings.ts';
import synonyms from '../../../catalog/advisor/species-synonyms.json' with {type: 'json'};
import {contactRegion} from './resolve.ts';
import {imageOf} from '../intake/reports.ts';
import {MediaTooLarge} from '../vision/index.ts';
import type {VisionChain} from '../vision/index.ts';
import {advisorLog} from '../log.ts';
import type {Env} from '../../env.ts';
import type {AdvisorContactRow, AdvisorSettings, Language} from '../types.ts';

/** The stored photo a fish ID reads (an advisor_media row's columns). */
export interface MediaInput {id: string; mime: string; width: number | null; height: number | null; r2_key: string}

export type {FishBand} from '../vision/index.ts';

/** The rule facts a reply quotes (null fields are left out of the text). */
export interface RuleSummary {
  species_key: string; label: string; applies_as: 'species' | 'group'; stale: boolean;
  size_min_in: number | null; size_max_in: number | null; bag_limit: number | null; season_open: string | null; season_close: string | null;
  depth_limit_ft: number | null; source_name: string; source_url: string; checked: string;
}
export interface FishIdAnswer {
  band: FishBand;
  top: {species_key: string | null; label: string; confidence: number} | null;
  second: {species_key: string | null; label: string; confidence: number} | null;
  needs_better_photo: boolean; reason: string | null;
  protected: string[];                          // must-release keys among candidates >= 0.3
  rules: RuleSummary | null;                    // the top candidate's (high and medium only)
  second_rules: RuleSummary | null;             // the second's, only when it differs from the top's
  /** The reply text (links still as placeholders). */
  text: string;
  /** True when the AC-1 share offer may follow: the top candidate is >= 0.6 (the caller checks the role). */
  offer_eligible: boolean;
}

const ES = synonyms.species as Record<string, {en: string[]; es: string[]}>;

/**
 * The name a reply uses for a candidate, lower-case except proper nouns: the
 * catalog name for its key (else the provider's label); in Spanish the first
 * Spanish synonym when the catalog has one ("colorado", "ojo amarillo").
 */
export function speciesLabel(c: {species_key: string | null; label: string}, language: Language): string {
  const key = c.species_key ? canonicalSpecies(c.species_key) : null;
  if (language === 'es' && key && ES[key]?.es?.length) return ES[key]!.es[0]!;
  const name = (key && speciesName(key)) || c.label;
  return /^(?:California|Pacific|King|Chinook|Dungeness)\b/.test(name) ? name : name.charAt(0).toLowerCase() + name.slice(1);
}
/** "a vermilion rockfish", "an albacore tuna", "un colorado" (strings article_a / article_an). */
export const withArticle = (label: string, language: Language): string => t(language, /^[aeiou]/i.test(label) ? 'article_an' : 'article_a', {label});
const sentence = (s: string): string => { const x = s.trim().replace(/[.\s]+$/, ''); return x ? x.charAt(0).toUpperCase() + x.slice(1) + '.' : ''; };

const STOP = new Set(['with', 'body', 'often', 'along', 'across', 'the', 'and', 'from', 'that', 'than', 'side', 'fins', 'young', 'fish', 'adults']);
const words = (s: string): Set<string> => new Set(s.toLowerCase().split(/[^a-z]+/).filter(w => w.length >= 3 && !STOP.has(w)));

/**
 * The pair of look-alike cues that tells two species apart: the cues of each
 * (catalog/advisor/lookalikes.json, else the provider's) that share a feature
 * word ("lower jaw" against "lower jaw"), else the first cue of each. The
 * match is made on the English cues; in Spanish (TA-A6) the pair is the
 * catalog's `cues_es` at the same places, or null when either species has
 * none (the provider's cues are English only).
 */
export function contrastingCues(a: {species_key: string | null; cues?: string[]}, b: {species_key: string | null; cues?: string[]}, language: Language = 'en'): [string, string] | null {
  const ca = speciesCues(a.species_key).length ? speciesCues(a.species_key) : (a.cues ?? []);
  const cb = speciesCues(b.species_key).length ? speciesCues(b.species_key) : (b.cues ?? []);
  if (!ca.length || !cb.length) return null;
  let best: [number, number] = [0, 0], score = 0;
  ca.forEach((x, i) => cb.forEach((y, j) => {
    const wy = words(y), shared = [...words(x)].filter(w => wy.has(w)).length;
    if (shared > score) { best = [i, j]; score = shared; }
  }));
  if (language !== 'es') return [ca[best[0]]!, cb[best[1]]!];
  const ea = speciesCues(a.species_key, 'es'), eb = speciesCues(b.species_key, 'es');
  return ea[best[0]] && eb[best[1]] ? [ea[best[0]]!, eb[best[1]]!] : null;
}

const REASONS: Record<string, StringKey> = {blurry: 'fishid_reason_blurry', partial: 'fishid_reason_partial', multiple_fish: 'fishid_reason_multiple', no_fish: 'fishid_reason_no_fish', too_far: 'fishid_reason_too_far'};

// ---- rules (ID-2) -------------------------------------------------------------------------

const MONTHS: Record<Language, string[]> = {
  en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
  es: ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'],
};
/** "Apr 1" / "1 abr" from YYYY-MM-DD or MM-DD; the input itself when it is neither. */
export function monthDay(date: string | null, language: Language): string | null {
  if (!date) return null;
  const m = /^(?:\d{4}-)?(\d{2})-(\d{2})$/.exec(date);
  if (!m) return date;
  const month = MONTHS[language][Number(m[1]) - 1], day = Number(m[2]);
  if (!month || !day) return date;
  return language === 'es' ? `${day} ${month}` : `${month} ${day}`;
}

/** The row a reply quotes for a species: its own row first, else its group's (rockfish for a vermilion). */
export function pickRule(rules: readonly Rule[]): Rule | null {
  return rules.find(r => r.applies_as === 'species') ?? rules.find(r => r.applies_as === 'group') ?? null;
}
const summary = (r: Rule): RuleSummary => ({species_key: r.species_key, label: r.species_label, applies_as: r.applies_as, stale: r.stale,
  size_min_in: r.size_min_in, size_max_in: r.size_max_in, bag_limit: r.bag_limit, season_open: r.season_open, season_close: r.season_close,
  depth_limit_ft: r.depth_limit_ft, source_name: r.source_name, source_url: r.source_url, checked: r.reviewed_at.slice(0, 10)});

/** The parts of a rule in words: size, bag, season, depth. Empty when the row states none. */
export function ruleParts(r: RuleSummary, language: Language): string[] {
  const parts: string[] = [];
  const n = (v: number) => String(Number.isInteger(v) ? v : Math.round(v * 100) / 100);
  if (r.size_min_in !== null) parts.push(t(language, 'rule_size_min', {n: n(r.size_min_in)}));
  if (r.size_max_in !== null) parts.push(t(language, 'rule_size_max', {n: n(r.size_max_in)}));
  if (r.bag_limit === 0) parts.push(t(language, 'rule_no_take'));
  else if (r.bag_limit !== null) parts.push(t(language, 'rule_bag', {n: r.bag_limit}));
  if (r.season_open && r.season_close) parts.push(t(language, 'rule_season', {open: monthDay(r.season_open, language)!, close: monthDay(r.season_close, language)!}));
  else if (!r.season_open && !r.season_close && r.bag_limit !== 0) parts.push(t(language, 'rule_year_round'));
  if (r.depth_limit_ft !== null) parts.push(t(language, 'rule_depth', {n: r.depth_limit_ft}));
  return parts;
}
const sameRule = (a: RuleSummary, b: RuleSummary): boolean => a.stale === b.stale &&
  (['size_min_in', 'size_max_in', 'bag_limit', 'season_open', 'season_close', 'depth_limit_ft'] as const).every(k => a[k] === b[k]);

/**
 * The rules sentences (06 § fish ID step 3): "Rules ({source}, checked {date}):
 * {size}, {bag}, {season}." then, for a medium ID whose look-alike has a
 * different rule, "If it's a {second}: ...", then "Double-check before you keep
 * it: {{link:rules:<key>}}". A stale row is never quoted with numbers. No row:
 * the CDFW line with the rules link.
 */
export function rulesText(top: RuleSummary | null, topKey: string, second: {rule: RuleSummary; label: string} | null, language: Language): string {
  const link = `{{link:rules:${topKey}}}`;
  if (!top) return t(language, 'fishid_rules_none', {link});
  const head = {source: top.source_name, date: monthDay(top.checked, language)!};
  const out: string[] = [];
  if (top.stale) out.push(t(language, 'fishid_rules_stale', {...head, link}));
  else {
    const parts = ruleParts(top, language);
    out.push(parts.length ? t(language, 'fishid_rules', {...head, parts: parts.join(', ')}) : t(language, 'fishid_rules_see', head));
  }
  if (second) {
    const parts = ruleParts(second.rule, language);
    out.splice(top.stale ? 0 : 1, 0, second.rule.stale || !parts.length
      ? t(language, 'fishid_rules_second_stale', {a_second: withArticle(second.label, language)})
      : t(language, 'fishid_rules_second', {a_second: withArticle(second.label, language), parts: parts.join(', ')}));
  }
  if (!top.stale) out.push(t(language, 'fishid_rules_link', {link}));
  return out.join(' ');
}

// ---- the answer ---------------------------------------------------------------------------

/** The must-release names for the warning, in candidate order: "yelloweye rockfish" or "yelloweye rockfish or cowcod". */
function protectedLine(hits: readonly ProtectedSpecies[], language: Language): string | null {
  const release = hits.filter(p => p.must_release);
  if (!release.length) return null;
  const names = release.map(p => speciesLabel({species_key: p.key, label: p.key}, language));
  const joined = names.length === 1 ? names[0]! : t(language, 'words_or', {a: names.slice(0, -1).join(', '), b: names.at(-1)!});
  return t(language, 'fishid_protected', {names: joined});
}

export interface AnswerDeps {db: D1Database; region: string; now: number; language: Language}

/** The rules for a candidate's key: the quoted row, or null (no key, no row). */
async function rulesFor(deps: AnswerDeps, key: string | null): Promise<RuleSummary | null> {
  if (!key) return null;
  const row = pickRule(await lookupRules(deps.db, {region: deps.region, speciesKey: key, now: deps.now}));
  return row ? summary(row) : null;
}

/** Compose the reply for a FishId (no I/O but the rules table). */
export async function answerFor(id: FishId, deps: AnswerDeps): Promise<FishIdAnswer> {
  const {language} = deps;
  const band = decideFishBand(id);
  const [c0, c1] = id.candidates;
  const top = c0 ? {species_key: c0.species_key, label: c0.label, confidence: c0.confidence} : null;
  const second = c1 ? {species_key: c1.species_key, label: c1.label, confidence: c1.confidence} : null;
  const hits = decideProtected(id, PROTECTED);
  const warn = protectedLine(hits, language);
  const parts: string[] = [];
  let rules: RuleSummary | null = null, secondRules: RuleSummary | null = null;
  if (band === 'ask' || !c0) {
    const reason = id.reason && REASONS[id.reason] ? t(language, REASONS[id.reason]!) : t(language, 'fishid_reason_unsure');
    parts.push(t(language, 'fishid_ask', {reason}));
    if (warn) parts.push(warn);
  } else {
    const label = speciesLabel(c0, language);
    if (band === 'high') {
      // TA-A6: a Spanish reply uses the catalog's cues_es; the provider's cues are English, so without a catalog cue it leaves the cue out.
      const cue = language === 'es' ? speciesCues(c0.species_key, 'es')[0] ?? null : speciesCues(c0.species_key)[0] ?? c0.cues[0] ?? null;
      parts.push(t(language, 'fishid_high', {a_label: withArticle(label, language)}) + (cue ? ` ${sentence(cue)}` : ''));
    } else if (c1) {
      const label2 = speciesLabel(c1, language);
      const cues = contrastingCues(c0, c1, language);
      parts.push(cues ? t(language, 'fishid_medium', {a_label: withArticle(label, language), a_second: withArticle(label2, language), cue: cues[0], label, cue2: cues[1], second: label2})
        : t(language, 'fishid_medium_plain', {a_label: withArticle(label, language), a_second: withArticle(label2, language)}));
    } else {
      parts.push(t(language, 'fishid_medium_alone', {a_label: withArticle(label, language)}));
    }
    if (warn) parts.push(warn);
    rules = await rulesFor(deps, c0.species_key);
    if (band === 'medium' && c1?.species_key && c1.species_key !== c0.species_key) {
      const r2 = await rulesFor(deps, c1.species_key);
      if (r2 && (!rules || !sameRule(rules, r2))) secondRules = r2;
    }
    const topKey = c0.species_key ? canonicalSpecies(c0.species_key) : 'rockfish';
    parts.push(c0.species_key ? rulesText(rules, topKey, secondRules && c1 ? {rule: secondRules, label: speciesLabel(c1, language)} : null, language)
      : t(language, 'fishid_rules_none', {link: '{{link:rules}}'}));
  }
  return {band, top, second, needs_better_photo: id.needs_better_photo, reason: id.reason,
    protected: hits.filter(p => p.must_release).map(p => p.key), rules, second_rules: secondRules,
    text: parts.filter(Boolean).join(' '), offer_eligible: band !== 'ask' && (c0?.confidence ?? 0) >= THRESHOLDS.fishMedium};
}

/** AC-1 (06 § fish ID step 5): the share offer only after an ID at >= 0.6, and never for a skipper or crew (their photos go through intake). */
export const offerShare = (answer: Pick<FishIdAnswer, 'offer_eligible'>, role: string): boolean => answer.offer_eligible && role !== 'skipper' && role !== 'crew';

// ---- the vision call ----------------------------------------------------------------------

export interface IdentifyDeps {vision: VisionChain; language: Language; now: number; settings: Pick<AdvisorSettings, 'regionDefault'>}
export type IdentifyResult = {ok: true; id: FishId; answer: FishIdAnswer} | {ok: false; error: 'too_large' | 'unavailable'};

/**
 * 06 § fish ID: vision's identifyFish on one stored photo (the region is the
 * contact's: its home port's, else ADVISOR_REGION_DEFAULT), then the reply.
 * The result is cached on the media row by the chain, so a retried message
 * never re-runs vision. Vision errors come back as {ok: false}.
 */
export async function identify(env: Env, media: MediaInput, contact: Pick<AdvisorContactRow, 'home_port'>, deps: IdentifyDeps): Promise<IdentifyResult> {
  const region = contactRegion(contact, deps.settings);
  let id: FishId;
  try {
    id = await deps.vision.identifyFish(imageOf(env, media), region);
  } catch (error) {
    if (error instanceof MediaTooLarge) return {ok: false, error: 'too_large'};
    advisorLog('warn', 'advisor_fishid_failed', {name: (error as Error)?.name ?? 'Error'});
    return {ok: false, error: 'unavailable'};
  }
  const answer = await answerFor(id, {db: env.DB!, region, now: deps.now, language: deps.language});
  advisorLog('info', 'advisor_fishid', {band: answer.band, protected: answer.protected.length > 0, rules: answer.rules ? (answer.rules.stale ? 'stale' : 'ok') : 'none'});
  return {ok: true, id, answer};
}
