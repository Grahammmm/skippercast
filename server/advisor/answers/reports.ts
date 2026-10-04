// "What's biting out of Morro Bay" (docs/plans/text-advisor/06-angler-answers.md
// § "What's biting", FR-1, FR-4, FC-6): one cached answer per port per day in
// English and Spanish (advisor_daily_answers), regenerated when its inputs
// change.
//
//   portForQuestion(text, contact)    a port named in the text (aliases), the home port, the region default
//   dailyInputs(env, port, date)      published skipper reports (3 days), the landing reports and their
//                                     ladder label, today's conditions, the active rules with stale flags
//   currentInputsHash(env, port, date) sha256 over those inputs
//   dailyAnswer(env, port, date, ...) the stored row when its hash matches, else one model call
//                                     (prompts/daily.ts, forced tool {en, es}) and the row written
//
// Fallbacks need no model call: with nothing at all (no skipper report, no
// landing report) the answer is "No reports from the last three days for
// {port} yet." plus the conditions (the FR-3 follow offer is Next); a model
// that fails, answers out of shape, says a percentage or a rule number, gets
// the deterministic composition of the same facts instead. Every text is
// capped at 480 characters with its link. Never a probability. A feed that
// fails to load never replaces today's stored answer.
import ports from '../../../catalog/home-ports.json' with {type: 'json'};
import {portName, portRegion, resolveLinks} from '../links.ts';
import {resolvePort, landingNames, exactPort, fold} from './resolve.ts';
import {regionConfig} from './regions.ts';
import {dailyFeed, intelligenceFeed, feedReader} from './feeds.ts';
import type {FeedReader} from './feeds.ts';
import {reportEvidence, targetSpecies} from './confidence.ts';
import type {Confidence, LandingReport} from './confidence.ts';
import {advisoriesFrom, regionZones, windowConditions, windowEpochs, WINDOW} from './conditions.ts';
import type {DayConditions} from './conditions.ts';
import {lookupRules} from './rules.ts';
import {addDays, daysBetween, localDate} from './time.ts';
import {sha256} from '../ids.ts';
import {t} from '../strings.ts';
import {capReply, statesRuleNumber, stripMarkdown} from '../reply.ts';
import {DAILY_TOOL, dailyPrompt} from '../prompts/daily.ts';
import {advisorSettings} from '../settings.ts';
import {advisorLog} from '../log.ts';
import {recordLlm} from '../../analytics.ts';
import type {LlmUsage} from '../../analytics.ts';
import type {Env} from '../../env.ts';
import type {Action, AdvisorContactRow, AdvisorSettings, EngineResult, Language} from '../types.ts';
import type {Flow, FlowContext} from '../engine.ts';

export const DAILY_DAYS = 3;                 // 06: skipper reports from the last three days
export const DAILY_MAX = 480;                // 02 § advisor_daily_answers: <= 480 chars each
export const DAILY_MAX_TOKENS = 700;
export const DAILY_TIMEOUT_MS = 30_000;
export const API = 'https://api.anthropic.com/v1/messages';
const FORECAST_POINT = new Map(ports.ports.map(p => [p.id, p.forecast_point] as const));

/** 06 portForQuestion: the port named in the text, else the contact's home port, else the region default's first port. */
export function portForQuestion(text: string | null | undefined, contact: Pick<AdvisorContactRow, 'home_port'> | null, settings: Pick<AdvisorSettings, 'regionDefault'> = {regionDefault: 'morro-bay'}): {port: string; from: 'text' | 'home_port' | 'default'} | null {
  return resolvePort(text, contact, settings);
}

// ---- inputs --------------------------------------------------------------------------------

export interface DailySkipperReport {id: string; version: number; date: string; boat: string; verified: boolean; trip_type: string | null; anglers: number | null;
  counts: {label: string; species_key: string; kept: number | null; released: number | null}[]}
export interface DailyLanding {target: string; species: string[]; confidence: Confidence; trips: number; boats: number; days: number}
export interface DailyRule {species_key: string; open: boolean | null; stale: boolean}
export interface DailyInputs {
  port: string; port_name: string; region: string; date: string;
  /** Whether each regional feed loaded: a failed read must not replace a good stored answer with a poorer one (dailyAnswer). */
  feeds: {daily: boolean; intelligence: boolean};
  skipper_reports: DailySkipperReport[];
  landing: {available: boolean; reports: {id: string; date: string; boat: string; catches: {label: string; count: number}[]}[]; activity: DailyLanding[]};
  conditions: {available: boolean; advisories: string[]; day: Pick<DayConditions, 'wind_kt' | 'wind_from' | 'seas_ft' | 'sea_period_s' | 'comfort'> | null};
  rules: DailyRule[];
}

interface ReportRow {id: string; version: number; report_date: string; trip_type: string | null; anglers: number | null; counts_json: string; verified: number; boat_name: string}
function counts(json: string): DailySkipperReport['counts'] {
  try {
    const v = JSON.parse(json);
    return Array.isArray(v) ? v.filter(c => c && typeof c.label === 'string').slice(0, 10).map(c => ({label: String(c.label).slice(0, 40), species_key: typeof c.species_key === 'string' ? c.species_key : 'other',
      kept: Number.isFinite(c.kept) ? c.kept : null, released: Number.isFinite(c.released) ? c.released : null})) : [];
  } catch { return []; }
}

/** Is a season open on `date`? null when the row has no window (year-round unless bag 0). MM-DD or ISO bounds. */
export function seasonOpen(rule: {season_open: string | null; season_close: string | null; bag_limit: number | null}, date: string): boolean | null {
  if (rule.bag_limit === 0 && !rule.season_open) return false;
  if (!rule.season_open || !rule.season_close) return null;
  const md = (s: string) => s.length === 10 ? s : `${date.slice(0, 4)}-${s}`;
  const open = md(rule.season_open), close = md(rule.season_close);
  return open <= close ? date >= open && date <= close : date >= open || date <= close;
}

export interface DailyDeps {feeds?: (url: string) => Promise<unknown>; fetcher?: (url: string, init: RequestInit) => Promise<Response>; clock?: () => number}

/**
 * Everything the day's answer depends on, in a stable order (the hash is
 * taken over this object): the port's published skipper reports dated within
 * the last three days (ids and versions, so an edit or a publish changes it;
 * an unverified boat is "a boat"), the landing reports the daily feed holds for
 * the port with the ladder label per region target, today's advisories and
 * window conditions, and the region's rules for its targets with their stale
 * flags and whether the season is open today.
 */
export async function dailyInputs(env: Env, port: string, date: string, deps: DailyDeps = {}, now: number = Date.now()): Promise<DailyInputs> {
  const regionId = portRegion(port)!, region = regionConfig(regionId);
  const db = env.DB!;
  const rows = (await db.prepare(`SELECT r.id,r.version,r.report_date,r.trip_type,r.anglers,r.counts_json,r.verified,b.name AS boat_name
      FROM advisor_reports r JOIN advisor_boats b ON b.id=r.boat_id WHERE r.port=? AND r.status='published' AND r.report_date>=? AND r.report_date<=?
      ORDER BY r.report_date DESC, r.id LIMIT 8`).bind(port, addDays(date, -DAILY_DAYS), date).all<ReportRow>()).results;
  const skipper = rows.map(r => ({id: r.id, version: r.version, date: r.report_date, boat: r.verified ? r.boat_name : 'a boat', verified: Boolean(r.verified),
    trip_type: r.trip_type, anglers: r.anglers, counts: counts(r.counts_json)}));

  const read: FeedReader = feedReader(deps);
  const [daily, intel] = region ? await Promise.all([dailyFeed(region, read), intelligenceFeed(region, read)]) : [null, null];
  let landing: DailyInputs['landing'] = {available: false, reports: [], activity: []};
  if (daily && region) {
    const names = new Set(landingNames(port).map(n => n.toLowerCase()));
    const portFeed = {...daily, reports: (daily.reports as LandingReport[]).filter(r => names.has(String(r.port ?? '').toLowerCase()))};
    const targets = [...new Set(region.species.filter(s => s !== 'dungeness'))];
    const ev = targets.map(target => ({target, ...reportEvidence(portFeed, target, now, null, region.timezone)}));
    const seen = new Map<string, LandingReport>();
    for (const e of ev) for (const r of e.reports) if (r.id && !seen.has(r.id)) seen.set(r.id, r);
    landing = {available: true,
      reports: [...seen.values()].sort((a, b) => String(b.date).localeCompare(String(a.date)) || String(a.id).localeCompare(String(b.id))).slice(0, 6)
        .map(r => ({id: String(r.id), date: String(r.date), boat: String(r.boat ?? ''), catches: (r.catches ?? []).filter(c => (c.count ?? 0) > 0).slice(0, 6)
          .map(c => ({label: String((c as {label?: string}).label ?? c.species ?? ''), count: c.count ?? 0}))})),
      activity: ev.filter(e => e.reports.length).map(e => ({target: e.target, species: targetSpecies(e.target), confidence: e.confidence, trips: e.reports.length, boats: e.boats, days: e.days}))};
  }

  let conditions: DailyInputs['conditions'] = {available: false, advisories: [], day: null};
  if (region) {
    const [from, to] = windowEpochs(date, region.timezone, WINDOW);
    const advisories = daily ? advisoriesFrom(daily, regionZones(region), from, to).map(a => a.event) : [];
    const day = intel ? windowConditions(intel, region, FORECAST_POINT.get(port) ?? region.forecast_points[0]?.id ?? '', date, WINDOW) : null;
    conditions = {available: Boolean(day?.available), advisories: [...new Set(advisories)],
      day: day?.available ? {wind_kt: day.wind_kt, wind_from: day.wind_from, seas_ft: day.seas_ft, sea_period_s: day.sea_period_s, comfort: day.comfort} : null};
  }

  const rules: DailyRule[] = [];
  for (const key of region ? [...new Set(region.species.filter(s => s !== 'dungeness').flatMap(targetSpecies))] : []) {
    const row = (await lookupRules(db, {region: regionId, speciesKey: key, now})).find(r => r.applies_as === 'species') ?? null;
    if (row) rules.push({species_key: key, open: seasonOpen(row, date), stale: row.stale});
  }
  return {port, port_name: portName(port) ?? port, region: regionId, date, feeds: {daily: Boolean(daily), intelligence: Boolean(intel)}, skipper_reports: skipper, landing, conditions, rules};
}

/** sha256 over the inputs (02 § advisor_daily_answers: report ids, conditions snapshot and rules used). */
export const hashInputs = async (inputs: DailyInputs): Promise<string> => sha256(JSON.stringify(inputs));
/** 06: the current inputs hash for a port and date. */
export async function currentInputsHash(env: Env, port: string, date: string, deps: DailyDeps = {}, now: number = Date.now()): Promise<string> {
  return hashInputs(await dailyInputs(env, port, date, deps, now));
}

// ---- the deterministic composition (fallbacks) -----------------------------------------------

const range = (r: [number, number] | null): string | null => r ? (r[0] === r[1] ? String(r[0]) : `${r[0]}-${r[1]}`) : null;
const dateWords = (date: string, language: Language): string => {
  const d = new Date(`${date}T12:00:00Z`);
  const wd = new Intl.DateTimeFormat(language === 'es' ? 'es' : 'en-US', {weekday: 'short', timeZone: 'UTC'}).format(d).replace(/\.$/, '');
  const mo = new Intl.DateTimeFormat(language === 'es' ? 'es' : 'en-US', {month: 'short', timeZone: 'UTC'}).format(d).replace(/\.$/, '');
  return language === 'es' ? `${wd} ${d.getUTCDate()} ${mo}` : `${wd} ${mo} ${d.getUTCDate()}`;
};
const dayWord = (date: string, today: string, language: Language): string => {
  const ago = daysBetween(date, today);
  if (ago === 0) return language === 'es' ? 'hoy' : 'today';
  if (ago === 1) return language === 'es' ? 'ayer' : 'yesterday';
  const wd = new Intl.DateTimeFormat(language === 'es' ? 'es' : 'en-US', {weekday: 'short', timeZone: 'UTC'}).format(new Date(`${date}T12:00:00Z`)).replace(/\.$/, '');
  return language === 'es' ? `el ${wd}` : wd;   // "reportó ayer", "reportó el sáb"
};
const COMFORT_KEYS = {comfortable: 'comfort_comfortable', bumpy: 'comfort_bumpy', rough: 'comfort_rough'} as const;

/** "Conditions: seas 4-5 ft at 9 s, wind 5-10 kt from the NW, bumpy for a mid-size center console." (advisories first, in capitals on the word). */
export function conditionsText(c: DailyInputs['conditions'], language: Language): string {
  const out: string[] = c.advisories.map(event => t(language, 'daily_advisory', {event: event.toUpperCase()}));
  const d = c.day;
  if (!d) { out.push(t(language, 'daily_conditions_none')); return out.join(' '); }
  const parts: string[] = [];
  const seas = range(d.seas_ft), wind = range(d.wind_kt);
  if (seas) parts.push(d.sea_period_s ? t(language, 'daily_seas', {range: seas, period: d.sea_period_s}) : t(language, 'daily_seas_no_period', {range: seas}));
  if (wind) parts.push(d.wind_from ? t(language, 'daily_wind', {range: wind, from: d.wind_from}) : t(language, 'daily_wind_no_dir', {range: wind}));
  const key = COMFORT_KEYS[d.comfort as keyof typeof COMFORT_KEYS];
  if (key) parts.push(t(language, 'daily_comfort', {word: t(language, key)}));
  out.push(parts.length ? t(language, 'daily_conditions', {parts: parts.join(', ')}) : t(language, 'daily_conditions_none'));
  return out.join(' ');
}

const speciesWords = (a: DailyLanding, language: Language): string => a.target === 'reef' ? (language === 'es' ? 'rocote y lingcod' : 'rockfish and lingcod') : a.target;

/**
 * The answer composed from the facts without a model (06's fallbacks; also
 * what a failed generation stores). Advisories lead (AD-4). Nothing at all:
 * "No reports from the last three days for {port} yet." and the conditions,
 * no link (the FR-3 follow offer is Next). No skipper report but landing
 * reports: "No skipper reports from the last three days." then the landing's
 * trips with the ladder label, attributed to the landing.
 */
export function composeDaily(inputs: DailyInputs, language: Language): string {
  const advisories = inputs.conditions.advisories.map(event => t(language, 'daily_advisory', {event: event.toUpperCase()}));
  const conditions = conditionsText({...inputs.conditions, advisories: []}, language);
  const landing = inputs.landing.activity.filter(a => a.trips > 0);
  if (!inputs.skipper_reports.length && !landing.length) return [...advisories, t(language, 'daily_nothing', {port: inputs.port_name}), conditions].join(' ');
  const body: string[] = [];
  for (const r of inputs.skipper_reports.slice(0, 3)) {
    // Kept fish first; a trip that released everything still says what it caught.
    const kept = r.counts.filter(c => c.kept).slice(0, 4).map(c => `${c.kept} ${c.label}`);
    const list = (kept.length ? kept : r.counts.filter(c => c.released).slice(0, 3).map(c => t(language, 'daily_released', {n: c.released!, label: c.label}))).join(', ');
    if (list) body.push(t(language, 'daily_skipper', {boat: r.verified ? r.boat : t(language, 'daily_unverified_boat'), day: dayWord(r.date, inputs.date, language), counts: list}));
  }
  if (!inputs.skipper_reports.length) {
    body.push(t(language, 'daily_no_skipper'));
    for (const a of landing.slice(0, 2)) body.push(a.trips === 1 ? t(language, 'daily_landing_one', {species: speciesWords(a, language), label: a.confidence}) : t(language, 'daily_landing', {trips: a.trips, species: speciesWords(a, language), label: a.confidence}));
  }
  return [`${inputs.port_name}, ${dateWords(inputs.date, language)}:`, ...advisories, ...body, conditions,
    t(language, 'daily_link', {target: `port:${inputs.port}`})].join(' ');
}

// ---- generation ------------------------------------------------------------------------------

/**
 * A generated text that is safe to store: no markdown, no percentage, no odds
 * word, no rule number, no follow offer, ends with the link. `labels`: with no
 * skipper report the answer rests on the landing's reports, so it must carry
 * one of their ladder labels (06: "fall back to the landing-report confidence
 * label with its source named").
 */
export function acceptable(text: unknown, link: string, labels: readonly string[] = []): string | null {
  if (typeof text !== 'string') return null;
  let s = stripMarkdown(text).replace(/\s+/g, ' ').trim();
  if (labels.length && !labels.some(label => new RegExp(String.raw`\b${label}\b`).test(s))) return null;
  if (!s || /%|\bpercent|\bprobab|\bchance|\bodds\b|por ciento|probabilidad/i.test(s)) return null;
  // 06: in v1 the answer stops at the conditions; the follow offer (FR-3) is Next.
  if (/\btext you when\b|\blet you know when\b|\bwant me to\b|te (?:aviso|escribo|mando)|quieres que/i.test(s)) return null;
  if (s.split(/(?<=[.!?])\s+/).some(statesRuleNumber)) return null;
  if (!s.includes(link)) s = `${s} ${link}`;
  return s;
}

/** One model call (prompts/daily.ts, forced tool {en, es}). Null on any failure; the caller composes instead. */
async function generate(env: Env, settings: AdvisorSettings, inputs: DailyInputs, link: string, deps: DailyDeps): Promise<{en: string; es: string} | null> {
  if (!env.ANTHROPIC_API_KEY) return null;
  // The global LLM cap (04 § spend and caps) covers this call too: past it, the facts are composed instead.
  const day = Math.floor((deps.clock ?? Date.now)() / 86400000);
  const used = await env.DB!.prepare('INSERT INTO request_limits(id,count,expires_at) VALUES(?,1,?) ON CONFLICT(id) DO UPDATE SET count=count+1 RETURNING count')
    .bind(`global:advisor-llm:${day}`, (day + 2) * 86400).first<{count: number}>();
  if ((used?.count ?? Infinity) > settings.globalDailyLlm) { advisorLog('warn', 'advisor_global_cap', {limit: settings.globalDailyLlm, feature: 'daily'}); return null; }
  const fetcher = deps.fetcher ?? ((url: string, init: RequestInit) => fetch(url, init));
  const usage: LlmUsage = {model: settings.model, turns: 0, input_tokens: 0, output_tokens: 0, web_search_requests: 0};
  let outcome = 'error';
  try {
    const facts = {...inputs, conditions_sentence: {en: conditionsText(inputs.conditions, 'en'), es: conditionsText(inputs.conditions, 'es')},
      date_words: {en: dateWords(inputs.date, 'en'), es: dateWords(inputs.date, 'es')}};
    const body = JSON.stringify({model: settings.model, max_tokens: DAILY_MAX_TOKENS, temperature: 0, tools: [DAILY_TOOL], tool_choice: {type: 'tool', name: DAILY_TOOL.name},
      messages: [{role: 'user', content: dailyPrompt(facts, link)}]});
    const response = await fetcher(API, {method: 'POST', signal: AbortSignal.timeout(DAILY_TIMEOUT_MS),
      headers: {'x-api-key': env.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}, body});
    usage.turns = 1;
    if (!response.ok) throw Error(`daily answer HTTP ${response.status}`);
    const data = await response.json() as {content?: {type: string; name?: string; input?: {en?: unknown; es?: unknown}}[]; usage?: Record<string, number>};
    usage.input_tokens = (data.usage?.input_tokens ?? 0) + (data.usage?.cache_read_input_tokens ?? 0) + (data.usage?.cache_creation_input_tokens ?? 0);
    usage.output_tokens = data.usage?.output_tokens ?? 0;
    const block = (data.content ?? []).find(b => b.type === 'tool_use' && b.name === DAILY_TOOL.name);
    // No skipper report: the landing's label must be there (and the English must say there were no skipper reports).
    const labels = inputs.skipper_reports.length ? [] : [...new Set(inputs.landing.activity.filter(a => a.trips > 0).map(a => a.confidence))];
    const en = acceptable(block?.input?.en, link, labels), es = acceptable(block?.input?.es, link, labels);
    if (en && labels.length && !/\bno skipper reports?\b/i.test(en)) { outcome = 'invalid'; return null; }
    if (!en || !es) { outcome = 'invalid'; return null; }
    outcome = 'ok';
    return {en, es};
  } catch (error) {
    advisorLog('warn', 'advisor_daily_failed', {reason: String((error as Error)?.message).slice(0, 120)});
    return null;
  } finally {
    if (usage.turns) recordLlm(env, 'advisor:daily', outcome, usage);
  }
}

const capped = (text: string, base: string): string => { const r = resolveLinks(text, base); return capReply(r.text, r.links, DAILY_MAX); };

export interface DailyAnswer {port: string; date: string; text: string; text_en: string; text_es: string; inputs_hash: string; generated_at: string; source: 'cache' | 'model' | 'composed'}

/**
 * 06 dailyAnswer: the stored answer for `<port>:<date>` when its inputs_hash
 * is current; otherwise regenerated (one model call when there is something to
 * summarise, else the composed fallback) and both languages written with the
 * hash. Texts are stored with their link resolved, at most 480 characters.
 */
export interface DailyOptions {
  /**
   * false: never call the model; a missing or stale answer is composed from the
   * facts and returned without being stored (get_port_report, inside a model
   * turn, must not start a second model call; the pre-router or the slot
   * stores the generated one).
   */
  generate?: boolean;
}
export async function dailyAnswer(env: Env, port: string, date: string, language: Language, deps: DailyDeps = {}, options: DailyOptions = {}): Promise<DailyAnswer> {
  const settings = advisorSettings(env), db = env.DB!;
  const now = (deps.clock ?? Date.now)();
  const key = `${port}:${date}`;
  const inputs = await dailyInputs(env, port, date, deps, now);
  const hash = await hashInputs(inputs);
  const row = await db.prepare('SELECT text_en,text_es,inputs_hash,generated_at FROM advisor_daily_answers WHERE key=?').bind(key).first<{text_en: string; text_es: string; inputs_hash: string; generated_at: string}>();
  if (row && row.inputs_hash === hash) return {port, date, text: language === 'es' ? row.text_es : row.text_en, text_en: row.text_en, text_es: row.text_es, inputs_hash: hash, generated_at: row.generated_at, source: 'cache'};
  // A feed that failed to load changes the hash but is no new information: today's stored answer stands until the
  // feeds are back (a published report deletes the row, intake/reports.ts, so a new report is never hidden by this).
  if (row && (!inputs.feeds.daily || !inputs.feeds.intelligence)) return {port, date, text: language === 'es' ? row.text_es : row.text_en, text_en: row.text_en, text_es: row.text_es, inputs_hash: row.inputs_hash, generated_at: row.generated_at, source: 'cache'};

  const link = `{{link:port:${port}}}`;
  if (options.generate === false) {
    const en = capped(composeDaily(inputs, 'en'), settings.publicBase), es = capped(composeDaily(inputs, 'es'), settings.publicBase);
    return {port, date, text: language === 'es' ? es : en, text_en: en, text_es: es, inputs_hash: hash, generated_at: new Date(now).toISOString(), source: 'composed'};
  }
  const nothing = !inputs.skipper_reports.length && !inputs.landing.activity.some(a => a.trips > 0);
  const made = nothing ? null : await generate(env, settings, inputs, link, deps);
  const en = capped(made?.en ?? composeDaily(inputs, 'en'), settings.publicBase), es = capped(made?.es ?? composeDaily(inputs, 'es'), settings.publicBase);
  const at = new Date(now).toISOString();
  await db.prepare('INSERT INTO advisor_daily_answers(key,text_en,text_es,inputs_hash,generated_at) VALUES(?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET text_en=excluded.text_en,text_es=excluded.text_es,inputs_hash=excluded.inputs_hash,generated_at=excluded.generated_at')
    .bind(key, en, es, hash, at).run();
  advisorLog('info', 'advisor_daily_generated', {port, source: made ? 'model' : 'composed', reports: inputs.skipper_reports.length});
  return {port, date, text: language === 'es' ? es : en, text_en: en, text_es: es, inputs_hash: hash, generated_at: at, source: made ? 'model' : 'composed'};
}

/** The ports whose answers the 05:30 slot pre-generates: every catalog/home-ports.json port of a region with status 'active'. */
export function activePorts(): string[] {
  return ports.ports.filter(p => regionConfig(p.region)?.status === 'active').map(p => p.id);
}

// ---- the cron slot (01 § cron slots) --------------------------------------------------------

/** Pre-generate today's answer for every active port (the daily-answers slot, 05:30 local). Throws when any port failed, so the slot retries. */
export async function pregenerateDaily(env: Env, now: number, deps: DailyDeps = {}): Promise<{ports: number; failed: number}> {
  let failed = 0;
  const list = activePorts();
  for (const port of list) {
    const tz = regionConfig(portRegion(port))?.timezone ?? 'America/Los_Angeles';
    try { await dailyAnswer(env, port, localDate(now, tz), 'en', {...deps, clock: deps.clock ?? (() => now)}); }
    catch (error) { failed++; advisorLog('warn', 'advisor_daily_slot_port_failed', {port, reason: String((error as Error)?.message).slice(0, 120)}); }
  }
  if (failed) throw Error(`daily answers failed for ${failed} of ${list.length} ports`);
  return {ports: list.length, failed};
}

// ---- the pre-router (04 § spend and caps) ----------------------------------------------------

// The plain question, after fold() (lower case, accents and punctuation gone): what's biting /
// how's the fishing / qué está picando / cómo está la pesca, an optional port, an optional "today".
const WHEN = String.raw`(?: (?:today|now|right now|this morning|this week|lately|hoy|ahorita|ahora|esta semana))?`;
const PLAIN: [RegExp, Language][] = [
  [new RegExp(String.raw`^(?:(?:so|hey|hi|ok) )?(?:what s|whats|what is|what are they) (?:been )?biting${WHEN}(?: (?:out of|out|at|in|near|off|around|from) (.+?))?${WHEN}$`), 'en'],
  [new RegExp(String.raw`^(?:(?:so|hey|hi|ok) )?(?:how s|hows|how is) (?:the )?fishing${WHEN}(?: (?:out of|at|in|near|off|around|from) (.+?))?${WHEN}$`), 'en'],
  [new RegExp(String.raw`^(?:(?:hola|oye) )?que (?:esta|estan|anda|andan) picando${WHEN}(?: (?:en|de|por|cerca de|saliendo de) (.+?))?${WHEN}$`), 'es'],
  [new RegExp(String.raw`^(?:(?:hola|oye) )?como (?:esta|va|anda) la pesca${WHEN}(?: (?:en|de|por|cerca de|saliendo de) (.+?))?${WHEN}$`), 'es'],
];

/** The plain "what's biting" question: its language and the port it names (null: none named). Null when the text is anything more. */
export function plainDailyQuestion(text: string | null | undefined): {language: Language; port: string | null} | null {
  const folded = fold(text);
  for (const [re, language] of PLAIN) {
    const m = re.exec(folded);
    if (!m) continue;
    if (!m[1]) return {language, port: null};
    const port = exactPort(m[1]);
    return port ? {language, port} : null;
  }
  return null;
}

/** The one-time home-port question after a daily answer for a contact with no home port (FC-2: ask once). */
export const homePortOnceKey = (contactId: string): string => `homeport.${contactId}`;

/**
 * The pre-router (04 § spend and caps, 06): the plain "what's biting" question,
 * with or without a port name (a port of an active region), is answered from the day's cached answer with
 * no chat model call (a stale or missing answer costs the one generation call,
 * shared by everyone asking about that port today). A contact with no home
 * port is asked for it once, after the answer. Anything more than the plain
 * question goes to the model, whose get_port_report returns the same answer.
 */
export async function dailyFlow(f: FlowContext): Promise<EngineResult | null> {
  const plain = f.text && !f.media.length ? plainDailyQuestion(f.text) : null;
  if (!plain) return null;
  const resolved = plain.port ? {port: plain.port, from: 'text' as const} : portForQuestion(null, f.contact, f.settings);
  const region = resolved ? regionConfig(portRegion(resolved.port)) : null;
  // Only the ports the 05:30 slot keeps (active regions); a preview region's port goes to the model and get_port_report.
  if (!resolved || !region || region.status !== 'active') return null;
  const answer = await dailyAnswer(f.env, resolved.port, localDate(f.now, region.timezone), f.language, {...f.deps, clock: f.deps.clock ?? (() => f.now)});
  const actions: Action[] = [{type: 'send_text', text: answer.text}];
  if (!f.contact.home_port && f.contact.role === 'angler') {
    const key = homePortOnceKey(f.contact.id);
    const asked = await f.db.prepare('SELECT 1 AS x FROM job_state WHERE key=?').bind(`advisor.once.${key}`).first();
    if (!asked) actions.push({type: 'send_text', text: t(f.language, 'ask_home_port')}, {type: 'mark_once', key});
  }
  return {actions, intent: `reports.daily.${answer.source}`};
}

/** The flow engine.ts registers in STAGE_TWO_FLOWS, after TA-I3's. */
export const DAILY_FLOWS: readonly Flow[] = [{name: 'daily', run: dailyFlow}];

/** The day's stored answer for a port, if one exists (the situation brief; no regeneration). */
export async function storedDaily(db: D1Database, port: string, now: number): Promise<{text_en: string; text_es: string} | null> {
  const tz = regionConfig(portRegion(port))?.timezone ?? 'America/Los_Angeles';
  return db.prepare('SELECT text_en,text_es FROM advisor_daily_answers WHERE key=?').bind(`${port}:${localDate(now, tz)}`).first<{text_en: string; text_es: string}>();
}
