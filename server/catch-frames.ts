type MissingFrame = {missing: 'not archived' | 'bad time'};

const EXPLICIT_ZONE = /(?:Z|[+-]\d{2}:\d{2})$/;
const SAMPLE_INSTANT = /^(\d{4}-\d{2}-\d{2})T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})$/;
const HALF_HOUR_MS = 30 * 60_000;

function catchTime(startedAt: string): number {
  return EXPLICIT_ZONE.test(startedAt) ? Date.parse(startedAt) : NaN;
}

// Match the day from web/hour.ts without importing its browser clock code.
function regionDay(format: Intl.DateTimeFormat, at: number): string {
  let year = '', month = '', day = '';
  for (const part of format.formatToParts(at)) {
    if (part.type === 'year') year = part.value;
    if (part.type === 'month') month = part.value.padStart(2, '0');
    if (part.type === 'day') day = part.value.padStart(2, '0');
  }
  return `${year}-${month}-${day}`;
}

export function observedFrameFor(startedAt: string, tz: string, sampleTimes: readonly string[]): {sampleAt: string} | MissingFrame {
  const started = catchTime(startedAt);
  if (!Number.isFinite(started)) return {missing: 'bad time'};
  const format = new Intl.DateTimeFormat('en-CA', {timeZone: tz, year: 'numeric', month: 'numeric', day: 'numeric'});
  const day = regionDay(format, started);

  let before: {at: number; sampleAt: string} | undefined;
  let after: {at: number; sampleAt: string} | undefined;
  for (const sampleAt of sampleTimes) {
    const writtenDay = SAMPLE_INSTANT.exec(sampleAt)?.[1];
    if (!writtenDay) continue;
    const at = Date.parse(sampleAt);
    if (!Number.isFinite(at)) continue;
    // Date.parse can normalize a nonexistent written day into the next month.
    if (new Date(writtenDay).getUTCDate() !== Number(writtenDay.slice(-2))) continue;
    if (regionDay(format, at) !== day) continue;
    if (at <= started) {
      if (!before || at > before.at) before = {at, sampleAt};
    } else if (!after || at < after.at) {
      after = {at, sampleAt};
    }
  }
  const chosen = before ?? after;
  return chosen ? {sampleAt: chosen.sampleAt} : {missing: 'not archived'};
}

export function forecastHourFor(startedAt: string, hours: readonly number[]): {at: number} | MissingFrame {
  const started = catchTime(startedAt);
  if (!Number.isFinite(started)) return {missing: 'bad time'};

  let best: {at: number; gap: number} | undefined;
  for (const at of hours) {
    if (!Number.isFinite(at)) continue;
    const gap = Math.abs(at - started);
    if (gap > HALF_HOUR_MS) continue;
    if (!best || gap < best.gap || (gap === best.gap && at < best.at)) best = {at, gap};
  }
  return best ? {at: best.at} : {missing: 'not archived'};
}
