// Device-local display choice only; models, comparisons and exports keep Fahrenheit.
import {signal} from '@preact/signals';
export type Units = Readonly<{temp: 'F' | 'C'}>;
const KEY = 'skippercast-units-v1';
function readUnits(): Units {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null');
    if (saved?.temp === 'F' || saved?.temp === 'C') return {temp: saved.temp};
  } catch { /* Missing or blocked storage uses the default. */ }
  return {temp: 'F'};
}
export const units = signal<Units>(readUnits());
export function setUnits(next: Units): void {
  if (next?.temp !== 'F' && next?.temp !== 'C') return;
  units.value = {temp: next.temp};
  try { localStorage.setItem(KEY, JSON.stringify(units.peek())); } catch { /* The current page still uses the choice. */ }
}
