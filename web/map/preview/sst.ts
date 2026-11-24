// MAPLIVE-1: sea-surface temperature, style "SST 2" (MAPLAYER-SST-1; research/scripts/map_style/build_sst.py).
// Native analysis cells in 14 bands from 52 to 66 °F, with strong-break lines. The file carries its own time and
// age limit; an older or unreadable analysis draws nothing.
import type {Overlay} from '../engine.ts';
import type {Palette} from '../palette.ts';
import {PREVIEW_DATA, type PreviewAttach} from '../preview-layers.ts';
import {paintEdits} from '../theme-restyle.ts';
import {ageText, BEFORE_APP_LAYERS, expireWhenStale, freshWithin, getJson, handle, hoursOld, isPositiveFiniteHours, utc} from './common.ts';

export const SST_CELLS = 'preview-sst-cells', SST_BREAKS = 'preview-sst-breaks', SST_HALO = 'preview-sst-break-halo', SST_LINES = 'preview-sst-break-line';

interface SstDoc {data_time: string; max_age_hours: number; colours: string[]; cells: unknown; breaks: unknown; source_id?: string}

export function readSst(raw: unknown): SstDoc {
  const d = raw as Partial<SstDoc> | null;
  const collection = (v: unknown): boolean => !!v && (v as {type?: unknown}).type === 'FeatureCollection' && Array.isArray((v as {features?: unknown}).features);
  // The producer emits #rrggbb; keep valid #rgb shorthand too. The legend gradient needs at least two stops.
  if (!d || typeof d.data_time !== 'string' || !isPositiveFiniteHours(d.max_age_hours) ||
      !Array.isArray(d.colours) || d.colours.length < 2 ||
      ![...d.colours].every(c => typeof c === 'string' && /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(c)) ||
      !collection(d.cells) || !collection(d.breaks)) {
    throw new Error('analysis file is not a valid SST preview');
  }
  return d as SstDoc;
}

/** The strong-break line is the token text colour over a token dark under-stroke, so it reads on every band. */
const sstLayers = (p: Pick<Palette, 'text' | 'bgDeep'>): Overlay['layers'] => [
  {id: SST_CELLS, type: 'fill', source: SST_CELLS, paint: {'fill-color': ['get', 'colour'], 'fill-opacity': 0.82, 'fill-antialias': false}},
  {id: SST_HALO, type: 'line', source: SST_BREAKS, paint: {'line-color': p.text, 'line-width': 2.4}},
  {id: SST_LINES, type: 'line', source: SST_BREAKS, paint: {'line-color': p.bgDeep, 'line-width': 0.5}},
];

/** The cell colours come from the file, so only the two break lines follow the theme; a switch edits their paints in place. */
export function sstOverlay(d: SstDoc, p: Pick<Palette, 'text' | 'bgDeep'>): Overlay {
  return {
    sources: {
      [SST_CELLS]: {type: 'geojson', data: d.cells as never, attribution: 'NOAA CoastWatch / GHRSST'},
      [SST_BREAKS]: {type: 'geojson', data: d.breaks as never},
    },
    layers: sstLayers(p),
    themePaint: q => paintEdits(sstLayers(q)),
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
