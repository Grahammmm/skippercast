type PastDay = {day: string; weekday: string};
type PastChip = PastDay & {offset: number; date: number; selected: boolean};

const DAY_MS = 86_400_000;

function utcDay(day: string): number | null {
  if (day.length !== 10 || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return null;
  // ISO dates without a time parse at UTC midnight. Round-trip to reject rollover.
  const date = new Date(day);
  const ms = date.getTime();
  return Number.isFinite(ms) && date.toISOString().slice(0, 10) === day ? ms : null;
}

export function pastChips(past: readonly PastDay[], today: string, selected: string | null): {chips: PastChip[]; pastSelected: boolean} {
  const todayMs = utcDay(today);
  if (todayMs === null) return {chips: [], pastSelected: false};

  const chips: PastChip[] = [];
  const seen = new Set<string>();
  for (const {day, weekday} of past) {
    const dayMs = utcDay(day);
    if (dayMs === null) continue;
    const offset = (todayMs - dayMs) / DAY_MS;
    if (offset < 1 || offset > 7 || seen.has(day)) continue;
    seen.add(day);
    chips.push({day, weekday, offset, date: Number(day.slice(-2)), selected: day === selected});
  }
  chips.sort((a, b) => b.offset - a.offset);
  return {chips, pastSelected: chips.some(chip => chip.selected)};
}

/** Move among oldest-first chips, with Today immediately after them. */
export function chipKey(chips: readonly Pick<PastChip, 'day'>[], current: string, key: 'ArrowLeft' | 'ArrowRight' | 'Home' | 'End'): string {
  const index = chips.findIndex(chip => chip.day === current);
  const position = index < 0 ? chips.length : index;
  switch (key) {
    case 'ArrowLeft': return chips[Math.max(0, position - 1)]?.day ?? 'today';
    case 'ArrowRight': return chips[position + 1]?.day ?? 'today';
    case 'Home': return chips[0]?.day ?? 'today';
    case 'End': return 'today';
  }
}
