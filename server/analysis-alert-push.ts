import {ANALYSIS_LAYERS, type AnalysisAlert} from './analysis-alerts.ts';
import {PUSH_BODY_MAX} from './spot-watch-push.ts';

type AnalysisAlertPushResult =
  | {ok: true; push: {title: string; body: string; eventId: string; url: string}}
  | {ok: false; reason: 'claim-words' | 'too-long'};

export function analysisEventId({region, layer, sampleAt}: AnalysisAlert): string {
  if (!region || !sampleAt) throw new TypeError('Region and sample timestamp are required');
  if (!ANALYSIS_LAYERS.some(allowed => allowed === layer)) throw new TypeError('Invalid analysis layer');
  return `analysis:${region}:${layer}:${sampleAt}`;
}

export function analysisUrl(region: string, layer: string): string {
  if (!/^[a-z0-9-]+$/.test(region)) throw new TypeError('Invalid region');
  if (layer !== 'sst-analysis' && layer !== 'chlorophyll-observation') {
    throw new TypeError('Invalid analysis layer');
  }
  const mapLayer = layer === 'sst-analysis' ? 'water-temp' : 'chlorophyll';
  return `/map?region=${encodeURIComponent(region)}&layers=${mapLayer}`;
}

export function analysisAlertPush(
  a: AnalysisAlert,
  title: string,
  regionName: string,
  render: (regionName: string) => string,
): AnalysisAlertPushResult {
  const eventId = analysisEventId(a);
  const url = analysisUrl(a.region, a.layer);
  // Screen the template alone, consistent with spot-watch pushes.
  if (/\b(fish|fishing|bite|bites|hot ?spots?|best|predict(?:s|ed)?)\b/i.test(render(''))) {
    return {ok: false, reason: 'claim-words'};
  }
  let body = render(regionName);
  if ([...body].length <= PUSH_BODY_MAX) return {ok: true, push: {title, body, eventId, url}};

  const name = [...regionName];
  // Re-render to preserve the whole template, trying the longest prefix first.
  for (let end = name.length - 1; end >= 1; end--) {
    body = render(name.slice(0, end).join('') + '…');
    if ([...body].length <= PUSH_BODY_MAX) return {ok: true, push: {title, body, eventId, url}};
  }
  return {ok: false, reason: 'too-long'};
}
