import {layerOf} from '../web/map/habitat-feed.ts';
import {ANALYSIS_LAYERS} from './analysis-alerts.ts';

/** Latest populated sample time per available analysis layer, from the manifest alone. */
export function analysisSamples(manifest: unknown, regionId: string): Record<string, string> {
  const samples: Record<string, string> = {};
  for (const id of ANALYSIS_LAYERS) {
    try {
      const layer = id === 'sst-analysis'
        ? layerOf(manifest, regionId, id, 'analysis', ['temperature_c'])
        : layerOf(manifest, regionId, id, 'observation', ['chlorophyll_mg_m3']);
      if (!layer || (layer.status !== 'ok' && layer.status !== 'retained')) continue;

      // Match the habitat feed: only a finite, nonpositive cell count marks a frame empty.
      const times = layer.frames.filter(({valid_cells: count}) =>
        typeof count !== 'number' || !Number.isFinite(count) || count > 0).map(frame => frame.time);
      if (times.length === 0) continue;
      samples[id] = new Date(Math.max(...times) * 1000).toISOString();
    } catch {
      // A malformed layer or unconvertible newest time doesn't suppress the other layer.
    }
  }
  return samples;
}
