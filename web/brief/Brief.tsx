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
import {createVerdictLoad, type ForecastSlot, type InputSet, type Source, type VerdictContext, type VerdictEpoch} from './verdict-load.ts';
import type {ComponentChildren} from 'preact';
import {batch, effect, signal} from '@preact/signals';
import {counties} from '../../packages/coast/src/counties.ts';
import {dateKey} from '../../packages/coast/src/daily.ts';
import type {Report} from '../../packages/coast/src/types.ts';
import {coastBinding, coastData, coastReport, coastStatus, type CoastData} from '../coast-data.ts';
import type {CoastReportContext} from '../../packages/coast/src/state/report-binding.ts';
import {briefForecast, loadConditionsForecast, type ConditionsForecast, type ForecastFailureReason, type ForecastLoadResult} from '../conditions.ts';
import {feedPath} from '../landing/readings.ts';
import {responseProvenance} from '../offline-response.ts';
import {PROFILE_TABLE, type Profile} from '../profile.ts';
import {day, hour, hourParam, parseHour, port, profile, region, species} from '../state.ts';
import {dockTime, horizonDays} from '../hour.ts';
import {loadRegs, regsData, regulationState, ruleSummary} from '../regs.ts';
import {useEffect} from 'preact/hooks';
import {hasOwnLimits, limitsFor, type ComfortLimits} from '../limits.ts';
import {regionInfo, type RegionInfo} from '../app/region-info.ts';
import {Popover} from '../ui/Popover.tsx';
import {Button} from '../ui/Button.tsx';
import {buildCoastBrief, buildRegionalBrief} from './model.ts';
import {Tiles} from './Tiles.tsx';
import {sourceGapText} from './tile-copy.ts';
import {TideStationControl} from './TideStationControl.tsx';
import {tideSelection} from '../tide-selection.ts';
import {withTideSelection} from '../tide-stations.ts';
import {briefVerdict, clockText, feedReader, type BriefVerdict} from './verdict.ts';
import {loadSkill, skillFile, skillLine, skillSummary} from './skill.ts';
import {activeBoatFactors, savedBoat} from '../../dist/boat-handling.js';
import {boatBasisName, boatRangeNote, REFERENCE_BOAT_NAME, type SavedBoatLike} from '../boat-range.ts';
import {language, localeOf, num, shortDate, t, type Language, type StringId} from '../i18n.ts';
import {boatSaved} from '../boat-entry.ts';
import type {BoatFactors} from '../score.ts';
import type {Brief as BriefModel, RegionalDailyFeed} from './types.ts';
import {DEFAULT_ZONE} from '../zone.ts';
import {dockPending} from '../dock-selection.ts';
import {dailyPartPath} from '../../dist/offline-core.js';
import './brief-print.css';
import {validDailyPart} from '../map/habitat.ts';
import {browserStore, displayedForecast, displayedRegion, readSaved, savedLine, writeSaved, type SavedRegion, type SavedState, type SavedStore} from './saved-brief.ts';

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

/**
 * SC1722-02: the weather answer's own admission (web/brief/verdict-load.ts). Each producer below reports its outcome under the ticket
 * it was asked with; the verdict surfaces read only a sealed source snapshot (verdictPresentation). The raw signals keep serving tiles and exports.
 */
export const verdictEpoch = signal<VerdictEpoch | null>(null);
export const verdictLoad = createVerdictLoad(epoch => { verdictEpoch.value = epoch; });
/** The saved brief restored for the selected region, copied whole (with its own times) before any live part can mix with it. */
const savedAnswer = signal<{region: string; inputs: InputSet; at: number} | null>(null);
/** Own the load of region `id` (null clears it): a new region is a new epoch with every source pending, and withdraws the saved answer. */
export function beginVerdictRegion(id: string | null): void {
  if ((verdictLoad.peek()?.region ?? null) === id) return;
  savedAnswer.value = null;
  if (id) verdictLoad.start(id); else verdictLoad.reset();
}
/** Region `id`'s metadata could not be read: its context (forecast point, coast binding) can never be known, so those end failed. */
export function failVerdictMetadata(id: string): void {
  const epoch = verdictLoad.peek();
  if (epoch?.region !== id) return;
  for (const source of ['metadata', 'forecast', 'coast'] as const) verdictLoad.settle(epoch.tickets[source], source, {state: 'failed'});
}
/** Ask `sources` of region `id` again; the returned ticket is the only one that can settle them. */
function askSources(id: string, sources: readonly Source[], context: Partial<VerdictContext> = {}): number {
  beginVerdictRegion(id);
  return verdictLoad.request(sources, context);
}

// SC-PERF-INSTANT-1: the last brief that loaded, kept on this device (web/brief/saved-brief.ts) and shown at once on the
// next visit while the feeds are read again. `held` says which parts on screen are still the saved ones and when each was
// fetched; the brief is rebuilt from them, so the stale rules apply as to live data. Off until the app calls enableSavedBrief.
// SC1722-03: `pack` marks a part the saved offline pack answered (X-SC-Offline): held as saved at the pack's own save time, never fresh.
interface HeldPart {at: number; saved: boolean; failed: boolean; pack?: boolean}
const held: {region: string | null; daily: HeldPart | null; forecast: HeldPart | null} = {region: null, daily: null, forecast: null};
let savedStore: SavedStore | null | undefined;
/** After this long a saved brief that has not been replaced says the update failed (a weak signal can hang a read). */
export const SAVED_SETTLE_MS = 20_000;
/** Set while any part on screen is the saved one: the oldest saved part's fetch time and whether the update is running or failed; null otherwise. */
export const savedBrief = signal<{at: number; state: SavedState} | null>(null);

/**
 * The minimal region metadata (id, name, centre, zone) restored from the saved brief. The brief cannot be rebuilt without it, and
 * regions/<id>/region.json is a network read, so on a fresh page it stands in until that read publishes regionInfo, which then wins.
 */
export const savedRegion = signal<RegionInfo | null>(null);
/** The region the brief is built for: the real one once read, else the one restored from the device. */
export const shownRegion = (): RegionInfo | null => {
  const id = region.value, real = regionInfo.value, saved = savedRegion.value;
  if (real) return real;
  return saved && (!id || saved.id === id) ? saved : null;
};
// Selecting another region withdraws the restored brief of the old one: its metadata, feeds and "last updated" line must not
// stand in for the new selection while the new region.json is delayed or fails.
effect(() => {
  const id = region.value;
  if (!id || held.region === null || held.region === id) return;
  if (held.daily?.saved) dailyFeed.value = null;
  if (held.forecast?.saved) regionalForecast.value = null;
  held.region = null; held.daily = held.forecast = null;
  savedRegion.value = null;
  savedBrief.value = null;
});

/** Turn on keeping and showing the last brief on this device; `store` is the browser's by default, null when there is none. */
export function enableSavedBrief(store: SavedStore | null = browserStore()): void { savedStore = store; }

function publishSaved(): void {
  const parts = [held.daily, held.forecast].filter((p): p is HeldPart => !!p?.saved);
  savedBrief.value = parts.length ? {at: Math.min(...parts.map(p => p.at)), state: parts.some(p => p.failed) ? 'failed' : parts.some(p => p.pack) ? 'offline' : 'updating'} : null;
}
function markFresh(part: 'daily' | 'forecast', id: string): void {
  if (held.region !== id) { held.region = id; held.daily = held.forecast = null; }
  held[part] = {at: Date.now(), saved: false, failed: false};
  publishSaved();
}
/** SC1722-03: the part came from the saved offline pack: held as saved at the pack's save time (not now), and never written back as a new saved brief. */
function markPack(part: 'daily' | 'forecast', id: string, at: number): void {
  if (held.region !== id) { held.region = id; held.daily = held.forecast = null; }
  held[part] = {at, saved: true, failed: false, pack: true};
  publishSaved();
}
function persistSaved(id: string): void {
  const feed = dailyFeed.peek(), forecast = regionalForecast.peek();
  if (!savedStore || held.region !== id || !held.daily || feed?.region_id !== id) return;
  // A saved part on screen (the restored one or the pack's) is never renewed by a write: the stored entry keeps its own times until network data has replaced them.
  if (held.daily.saved || held.forecast?.saved) return;
  const info = regionInfo.peek(), shown = savedRegion.peek();
  const region: SavedRegion | null = info?.id === id ? displayedRegion(info) : shown?.id === id ? displayedRegion(shown) : null;
  writeSaved(savedStore, id, {at: held.daily.at, data: feed},
    held.forecast && forecast?.region === id ? {at: held.forecast.at, data: displayedForecast(forecast)} : null, region);
}
/** Once the region's own metadata has been read, keep it with the saved brief (the daily feed may have been saved before it arrived). */
export function noteRegionInfo(id: string): void {
  const info = regionInfo.peek();
  if (info?.id !== id) return;
  beginVerdictRegion(id);
  const epoch = verdictLoad.peek()!;
  if (epoch.inputs.metadata.data !== info) {
    const ticket = epoch.inputs.metadata.state === 'pending' ? epoch.tickets.metadata : verdictLoad.request(['metadata']);
    verdictLoad.settle(ticket, 'metadata', {state: 'loaded', data: info});
  }
  if (savedRegion.peek()?.id !== id) persistSaved(id);
}

/**
 * Show the saved brief for `id` before anything is read, when this device has one for that region and nothing is on screen yet.
 * Returns whether it did; the caller then reads the feeds as usual (needsDailyLoad) and they replace it.
 */
export function showSavedBrief(id: string, now = Date.now()): boolean {
  if (savedStore === undefined || dailyFeed.peek()) return false;
  const entry = readSaved(savedStore, id, now);
  if (!entry?.daily) return false;
  if (entry.region_info && !regionInfo.peek()) savedRegion.value = {id, ...entry.region_info};
  beginVerdictRegion(id);
  const info = entry.region_info ? {id, ...entry.region_info} : regionInfo.peek();
  if (info?.id === id && entry.forecast) savedAnswer.value = {region: id, at: Math.min(entry.daily.at, entry.forecast.at), inputs: {
    metadata: {state: 'loaded', data: info}, daily: {state: 'loaded', data: {feed: entry.daily.data, savedAt: entry.daily.at}},
    conditions: {state: 'absent'}, forecast: {state: 'loaded', data: {forecast: entry.forecast.data, savedAt: entry.forecast.at}}, coast: {state: 'absent'},
  }};
  held.region = id;
  held.daily = {at: entry.daily.at, saved: true, failed: false};
  held.forecast = entry.forecast ? {at: entry.forecast.at, saved: true, failed: false} : null;
  dailyFeed.value = entry.daily.data;
  if (entry.forecast) regionalForecast.value = entry.forecast.data;
  publishSaved();
  const settle = setTimeout(() => {
    if (held.region !== id) return;
    for (const part of [held.daily, held.forecast]) if (part?.saved && !part.pack) part.failed = true; // a pack answer that arrived meanwhile is not a failure
    publishSaved();
  }, SAVED_SETTLE_MS) as unknown as {unref?: () => void};
  settle.unref?.(); // Node tests must not wait for it; browsers have no unref
  return true;
}

/** True when region `id` has no daily feed on screen yet, or only the restored one that has not been replaced; a pack answer is a completed read, tried again on the visible-page cadence. */
export const needsDailyLoad = (id: string): boolean => dailyFeed.peek()?.region_id !== id || (held.region === id && !!held.daily?.saved && !held.daily.pack && !dailyPending) || feedsUnasked(id);
/** SC1722-02: region `id`'s current epoch still waits on a feed that no running read will settle (A -> B -> A restarts it while the raw cached feed is still A's). */
const feedsUnasked = (id: string): boolean => {
  const epoch = verdictLoad.peek();
  return epoch?.region === id && (epoch.inputs.daily.state === 'pending' || epoch.inputs.conditions.state === 'pending') && !(dailyPending && dailyRequest?.id === id);
};

export const FEED_GAP = {both: t('brief.gap.both'), daily: t('brief.gap.daily').replace(/\.$/, ''), conditions: t('brief.gap.conditions')} as const;

/** A feed-gap line (kept in English in feedGaps, which the tests compare) in `lang`: each is one of the catalogue's English gap sentences. */
const GAP_IDS: readonly StringId[] = ['brief.gap.both', 'brief.gap.daily', 'brief.gap.daily.tide', 'brief.gap.daily.alerts', 'brief.gap.daily.both', 'brief.gap.conditions'];
const gapText = (text: string, lang: Language): string => { const id = GAP_IDS.find(i => t(i) === text); return id ? t(id, lang) : text; };

/** SC1722-03: a feed read that was admitted, with the saved offline pack's save time (epoch ms) when the answer carried X-SC-Offline, else null (network). */
interface FeedRead {feed: RegionalDailyFeed; savedAt: number | null}

async function readFeed(path: string, id: string, fetchFn: typeof fetch): Promise<FeedRead | null> {
  try {
    const response = await fetchFn(path);
    const json = response.ok ? await response.json() as Partial<RegionalDailyFeed> & {schema_version?: number} : null;
    if (!(json?.schema_version === 1 && json.region_id === id && !!json.sources && typeof json.sources === 'object')) return null;
    // The mark is read once the feed is admitted; a mark that is not a usable time never reads as a network answer.
    const origin = responseProvenance(response.headers, Date.now());
    return origin.kind === 'invalid' ? null : {feed: json as RegionalDailyFeed, savedAt: origin.kind === 'saved' ? origin.at : null};
  } catch { return null; }
}

/**
 * SC2222-03: the daily feed's 'brief' part from /api/daily (about a sixth of the whole feed), with the same
 * identity checks; the whole feed is read once only when the part fails and load `load` is still the latest.
 * Only the reply that is admitted counts for provenance, never a rejected part's.
 */
async function readDaily(id: string, fetchFn: typeof fetch, load: number): Promise<FeedRead | null> {
  const part = await readFeed(dailyPartPath(id, 'brief'), id, fetchFn);
  if (part && validDailyPart(part.feed as unknown as Record<string, unknown>, 'brief', id)) return part;
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
/** SC1922-08: the region the coast client's place was last bound for; it trails the selection until that region's metadata is read. */
let coastPlaceRegion: string | null = null;
/** SC1922-08: the feeds a pressed refresh read, for the next readFeeds to admit (daily, conditions). */
let pressedFeeds: [FeedRead | null, FeedRead | null] | null = null;

async function readFeeds(id: string, fetchFn: typeof fetch, refresh: boolean): Promise<RegionalDailyFeed | null> {
  const before = verdictLoad.peek()?.region === id ? verdictLoad.peek()!.inputs : null, ticket = askSources(id, ['daily', 'conditions']);
  const load = ++feedLoad;
  dailyRequest = {id, fetchFn};
  dailyPending = true;
  bindVisibility();
  if (!refresh) feedGaps.value = [];
  // SC1722-02: each feed reports to the verdict on its own completion; a failed refresh waits for its partner (below).
  const report = (source: 'daily' | 'conditions') => (read: FeedRead | null): FeedRead | null => {
    if (read || !refresh) verdictLoad.settle(ticket, source, read ? {state: 'loaded', data: read} : {state: 'failed'});
    return read;
  };
  // SC1922-08: a pressed refresh has read the feeds itself and hands them in here, to be admitted as an ordinary load admits its reads.
  const pressed = pressedFeeds; pressedFeeds = null;
  const [dailyRead, conditionsRead] = pressed ? [report('daily')(pressed[0]), report('conditions')(pressed[1])] : await Promise.all([readDaily(id, fetchFn, load).then(report('daily')), readFeed(feedPath(undefined, id), id, fetchFn).then(report('conditions'))]);
  // A refresh that read neither keeps the feeds already admitted, as the brief keeps them on screen; one that read one drops the other's.
  for (const source of ['daily', 'conditions'] as const) verdictLoad.settle(ticket, source, {state: 'failed', ...(!dailyRead && !conditionsRead && before?.[source].data ? {data: before[source].data} : {})});
  const daily = dailyRead?.feed ?? null, conditions = conditionsRead?.feed ?? null;
  // A later load (another region) owns the feed and its gap lines; this one only returns what it read.
  if (load !== feedLoad) return mergeFeeds(daily, conditions);
  dailyPending = false;
  // A saved daily feed on screen stands in for a daily read that failed (shown as such), never for a fresh one.
  const savedDaily = !daily && held.region === id && held.daily?.saved && dailyFeed.peek()?.region_id === id ? dailyFeed.peek() : null;
  if (savedDaily) { held.daily!.failed = true; publishSaved(); }
  if (savedDaily && !conditions) return savedDaily;
  // A refresh that read neither keeps the feed and gap lines shown (readings carry their own times) and its old
  // read time, so the next visible page tries again.
  if (refresh && !daily && !conditions) return dailyFeed.peek();
  const base = daily ?? savedDaily;
  dailyLoadedAt = daily ? Date.now() : 0;
  feedGaps.value = !base && !conditions ? [FEED_GAP.both] : !base ? [dailyGap(conditions!)] : !conditions ? [FEED_GAP.conditions] : [];
  dailyFeed.value = mergeFeeds(base, conditions);
  // SC1722-03: an admitted feed that came from the saved offline pack makes the combined daily part saved at the oldest such time
  // (the buoy feed too: it overrides the daily's observations), never fresh and never stored as a new saved brief.
  const packTimes = [dailyRead?.savedAt, conditionsRead?.savedAt].filter((at): at is number => typeof at === 'number');
  if (packTimes.length) {
    if (savedDaily && held.daily) { held.daily.at = Math.min(held.daily.at, ...packTimes); publishSaved(); } // the restored part stands, from its older of the two times
    else markPack('daily', id, Math.min(...packTimes));
  } else if (daily) { markFresh('daily', id); persistSaved(id); }
  return dailyFeed.peek();
}

/**
 * Ask the coast data client for the report wherever `place` binds one, whichever layers are on (the
 * Swell and Water temp layers ask for the same place; the client requests once per place).
 */
export function bindBriefReport(place: () => CoastReportContext | null, data: Pick<CoastData, 'setPlace' | 'load' | 'coastReport'> = coastData): () => void {
  return effect(() => {
    const p = place();
    if (!p) return; // until the region's metadata is read its coast binding is unknown: the coast part stays pending, never absent
    const binding = data.setPlace(p);
    coastPlaceRegion = p.regionId; // SC1922-08: the region the client's current place (and so a refresh of its report) belongs to
    const key = `${p.regionId}:${binding?.areaId ?? ''}`, load = data.load('report');
    // SC1722-02: a binding asks the verdict's coast part under its own ticket. The same binding already asked waits on that ask; a
    // different one is a new context, so a completion captured for the earlier binding can no longer settle it.
    beginVerdictRegion(p.regionId);
    const epoch = verdictLoad.peek()!;
    if (epoch.parts.coast === key) return;
    const ticket = verdictLoad.request(['coast'], {coast: key});
    if (!binding) { verdictLoad.settle(ticket, 'coast', {state: 'absent'}); return; }
    const settle = (): void => {
      const snapshot = data.coastReport.peek();
      verdictLoad.settle(ticket, 'coast', snapshot ? {state: 'loaded', data: {snapshot, areaId: binding.areaId}} : {state: 'failed'});
    };
    void load.then(settle, settle);
  });
}

/** The region's forecast feed at its chosen point once loaded; null before, when it failed, or for another region. regionalForecastState says which. */
export const regionalForecast = signal<ConditionsForecast | null>(null);

/**
 * SC1722-01: how the forecast read for `region`/`key` stands, beside the unchanged data signal above. `reason` and `status` are codes,
 * never text (the page's language words them); `loading` keeps the reason of the failure being retried. `generation` counts real new
 * requests, so a result that is not the latest request's is ignored.
 */
export interface ForecastState {region: string | null; key: string | null; generation: number; state: 'absent' | 'loading' | 'loaded' | 'failed'; reason?: ForecastFailureReason; status?: number}
export const regionalForecastState = signal<ForecastState>({region: null, key: null, generation: 0, state: 'absent'});

let forecastKey: string | null = null;
let forecastRequest: {id: string; near: readonly [number, number] | null; fetchFn: typeof fetch; page: string} | null = null;
let forecastSlot: ForecastSlot | null = null, forecastJoiners: number[] = [];
let forecastLoadedAt = 0, forecastPending = false, forecastGeneration = 0, forecastInflight: Promise<ConditionsForecast | null> | null = null, visibilityBound = false;
/** A loaded forecast older than this is fetched again when the page becomes visible. */
export const FORECAST_MAX_AGE_MS = 30 * 60_000;
/** SC1922-08: the forecast a pressed refresh read, for the next ensureRegionalForecast to admit. */
let pressedForecast: ForecastLoadResult | null = null;

/**
 * Load the forecast for region `id` at the point nearest `near`, once per region and point; the brief and the Conditions view share it.
 * A call while that read is pending joins it. A failed read is recorded in regionalForecastState and tried again on the next call.
 */
export function ensureRegionalForecast(id: string, near: readonly [number, number] | null, fetchFn: typeof fetch = fetch, page = location.href): Promise<ConditionsForecast | null> {
  const key = `${id}|${near?.join(',') ?? ''}`;
  bindVisibility();
  if (forecastKey === key) {
    // SC1722-02: a reused read (cached or in flight) still has to answer the epoch now current. After A -> B -> A the epoch restarted with the
    // forecast pending and the read's own ticket is stale, so the epoch asks again under a fresh ticket that only this reused read settles.
    const epoch = verdictLoad.peek();
    if (epoch?.region !== id || epoch.parts.forecast !== key) {
      const joined = askSources(id, ['forecast'], {forecast: key});
      if (forecastSlot) verdictLoad.settle(joined, 'forecast', forecastSlot); else forecastJoiners.push(joined);
    }
    return forecastInflight ?? Promise.resolve(regionalForecast.peek());
  }
  const ticket = askSources(id, ['forecast'], {forecast: key});
  forecastSlot = null; forecastJoiners = [];
  forecastKey = key;
  forecastRequest = {id, near, fetchFn, page};
  forecastPending = true;
  const generation = ++forecastGeneration, before = regionalForecastState.peek();
  batch(() => {
    if (regionalForecast.peek()?.region !== id) regionalForecast.value = null;
    const retried = before.state === 'failed' && before.region === id ? {reason: before.reason, ...(before.status === undefined ? {} : {status: before.status})} : {};
    regionalForecastState.value = {region: id, key, generation, state: 'loading', ...retried};
  });
  const pressed = pressedForecast; pressedForecast = null; // SC1922-08: a pressed refresh read the forecast itself and hands it in to be admitted as an ordinary read is
  const read = (pressed ? Promise.resolve(pressed) : loadConditionsForecast(id, near, fetchFn, page)).then(result => {
    if (generation !== forecastGeneration) return regionalForecast.peek(); // a later request (even for this same key) owns the state
    // SC1722-02: the verdict's forecast part, under this request's ticket (-01's result, unchanged; absent is no request, not a failure).
    const slot: ForecastSlot = result.state === 'loaded' ? {state: 'loaded', data: {forecast: result.forecast, savedAt: result.savedAt}}
      : result.state === 'failed' ? {state: 'failed', reason: result.reason, ...(result.status === undefined ? {} : {status: result.status})} : {state: 'absent'};
    verdictLoad.settle(ticket, 'forecast', slot);
    // Reads that joined this one after an epoch restart settle under their own tickets; a loaded outcome stays for later reuse.
    for (const joined of forecastJoiners) verdictLoad.settle(joined, 'forecast', slot);
    forecastJoiners = []; forecastSlot = result.state === 'loaded' ? slot : null;
    forecastPending = false; forecastInflight = null;
    if (result.state !== 'loaded') {
      forecastKey = null; // a failed load is tried again on the next call
      const failed: ForecastState = result.state === 'failed' ? {region: id, key, generation, state: 'failed', reason: result.reason, ...(result.status === undefined ? {} : {status: result.status})} : {region: id, key, generation, state: 'absent'};
      if (held.region === id && held.forecast?.saved && regionalForecast.peek()?.region === id) {
        // The saved forecast stays on screen, said to be the saved one; read again on the next call or visible page.
        held.forecast.failed = true; publishSaved();
        forecastLoadedAt = 0;
        regionalForecastState.value = failed;
        return regionalForecast.peek();
      }
      forecastLoadedAt = 0; // a failure never renews freshness
      batch(() => { regionalForecast.value = null; regionalForecastState.value = failed; });
      return null;
    }
    batch(() => { regionalForecast.value = result.forecast; regionalForecastState.value = {region: id, key, generation, state: 'loaded'}; });
    forecastLoadedAt = Date.now(); // the read's completion for the visible-page cadence; a pack answer's own (older) time is only the held clock below
    if (result.savedAt !== null) markPack('forecast', id, result.savedAt);
    else { markFresh('forecast', id); persistSaved(id); }
    return result.forecast;
  });
  forecastInflight = read;
  return read;
}

/** True when the current epoch gave up on the forecast at its deadline: the read the loader still has in flight no longer answers it. */
const forecastTimedOut = (): boolean => verdictLoad.peek()?.inputs.forecast.state === 'timedout';

/** SC1722-01: read the forecast again after a failure with the request it last made: joins a read in flight, else asks once more. Null when no forecast was ever asked for. */
export function retryRegionalForecast(): Promise<ConditionsForecast | null> | null {
  const req = forecastRequest, selected = region.peek();
  // SC1722-02: only the selected region's own request is read again; an earlier region's would switch the epoch off the selection.
  if (!req || (selected && selected !== req.id)) return null;
  // A read still in flight when its epoch sealed as timed out answers nothing now (the sealed epoch never admits it): Try again starts
  // a new request, hence a new generation and deadline, and the old read's late result is ignored by the loader's generation check.
  if (forecastPending && forecastInflight && !forecastTimedOut()) return forecastInflight;
  forecastKey = null;
  return ensureRegionalForecast(req.id, req.near, req.fetchFn, req.page);
}

/** SC1922-08: where a pressed refresh stands. A code, never text; the chip words it in the page's language. */
export type ManualRefreshState = 'idle' | 'refreshing' | 'offline' | 'failed';
export const manualRefresh = signal('idle' as ManualRefreshState);
let manualRun: Promise<void> | null = null;
// Selecting another region ends the press in progress: its replies belong to the old region and must neither say anything about the new
// one nor change what it shows, and a word left by an earlier press (failed, offline) is about the old region too.
effect(() => {
  void region.value;
  manualRun = null;
  manualRefresh.value = 'idle';
});
// Back online, "Offline" said by a refused press is out of date.
if (typeof window !== 'undefined') window.addEventListener('online', () => { if (manualRefresh.peek() === 'offline') manualRefresh.value = 'idle'; });

/**
 * The freshness chip's Refresh: ask the forecast, the daily feeds and the coast report again, once per press. A press during a press, or
 * while any of those reads is already under way, asks nothing more. Offline asks nothing and says so (manualRefresh 'offline'). The press
 * reads the forecast and feeds without showing them, asks the coast report only once those answered, and shows the new forecast and feeds
 * (through their own loaders) only when the coast report answered too; if any source failed the brief stays exactly as it was and the
 * press says so (manualRefresh 'failed'); it is never read as a verdict. No timer, no retry.
 */
export function refreshBriefNow(online: () => boolean = () => globalThis.navigator?.onLine !== false): Promise<void> {
  if (manualRun) return manualRun;
  if (!online()) { manualRefresh.value = 'offline'; return Promise.resolve(); }
  if (forecastPending || dailyPending || coastStatus.peek().report === 'loading') return Promise.resolve();
  // Each source's captured request must be the selected region's own: until that region's reads have begun they are still the previous
  // region's, and a press then asks nothing (it never borrows them, nor refreshes the previous place's report).
  const selected = region.peek(), fc = forecastRequest, df = dailyRequest;
  if (!selected || (fc && fc.id !== selected) || (df && df.id !== selected) || (coastBinding.peek() && coastPlaceRegion !== selected)) return Promise.resolve();
  manualRefresh.value = 'refreshing';
  let run!: Promise<void>; // the async body below compares manualRun with it after its first await
  run = manualRun = (async () => {
    let ok = false;
    try {
      const [forecast, feeds] = await Promise.all([fc && loadConditionsForecast(fc.id, fc.near, fc.fetchFn, fc.page), df && Promise.all([readDaily(df.id, df.fetchFn, feedLoad), readFeed(feedPath(undefined, df.id), df.id, df.fetchFn)])]);
      ok = forecast?.state !== 'failed' && !feeds?.includes(null);
      if (ok && manualRun === run && coastBinding.peek()) {
        // Only a reply the client admitted counts: an expired, invalid or older one leaves the held snapshot (and its 'ready') as it was.
        const held = coastReport.peek();
        await coastData.refresh('report');
        ok = coastStatus.peek().report === 'ready' && coastReport.peek() !== held && coastReport.peek() !== null;
      }
      if (ok && manualRun === run) {
        if (forecast) { pressedForecast = forecast; forecastKey = null; void ensureRegionalForecast(fc!.id, fc!.near, fc!.fetchFn, fc!.page); }
        if (feeds) { pressedFeeds = feeds; void readFeeds(df!.id, df!.fetchFn, true); }
      }
    } catch { ok = false; } // a press that threw failed
    if (manualRun !== run) return; // another region was selected meanwhile: this press says nothing about it
    manualRun = null;
    manualRefresh.value = ok ? 'idle' : 'failed';
  })();
  return run;
}

/** Reload the forecast when it failed or was loaded over 30 minutes before `now`; no timer, only called as the page becomes visible. */
export function refreshForecastIfStale(now = Date.now()): Promise<ConditionsForecast | null> | null {
  const req = forecastRequest, selected = region.peek();
  if (!req || forecastPending || (selected && selected !== req.id)) return null;
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
  const brief = briefFrom({info: shownRegion(), feed: dailyFeed.value, forecast: regionalForecast.value, coast: report && binding ? {report: report.data, areaId: binding.areaId} : null, profile: profile.value, hour: at,
    limits: hasOwnLimits(profile.value) ? limitsFor(profile.value) : null}, now);
  const chosen = tideSelection.choice.value, config = tideSelection.region.value;
  if (!brief || !chosen || !config || config.id !== shownRegion()?.id || chosen === config.station) return brief;
  const station = tideSelection.stations.value.find(s => s.id === chosen) ?? {id: chosen, name: chosen};
  return withTideSelection(brief, station, tideSelection.reading.value, shownRegion()!.timezone, now, at);
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

/**
 * SC-PERF-INSTANT-1: while any part of the brief on screen is still the saved one, when this device fetched it and whether it
 * is updating or the update failed. Amber when that is past the brief's own limit (verdict.ts RUN_STALE_MS) or a reading on
 * screen is stale; the brief itself, rebuilt from the saved inputs, labels its aged readings as it does for live data.
 */
export function SavedLine({now, snapshot}: {now: Date; snapshot?: VerdictPresentation}) {
  const s = snapshot ? snapshot.saved : savedBrief.value;
  if (!s) return null;
  const tz = (snapshot?.info ?? shownRegion())?.timezone ?? DEFAULT_ZONE, lang = language.value;
  const stale = !!(snapshot ? snapshot.brief : leadBrief(now))?.tiles.some(tile => tile.state === 'stale' || tile.lastGood);
  const line = savedLine(s.at, now.getTime(), s.state, stale, tz, lang);
  return <p class="app-saved ui-mono" role="status" data-saved={s.state} data-stale={line.amber ? 'true' : undefined}>{line.text}</p>;
}

/** The brief the lead answers from: the dock's brief once a time is chosen, else tomorrow's. */
export function leadBrief(now: Date): BriefModel | null {
  return currentBrief(now, leadHour(hour.value, day.value, now, shownRegion()?.timezone ?? DEFAULT_ZONE));
}

/** The day ("YYYY-MM-DD") the lead answers for: its brief's date, else the day of its hour. */
export function leadDate(now: Date, brief: BriefModel | null = leadBrief(now)): string {
  const tz = shownRegion()?.timezone ?? DEFAULT_ZONE, at = leadHour(hour.value, day.value, now, tz);
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

/** The day verdict for the brief shown now: the regional forecast only when it is this region's, rated for the saved boat (MYB-2); its reason sentences are in `lang` (the page's by default). */
export function currentVerdict(brief: BriefModel | null, now: Date, lang: Language = language.value): BriefVerdict | null {
  const info = shownRegion(), forecast = regionalForecast.value;
  void boatSaved.value;   // a boat saved on first use (boat-entry.ts) re-rates the verdict on screen
  return briefVerdict(brief, info && forecast?.region === info.id ? forecast : null, now, info?.timezone ?? DEFAULT_ZONE, activeBoatFactors() as BoatFactors, lang);
}

/**
 * SC1722-02: what every weather-answer surface (the brief's Verdict, the first answer, the day chips) answers from. `pending`: no word
 * yet (Updating); `failed`: the forecast could not be read and nothing saved stands in (ForecastFailure); `saved`: the saved brief's own
 * snapshot or the offline pack's, with its SavedLine clocks; `live`: a sealed epoch's snapshot. The brief and verdict are built from the
 * one selected snapshot, never from live parts mixed with saved ones.
 */
export type VerdictPresentation = {state: 'pending' | 'failed' | 'saved' | 'live'; brief: BriefModel | null; verdict: BriefVerdict | null; info: RegionInfo | null; forecast: ConditionsForecast | null;
  saved: {at: number; state: SavedState} | null; forecastFailed: boolean; reason?: ForecastFailureReason; status?: number};
type Selected = {state: VerdictPresentation['state']; inputs: InputSet | null; restored: boolean; forecastFailed: boolean; reason?: ForecastFailureReason; status?: number};
const forecastDown = (inputs: InputSet): boolean => inputs.forecast.state === 'failed' || inputs.forecast.state === 'timedout';
/** Metadata and at least one feed in hand: the brief could be built, so only the forecast stands between it and an answer. */
const couldAnswer = (inputs: InputSet): boolean => !!inputs.metadata.data && !!(inputs.daily.data || inputs.conditions.data);
/** A sealed snapshot that can carry a live answer: its forecast was read (or has none to read), with metadata and at least one feed. */
const answers = (epoch: VerdictEpoch | null): boolean => !!epoch?.sealed && !forecastDown(epoch.inputs) && couldAnswer(epoch.inputs);

/** Which snapshot answers now, without building a brief (the guard and the chips read only this). */
function selectSnapshot(): Selected {
  const epoch = verdictEpoch.value, id = region.value, saved = savedAnswer.value;
  if (!epoch || (id && epoch.region !== id)) return {state: 'pending', inputs: null, restored: false, forecastFailed: false};
  // The forecast read's own failure code: the epoch's (a deadline is 'timeout'), else the loader's, which keeps it while a retry runs.
  const raw = regionalForecastState.value, rawFailed = raw.region === epoch.region && (raw.state === 'failed' || (raw.state === 'loading' && !!raw.reason));
  const forecastFailed = forecastDown(epoch.inputs) || rawFailed, slot = epoch.inputs.forecast;
  const code = {reason: slot.reason ?? (rawFailed ? raw.reason : undefined), status: slot.status ?? (rawFailed ? raw.status : undefined)};
  if (answers(epoch)) return {state: 'live', inputs: epoch.inputs, restored: false, forecastFailed: false};
  // While a refresh of the same context runs, the answer it refreshes stands.
  const standing = verdictLoad.published();
  if (!epoch.sealed && standing && answers(standing) && standing.region === epoch.region && standing.context === epoch.context) return {state: 'live', inputs: standing.inputs, restored: false, forecastFailed: false};
  if (saved?.region === epoch.region) return {state: 'saved', inputs: saved.inputs, restored: true, forecastFailed, ...code};
  if (!epoch.sealed) return {state: 'pending', inputs: null, restored: false, forecastFailed: false};
  // A failed forecast replaces the answer only where the metadata and a feed could answer; with no metadata or neither feed read the brief
  // is the existing "Readings unavailable" (never a weather word, never a forecast failure the user cannot act on), as before this gate.
  if (forecastDown(epoch.inputs) && couldAnswer(epoch.inputs)) return {state: 'failed', inputs: null, restored: false, forecastFailed: true, ...code};
  return {state: 'live', inputs: epoch.inputs, restored: false, forecastFailed: false}; // no metadata or feed: the unavailable brief, never a weather word
}

/** The brief and verdict one snapshot gives for the hour `selected` (undefined: the lead's hour). */
function assess(inputs: InputSet, now: Date, at: string | null | undefined, lang: Language) {
  const info = inputs.metadata.data ?? null, tz = info?.timezone ?? DEFAULT_ZONE;
  const forecast = inputs.forecast.data && inputs.forecast.data.forecast.region === info?.id ? inputs.forecast.data.forecast : null; // only this region's, as currentVerdict
  const selected = at === undefined ? leadHour(hour.value, day.value, now, tz) : at, coast = inputs.coast.data;
  let brief = briefFrom({info, forecast, feed: mergeFeeds(inputs.daily.data?.feed ?? null, inputs.conditions.data?.feed ?? null),
    coast: coast && Date.parse(coast.snapshot.expiresAt) > now.getTime() ? {report: coast.snapshot.data, areaId: coast.areaId} : null,
    profile: profile.value, hour: selected, limits: hasOwnLimits(profile.value) ? limitsFor(profile.value) : null}, now);
  // The tide station chosen beside the brief (a choice, not a load) applies as it does to the raw brief.
  const chosen = tideSelection.choice.value, config = tideSelection.region.value;
  if (brief && info && chosen && config?.id === info.id && chosen !== config.station) {
    const station = tideSelection.stations.value.find(st => st.id === chosen) ?? {id: chosen, name: chosen};
    brief = withTideSelection(brief, station, tideSelection.reading.value, tz, now, selected);
  }
  void boatSaved.value; // a boat saved on first use (boat-entry.ts) re-rates the answer
  return {brief, verdict: briefVerdict(brief, forecast, now, tz, activeBoatFactors() as BoatFactors, lang), info, forecast};
}

/** Assess the selected snapshot for the hour `at` (the lead's hour by default; the chips pass theirs, so they never follow scrubbing). */
export function verdictPresentation(now: Date, at?: string | null, lang: Language = language.value): VerdictPresentation {
  const s = selectSnapshot(), base = {brief: null, verdict: null, info: null, forecast: null, saved: null, forecastFailed: s.forecastFailed, reason: s.reason, status: s.status};
  if (!s.inputs) return {...base, state: s.state};
  if (s.restored) {
    const view = assess(s.inputs, now, at, lang), epoch = verdictEpoch.value!;
    if (view.verdict && view.verdict.verdict !== 'unknown') {
      const failed = epoch.sealed || s.forecastFailed || savedBrief.value?.state === 'failed';
      return {...base, ...view, state: 'saved', saved: {at: savedAnswer.value!.at, state: failed ? 'failed' : 'updating'}};
    }
    // A saved snapshot that cannot answer is never a saved Unknown: Updating while live reads run, then the live outcome.
    if (!epoch.sealed) return {...base, state: 'pending'};
    if (forecastDown(epoch.inputs) && couldAnswer(epoch.inputs)) return {...base, state: 'failed'};
    return {...base, ...assess(epoch.inputs, now, at, lang), state: 'live'};
  }
  const view = assess(s.inputs, now, at, lang);
  // SC1722-03: parts the saved offline pack answered are held as saved at the pack's own time, never as fresh.
  const times = packTimes(s.inputs);
  return {...base, ...view, state: times.length ? 'saved' : 'live', saved: times.length ? {at: Math.min(...times), state: 'offline'} : null};
}

/** The save times of the parts of `inputs` the saved offline pack answered (SC1722-03); empty when every part is fresh. */
const packTimes = (inputs: InputSet): number[] => [inputs.daily.data?.savedAt, inputs.conditions.data?.savedAt, inputs.forecast.data?.savedAt].filter((n): n is number => typeof n === 'number');

/** True while no weather word may show: the dock guard's source input (a saved snapshot is assessed only when one stands in). */
export const sourcePending = (now: Date): boolean => { const s = selectSnapshot(); return s.state === 'pending' || (s.restored && verdictPresentation(now).state === 'pending'); };
/** The day chips rate only a live snapshot: pending, failed and saved answers (the saved brief, or parts the offline pack answered) give date-only chips. */
export const chipsAdmitted = (): boolean => { const s = selectSnapshot(); return s.state === 'live' && !!s.inputs && packTimes(s.inputs).length === 0; };

const FORECAST_REASON: Readonly<Record<ForecastFailureReason, StringId>> = {network: 'forecast.reason.network', http: 'forecast.reason.http', invalid: 'forecast.reason.invalid', aborted: 'forecast.reason.aborted', timeout: 'forecast.reason.timeout'};

/** SC1722-01: "Couldn't load the forecast", the plain reason and a Try again that reads the forecast again (busy and disabled while that read runs). `as` is the heading element for the place it sits in. */
export function ForecastFailure({as: Heading = 'h1', failure}: {as?: 'h1' | 'h2' | 'p'; failure?: {reason?: ForecastFailureReason; status?: number}}) {
  // SC1722-02: the presented failure names the code; busy and disabled stay the loader's own (a retry in flight), never the presentation's.
  // A read the epoch gave up on at its deadline is not a retry in flight: Try again stays available and starts a new generation.
  const raw = regionalForecastState.value, lang = language.value, timedOut = verdictEpoch.value?.inputs.forecast.state === 'timedout', busy = raw.state === 'loading' && !timedOut;
  const reason = failure?.reason ?? raw.reason, status = failure?.status ?? raw.status;
  return (
    <div class="app-forecast-failed" role="status" data-forecast="failed" data-reason={reason} aria-busy={busy ? 'true' : undefined}>
      <Heading class="app-forecast-failed-head">{t('forecast.failed', lang)}</Heading>
      <p class="app-forecast-failed-reason">{t(FORECAST_REASON[reason ?? 'network'], lang, {status: status ?? 0})}</p>
      <Button class="app-forecast-retry" disabled={busy} onClick={() => { void retryRegionalForecast(); }}>{t('forecast.retry', lang)}</Button>
    </div>
  );
}

/** The boat the comfort rating names, in `lang`; a saved boat's own name is shown as typed. */
function boatName(boat: SavedBoatLike, lang: Language): string {
  const name = boatBasisName(boat), length = /^your (\d+(?:\.\d+)?) ft boat$/.exec(name);
  return name === REFERENCE_BOAT_NAME ? t('brief.boat.reference', lang) : name === 'your boat' ? t('brief.boat.generic', lang) : length ? t('brief.boat.yours', lang, {n: num(Number(length[1]), lang)}) : name;
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
  const rules = shownRegion()?.rules, lang = language.value;
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
 * SCFEAT-SKILL-1: measured forecast skill under the model-disagreement line (web/brief/skill.ts); UNKNOWN when history is short.
 * SC1407-11: for the lead of the hour `at` the brief answers for (24/48/72 h ahead of now), with a link to the full /skill scorecard.
 */
function SkillLine({now, lang}: {now: Date; lang: Language}) {
  useEffect(() => { loadSkill(); }, []);
  const file = skillFile.value, region = shownRegion();
  if (file === undefined || !region) return null;
  const at = leadHour(hour.value, day.value, now, region.timezone), s = skillSummary(file, region.id, now.getTime(), at ? Date.parse(at) : undefined);
  return <p class="app-verdict-skill ui-mono" data-skill={s.state}>{skillLine(s, lang)} <a href="/skill">{t('brief.details', lang)}</a></p>;
}

/**
 * SC1407-05: while the dock's hour is pending (web/dock-selection.ts), the answer it wraps is the previous
 * hour's, so it is hidden and inert and "Updating…" stands in, unannounced (aria-live off, no role, no focus
 * move). Only this wrapper reads the pending flag: the settled child keeps its vnode and is not re-rendered
 * on entry or exit, and in print the settled answer shows (brief-print.css).
 */
export function DockVerdictGuard({children, now = new Date()}: {children: ComponentChildren; now?: Date}) {
  // SC1722-02: a source load still under way (no sealed answer, no labelled saved one) holds the same single Updating notice. In print the
  // settled slot shows as for the dock; while sources are pending it holds only the waiting headline, never a weather word.
  const pending = dockPending.value || sourcePending(now);
  return (
    <div class="app-hour-guard" aria-busy={pending ? 'true' : undefined} data-pending={pending ? 'true' : undefined}>
      {pending ? <p class="app-hour-updating ui-mono" aria-live="off">{t('dock.updating', language.value)}</p> : null}
      <div class="app-hour-settled" hidden={pending} inert={pending}>{children}</div>
    </div>
  );
}

/**
 * The brief's first lines: the verdict word for the morning window of the lead's day (tomorrow until
 * a time is chosen), the day and window, one sentence naming what limits it with the basis behind a
 * popover, and whether the target is legal that day. A provisional day (packages/coast daily.ts, from
 * the day after tomorrow) says so in the verdict line itself. Before there is a brief, the waiting
 * headline. Guarded while the dock's hour settles (SC1407-05).
 */
export const Verdict = ({now}: {now: Date}) => <DockVerdictGuard now={now}><SettledVerdict now={now} /></DockVerdictGuard>;

/** The verdict for the settled day and hour. */
function SettledVerdict({now}: {now: Date}) {
  const view = verdictPresentation(now), {brief, verdict: v} = view, lang = language.value;
  const tz = view.info?.timezone ?? DEFAULT_ZONE, date = leadDate(now, brief), rulesLine = <LeadRules date={date} now={now} />;
  // Source pending: the guard shows Updating; the hidden settled slot keeps the page's waiting headline, never a weather word.
  if (view.state === 'pending') return <><h1>{t('common.waiting', lang)}</h1>{rulesLine}</>;
  if (view.state === 'failed') return <div class="app-verdict app-verdict-failed"><ForecastFailure failure={view} />{rulesLine}</div>;
  if (!v) return <><h1>{t('brief.unavailable', lang)}</h1>{rulesLine}</>;
  const when = leadDayText(date, now, tz, lang);
  const window = lang === 'es' && v.windowBounds ? v.windowBounds.map(ms => clock(ms, tz, lang)).join('–') : v.window;
  const provisional = !!brief?.provisional;
  const a = v.agreement, gap = (n: number) => num(Number(n.toFixed(1)), lang);
  const models = !a || a.state === 'none' ? null : a.state === 'agree' ? t('brief.models.agree', lang, {until: window?.split('–')[1] ?? '', wind: gap(a.gap!.wind), sea: gap(a.gap!.sea)})
    : a.state === 'differ' ? `${t('brief.models.differ', lang, {at: lang === 'es' ? clock(a.worst!.ms, tz, lang) : clockText(a.worst!.ms, tz), wind: gap(a.worst!.wind), sea: gap(a.worst!.sea)})}${a.differing > 1 ? ` ${t('brief.models.hours', lang, {n: a.differing, total: a.hours})}` : ''}`
    : a.state === 'partial' ? t('brief.models.partial', lang, {n: a.compared, total: a.hours}) : t('brief.models.one', lang);
  const modelHour = a?.state === 'differ' && view.forecast ? feedReader(view.forecast, now).read(a.worst!.ms) : null;
  const boat = v.basis === 'comfort-score' ? storedBoat() : null, rangeNote = boat && boatRangeNote(boat.loa_ft) ? t('brief.boat.note', lang) : null;
  return (
    <div class="app-verdict" data-verdict={v.verdict} data-provisional={provisional ? 'true' : undefined}>
      <div class="app-verdict-head">
        <h1><span class="app-verdict-word">{t(`brief.verdict.${v.verdict}` as StringId, lang)}</span>{' '}<span class="app-verdict-window ui-mono" data-day={date}>{window ? `${when}, ${window}` : when}</span>{provisional ? ' ' : null}{provisional ? <span class="app-verdict-window app-verdict-provisional ui-mono">{t('brief.provisional', lang)}</span> : null}</h1>
        <Popover align="end">{v.basis === 'comfort-score' ? comfortBasis(boat, lang) : t('brief.basis.profile', lang)}{rangeNote ? ` ${rangeNote}` : ''}{provisional ? ` ${t('brief.provisional.basis', lang)}` : ''}{v.score !== null ? ` ${t('brief.worst', lang, {score: num(v.score, lang, 20)})}` : ''}</Popover>
      </div>
      <SavedLine now={now} snapshot={view} />
      {view.state === 'saved' && view.forecastFailed ? <ForecastFailure as="p" failure={view} /> : null}
      <p class="app-verdict-limit">{v.limit}{v.held ? ` ${v.held}` : ''}</p>
      {rangeNote ? <p class="app-verdict-boat-note">{rangeNote}</p> : null}
      {models ? <p class="app-verdict-models ui-mono" data-agreement={a!.state}>{models}</p> : null}
      {modelHour ? <details class="app-verdict-models-detail"><summary>{t('brief.models.detail', lang)}</summary>{t('brief.models.readings', lang, {w1: gap(modelHour.wind!), w2: gap(modelHour.other_wind!), s1: gap(modelHour.sea!), s2: gap(modelHour.other_sea!)})}</details> : null}
      <SkillLine now={now} lang={lang} />
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

const clock = (iso: string | number, tz: string, lang: Language = 'en') => new Intl.DateTimeFormat(localeOf(lang), {hour: 'numeric', minute: '2-digit', timeZone: tz}).format(new Date(iso)).replace(':00', '').toLowerCase();

/** The quietest window the model screened, labelled lower exposure; none is said plainly. */
export function LowerExposure({brief}: {brief: BriefModel | null}) {
  if (!brief) return null;
  const tz = shownRegion()?.timezone ?? DEFAULT_ZONE, w = brief.windows[0], lang = language.value;
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
          {sources.map(gap => <li key={gap.id} data-status={gap.status}>{sourceGapText(gap, lang)}</li>)}
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

const CAVEAT_IDS: Record<Profile, StringId> = {boat: 'brief.caveat.boat', shore: 'brief.caveat.shore', spear: 'brief.caveat.spear', kayak: 'brief.caveat.kayak'};

/** The profile caveat in the chosen language. The model and PROFILE_TABLE keep their English; only a caveat equal to the profile's own table sentence is translated, any other text passes through. */
export const caveatText = (brief: BriefModel | null, lang: Language): string => {
  const p = brief?.profile ?? profile.value, raw = brief?.caveat ?? PROFILE_TABLE[p].caveat;
  return raw === PROFILE_TABLE[p].caveat ? t(CAVEAT_IDS[p], lang) : raw;
};

export const Caveat = ({brief}: {brief: BriefModel | null}) => <p class="app-caveat">{caveatText(brief, language.value)}</p>;

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

/** SC2037-04: when the page was last sent to print (epoch ms); the print block falls back to render time. */
export const printedAt = signal<number | null>(null);

/** Epoch ms -> "Wed 6:05 PM PDT" in the region zone (never the device zone). */
export const printedText = (ms: number, tz: string, lang: Language = 'en'): string =>
  new Intl.DateTimeFormat(localeOf(lang), {weekday: 'short', hour: 'numeric', minute: '2-digit', timeZone: tz, timeZoneName: 'short'}).format(new Date(ms));

/** Open every disclosure in the brief for the printout (a closed one prints nothing), then restore them. */
const opened: HTMLDetailsElement[] = [];
export function beforePrint(now: () => number = Date.now, doc: Document | undefined = typeof document === 'undefined' ? undefined : document): void {
  printedAt.value = now();
  opened.length = 0;
  doc?.querySelectorAll<HTMLDetailsElement>('details:not([open])').forEach(d => { d.open = true; opened.push(d); });
}
export function afterPrint(): void { opened.splice(0).forEach(d => { d.open = false; }); }
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('beforeprint', () => beforePrint());
  window.addEventListener('afterprint', afterPrint);
}

/** The button (screen only) and the print-only block: where and when, the printed-at time, the no-update line. */
export function PrintBrief({now}: {now: Date}) {
  const tz = shownRegion()?.timezone ?? DEFAULT_ZONE, lang = language.value;
  const at = leadHour(hour.value, day.value, now, tz), date = leadDate(now), when = at ? new Date(at) : now;
  const place = [shownRegion()?.name, port.value ? port.value.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ') : null, PROFILE_TABLE[profile.value].label].filter(Boolean).join(' · ');
  return (
    <>
      <Button class="app-print-button" onClick={() => window.print()}>{t('brief.print', lang)}</Button>
      <div class="app-print-only" data-print="brief">
        <p class="app-print-place">{place}</p>
        <p class="app-print-when ui-mono">{leadDayText(date, now, tz, lang)}, {clock(when.getTime(), tz, lang)}</p>
        <p class="app-print-at ui-mono">{t('brief.print.at', lang, {time: printedText(printedAt.value ?? now.getTime(), tz, lang)})}</p>
        <p class="app-print-stale">{t('brief.print.stale', lang)}</p>
      </div>
    </>
  );
}

export const DISCLAIMER = t('brief.disclaimer');

/** The C1 short form of docs/legal/disclaimers.md (item 3, the persistent footer line). */
export const PLANNING_AID = t('brief.planning');

/** The one disclaimer line per page with the planning-aid line, Terms and Sources links; `children` adds links after them. */
export const BriefFooter = ({children}: {children?: ComponentChildren} = {}) =>
  <footer class="app-brief-footer">{t('brief.disclaimer', language.value)} {t('brief.planning', language.value)} <a href="/terms.html">{t('brief.terms', language.value)}</a> · <a href="/sources">{t('brief.sources', language.value)}</a>{children}</footer>;
