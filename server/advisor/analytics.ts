// Text Advisor analytics points (docs/plans/text-advisor/01-architecture.md
// § request flow, step 7): thin wrappers over writePoint in server/analytics.ts,
// whose header documents the columns. Counts, timings, intents and outcomes
// only: never a contact, message, boat or post id, a number or a body.
import {writePoint} from '../analytics.ts';
import type {Env} from '../env.ts';

// Intents and outcomes are short codes ('report.count_board', 'stub', 'done').
// Anything else (a bug passing free text) is written as 'other', so a value
// that could carry content never reaches the dataset.
const CODE = /^[a-z][\w.:-]{0,47}$/i;
const code = (value: unknown): string => typeof value === 'string' && CODE.test(value) ? value : 'other';

export interface AdvisorTurn {intent: string; outcome: string; ms: number; actions: number; sends: number; retries: number}
/** One point per processed inbound message: kind advisor_turn. */
export function recordAdvisorTurn(env: Pick<Env, 'ANALYTICS'> | undefined, turn: AdvisorTurn): void {
  writePoint(env, 'advisor_turn', {blobs: [code(turn.intent), code(turn.outcome)], doubles: [turn.ms, turn.actions, turn.sends, turn.retries]});
}

export interface PublishRun {kind: string; outcome: string; ms: number}
/** One point per social publish attempt (09 § publishing): kind publish. */
export function recordPublish(env: Pick<Env, 'ANALYTICS'> | undefined, run: PublishRun): void {
  writePoint(env, 'publish', {blobs: [code(run.kind), code(run.outcome)], doubles: [run.ms]});
}
