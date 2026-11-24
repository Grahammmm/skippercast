// MAPLIVE-1: the seafloor medium-relief base (MAPSTYLE-2/3b; scripts/build_bathy_tiles.py) on the Chart.
// A private raster PMTiles archive read by byte range; it is never published (scripts/client-build.mjs PRIVATE_OUTPUT).
import type {Overlay} from '../engine.ts';
import {PREVIEW_DATA, type PreviewAttach} from '../preview-layers.ts';
import {BEFORE_APP_LAYERS, handle} from './common.ts';

export const SEAFLOOR_ID = 'preview-seafloor';
/** Under the other preview layers, so wind, currents, temperature and chlorophyll read over the relief. */
export const SEAFLOOR_BEFORE = ['preview-sst-cells', 'preview-chlorophyll', 'preview-currents-tint', ...BEFORE_APP_LAYERS] as const;

export function seafloorOverlay(archive: string): Overlay {
  return {
    sources: {[SEAFLOOR_ID]: {type: 'raster', url: `pmtiles://${archive}`, tileSize: 256, attribution: 'Seafloor surveys (research base)'}},
    layers: [{id: SEAFLOOR_ID, type: 'raster', source: SEAFLOOR_ID, paint: {'raster-fade-duration': 0}}],
  };
}

export const attach: PreviewAttach = async ctx => {
  const archive = ctx.url(PREVIEW_DATA.seafloor);
  const probe = await ctx.fetchFn(archive, {headers: {Range: 'bytes=0-0'}, cache: 'no-store', signal: ctx.signal});
  // The probe only needs headers. Cancel even if the server ignored Range and sent the whole archive.
  await probe.body?.cancel();
  if (ctx.signal.aborted) return null;
  if (!probe.ok) throw new Error(`seafloor relief archive not found (HTTP ${probe.status})`);
  if (probe.status !== 206 || !/^bytes 0-0\/(?:0*[1-9]\d*|\*)$/i.test(probe.headers.get('Content-Range') ?? '')) {
    throw new Error(`seafloor relief archive did not return the requested one-byte range (HTTP ${probe.status})`);
  }
  const length = probe.headers.get('Content-Length');
  // HTTP Content-Length is decimal digits; allow leading zeros for a value of one.
  if (length !== null && !/^0*1$/.test(length)) {
    throw new Error('seafloor relief archive returned a Content-Length inconsistent with the requested one-byte range');
  }
  ctx.engine.setOverlay(SEAFLOOR_ID, seafloorOverlay(archive), SEAFLOOR_BEFORE);
  ctx.report({state: 'ready', text: 'Medium relief with 2 m shallow bathymetry. Tan or clear = no survey.'});
  return handle(() => ctx.engine.setOverlay(SEAFLOOR_ID, null));
};
