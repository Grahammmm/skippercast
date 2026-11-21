import {layerOf} from '../web/map/habitat-feed.ts';
import {WATCH_FEED_LAYERS} from './spot-watch-run.ts';

const feedLayers = new Set(Object.values(WATCH_FEED_LAYERS).map(({layer}) => layer));
const manifestRequirements = {
  'sst-analysis': {kind: 'analysis', needs: ['temperature_c']},
  'chlorophyll-observation': {kind: 'observation', needs: ['chlorophyll_mg_m3']},
};

/** Read manifest statuses for the watch planner without loading any tiles. */
export function watchFeedLayers(manifest: unknown, regionId: string): Record<string, {status: string}> {
  const layers: Record<string, {status: string}> = {};
  for (const id of feedLayers) {
    const {kind, needs} = manifestRequirements[id];
    try {
      const layer = layerOf(manifest, regionId, id, kind, needs);
      if (layer) layers[id] = {status: layer.status};
    } catch {
      // Treat a rejected layer as missing without discarding other layers.
    }
  }
  return layers;
}
