const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

export function pastPlayOrder(past: readonly {day: string}[], today: string): string[] {
  const days = new Set<string>();
  for (const {day} of past) {
    if (day >= today || !ISO_DAY.test(day)) continue;
    // Date can roll an impossible day (e.g. February 30) into the next month.
    if (new Date(day).getUTCDate() === Number(day.slice(-2))) days.add(day);
  }
  return [...days].sort().concat(today);
}

export function nextPlayDay(selected: string, past: readonly {day: string}[], today: string): string | null {
  return pastPlayOrder(past, today).find(day => day > selected) ?? null;
}

export function pastStep(
  get: () => string, set: (day: string) => void, past: readonly {day: string}[], today: string,
): () => boolean {
  return () => {
    const next = nextPlayDay(get(), past, today);
    if (next === null) return false;
    set(next);
    return true;
  };
}
