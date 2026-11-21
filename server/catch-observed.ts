import {cellIndex, sampleAt} from '../web/map/habitat-sample.ts';

export type ObservedFrame = {
  layer: string;
  product: string;
  sampleAt: string;
  resolution: readonly [number, number];
  fields: readonly string[];
  rows: readonly (readonly unknown[])[];
};

export type ObservedValue =
  | {value: number; unit: 'F' | 'mg/m3'; product: string; sample_at: string}
  | {missing: 'not archived' | 'no position' | 'bad frame' | 'outside coverage' | 'gap'};

function readObserved(frame: ObservedFrame | null, lat: number | null, lon: number | null,
  layer: string, field: string, unit: 'F' | 'mg/m3'): ObservedValue {
  if (frame === null) return {missing: 'not archived'};
  if (lat === null || lon === null || !Number.isFinite(lat) || !Number.isFinite(lon)) {
    return {missing: 'no position'};
  }
  try {
    if (frame.layer !== layer) return {missing: 'bad frame'};
    // The index validates the named column before looking at rows, even for an empty frame.
    const sample = sampleAt(cellIndex(frame.rows, frame.resolution, frame.fields, field), lat, lon);
    if ('reason' in sample && sample.reason === 'outside') return {missing: 'outside coverage'};
    if (sample.value === null) return {missing: 'gap'};
    const value = unit === 'F' ? Math.round((sample.value * 1.8 + 32) * 10) / 10 : sample.value;
    return {value, unit, product: frame.product, sample_at: frame.sampleAt};
  } catch {
    return {missing: 'bad frame'};
  }
}

export function catchWaterTemp(frame: ObservedFrame | null, lat: number | null, lon: number | null): ObservedValue {
  return readObserved(frame, lat, lon, 'sst-analysis', 'temperature_c', 'F');
}

export function catchChlorophyll(frame: ObservedFrame | null, lat: number | null, lon: number | null): ObservedValue {
  return readObserved(frame, lat, lon, 'chlorophyll-observation', 'chlorophyll_mg_m3', 'mg/m3');
}
