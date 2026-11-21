import type {WindFrame, WindSample} from './wind.ts';

export type WindReading =
  | {ok: true; sample: WindSample; validAt: number; stamp: string}
  | {ok: false; reason: 'no-frame' | 'no-sample-near'};

export function windReadingAt(frame: WindFrame | null, at: {lon: number; lat: number}): WindReading {
  if (!frame?.step || !Number.isFinite(at.lon) || !Number.isFinite(at.lat)) {
    return {ok: false, reason: 'no-frame'};
  }
  const lonStep = frame.step[0], latStep = frame.step[1];
  if (!Number.isFinite(lonStep) || lonStep <= 0 || !Number.isFinite(latStep) || latStep <= 0) {
    return {ok: false, reason: 'no-frame'};
  }

  let nearest: WindSample | undefined;
  let bestDistance = Infinity;
  for (const sample of frame.points) {
    if (!Number.isFinite(sample.lon) || !Number.isFinite(sample.lat) ||
        !Number.isFinite(sample.knots) || !Number.isFinite(sample.from)) continue;
    const dlon = Math.abs(sample.lon - at.lon);
    const dlat = Math.abs(sample.lat - at.lat);
    if (dlon > lonStep / 2 || dlat > latStep / 2) continue;
    const distance = (dlon / lonStep) ** 2 + (dlat / latStep) ** 2;
    if (distance < bestDistance) {
      nearest = sample;
      bestDistance = distance;
    }
  }
  return nearest
    ? {ok: true, sample: nearest, validAt: frame.validAt, stamp: frame.stamp}
    : {ok: false, reason: 'no-sample-near'};
}
