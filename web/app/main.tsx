// Entry of dist/app.html (FE-05): a v2 store (region changes never reload),
// the address read once and followed on Back/Forward, the shell rendered
// into #app, then the region's name and zone for the masthead and the dock.
import {render} from 'preact';
import {effect} from '@preact/signals';
import {configureStore, region, startURLSync} from '../state.ts';
import {App, freshness, loadRegion, regionInfo} from './App.tsx';

configureStore({v2: true});
startURLSync();
const host = document.getElementById('app');
if (host) { host.replaceChildren(); render(<App />, host); }

effect(() => {
  const id = region.value;
  if (id && regionInfo.peek()?.id !== id) void loadRegion(id);
});
const online = () => { freshness.value = navigator.onLine ? {state: 'unknown', age: null} : {state: 'offline', age: null}; };
addEventListener('online', online);
addEventListener('offline', online);
online();
