const DAY = /^\d{4}-\d{2}-\d{2}$/;
// Match the timestamp grammar of pastDayGate without depending on the draw gate.
const INSTANT = /^((?:\d{4}|[+-]\d{6})-\d{2}-\d{2})T\d{2}:\d{2}(?::\d{2}(?:\.(\d+))?)?(?:Z|[+-]\d{2}:?\d{2})$/;

function isCalendarDate(day: string): boolean {
  const midnight = new Date(`${day}T00:00:00Z`);
  return Number.isFinite(midnight.getTime()) && midnight.toISOString().split('T')[0] === day;
}

/** Pick the latest available history sample on the selected region-local day. */
export function pastSampleFor(samples: readonly string[], selectedDay: string, zone: string): string | null {
  if (typeof selectedDay !== 'string' || !DAY.test(selectedDay) || !isCalendarDate(selectedDay)
    || typeof zone !== 'string') return null;

  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: zone, calendar: 'gregory', era: 'short', year: 'numeric', month: '2-digit', day: '2-digit',
    });
    let newest: string | null = null;
    let newestAt = -Infinity;
    let newestTail = '';
    for (const sample of samples) {
      const match = typeof sample === 'string' ? INSTANT.exec(sample) : null;
      if (!match?.[1] || !isCalendarDate(match[1])) continue;
      const at = Date.parse(sample);
      if (!Number.isFinite(at)) continue;
      // Date.parse drops digits after milliseconds. Compare the remaining decimal digits,
      // ignoring trailing zeroes so different spellings of one instant still tie.
      const tail = (match[2] ?? '').slice(3).replace(/0+$/, '');
      if (at < newestAt || (at === newestAt && tail <= newestTail)) continue;

      const parts = formatter.formatToParts(at);
      const part = (type: Intl.DateTimeFormatPartTypes) => parts.find(p => p.type === type)?.value;
      const year = Number(part('year'));
      // Gregorian 1 BC is ISO year 0000, as in pastDayGate.
      const isoYear = part('era') === 'BC' ? 1 - year : year;
      const localDay = `${String(isoYear).padStart(4, '0')}-${part('month')}-${part('day')}`;
      if (localDay === selectedDay) {
        newest = sample;
        newestAt = at;
        newestTail = tail;
      }
    }
    return newest;
  } catch {
    return null;
  }
}

export function pastDayCoverage(samples: readonly string[], days: readonly string[], zone: string): Record<string, boolean> {
  return Object.fromEntries(days.map(day => [day, pastSampleFor(samples, day, zone) !== null]));
}
