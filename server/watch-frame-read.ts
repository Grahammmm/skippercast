import {habitatTileURL, layerOf, SST_LAYER_ID, tileRows} from '../web/map/habitat-feed.ts';
import type {WatchFrame} from './spot-watch-eval.ts';
import {WATCH_FEED_LAYERS} from './spot-watch-run.ts';

export type WatchFrameRead = {state: 'ready'; frame: WatchFrame} | {state: 'none' | 'withheld' | 'error'};

/** Verify a published frame before handing its native rows to the watch evaluator. */
export async function readWatchFrame(
  read: (key: string) => Promise<ArrayBuffer | null>, regionId: string, watchLayer: string,
): Promise<WatchFrameRead> {
  if (!Object.hasOwn(WATCH_FEED_LAYERS, watchLayer)) return {state: 'none'};
  const {layer: id, field: valueField} = WATCH_FEED_LAYERS[watchLayer as keyof typeof WATCH_FEED_LAYERS];
  const manifestKey = `conditions/regions/${regionId}/habitat-dynamics.json`;
  const [kind, baseField] = id === SST_LAYER_ID ? ['analysis', 'temperature_c'] as const : ['observation', 'chlorophyll_mg_m3'] as const;
  try {
    const bytes = await read(manifestKey);
    if (bytes === null) return {state: 'none'};
    const layer = layerOf(JSON.parse(new TextDecoder().decode(bytes)), regionId, id, kind, [baseField, valueField]);
    if (!layer) return {state: 'none'};
    if (layer.status !== 'ok' && layer.status !== 'retained') return {state: 'withheld'};
    // Match habitat-feed.ts's populated rule, including absent and nonnumeric counts.
    const latest = Math.max(...layer.frames.filter(({valid_cells: count}) =>
      typeof count !== 'number' || !Number.isFinite(count) || count > 0).map(({time}) => time));
    if (latest === -Infinity) return {state: 'withheld'};

    // The synthetic origin is only for the browser's region/path checks; read object keys, not URLs.
    const manifestURL = `https://habitat.invalid/${manifestKey}`;
    const tiles = layer.tiles.map(ref => ({ref, key: new URL(habitatTileURL(manifestURL, ref, regionId)).pathname.slice(1)}));
    const rows: unknown[][] = [];
    for (const {ref, key} of tiles) {
      const tile = await read(key);
      if (tile === null) return {state: 'error'};
      const frames = await tileRows(tile, ref, regionId, layer);
      for (const row of frames.get(latest) ?? []) rows.push(row);
    }

    const supported = watchLayer === 'sst-contrast' ? layer.fields.indexOf('thermal_contrast_supported') : -1;
    const value = layer.fields.indexOf(valueField);
    return {state: 'ready', frame: {
      sampleAt: new Date(latest * 1000).toISOString(), fields: layer.fields, resolution: layer.resolution, valueField,
      rows: supported === -1 ? rows : rows.map(row => {
        if (row[supported] === 1 || row[supported] === true) return row;
        const masked = [...row];
        masked[value] = null;
        return masked;
      }),
    }};
  } catch {
    return {state: 'error'};
  }
}
