// Entry of dist/app.html (FE-05): a v2 store (region changes never reload),
// the address read once and followed on Back/Forward, the width followed for
// the mobile layout (FE-06), the shell rendered into #app, then the region's
// name and zone for the masthead and the dock.
// /map with no region or coast (FE-08, § 7) opens the saved home (a port v1
// or v2 saved, or a /coast place, FE-83), else the landing; the chooser
// itself never opens on its own.
import {render} from 'preact';
import {effect, signal} from '@preact/signals';
import {configureStore, coast, loadCoordinateFormat, profile, region, species, startURLSync} from '../state.ts';
import {savedHomeURL} from '../ports.ts';
import {loadCruise, loadLimits} from '../limits.ts';
import {loadReach} from '../reach.ts';
import {startTrip} from '../trip.ts';
import {App, appNow, freshness, freshnessFrom, loadRegion, narrow, NARROW_QUERY, regionInfo, startAppClock} from './App.tsx';
import {loadPlans, regionPlans} from '../species.ts';
import {bindBriefReport, currentBrief, dailyFeed, ensureRegionalForecast, feedGaps, loadDailyFeed} from '../brief/Brief.tsx';
import {coastBinding, coastStatus} from '../coast-data.ts';
import {regionPlace} from '../map/currents.ts';
import {initTelemetry} from '../telemetry.ts';

/** Give the shell a paint opportunity before the noncritical daily feed starts. */
export function deferDailyFeed({current = () => region.value, loaded = () => dailyFeed.peek()?.region_id,
  load = loadDailyFeed as (id: string) => Promise<unknown>,
  frame = (next: FrameRequestCallback) => requestAnimationFrame(next), cancel = (id: number) => cancelAnimationFrame(id)} = {}): () => void {
  const painted = signal(false);
  let disposed = false, second: number | undefined;
  const stop = effect(() => {
    const id = current();
    if (painted.value && id && loaded() !== id) void load(id).catch(() => { /* Brief owns its feed failure state. */ });
  });
  // A callback in the first frame still runs before that frame's paint. Start in
  // the next frame, after the browser had a chance to present the shell.
  const first = frame(() => {
    if (!disposed) second = frame(() => { if (!disposed) painted.value = true; });
  });
  return () => { disposed = true; stop(); cancel(first); if (second !== undefined) cancel(second); };
}

/** The browser entry; exporting the scheduler above does not boot a test document. */
export function startApp(): void {
configureStore({v2: true});
loadCoordinateFormat();
startURLSync();
// Cookie-less funnel and error reporting, as v1's dist/boot.js; nothing is sent under Do Not Track or GPC (web/telemetry.ts).
initTelemetry();
// #542: the user's own comfort limits, and the cruise speed for run times, kept on this device.
loadLimits();
loadCruise();
// #644: the range to consider for Boat and Kayak, kept on this device.
loadReach();
// The shell shows "No port chosen" until the address changes.
if (!region.peek() && !coast.peek()) void savedHomeURL(location.href).then(next => location.replace(next));
const width = matchMedia(NARROW_QUERY);
narrow.value = width.matches;
width.addEventListener('change', event => { narrow.value = event.matches; });
const host = document.getElementById('app');
if (host) { host.replaceChildren(); render(<App />, host); }
startAppClock();
// FE-51: after the render, so `#export` finds the planner's host.
startTrip();

effect(() => {
  const id = region.value;
  if (id && regionInfo.peek()?.id !== id) void loadRegion(id);
  if (id && regionPlans.peek()?.region !== id) void loadPlans(id);
});
deferDailyFeed();
// The brief's Wind and Swell tiles (#542): the region's forecast at the point nearest its centre, once the region's centre is known.
effect(() => {
  const id = region.value, info = regionInfo.value;
  if (id && info?.id === id) void ensureRegionalForecast(id, info.center);
});
// The brief's coast report where the region binds one, whichever layers are on: the same place the
// Swell and Water temp layers ask for (web/app/MapStage.tsx), so the client requests it once.
bindBriefReport(() => { const info = regionInfo.value; return info?.id === region.value ? regionPlace(info, profile.value, species.value ?? '') : null; });
const connected = signal(navigator.onLine);
const online = () => { connected.value = navigator.onLine; };
addEventListener('online', online);
addEventListener('offline', online);
online();
effect(() => {
  const now = appNow.value;
  const brief = regionInfo.value?.id === region.value ? currentBrief(now) : null;
  const failed = regionInfo.value?.id === region.value && (feedGaps.value.length > 0 || (brief?.gaps.length ?? 0) > 0
    || (!!coastBinding.value && ['error', 'invalid'].includes(coastStatus.value.report)));
  freshness.value = freshnessFrom(brief?.tiles ?? null, now, connected.value, failed);
});
}

if (typeof document !== 'undefined') startApp();
