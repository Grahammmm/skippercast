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
import {startTrip} from '../trip.ts';
import {App, freshness, loadRegion, narrow, NARROW_QUERY, regionInfo} from './App.tsx';
import {loadPlans, regionPlans} from '../species.ts';

configureStore({v2: true});
startURLSync();
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
});
const online = () => { freshness.value = navigator.onLine ? {state: 'unknown', age: null} : {state: 'offline', age: null}; };
addEventListener('online', online);
addEventListener('offline', online);
online();
