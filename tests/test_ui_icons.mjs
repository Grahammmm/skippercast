// Icons and UI primitives (FE-03, docs/plans/front-end/dev-plan.md): the
// .tsx modules are bundled with esbuild and rendered to strings. Checks the
// task's acceptance: every icon is one <svg> in currentColor, the primitives
// carry no colour or font literal (the token lint's rules) and resolve every
// token in both themes, and their markup is pinned by snapshot per theme in
// tests/fixtures/ui-snapshots.json (UI_SNAPSHOT_UPDATE=1 rewrites it).
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {readdirSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {lintFile, stripComments as stripped} from '../scripts/check_tokens.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const SNAPSHOTS = join(ROOT, 'tests/fixtures/ui-snapshots.json');
const UI_FILES = readdirSync(join(ROOT, 'web/ui')).map(name => `web/ui/${name}`);
const FISH_ICONS = ['wave', 'fish', 'boat', 'shore', 'spear', 'wind', 'temperature', 'tide', 'sun', 'cloud', 'layers', 'map', 'chart', 'history',
  'pin', 'arrow', 'chevron', 'down', 'close', 'play', 'pause', 'info', 'check', 'compass', 'current', 'eye', 'shield', 'target', 'settings', 'expand', 'bell'];

async function ui() {
  const dir = await mkdtemp(join(tmpdir(), 'ui-'));
  const out = join(dir, 'ui.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {Icon, ICON_NAMES} from './web/ui/icons.tsx';
      export {Button, IconButton} from './web/ui/Button.tsx';
      export {Chip, Segmented} from './web/ui/Chip.tsx';
      export {Tile} from './web/ui/Tile.tsx';
      export {Rail, RailItem} from './web/ui/Rail.tsx';
      export {Sheet, DETENTS, nextDetent, stepDetent} from './web/ui/Sheet.tsx';
      export {Dock, Range} from './web/ui/Dock.tsx';
      export {Popover} from './web/ui/Popover.tsx';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  });
  return import(pathToFileURL(out).href);
}
const noop = () => {};

test('every icon name renders one <svg> in currentColor, decorative unless labelled', async () => {
  const {Icon, ICON_NAMES, render, h} = await ui();
  for (const name of FISH_ICONS) assert.ok(ICON_NAMES.includes(name), `${name} ported from fish`);
  assert.ok(ICON_NAMES.length >= 31);
  for (const name of ICON_NAMES) {
    const svg = render(h(Icon, {name}));
    assert.equal((svg.match(/<svg\b/g) || []).length, 1, name);
    assert.match(svg, /^<svg class="icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" data-icon="[a-z]+" aria-hidden="true">/, name);
    assert.doesNotMatch(svg, /#[0-9a-f]{3,8}\b|rgb\(/i, `${name} has no colour`);
    assert.match(svg, /<path d="[^"]+"><\/path>/, name);
  }
  const labelled = render(h(Icon, {name: 'info', label: 'Basis', size: 16}));
  assert.match(labelled, /width="16" height="16"/);
  assert.match(labelled, /role="img" aria-label="Basis"/);
  assert.doesNotMatch(labelled, /aria-hidden/);
});

test('the primitives carry no colour or font literal, no emoji, and resolve every token in both themes', async () => {
  const tokens = await readFile(join(ROOT, 'web/tokens.css'), 'utf8');
  const block = selector => Object.fromEntries([...tokens.slice(tokens.indexOf(selector)).replace(/^[^{]*\{/, '').split('}')[0].matchAll(/(--[\w-]+):\s*([^;]+);/g)].map(m => [m[1], m[2]]));
  const dark = block(':root {'), light = {...dark, ...block(':root[data-theme="light"]')};
  const css = await readFile(join(ROOT, 'web/ui/ui.css'), 'utf8');
  const local = new Set([...css.matchAll(/(--sheet-[\w-]+):/g)].map(m => m[1]));
  for (const file of UI_FILES) {
    const source = readFileSync(join(ROOT, file), 'utf8');
    assert.deepEqual(lintFile(file, source), [], file);
    assert.doesNotMatch(source, /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u, `${file} has no emoji`);
  }
  for (const [, name] of css.matchAll(/var\((--[\w-]+)\)/g)) {
    if (local.has(name)) continue;
    assert.ok(name in dark, `${name} is a dark token`);
    assert.ok(name in light, `${name} resolves in the light theme`);
  }
  // Every interactive class is a 44 px target, and no rule on one (base, variant, modifier or
  // descendant; pseudo-elements like the slider track are parts, not targets) shrinks it.
  const INTERACTIVE = /\.ui-(?:button|icon-button|chip|popover-summary|range|sheet-handle|rail-toggle)\b/;
  const rules = [...stripped(css).matchAll(/([^{}]+)\{([^}]*)\}/g)].map(m => ({selector: m[1].trim(), body: m[2]}));
  for (const name of ['ui-button', 'ui-popover-summary', 'ui-range', 'ui-sheet-handle']) {
    assert.ok(rules.some(r => r.selector === `.${name}` && /(?:min-)?height: var\(--touch-min\)/.test(r.body)), `${name} is a 44 px target`);
  }
  for (const {selector, body} of rules) {
    if (!INTERACTIVE.test(selector) || /::/.test(selector)) continue;
    for (const [, prop, value] of body.matchAll(/(?:^|;)\s*((?:min-)?height):\s*([^;]+)/g)) assert.equal(value.trim(), 'var(--touch-min)', `${selector} ${prop}`);
  }
  assert.match(css, /:focus-visible \{ outline: 2px solid var\(--focus\)/);
});

/** One sample of each primitive, rendered as the shell will use it. */
function samples({Button, IconButton, Chip, Segmented, Tile, Rail, RailItem, Sheet, Dock, Range, Popover, h}) {
  const profiles = [{value: 'boat', label: 'Boat', icon: 'boat'}, {value: 'shore', label: 'Shore', icon: 'shore'}, {value: 'spear', label: 'Spear', icon: 'spear'}];
  return {
    Button: h(Button, {variant: 'primary', icon: 'plus'}, 'Add to trip'),
    IconButton: h(IconButton, {icon: 'play', label: 'Play', pressed: false, onClick: noop}),
    Chip: h(Chip, {on: true, icon: 'boat'}, 'Boat'),
    Segmented: h(Segmented, {label: 'Profile', options: profiles, value: 'shore', onChange: noop}),
    Tile: h(Tile, {label: 'Wind', icon: 'wind', hue: 'mint', reading: '12', unit: 'kt', detail: 'NW, gusts 18', source: 'NWS 2 h', basis: 'NWS point forecast for the hour shown.'}),
    TileStale: h(Tile, {label: 'Water', icon: 'temperature', hue: 'coral', reading: 'no fresh buoy', source: 'Buoy 46011 9 h', stale: true}),
    Rail: h(Rail, null, h(RailItem, {id: 'currents', label: 'Currents', icon: 'current', on: true, onToggle: noop, note: 'no fresh frame 14:00', basis: 'WCOFS surface forecast, about 4 km.'})),
    Sheet: h(Sheet, {label: 'Brief', detent: 'half', onDetent: noop, edge: h(Range, {label: 'Hour', value: 3, max: 23, onChange: noop})}, 'Headline'),
    Dock: h(Dock, {days: [{value: 'today', label: 'Today'}, {value: 'tue', label: 'Tue'}], day: 'today', onDay: noop, playing: true, onPlay: noop, hour: 14, hours: 24, onHour: noop, hourText: v => `${v % 12 || 12} ${v < 12 ? 'am' : 'pm'}`}),
    Popover: h(Popover, {iconOnly: true, summary: 'Swell basis', align: 'end'}, 'Model wave forecast on the region grid.'),
  };
}

test('each primitive matches its snapshot under both themes', async () => {
  const mod = await ui();
  const {render, h} = mod;
  const actual = {};
  for (const theme of ['dark', 'light']) {
    for (const [name, node] of Object.entries(samples(mod))) actual[`${name}@${theme}`] = render(h('div', {'data-theme': theme}, node));
  }
  if (process.env.UI_SNAPSHOT_UPDATE) await writeFile(SNAPSHOTS, JSON.stringify(actual, null, 1) + '\n');
  assert.deepEqual(actual, JSON.parse(await readFile(SNAPSHOTS, 'utf8')));
});

test('the primitives are accessible as drawn: real buttons, names, pressed state, native disclosure', async () => {
  const mod = await ui();
  const {render, h, nextDetent, stepDetent, DETENTS} = mod;
  const out = Object.fromEntries(Object.entries(samples(mod)).map(([k, node]) => [k, render(node)]));
  assert.match(out.Button, /^<button type="button" class="ui-button ui-button--primary">/);
  assert.doesNotMatch(out.Button, /aria-pressed/, 'a plain button is not a toggle');
  assert.match(out.IconButton, /^<button aria-label="Play" title="Play" type="button" class="ui-button ui-button--quiet ui-icon-button" aria-pressed="false"><svg/);
  assert.match(out.Chip, /aria-pressed="true" data-on="true"/);
  assert.match(out.Segmented, /^<div role="group" aria-label="Profile" class="ui-segmented">/);
  assert.equal((out.Segmented.match(/aria-pressed="true"/g) || []).length, 1);
  assert.equal((out.Segmented.match(/<button /g) || []).length, 3);
  assert.match(out.Tile, /<details class="ui-popover"[^>]*><summary [^>]*>basis<\/summary><div class="ui-popover-body">NWS point forecast/);
  assert.match(out.TileStale, /data-state="stale"[\s\S]*>stale<\/span>/);
  assert.match(out.Rail, /^<div class="ui-rail" role="group" aria-label="Layers"><ul class="ui-rail-list"><li class="ui-rail-item" data-on="true"><button [^>]*aria-pressed="true"/);
  assert.match(out.Rail, /<summary class="ui-popover-summary ui-eyebrow" aria-label="Currents basis"><svg/);
  assert.match(out.Sheet, /<section class="ui-sheet" data-detent="half" aria-label="Brief">/);
  assert.match(out.Sheet, /<button type="button" class="ui-sheet-handle" aria-label="Expand Brief" aria-expanded="true"/);
  assert.match(out.Dock, /<input type="range" class="ui-range ui-dock-range" aria-label="Hour" aria-valuetext="2 pm" min="0" max="23" step="1" value="14"\/>/);
  assert.match(out.Dock, /<output class="ui-dock-readout ui-mono" aria-live="off">2 pm<\/output>/);
  assert.match(out.Dock, /aria-label="Pause"/);
  assert.deepEqual(DETENTS, ['peek', 'half', 'full']);
  assert.deepEqual(['ArrowUp', 'ArrowDown', 'Home', 'End', 'Escape', 'Tab'].map(k => nextDetent('half', k)), ['full', 'peek', 'peek', 'full', 'peek', null]);
  assert.equal(nextDetent('full', 'ArrowUp'), 'full');
  assert.deepEqual(DETENTS.map(stepDetent), ['half', 'full', 'peek']);
});
