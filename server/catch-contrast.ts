import {cellIndex, sampleAt} from '../web/map/habitat-sample.ts';
import {M_PER_NMI} from '../web/units.ts';

type ContrastFrame = {
  sampleAt: string;
  product: string;
  fields: readonly string[];
  resolution: readonly [number, number];
  rows: readonly (readonly unknown[])[];
};

type ContrastItem = {value: number; unit: 'F/nm'; product: string; sample_at: string}
  | {missing: 'no position' | 'not archived' | 'bad tile' | 'outside' | 'gap' | 'not supported'};

function isObservationTime(value: unknown): value is string {
  if (typeof value !== 'string' || !value.endsWith('Z')
      || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,3})?Z$/.test(value)) return false;
  const ms = Date.parse(value);
  // Parsing can roll an impossible date or 24:00 into the next day.
  return Number.isFinite(ms) && new Date(ms).toISOString().slice(0, 19) === value.slice(0, 19);
}

/** Read the analysis gradient only where its native cell is flagged as supported. */
export function catchContrast(frame: ContrastFrame | null, point: {lat: number; lon: number} | null): ContrastItem {
  if (point === null) return {missing: 'no position'};
  if (frame === null) return {missing: 'not archived'};
  try {
    const {sampleAt: time, product, rows, resolution, fields} = frame;
    if (!isObservationTime(time) || typeof product !== 'string' || product.length === 0
        || product.length > 400 || [...product].length > 200) return {missing: 'bad tile'};

    const gradientIndex = cellIndex(rows, resolution, fields, 'temperature_gradient_c_per_km');
    const supportIndex = cellIndex(rows, resolution, fields, 'thermal_contrast_supported');
    const {lat, lon} = point;
    const gradient = sampleAt(gradientIndex, lat, lon);
    if ('reason' in gradient) return {missing: gradient.reason};
    if (gradient.value === null || gradient.value < 0) return {missing: 'gap'};
    if (sampleAt(supportIndex, lat, lon).value !== 1) return {missing: 'not supported'};

    const converted = gradient.value * 1.8 * (M_PER_NMI / 1000);
    if (!Number.isFinite(converted)) return {missing: 'bad tile'};
    // Round without scaling very large finite readings into Infinity.
    return {value: Number(converted.toFixed(3)), unit: 'F/nm', product, sample_at: time};
  } catch {
    return {missing: 'bad tile'};
  }
}
