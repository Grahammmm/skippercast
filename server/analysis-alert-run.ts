import {ANALYSIS_LAYERS, type AnalysisAlert} from './analysis-alerts.ts';

export const MAX_ANALYSIS_ALERTS_PER_RUN = 200;

type AnalysisAlertRunPlan =
  | {run: false; reason: 'degraded' | 'no-candidates'}
  | {run: true; send: AnalysisAlert[]; noDevice: AnalysisAlert[]; deferred: AnalysisAlert[]};

const compare = (a: string, b: string): number => a < b ? -1 : a > b ? 1 : 0;

/** Plan one publication's sends without attempting delivery. */
export function planAnalysisAlertRun(input: {
  degraded: boolean;
  candidates: readonly AnalysisAlert[];
  devices: ReadonlySet<string>;
}): AnalysisAlertRunPlan {
  if (input.degraded) return {run: false, reason: 'degraded'};

  const unique = new Map<string, AnalysisAlert>();
  for (const candidate of input.candidates) {
    if (candidate == null) continue;
    const {owner, region, layer, sampleAt} = candidate;
    if (typeof owner !== 'string' || typeof region !== 'string' || typeof layer !== 'string' ||
        typeof sampleAt !== 'string' || !ANALYSIS_LAYERS.some(allowed => allowed === layer)) continue;
    const key = JSON.stringify([owner, region, layer]);
    if (!unique.has(key)) unique.set(key, {owner, region, layer, sampleAt});
  }
  if (unique.size === 0) return {run: false, reason: 'no-candidates'};

  const ordered = [...unique.values()].sort((a, b) =>
    compare(a.owner, b.owner) || compare(a.region, b.region) || compare(a.layer, b.layer));
  const plan: Extract<AnalysisAlertRunPlan, {run: true}> = {run: true, send: [], noDevice: [], deferred: []};
  for (const alert of ordered) {
    if (!input.devices.has(alert.owner)) plan.noDevice.push(alert);
    else if (plan.send.length < MAX_ANALYSIS_ALERTS_PER_RUN) plan.send.push(alert);
    else plan.deferred.push(alert);
  }
  return plan;
}
