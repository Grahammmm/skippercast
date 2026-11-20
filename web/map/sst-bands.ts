// SST-B display model, shared by the Chart and its offline case exporter.
import type * as MapLibre from 'maplibre-gl';
import {LAYERS_STYLE} from './layers-style.gen.ts';
import {kitZoom} from './nearshore-paint.ts';
import {sklColor, type Palette} from './palette.ts';
import {fieldColor} from './surface-field.js';

export const SST_STYLE = LAYERS_STYLE.layers['sst-fill'];
export const SST_BAND_EDGE = 'skl-sst-band-edge';
export const SST_BAND_SOURCE = 'sst-bands';
export const SST_FILL = 'skl-sst-fill-fill';
export const SST_FILL_SOURCE = 'sst-texture';
export const sstRamp = (p: Palette): string[] => SST_STYLE.ramp_stops.map(color => sklColor(p, color));

export function sstBandStep(zoom: number): number {
  return SST_STYLE.band_step_f_by_zoom.findLast(([z]) => zoom >= z)?.[1] ?? SST_STYLE.band_step_f_by_zoom[0][1];
}

export function sstOpacity(zoom: number): number {
  const stops = SST_STYLE.opacity;
  for (let i = 1; i < stops.length; i++) {
    const [z1, v1] = stops[i]!;
    if (zoom <= z1) {
      const [z0, v0] = stops[i - 1]!;
      return v0 + Math.max(0, (zoom - z0) / (z1 - z0)) * (v1 - v0);
    }
  }
  return stops.at(-1)![1];
}

export function sstBandModel(visible: Float64Array, zoom: number) {
  const values = visible.filter(Number.isFinite).sort();
  if (!values.length) return null;
  const percentile = (pct: number) => {
    const i = (values.length - 1) * pct / 100, j = Math.floor(i);
    return values[j]! + (values[Math.ceil(i)]! - values[j]!) * (i - j);
  };
  const step = sstBandStep(zoom);
  const low = Math.floor(percentile(SST_STYLE.stretch.low_pct) / step) * step;
  const high = Math.max(low + step, Math.ceil(percentile(SST_STYLE.stretch.high_pct) / step) * step);
  const count = Math.round((high - low) / step);
  return {
    step, low, high, count, mean: values.reduce((sum, v) => sum + v, 0) / values.length,
    opacity: sstOpacity(zoom), legend: SST_STYLE.legend.title.replace('{step}', String(step)),
    baseDesaturation: SST_STYLE.desaturates_base ? LAYERS_STYLE.stacking.base_desaturation_when_field_on : 0,
  };
}

type Bands = NonNullable<ReturnType<typeof sstBandModel>>;
export function sstBandPixels(samples: Float64Array, bands: Bands, ramp: string[], opacity = 1): Uint8ClampedArray<ArrayBuffer> {
  const {low, step, count} = bands;
  const colours = Array.from({length: count}, (_, i) => fieldColor(i, 0, Math.max(1, count - 1), ramp));
  const rgba = new Uint8ClampedArray(samples.length * 4);
  for (let i = 0; i < samples.length; i++) {
    const temp = samples[i]!;
    if (!Number.isFinite(temp)) continue;
    rgba.set(colours[Math.max(0, Math.min(count - 1, Math.floor((temp - low) / step)))]!, i * 4);
    rgba[i * 4 + 3] = Math.floor(opacity * 255);
  }
  return rgba;
}

/** Canonical kit fragment projection; Chart mounts these same paints on its active sources. */
export function sstBandLayers(p: Palette, fragment = false) {
  const edge = SST_STYLE.band_edge;
  const opacity = fragment ? ['interpolate', ['linear'], ['zoom'], ...SST_STYLE.opacity.flat()] : kitZoom(SST_STYLE.opacity);
  const layout = fragment ? {layout: {visibility: 'none' as const}} : {};
  return [
    {id: SST_FILL, type: 'raster', source: SST_FILL_SOURCE, ...layout,
      paint: {'raster-opacity': opacity as MapLibre.ExpressionSpecification, 'raster-resampling': 'linear', 'raster-fade-duration': 0},
      metadata: {'skippercast:ramp': {ramp_stops: sstRamp(p), band_step_f_by_zoom: SST_STYLE.band_step_f_by_zoom, stretch: SST_STYLE.stretch, rule: SST_STYLE.band_colors_rule},
        'skippercast:water_only': SST_STYLE.water_only, 'skippercast:gaps': LAYERS_STYLE.display_sampling,
        'skippercast:z': 'color-field', 'skippercast:layer': 'sst-fill'}, _token: 'layers.sst-fill.ramp_stops'},
    {id: SST_BAND_EDGE, type: 'line', source: SST_BAND_SOURCE, ...layout,
      paint: {'line-color': sklColor(p, edge.color), 'line-width': edge.width_pt, 'line-opacity': edge.opacity},
      metadata: {'skippercast:hide_when_any_on': edge.hide_when_any_on, 'skippercast:z': 'isolines', 'skippercast:layer': 'sst-fill'}, _token: 'layers.sst-fill.band_edge'},
  ] as const satisfies readonly (MapLibre.LayerSpecification & {_token: string})[];
}
