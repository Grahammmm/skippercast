export const PUSH_BODY_MAX = 120;

type WatchLayer = 'water-temp' | 'chlorophyll' | 'sst-contrast';

type SpotWatchPushInput = {
  watchId: string;
  sampleAt: string;
  region: string;
  spotId: string;
  layer: WatchLayer;
  spotName: string;
  title: string;
};

type SpotWatchPushResult =
  | {ok: true; push: {title: string; body: string; eventId: string; url: string}}
  | {ok: false; reason: 'too-long' | 'claim-words'};

export function spotWatchEventId(watchId: string, sampleAt: string): string {
  if (!watchId || !sampleAt) throw new TypeError('Watch ID and sample timestamp are required');
  return `spotwatch:${watchId}:${sampleAt}`;
}

export function spotWatchUrl(region: string, spotId: string, layer: WatchLayer): string {
  if (!/^[a-z0-9-]+$/.test(region)) throw new TypeError('Invalid region');
  if (!spotId) throw new TypeError('Spot ID is required');
  if (layer !== 'water-temp' && layer !== 'chlorophyll' && layer !== 'sst-contrast') {
    throw new TypeError('Invalid watch layer');
  }
  return `/map?region=${encodeURIComponent(region)}&spot=${encodeURIComponent(spotId)}&layers=${layer}`;
}

export function spotWatchPush(
  {watchId, sampleAt, region, spotId, layer, spotName, title}: SpotWatchPushInput,
  render: (spotName: string) => string,
): SpotWatchPushResult {
  const eventId = spotWatchEventId(watchId, sampleAt);
  const url = spotWatchUrl(region, spotId, layer);
  // Screen only the caller's template, not the user's name.
  if (/\b(fish|fishing|bite|bites|hot ?spots?)\b/i.test(render(''))) {
    return {ok: false, reason: 'claim-words'};
  }
  let body = render(spotName);
  if ([...body].length <= PUSH_BODY_MAX) return {ok: true, push: {title, body, eventId, url}};

  const name = [...spotName];
  // Re-render each shorter prefix; slicing the body could drop template text.
  for (let end = name.length - 1; end >= 1; end--) {
    body = render(name.slice(0, end).join('') + '…');
    if ([...body].length <= PUSH_BODY_MAX) return {ok: true, push: {title, body, eventId, url}};
  }
  return {ok: false, reason: 'too-long'};
}
