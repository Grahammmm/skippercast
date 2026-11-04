// BF-one-answer: the one line the app leads with - can I fish tomorrow, and is it legal. Pure and
// thin: the fishable word is the brief's own verdict (web/brief/verdict.ts briefVerdict, passed in
// as `verdict`), the reason is that verdict's own sentence, and the legality note names the state
// web/regs.ts regulationState and ruleSummary give the rules card. Nothing is graded here and no
// rule is quoted: legality is a pointer to the rules card, never a ruling.
import type {BriefVerdict, DayVerdict} from './brief/verdict.ts';
import {PROFILE_TABLE, type Profile} from './profile.ts';
import {CDFW_OCEAN, regulationState, ruleSummary, type RulesRegion} from './regs.ts';

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

/** One distinct line per answer; `unknown` never reads as a yes. */
const LINE: Readonly<Record<Fishable, (day: string) => string>> = {
  yes: day => `Yes - ${day} looks fishable.`,
  marginal: day => `Marginal - ${day} is a borderline day to fish.`,
  no: day => `No - ${day} looks too rough to fish.`,
  unknown: day => `Not known yet - no usable forecast for ${day}.`,
};

/** Reviewed, due for review, or unavailable: the rules card's own state, with no bag, size or depth numbers. */
function legality(s: FirstAnswerState): {note: string; href: string} {
  if (!s.rules || !s.regs) return {note: 'Rules unavailable - open the official rules before you go.', href: CDFW_OCEAN};
  const state = regulationState(s.regs, s.target, s.rules, s.now.getTime(), s.date, null), sum = ruleSummary(s.regs, s.target, state, s.rules);
  if (state.status === 'unknown' || state.overdue) return {note: 'Rules due for review - check the official page before you go.', href: sum.link};
  return {note: `Rules reviewed (${sum.label}) - see the rules card for the limits.`, href: sum.link};
}

/** The first answer for the lead's day. Every field comes from verdict.ts, regs.ts or the profile table. */
export function firstAnswer(s: FirstAnswerState): FirstAnswer {
  const v = s.verdict, fishable = v ? FISHABLE[v.verdict] : 'unknown';
  const law = legality(s), assumed = s.chosen ? '' : ` Assuming the ${PROFILE_TABLE[s.profile].label} profile - change it above.`;
  return {
    fishable, legalityNote: law.note, rulesHref: law.href, asOf: s.now.toISOString(),
    line: `${LINE[fishable](s.day)}${assumed}`,
    reason: v ? `${v.limit}${v.held ? ` ${v.held}` : ''}` : 'Waiting for readings.',
  };
}
