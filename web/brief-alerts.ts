// An editable alert draft passed to the active account menu, never persisted.
import {effect, signal} from '@preact/signals';
import type {ComfortLimits} from './limits.ts';
import type {Profile} from './profile.ts';
import {profile, region} from './state.ts';

export type BriefAlertSeed = {
  region: string;
  profile: Profile;
  date: string;
  start: number;
  end: number;
  port: {lat: number; lon: number} | null;
  target: string;
  ownLimits: Pick<ComfortLimits, 'wind' | 'gust' | 'seas'> | null;
};
type Request = BriefAlertSeed & {id: number; opener: HTMLButtonElement};
let sequence = 0;
const pending = signal<Request | null>(null);
export const briefAlertRequest: Readonly<typeof pending> = pending;

export function openBriefAlerts(seed: BriefAlertSeed, opener: HTMLButtonElement): void {
  if (seed.region === region.peek() && seed.profile === profile.peek()) pending.value = {...seed, id: ++sequence, opener};
}

/** A late close from another dialog cannot discard the current request. */
export function clearBriefAlerts(request = pending.peek()): boolean {
  if (!request || pending.peek() !== request) return false;
  pending.value = null;
  return true;
}

effect(() => {
  const request = pending.value;
  if (request && (request.region !== region.value || request.profile !== profile.value)) clearBriefAlerts(request);
});
