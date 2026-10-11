// The v2 app shell (FE-05 desktop, FE-06 mobile; docs/plans/front-end/dev-plan.md): the
// web/app modules are bundled with esbuild and rendered to strings against a
// store read from a test address. Checks the shell's structure (masthead,
// command bar, brief, map chrome), that every control reflects the URL state
// it writes (profile, view, day, hour, layers, selection), that the brief's
// empty state invents no number, and that the copy and token rules hold.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {readdirSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {lintFile} from '../scripts/check_tokens.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const APP_FILES = ['web/app', 'web/app/views'].flatMap(dir => readdirSync(join(ROOT, dir)).filter(name => name.includes('.')).map(name => `${dir}/${name}`));
const ORIGIN = 'https://s.test/map';
const TZ = 'America/Los_Angeles';
/** The shell's clock in every render: Monday 2026-10-05, 1 pm Pacific, so chips and windows read the same whatever day the tests run. */
const NOW = new Date('2026-10-05T20:00:00Z');
/** The day chips of the 169-hour horizon from NOW: the eighth day repeats Monday, so it carries its date. */
const WEEK = ['Today', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun', 'Mon 12'];
/** 2 pm Pacific on Tuesday 2026-10-06. */
const TUE_2PM = '2026-10-06T21:00Z';

let shell;
async function load() {
  if (shell) return shell;
  const out = join(await mkdtemp(join(tmpdir(), 'shell-')), 'shell.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export * from './web/app/App.tsx';
      export {coordinates, titleCase, viewParam, MASTHEAD_VIEWS, advisorOn, checkAdvisor, ChatEntry} from './web/app/Masthead.tsx';
      export {targetOptions, windowText} from './web/app/CommandBar.tsx';
      export {Brief, emptyTiles, DISCLAIMER} from './web/app/Desktop.tsx';
      export {RAIL_ENTRIES, toggled} from './web/app/LayerRail.tsx';
      export {MarkCard, clearSelection, currentMark, placeholderMark, readingCard, terrainCard} from './web/app/MarkCard.tsx';
      export {chartMark} from './web/map/chart.ts';
      export {terrainMark, terrainReading} from './web/map/stage.ts';
      export {dayOptions, dockState, hourText, localParts, readout, zoneName} from './web/app/TimeDock.tsx';
      export {Mobile, LayersPanel, afterDetent, toggleLayers} from './web/app/Mobile.tsx';
      export {dragDetent, DRAG_MIN} from './web/ui/Sheet.tsx';
      export * as state from './web/state.ts';
      export {PROFILE_TABLE, RAIL_IDS} from './web/profile.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  shell = await import(pathToFileURL(out).href);
  return shell;
}
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))}; };
const count = (html, re) => (html.match(re) || []).length;
const attrs = (html, re) => [...html.matchAll(re)].map(m => m[1]);

/** Render the whole shell for `href` with a fresh store at the fixed clock `now`. */
async function renderShell(href, now = NOW) {
  const {App, render, h, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(href);
  return render(h(App, {now}));
}
/** The day chips of the group labelled Day in `html`, as [label, on]. */
const dayChips = html => [...html.match(/aria-label="Day"[^>]*>(.*?)<\/div>/s)[1].matchAll(/aria-pressed="(true|false)"[^>]*>(?:<svg.*?<\/svg>)?([^<]+)<\/button>/gs)].map(m => [m[2], m[1] === 'true']);

test('the shell has the masthead, the command bar, the brief column and the map chrome', async () => {
  const html = await renderShell(`${ORIGIN}?region=morro-bay`);
  assert.match(html, /<header class="app-masthead">/);
  assert.match(html, /class="app-brand" href="\/"[^>]*>.*SkipperCast/);
  assert.match(html, /class="app-location ui-mono" data-region="morro-bay">Morro Bay —</, 'the location names the region and leaves the centre blank until it loads');
  assert.match(html, /<nav aria-label="Views">/);
  assert.match(html, /<section class="app-command" aria-label="Command bar">/);
  assert.match(html, /<main class="app-main"><aside/);
  assert.deepEqual(attrs(html, /data-view="([a-z]+)"/g), ['coast', 'conditions', 'history', 'fleet']);
  assert.match(html, /class="app-fresh" role="status" data-state="unknown" aria-label="Freshness: No readings yet"/);
  // FE-50: sign in is the account menu's button, closed until pressed.
  assert.match(html, /<div class="app-account"><button type="button" class="ui-button ui-button--quiet app-account-trigger" aria-expanded="false" aria-controls="([^"]+)">.*?Sign in<\/button><div id="\1" class="app-account-panel" hidden/);
  assert.match(html, /role="group" aria-label="Profile"/);
  assert.equal(count(html, /(?:Boat|Shore|Spear)<\/button>/g), 3);
  assert.equal(count(html, /<label>Target<select/g), 1);
  assert.equal(count(html, /<label>Area<select/g), 1);
  assert.match(html, /<output class="app-window ui-mono" aria-label="Time window">Today · 1 pm<\/output>/);
  assert.deepEqual(dayChips(html), [['Today', true], ...WEEK.slice(1).map(label => [label, false])], 'no ?day= means today, at the fixed clock');
  assert.match(html, /aria-label="Hour" aria-valuetext="1 pm" min="0" max="10" step="1" value="0"/, 'today runs from the current hour to 11 pm');
  assert.match(html, /<aside class="app-brief" aria-label="Brief">/);
  assert.match(html, /class="ui-eyebrow">Today's brief</);
  assert.match(html, /<h1>[A-Z][^<]*\.<\/h1>/, 'the headline is one sentence with a full stop');
  assert.equal(count(html, /class="ui-tile"/g), 4);
  for (const label of ['Wind', 'Swell', 'Water', 'Tide']) assert.match(html, new RegExp(`<span>${label}</span>`));
  assert.match(html, /<figure class="app-spark" aria-label="Tide curve">/);
  assert.match(html, /class="ui-eyebrow">Where to look</);
  assert.match(html, /<p class="app-caveat">Habitat describes a place to look; fish presence is unverified.<\/p>/);
  assert.equal(count(html, /separate clocks/g), 1, 'one disclaimer line per page');
  assert.match(html, /<section class="app-stage" aria-label="Map">/);
  assert.match(html, /<section class="app-legend" aria-label="Legend">/);
  assert.match(html, /role="group" aria-label="Layers"/);
  assert.equal(count(html, /class="ui-rail-item"/g), 6);
  assert.match(html, /role="group" aria-label="Time"/);
  assert.match(html, /<input type="range" class="ui-range ui-dock-range" aria-label="Hour"/);
  assert.doesNotMatch(html, /app-mark/, 'no mark card without a selection');
});

test('the brief invents no number: every tile reads "—" and keeps its source line and basis', async () => {
  const {emptyTiles, render, h, Brief, state} = await load();
  for (const nearshore of [false, true]) {
    const tiles = emptyTiles(nearshore);
    assert.deepEqual(tiles.map(t => t.reading), ['—', '—', '—', '—']);
    for (const t of tiles) { assert.ok(t.source && t.basis, t.label); assert.doesNotMatch(t.source, /\d/, `${t.label} source carries no age yet`); }
    assert.equal(tiles[1].source, nearshore ? 'Nearshore site —' : 'Offshore —');
  }
  state.configureStore({storage: memory()});
  state.syncFromURL(`${ORIGIN}?profile=spear`);
  const html = render(h(Brief, {}));
  assert.equal(count(html, /<span class="ui-reading">—<\/span>/g), 4);
  assert.equal(count(html, /<details class="ui-popover"/g), 4, 'each tile has its basis in a <details>');
  assert.match(html, /Nearshore site —/, 'spear takes the nearshore swell source');
  assert.match(html, /<p class="app-empty">No ranked places yet.<\/p>/);
  assert.match(html, /In-water visibility is unverified/);
  const picks = [{id: 'r1', name: 'North reef', distance: '3.2 nm', depth: '60–90 ft', fit: 'fits habitat 3 of 3', reason: 'Hard bottom inside the limit.'}];
  const ranked = render(h(Brief, {picks}));
  assert.match(ranked, /<ol class="app-picks"><li class="app-pick" data-mark="r1">/);
  assert.match(ranked, /class="app-fit ui-eyebrow">fits habitat 3 of 3</);
});

test('every control reflects the address: profile, view, day, hour, layers and the selection', async () => {
  const link = `${ORIGIN}?region=morro-bay&profile=shore&view=conditions&layers=swell,water-temp&spot=r12&day=2026-10-06&hour=${encodeURIComponent(TUE_2PM)}&target=halibut&area=estero`;
  const html = await renderShell(link);
  // The Conditions view (FE-32) covers the map: its section shows and the map chrome's rail, legend and card do not; the dock stays.
  assert.match(html, /<section class="app-conditions" aria-labelledby="app-conditions-title">/);
  assert.equal(count(html, /class="ui-rail-item"/g), 0);
  const coastView = await renderShell(link.replace('&view=conditions', ''));
  // Profile switch: exactly Shore is on, and the shore caveat and swell source follow.
  const chips = [...html.matchAll(/<button[^>]*class="ui-button ui-button--ghost ui-button--sm ui-chip"[^>]*aria-pressed="(true|false)"[^>]*>.*?<\/svg>(Boat|Shore|Spear)/gs)].map(m => [m[2], m[1]]);
  assert.deepEqual(chips, [['Boat', 'false'], ['Shore', 'true'], ['Spear', 'false']]);
  assert.match(html, /Offshore seas do not measure breakers/);
  assert.match(html, /Nearshore site —/);
  // Views: the current one is aria-current and every link carries ?view= (coast drops it).
  assert.match(html, /href="[^"]*[?&]view=conditions[^"]*" aria-current="page" data-view="conditions"/);
  assert.match(html, /href="[^"]*[?&]view=history[^"]*" data-view="history"/);
  assert.doesNotMatch(html.match(/<a href="([^"]*)" data-view="coast"/)[1], /view=/, 'coast is the default and drops ?view=');
  // Target and area menus show the link's values.
  assert.match(html, /<label>Target<select><option value="surfperch">Barred surfperch<\/option><option selected value="halibut">California halibut<\/option><\/select>/, 'the coast targets\' names (FE-30)');
  assert.match(html, /<label>Area<select><option value>Whole region<\/option><option selected value="estero">Estero<\/option><\/select>/);
  // Rail and legend: swell and water temp on, the rest off; the protected areas always draw on the Chart (FE-19).
  const rail = Object.fromEntries([...coastView.matchAll(/<li class="ui-rail-item" data-on="(true|false)"><button[^>]*>.*?<span class="ui-rail-label">([^<]+)<\/span>/gs)].map(m => [m[2], m[1]]));
  assert.deepEqual(rail, {Seafloor: 'false', Currents: 'false', 'Water temp': 'true', Swell: 'true', 'Charter fleet': 'false', Clouds: 'false'});
  assert.match(coastView, /class="app-legend-water-temp"/);
  assert.deepEqual(attrs(coastView, /class="app-swatch" data-layer="([a-z-]+)"/g), ['mpas'], 'no colour key until a layer draws (FE-20)');
  // Dock: the chips run from the fixed clock (Monday), Tuesday 2026-10-06 is on and the slider sits at 2 pm local.
  assert.deepEqual(dayChips(html), WEEK.map(label => [label, label === 'Tue']));
  assert.match(html, /aria-label="Hour" aria-valuetext="2 pm" min="0" max="23" step="1" value="14"/);
  assert.match(html, /<output class="ui-dock-readout ui-mono" aria-live="off">2 pm<\/output>/);
  assert.match(html, /class="app-dock-zone ui-mono">P[DS]T</, 'the zone shows once in the dock');
  assert.match(html, /aria-label="Time window">Tue · 2 pm<\/output>/);
  // Selection: the mark card names the spot with blank reading and source.
  assert.match(coastView, /<section class="app-mark" aria-label="Selected mark"><div class="app-mark-head"><h2 tabindex="-1">r12<\/h2>/);
  assert.match(coastView, /<p class="ui-reading">—<\/p><p class="app-mark-source ui-mono">Source —<\/p>/);
  assert.match(coastView, /aria-label="Clear selection"/);
});

test('the helpers behind the controls round-trip through the store keys', async () => {
  const {localParts, dayOptions, dockState, hourText, readout, toggled, targetOptions, coordinates, titleCase, viewParam, clearSelection, windowText, RAIL_ENTRIES, RAIL_IDS, state, MASTHEAD_VIEWS} = await load();
  assert.deepEqual([localParts(new Date(TUE_2PM), TZ).day, localParts(new Date(TUE_2PM), TZ).hour], ['2026-10-06', 14]);
  assert.deepEqual([hourText(0), hourText(12), hourText(14)], ['12 am', '12 pm', '2 pm']);
  // Day chips: the horizon's eight local days; a selected day outside the horizon is kept.
  const now = new Date('2026-10-05T20:00:00Z');
  assert.deepEqual(dayOptions(now, TZ, null).map(o => o.label), WEEK);
  assert.deepEqual(dayOptions(now, TZ, null).slice(0, 2), [{value: '2026-10-05', label: 'Today'}, {value: '2026-10-06', label: 'Tue'}]);
  assert.deepEqual(dayOptions(now, TZ, '2026-10-20').at(-1), {value: '2026-10-20', label: '10-20'});
  state.configureStore({storage: memory()});
  state.syncFromURL(ORIGIN);
  const today = dockState(now, TZ);
  assert.deepEqual([today.day, today.today, today.at, today.index, today.hours.length], ['2026-10-05', '2026-10-05', Date.parse('2026-10-05T20:00Z'), 0, 11], 'no ?day= or ?hour= means today, now');
  state.syncFromURL(`${ORIGIN}?hour=2026-09-01T20:00Z`);
  assert.equal(readout(dockState(now, TZ), TZ), '1 pm · outside the forecast', 'a stale hour is kept and said to be outside');
  state.syncFromURL(ORIGIN);
  assert.equal(windowText(now, TZ), 'Today · 1 pm');
  // Rail toggles keep rail order and write ?layers=none for an empty rail.
  assert.deepEqual(RAIL_ENTRIES.map(e => e.id), [...RAIL_IDS]);
  assert.deepEqual(toggled(['swell'], 'seafloor', true), ['seafloor', 'swell']);
  assert.deepEqual(toggled(['seafloor', 'swell'], 'swell', false), ['seafloor']);
  assert.equal(state.layersParam(toggled(['seafloor'], 'seafloor', false)), 'none');
  assert.deepEqual(state.parseLayers(state.layersParam(toggled([], 'clouds', true))), ['clouds']);
  // Targets: the profile's list, with the link's target kept first when it is not in it.
  assert.deepEqual(targetOptions('shore', null), ['surfperch', 'halibut']);
  assert.deepEqual(targetOptions('boat', 'vermilion'), ['vermilion', 'lingcod']);
  assert.deepEqual(MASTHEAD_VIEWS, ['coast', 'conditions', 'history', 'fleet']);
  assert.deepEqual([viewParam('coast'), viewParam('fleet')], [null, 'fleet']);
  assert.equal(coordinates([35.34, -120.965]), '35.34N 120.97W');
  assert.equal(titleCase('cabezon-shallow-reef'), 'Cabezon Shallow Reef');
  assert.equal(clearSelection(`${ORIGIN}?region=morro-bay&spot=r12&focus=r13&view=fleet`), `${ORIGIN}?region=morro-bay&view=fleet`);
});

/** Render the shell for `href` as the mobile layout (what main.tsx does under 1,024 px). */
async function renderMobile(href) {
  const {narrow} = await load();
  narrow.value = true;
  try { return await renderShell(href); } finally { narrow.value = false; }
}

test('under 1,024 px the shell is the map, a top strip, one sheet at peek and a four-tab nav', async () => {
  const html = await renderMobile(`${ORIGIN}?region=morro-bay`);
  assert.match(html, /^<div class="app-mobile"><section class="app-stage" aria-label="Map">/, 'the map stage comes first and fills the viewport');
  assert.doesNotMatch(html, /app-masthead|app-command|app-main|app-brief"|app-dock/, 'no desktop chrome');
  // Top strip: the brand and location card, the layers button, then the full-width profile switch.
  assert.match(html, /<header class="app-top"><div class="app-top-row"><div class="app-top-card"><a class="app-brand" href="\/">.*?<span class="app-location ui-mono" data-region="morro-bay">Morro Bay —<\/span><\/div><button[^>]*aria-label="Layers"[^>]*aria-pressed="false"/s);
  assert.match(html, /role="group" aria-label="Profile" class="ui-segmented app-profile"/);
  assert.equal(count(html, /(?:Boat|Shore|Spear)<\/button>/g), 3);
  // One sheet at peek with the hour slider at its edge, then the brief in sheet order.
  assert.equal(count(html, /class="ui-sheet /g), 1);
  assert.match(html, /<section class="ui-sheet app-sheet" data-detent="peek" aria-label="Brief"><div class="ui-sheet-edge"><button type="button" class="ui-sheet-handle" aria-label="Expand Brief" aria-expanded="false"/);
  assert.match(html, /<\/button><div class="app-sheet-hour" role="group" aria-label="Time"><input type="range" class="ui-range ui-dock-range" aria-label="Hour" aria-valuetext="1 pm"[^>]*><output class="ui-dock-readout ui-mono" aria-live="off">1 pm<\/output><\/div><\/div>/);
  const body = html.slice(html.indexOf('<div class="ui-sheet-body">'), html.indexOf('<nav aria-label="Views"'));
  const order = ['class="ui-eyebrow">Today · 1 pm</span>','class="app-fresh" role="status"', '<h1>Waiting for readings.</h1>', '<div class="app-tiles">', 'class="ui-eyebrow">Where to look', '<figure class="app-spark"',
    '<div class="app-sheet-menus"><div role="group" aria-label="Day"', '<label>Target<select', '<label>Area<select', '<p class="app-caveat">', '<footer class="app-brief-footer">', '<div class="app-account" data-inline="true">'];
  const at = order.map(s => body.indexOf(s));
  assert.ok(at.every(i => i >= 0), `every piece renders: ${JSON.stringify(order.filter((_, i) => at[i] < 0))}`);
  assert.deepEqual(at, [...at].sort((a, b) => a - b), 'in sheet order: eyebrow, freshness, headline, tiles, picks, tide, menus, caveat, footer');
  assert.equal(count(body, /class="ui-tile"/g), 4);
  assert.equal(count(html, /<h1>/g), 1);
  assert.equal(count(html, /separate clocks/g), 1, 'one disclaimer line per page');
  assert.doesNotMatch(html, /ui-rail-item|app-legend/, 'the rail and legend wait for the layers button');
  // Tabs: the four views with icons, after the sheet.
  assert.match(html, /<nav aria-label="Views" class="app-tabs"><ul class="app-views">/);
  assert.deepEqual(attrs(html, /data-view="([a-z]+)"/g), ['coast', 'conditions', 'history', 'fleet']);
  assert.equal(count(html, /data-view="[a-z]+"><svg/g), 4, 'each tab has its icon');
  assert.match(html, /aria-current="page" data-view="coast"/);
});

test('the mobile sheet reflects the address: the mark card stands in at peek, the hour and day follow the dock', async () => {
  const {render, h, LayersPanel, state, afterDetent, toggleLayers, dragDetent, DRAG_MIN} = await load();
  const html = await renderMobile(`${ORIGIN}?region=morro-bay&profile=spear&spot=r12&day=2026-10-06&hour=${encodeURIComponent(TUE_2PM)}&layers=clouds`);
  assert.match(html, /<section class="ui-sheet app-sheet app-sheet--mark" data-detent="peek" aria-label="Brief">/);
  assert.match(html, /<div class="ui-sheet-body"><div class="app-sheet-brief"><section class="app-mark" aria-label="Selected mark"><div class="app-mark-head"><h2 tabindex="-1">r12<\/h2>/);
  assert.doesNotMatch(html, /<h1>/, 'the card replaces the headline');
  assert.match(html, /aria-label="Hour" aria-valuetext="2 pm" min="0" max="23" step="1" value="14"/);
  assert.deepEqual(dayChips(html), WEEK.map(label => [label, label === 'Tue']), 'the sheet\'s day menu runs from the fixed clock');
  assert.match(html, /Nearshore site —/);
  assert.match(html, /In-water visibility is unverified/);
  // The layers panel: the rail with the legend of what is on, and a Done button.
  state.configureStore({v2: true, storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay&layers=clouds`);
  const panel = render(h(LayersPanel, {onClose: () => {}}));
  assert.match(panel, /^<div class="app-sheet-layers"><div class="app-sheet-head"><span class="ui-eyebrow">Layers<\/span><button[^>]*>.*?Done<\/button><\/div><div class="ui-rail app-rail" role="group" aria-label="Layers">/s);
  assert.equal(count(panel, /class="ui-rail-item"/g), 6);
  assert.match(panel, /<li class="app-legend-clouds"><span class="app-legend-text">Clouds</);
  assert.deepEqual(attrs(panel, /class="app-swatch" data-layer="([a-z-]+)"/g), ['mpas'], 'no cloud key until a frame shows (FE-20)');
  // Panel and detent rules: layers opens at half from peek, closes when the sheet drops to peek.
  assert.deepEqual(toggleLayers('brief', 'peek'), {panel: 'layers', detent: 'half'});
  assert.deepEqual(toggleLayers('brief', 'full'), {panel: 'layers', detent: 'full'});
  assert.deepEqual(toggleLayers('layers', 'half'), {panel: 'brief', detent: 'half'});
  assert.deepEqual(afterDetent('layers', 'peek'), {panel: 'brief', detent: 'peek'});
  assert.deepEqual(afterDetent('layers', 'full'), {panel: 'layers', detent: 'full'});
  // Drag: short drags snap back, a drag past the minimum steps once, a far drag goes to the end.
  assert.equal(dragDetent('peek', -(DRAG_MIN - 1), 700), 'peek');
  assert.equal(dragDetent('peek', -DRAG_MIN, 700), 'half');
  assert.equal(dragDetent('peek', -400, 700), 'full');
  assert.equal(dragDetent('half', 60, 700), 'peek');
  assert.equal(dragDetent('full', 400, 700), 'peek');
  assert.equal(dragDetent('full', -100, 700), 'full');
});

test('loadRegion fills the masthead from regions/<id>/region.json and leaves placeholders on failure', async () => {
  const {loadRegion, regionInfo, render, h, App, state} = await load();
  const fetched = [];
  const area = {id: 'estero-bay', name: 'Estero Bay', bounds: [-121.05, 35.32, -120.78, 35.47]};
  const ok = async url => { fetched.push(url); return {ok: true, json: async () => ({name: 'Morro Bay & Avila', timezone: TZ, map: {center: [35.34, -120.965], local_areas: [area, {id: 7}, null]}})}; };
  // The reviewed local areas come along for the coast report binding (FE-15's currents packet); malformed ones are dropped.
  assert.deepEqual(await loadRegion('morro-bay', ok), {id: 'morro-bay', name: 'Morro Bay & Avila', center: [35.34, -120.965], timezone: TZ, localAreas: [area]});
  assert.deepEqual(fetched, ['regions/morro-bay/region.json']);
  state.configureStore({storage: memory()});
  state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  assert.match(render(h(App, {})), /data-region="morro-bay">Morro Bay &amp; Avila 35.34N 120.97W</);
  regionInfo.value = null;
  assert.equal(await loadRegion('x', async () => ({ok: false})), null);
  assert.equal(await loadRegion('x', async () => { throw new Error('offline'); }), null);
  assert.equal(regionInfo.value, null);
});

// FE-55: the chat entry renders only while the advisor answers (its gate 404s /chat.html while TEXT_ADVISOR_ENABLED is off).
test('the masthead chat entry renders nothing with the advisor off and links to the web chat when on', async () => {
  const {advisorOn, checkAdvisor, ChatEntry, render, h} = await load();
  const asked = [];
  const answer = status => async (url, init) => { asked.push([url, init]); return {ok: status >= 200 && status < 300, status}; };
  assert.equal(await checkAdvisor(answer(404)), false, 'the gate answers 404 while the advisor is off');
  assert.equal(await checkAdvisor(async () => { throw new Error('offline'); }), false);
  assert.equal(await checkAdvisor(answer(200)), true);
  assert.deepEqual(asked[0], ['/chat.html', {method: 'HEAD', credentials: 'omit', cache: 'no-store'}], 'one HEAD, no cookie');

  advisorOn.value = false;
  assert.equal(render(h(ChatEntry, {})), '');
  const off = await renderShell(`${ORIGIN}?region=morro-bay`);
  assert.doesNotMatch(off, /data-advisor-entry|chat\.html|Ask SkipperCast/);
  advisorOn.value = true;
  try {
    assert.equal(render(h(ChatEntry, {})), '<a class="ui-button ui-button--quiet" href="/chat.html" data-advisor-entry="true">Ask SkipperCast</a>');
    assert.match(await renderShell(`${ORIGIN}?region=morro-bay`), /class="app-fresh".*data-advisor-entry="true">Ask SkipperCast<\/a><div class="app-account">/s, 'between freshness and the account menu');
  } finally { advisorOn.value = false; }
});

test('the map chrome offers Chart, 2D and 3D; without terrain the terrain choices are disabled and point at the reason', async () => {
  const toggle = html => [...html.match(/aria-label="Map presentation"[^>]*>(.*?)<\/div>/s)[1].matchAll(/<button([^>]*)>([^<]+)<\/button>/g)]
    .map(([, a, label]) => [label, /aria-pressed="true"/.test(a), /disabled/.test(a), /aria-describedby="app-stage-note"/.test(a)]);
  for (const narrowed of [false, true]) {
    const {narrow} = await load();
    narrow.value = narrowed;
    try {
      const terrain = await renderShell(`${ORIGIN}?region=morro-bay&presentation=3d`);
      assert.deepEqual(toggle(terrain), [['Chart', false, false, false], ['2D', false, false, false], ['3D', true, false, false]]);
      assert.match(terrain, /<div class="app-map" hidden><div class="app-chart"><\/div><\/div><div class="app-terrain" data-coast-theme="tokens"><\/div>/, 'the terrain host is shown with the token opt-in; the Chart host (FE-11) waits hidden');
      const none = await renderShell(`${ORIGIN}?region=channel-islands&presentation=3d`);
      assert.deepEqual(toggle(none), [['Chart', true, false, false], ['2D', false, true, true], ['3D', false, true, true]]);
      assert.match(none, /<p id="app-stage-note" class="app-stage-note" role="status">No reviewed coastal terrain covers this region yet.<\/p>/);
    } finally { narrow.value = false; }
  }
});

test('the mark card shows a Chart selection, then the terrain\'s on the Chart, then the link\'s atlas mark', async () => {
  const {MarkCard, currentMark, terrainCard, chartMark, terrainMark, render, h, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  const shore = {id: 'coastline:S1', name: 'Shoreline', kind: 'Mean High Water · Natural', reading: 'Lidar · ±2 m stated', source: 'NOAA NGS CUSP · source date 2010-11-01', basis: 'NOAA NGS CUSP shoreline, 1994–2010 sources.'};
  const reef = {latitude: 35.38, longitude: -120.88, id: 'reef:r1'};
  try {
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&spot=r12`);
    assert.equal(currentMark.value.name, 'r12', 'the atlas placeholder');
    terrainMark.value = reef;
    assert.equal(currentMark.value.name, 'r12', 'the terrain\'s selection shows only while the link names it');
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&spot=r12&habitat=reef:r1`);
    assert.deepEqual(currentMark.value, terrainCard(reef));
    assert.equal(terrainCard(reef).reading, '35.3800° N, 120.8800° W');
    chartMark.value = shore;
    assert.equal(currentMark.value, shore, 'a Chart click wins');
    const html = render(h(MarkCard, {}));
    assert.match(html, /<h2 tabindex="-1">Shoreline<\/h2>.*Lidar · ±2 m stated.*NOAA NGS CUSP · source date 2010-11-01/s);
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d&spot=r12`);
    assert.equal(currentMark.value.name, 'r12', 'in the terrain its own panel speaks; the atlas mark stays');
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d`);
    assert.equal(currentMark.value, null);
  } finally { chartMark.value = null; terrainMark.value = null; }
});

test('FE-80: in 2D and 3D a terrain reading is the card, with the renderer\'s label and source clock verbatim, then its habitat', async () => {
  const {MarkCard, currentMark, readingCard, terrainCard, terrainMark, terrainReading, render, h, state} = await load();
  state.configureStore({v2: true, storage: memory()});
  const reading = {latitude: 35.37, longitude: -120.86, heightM: -12, spacingM: 2, label: 'ORIGINAL SURVEY SAMPLE', value: '39 ft depth', location: '35.37000° N · 120.86000° W',
    detail: 'USGS survey · 2008-05-01 · 2 m display spacing. Nominal. Original spacing 2 m. Vertical references have not been reconciled.',
    source: {id: 2, label: 'USGS survey', kind: 'survey', resolutionM: 2, datum: 'Nominal', sourceDate: '2008-05-01', url: 'https://example.test'}};
  const reef = {latitude: 35.38, longitude: -120.88, id: 'reef:r1'};
  try {
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=3d&habitat=reef:r1`);
    terrainMark.value = reef;
    assert.deepEqual(currentMark.value, terrainCard(reef), 'the terrain\'s habitat shows in 2D and 3D too');
    terrainReading.value = reading;
    assert.deepEqual(currentMark.value, readingCard(reading));
    const html = render(h(MarkCard, {}));
    assert.match(html, /<h2 tabindex="-1">39 ft depth<\/h2>.*<p class="app-mark-kind">ORIGINAL SURVEY SAMPLE<\/p><p class="ui-reading">35\.37000° N · 120\.86000° W<\/p><p class="app-mark-source ui-mono">USGS survey · 2008-05-01 · 2 m display spacing\. Nominal\. Original spacing 2 m\. Vertical references have not been reconciled\.<\/p>/s);
    state.syncFromURL(`${ORIGIN}?region=morro-bay&presentation=chart&habitat=reef:r1`);
    assert.deepEqual(currentMark.value, terrainCard(reef), 'the Chart has no terrain reading');
  } finally { terrainMark.value = null; terrainReading.value = null; }
});

test('the shell files keep the token and copy rules, and app.html mounts the entry', async () => {
  for (const file of APP_FILES) {
    const source = readFileSync(join(ROOT, file), 'utf8');
    assert.deepEqual(lintFile(file, source), [], file);
    assert.doesNotMatch(source, /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u, `${file} has no emoji`);
    // FE-75: CoastMarkup is the one markup host (scripts/check_web.py enforces it across web/).
    if (file !== 'web/app/CoastMarkup.tsx') assert.doesNotMatch(source, /innerHTML/, `${file} renders through Preact`);
    assert.doesNotMatch(source, /\b(?:best spot|productive|catch rate|bite)\b/i, `${file} promises no fish`);
  }
  const page = await readFile(join(ROOT, 'dist/app.html'), 'utf8');
  assert.match(page, /<div id="app">/);
  assert.match(page, /<script type="module" src="\.\.\/web\/app\/main\.tsx"><\/script>/);
  assert.deepEqual(attrs(page, /<link rel="stylesheet" href="([^"]+)"/g), ['../web/tokens.css', '../web/ui/ui.css', '../web/app/app.css', '../web/landing/port-input.css', '../web/app/account.css', '../web/app/trip.css'],
    'tokens first, then the primitives, then the shell, then the entry flow (FE-08), then the account dialogs (FE-50), then the trip plan (FE-51)');
  assert.doesNotMatch(page, /leaflet/i, 'the v2 shell imports no Leaflet');
  assert.deepEqual(attrs(page, /src="(vendor\/[^"]+)"/g), ['vendor/simplewebauthn-browser-14.0.0/index.umd.min.js'], 'the only vendored script is the passkey library (FE-50)');
});
