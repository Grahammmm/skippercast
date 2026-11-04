// Arithmetic over planRun's output; window selection and transit stay upstream.
import {ROUND_MIN} from './run.ts';
import type {RunState} from './run.ts';
export interface FishingRule {status: string; opensAt: number | null; label: string; reason: string}
type End = 'opening' | 'daylight' | 'conditions';
export type FishingHours =
  | {kind: 'enough'; availableMin: number; wantedMin: number; spareMin: number}
  | {kind: 'short'; availableMin: number; wantedMin: number; shortMin: number; endedBy: End; rulesUnconfirmed?: boolean}
  | {kind: 'none'; endedBy: End; rulesUnconfirmed?: boolean}
  | {kind: 'closed'; label: string; reason: string}
  | {kind: 'no-wanted'}
  | {kind: 'beyond-daylight'; daylightMin: number; wantedMin: number};
export function fishingHours(run: Extract<RunState, {kind: 'ok' | 'no-time'}>,
  {wantedMin, sunrise, sunset, rule}: {wantedMin: number | null; sunrise: string | null; sunset: string | null; rule: FishingRule}): FishingHours {
  if (rule.status === 'closed' || rule.status === 'excluded') return {kind: 'closed', label: rule.label, reason: rule.reason};
  const light = sunrise && sunset ? (Date.parse(sunset) - Date.parse(sunrise)) / 60000 : NaN;
  const unknown = rule.status === 'unknown';
  const endedBy: End = run.kind === 'ok' && rule.opensAt !== null && rule.opensAt > Date.parse(run.arrive) ? 'opening'
    : sunset && Date.parse(run.window.end) + 3600000 > Date.parse(sunset) ? 'daylight' : 'conditions';
  if (run.kind === 'no-time') return {kind: 'none', endedBy, ...(unknown ? {rulesUnconfirmed: true} : {})};
  if (wantedMin === null || !Number.isFinite(wantedMin) || wantedMin <= 0) return {kind: 'no-wanted'};
  if (Number.isFinite(light) && light > 0 && wantedMin > light) return {kind: 'beyond-daylight', daylightMin: Math.floor(light), wantedMin};
  const start = Math.max(Date.parse(run.arrive), rule.opensAt ?? -Infinity);
  const availableMin = Math.max(0, Math.floor((Date.parse(run.turnBack) - start) / (60000 * ROUND_MIN)) * ROUND_MIN);
  if (!availableMin) return {kind: 'none', endedBy, ...(unknown ? {rulesUnconfirmed: true} : {})};
  if (availableMin >= wantedMin && !unknown) return {kind: 'enough', availableMin, wantedMin, spareMin: availableMin - wantedMin};
  return {kind: 'short', availableMin, wantedMin, shortMin: Math.max(0, wantedMin - availableMin), endedBy, ...(unknown ? {rulesUnconfirmed: true} : {})};
}
