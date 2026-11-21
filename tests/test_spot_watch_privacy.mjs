import assert from 'node:assert/strict';
import {readdirSync, readFileSync} from 'node:fs';
import test from 'node:test';
import {evaluateWatches} from '../server/spot-watch-eval.ts';
import {spotWatchPush} from '../server/spot-watch-push.ts';

function forbiddenTokens(source) {
  const hits = new Set(['console.', 'fetch(', 'sendBeacon', 'XMLHttpRequest']
    .filter(token => source.includes(token)));

  // Keep quoted import paths intact while dropping comments, including commented-out imports.
  const code = source.replace(/("(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|`(?:\\[\s\S]|[^`\\])*`)|\/\*[\s\S]*?\*\/|\/\/[^\r\n]*/g,
    (_match, quoted) => quoted ?? ' ');
  // Bare, from, and literal dynamic imports (plus TypeScript's import = require form).
  const imports = /\bimport\s*(?:\(\s*|[\w$\s,*{}]+?\bfrom\s*|[\w$]+\s*=\s*require\s*\(\s*)?(['"`])((?:(?!\1)[^\r\n])*)\1/g;
  for (const [, , path] of code.matchAll(imports)) {
    for (const token of ['routes/', 'analytics', 'telemetry']) {
      if (path.includes(token)) hits.add(token);
    }
  }
  return [...hits];
}

function assertPrivateSource(file, source) {
  const hits = forbiddenTokens(source);
  assert.ok(hits.length === 0, `${file}: forbidden ${hits.join(', ')}`);
}

// C1: A new spot-watch module must not quietly acquire a logging or network sink.
test('C1: all spot-watch modules pass the source privacy scan', () => {
  const server = new URL('../server/', import.meta.url);
  const files = readdirSync(server, {withFileTypes: true})
    .filter(entry => entry.isFile() && /^spot-watch-.*\.ts$/.test(entry.name))
    .map(entry => entry.name)
    .sort();
  assert.ok(files.length >= 4, `expected at least four spot-watch modules, found ${files.length}`);
  for (const file of files) {
    assertPrivateSource(`server/${file}`, readFileSync(new URL(file, server), 'utf8'));
  }

  // Prove each diagnostic independently without adding a fixture module to the inventory.
  for (const [token, source] of [
    ['console.', 'console.log(position);'],
    ['fetch(', 'fetch(url);'],
    ['sendBeacon', 'navigator.sendBeacon(url);'],
    ['XMLHttpRequest', 'new XMLHttpRequest();'],
    ['routes/', "import {\n  read\n} from './routes/spots.ts';"],
    ['analytics', 'import "./analytics.ts";'],
    ['analytics', 'await import(`../analytics.ts`);'],
    ['telemetry', "await import('../telemetry.ts');"],
  ]) {
    assert.throws(() => assertPrivateSource('spot-watch-sample.ts', source), {
      message: `spot-watch-sample.ts: forbidden ${token}`,
    });
  }
  assertPrivateSource('spot-watch-comment.ts', `
    // routes/, analytics and telemetry are not imported here.
    /* import './telemetry.ts'; */
    import {sampleAt} from '../web/map/habitat-sample.ts';
  `);
});

const position = {lat: 0.0123456789, lon: -0.987654321};
const sampleAt = '2026-11-20T12:00:00Z';

// C2: Spreading the watch into a result or embedding its position in an existing field leaks it.
test('C2: the complete batch evaluation omits both sentinel coordinates', () => {
  const prev = {state: 'false', lastSampleAt: '2026-11-19T12:00:00Z'};
  const watch = {...position, id: 'watch-1', layer: 'water-temp', cond: {op: '>=', a: 58}, prev};
  const frame = {
    sampleAt,
    fields: ['latitude', 'longitude', 'temperature_c'],
    resolution: [0.1, 0.1],
    rows: [[0.05, -0.95, 59]],
  };
  const result = evaluateWatches([watch, {...watch, id: 'watch-2', layer: 'chlorophyll'}],
    new Map([['water-temp', frame]]));
  assert.deepEqual(result, [
    {id: 'watch-1', next: {state: 'true', lastSampleAt: sampleAt}, fire: true, value: 59, reason: null},
    {id: 'watch-2', next: {state: 'false', lastSampleAt: '2026-11-19T12:00:00Z'}, fire: false, value: null, reason: 'withheld'},
  ]);
  const json = JSON.stringify(result);
  assert.ok(!json.includes(String(position.lat)), 'evaluation JSON echoed the latitude');
  assert.ok(!json.includes(String(position.lon)), 'evaluation JSON echoed the longitude');
});

// C3: Even if a caller passes a watch position along, it must not become payload or URL data.
test('C3: the complete push payload links by spot ID without extra parameters', () => {
  const input = {
    ...position, watchId: 'watch-1', sampleAt, region: 'central-2',
    spotId: 'spot-1', layer: 'water-temp', spotName: 'Test Ridge', title: 'Water update',
  };
  assert.deepEqual(spotWatchPush(input, name => `${name}: 59 °F`), {
    ok: true,
    push: {
      title: 'Water update',
      body: 'Test Ridge: 59 °F',
      eventId: 'spotwatch:watch-1:2026-11-20T12:00:00Z',
      url: '/map?region=central-2&spot=spot-1&layers=water-temp',
    },
  });
});
