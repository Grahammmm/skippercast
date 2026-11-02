// BF-landing-live: the landing's live answer. Tomorrow's day verdict for the default region and the
// reference boat, computed by the app's own loaders and brief code (web/brief/Brief.tsx briefFrom,
// web/brief/verdict.ts briefVerdict) from the same inputs the app's lead reads for
// /map?region=morro-bay&profile=boat: region info, the daily and conditions feeds, the regional
// forecast at the region centre and, where the region binds one, the coast report (its own client,
// destroyed after one read). The visitor's saved profile and limits are not read and nothing is
// stored. Landing.tsx imports this module dynamically after the readout resolves, so none of it is
// in the landing's entry chunk.
import {dateKey} from '../../packages/coast/src/daily.ts';
import {createRegionReader, REGION_MISSING} from '../app/region-info.ts';
import {briefFrom, leadDayText, leadHour, loadDailyFeed} from '../brief/Brief.tsx';
import {briefVerdict, VERDICT_WORD, type DayVerdict} from '../brief/verdict.ts';
import {createCoastData} from '../coast-data.ts';
import {loadConditionsForecast} from '../conditions.ts';
import {regionPlace} from '../map/currents.ts';
import {DEFAULT_REGION} from './readings.ts';

export type LandingVerdict = {verdict: DayVerdict; word: string; sentence: string; day: string; date: string; place: string; href: string};

/** The brief link for the verdict's day, with the reference boat named. */
export const briefHref = (region: string, date: string): string =>
  `/map?region=${encodeURIComponent(region)}&profile=boat&day=${date}`;

/** The coast report the app's brief would bind for `info` (Morro Bay, Cambria), or null when none binds or it cannot be read. */
async function boundReport(info: Parameters<typeof regionPlace>[0]) {
  const coast = createCoastData({clockEvents: null});
  try {
    if (!coast.setPlace(regionPlace(info, 'boat', ''))) return null;
    await coast.load('report');
    const report = coast.coastReport.peek(), binding = coast.coastBinding.peek();
    return report && binding ? {report: report.data, areaId: binding.areaId} : null;
  } finally { coast.destroy(); }
}

/**
 * Tomorrow's verdict for the default region at `now`, or null when the region or its feeds cannot be
 * read (no brief). A missing forecast reads Unknown, never a calmer word, as in the app.
 */
export async function loadLandingVerdict(fetchFn: typeof fetch = fetch, now: Date = new Date(), page: string = location.href): Promise<LandingVerdict | null> {
  const info = await createRegionReader(fetchFn)(DEFAULT_REGION).catch(() => null);
  if (!info || info === REGION_MISSING) return null;
  const [feed, forecast, coast] = await Promise.all([loadDailyFeed(info.id, fetchFn), loadConditionsForecast(info.id, info.center, fetchFn, page), boundReport(info).catch(() => null)]);
  const tz = info.timezone, hour = leadHour(null, null, now, tz);
  const brief = briefFrom({info, feed, forecast, coast, profile: 'boat', hour, limits: null}, now);
  const v = briefVerdict(brief, forecast?.region === info.id ? forecast : null, now, tz);
  if (!brief || !v) return null;
  const date = brief.date ?? dateKey(hour ? new Date(hour) : now, tz), when = leadDayText(date, now, tz);
  return {verdict: v.verdict, word: VERDICT_WORD[v.verdict], sentence: `${v.limit}${v.held ? ` ${v.held}` : ''}`,
    day: when.charAt(0).toUpperCase() + when.slice(1), date, place: info.name, href: briefHref(info.id, date)};
}
