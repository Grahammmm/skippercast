import type {Units} from './unit-choice.ts';
import {fToC} from './units.ts';

export const WATCH_RANGES = {
  'water-temp': [28, 95],
  chlorophyll: [0.01, 100],
  'sst-contrast': [0, 10],
} as const;

export type WatchLayer = keyof typeof WATCH_RANGES;
type Temp = Units['temp'];

function checkLayer(layer: WatchLayer): void {
  if (typeof layer !== 'string' || !Object.hasOwn(WATCH_RANGES, layer)) {
    throw new TypeError('Unknown watch layer');
  }
}

function round(value: number, scale: number): number {
  // Adding positive zero normalizes Math.round's negative zero without masking NaN.
  return Math.round(value * scale) / scale + 0;
}

export function toStored(layer: WatchLayer, value: number, temp: Temp): number | null {
  checkLayer(layer);
  if (!Number.isFinite(value)) return null;
  const [min, max] = WATCH_RANGES[layer];
  let stored = value;
  if (temp === 'C') {
    if (layer === 'water-temp') stored = round(value * 9 / 5 + 32, 10);
    if (layer === 'sst-contrast') stored = round(value * 9 / 5, 100);
  }
  return stored >= min && stored <= max ? stored : null;
}

export function fromStored(layer: WatchLayer, stored: number, temp: Temp): number {
  checkLayer(layer);
  if (temp === 'C') {
    if (layer === 'water-temp') return round(fToC(stored), 10);
    if (layer === 'sst-contrast') return round(stored * 5 / 9, 100);
  }
  return stored;
}

export function displayRange(layer: WatchLayer, temp: Temp): [number, number] {
  checkLayer(layer);
  const [min, max] = WATCH_RANGES[layer];
  // Round inward from the unrounded display values, not from fromStored's nearest step.
  if (temp === 'C') {
    if (layer === 'water-temp') return [Math.ceil(fToC(min) * 10) / 10, Math.floor(fToC(max) * 10) / 10];
    if (layer === 'sst-contrast') return [Math.ceil(min * 5 / 9 * 100) / 100, Math.floor(max * 5 / 9 * 100) / 100];
  }
  return [min, max];
}

export function unitSymbol(layer: WatchLayer, temp: Temp): '°F' | '°C' | 'mg/m³' | '°F/nm' | '°C/nm' {
  checkLayer(layer);
  if (layer === 'chlorophyll') return 'mg/m³';
  if (layer === 'sst-contrast') return temp === 'C' ? '°C/nm' : '°F/nm';
  return temp === 'C' ? '°C' : '°F';
}
