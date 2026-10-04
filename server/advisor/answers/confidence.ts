// The recent-activity confidence ladder (Insufficient / Low / Moderate) for the
// landing reports in the daily feed, re-implemented for the Worker
// (docs/plans/text-advisor/06-angler-answers.md § what's biting, principle 6,
// docs/bite-evidence.md). server/ does not import the browser modules, so this
// is a copy of reportEvidence() in dist/bite-evidence.js (the plan named
// web/confidence.ts, which holds the map badges, not this ladder);
// tests/test_advisor_tools.mjs pins the two to the same feeds, including the
// fixtures tests/test_evidence.mjs builds.
//
// Moderate needs a fresh feed (generated within 36 h), all seven recent report
// pages checked, and at least five positive trips from two boats across three
// dates. Fewer reports are Low; none are Insufficient. No High, no number.

const HOUR = 3600000;
export type Confidence = 'Insufficient' | 'Low' | 'Moderate';
export const CONFIDENCE_WORDS: readonly Confidence[] = ['Insufficient', 'Low', 'Moderate'];

/** A target id ('reef' is lingcod and rockfish) as the species keys the feed uses (dist/target-groups.js). */
export const targetSpecies = (target: string): string[] => target === 'reef' ? ['lingcod', 'rockfish'] : [target];

interface Catch {species?: string; count?: number}
export interface LandingReport {id?: string; date?: string; boat?: string; port?: string; ground_id?: string | null; trip_type?: string; catches?: Catch[]; species?: string[]}
export interface DailyFeed {schema_version?: number; generated_at?: string; sources?: Record<string, {status?: string; data_retrieved_at?: string} | undefined>; reports?: LandingReport[];
  health?: unknown; catch_probability?: unknown; bite_score?: unknown; region_id?: string}

/** dist/bite-evidence.js validFeed. */
export function validFeed(data: DailyFeed | null | undefined): boolean {
  return Boolean(data?.schema_version === 1 && Number.isFinite(Date.parse(data.generated_at ?? '')) && data.sources && !Array.isArray(data.sources) &&
    Array.isArray(data.reports) && data.health && data.catch_probability === null && data.bite_score === null);
}

const age = (s: string | undefined, now: number): number => Number.isFinite(Date.parse(s ?? '')) ? (now - Date.parse(s!)) / HOUR : Infinity;
const dayFormats = new Map<string, Intl.DateTimeFormat>();
function localDay(now: number, tz: string): string {
  let f = dayFormats.get(tz);
  if (!f) { f = new Intl.DateTimeFormat('en-CA', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit'}); dayFormats.set(tz, f); }
  return f.format(new Date(now));
}

export interface Evidence {
  confidence: Confidence; fresh: boolean; reports: LandingReport[]; boats: number; days: number; coverage: number;
  start: string; end: string; named: number; catch_probability: null; bite_score: null;
}

/** dist/bite-evidence.js reportEvidence (without the reason text), for one target over the last seven days before today. */
export function reportEvidence(data: DailyFeed | null | undefined, target: string, now = Date.now(), groundId: string | null = null, tz = 'America/Los_Angeles'): Evidence {
  const today = localDay(now, tz);
  const first = new Date(Date.parse(today + 'T12:00:00Z') - 7 * 24 * HOUR).toISOString().slice(0, 10);
  const fresh = validFeed(data) && age(data!.generated_at, now) >= -1 && age(data!.generated_at, now) <= 36;
  const species = targetSpecies(target);
  const reports = (data?.reports || []).filter(r => (r.date ?? '') >= first && (r.date ?? '') < today && (!groundId || r.ground_id === groundId) &&
    r.catches?.some(c => species.includes(c.species ?? '') && (c.count ?? 0) > 0));
  const boats = new Set(reports.map(r => r.boat)).size;
  const days = new Set(reports.map(r => r.date)).size;
  const pages = Array.from({length: 7}, (_, i) => new Date(Date.parse(today + 'T12:00:00Z') - (i + 1) * 24 * HOUR).toISOString().slice(0, 10));
  const coverage = pages.filter(d => {
    const s = data?.sources?.['catches-' + d];
    return s?.status === 'ok' && age(s.data_retrieved_at, now) <= 36 && age(s.data_retrieved_at, now) >= -1;
  }).length;
  let confidence: Confidence = 'Insufficient';
  if (reports.length) confidence = 'Low';
  if (fresh && coverage === 7 && reports.length >= 5 && boats >= 2 && days >= 3) confidence = 'Moderate';
  return {confidence, fresh, reports, boats, days, coverage, start: first, end: pages[0]!, named: reports.filter(r => r.ground_id).length, catch_probability: null, bite_score: null};
}
