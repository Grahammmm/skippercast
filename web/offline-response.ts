// SC1722-03: where an answer came from. The saved offline pack's worker (dist/sw.js) marks every answer it serves from the pack
// with X-SC-Offline: the ISO time the pack saved it. A network answer never carries the header. The brief reads that mark so pack
// data is shown as saved at that time, never as fresh, and the mark's own age is never replaced by the time it was read.
//
// Erasable syntax only: Node tests import this file by type stripping.

export const OFFLINE_HEADER = 'X-SC-Offline';
/** A save time further ahead than this (a pack from a clock that moved back) is not trusted. */
const FUTURE_MS = 10 * 60_000;

/** `network`: no header. `saved`: the pack's save time in epoch ms (0 is a valid, ancient clock). `invalid`: a header that is not a usable time. */
export type Provenance = {kind: 'network'} | {kind: 'saved'; at: number} | {kind: 'invalid'};

/** Classify an answer from its headers at `now` (epoch ms). Pure: no fetch, no storage. */
export function responseProvenance(headers: Pick<Headers, 'get'>, now: number): Provenance {
  const raw = headers.get(OFFLINE_HEADER);
  if (raw === null) return {kind: 'network'};
  const text = raw.trim();
  const at = text === '' ? NaN : Date.parse(text);
  return Number.isFinite(at) && at - now <= FUTURE_MS ? {kind: 'saved', at} : {kind: 'invalid'};
}
