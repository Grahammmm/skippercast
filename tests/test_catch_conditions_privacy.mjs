import test from 'node:test';
import assert from 'node:assert/strict';
import {globSync, readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {regionForEntry} from '../server/catch-region.ts';
import {catchPatterns} from '../web/catch-patterns.ts';

const outputTokens = ['console.', 'fetch(', 'sendBeacon', 'XMLHttpRequest'];
const importTokens = ['routes/', 'analytics', 'telemetry'];

function privacyHits(file, source) {
  const hits = outputTokens.filter(token => source.includes(token));
  // Strip comments without mangling quoted module paths (including URL imports).
  const code = source.replace(/("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|\/\*[\s\S]*?\*\/|\/\/[^\r\n]*/g,
    (_, quoted) => quoted ?? ' ');
  const paths = [...code.matchAll(/\bimport\s*(?:\(\s*|[^"'`;()=]+?\bfrom\s*)?(["'])([^"'\r\n]+)\1/g)]
    .map(match => match[2]);
  return [...hits, ...importTokens.filter(token => paths.some(path => path.includes(token)))]
    .map(token => `${file}: ${token}`);
}

// A debug log, direct request, or import of a transport can expose a private snapshot.
test('C1: catch-conditions sources have no banned logging or transport tokens', () => {
  const sample = `
    console.log(snapshot);
    fetch(endpoint);
    navigator.sendBeacon(endpoint);
    new XMLHttpRequest();
    import {handler} from '../routes/example.ts';
    import '../analytics.ts';
    import('../telemetry.ts');
  `;
  assert.deepEqual(privacyHits('sample.ts', sample), [
    'sample.ts: console.', 'sample.ts: fetch(', 'sample.ts: sendBeacon', 'sample.ts: XMLHttpRequest',
    'sample.ts: routes/', 'sample.ts: analytics', 'sample.ts: telemetry',
  ]);
  assert.deepEqual(privacyHits('sample.ts', `
    // analytics, telemetry and routes/
    /* import '../telemetry.ts'; */
    import {example as analytics} from './example.ts';
  `), []);

  const root = new URL('../', import.meta.url);
  const files = [
    ...globSync(['server/catch-*.ts', 'web/catch-*.ts'], {cwd: fileURLToPath(root)}),
    'server/conditions-v1.ts', 'server/front-distance.ts',
  ].sort();
  assert.ok(files.length >= 6, `Expected at least 6 catch-conditions modules; found ${files.length}: ${files.join(', ')}`);
  const hits = files.flatMap(file => privacyHits(file, readFileSync(new URL(file, root), 'utf8')));
  assert.equal(hits.length, 0, hits.join('\n'));
});

const position = {lat: 12.34567891, lon: -43.21098765};

function assertOmitsSentinels(result, sentinels) {
  const json = JSON.stringify(result);
  for (const [field, value] of Object.entries(sentinels)) {
    assert.ok(!json.includes(String(value)), `Result JSON must not include the input ${field}`);
  }
}

// A row copied into an aggregate band would expose its position or note.
test('C2: shown patterns contain only aggregates, not entry positions or notes', () => {
  const sentinels = {...position, note: 'synthetic-catch-privacy-marker'};
  const entries = Array.from({length: 12}, (_, i) => ({
    ...sentinels,
    outcome: i < 8 ? 'fish' : 'blank',
    conditions: {v: 1, layers: {water_temp: {value: 62.4, unit: 'F'}, tide: {stage: 'flood'}}},
  }));
  const result = catchPatterns(entries);
  assert.deepEqual(result, {n: 12, shown: true, bands: [{bandF: 62, tide: 'flood', fish: 8, blank: 4}]});
  assertOmitsSentinels(result, sentinels);
});

// A region result must not start carrying the point used to resolve it.
test('C3: a position-based region result does not return the entry coordinates', () => {
  const result = regionForEntry(position, [{id: 'fixture-region', bounds: [-45, 11, -42, 14]}]);
  assert.deepEqual(result, {region: 'fixture-region', via: 'position'});
  assertOmitsSentinels(result, position);
});
