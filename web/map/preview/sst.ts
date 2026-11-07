// MAPLIVE-1: sea-surface temperature, style "SST 2" (MAPLAYER-SST-1; research/scripts/map_style/build_sst.py).
// Native analysis cells in 14 bands from 52 to 66 °F, with strong-break lines. The file carries its own time and
// age limit; an older or unreadable analysis draws nothing.
import type {Overlay} from '../engine.ts';
import type {Palette} from '../palette.ts';
import {PREVIEW_DATA, type PreviewAttach} from '../preview-layers.ts';
import {ageText, BEFORE_APP_LAYERS, expireWhenStale, freshWithin, getJson, handle, hoursOld, utc} from './common.ts';

export const SST_CELLS = 'preview-sst-cells', SST_BREAKS = 'preview-sst-breaks', SST_HALO = 'preview-sst-break-halo', SST_LINES = 'preview-sst-break-line';

interface SstDoc {data_time: string; max_age_hours: number; colours: string[]; cells: unknown; breaks: unknown; source_id?: string}

export function readSst(raw: unknown): SstDoc {
  const d = raw as Partial<SstDoc> | null;
  const collection = (v: unknown): boolean => !!v && (v as {type?: unknown}).type === 'FeatureCollection' && Array.isArray((v as {features?: unknown}).features);
  if (!d || typeof d.data_time !== 'string' || !(Number(d.max_age_hours) > 0) || !Array.isArray(d.colours) || !collection(d.cells) || !collection(d.breaks)) {
    throw new Error('analysis file is not a valid SST preview');
  }
  return d as SstDoc;
}

/** The strong-break line is the token text colour over a token dark under-stroke, so it reads on every band. */
export function sstOverlay(d: SstDoc, p: Pick<Palette, 'text' | 'bgDeep'>): Overlay {
  return {
    sources: {
      [SST_CELLS]: {type: 'geojson', data: d.cells as never, attribution: 'NOAA CoastWatch / GHRSST'},
      [SST_BREAKS]: {type: 'geojson', data: d.breaks as never},
    },
    layers: [
      {id: SST_CELLS, type: 'fill', source: SST_CELLS, paint: {'fill-color': ['get', 'colour'], 'fill-opacity': 0.82, 'fill-antialias': false}},
      {id: SST_HALO, type: 'line', source: SST_BREAKS, paint: {'line-color': p.text, 'line-width': 2.4}},
      {id: SST_LINES, type: 'line', source: SST_BREAKS, paint: {'line-color': p.bgDeep, 'line-width': 0.5}},
    ],
  };
}

export const attach: PreviewAttach = async ctx => {
  const d = readSst(await getJson(ctx, PREVIEW_DATA.sst));
  if (ctx.signal.aborted) return null;
  const usable = () => freshWithin(d.data_time, d.max_age_hours, ctx.now());
  const ramp = {colours: d.colours, low: '52 °F', high: '66 °F'};
  if (!usable()) {
    ctx.report({state: 'stale', dataTime: d.data_time, text: `Analysis ${utc(d.data_time)} is older than its ${d.max_age_hours} h limit or not valid. Withheld.`});
    return null;
  }
  const draw = () => ctx.engine.setOverlay(SST_CELLS, sstOverlay(d, ctx.palette()), BEFORE_APP_LAYERS);
  draw();
  const text = () => `Analysis ${utc(d.data_time)} (${ageText(hoursOld(d.data_time, ctx.now()))}). Not live observations.`;
  ctx.report({state: 'ready', dataTime: d.data_time, text: text(), ramp});
  const stopTimer = expireWhenStale(ctx, usable, () => {
    ctx.engine.setOverlay(SST_CELLS, null);
    ctx.report({state: 'stale', dataTime: d.data_time, text: `Analysis ${utc(d.data_time)} passed its ${d.max_age_hours} h limit. Withheld.`});
  });
  return handle(stopTimer, () => ctx.engine.setOverlay(SST_CELLS, null));
};
