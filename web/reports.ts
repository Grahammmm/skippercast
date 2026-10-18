// Reports view data (FE-52, docs/plans/front-end/design.md § 6): what v1's
// Forecast and Guide panels show as dated evidence, gathered for the v2
// Reports page (web/app/views/Reports.tsx). Each section keeps v1's own rules
// by calling v1's modules, never a copy of them:
// - discussions: dist/recent-discussions.js `recentDiscussionState` over
//   /feeds/data/recent-intel.json (unreviewed links, at most four, 30 days);
// - recent evidence: dist/bite-evidence.js `validFeed` and `reportEvidence`
//   over the region's daily evidence feed (the `data` branch, the feed v1's
//   Forecast panel reads), with its Insufficient / Low / Moderate rule;
// - seasonal watch: dist/coasts.js `loadCoasts`, `coastForPackage`,
//   `loadCoastalStatus` and `sourceFresh`, as `seasonalMarkup` reads them;
// - charter evidence: dist/charter-grounds.js `reportSummary` over the
//   region's published charter grounds, broad regional names left out.
// Catch cards are packages/coast `catchSheet`, mounted by the view through
// CoastMarkup. This module is loaded with a dynamic import when the view
// first opens, so none of these v1 modules joins the app entry.
//
// Nothing here ranks places or predicts catches: rows are dated records with
// their source links, ordered by date. A failed source gives that section an
// unavailable state; the others still show.
import {validFeed, reportEvidence} from '../dist/bite-evidence.js';
import {reportSummary} from '../dist/charter-grounds.js';
import {coastForPackage, loadCoastalStatus, loadCoasts, sourceFresh} from '../dist/coasts.js';
import {recentDiscussionState} from '../dist/recent-discussions.js';
import {matchesTargetSpecies} from '../dist/target-groups.js';

export const DISCUSSIONS_FEED = '/feeds/data/recent-intel.json';
/** The region's daily evidence feed (region.json `daily_feed`, routed through /feeds/). */
export const evidenceFeed = (region: string): string => `/feeds/data/regions/${encodeURIComponent(region)}/latest.json`;
/** Charter grounds shown at most; the rest are counted. */
export const CHARTER_LIMIT = 6;

const https = (value: unknown): string | null => {
  try { const url = new URL(String(value)); return url.protocol === 'https:' && !url.username && !url.password ? url.href : null; } catch { return null; }
};

export interface Discussion {readonly url: string; readonly title: string; readonly source: string; readonly published_at: string; readonly location_basis?: string}
/** `recentDiscussionState`'s result, typed. */
export interface Discussions {
  readonly status: 'unavailable' | 'stale' | 'current' | 'degraded'; readonly candidates: readonly Discussion[];
  readonly checkedQueries: number; readonly totalQueries: number; readonly generatedAt?: string;
}

export interface EvidenceRow {readonly date: string; readonly boat: string; readonly catches: string; readonly where: string; readonly url: string | null}
export interface Evidence {
  readonly confidence: string; readonly reason: string; readonly start: string; readonly end: string;
  readonly boats: number; readonly days: number; readonly trips: number; readonly generatedAt: string; readonly rows: readonly EvidenceRow[];
}

type FeedCatch = {species?: unknown; label?: unknown; count?: unknown; disposition?: unknown};
type FeedReport = {date: string; boat: string; port?: string; ground?: string; anglers?: number | null; source_url?: string; catches?: FeedCatch[]};

/** v1's evidence for `species` over the daily feed, its five latest trips as rows; null when the feed is not this region's or fails v1's schema check. */
export function evidenceFrom(data: unknown, region: string, species: string, now = Date.now()): Evidence | null {
  const feed = data as {region_id?: string; generated_at: string} | null;
  if (!validFeed(data) || feed?.region_id !== region) return null;
  const e = reportEvidence(data, species, now);
  const rows = (e.reports as FeedReport[]).slice(0, 5).map(r => ({
    date: r.date, boat: r.boat, url: https(r.source_url),
    catches: (r.catches ?? []).filter(c => matchesTargetSpecies(c.species, species) && Number(c.count) > 0)
      .map(c => `${Number(c.count)} ${String(c.label ?? c.species)}${c.disposition === 'released' ? ' released' : ' reported'}`).join(' · '),
    where: r.ground ? `Reported ground: ${r.ground}` : `${r.port ?? 'Port'} landing · fishing location unreported`,
  }));
  return {confidence: e.confidence, reason: e.reason, start: e.start, end: e.end ?? e.start, boats: e.boats, days: e.days, trips: e.reports.length, generatedAt: feed.generated_at, rows};
}

export interface WatchItem {readonly name: string; readonly located: boolean; readonly links: readonly {date: string; publisher: string; url: string}[]}
export interface Watch {readonly coast: string; readonly items: readonly WatchItem[]; readonly checked: boolean}

type Catalog = {regions: unknown[]; target_names: Record<string, string>};
type Coast = {id: string; name: string; watch: string[]};
type Status = {completed_at?: string; regions?: Record<string, {watch?: {target: string; status: string; evidence?: {url: string; date: string; publisher: string}[]}[]}>} | null;

/** The seasonal watch `seasonalMarkup` lists: located-report links only while the status snapshot is fresh. */
export function watchFrom(catalog: Catalog, coast: Coast, status: Status, now = Date.now()): Watch {
  const fresh = !!status && sourceFresh({status: 'ok', data_retrieved_at: status.completed_at}, 36, now);
  const watch = status?.regions?.[coast.id]?.watch ?? coast.watch.map(target => ({target, status: 'watch-only', evidence: []}));
  return {coast: coast.name, checked: !!status, items: watch.map(w => {
    const located = fresh && w.status === 'recent-located-reports';
    const links = located ? (w.evidence ?? []).flatMap(e => { const url = https(e.url); return url ? [{date: String(e.date), publisher: String(e.publisher), url}] : []; }) : [];
    return {name: catalog.target_names[w.target] ?? w.target, located, links};
  })};
}

export interface CharterRow {readonly label: string; readonly ground: string; readonly trips: number; readonly boats: number; readonly latest: string | null; readonly sources: readonly {date: string; boat: string; url: string}[]}
export interface Charters {readonly audit: string; readonly rows: readonly CharterRow[]; readonly more: number}
type Ground = {label: string; reported_ground: string; precision: string; reports: {species: string[]; date: string; boat: string; source_url?: unknown}[]};

/** Grounds with trips reported for `species`, newest report first (not a ranking); broad regional names left out, as v1 does. */
export function chartersFrom(evidence: {audit_date?: unknown; grounds?: unknown} | null, species: string): Charters | null {
  if (!evidence || typeof evidence.audit_date !== 'string' || !Array.isArray(evidence.grounds)) return null;
  const all = (evidence.grounds as Ground[]).filter(g => g.precision !== 'Broad regional name')
    .map(g => ({g, s: reportSummary(g, species)})).filter(({s}) => s.trips > 0)
    .sort((a, b) => String(b.s.latest).localeCompare(String(a.s.latest)) || a.g.label.localeCompare(b.g.label))
    .map(({g, s}) => ({label: g.label, ground: g.reported_ground, trips: s.trips, boats: s.boats.length, latest: s.latest,
      sources: g.reports.filter(r => r.species.some(id => matchesTargetSpecies(id, species)))
        .flatMap(r => { const url = https(r.source_url); return url ? [{date: r.date, boat: r.boat, url}] : []; })}));
  return {audit: evidence.audit_date, rows: all.slice(0, CHARTER_LIMIT), more: Math.max(0, all.length - CHARTER_LIMIT)};
}

export interface ReportsData {
  readonly discussions: Discussions; readonly evidence: Evidence | null; readonly watch: Watch | null; readonly charters: Charters | null;
}
export interface ReportsInput {readonly region: string; readonly species: string; readonly charters?: string | null; readonly now?: number}

const json = async (fetchFn: typeof fetch, url: string): Promise<unknown> => {
  const response = await fetchFn(url, {cache: 'no-cache', signal: AbortSignal.timeout(15000)});
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
};

/** Load every section for `region` and `species`; each failure is that section's alone. */
export async function loadReports({region, species, charters, now = Date.now()}: ReportsInput, fetchFn: typeof fetch = fetch): Promise<ReportsData> {
  const [intel, daily, grounds, watch] = await Promise.all([
    json(fetchFn, DISCUSSIONS_FEED).catch(() => null),
    json(fetchFn, evidenceFeed(region)).catch(() => null),
    charters ? json(fetchFn, charters).catch(() => null) : Promise.resolve(null),
    (async () => {
      const catalog = await loadCoasts() as Catalog;
      const coast = coastForPackage(region, catalog) as Coast | null;
      return coast ? watchFrom(catalog, coast, await loadCoastalStatus(catalog) as Status, now) : null;
    })().catch(() => null),
  ]);
  return {
    discussions: recentDiscussionState(intel, region, now) as Discussions,
    evidence: evidenceFrom(daily, region, species, now),
    watch,
    charters: chartersFrom(grounds as {audit_date?: unknown; grounds?: unknown} | null, species),
  };
}
