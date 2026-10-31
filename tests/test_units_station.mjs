// RF1105-21: the station model (seas ft, wind/gust kt) and the qualified-depth disclaimer
// take their factors from web/units.ts. Every value a visitor sees is what the old
// literals (3.280839895, 1.943844492, 3.28084) printed; no conversion literal is left.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {FT_PER_M, KT_PER_MS} from '../web/units.ts';
import {qualifiedDepth} from '../web/disclaimers.ts';

const MODEL = readFileSync(new URL('../web/map/station-model.ts', import.meta.url), 'utf8');
const DISCLAIMERS = readFileSync(new URL('../web/disclaimers.ts', import.meta.url), 'utf8');
const row = key => MODEL.split('\n').find(l => l.includes(`key: '${key}'`)) ?? '';

test('station units: no conversion literal left in either file', () => {
  for (const [name, text] of [['station-model.ts', MODEL], ['disclaimers.ts', DISCLAIMERS]])
    for (const literal of ['3.28084', '3.280839895', '1.943844', '0.3048', '1852'])
      assert.ok(!text.includes(literal), `${name} still contains ${literal}`);
  assert.match(row('WVHT'), /scale: FT_PER_M, offset: 0/);
  assert.match(row('WSPD'), /scale: KT_PER_MS, offset: 0/);
  assert.match(row('GST'), /scale: KT_PER_MS, offset: 0/);
});

test('station units: temperature row still converts degC by 1.8 and 32', () => {
  assert.match(row('WTMP'), /raw: 'degC', scale: 1\.8, offset: 32\}/);
  assert.match(MODEL, /\$\{sample\.value\.toFixed\(1\)\} \$\{v\.unit\}/, 'label precision is one decimal');
});

test('station units: seas label unchanged for 0.00..15.00 m by 0.01', () => {
  for (let i = 0; i <= 1500; i++) {
    const v = i / 100;
    assert.equal((v * FT_PER_M + 0).toFixed(1), (v * 3.280839895 + 0).toFixed(1), `${v} m`);
  }
});

test('station units: wind and gust labels unchanged for 0.0..60.0 m/s by 0.1', () => {
  for (let i = 0; i <= 600; i++) {
    const v = i / 10;
    assert.equal((v * KT_PER_MS + 0).toFixed(1), (v * 1.943844492 + 0).toFixed(1), `${v} m/s`);
    assert.equal(Math.round(v * KT_PER_MS), Math.round(v * 1.943844492), `${v} m/s rounded`);
  }
});

const oldDepth = (datum, u, marginM) =>
  `Measured-depth screen on ${datum}: the survey states product uncertainty up to ${u} m (${(u * 3.28084).toFixed(1)} ft)`
  + `${typeof marginM === 'number' && marginM > 0 ? `, and the screen adds a ${marginM} m planning allowance` : ''}.`
  + ' Not a tide forecast, navigation route or catch probability; verify on your sounder.';

test('station units: qualified-depth text unchanged for 0.00..10.00 m by 0.01 and each margin', () => {
  let nearHalf = 0;
  for (let i = 0; i <= 1000; i++) {
    const u = i / 100;
    const tenths = u * 3.28084 * 10;
    if (Math.abs(tenths - Math.floor(tenths) - 0.5) < 0.005) nearHalf++;
    for (const margin of [0, 0.5, null, undefined])
      assert.equal(qualifiedDepth('MLLW', u, margin), oldDepth('MLLW', u, margin), `${u} m, margin ${margin}`);
  }
  assert.ok(nearHalf > 0, 'the sweep includes uncertainties whose feet land on a .x5 boundary');
  assert.match(qualifiedDepth('MLLW', 0.5, 0.5), /up to 0\.5 m \(1\.6 ft\), and the screen adds a 0\.5 m planning allowance\./);
});

test('station units: non-finite uncertainty prints as before (no new guard)', () => {
  for (const u of [NaN, Infinity, -Infinity]) {
    assert.equal(qualifiedDepth('MLLW', u, null), oldDepth('MLLW', u, null), String(u));
    assert.ok(qualifiedDepth('MLLW', u).includes(`up to ${u} m (${u} ft)`), String(u));
  }
});
