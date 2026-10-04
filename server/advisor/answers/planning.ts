// "Is Saturday worth going for rockfish" (docs/plans/text-advisor/06-angler-answers.md
// § planning, FR-2, AD-4, principle 6): the planning brief. get_conditions
// returns it as its `planning` field when the model passes a species (the
// smaller change than a new plan_trip tool: one tool, one call, one intent).
//
//   tripConditions(input, opts)       get_conditions' data: the dates in the person's words (en/es weekdays,
//                                     mañana, "this weekend" → two days, more than 7 days → beyond_horizon),
//                                     the window's wind, gusts, seas, swell and comfort word, the NWS
//                                     advisories per day and `advisory_line`, already written in the reply
//                                     language ("SMALL CRAFT ADVISORY posted for Sat.")
//   planningBrief(env, args, opts)    those, plus the season status from the rules table (lookupRules: a
//                                     closed season comes first, a stale row says "double-check", never a
//                                     number), the port's recent activity from the daily answer's inputs
//                                     (dailyInputs), exactly one confidence phrase from the ladder ("recent
//                                     reported activity: Moderate|Low|Insufficient"), and the NWS closer
//
// The ladder is the landing's (answers/confidence.ts, the same rule as
// dist/bite-evidence.js) for the species asked about; a published skipper
// report of that species in the last three days lifts Insufficient to Low
// (positive reports exist, coverage weaker: docs/bite-evidence.md's Low),
// never to Moderate. No probability, no catch number, no clearance.
import ports from '../../../catalog/home-ports.json' with {type: 'json'};
import {portName, portRegion} from '../links.ts';
import {landingNames, resolvePort, resolveSpecies} from './resolve.ts';
import {regionConfig} from './regions.ts';
import {dailyFeed, intelligenceFeed, feedReader} from './feeds.ts';
import type {FeedReader} from './feeds.ts';
import {advisoriesFrom, parseTripDate, regionZones, windowConditions, windowEpochs, WINDOW, HORIZON_DAYS} from './conditions.ts';
import type {Advisory, DayConditions, Window} from './conditions.ts';
import {reportEvidence, CONFIDENCE_WORDS} from './confidence.ts';
import type {Confidence, LandingReport} from './confidence.ts';
import {lookupRules} from './rules.ts';
import {dailyInputs, seasonOpen} from './reports.ts';
import {pickRule, speciesLabel} from './fishid.ts';
import {daysBetween, localDate} from './time.ts';
import {canonicalSpecies, reportSpeciesKey} from '../vision/species.ts';
import {t} from '../strings.ts';
import {TOOL_RESULT_MAX} from '../tools/tool.ts';
import type {Env} from '../../env.ts';
import type {AdvisorContactRow, AdvisorSettings, Language} from '../types.ts';

const FORECAST_POINT = new Map(ports.ports.map(p => [p.id, p.forecast_point] as const));
const hourOf = (v: unknown): number | null => Number.isInteger(v) && (v as number) >= 0 && (v as number) <= 23 ? v as number : null;

export interface PlanningOptions {
  now: number; language: Language;
  deps?: {feeds?: (url: string) => Promise<unknown>} | null;
  contact?: Pick<AdvisorContactRow, 'home_port'> | null;
  settings?: Pick<AdvisorSettings, 'regionDefault'>;
}

/** A feed reader that reads each URL once per brief (the conditions, the daily inputs and the ladder share the daily feed). */
function once(read: FeedReader): FeedReader {
  const seen = new Map<string, ReturnType<FeedReader>>();
  return url => { let p = seen.get(url); if (!p) { p = read(url); seen.set(url, p); } return p; };
}

/** "today", "tomorrow", "Sat" / "hoy", "mañana", "el sábado": how a reply names a trip date. */
export function dayWord(date: string, today: string, language: Language): string {
  const ahead = daysBetween(today, date);
  if (ahead === 0) return t(language, 'day_today');
  if (ahead === 1) return t(language, 'day_tomorrow');
  const d = new Date(`${date}T12:00:00Z`);
  return language === 'es' ? `el ${new Intl.DateTimeFormat('es', {weekday: 'long', timeZone: 'UTC'}).format(d)}`
    : new Intl.DateTimeFormat('en-US', {weekday: 'short', timeZone: 'UTC'}).format(d);
}
const joinAnd = (items: string[], language: Language): string => items.length < 2 ? items.join('') : t(language, 'words_and', {a: items.slice(0, -1).join(', '), b: items.at(-1)!});

/**
 * The advisory sentence a planning reply starts with (AD-4): each event in
 * capitals with the days it overlaps the fishing window, gale first.
 * "SMALL CRAFT ADVISORY posted for Sat and Sun." Null when there is none.
 */
export function advisoryLine(byDay: {date: string; advisories: Advisory[]}[], today: string, language: Language): string | null {
  const events: {event: string; dates: string[]}[] = [];
  for (const day of byDay) for (const a of day.advisories) {
    const e = events.find(x => x.event === a.event);
    if (e) { if (!e.dates.includes(day.date)) e.dates.push(day.date); } else events.push({event: a.event, dates: [day.date]});
  }
  if (!events.length) return null;
  return events.map(e => t(language, 'planning_advisory', {event: e.event.toUpperCase(), days: joinAnd(e.dates.map(d => dayWord(d, today, language)), language)})).join(' ');
}

/** True when the reply's first sentence names one of the advisory events in capitals (the backstop's check, engine.ts). */
export function leadsWithAdvisory(reply: string, events: readonly string[]): boolean {
  const first = String(reply ?? '').trim().split(/(?<=[.!?])\s+/)[0] ?? '';
  return events.some(e => first.includes(e.toUpperCase()));
}

export interface ConditionsInput {port: string; date?: string | null; start_hour?: unknown; end_hour?: unknown}

/** get_conditions' result (04 § Tools, 06 § planning steps 1-3). Advisories before the numbers. */
export async function tripConditions(input: ConditionsInput, opts: PlanningOptions & {read?: FeedReader}): Promise<Record<string, unknown>> {
  const resolved = resolvePort(String(input.port ?? ''), opts.contact ?? null, opts.settings);
  const region = resolved ? regionConfig(portRegion(resolved.port)) : null;
  if (!resolved || !region) return {error: 'unknown port'};
  const port = resolved.port, tz = region.timezone, language = opts.language, today = localDate(opts.now, tz);
  const start = hourOf(input.start_hour) ?? WINDOW.start, end = hourOf(input.end_hour) ?? WINDOW.end;
  const window: Window = start < end ? {start, end} : WINDOW;
  const when = parseTripDate(typeof input.date === 'string' ? input.date : '', opts.now, tz);
  const head = {port, port_name: portName(port), asked: input.date ?? null, dates: when.dates, date_understood: when.parsed};
  if (when.past) return {...head, error: 'that date has passed'};
  if (when.beyond_horizon) return {...head, beyond_horizon: true,
    horizon_line: t(language, 'planning_beyond_horizon', {days: HORIZON_DAYS, day: dayWord(when.dates[0]!, today, language)}),
    note: 'The forecast only reaches 7 days. Say so (horizon_line) and offer to check closer to the day.'};

  const read = opts.read ?? once(feedReader(opts.deps));
  const [intel, daily] = await Promise.all([intelligenceFeed(region, read), dailyFeed(region, read)]);
  const pointId = FORECAST_POINT.get(port) ?? region.forecast_points[0]?.id ?? '';
  const days: DayConditions[] = when.dates.map(date => windowConditions(intel, region, pointId, date, window));
  const zones = regionZones(region);
  const byDay = when.dates.map(date => { const [from, to] = windowEpochs(date, tz, window); return {date, advisories: daily ? advisoriesFrom(daily, zones, from, to) : []}; });
  const [from] = windowEpochs(when.dates[0]!, tz, window), [, to] = windowEpochs(when.dates.at(-1)!, tz, window);
  const alerts = daily ? advisoriesFrom(daily, zones, from, to) : null;
  const line = alerts?.length ? advisoryLine(byDay, today, language) : null;
  return {
    ...head, beyond_horizon: false,
    advisories: alerts ?? [],
    advisories_checked: alerts !== null,
    advisories_as_of: daily?.sources ? (Object.entries(daily.sources).find(([k]) => k.startsWith('alerts-'))?.[1] as {checked_at?: string} | undefined)?.checked_at ?? null : null,
    lead_with_advisory: Boolean(alerts?.length),
    ...(line ? {advisory_line: line} : {}),
    days,
    forecast_issued: intel?.completed_at ?? null,
    note: [alerts?.length ? `Start the reply with advisory_line (the word in capitals, SMALL CRAFT ADVISORY), and end with "${t(language, 'nws_closer')}"` : null,
      alerts === null ? 'NWS advisories could not be checked: say so and point to the NWS forecast.' : null,
      'Comfort is for a mid-size center console; the person\'s own boat may differ. Never say the harbor bar is open or closed. Never give a percentage or a catch number.'].filter(Boolean).join(' '),
  };
}

// ---- season, activity, confidence -----------------------------------------------------------

export type SeasonStatus = 'open' | 'closed' | 'no_rule';
export interface Season {status: SeasonStatus; stale: boolean; source_name: string | null; checked: string | null; line: string; link: string}

/** The season on the trip dates from the rules table, as words only (no rule number: get_rules quotes those). */
export async function seasonFor(db: D1Database, region: string, speciesKey: string, label: string, dates: readonly string[], now: number, language: Language): Promise<Season> {
  const link = `{{link:rules:${speciesKey}}}`;
  const row = pickRule(await lookupRules(db, {region, speciesKey, now}));
  if (!row) return {status: 'no_rule', stale: false, source_name: null, checked: null, line: t(language, 'planning_season_none', {species: label, link}), link};
  const open = dates.map(d => seasonOpen(row, d));
  const status: SeasonStatus = open.some(o => o === false) ? 'closed' : 'open';
  const key = status === 'closed' ? (row.stale ? 'planning_season_closed_stale' : 'planning_season_closed') : (row.stale ? 'planning_season_open_stale' : 'planning_season_open');
  return {status, stale: row.stale, source_name: row.source_name, checked: row.reviewed_at.slice(0, 10), line: t(language, key, {species: label, link}), link};
}

/** The feed species a ladder is computed for: a region target as it is ('reef'), else the catalog key a report files it under (vermilion → rockfish). */
const ladderKey = (key: string): string => key === 'reef' ? key : reportSpeciesKey(canonicalSpecies(key));

export interface Activity {
  skipper_reports: {date: string; day: string; boat: string; counts: {label: string; kept: number | null; released: number | null}[]}[];
  landing: {available: boolean; label: string; trips: number; boats: number; days: number; window: {from: string; to: string} | null};
}
export interface PlanningExtras {
  species_key: string | null; species_name: string | null; season: Season | null; recent_activity: Activity;
  confidence: Confidence; confidence_phrase: string; closer: string; note: string;
}

const PLANNING_NOTE = 'Compose the reply in this order: advisory_line first when there is one; then a closed season (season.line); then the day\'s conditions with the comfort word; '
  + 'then the season line otherwise (say "double-check" when it does); then the recent reports, each with its date and boat; then confidence_phrase, exactly once and word for word; '
  + 'end with closer. No other confidence word. Never a percentage or a catch number. For a size, bag or date, call get_rules.';

/**
 * The planning brief (06 § planning, TA-A2): get_conditions' data for the
 * port, date and window with `planning` added: the season, the recent
 * activity, the one confidence phrase and the closer, each in the reply
 * language. `env.DB` reads the rules and the reports.
 */
export async function planningBrief(env: Env, args: {port: string; date?: string | null; species: string; startHour?: number | null; endHour?: number | null}, opts: PlanningOptions): Promise<Record<string, unknown>> {
  const read = once(feedReader(opts.deps));
  const conditions = await tripConditions({port: args.port, date: args.date, start_hour: args.startHour, end_hour: args.endHour}, {...opts, read});
  if (conditions.error) return conditions;
  const port = conditions.port as string, regionId = portRegion(port)!, region = regionConfig(regionId)!, tz = region.timezone, language = opts.language;
  const today = localDate(opts.now, tz), dates = conditions.dates as string[];
  const species = resolveSpecies(args.species)?.key ?? null;
  const label = species ? speciesLabel({species_key: species, label: species}, language) : String(args.species ?? '').slice(0, 40);
  const db = env.DB!;

  const season = species ? await seasonFor(db, regionId, species, label, dates, opts.now, language) : null;

  // Recent activity: the daily answer's inputs (published skipper reports of three days, verified boats by name) for this species,
  // and the landing's reports of the last seven days with the ladder.
  const inputs = await dailyInputs(env, port, today, {feeds: read}, opts.now);
  const feedKey = species ? ladderKey(species) : null;
  const matches = (c: {species_key: string}) => feedKey !== null && (feedKey === 'reef' ? ['lingcod', 'rockfish'].includes(reportSpeciesKey(c.species_key)) : reportSpeciesKey(c.species_key) === feedKey);
  const skipper = inputs.skipper_reports.map(r => ({date: r.date, day: dayWord(r.date, today, language), boat: r.boat, counts: r.counts.filter(matches).map(({label: l, kept, released}) => ({label: l, kept, released}))}))
    .filter(r => r.counts.length).slice(0, 3);
  let landing: Activity['landing'] = {available: false, label: 'reported by the landing', trips: 0, boats: 0, days: 0, window: null};
  let confidence: Confidence = 'Insufficient';
  const daily = await dailyFeed(region, read);
  if (daily && feedKey && feedKey !== 'dungeness') {
    const names = new Set(landingNames(port).map(n => n.toLowerCase()));
    const portFeed = {...daily, reports: (daily.reports as LandingReport[]).filter(r => names.has(String(r.port ?? '').toLowerCase()))};
    const ev = reportEvidence(portFeed, feedKey, opts.now, null, tz);
    confidence = ev.confidence;
    landing = {available: true, label: 'reported by the landing', trips: ev.reports.length, boats: ev.boats, days: ev.days, window: {from: ev.start, to: ev.end}};
  } else if (daily) landing = {...landing, available: true};
  if (confidence === 'Insufficient' && skipper.some(r => r.counts.some(c => (c.kept ?? 0) > 0 || (c.released ?? 0) > 0))) confidence = 'Low';
  if (!CONFIDENCE_WORDS.includes(confidence)) confidence = 'Insufficient';

  const planning: PlanningExtras = {
    species_key: species, species_name: species ? label : null, season,
    recent_activity: {skipper_reports: skipper, landing},
    confidence, confidence_phrase: t(language, 'planning_confidence', {label: confidence}),
    closer: t(language, 'nws_closer'),
    note: species ? PLANNING_NOTE : `${PLANNING_NOTE} The species was not recognised: ask which fish they mean.`,
  };
  return fit({...conditions, planning});
}

/**
 * Keep the brief inside the tool-result limit (TOOL_RESULT_MAX; a cut JSON
 * would not parse): drop the advisory headlines first (the events and times
 * stay), then the oldest skipper reports, then the count lines past three.
 */
export function fit(brief: Record<string, unknown>, max = TOOL_RESULT_MAX - 100): Record<string, unknown> {
  const size = () => JSON.stringify(brief).length;
  if (size() <= max) return brief;
  if (Array.isArray(brief.advisories)) brief.advisories = (brief.advisories as Advisory[]).map(a => ({...a, headline: null}));
  const activity = (brief.planning as PlanningExtras | undefined)?.recent_activity;
  while (activity && size() > max && activity.skipper_reports.length > 1) activity.skipper_reports.pop();
  if (activity && size() > max) for (const r of activity.skipper_reports) r.counts = r.counts.slice(0, 3);
  return brief;
}
