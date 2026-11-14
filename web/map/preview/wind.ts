// MAPLIVE-1: wind particle trails, style "wind 3" (MAPLAYER-WIND-1; web/map/wind-layer.js).
// A canvas over the Chart driven by the study's own particle module, fed a real NOAA GFS 10 m grid. The module
// wants a MapLibre-shaped map, so a small adapter maps it onto the engine's view (the Chart exposes no raw map).
// A run older than 18 h, or an invalid grid, draws nothing.
import type {MapView} from '../engine.ts';
import {PREVIEW_DATA, type PreviewAttach} from '../preview-layers.ts';
import {ageText, expireWhenStale, getJson, handle, hoursOld, utc} from './common.ts';
import {COLOURS, fresh, particles, validate} from '../wind-layer.js';

type Listener = () => void;
/** The subset of MapLibre's Map the particle module calls, over the engine's view. */
export function viewAsMap(view: MapView) {
  const offs = new Map<string, Map<Listener, () => void>>();
  const bucket = (type: string) => offs.get(type) ?? offs.set(type, new Map()).get(type)!;
  return {
    getCanvas: () => ({clientWidth: view.size().width, clientHeight: view.size().height}),
    on(type: 'resize' | 'movestart', listener: Listener) { bucket(type).set(listener, view.on(type, listener)); },
    off(type: string, listener: Listener) { bucket(type).get(listener)?.(); bucket(type).delete(listener); },
    unproject: ([x, y]: [number, number]) => { const p = view.unproject(x, y); return {lng: p.lon, lat: p.lat}; },
    project: ([lon, lat]: [number, number]) => view.project(lon, lat),
    isMoving: () => view.busy(),
  };
}

export const attach: PreviewAttach = async ctx => {
  const grid = validate(await getJson(ctx, PREVIEW_DATA.wind));
  if (ctx.signal.aborted) return null;
  const usable = () => fresh(grid, ctx.now().getTime());
  if (!usable()) {
    ctx.report({state: 'stale', dataTime: grid.data_time, text: `Wind run ${utc(String(grid.run_time))} is past its 18 h limit or not valid. Withheld.`});
    return null;
  }
  const canvas = document.createElement('canvas');
  canvas.setAttribute('aria-hidden', 'true');
  canvas.dataset.previewLayer = 'wind';
  Object.assign(canvas.style, {position: 'absolute', inset: '0', width: '100%', height: '100%', pointerEvents: 'none'});
  ctx.engine.view.container().appendChild(canvas);
  const overlay = particles(viewAsMap(ctx.engine.view), canvas, grid);
  overlay.setVisible(true);
  const stopped = () => { overlay.stop(); canvas.remove(); };
  ctx.report({state: 'ready', dataTime: String(grid.data_time), ramp: {colours: COLOURS, low: '0 kt', high: '30+ kt'},
    text: `Valid ${utc(String(grid.data_time))}, run ${utc(String(grid.run_time))} (${ageText(hoursOld(String(grid.run_time), ctx.now()))}). Forecast, not observations. Trails move downwind; motion exaggerated.`});
  const stopTimer = expireWhenStale(ctx, usable, () => {
    stopped();
    ctx.report({state: 'stale', dataTime: String(grid.data_time), text: `Wind run ${utc(String(grid.run_time))} passed its 18 h limit. Withheld.`});
  });
  return handle(stopTimer, stopped);
};
