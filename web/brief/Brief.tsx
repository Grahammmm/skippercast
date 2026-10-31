// The brief (FE-37, design § 10): the FE-31 model (web/brief/model.ts)
// rendered in tokens. Desktop.tsx shows the whole column; Mobile.tsx composes
// the same pieces into the sheet (peek: headline; half: tiles and top pick;
// full: everything).
//
// Data: the region's daily feed (/feeds/data/regions/<id>/latest.json) with
// the conditions feed's newer buoys first, both loaded by loadDailyFeed; the
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
import {hour, profile} from '../state.ts';
import {hasOwnLimits, limitsFor, type ComfortLimits} from '../limits.ts';
import {regionInfo, type RegionInfo} from '../app/App.tsx';
import {Popover} from '../ui/Popover.tsx';
import {buildCoastBrief, buildRegionalBrief} from './model.ts';
import {Tiles} from './Tiles.tsx';
import {TideStationControl} from './TideStationControl.tsx';
import {tideSelection} from '../tide-selection.ts';
import {withTideSelection} from '../tide-stations.ts';
import {briefVerdict, VERDICT_WORD, type BriefVerdict} from './verdict.ts';
import type {Brief as BriefModel, RegionalDailyFeed} from './types.ts';
import {DEFAULT_ZONE} from '../zone.ts';

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

export const FEED_GAP = {
  both: 'Conditions feeds could not be read: no buoy, tide or marine alert readings. The map, rules and trip tools still work.',
  daily: 'Daily feed could not be read',
  conditions: 'Live buoy feed could not be read: buoy readings come from the once-a-day run.',
} as const;

async function readFeed(path: string, id: string, fetchFn: typeof fetch): Promise<RegionalDailyFeed | null> {
  try {
    const response = await fetchFn(path);
    const json = response.ok ? await response.json() as Partial<RegionalDailyFeed> & {schema_version?: number} : null;
    return json?.schema_version === 1 && json.region_id === id && !!json.sources && typeof json.sources === 'object' ? json as RegionalDailyFeed : null;
  } catch { return null; }
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
  const lost = [kinds.has('prediction') ? null : 'tide predictions', kinds.has('advisory') ? null : 'marine alert checks'].filter(Boolean);
  return `${FEED_GAP.daily}${lost.length ? `: ${lost.join(' and ')} are missing` : ''}.`;
}

/** Load the daily and conditions feeds for region `id`; failed fetches or feeds for another region leave the brief empty. */
export async function loadDailyFeed(id: string, fetchFn: typeof fetch = fetch): Promise<RegionalDailyFeed | null> {
  const load = ++feedLoad;
  feedGaps.value = [];
  const [daily, conditions] = await Promise.all([readFeed(dailyFeedPath(id), id, fetchFn), readFeed(feedPath(undefined, id), id, fetchFn)]);
  // A later load (another region) owns the feed and its gap lines; this one only returns what it read.
  if (load !== feedLoad) return mergeFeeds(daily, conditions);
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

// One listener for the page's life, bound on the first load.
function bindVisibility() {
  if (visibilityBound || typeof document === 'undefined') return;
  visibilityBound = true;
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') void refreshForecastIfStale(); });
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

/** The brief the shell shows now, read from the signals so a component re-renders when they change. */
export function currentBrief(now: Date): BriefModel | null {
  const report = coastReport.value, binding = coastBinding.value;
  const brief = briefFrom({info: regionInfo.value, feed: dailyFeed.value, forecast: regionalForecast.value, coast: report && binding ? {report: report.data, areaId: binding.areaId} : null, profile: profile.value, hour: hour.value,
    limits: hasOwnLimits(profile.value) ? limitsFor(profile.value) : null}, now);
  const chosen = tideSelection.choice.value, config = tideSelection.region.value;
  if (!brief || !chosen || !config || config.id !== regionInfo.value?.id || chosen === config.station) return brief;
  const station = tideSelection.stations.value.find(s => s.id === chosen) ?? {id: chosen, name: chosen};
  return withTideSelection(brief, station, tideSelection.reading.value, regionInfo.value.timezone, now, hour.value);
}

export const Headline = ({brief}: {brief: BriefModel | null}) =>
  <h1>{brief?.headline ?? (feedGaps.value.includes(FEED_GAP.both) ? 'Readings unavailable.' : 'Waiting for readings.')}</h1>;

export const Deck = ({brief}: {brief: BriefModel | null}) => brief?.deck ? <p class="app-deck">{brief.deck}</p> : null;

/** The day verdict for the brief shown now: the regional forecast only when it is this region's. */
export function currentVerdict(brief: BriefModel | null, now: Date): BriefVerdict | null {
  const info = regionInfo.value, forecast = regionalForecast.value;
  return briefVerdict(brief, info && forecast?.region === info.id ? forecast : null, now, info?.timezone ?? DEFAULT_ZONE);
}

const VERDICT_BASIS = {
  'comfort-score': 'Comfort rating for the reference 23 ft boat, not a bite forecast or a safety clearance. Each hour of the window (sunrise to noon, or the rest of the daylight once noon has passed) is scored 0 to 10 from both forecast models’ wind, gusts, combined seas and wind chop at the forecast point, less a penalty for a crossing swell or short, steep chop. The worst hour sets the day: 7 and above is Comfortable, under 4 is Rough, Marginal between. An estimate missing wave detail or the second model is capped at 6.9; a marine alert makes the day Rough.',
  profile: 'Comfort rating from this profile’s hourly grade (surf or surge, wind, seas and launch where it applies), not a bite forecast or a safety clearance. The roughest hour of the window (sunrise to noon, or the rest of the daylight once noon has passed) sets the day; Calmer reads Comfortable. A marine alert makes the day Rough.',
} as const;

/**
 * The brief's first two lines: the verdict word for the morning window and one sentence naming what
 * limits it, with the basis behind a popover. Before there is a brief, the waiting headline.
 */
export function Verdict({brief, now}: {brief: BriefModel | null; now: Date}) {
  const v = currentVerdict(brief, now);
  if (!v) return <Headline brief={brief} />;
  return (
    <div class="app-verdict" data-verdict={v.verdict}>
      <div class="app-verdict-head">
        <h1><span class="app-verdict-word">{VERDICT_WORD[v.verdict]}</span>{v.window ? ' ' : null}{v.window ? <span class="app-verdict-window ui-mono">{v.window}</span> : null}</h1>
        <Popover align="end">{v.basis === 'comfort-score' ? VERDICT_BASIS['comfort-score'] : VERDICT_BASIS.profile}{v.score !== null ? ` Worst hour: ${v.score}/10.` : ''}</Popover>
      </div>
      <p class="app-verdict-limit">{v.limit}{v.held ? ` ${v.held}` : ''}</p>
    </div>
  );
}

/**
 * The longer text folded under the verdict: the readings line, the deck, what is missing and the
 * profile caveat (the profile's own before there is a brief). The summary keeps a count of missing or
 * stale sources in view.
 */
export function Details({brief}: {brief: BriefModel | null}) {
  const gaps = feedGaps.value.length + (brief?.gaps.length ?? 0);
  return (
    <details class="app-details">
      <summary>Details{gaps ? <span class="app-details-gaps"> · {gaps} missing or stale</span> : null}</summary>
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
  <><Tiles tiles={brief?.tiles ?? null} compact={compact} dense={dense} nearshore={PROFILE_TABLE[profile.value].swellTile === 'nearshore'} />{compact ? null : <TideStationControl />}</>;

const clock = (iso: string, tz: string) => new Intl.DateTimeFormat('en-US', {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(iso)).replace(':00', '').toLowerCase();

/** The quietest window the model screened, labelled lower exposure; none is said plainly. */
export function LowerExposure({brief}: {brief: BriefModel | null}) {
  if (!brief) return null;
  const tz = regionInfo.value?.timezone ?? DEFAULT_ZONE, w = brief.windows[0];
  // The safety caveat stays visible; a window the user's looser limits decided adds that note after it.
  const own = w?.reasons.find(reason => reason.startsWith('Using your limits')), caveat = w?.reasons.find(reason => reason !== own);
  return (
    <p class="app-window">
      <span class="ui-eyebrow">Lower exposure</span>{' '}
      {w ? <><span class="ui-mono">{clock(w.start, tz)}–{clock(w.end, tz)}</span> · {w.label}. {[caveat, own].filter(Boolean).join('. ')}</> : brief.limits?.custom ? 'No lower-exposure window within your limits for this day.' : 'No lower-exposure window screened for this day.'}
    </p>
  );
}

/**
 * What the brief is missing and why. Feeds that could not be read and brief sources that are not
 * ok (stale, retained, failed or missing, each named by its station) stay visible; what the day's
 * model could not check sits in a disclosure, so the list never becomes a caveat wall.
 */
export function BriefGaps({brief}: {brief: BriefModel | null}) {
  const feeds = feedGaps.value, sources = brief?.gaps ?? [], unchecked = brief?.missing ?? [];
  if (!feeds.length && !sources.length && !unchecked.length) return null;
  return (
    <div class="app-gaps">
      {feeds.length || sources.length ? (
        <ul class="app-gaps-list" aria-label="Missing readings">
          {feeds.map(text => <li key={text}>{text}</li>)}
          {sources.map(gap => <li key={gap.id} data-status={gap.status}>{gap.text}</li>)}
        </ul>
      ) : null}
      {unchecked.length ? (
        <details class="app-gaps-more">
          <summary>Not checked in this brief ({unchecked.length})</summary>
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
      {brief.notice ? <li><a href={brief.notice.url} target="_blank" rel="noopener">Beach notice: {brief.notice.name}</a></li> : null}
      {brief.fleet ? <li><a href={brief.fleet.href}>{brief.fleet.text}</a></li> : null}
      <li class="app-local" data-available={String(brief.localReport.available)}>{brief.localReport.text}</li>
    </ul>
  );
}

export const DISCLAIMER = 'Forecasts, observations and habitat carry separate clocks; check the rules before you fish.';

/** The one disclaimer line per page with the sources link; `children` adds links after it. */
export const BriefFooter = ({children}: {children?: ComponentChildren} = {}) =>
  <footer class="app-brief-footer">{DISCLAIMER} <a href="/sources">Sources</a>{children}</footer>;
