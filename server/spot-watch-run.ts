export const WATCH_FEED_LAYERS = {
  'water-temp': {layer: 'sst-analysis', field: 'temperature_c'},
  chlorophyll: {layer: 'chlorophyll-observation', field: 'chlorophyll_mg_m3'},
  'sst-contrast': {layer: 'sst-analysis', field: 'temperature_gradient_c_per_km'},
} as const;

export const MAX_OWNER_WATCHES = 50;

export type WatchRunPlan =
  | {run: false; reason: 'degraded' | 'no-publication' | 'no-watches'}
  | {
    run: true;
    publication: string;
    evaluate: string[];
    unknown: {id: string; reason: 'unknown-layer' | 'layer-missing' | 'layer-withheld'}[];
    deferred: string[];
  };

function compare(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Plan work for one owner and publication without reading any feed data. */
export function planWatchRun(input: {
  degraded: boolean;
  publication: string | null;
  layers: Readonly<Record<string, {status: string}>>;
  watches: readonly {id: string; layer: string; enabled: boolean; createdAt: string}[];
}): WatchRunPlan {
  if (input.degraded) return {run: false, reason: 'degraded'};
  const {publication} = input;
  if (!publication) return {run: false, reason: 'no-publication'};

  const enabled = input.watches.filter(watch => watch.enabled);
  if (!enabled.length) return {run: false, reason: 'no-watches'};
  enabled.sort((a, b) => compare(a.createdAt, b.createdAt) || compare(a.id, b.id));

  const plan: Extract<WatchRunPlan, {run: true}> = {
    run: true, publication, evaluate: [], unknown: [],
    deferred: enabled.slice(MAX_OWNER_WATCHES).map(watch => watch.id),
  };
  for (const {id, layer} of enabled.slice(0, MAX_OWNER_WATCHES)) {
    if (!Object.hasOwn(WATCH_FEED_LAYERS, layer)) {
      plan.unknown.push({id, reason: 'unknown-layer'});
      continue;
    }
    const feedLayer = WATCH_FEED_LAYERS[layer as keyof typeof WATCH_FEED_LAYERS].layer;
    const feed = Object.hasOwn(input.layers, feedLayer) ? input.layers[feedLayer] : undefined;
    if (!feed) plan.unknown.push({id, reason: 'layer-missing'});
    else if (feed.status !== 'ok' && feed.status !== 'retained') plan.unknown.push({id, reason: 'layer-withheld'});
    else plan.evaluate.push(id);
  }
  return plan;
}
