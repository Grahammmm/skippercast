// The hazard window of a marine alert (SCB2222-02). NWS gives each alert onset and ends (when the hazard starts and
// stops) beside effective and expires (when this message was issued and when it will be replaced). Readers judge
// "is the alert in force" by the hazard: onset ?? effective for the start, ends ?? expires for the end.
//
// A hazard time the producer found present but unreadable (`unreadableHazardTime`) is unknown, never the message
// time: the start or end then counts as unreadable, so the alert applies (fail closed). Erasable syntax only.
import type {Alert} from './types.ts';

export type AlertClocks = Pick<Alert, 'effective' | 'expires'> & Partial<Pick<Alert, 'onset' | 'ends' | 'unreadableHazardTime'>>;

/** The hazard's start clock as written; null when there is none or it is unreadable. */
export function hazardStart(alert: AlertClocks): string | null {
  return alert.unreadableHazardTime?.includes('onset') ? null : alert.onset ?? alert.effective;
}

/** The hazard's end clock as written; null when there is none or it is unreadable. */
export function hazardEnd(alert: AlertClocks): string | null {
  return alert.unreadableHazardTime?.includes('ends') ? null : alert.ends ?? alert.expires;
}

const time = (value: string | null, unreadable: boolean, absent: number): number =>
  unreadable ? NaN : value ? Date.parse(value) : absent;

/** Hazard start in epoch ms: -Infinity when no clock exists, NaN when it is unreadable (callers treat NaN as applying). */
export function hazardStartMs(alert: AlertClocks): number {
  return time(alert.onset ?? alert.effective, !!alert.unreadableHazardTime?.includes('onset'), -Infinity);
}

/** Hazard end in epoch ms: Infinity when no clock exists, NaN when it is unreadable (callers treat NaN as applying). */
export function hazardEndMs(alert: AlertClocks): number {
  return time(alert.ends ?? alert.expires, !!alert.unreadableHazardTime?.includes('ends'), Infinity);
}
