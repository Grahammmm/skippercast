// The brief (FE-37, design § 10): the FE-31 model (web/brief/model.ts)
// rendered in tokens. Desktop.tsx shows the whole column; Mobile.tsx composes
// the same pieces into the sheet (peek: headline; half: tiles and top pick;
// full: everything).
//
// Data: the region's daily feed (/feeds/data/regions/<id>/latest.json) with
// the conditions feed's newer buoys first, both loaded by loadDailyFeed (read again like the forecast); the
// regional forecast (/api/forecast?region=<id>, edge-cached, loaded once per
// region by ensureRegionalForecast and shared with the Conditions view; web/conditions.ts briefForecast samples it at the
// forecast point nearest the region centre) and, where web/coast-data.ts
// admits a coast report for a bound place, that report. Without the forecast
// the wind and swell tiles read unavailable rather than guessed; with an old
// run they read stale with its age. Before the feed loads the brief keeps its
// empty state; when a feed cannot be read, BriefGaps says which and the
// headline stops waiting.
import type {ComponentChildren} from 'preact';
import {effect, signal} from '@preact/signals';
import {counties} from '../../packages/coast/src/counties.ts';
import {dateKey} from '../../packages/coast/src/daily.ts';
import type {Report} from '../../packages/coast/src/types.ts';
import {coastBinding, coastData, coastReport, type CoastData} from '../coast-data.ts';
import type {CoastReportContext} from '../../packages/coast/src/state/report-binding.ts';
import {briefForecast, loadConditionsForecast, type ConditionsForecast} from '../conditions.ts';
import {feedPath} from '../landing/readings.ts';
import {PROFILE_TABLE, type Profile} from '../profile.ts';
import {day, hour, hourParam, parseHour, profile, species} from '../state.ts';
import {dockTime, horizonDays} from '../hour.ts';
import {loadRegs, regsData, regulationState, ruleSummary} from '../regs.ts';
import {useEffect} from 'preact/hooks';
import {hasOwnLimits, limitsFor, type ComfortLimits} from '../limits.ts';
import {regionInfo, type RegionInfo} from '../app/region-info.ts';
import {Popover} from '../ui/Popover.tsx';
import {buildCoastBrief, buildRegionalBrief} from './model.ts';
import {Tiles} from './Tiles.tsx';
import {TideStationControl} from './TideStationControl.tsx';
import {tideSelection} from '../tide-selection.ts';
import {withTideSelection} from '../tide-stations.ts';
import {briefVerdict, clockText, feedReader, type BriefVerdict} from './verdict.ts';
import {activeBoatFactors, savedBoat} from '../../dist/boat-handling.js';
import {boatBasisName, boatRangeNote, REFERENCE_BOAT_NAME, type SavedBoatLike} from '../boat-range.ts';
import {language, localeOf, num, shortDate, t, type Language, type StringId} from '../i18n.ts';
import {boatSaved} from '../boat-entry.ts';
import type {BoatFactors} from '../score.ts';
import type {Brief as BriefModel, RegionalDailyFeed} from './types.ts';
import {DEFAULT_ZONE} from '../zone.ts';
import {dailyPartPath} from '../../dist/offline-core.js';
import {validDailyPart} from '../map/habitat.ts';

export type {BriefModel};

/** The region's daily feed once loaded; null before, or when it failed its identity check. */
export const dailyFeed = signal<RegionalDailyFeed | null>(null);

/** The region's daily feed (`data` branch `regions/<id>/latest.json`): tides, advisories, chlorophyll, landing reports and their landing names. */
export const dailyFeedPath = (id: string): string => `/feeds/data/regions/${encodeURIComponent(id)}/latest.json`;

/**
 * Why the brief's feeds are incomplete, one line per feed that could not be read (missing,
 * unreadable, wrong schema or another region's); empty before loading and when both loaded.
 */
export const feedGaps = signal<readonly string[]>([]);

let feedLoad = 0;

export const FEED_GAP = {both: t('brief.gap.both'), daily: t('brief.gap.daily').replace(/\.$/, ''), conditions: t('brief.gap.conditions')} as const;

/** A feed-gap line (kept in English in feedGaps, which the tests compare) in `lang`: each is one of the catalogue's English gap sentences. */
const GAP_IDS: readonly StringId[] = ['brief.gap.both', 'brief.gap.daily', 'brief.gap.daily.tide', 'brief.gap.daily.alerts', 'brief.gap.daily.both', 'brief.gap.conditions'];
const gapText = (text: string, lang: Language): string => { const id = GAP_IDS.find(i => t(i) === text); return id ? t(id, lang) : text; };

async function readFeed(path: string, id: string, fetchFn: typeof fetch): Promise<RegionalDailyFeed | null> {
  try {
    const response = await fetchFn(path);
    const json = response.ok ? await response.json() as Partial<RegionalDailyFeed> & {schema_version?: number} : null;
    return json?.schema_version === 1 && json.region_id === id && !!json.sources && typeof json.sources === 'object' ? json as RegionalDailyFeed : null;
  } catch { return null; }
}

/**
 * SC2222-03: the daily feed's 'brief' part from /api/daily (about a sixth of the whole feed), with the same
 * identity checks; the whole feed is read once only when the part fails and load `load` is still the latest.
 */
async function readDaily(id: string, fetchFn: typeof fetch, load: number): Promise<RegionalDailyFeed | null> {
  const part = await readFeed(dailyPartPath(id, 'brief'), id, fetchFn);
  if (part && validDailyPart(part as unknown as Record<string, unknown>, 'brief', id)) return part;
  return load === feedLoad ? readFeed(dailyFeedPath(id), id, fetchFn) : null;
}

/**
 * The daily feed with the conditions feed's buoy observations first: the conditions run every 30
 * minutes, the daily run once a day, so the regional brief's water tile reads the newer buoy
 * (regionalReport takes the first observation source). Either feed alone stands when the other fails.
 */
export function mergeFeeds(daily: RegionalDailyFeed | null, conditions: RegionalDailyFeed | null): RegionalDailyFeed | null {
  if (!daily || !conditions) return daily ?? conditions;
  const buoys = Object.fromEntries(Object.entries(conditions.sources).filter(([, source]) => source?.kind === 'observation'));
  // Buoys first in key order, and the conditions copy wins where both feeds use one key.
  return {...daily, sources: {...buoys, ...daily.sources, ...buoys}};
}

/** The daily feed's line: what the brief lost with it, judged by what the conditions feed still carries. */
function dailyGap(conditions: RegionalDailyFeed): string {
  const kinds = new Set(Object.values(conditions.sources).map(source => source?.kind));
  const tide = !kinds.has('prediction'), alerts = !kinds.has('advisory');
  return t(tide && alerts ? 'brief.gap.daily.both' : tide ? 'brief.gap.daily.tide' : alerts ? 'brief.gap.daily.alerts' : 'brief.gap.daily');
}

/** Load the daily and conditions feeds for region `id`; failed fetches or feeds for another region leave the brief empty. */
export function loadDailyFeed(id: string, fetchFn: typeof fetch = fetch): Promise<RegionalDailyFeed | null> {
  return readFeeds(id, fetchFn, false);
}

let dailyRequest: {id: string; fetchFn: typeof fetch} | null = null;
let dailyLoadedAt = 0, dailyPending = false;

async function readFeeds(id: string, fetchFn: typeof fetch, refresh: boolean): Promise<RegionalDailyFeed | null> {
  const load = ++feedLoad;
  dailyRequest = {id, fetchFn};
  dailyPending = true;
  bindVisibility();
  if (!refresh) feedGaps.value = [];
  const [daily, conditions] = await Promise.all([readDaily(id, fetchFn, load), readFeed(feedPath(undefined, id), id, fetchFn)]);
  // A later load (another region) owns the feed and its gap lines; this one only returns what it read.
  if (load !== feedLoad) return mergeFeeds(daily, conditions);
  dailyPending = false;
  // A refresh that read neither keeps the feed and gap lines shown (readings carry their own times) and its old
  // read time, so the next visible page tries again.
  if (refresh && !daily && !conditions) return dailyFeed.peek();
  dailyLoadedAt = Date.now();
  feedGaps.value = !daily && !conditions ? [FEED_GAP.both] : !daily ? [dailyGap(conditions!)] : !conditions ? [FEED_GAP.conditions] : [];
  dailyFeed.value = mergeFeeds(daily, conditions);
  return dailyFeed.peek();
}

/**
 * Ask the coast data client for the report wherever `place` binds one, whichever layers are on (the
 * Swell and Water temp layers ask for the same place; the client requests once per place).
 */
export function bindBriefReport(place: () => CoastReportContext | null, data: Pick<CoastData, 'setPlace' | 'load'> = coastData): () => void {
  return effect(() => {
    const p = place();
    if (!p) return;
    data.setPlace(p);
    void data.load('report');
  });
}

/** The region's forecast feed at its chosen point once loaded; null before, when it failed, or for another region. */
export const regionalForecast = signal<ConditionsForecast | null>(null);
let forecastKey: string | null = null;
let forecastRequest: {id: string; near: readonly [number, number] | null; fetchFn: typeof fetch; page: string} | null = null;
let forecastLoadedAt = 0, forecastPending = false, visibilityBound = false;
/** A loaded forecast older than this is fetched again when the page becomes visible. */
export const FORECAST_MAX_AGE_MS = 30 * 60_000;

/** Load the forecast for region `id` at the point nearest `near`, once per region and point; the brief and the Conditions view share it. */
export function ensureRegionalForecast(id: string, near: readonly [number, number] | null, fetchFn: typeof fetch = fetch, page = location.href): Promise<ConditionsForecast | null> {
  const key = `${id}|${near?.join(',') ?? ''}`;
  bindVisibility();
  if (forecastKey === key) return Promise.resolve(regionalForecast.peek());
  forecastKey = key;
  forecastRequest = {id, near, fetchFn, page};
  forecastPending = true;
  if (regionalForecast.peek()?.region !== id) regionalForecast.value = null;
  return loadConditionsForecast(id, near, fetchFn, page).then(f => {
    if (forecastKey !== key) return regionalForecast.peek();
    forecastPending = false;
    regionalForecast.value = f;
    forecastLoadedAt = Date.now();
    if (!f) forecastKey = null; // a failed load is tried again on the next call
    return f;
  });
}

/** Reload the forecast when it failed or was loaded over 30 minutes before `now`; no timer, only called as the page becomes visible. */
export function refreshForecastIfStale(now = Date.now()): Promise<ConditionsForecast | null> | null {
  const req = forecastRequest;
  if (!req || forecastPending) return null;
  if (regionalForecast.peek() && now - forecastLoadedAt <= FORECAST_MAX_AGE_MS) return null;
  forecastKey = null;
  return ensureRegionalForecast(req.id, req.near, req.fetchFn, req.page);
}

/** The brief's daily and conditions feeds follow the forecast's 30-minute rule. */
export const DAILY_MAX_AGE_MS = FORECAST_MAX_AGE_MS;

/** Read both feeds again for the last loaded region when the last read got neither or was over 30 minutes before `now`; no timer, only called as the page becomes visible. */
export function refreshDailyIfStale(now = Date.now()): Promise<RegionalDailyFeed | null> | null {
  const req = dailyRequest;
  if (!req || dailyPending) return null;
  if (dailyFeed.peek() && now - dailyLoadedAt <= DAILY_MAX_AGE_MS) return null;
  return readFeeds(req.id, req.fetchFn, true);
}

// One listener for the page's life, bound on the first load.
function bindVisibility() {
  if (visibilityBound || typeof document === 'undefined') return;
  visibilityBound = true;
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { void refreshForecastIfStale(); void refreshDailyIfStale(); } });
}

export type BriefSources = {info: RegionInfo | null; feed: RegionalDailyFeed | null; forecast?: ConditionsForecast | null; coast: {report: Report; areaId: string} | null; profile: Profile; hour: string | null;
  /** The user's own comfort limits for the profile (web/limits.ts); null or absent uses the defaults. */
  limits?: ComfortLimits | null};

/** The brief for these sources at `now`, or null when the region's feed is not in hand. */
export function briefFrom({info, feed, forecast = null, coast, profile: p, hour: at, limits = null}: BriefSources, now: Date): BriefModel | null {
  if (!info || !feed || feed.region_id !== info.id) return null;
  const pivot = at && Number.isFinite(Date.parse(at)) ? at : undefined;
  const date = dateKey(new Date(pivot ?? now), info.timezone);
  try {
    const county = coast ? counties[coast.report.countyId] : undefined;
    if (coast && county) return buildCoastBrief({report: coast.report, county, areaId: coast.areaId, profile: p, date, now, at: pivot, reports: feed.reports ?? [], port: feed.landing_names ?? [], daily: feed, limits});
    const [lat, lon] = info.center;
    return buildRegionalBrief({daily: feed, forecast: forecast?.region === info.id ? briefForecast(forecast) : null, place: {id: info.id, name: info.name, lat, lon, timezone: info.timezone}, profile: p, date, now, at: pivot, limits});
  } catch { return null; }
}

/** The brief the shell shows now, read from the signals so a component re-renders when they change. `at` defaults to the dock's hour. */
export function currentBrief(now: Date, at: string | null = hour.value): BriefModel | null {
  const report = coastReport.value, binding = coastBinding.value;
  const brief = briefFrom({info: regionInfo.value, feed: dailyFeed.value, forecast: regionalForecast.value, coast: report && binding ? {report: report.data, areaId: binding.areaId} : null, profile: profile.value, hour: at,
    limits: hasOwnLimits(profile.value) ? limitsFor(profile.value) : null}, now);
  const chosen = tideSelection.choice.value, config = tideSelection.region.value;
  if (!brief || !chosen || !config || config.id !== regionInfo.value?.id || chosen === config.station) return brief;
  const station = tideSelection.stations.value.find(s => s.id === chosen) ?? {id: chosen, name: chosen};
  return withTideSelection(brief, station, tideSelection.reading.value, regionInfo.value.timezone, now, at);
}

/**
 * The hour the lead answers for (SC-LAUNCH-3): the hour chosen in the dock; else the later day a
 * link's ?day= names; else tomorrow. A day is read at the dock's hour on it (web/hour.ts dockTime),
 * so the lead is the brief the dock shows once that day is picked. Null (now) only for ?day= today.
 */
export function leadHour(hourValue: string | null, dayValue: string | null, now: Date, tz: string): string | null {
  if (parseHour(hourValue) !== null) return hourValue;
  const days = horizonDays(now, tz);
  if (dayValue && dayValue === days[0]?.day) return null;
  const named = days.slice(1).find(d => d.day === dayValue) ?? days[1];
  return named ? hourParam(dockTime(named.day, null, now, tz, days).at / 1000) : null;
}

/** The brief the lead answers from: the dock's brief once a time is chosen, else tomorrow's. */
export function leadBrief(now: Date): BriefModel | null {
  return currentBrief(now, leadHour(hour.value, day.value, now, regionInfo.value?.timezone ?? DEFAULT_ZONE));
}

/** The day ("YYYY-MM-DD") the lead answers for: its brief's date, else the day of its hour. */
export function leadDate(now: Date, brief: BriefModel | null = leadBrief(now)): string {
  const tz = regionInfo.value?.timezone ?? DEFAULT_ZONE, at = leadHour(hour.value, day.value, now, tz);
  return brief?.date ?? dateKey(at ? new Date(at) : now, tz);
}

/** "today", "tomorrow", else "Sat Oct 10" ("hoy", "mañana", "el sáb 10 oct"), for the lead's day `date` ("YYYY-MM-DD"). */
export function leadDayText(date: string, now: Date, tz: string, lang: Language = 'en'): string {
  const today = dateKey(now, tz), next = dateKey(new Date(Date.parse(`${today}T12:00:00Z`) + 86_400_000), 'UTC');
  if (date === today) return t('brief.day.today', lang);
  if (date === next) return t('brief.day.tomorrow', lang);
  return t('brief.day.date', lang, {date: shortDate(`${date}T12:00:00Z`, lang)});
}

export const Headline = ({brief}: {brief: BriefModel | null}) =>
  <h1>{brief?.headline ?? t(feedGaps.value.includes(FEED_GAP.both) ? 'brief.unavailable' : 'common.waiting', language.value)}</h1>;

export const Deck = ({brief}: {brief: BriefModel | null}) => brief?.deck ? <p class="app-deck">{brief.deck}</p> : null;

/** The boat saved in this browser (dist/boat-handling.js), or null. */
const storedBoat = (): SavedBoatLike => (savedBoat() as {boat?: SavedBoatLike} | null)?.boat ?? null;

/** The day verdict for the brief shown now: the regional forecast only when it is this region's, rated for the saved boat (MYB-2). */
export function currentVerdict(brief: BriefModel | null, now: Date): BriefVerdict | null {
  const info = regionInfo.value, forecast = regionalForecast.value;
  void boatSaved.value;   // a boat saved on first use (boat-entry.ts) re-rates the verdict on screen
  return briefVerdict(brief, info && forecast?.region === info.id ? forecast : null, now, info?.timezone ?? DEFAULT_ZONE, activeBoatFactors() as BoatFactors);
}

/** The boat the comfort rating names, in `lang`; a saved boat's own name is shown as typed. */
function boatName(boat: SavedBoatLike, lang: Language): string {
  const name = boatBasisName(boat), length = /^your (\d+(?:\.\d+)?) ft boat$/.exec(name);
  return name === REFERENCE_BOAT_NAME ? t('brief.boat.reference', lang) : name === 'your boat' ? t('brief.boat.generic', lang) : length ? t('brief.boat.yours', lang, {n: length[1]!}) : name;
}

/** The comfort-score basis naming the boat rated: the saved boat's name, "your <n> ft boat", or the reference 23 ft boat. */
export const comfortBasis = (boat: SavedBoatLike, lang: Language = 'en'): string => t('brief.basis.comfort', lang, {boat: boatName(boat, lang)});

/** The basis line on a provisional day. */
export const PROVISIONAL_BASIS = t('brief.provisional.basis');

/**
 * The lead's legality line (SC-LAUNCH-3): whether the selected target (the profile's default before
 * one is chosen) is open on the lead's day, as web/regs.ts regulationState and ruleSummary read the
 * region's reviewed registry, with the state's own reason and the official link. Nothing is computed
 * here; before the registry loads the state reads "Check rules", never open.
 */
export function LeadRules({date, now}: {date: string; now: Date}) {
  const rules = regionInfo.value?.rules, lang = language.value;
  useEffect(() => { if (rules) void loadRegs(rules); }, [rules?.id]);
  if (!rules) return null;
  const loaded = regsData.value, data = loaded?.region === rules.id ? loaded.data : null;
  const target = species.value ?? PROFILE_TABLE[profile.value].defaultTarget;
  const state = regulationState(data, target, rules, now.getTime(), date, null), s = ruleSummary(data, target, state, rules, lang);
  const name = target === 'reef' ? 'Lingcod & rockfish' : state.profile?.name ?? target;
  return (
    <p class="app-verdict-rules" data-status={s.status}>
      <span class="app-mark-regs-badge" data-status={s.status}>{s.label}</span> {name} {leadDayText(date, now, rules.timezone ?? DEFAULT_ZONE, lang)}. {lang === 'es' ? <><span lang="en">{state.reason}</span> {t('rules.english.inline', lang)}</> : state.reason}{' '}
      <a href={s.link} target="_blank" rel="noopener" aria-label={t('rules.link.for', lang, {label: s.linkLabel, name})}>{s.linkLabel}</a>
    </p>
  );
}

/**
 * The brief's first lines: the verdict word for the morning window of the lead's day (tomorrow until
 * a time is chosen), the day and window, one sentence naming what limits it with the basis behind a
 * popover, and whether the target is legal that day. A provisional day (packages/coast daily.ts, from
 * the day after tomorrow) says so in the verdict line itself. Before there is a brief, the waiting headline.
 */
export function Verdict({now}: {now: Date}) {
  const tz = regionInfo.value?.timezone ?? DEFAULT_ZONE, brief = leadBrief(now), date = leadDate(now, brief), lang = language.value;
  const v = currentVerdict(brief, now), rulesLine = <LeadRules date={date} now={now} />;
  if (!v) return <><Headline brief={brief} />{rulesLine}</>;
  const when = leadDayText(date, now, tz, lang);
  const provisional = !!brief?.provisional;
  const a = v.agreement, gap = (n: number) => num(Number(n.toFixed(1)), lang);
  const models = !a || a.state === 'none' ? null : a.state === 'agree' ? t('brief.models.agree', lang, {until: v.window?.split('–')[1] ?? '', wind: gap(a.gap!.wind), sea: gap(a.gap!.sea)})
    : a.state === 'differ' ? `${t('brief.models.differ', lang, {at: clockText(a.worst!.ms, tz), wind: gap(a.worst!.wind), sea: gap(a.worst!.sea)})}${a.differing > 1 ? ` ${t('brief.models.hours', lang, {n: a.differing, total: a.hours})}` : ''}`
    : a.state === 'partial' ? t('brief.models.partial', lang, {n: a.compared, total: a.hours}) : t('brief.models.one', lang);
  const modelHour = a?.state === 'differ' && regionalForecast.value ? feedReader(regionalForecast.value, now).read(a.worst!.ms) : null;
  const boat = v.basis === 'comfort-score' ? storedBoat() : null, rangeNote = boat && boatRangeNote(boat.loa_ft) ? t('brief.boat.note', lang) : null;
  return (
    <div class="app-verdict" data-verdict={v.verdict} data-provisional={provisional ? 'true' : undefined}>
      <div class="app-verdict-head">
        <h1><span class="app-verdict-word">{t(`brief.verdict.${v.verdict}` as StringId, lang)}</span>{' '}<span class="app-verdict-window ui-mono" data-day={date}>{v.window ? `${when}, ${v.window}` : when}</span>{provisional ? ' ' : null}{provisional ? <span class="app-verdict-window app-verdict-provisional ui-mono">{t('brief.provisional', lang)}</span> : null}</h1>
        <Popover align="end">{v.basis === 'comfort-score' ? comfortBasis(boat, lang) : t('brief.basis.profile', lang)}{rangeNote ? ` ${rangeNote}` : ''}{provisional ? ` ${t('brief.provisional.basis', lang)}` : ''}{v.score !== null ? ` ${t('brief.worst', lang, {score: num(v.score, lang, 20)})}` : ''}</Popover>
      </div>
      <p class="app-verdict-limit">{v.limit}{v.held ? ` ${v.held}` : ''}</p>
      {rangeNote ? <p class="app-verdict-boat-note">{rangeNote}</p> : null}
      {models ? <p class="app-verdict-models ui-mono" data-agreement={a!.state}>{models}</p> : null}
      {modelHour ? <details class="app-verdict-models-detail"><summary>{t('brief.models.detail', lang)}</summary>{t('brief.models.readings', lang, {w1: gap(modelHour.wind!), w2: gap(modelHour.other_wind!), s1: gap(modelHour.sea!), s2: gap(modelHour.other_sea!)})}</details> : null}
      {rulesLine}
    </div>
  );
}

/**
 * The longer text folded under the verdict: the readings line, the deck, what is missing and the
 * profile caveat (the profile's own before there is a brief). The summary keeps a count of missing or
 * stale sources in view.
 */
export function Details({brief}: {brief: BriefModel | null}) {
  const gaps = feedGaps.value.length + (brief?.gaps.length ?? 0), lang = language.value;
  return (
    <details class="app-details">
      <summary>{t('brief.details', lang)}{gaps ? <span class="app-details-gaps"> · {t('brief.details.gaps', lang, {n: gaps})}</span> : null}</summary>
      <div class="app-details-body">
        {brief ? <p class="app-readings ui-mono">{brief.headline}</p> : null}
        <Deck brief={brief} />
        <BriefGaps brief={brief} />
        <Caveat brief={brief} />
      </div>
    </details>
  );
}

/** The four tiles: compact in the sheet below full, dense (short source, one row) in the desktop column. */
export const BriefTiles = ({brief, compact = false, dense = false}: {brief: BriefModel | null; compact?: boolean; dense?: boolean}) =>
  <><Tiles tiles={brief?.tiles ?? null} compact={compact} dense={dense} provisional={!!brief?.provisional} nearshore={PROFILE_TABLE[profile.value].swellTile === 'nearshore'} />{compact ? null : <TideStationControl />}</>;

const clock = (iso: string, tz: string, lang: Language = 'en') => new Intl.DateTimeFormat(localeOf(lang), {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(iso)).replace(':00', '').toLowerCase();

/** The quietest window the model screened, labelled lower exposure; none is said plainly. */
export function LowerExposure({brief}: {brief: BriefModel | null}) {
  if (!brief) return null;
  const tz = regionInfo.value?.timezone ?? DEFAULT_ZONE, w = brief.windows[0], lang = language.value;
  // The safety caveat stays visible; a window the user's looser limits decided adds that note after it.
  const own = w?.reasons.find(reason => reason.startsWith('Using your limits')), caveat = w?.reasons.find(reason => reason !== own);
  return (
    <p class="app-window">
      <span class="ui-eyebrow">{t('brief.lower', lang)}</span>{' '}
      {w ? <><span class="ui-mono">{clock(w.start, tz, lang)}–{clock(w.end, tz, lang)}</span> · {w.label}. {[caveat, own].filter(Boolean).join('. ')}</> : t(brief.limits?.custom ? 'brief.lower.custom' : 'brief.lower.none', lang)}
    </p>
  );
}

/**
 * What the brief is missing and why. Feeds that could not be read and brief sources that are not
 * ok (stale, retained, failed or missing, each named by its station) stay visible; what the day's
 * model could not check sits in a disclosure, so the list never becomes a caveat wall.
 */
export function BriefGaps({brief}: {brief: BriefModel | null}) {
  const feeds = feedGaps.value, sources = brief?.gaps ?? [], unchecked = brief?.missing ?? [], lang = language.value;
  if (!feeds.length && !sources.length && !unchecked.length) return null;
  return (
    <div class="app-gaps">
      {feeds.length || sources.length ? (
        <ul class="app-gaps-list" aria-label={t('brief.gaps.label', lang)}>
          {feeds.map(text => <li key={text}>{gapText(text, lang)}</li>)}
          {sources.map(gap => <li key={gap.id} data-status={gap.status}>{gap.text}</li>)}
        </ul>
      ) : null}
      {unchecked.length ? (
        <details class="app-gaps-more">
          <summary>{t('brief.gaps.unchecked', lang, {n: unchecked.length})}</summary>
          <ul>{unchecked.map(text => <li key={text}>{text}</li>)}</ul>
        </details>
      ) : null}
    </div>
  );
}

export const Caveat = ({brief}: {brief: BriefModel | null}) => <p class="app-caveat">{brief?.caveat ?? PROFILE_TABLE[profile.value].caveat}</p>;

/** The beach notice link, the fleet line and the local-report line, each only when the model has it. */
export function BriefLinks({brief}: {brief: BriefModel | null}) {
  if (!brief) return null;
  return (
    <ul class="app-brief-links">
      {brief.notice ? <li><a href={brief.notice.url} target="_blank" rel="noopener">{t('brief.notice', language.value, {name: brief.notice.name})}</a></li> : null}
      {brief.fleet ? <li><a href={brief.fleet.href}>{brief.fleet.text}</a></li> : null}
      <li class="app-local" data-available={String(brief.localReport.available)}>{brief.localReport.text}</li>
    </ul>
  );
}

export const DISCLAIMER = t('brief.disclaimer');

/** The C1 short form of docs/legal/disclaimers.md (item 3, the persistent footer line). */
export const PLANNING_AID = t('brief.planning');

/** The one disclaimer line per page with the planning-aid line, Terms and Sources links; `children` adds links after them. */
export const BriefFooter = ({children}: {children?: ComponentChildren} = {}) =>
  <footer class="app-brief-footer">{t('brief.disclaimer', language.value)} {t('brief.planning', language.value)} <a href="/terms.html">{t('brief.terms', language.value)}</a> · <a href="/sources">{t('brief.sources', language.value)}</a>{children}</footer>;
