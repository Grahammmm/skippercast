// Deterministic scheduler: tests execute the actual Reports effect callback.
export const effects: (() => void)[] = [];
export function useEffect(callback: () => void, _deps: unknown[]) { effects.push(callback); }
