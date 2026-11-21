import type {WindFrame} from './wind.ts';
import {windReadingAt, type WindReading} from './wind-reading.ts';

export function windHourReading(
  frames: readonly WindFrame[],
  hourMs: number,
  at: {lon: number; lat: number},
): WindReading {
  if (!Number.isFinite(hourMs) || !Array.isArray(frames)) return windReadingAt(null, at);
  const frame = frames.find(frame => frame?.validAt === hourMs);
  return windReadingAt(frame ?? null, at);
}
