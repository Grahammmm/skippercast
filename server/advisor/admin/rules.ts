// The admin Rules view and the CDFW change-watch (docs/plans/text-advisor/08-website.md
// § Admin, Rules; 02 § advisor_rules; OP-6; TA-A4). The rules table is the only
// source the advisor quotes a regulation from, so every row an admin creates or
// edits is a human review: it becomes 'active' with reviewed_at now and
// review_due = the sooner of 90 days and the season's end (the importer's rule,
// scripts/advisor/import-rules.mjs). Every change bumps the pages version (the
// species pages show the rules card).
//
//   listRules            ?jurisdiction= &status= (active | review | retired | due), with `due`
//                        per row (in review or past review_due) and the choices the editor needs
//   createRule           a new row, id as the importer makes it (jurisdiction|region|species|label
//                        for 'other'), refused when that row exists
//   editRule             content fields; reviewed_at, review_due, status 'active', updated_by
//   retireRule           status 'retired' (never quoted again; kept for the record)
//   watchRuleSources     the daily 'rules-watch' slot (cron.ts): each active region's daily feed
//                        `regulations.checks` (src/skippercast/pipeline/regulations.py); a check
//                        whose status is 'changed' (the page's normalised fingerprint differs from
//                        the reviewed one) puts that jurisdiction's active rows into review
//                        (answers/rules.ts markJurisdictionForReview) and opens one 'rule' review,
//                        reason rule_source_changed, per jurisdiction and set of changed pages
import central from '../../../jurisdictions/california-central.json' with {type: 'json'};
import mendocino from '../../../jurisdictions/california-mendocino.json' with {type: 'json'};
import northern from '../../../jurisdictions/california-northern.json' with {type: 'json'};
import sanFrancisco from '../../../jurisdictions/california-san-francisco.json' with {type: 'json'};
import southern from '../../../jurisdictions/california-southern.json' with {type: 'json'};
import catalog from '../../../catalog/species.json' with {type: 'json'};
import extra from '../../../catalog/advisor/species-extra.json' with {type: 'json'};
import {sha256} from '../ids.ts';
import {advisorLog} from '../log.ts';
import {reviewId} from '../contacts.ts';
import {localDate} from '../answers/time.ts';
import {isStale, markJurisdictionForReview} from '../answers/rules.ts';
import type {RuleRow} from '../answers/rules.ts';
import {dailyFeed, feedReader} from '../answers/feeds.ts';
import {regionConfig} from '../answers/regions.ts';
import {bumpPagesVersion} from '../intake/reports.ts';
import type {Env} from '../../env.ts';
import type {Region} from '../../types.ts';

export const REVIEW_DAYS = 90;                         // 02: reviewed_at + 90 days, or the season end if sooner
export const RULES_MAX = 1000;
export const CHANGE_PREFIX = 'advisor.rules.change.';  // job_state: one change-watch finding per review ref
export const LAST_WATCH_KEY = 'advisor.rules.last_watch';
export const WATCH_REASON = 'rule_source_changed';
const DAY = 86400000;

/** The rules jurisdictions (jurisdictions/*.json) and the hosts a rule's source may be on. */
export const JURISDICTIONS: ReadonlyMap<string, readonly string[]> = new Map(
  [central, mendocino, northern, sanFrancisco, southern].map(j => [j.id, j.authority_hosts] as const));
/** Species keys a rule may name: the catalog's, species-extra's (synonyms excluded) and 'other' (the label says which). */
export const SPECIES: ReadonlyMap<string, string> = new Map([
  ...catalog.species.map(s => [s.id, s.name] as const),
  ...(extra.species as {key: string; name: string; same_as_parent?: boolean}[]).filter(e => !e.same_as_parent).map(e => [e.key, e.name] as const),
  ['other', 'Other (named by the label)'] as const,
]);
export const RULE_STATUSES = ['active', 'review', 'retired'] as const;
export const LIST_STATUSES = [...RULE_STATUSES, 'due'] as const;

const TEXT: Readonly<Record<string, number>> = {species_label: 80, bag_notes: 500, area_notes: 500, gear_notes: 500, source_name: 120};
const NUMBER: Readonly<Record<string, {max: number; integer: boolean}>> = {
  size_min_in: {max: 120, integer: false}, size_max_in: {max: 120, integer: false}, bag_limit: {max: 100, integer: true}, depth_limit_ft: {max: 2000, integer: true},
};
const CONTENT = ['species_label', 'size_min_in', 'size_max_in', 'bag_limit', 'bag_notes', 'season_open', 'season_close', 'depth_limit_ft',
  'area_notes', 'gear_notes', 'source_name', 'source_url'] as const;
type Content = typeof CONTENT[number];
export type RuleFields = Partial<Record<Content, string | number | null>>;

const iso = (ms: number): string => new Date(ms).toISOString();
const SEASON = /^(?:(\d{4})-)?(\d{2})-(\d{2})$/;
/** A season date: MM-DD (every year) or YYYY-MM-DD, a real calendar day. */
export function validSeason(value: string): boolean {
  const m = SEASON.exec(value);
  if (!m) return false;
  const year = m[1] ? Number(m[1]) : 2024, month = Number(m[2]), day = Number(m[3]);   // 2024: a leap year, so 02-29 is a valid MM-DD
  const d = new Date(Date.UTC(year, month - 1, day));
  return d.getUTCMonth() === month - 1 && d.getUTCDate() === day;
}

/**
 * review_due for a row reviewed at `now` (Pacific dates): 90 days on, or the
 * season's close when that comes sooner and is not past. A MM-DD close is its
 * next occurrence.
 */
export function reviewDue(now: number, seasonClose: string | null): string {
  const today = localDate(now), due90 = localDate(now + REVIEW_DAYS * DAY);
  if (!seasonClose || !validSeason(seasonClose)) return due90;
  let end = seasonClose;
  if (seasonClose.length === 5) {
    end = `${today.slice(0, 4)}-${seasonClose}`;
    if (end < today) end = `${Number(today.slice(0, 4)) + 1}-${seasonClose}`;
  }
  return end >= today && end < due90 ? end : due90;
}

/** The content fields of a create or edit, validated; `null` clears an optional field. */
export function ruleFields(input: unknown, jurisdiction: string, {create = false} = {}): {fields: RuleFields} | {error: string} {
  if (!input || typeof input !== 'object' || Array.isArray(input)) return {error: 'fields must be an object'};
  const fields: RuleFields = {};
  for (const [key, raw] of Object.entries(input)) {
    if (!(CONTENT as readonly string[]).includes(key)) return {error: `unknown field ${key.slice(0, 40)}`};
    const empty = raw === null || raw === '' || (typeof raw === 'string' && !raw.trim());
    if (key in TEXT) {
      if (empty) { if (key === 'species_label' || key === 'source_name') return {error: `${key} is required`}; fields[key as Content] = null; continue; }
      if (typeof raw !== 'string') return {error: `${key} must be text`};
      const v = raw.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, '').trim();
      if (Array.from(v).length > TEXT[key]!) return {error: `${key} is at most ${TEXT[key]} characters`};
      fields[key as Content] = v;
    } else if (key in NUMBER) {
      if (empty) { fields[key as Content] = null; continue; }
      const n = typeof raw === 'number' ? raw : typeof raw === 'string' ? Number(raw) : NaN;
      const spec = NUMBER[key]!;
      if (!Number.isFinite(n) || n < 0 || n > spec.max || (spec.integer && !Number.isInteger(n))) return {error: `${key} must be ${spec.integer ? 'a whole number' : 'a number'} from 0 to ${spec.max}`};
      fields[key as Content] = n;
    } else if (key === 'season_open' || key === 'season_close') {
      if (empty) { fields[key] = null; continue; }
      if (typeof raw !== 'string' || !validSeason(raw.trim())) return {error: `${key} must be MM-DD or YYYY-MM-DD`};
      fields[key] = raw.trim();
    } else if (key === 'source_url') {
      if (empty || typeof raw !== 'string') return {error: 'source_url is required'};
      let url: URL;
      try { url = new URL(raw.trim()); } catch { return {error: 'source_url must be a link'}; }
      if (url.protocol !== 'https:' || url.username || url.password || raw.length > 300) return {error: 'source_url must be an https link'};
      if (!(JURISDICTIONS.get(jurisdiction) ?? []).includes(url.hostname)) return {error: "source_url must be on one of the jurisdiction's authority hosts"};
      fields.source_url = url.toString();
    }
  }
  if (create) for (const key of ['species_label', 'source_name', 'source_url'] as const) if (fields[key] == null) return {error: `${key} is required`};
  return {fields};
}

/** Both season ends or neither (02: both null = year-round). */
function seasonPair(open: unknown, close: unknown): string | null {
  return (open == null) === (close == null) ? null : 'season_open and season_close go together (both empty: year-round)';
}

export interface RuleView extends RuleRow {due: boolean}
export interface RulesList {
  rules: RuleView[]; today: string;
  jurisdictions: string[]; regions: {id: string; jurisdiction: string}[]; species: {key: string; name: string}[];
}

const activeRegions = (): Region[] => Object.values((typeof REGIONS === 'undefined' ? {} : REGIONS) as Record<string, Region>).filter(r => r.status === 'active');

/** Rules, by jurisdiction then species, with the editor's choices. */
export async function listRules(db: D1Database, query: {jurisdiction?: string | null; status?: string | null}, now: number = Date.now()): Promise<RulesList | {error: string}> {
  const today = localDate(now), where: string[] = [], args: unknown[] = [];
  if (query.jurisdiction) { if (!JURISDICTIONS.has(query.jurisdiction)) return {error: 'unknown jurisdiction'}; where.push('jurisdiction=?'); args.push(query.jurisdiction); }
  if (query.status) {
    if (!(LIST_STATUSES as readonly string[]).includes(query.status)) return {error: 'unknown status'};
    if (query.status === 'due') { where.push("status<>'retired' AND (status='review' OR review_due<?)"); args.push(today); }
    else { where.push('status=?'); args.push(query.status); }
  }
  const rows = (await db.prepare(`SELECT * FROM advisor_rules${where.length ? ` WHERE ${where.join(' AND ')}` : ''} ORDER BY jurisdiction, species_label, region, id LIMIT ?`)
    .bind(...args, RULES_MAX).all<RuleRow>()).results;
  return {
    rules: rows.map(r => ({...r, due: r.status !== 'retired' && isStale(r, today)})), today,
    jurisdictions: [...JURISDICTIONS.keys()],
    regions: Object.values((typeof REGIONS === 'undefined' ? {} : REGIONS) as Record<string, Region>).filter(r => r.jurisdiction_id).map(r => ({id: r.id, jurisdiction: r.jurisdiction_id!})),
    species: [...SPECIES].map(([key, name]) => ({key, name})),
  };
}

export type RuleOutcome = {status: 'ok'; rule: RuleView} | {status: 'not-found'} | {status: 'invalid'; error: string} | {status: 'conflict'; error: string};

/** The importer's id: sha256(jurisdiction|region|species_key|label for 'other')[:32]. */
export const ruleId = async (r: {jurisdiction: string; region: string; species_key: string; species_label: string}): Promise<string> =>
  (await sha256([r.jurisdiction, r.region, r.species_key, r.species_key === 'other' ? r.species_label : ''].join('|'))).slice(0, 32);

async function viewOf(db: D1Database, id: string, now: number): Promise<RuleView> {
  const row = (await db.prepare('SELECT * FROM advisor_rules WHERE id=?').bind(id).first<RuleRow>())!;
  return {...row, due: row.status !== 'retired' && isStale(row, localDate(now))};
}

/** A new rule, reviewed by the admin creating it: 'active' at once. */
export async function createRule(db: D1Database, input: Record<string, unknown>, by: string, now: number): Promise<RuleOutcome> {
  const jurisdiction = String(input.jurisdiction ?? ''), region = input.region == null || input.region === '' ? '*' : String(input.region), species = String(input.species_key ?? '');
  if (!JURISDICTIONS.has(jurisdiction)) return {status: 'invalid', error: 'unknown jurisdiction'};
  if (region !== '*' && regionConfig(region)?.jurisdiction_id !== jurisdiction) return {status: 'invalid', error: "region must be '*' or a region of that jurisdiction"};
  if (!SPECIES.has(species)) return {status: 'invalid', error: 'unknown species_key'};
  const {jurisdiction: _j, region: _r, species_key: _s, ...rest} = input;
  const parsed = ruleFields(rest, jurisdiction, {create: true});
  if ('error' in parsed) return {status: 'invalid', error: parsed.error};
  const f = parsed.fields;
  const pair = seasonPair(f.season_open ?? null, f.season_close ?? null);
  if (pair) return {status: 'invalid', error: pair};
  const id = await ruleId({jurisdiction, region, species_key: species, species_label: String(f.species_label)});
  if (await db.prepare('SELECT 1 AS x FROM advisor_rules WHERE id=?').bind(id).first()) return {status: 'conflict', error: 'that rule exists already: edit it'};
  const at = iso(now), row: Record<string, unknown> = {id, region, jurisdiction, species_key: species};
  for (const key of CONTENT) row[key] = f[key] ?? null;
  Object.assign(row, {reviewed_at: at, review_due: reviewDue(now, (f.season_close as string | null) ?? null), status: 'active', updated_by: by, updated_at: at});
  const columns = Object.keys(row);
  await db.prepare(`INSERT INTO advisor_rules(${columns.join(',')}) VALUES(${columns.map(() => '?').join(',')})`).bind(...columns.map(c => row[c])).run();
  await bumpPagesVersion(db, now);
  advisorLog('info', 'advisor_rule_created', {jurisdiction, species: species});
  return {status: 'ok', rule: await viewOf(db, id, now)};
}

/** An edit (an empty one confirms the row as it is): reviewed now, due again, active, by this admin. */
export async function editRule(db: D1Database, id: string, input: Record<string, unknown>, by: string, now: number): Promise<RuleOutcome> {
  if (!/^[0-9a-f]{32}$/.test(id)) return {status: 'not-found'};
  const row = await db.prepare('SELECT * FROM advisor_rules WHERE id=?').bind(id).first<RuleRow>();
  if (!row) return {status: 'not-found'};
  for (const key of ['jurisdiction', 'region', 'species_key', 'status', 'reviewed_at', 'review_due', 'id'])
    if (key in input) return {status: 'invalid', error: `${key} cannot be edited (retire the rule and create another)`};
  const parsed = ruleFields(input, row.jurisdiction);
  if ('error' in parsed) return {status: 'invalid', error: parsed.error};
  const f = parsed.fields;
  const open = 'season_open' in f ? f.season_open : row.season_open, close = 'season_close' in f ? f.season_close : row.season_close;
  const pair = seasonPair(open, close);
  if (pair) return {status: 'invalid', error: pair};
  const at = iso(now), sets = Object.entries(f);
  await db.prepare(`UPDATE advisor_rules SET ${[...sets.map(([k]) => `${k}=?`), 'reviewed_at=?', 'review_due=?', "status='active'", 'updated_by=?', 'updated_at=?'].join(',')} WHERE id=?`)
    .bind(...sets.map(([, v]) => v), at, reviewDue(now, (close as string | null) ?? null), by, at, id).run();
  await bumpPagesVersion(db, now);
  advisorLog('info', 'advisor_rule_reviewed', {jurisdiction: row.jurisdiction, fields: sets.length});
  return {status: 'ok', rule: await viewOf(db, id, now)};
}

/** Retire a rule: never quoted again (lookupRules skips 'retired'), kept for the record. */
export async function retireRule(db: D1Database, id: string, by: string, now: number): Promise<RuleOutcome> {
  if (!/^[0-9a-f]{32}$/.test(id)) return {status: 'not-found'};
  if (!await db.prepare('SELECT 1 AS x FROM advisor_rules WHERE id=?').bind(id).first()) return {status: 'not-found'};
  const r = await db.prepare("UPDATE advisor_rules SET status='retired',updated_by=?,updated_at=? WHERE id=? AND status<>'retired'").bind(by, iso(now), id).run();
  if (r.meta.changes) { await bumpPagesVersion(db, now); advisorLog('info', 'advisor_rule_retired', {count: 1}); }
  return {status: 'ok', rule: await viewOf(db, id, now)};
}

// ---- the change-watch (OP-6) -------------------------------------------------------------

export interface ChangedSource {id: string; name: string | null; url: string | null; content_sha256: string | null; approved_sha256: string | null}
export interface RuleChange {jurisdiction: string; regions: string[]; checked_at: string | null; sources: ChangedSource[]; marked_at: string | null; rows_marked: number}

const HEX64 = /^[0-9a-f]{64}$/;
const SOURCE_ID = /^[\w.-]{1,64}$/;
/** A changed page's link, only when it is https on one of the jurisdiction's authority hosts. */
function pageUrl(value: unknown, jurisdiction: string): string | null {
  try {
    const url = new URL(String(value ?? ''));
    return url.protocol === 'https:' && (JURISDICTIONS.get(jurisdiction) ?? []).includes(url.hostname) ? url.toString() : null;
  } catch { return null; }
}

/** The 'changed' checks of one daily feed's regulations part (regulations.py regulatory_snapshot), or [] when it has none. */
export function changedSources(regulations: unknown, jurisdiction: string): ChangedSource[] {
  const regs = regulations as {jurisdiction_id?: unknown; checks?: Record<string, {status?: unknown; url?: unknown; content_sha256?: unknown}>;
    sources?: Record<string, {name?: unknown; approved_content_sha256?: unknown}>} | null;
  if (!regs || typeof regs !== 'object' || !regs.checks || typeof regs.checks !== 'object') return [];
  if (regs.jurisdiction_id !== undefined && regs.jurisdiction_id !== jurisdiction) return [];
  const out: ChangedSource[] = [];
  for (const [id, check] of Object.entries(regs.checks)) {
    if (!SOURCE_ID.test(id) || check?.status !== 'changed') continue;
    const source = regs.sources?.[id];
    out.push({id, name: typeof source?.name === 'string' ? source.name.slice(0, 120) : null, url: pageUrl(check.url, jurisdiction),
      content_sha256: HEX64.test(String(check.content_sha256)) ? String(check.content_sha256) : null,
      approved_sha256: HEX64.test(String(source?.approved_content_sha256)) ? String(source!.approved_content_sha256) : null});
  }
  return out.sort((a, b) => a.id.localeCompare(b.id));
}

/** The review ref for a set of changed pages: "<jurisdiction>:<16 hex of their ids and fingerprints>". */
export async function changeRef(jurisdiction: string, sources: ChangedSource[]): Promise<string> {
  return `${jurisdiction}:${(await sha256(sources.map(s => `${s.id}=${s.content_sha256 ?? ''}`).join('\n'))).slice(0, 16)}`;
}
export const CHANGE_REF = /^([a-z][a-z-]{1,60}):([0-9a-f]{16})$/;

/** The stored finding behind a change-watch review, or null. */
export async function ruleChange(db: D1Database, ref: string): Promise<RuleChange | null> {
  if (!CHANGE_REF.test(ref)) return null;
  const raw = (await db.prepare('SELECT value FROM job_state WHERE key=?').bind(CHANGE_PREFIX + ref).first<{value: string}>())?.value;
  try { return raw ? JSON.parse(raw) as RuleChange : null; } catch { return null; }
}

const putState = (db: D1Database, key: string, value: unknown, at: string): Promise<unknown> =>
  db.prepare('INSERT INTO job_state(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at').bind(key, JSON.stringify(value), at).run();

export interface WatchResult {regions: number; unread: number; changed: number; opened: number; rows_marked: number}

/**
 * The 'rules-watch' slot. For each active region, the daily feed's
 * regulations checks; a jurisdiction with 'changed' pages gets, once per set of
 * changed pages: its active rows put into review (the advisor then says
 * "double-check" and the species pages "under review"), the pages version
 * bumped, and an open 'rule' review whose ref names the finding stored in
 * job_state. A finding already handled is not marked again, so an admin's
 * re-confirmation stands until the pages change again. Each step is
 * idempotent, so a failed run is finished by the next tick.
 */
export async function watchRuleSources(env: Env, now: number, deps: {feeds?: (url: string) => Promise<unknown>} = {}): Promise<WatchResult> {
  const db = env.DB!, read = feedReader(deps), at = iso(now);
  const found = new Map<string, {regions: string[]; checked_at: string | null; sources: Map<string, ChangedSource>}>();
  const regions = activeRegions();
  let unread = 0;
  for (const region of regions) {
    const jurisdiction = region.jurisdiction_id;
    if (!jurisdiction || !JURISDICTIONS.has(jurisdiction)) continue;
    const feed = await dailyFeed(region, read);
    if (!feed) { unread++; continue; }
    const changed = changedSources(feed.regulations, jurisdiction);
    if (!changed.length) continue;
    const entry = found.get(jurisdiction) ?? {regions: [] as string[], checked_at: null as string | null, sources: new Map<string, ChangedSource>()};
    entry.regions.push(region.id);
    entry.checked_at ??= typeof feed.regulations?.checked_at === 'string' ? feed.regulations.checked_at : null;
    for (const s of changed) entry.sources.set(s.id, s);
    found.set(jurisdiction, entry);
  }
  let opened = 0, marked = 0;
  for (const [jurisdiction, entry] of found) {
    const sources = [...entry.sources.values()].sort((a, b) => a.id.localeCompare(b.id));
    const ref = await changeRef(jurisdiction, sources);
    let change = await ruleChange(db, ref);
    if (!change) { change = {jurisdiction, regions: entry.regions.sort(), checked_at: entry.checked_at, sources, marked_at: null, rows_marked: 0}; await putState(db, CHANGE_PREFIX + ref, change, at); }
    if (!change.marked_at) {
      const rows = await markJurisdictionForReview(db, jurisdiction, now);
      if (rows) await bumpPagesVersion(db, now);
      change = {...change, marked_at: at, rows_marked: rows};
      await putState(db, CHANGE_PREFIX + ref, change, at);
      marked += rows;
    }
    const r = await db.prepare("INSERT INTO advisor_reviews(id,kind,ref_id,reason,status,opened_at) VALUES(?,'rule',?,?,'open',?) ON CONFLICT(id) DO NOTHING")
      .bind(await reviewId('rule', ref, WATCH_REASON), ref, WATCH_REASON, at).run();
    if (r.meta.changes) { opened++; advisorLog('info', 'advisor_rule_source_changed', {jurisdiction, pages: sources.length, rows: change.rows_marked}); }
  }
  const result: WatchResult = {regions: regions.length, unread, changed: found.size, opened, rows_marked: marked};
  await putState(db, LAST_WATCH_KEY, {checked_at: at, ...result}, at);
  return result;
}
