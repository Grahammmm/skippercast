// Entry of dist/app.html (FE-05): a v2 store (region changes never reload),
// the address read once and followed on Back/Forward, the width followed for
// the mobile layout (FE-06), the shell rendered into #app, then the region's
// name and zone for the masthead and the dock.
// /map with no region or coast (FE-08, § 7) opens the saved port, else the
// landing; the chooser itself never opens on its own.
import {render} from 'preact';
import {effect} from '@preact/signals';
import {configureStore, coast, region, startURLSync} from '../state.ts';
import {landingURL, loadPorts, portURL, savedPortId} from '../ports.ts';
import {App, freshness, loadRegion, narrow, NARROW_QUERY, regionInfo} from './App.tsx';

configureStore({v2: true});
startURLSync();
/** /map with no area: the saved port's app, else the landing (the shell shows "No port chosen" until the address changes). */
export async function openSavedPort(href: string = location.href): Promise<string> {
  const saved = savedPortId();
  const port = saved ? await loadPorts().then(ports => ports.find(p => p.id === saved) ?? null, () => null) : null;
  return port ? portURL(href, port) : landingURL(href);
}
if (!region.peek() && !coast.peek()) void openSavedPort().then(next => location.replace(next));
const width = matchMedia(NARROW_QUERY);
narrow.value = width.matches;
width.addEventListener('change', event => { narrow.value = event.matches; });
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
