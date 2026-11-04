// BF-one-answer: the one line the app leads with - can I fish tomorrow, and is it legal. Pure and
// thin: the fishable word is the brief's own verdict (web/brief/verdict.ts briefVerdict, passed in
// as `verdict`), the reason is that verdict's own sentence, and the legality note names the state
// web/regs.ts regulationState and ruleSummary give the rules card. Nothing is graded here and no
// rule is quoted: legality is a pointer to the rules card, never a ruling.
import type {BriefVerdict, DayVerdict} from './brief/verdict.ts';
import {PROFILE_TABLE, type Profile} from './profile.ts';
import {CDFW_OCEAN, regulationState, ruleSummary, type RulesRegion} from './regs.ts';
import {t, type Language, type StringId} from './i18n.ts';

export type Fishable = 'yes' | 'marginal' | 'no' | 'unknown';

export interface FirstAnswerState {
  /** The brief's verdict for the lead's day (Brief.tsx currentVerdict); null before there is a brief. */
  verdict: BriefVerdict | null;
  /** The region's rules identity and its registry; either missing reads as rules unavailable. */
  rules: RulesRegion | null;
  regs: unknown;
  /** The target the rules card shows and the lead's day ("YYYY-MM-DD") and its words ("tomorrow"). */
  target: string;
  date: string;
  day: string;
  now: Date;
  profile: Profile;
  /** False when the address and storage name no profile: the line then says which one it assumed. */
  chosen: boolean;
  /** The page's language (web/i18n.ts); English when absent. */
  lang?: Language;
}

export interface FirstAnswer {
  fishable: Fishable;
  legalityNote: string;
  reason: string;
  asOf: string;
  /** The one line shown, and the rules card's official link. */
  line: string;
  rulesHref: string;
}

const FISHABLE: Readonly<Record<DayVerdict, Fishable>> = {comfortable: 'yes', marginal: 'marginal', rough: 'no', unknown: 'unknown'};

/** One distinct line per answer (catalogue ids); `unknown` never reads as a yes. */
const LINE: Readonly<Record<Fishable, StringId>> = {yes: 'fa.yes', marginal: 'fa.marginal', no: 'fa.no', unknown: 'fa.unknown'};

/** Reviewed, due for review, or unavailable: the rules card's own state, with no bag, size or depth numbers. */
function legality(s: FirstAnswerState): {note: string; href: string} {
  const lang = s.lang ?? 'en';
  if (!s.rules || !s.regs) return {note: t('fa.rules.unavailable', lang), href: CDFW_OCEAN};
  const state = regulationState(s.regs, s.target, s.rules, s.now.getTime(), s.date, null), sum = ruleSummary(s.regs, s.target, state, s.rules, lang);
  if (state.status === 'unknown' || state.overdue) return {note: t('fa.rules.due', lang), href: sum.link};
  return {note: t('fa.rules.reviewed', lang, {label: sum.label}), href: sum.link};
}

/** The first answer for the lead's day. Every field comes from verdict.ts, regs.ts or the profile table. */
export function firstAnswer(s: FirstAnswerState): FirstAnswer {
  const v = s.verdict, fishable = v ? FISHABLE[v.verdict] : 'unknown', lang = s.lang ?? 'en';
  const law = legality(s), assumed = s.chosen ? '' : ` ${t('fa.assumed', lang, {profile: PROFILE_TABLE[s.profile].label})}`;
  return {
    fishable, legalityNote: law.note, rulesHref: law.href, asOf: s.now.toISOString(),
    line: `${t(LINE[fishable], lang, {day: s.day})}${assumed}`,
    reason: v ? `${v.limit}${v.held ? ` ${v.held}` : ''}` : t('common.waiting', lang),
  };
}
