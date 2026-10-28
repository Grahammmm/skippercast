// The mark card's regulations line (FE-54, design § 6 and § 9): v1's
// "rules at a glance" row (dist/regulations.js `ruleSummary` over
// `regulationState`) for the selected target in the current region. The rule
// text is the reviewed registry's own, cut to its first clause exactly as v1
// cuts it and never rewritten; every line links the official CDFW page.
//
// dist/regulations.js reads v1's active region (dist/region.js) when it loads,
// which v2 never sets, so its pure functions are restated here with the region
// passed in (timezone, required species, authority hosts). tests/test_regs_wrapper.mjs
// pins each to v1's output over the committed registry, including #396's guard:
// a target resolves only through the registry's own keys, never an inherited
// one (`constructor`, `__proto__`). No fishing location is passed: a season that
// applies within a geographic band reads "Choose fishing location", as v1's
// header does before a location is chosen.
//
// Erasable syntax only: the tests import it by type stripping.
import {signal} from '@preact/signals';
import {dailyPartPath} from '../dist/offline-core.js';
import {validDailyPart} from './map/habitat.ts';

/** The registry is v1's JSON, read field by field as v1 reads it. */
type Data = any;
/** The region.json fields the rules read. */
export interface RulesRegion {
  readonly id: string; readonly timezone?: string; readonly species?: readonly string[]; readonly jurisdiction_id?: string;
  readonly regulatory_authority_hosts?: readonly string[]; readonly assets?: Readonly<Record<string, string | null>>;
}
export interface RuleState {
  status: string; label: string; today: string; reason: string; issues: string[]; profile?: Data; timingNote?: string | null; members?: RuleState[];
}
export interface RuleSummary {
  status: string; label: string; bag: string[]; size: string[]; depth: string | null; verified: string | null; checked: string | null; link: string; linkLabel: string;
}

/** CDFW's ocean fishing page: v1's link when no reviewed source names one. */
export const CDFW_OCEAN = 'https://wildlife.ca.gov/Fishing/Ocean';
const HOUR = 3600000;
const HOSTS = ['wildlife.ca.gov', 'nrm.dfg.ca.gov', 'www.fisheries.noaa.gov', 'www.ecfr.gov'];
const zoneOf = (r: RulesRegion): string => r.timezone ?? 'America/Los_Angeles';
const dayIn = (tz: string, at: number): string => new Intl.DateTimeFormat('en-CA', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(at));
/** #396: only the table's own key, never an inherited one. */
const own = (table: Data, id: string): Data => table && typeof table === 'object' && Object.hasOwn(table, id) ? table[id] : null;
const str = (v: unknown): v is string => typeof v === 'string';
const dateOnly = (s: unknown): boolean => /^\d{4}-\d{2}-\d{2}$/.test(String(s || '')) && Number.isFinite(Date.parse(String(s))) && new Date(String(s)).toISOString().slice(0, 10) === s;
const validOpening = (w: Data, tz: string): boolean => w.start_at === undefined || (str(w.start_at) && /T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})$/.test(w.start_at)
  && Number.isFinite(Date.parse(w.start_at)) && dayIn(tz, Date.parse(w.start_at)) === w.start);
const validGeography = (g: Data, sources: Data): boolean => g === undefined || (g?.kind === 'latitude-band' && Number.isFinite(g.south) && Number.isFinite(g.north)
  && g.south >= -90 && g.north <= 90 && g.south < g.north && str(g.source_id) && !!sources?.[g.source_id]?.url && str(g.note) && g.note.length > 0);
const validWindows = (p: Data, data: Data, tz: string): boolean => Array.isArray(p.windows) && p.windows.every((w: Data) => w && dateOnly(w.start) && dateOnly(w.end)
  && w.start <= w.end && validOpening(w, tz) && validGeography(w.geography, data.sources) && (!w.geography || p.source_ids.includes(w.geography.source_id)));
const age = (s: unknown, now: number): number => (now - Date.parse(String(s))) / HOUR;

/** dist/regulations.js `ruleProfile`: a target's own complete registry record, else null. */
export function ruleProfile(data: Data, id: string, region: RulesRegion): Data {
  const p = own(data?.species, id);
  return p && typeof p === 'object' && [p.name, p.season, p.bag, p.size].every(str) && Array.isArray(p.details) && p.details.every(str)
    && Array.isArray(p.source_ids) && p.source_ids.length && p.source_ids.every((s: unknown) => str(s) && own(data.sources, s)?.url) && validWindows(p, data, zoneOf(region)) ? p : null;
}
/** dist/regulations.js `officialURL`: an https page on one of the region's authority hosts, else CDFW's ocean page. */
export function officialURL(value: unknown, region: RulesRegion): string {
  try {
    const u = new URL(String(value));
    return u.protocol === 'https:' && !u.username && !u.password && (region.regulatory_authority_hosts ?? HOSTS).includes(u.hostname) ? u.href : CDFW_OCEAN;
  } catch { return CDFW_OCEAN; }
}
/** dist/regulations.js `sourceIssues`: sources whose daily check is missing, changed, unapproved or over 36 h old. */
export function sourceIssues(data: Data, ids: unknown, now: number): string[] {
  if (!Array.isArray(ids)) return ['rule-profile'];
  return ids.filter((id: string) => {
    const s = data.checks?.[id], d = data.sources?.[id], approved = d?.approved_content_sha256, a = age(s?.data_retrieved_at, now);
    return !s || s.status !== 'unchanged' || s.source_status !== 'ok' || s.url !== d?.url || s.normalization !== d?.normalization
      || !/^[a-f0-9]{64}$/.test(approved || '') || s.content_sha256 !== approved || !Number.isFinite(a) || a < -1 || a > 36;
  });
}
const required = (r: RulesRegion): string[] => [...new Set((r.species ?? []).flatMap(id => id === 'reef' ? ['lingcod', 'rockfish'] : [id]))];
/** dist/regulations.js `validRegulations` for `region`'s species. */
export function validRegulations(data: Data, region: RulesRegion): boolean {
  return data?.schema_version === 1 && Number.isFinite(Date.parse(data.reviewed_at)) && dateOnly(data.valid_from) && dateOnly(data.valid_through)
    && data.valid_from <= data.valid_through && !!data.sources && !!data.checks && Array.isArray(data.common_notes)
    && (!data.area_notices || Array.isArray(data.area_notices) && data.area_notices.every((n: Data) => str(n.id) && str(n.name) && str(n.note)
      && Array.isArray(n.source_ids) && n.source_ids.length && n.source_ids.every((id: string) => data.sources[id]?.url)))
    && required(region).every(id => !!ruleProfile(data, id, region));
}

const LABELS: Readonly<Record<string, string>> = {restricted: 'Depth / species restrictions', open: 'Season open', closed: 'Season closed', scheduled: 'Opener unconfirmed', unknown: 'Check rules'};
const clock = (s: unknown, tz: string): string => Number.isFinite(Date.parse(String(s))) ? new Date(String(s)).toLocaleString('en-US', {
  timeZone: tz, month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit'}) + ' PT' : 'Unavailable';

/**
 * dist/regulations.js `regulationState` with no method and no location, for the trip day
 * `tripDate` (the dock's) and its hour `tripInstant`.
 */
export function regulationState(data: Data, species: string, region: RulesRegion, now: number = Date.now(), tripDate: string | null = null, tripInstant: number | null = null): RuleState {
  const tz = zoneOf(region);
  if (species === 'reef') {
    const members = ['lingcod', 'rockfish'].map(id => regulationState(data, id, region, now, tripDate, tripInstant));
    const status = ['excluded', 'unknown', 'closed', 'scheduled', 'restricted', 'open'].find(s => members.some(m => m.status === s))!;
    const first = members.find(m => m.status === status)!;
    return {...first, members, issues: [...new Set(members.flatMap(m => m.issues))],
      label: status === 'closed' && members.some(m => m.status !== 'closed') ? 'Check both seasons' : first.label};
  }
  const today = dateOnly(tripDate) ? tripDate! : dayIn(tz, now);
  const p = validRegulations(data, region) ? ruleProfile(data, species, region) : null;
  if (!p) return {status: 'unknown', label: 'Check rules', today, reason: 'Regulations unavailable. Open the official CDFW rules before fishing.', issues: []};
  const issues = sourceIssues(data, p.source_ids, now);
  const reviewed = today >= data.valid_from && today <= data.valid_through && age(data.reviewed_at, now) >= -1;
  const window = p.windows.find((w: Data) => today >= w.start && today <= w.end);
  let status = !window ? 'closed' : window.requires_opening_review ? 'scheduled' : window.restriction ? 'restricted' : 'open';
  let reason = status === 'closed' ? 'Outside the reviewed local season.' : status === 'scheduled'
    ? 'Scheduled opening only. A new review of season, health and trap restrictions is required before showing open.' : 'Local closures, MPAs and gear restrictions still apply.';
  if (window?.restriction) reason = window.restriction;
  const opening = window?.start_at ? Date.parse(window.start_at) : null;
  const timed = Number.isFinite(tripInstant) && dayIn(tz, tripInstant!) === today ? tripInstant : !tripDate ? now : null;
  let timingNote: string | null = null, timedRestriction = false;
  if (opening !== null && today === window.start) {
    timingNote = `Season starts ${clock(window.start_at, tz)}. The opening date is not an all-day opening.`;
    if (timed !== null && timed < opening) { status = 'closed'; reason = `Before the legal opening time. ${timingNote}`; }
    else if (timed === null && status === 'open') { status = 'restricted'; timedRestriction = true; reason = timingNote; }
  }
  if (data.rules_review_status !== 'reviewed') { status = 'unknown'; reason = 'Saved regulatory content needs review. Consult the official rules before fishing.'; }
  else if (!reviewed) { status = 'unknown'; reason = 'This date is outside the reviewed rule period. Current-year rules need review.'; }
  else if (issues.length) {
    status = 'unknown';
    reason = issues.some(id => data.checks[id]?.status === 'changed') ? 'An official source changed after review. The saved limits below may have changed; check CDFW.'
      : 'The daily source check is incomplete or over 36 hours old. Check CDFW; saved rules are shown below.';
  }
  const state: RuleState = {status, label: timedRestriction && status === 'restricted' ? 'Opening time applies' : LABELS[status]!, today, reason, issues, profile: p, timingNote};
  // v1's geographicSeasonState with no location chosen.
  const area = window?.geography;
  return area && ['open', 'restricted'].includes(status) ? {...state, status: 'unknown', label: 'Choose fishing location', reason: `This season applies only within a geographic area. ${area.note}`} : state;
}

const SUMMARY_STATUS: Readonly<Record<string, string>> = {open: 'Open', restricted: 'Open · limits', closed: 'Closed', scheduled: 'Opener unconfirmed', excluded: 'Protected area', unknown: 'Check rules'};
/** dist/regulations.js `firstClause`: the rule's own first clause, cut, never rewritten. */
export function firstClause(text: unknown, max = 48): string | null {
  const t = String(text ?? '').trim();
  if (!t) return null;
  let clause = t.split(/;|\.(?:\s|$)|\s\((?=or\b)/)[0]!.trim().replace(/\bminimum\b/, 'min');
  if (clause.length > max) clause = clause.slice(0, max).replace(/\s+\S*$/, '') + '…';
  return /\bexcept\b|\bno more than\b|\bwith an allowance\b|\balternat/i.test(t.slice(clause.length)) ? `${clause} (exceptions below)` : clause;
}
/** dist/regulations.js `depthLimit`. */
export function depthLimit(profile: Data, today: string): string | null {
  const w = profile?.windows?.find((x: Data) => today >= x.start && today <= x.end);
  if (!w) return null;
  if (w.access === 'shoreward-50fm') return 'Inside 50-fm line';
  if (w.access === 'seaward-50fm') return 'Outside 50-fm line';
  if (w.access || w.restriction) return null;
  return /\ball depths\b/i.test(profile.season || '') ? 'All depths' : null;
}
/** dist/regulations.js `ruleSummary`: status, bag, size, depth, the verified date and one official link. */
export function ruleSummary(data: Data, species: string, state: RuleState, region: RulesRegion): RuleSummary {
  const tz = zoneOf(region), ids = species === 'reef' ? ['lingcod', 'rockfish'] : [species];
  const profiles = validRegulations(data, region) ? ids.map(id => ruleProfile(data, id, region)).filter(Boolean) : [];
  const status = SUMMARY_STATUS[state.status] ? state.status : 'unknown';
  const summary: RuleSummary = {status, label: SUMMARY_STATUS[status]!, bag: [], size: [], depth: null, verified: null, checked: null, link: CDFW_OCEAN, linkLabel: 'Official CDFW rules'};
  if (profiles.length !== ids.length) return summary;
  const named = profiles.length > 1;
  for (const p of profiles) {
    const bag = firstClause(p.bag), size = firstClause(p.size);
    if (bag) summary.bag.push(named ? `${p.name}: ${bag}` : bag);
    if (size) summary.size.push(named ? `${p.name}: ${size}` : size);
  }
  if (['open', 'restricted'].includes(status)) {
    const depths = [...new Set(profiles.map(p => depthLimit(p, state.today)))];
    summary.depth = depths.length === 1 ? depths[0]! : null;
  }
  const sourceIds = [...new Set(profiles.flatMap(p => p.source_ids as string[]))];
  const times = sourceIds.map(id => data.checks?.[id]?.data_retrieved_at).filter(s => Number.isFinite(Date.parse(s)));
  const oldest = times.length === sourceIds.length ? times.sort((a, b) => Date.parse(a) - Date.parse(b))[0] : null;
  const short = (s: unknown): string | null => Number.isFinite(Date.parse(String(s))) ? new Date(String(s)).toLocaleDateString('en-US', {timeZone: tz, month: 'short', day: 'numeric'}) : null;
  // SP-RULES-STATUS: "Verified" is a source-check statement for a known state only. An unknown state (outside the
  // reviewed rule period, a review time beyond the tolerance, a season that needs a fishing location) can have no
  // source issues, so the state itself gates the badge; its last parseable check still reads as `checked`.
  if (oldest && status !== 'unknown' && !state.issues?.length && data.rules_review_status === 'reviewed') summary.verified = short(oldest);
  else summary.checked = short(oldest);
  const primary = species === 'reef' ? 'rules-groundfish' : profiles[0].primary_source_id || profiles[0].source_ids[0];
  if (data.sources?.[primary]?.url) { summary.link = officialURL(data.sources[primary].url, region); summary.linkLabel = species === 'reef' ? 'Official groundfish rules' : 'Official rules'; }
  return summary;
}
/** dist/regulations.js `ruleSummaryHTML`'s verified wording. */
export const verifiedText = (s: RuleSummary): string => s.verified ? `Verified ${s.verified}` : s.checked ? `Needs recheck · last check ${s.checked}` : 'Not verified';

/** The region's reviewed registry, keyed by region so another region's never shows. */
export const regsData = signal<{region: string; data: Data} | null>(null);
let loading: string | null = null;
/**
 * v1's load: the region's committed registry, then the daily feed's regulation checks when they are
 * at least as recent; each must name the region's jurisdiction and pass the checks above. A failure
 * keeps what loaded; with nothing, the line reads "Check rules" with CDFW's page.
 */
export async function loadRegs(region: RulesRegion, fetchFn: typeof fetch = fetch): Promise<void> {
  if (loading === region.id) return;
  loading = region.id;
  const accept = (candidate: Data): boolean => {
    const current = regsData.peek(), mine = current?.region === region.id ? current.data : null;
    if (loading !== region.id || candidate?.jurisdiction_id !== region.jurisdiction_id || !validRegulations(candidate, region)) return false;
    if (mine && Date.parse(candidate.reviewed_at) < Date.parse(mine.reviewed_at)) return false;
    regsData.value = {region: region.id, data: candidate};
    return true;
  };
  const get = async (url: string): Promise<Data> => { const r = await fetchFn(url, {cache: 'no-cache'}); if (!r.ok) throw new Error(String(r.status)); return r.json(); };
  const asset = region.assets?.regulations;
  if (asset) await get(asset).then(accept, () => false);
  await get(dailyPartPath(region.id, 'regulations')).then(d => validDailyPart(d, 'regulations', region.id) && accept(d.regulations), () => false);
}
