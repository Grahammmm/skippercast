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
// run they read stale with its age. Before the feed loads, or when it fails,
// the brief keeps its empty state.
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
import {buildCoastBrief, buildRegionalBrief} from './model.ts';
import {Tiles} from './Tiles.tsx';
import type {Brief as BriefModel, RegionalDailyFeed} from './types.ts';

export type {BriefModel};

/** The region's daily feed once loaded; null before, or when it failed its identity check. */
export const dailyFeed = signal<RegionalDailyFeed | null>(null);

/** The region's daily feed (`data` branch `regions/<id>/latest.json`): tides, advisories, chlorophyll, landing reports and their landing names. */
export const dailyFeedPath = (id: string): string => `/feeds/data/regions/${encodeURIComponent(id)}/latest.json`;

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
  return {...daily, sources: {...buoys, ...daily.sources}};
}

/** Load the daily and conditions feeds for region `id`; failed fetches or feeds for another region leave the brief empty. */
export async function loadDailyFeed(id: string, fetchFn: typeof fetch = fetch): Promise<RegionalDailyFeed | null> {
  const [daily, conditions] = await Promise.all([readFeed(dailyFeedPath(id), id, fetchFn), readFeed(feedPath(undefined, id), id, fetchFn)]);
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
  return briefFrom({info: regionInfo.value, feed: dailyFeed.value, forecast: regionalForecast.value, coast: report && binding ? {report: report.data, areaId: binding.areaId} : null, profile: profile.value, hour: hour.value,
    limits: hasOwnLimits(profile.value) ? limitsFor(profile.value) : null}, now);
}

export const Headline = ({brief}: {brief: BriefModel | null}) => <h1>{brief?.headline ?? 'Waiting for readings.'}</h1>;

export const Deck = ({brief}: {brief: BriefModel | null}) => brief?.deck ? <p class="app-deck">{brief.deck}</p> : null;

export const BriefTiles = ({brief, compact = false}: {brief: BriefModel | null; compact?: boolean}) =>
  <Tiles tiles={brief?.tiles ?? null} compact={compact} nearshore={PROFILE_TABLE[profile.value].swellTile === 'nearshore'} />;

const clock = (iso: string, tz: string) => new Intl.DateTimeFormat('en-US', {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(iso)).replace(':00', '').toLowerCase();

/** The quietest window the model screened, labelled lower exposure; none is said plainly. */
export function LowerExposure({brief}: {brief: BriefModel | null}) {
  if (!brief) return null;
  const tz = regionInfo.value?.timezone ?? 'America/Los_Angeles', w = brief.windows[0];
  // The safety caveat stays visible; a window the user's looser limits decided adds that note after it.
  const own = w?.reasons.find(reason => reason.startsWith('Using your limits')), caveat = w?.reasons.find(reason => reason !== own);
  return (
    <p class="app-window">
      <span class="ui-eyebrow">Lower exposure</span>{' '}
      {w ? <><span class="ui-mono">{clock(w.start, tz)}–{clock(w.end, tz)}</span> · {w.label}. {[caveat, own].filter(Boolean).join('. ')}</> : brief.limits?.custom ? 'No lower-exposure window within your limits for this day.' : 'No lower-exposure window screened for this day.'}
    </p>
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
