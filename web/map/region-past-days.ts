import {pastDays} from '../hour.ts';
import {CHLOROPHYLL_LAYER_ID, SST_LAYER_ID, historyDays, layerOf} from './habitat-feed.ts';
import {pastDayCoverage} from './past-sample.ts';

/** Region-local dock days backed by validated manifest history references. */
export function regionPastDays(manifest: unknown, regionId: string, now: Date, tz: string): {days: {day: string; weekday: string; layers: string[]}[]} {
  function samplesFor(id: string, kind: string, needs: readonly string[]): string[] {
    try {
      const layer = layerOf(manifest, regionId, id, kind, needs);
      return layer ? historyDays(layer) : [];
    } catch {
      // A bad layer must not hide the other layer's history.
      return [];
    }
  }

  const sst = samplesFor(SST_LAYER_ID, 'analysis', ['temperature_c', 'analysis_error_c']);
  const chlorophyll = samplesFor(CHLOROPHYLL_LAYER_ID, 'observation', ['chlorophyll_mg_m3']);
  try {
    const days = pastDays(now, tz, [...new Set([...sst, ...chlorophyll])]);
    const keys = days.map(({day}) => day);
    const sstCoverage = pastDayCoverage(sst, keys, tz);
    const chlorophyllCoverage = pastDayCoverage(chlorophyll, keys, tz);
    return {days: days.map(({day, weekday}) => {
      const layers: string[] = [];
      if (sstCoverage[day]) layers.push(SST_LAYER_ID);
      if (chlorophyllCoverage[day]) layers.push(CHLOROPHYLL_LAYER_ID);
      return {day, weekday, layers};
    })};
  } catch {
    // The calendar helper can reject an invalid date or time zone.
    return {days: []};
  }
}
