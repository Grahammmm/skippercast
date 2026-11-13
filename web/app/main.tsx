// Entry of dist/app.html (FE-05): a v2 store (region changes never reload),
// the address read once and followed on Back/Forward, the width followed for
// the mobile layout (FE-06), the shell rendered into #app, then the region's
// name and zone for the masthead and the dock.
// /map with no region or coast (FE-08, § 7) opens the saved home (a port v1
// or v2 saved, or a /coast place, FE-83), else the landing; the chooser
// itself never opens on its own.
import {render} from 'preact';
import {effect} from '@preact/signals';
import {initReadyLanguage} from '../i18n.ts';
import {configureStore, coast, loadCoordinateFormat, profile, region, species, startURLSync} from '../state.ts';
import {savedHomeURL} from '../ports.ts';
import {followStoredLimits, loadCruise, loadLimits} from '../limits.ts';
import {loadLaunch, loadReach, loadSpear} from '../reach.ts';
import {startTrip} from '../trip.ts';
import {App, bindStartupFreshness, loadRegion, narrow, NARROW_QUERY, regionInfo, regionLoad} from './App.tsx';
import {loadPlans, regionPlans} from '../species.ts';
import {failVerdictMetadata, beginVerdictRegion, bindBriefReport, currentBrief, ensureRegionalForecast, enableSavedBrief, noteRegionInfo, loadDailyFeed, needsDailyLoad, savedBrief, showSavedBrief, verdictEpoch} from '../brief/Brief.tsx';
import {regionPlace} from '../map/currents.ts';
import {shownPresentation} from '../map/stage.ts';
import {initTelemetry} from '../telemetry.ts';
import {installDegradedWatch} from '../degraded.ts';
import {holdMap, MAP_WAIT_MAX_MS, releaseMap, whenMapMayLoad} from '../map-ready.ts';

// SC-LAUNCH-4: before any read, so every response's cost-ceiling mark reaches the notice.
installDegradedWatch();
configureStore({v2: true});
loadCoordinateFormat();
// SC1407-09: the language now; a Spanish page's table loads meanwhile, and the first render below waits for it.
const ready = initReadyLanguage();
startURLSync();
// Cookie-less funnel and error reporting, as v1's dist/boot.js; nothing is sent under Do Not Track or GPC (web/telemetry.ts).
initTelemetry({views: true});
// #542: the user's own comfort limits, and the cruise speed for run times, kept on this device.
enableSavedBrief();
loadLimits();
loadCruise();
followStoredLimits();
// #644: the range to consider for Boat and Kayak, Spear's dive limits and Kayak's launch, kept on this device.
loadReach();
loadSpear();
loadLaunch();
// The shell shows "No port chosen" until the address changes.
if (!region.peek() && !coast.peek()) void savedHomeURL(location.href).then(next => location.replace(next));
// SCB-11: a page that opens on a region holds the Chart's own downloads (MapLibre, the basemap, the protected areas, the marks)
// until the first verdict is on screen: the region's answer settled, or the saved brief shown; at most MAP_WAIT_MAX_MS after the
// page started. On a slow link they would otherwise share it with the files the verdict needs (web/map-ready.ts).
if (region.peek()) {
  holdMap();
  effect(() => { if (verdictEpoch.value?.sealed || savedBrief.value) releaseMap(); });
  setTimeout(releaseMap, Math.max(0, MAP_WAIT_MAX_MS - performance.now()));
}
const width = matchMedia(NARROW_QUERY);
narrow.value = width.matches;
width.addEventListener('change', event => { narrow.value = event.matches; });

/** The first render (in the page language, its table ready) and what follows it. initReadyLanguage never rejects. */
async function start(): Promise<void> {
  await ready;
  effect(() => beginVerdictRegion(region.value));
  const host = document.getElementById('app');
  if (host) { host.replaceChildren(); render(<App />, host); }
  // SC1407-08 (#1762 M3): a /map page that opens on the Chart starts fetching its library as soon as the map may load (SCB-11: after
  // the first verdict), not when the Chart mounts. The Chart imports this same module (web/map/chart.ts), so the browser loads it once
  // and the Chart reports any failure.
  if (host && location.pathname === '/map' && region.peek() && shownPresentation.peek() === 'chart') whenMapMayLoad(() => void import('../map/maplibre.js').catch(() => {}));
  // FE-51: after the render, so `#export` finds the planner's host.
  startTrip();

  effect(() => {
    const id = region.value;
    if (id && regionInfo.peek()?.id !== id) void loadRegion(id);
    if (id && regionPlans.peek()?.region !== id) void loadPlans(id);
    if (id) showSavedBrief(id);   // the last brief kept on this device, at once; the reads below replace it
    if (id && needsDailyLoad(id)) void loadDailyFeed(id);
  });
  effect(() => { const load = regionLoad.value; if (load && (load.state === 'error' || load.state === 'missing')) failVerdictMetadata(load.id); });
  // The brief's Wind and Swell tiles (#542): the region's forecast at the point nearest its centre, once the region's centre is known.
  effect(() => {
    const id = region.value, info = regionInfo.value;
    if (id && info?.id === id) { void ensureRegionalForecast(id, info.center); noteRegionInfo(id); }
  });
  // The brief's coast report where the region binds one, whichever layers are on: the same place the
  // Swell and Water temp layers ask for (web/app/MapStage.tsx), so the client requests it once.
  bindBriefReport(() => { const info = regionInfo.value; return info?.id === region.value ? regionPlace(info, profile.value, species.value ?? '') : null; });
  // Reuse the displayed brief's original source clocks. Connectivity and cache access
  // never re-date a reading, and a switched-out region cannot supply the masthead age.
  bindStartupFreshness(() => regionInfo.value?.id === region.value ? currentBrief(new Date())?.tiles ?? [] : []);
}
void start();
