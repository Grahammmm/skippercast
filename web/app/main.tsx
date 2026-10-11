// Entry of dist/app.html (FE-05): a v2 store (region changes never reload),
// the address read once and followed on Back/Forward, the width followed for
// the mobile layout (FE-06), the shell rendered into #app, then the region's
// name and zone for the masthead and the dock.
// /map with no region or coast (FE-08, § 7) opens the saved home (a port v1
// or v2 saved, or a /coast place, FE-83), else the landing; the chooser
// itself never opens on its own.
import {render} from 'preact';
import {effect} from '@preact/signals';
import {configureStore, coast, region, startURLSync} from '../state.ts';
import {savedHomeURL} from '../ports.ts';
import {loadLimits} from '../limits.ts';
import {startTrip} from '../trip.ts';
import {App, freshness, loadRegion, narrow, NARROW_QUERY, regionInfo} from './App.tsx';
import {loadPlans, regionPlans} from '../species.ts';
import {dailyFeed, ensureRegionalForecast, loadDailyFeed} from '../brief/Brief.tsx';

configureStore({v2: true});
startURLSync();
// #542: the user's own comfort limits, kept on this device.
loadLimits();
// The shell shows "No port chosen" until the address changes.
if (!region.peek() && !coast.peek()) void savedHomeURL(location.href).then(next => location.replace(next));
const width = matchMedia(NARROW_QUERY);
narrow.value = width.matches;
width.addEventListener('change', event => { narrow.value = event.matches; });
const host = document.getElementById('app');
if (host) { host.replaceChildren(); render(<App />, host); }
// FE-51: after the render, so `#export` finds the planner's host.
startTrip();

effect(() => {
  const id = region.value;
  if (id && regionInfo.peek()?.id !== id) void loadRegion(id);
  if (id && regionPlans.peek()?.region !== id) void loadPlans(id);
  if (id && dailyFeed.peek()?.region_id !== id) void loadDailyFeed(id);
});
// The brief's Wind and Swell tiles (#542): the region's forecast at the point nearest its centre, once the region's centre is known.
effect(() => {
  const id = region.value, info = regionInfo.value;
  if (id && info?.id === id) void ensureRegionalForecast(id, info.center);
});
const online = () => { freshness.value = navigator.onLine ? {state: 'unknown', age: null} : {state: 'offline', age: null}; };
addEventListener('online', online);
addEventListener('offline', online);
online();
