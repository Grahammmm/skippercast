// #711: packages/coast chart series read v2 roles through tokens-bridge.css. Under the token opt-in each series
// colour is a web/tokens.css role (or a mix of two), readable as label text on the coast panels in both themes;
// without it every series keeps its v1 colour as the var() fallback, so non-opt-in hosts are unchanged.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {BRIDGE, bridged, contrast} from '../scripts/check_contrast.mjs';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const BRIEFING = read('packages/coast/src/ui/briefing.ts'), HISTORY = read('packages/coast/src/ui/history.ts');
/** Each series: its role and the v1 colour it keeps as the fallback. */
const SERIES = {
  briefing: {Wind: ['mint', '#64e4c0'], Gusts: ['series-gust', '#a5f4d8'], Offshore: ['blue', '#60b9ff'], Nearshore: ['series-violet', '#ab94ff'],
    Tide: ['amber', '#eabd76'], Air: ['coral', '#ff9580'], Cloud: ['muted', '#abc5d7']},
  history: {'Sea temperature': ['coral', '#ff9e86'], 'Wave height': ['blue', '#66bfff'], Wind: ['mint', '#65e3c0'], 'Air temperature': ['amber', '#ecbb70'],
    'Reported gust': ['series-gust', '#b5eaaa'], 'Dominant wave period': ['series-violet', '#bb9aff']},
};

test('every chart series names its v2 role and keeps its v1 colour as the fallback', () => {
  for (const [file, source] of [['briefing', BRIEFING], ['history', HISTORY]])
    for (const [label, [role, v1]] of Object.entries(SERIES[file]))
      assert.ok(source.includes(`label:'${label}',`) && new RegExp(`label:'${label}',unit:'[^']*',color:'var\\(--coast-${role},${v1}\\)'`).test(source), `${file} ${label}`);
  assert.equal(BRIEFING.match(/color:'var\(--coast-amber,#eabd76\)'/g).length, 2, 'both tide charts');
  assert.doesNotMatch(`${BRIEFING}${HISTORY}`, /color:'#/, 'no bare series literal');
});

test('SVG colours that may be var() sit in style, never in a presentation attribute (which cannot resolve var())', () => {
  for (const source of [BRIEFING, HISTORY, read('packages/coast/src/charts/series.ts')])
    assert.doesNotMatch(source, /(?:stroke|fill)="\$\{(?:spec|row)\.color\}"|(?:stroke|fill)="var\(/);
  assert.match(HISTORY, /style="stroke:var\(--coast-line,#9db6cc\)"/, 'the gridline reads --coast-line');
});

test('under the opt-in every series role resolves to an opaque colour readable as label text on the coast panels', () => {
  const roles = [...new Set(Object.values(SERIES).flatMap(s => Object.values(s).map(([role]) => role)))];
  for (const [theme, colours] of Object.entries(bridged(read(BRIDGE), read('web/tokens.css')))) {
    for (const role of roles) for (const surface of ['panel', 'panel-2']) {
      assert.ok(colours[role], `${theme}: --coast-${role} resolves`);
      assert.ok(contrast(colours[role], colours[surface]) >= 4.5, `${theme}: --coast-${role} on --coast-${surface} ${contrast(colours[role], colours[surface]).toFixed(2)}:1`);
    }
  }
});
