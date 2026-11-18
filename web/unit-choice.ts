// Device-local display choices only; models, comparisons and exports keep Fahrenheit, knots and feet.
import {signal} from '@preact/signals';
import type {WIND_SPEED} from './units.ts';
export type Units = Readonly<{temp: 'F' | 'C'; wind: keyof typeof WIND_SPEED; height: 'ft' | 'm'}>;
const KEY = 'skippercast-units-v1';
const validWind = (value: unknown): value is Units['wind'] => value === 'kt' || value === 'mph' || value === 'kmh';
function readUnits(): Units {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null');
    return {temp: saved?.temp === 'C' ? 'C' : 'F', wind: validWind(saved?.wind) ? saved.wind : 'kt', height: saved?.height === 'm' ? 'm' : 'ft'};
  } catch { /* Missing or blocked storage uses the default. */ }
  return {temp: 'F', wind: 'kt', height: 'ft'};
}
export const units = signal<Units>(readUnits());
export function setUnits({temp, wind, height}: Partial<Units>): void {
  if ((temp !== undefined && temp !== 'F' && temp !== 'C') || (wind !== undefined && !validWind(wind))) return;
  if (height !== undefined && height !== 'ft' && height !== 'm') return;
  const current = units.peek();
  units.value = {temp: temp ?? current.temp, wind: wind ?? current.wind, height: height ?? current.height};
  try { localStorage.setItem(KEY, JSON.stringify(units.peek())); } catch { /* The current page still uses the choice. */ }
}
