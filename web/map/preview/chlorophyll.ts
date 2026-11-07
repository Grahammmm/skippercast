// MAPLIVE-1: satellite chlorophyll, style "chlorophyll 4" (MAPLAYER-CHLR-1; scripts/build_chlorophyll_layer.py).
// A private web-mercator image with its own data time and age limit. Clear pixels are no reading, never zero.
import type {Overlay} from '../engine.ts';
import {PREVIEW_DATA, type PreviewAttach} from '../preview-layers.ts';
import {ageText, BEFORE_APP_LAYERS, expireWhenStale, freshWithin, getJson, handle, hoursOld, utc} from './common.ts';

export const CHLOROPHYLL_ID = 'preview-chlorophyll';
interface ChlDoc {bounds: [number, number, number, number]; sample_at: string; max_age_hours: number; style: {legend: Array<[number, string]>}}

export function readChlorophyll(raw: unknown): ChlDoc {
  const d = raw as Partial<ChlDoc> | null;
  if (!d || !Array.isArray(d.bounds) || d.bounds.length !== 4 || !d.bounds.every(Number.isFinite) || typeof d.sample_at !== 'string'
    || !(Number(d.max_age_hours) > 0) || !Array.isArray(d.style?.legend) || d.style.legend.length < 2
    || !d.style.legend.every(stop => Array.isArray(stop) && Number.isFinite(stop[0]) && stop[0] > 0 && typeof stop[1] === 'string')) throw new Error('chlorophyll file is not valid');
  return d as ChlDoc;
}

export function chlorophyllOverlay(d: ChlDoc, image: string): Overlay {
  const [w, s, e, n] = d.bounds;
  return {
    sources: {[CHLOROPHYLL_ID]: {type: 'image', url: image, coordinates: [[w, n], [e, n], [e, s], [w, s]]}},
    layers: [{id: CHLOROPHYLL_ID, type: 'raster', source: CHLOROPHYLL_ID, paint: {'raster-fade-duration': 0, 'raster-resampling': 'linear', 'raster-opacity': 1}}],
  };
}

export const attach: PreviewAttach = async ctx => {
  const d = readChlorophyll(await getJson(ctx, PREVIEW_DATA.chlorophyll));
  if (ctx.signal.aborted) return null;
  const usable = () => freshWithin(d.sample_at, d.max_age_hours, ctx.now());
  // The end labels are the file's own scale (build_chlorophyll_layer.py VMIN to VMAX); values outside it are drawn at the end colours.
  const values = d.style.legend.map(stop => stop[0]);
  const ramp = {colours: d.style.legend.map(stop => stop[1]), low: `${Math.min(...values)} mg/m³`, high: `${Math.max(...values)}+`};
  if (!usable()) {
    ctx.report({state: 'stale', dataTime: d.sample_at, text: `Sample ${utc(d.sample_at)} is older than its ${d.max_age_hours} h limit or not valid. Withheld.`});
    return null;
  }
  const image = ctx.url(PREVIEW_DATA.chlorophyll.replace(/chlorophyll\.json$/, 'chlorophyll.png'));
  ctx.engine.setOverlay(CHLOROPHYLL_ID, chlorophyllOverlay(d, image), BEFORE_APP_LAYERS);
  ctx.report({state: 'ready', dataTime: d.sample_at, ramp, text: `Sample ${utc(d.sample_at)} (${ageText(hoursOld(d.sample_at, ctx.now()))}). Clear = no reading.`});
  const stopTimer = expireWhenStale(ctx, usable, () => {
    ctx.engine.setOverlay(CHLOROPHYLL_ID, null);
    ctx.report({state: 'stale', dataTime: d.sample_at, text: `Sample ${utc(d.sample_at)} passed its ${d.max_age_hours} h limit. Withheld.`});
  });
  return handle(stopTimer, () => ctx.engine.setOverlay(CHLOROPHYLL_ID, null));
};
