// The brief (FE-37, design § 10): the FE-31 model (web/brief/model.ts)
// rendered in tokens. Desktop.tsx shows the whole column; Mobile.tsx composes
// the same pieces into the sheet (peek: headline; half: tiles and top pick;
// full: everything).
//
// Data: the region's daily feed (/feeds/conditions/regions/<id>/latest.json,
// loaded by loadDailyFeed) and, where web/coast-data.ts admits a coast report
// for a bound place, that report. Without a regional forecast (FE-32 brings
// web/conditions.ts) the wind and swell tiles read unavailable rather than
// guessed. Before the feed loads, or when it fails, the brief keeps its empty
// state.
import type {ComponentChildren} from 'preact';
import {signal} from '@preact/signals';
import {counties} from '../../packages/coast/src/counties.ts';
import {dateKey} from '../../packages/coast/src/daily.ts';
import type {Report} from '../../packages/coast/src/types.ts';
import {coastBinding, coastReport} from '../coast-data.ts';
import {feedPath} from '../landing/readings.ts';
import {PROFILE_TABLE, type Profile} from '../profile.ts';
import {hour, profile} from '../state.ts';
import {regionInfo, type RegionInfo} from '../app/App.tsx';
import {buildCoastBrief, buildRegionalBrief} from './model.ts';
import {Tiles} from './Tiles.tsx';
import type {Brief as BriefModel, RegionalDailyFeed} from './types.ts';

export type {BriefModel};

/** The region's daily feed once loaded; null before, or when it failed its identity check. */
export const dailyFeed = signal<RegionalDailyFeed | null>(null);

/** Load the daily feed for region `id`; a failed fetch or a feed for another region leaves the brief empty. */
export async function loadDailyFeed(id: string, fetchFn: typeof fetch = fetch): Promise<RegionalDailyFeed | null> {
  try {
    const response = await fetchFn(feedPath(undefined, id));
    const json = response.ok ? await response.json() as Partial<RegionalDailyFeed> & {schema_version?: number} : null;
    const ok = json?.schema_version === 1 && json.region_id === id && !!json.sources && typeof json.sources === 'object';
    dailyFeed.value = ok ? json as RegionalDailyFeed : null;
  } catch { dailyFeed.value = null; }
  return dailyFeed.peek();
}

export type BriefSources = {info: RegionInfo | null; feed: RegionalDailyFeed | null; coast: {report: Report; areaId: string} | null; profile: Profile; hour: string | null};

/** The brief for these sources at `now`, or null when the region's feed is not in hand. */
export function briefFrom({info, feed, coast, profile: p, hour: at}: BriefSources, now: Date): BriefModel | null {
  if (!info || !feed || feed.region_id !== info.id) return null;
  const pivot = at && Number.isFinite(Date.parse(at)) ? at : undefined;
  const date = dateKey(new Date(pivot ?? now), info.timezone);
  try {
    const county = coast ? counties[coast.report.countyId] : undefined;
    if (coast && county) return buildCoastBrief({report: coast.report, county, areaId: coast.areaId, profile: p, date, now, at: pivot, reports: feed.reports ?? [], port: info.name});
    const [lat, lon] = info.center;
    return buildRegionalBrief({daily: feed, forecast: null, place: {id: info.id, name: info.name, lat, lon, timezone: info.timezone, port: info.name}, profile: p, date, now, at: pivot});
  } catch { return null; }
}

/** The brief the shell shows now, read from the signals so a component re-renders when they change. */
export function currentBrief(now: Date): BriefModel | null {
  const report = coastReport.value, binding = coastBinding.value;
  return briefFrom({info: regionInfo.value, feed: dailyFeed.value, coast: report && binding ? {report: report.data, areaId: binding.areaId} : null, profile: profile.value, hour: hour.value}, now);
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
  return (
    <p class="app-window">
      <span class="ui-eyebrow">Lower exposure</span>{' '}
      {w ? <><span class="ui-mono">{clock(w.start, tz)}–{clock(w.end, tz)}</span> · {w.label}. {w.reasons[0] ?? ''}</> : 'No lower-exposure window screened for this day.'}
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
