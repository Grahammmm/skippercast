// MAPLIVE-1: surface currents, style "current 5" (MAPLAYER-CURRENT-1; research/scripts/map_style/currents-layer.js).
// A spin tint under dark streamlines from a real HF-radar grid, drawn only where all four surrounding cells hold a
// vector. The maths is the study's own module, imported unchanged; only the MapLibre wiring differs (the Chart's
// overlay API, and arrowheads as small triangles because the Chart carries no arrow sprite).
import type {Overlay} from '../engine.ts';
import {PREVIEW_DATA, type PreviewAttach} from '../preview-layers.ts';
import {ageText, BEFORE_APP_LAYERS, expireWhenStale, freshWithin, handle, hoursOld, utc} from './common.ts';
import {balance} from '../../../research/scripts/map_style/balance-ramp.js';
import {bearing, gridOf, loadCurrentsDoc, STREAM_COLOUR, streamlines, tintPixels} from '../../../research/scripts/map_style/currents-layer.js';

export const CURRENTS_TINT = 'preview-currents-tint', CURRENTS_LINES = 'preview-currents-lines', CURRENTS_HEADS = 'preview-currents-heads';
/** HF-radar grids are hourly; the study set no limit, so the preview withholds one older than two days. */
export const CURRENTS_MAX_AGE_HOURS = 48;

type Position = [number, number];
/** A small triangle at the end of a streamline, pointing along its last bearing. `size` is in degrees of latitude. */
export function arrowhead(tip: Position, from: Position, size: number): Position[] {
  const DEG = Math.PI / 180, b = bearing(from, tip) * DEG, kx = 1 / Math.max(0.2, Math.cos(tip[1] * DEG));
  const at = (angle: number, length: number): Position => [tip[0] + Math.sin(angle) * length * kx, tip[1] + Math.cos(angle) * length];
  return [tip, at(b + Math.PI - 0.45, size), at(b + Math.PI + 0.45, size), tip];
}

export function currentsOverlay(lines: Array<{coords: number[][]}>, image: {url: string; coordinates: number[][]}, size: number): Overlay {
  const features = lines.map(l => ({type: 'Feature' as const, properties: {}, geometry: {type: 'LineString' as const, coordinates: l.coords}}));
  const heads = lines.filter(l => l.coords.length > 2).map(l => ({type: 'Feature' as const, properties: {},
    geometry: {type: 'Polygon' as const, coordinates: [arrowhead(l.coords.at(-1)! as Position, l.coords.at(-3)! as Position, size)]}}));
  return {
    sources: {
      [CURRENTS_TINT]: {type: 'image', url: image.url, coordinates: image.coordinates as [Position, Position, Position, Position]},
      [CURRENTS_LINES]: {type: 'geojson', data: {type: 'FeatureCollection', features}},
      [CURRENTS_HEADS]: {type: 'geojson', data: {type: 'FeatureCollection', features: heads}},
    },
    layers: [
      {id: CURRENTS_TINT, type: 'raster', source: CURRENTS_TINT, paint: {'raster-fade-duration': 0, 'raster-resampling': 'linear'}},
      {id: CURRENTS_LINES, type: 'line', source: CURRENTS_LINES, layout: {'line-cap': 'round'},
        paint: {'line-color': STREAM_COLOUR, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.7, 13, 1.4]}},
      {id: CURRENTS_HEADS, type: 'fill', source: CURRENTS_HEADS, paint: {'fill-color': STREAM_COLOUR, 'fill-antialias': true}},
    ],
  };
}

const rgb = (c: number[]): string => `rgb(${c.join(',')})`;
export const CURRENTS_RAMP = [0, 0.25, 0.5, 0.75, 1].map(t => rgb(balance(t)));

export const attach: PreviewAttach = async ctx => {
  const doc = await loadCurrentsDoc((url: string) => ctx.fetchFn(url, {cache: 'no-store', signal: ctx.signal}), ctx.url(PREVIEW_DATA.currents));
  if (ctx.signal.aborted) return null;
  const usable = () => freshWithin(doc.sample_at, CURRENTS_MAX_AGE_HOURS, ctx.now());
  const ramp = {colours: CURRENTS_RAMP, low: 'clockwise spin', high: 'counter-clockwise'};
  if (!usable()) {
    ctx.report({state: 'stale', dataTime: doc.sample_at, text: `HF-radar grid ${utc(doc.sample_at)} is older than ${CURRENTS_MAX_AGE_HOURS} h or not valid. Withheld.`});
    return null;
  }
  const g = gridOf(doc), tint = tintPixels(g, 900);
  const canvas = document.createElement('canvas');
  canvas.width = tint.width; canvas.height = tint.height;
  canvas.getContext('2d')!.putImageData(new ImageData(tint.data, tint.width, tint.height), 0, 0);
  const cell = Math.min((g.lons[g.cols - 1] - g.lons[0]) / (g.cols - 1), (g.lats[g.rows - 1] - g.lats[0]) / (g.rows - 1));
  const overlay = currentsOverlay(streamlines(g), {url: canvas.toDataURL('image/png'), coordinates: tint.coordinates}, cell * 0.3);
  ctx.engine.setOverlay(CURRENTS_TINT, overlay, BEFORE_APP_LAYERS);
  ctx.report({state: 'ready', dataTime: doc.sample_at, ramp,
    text: `HF radar ${utc(doc.sample_at)} (${ageText(hoursOld(doc.sample_at, ctx.now()))}); ${doc.valid_cells} of ${doc.total_cells} cells have a vector. Near-surface flow; lines follow the flow.`});
  const stopTimer = expireWhenStale(ctx, usable, () => {
    ctx.engine.setOverlay(CURRENTS_TINT, null);
    ctx.report({state: 'stale', dataTime: doc.sample_at, text: `HF-radar grid ${utc(doc.sample_at)} passed ${CURRENTS_MAX_AGE_HOURS} h. Withheld.`});
  });
  return handle(stopTimer, () => ctx.engine.setOverlay(CURRENTS_TINT, null));
};
