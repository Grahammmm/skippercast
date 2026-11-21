import {parseEddiesTile} from './eddies-feed.ts';
import {eddyReading, type EddyReading} from './eddy-reading.ts';

export function eddyTileTap(
  raw: unknown, issuedAt: string, at: {lon: number; lat: number},
): EddyReading | {kind: 'invalid'; error: string} {
  const parsed = parseEddiesTile(raw);
  if (!parsed.ok) return {kind: 'invalid', error: parsed.error};
  const {frameTime, eddies} = parsed;
  return eddyReading({frameTime, eddies}, issuedAt, at);
}
