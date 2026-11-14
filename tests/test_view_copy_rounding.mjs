// RF1900-6: changing the display language never changes a rounded measurement. fixed() and coastCopy().number
// print the established English toFixed value, localized; Intl alone rounds the binary float and disagrees at a
// decimal tie (60.05 -> "60,1" against English "60.0"). Known answers are written out here, never computed by
// the code under test. Everything runs the production helpers and History renderer on synthetic data.
import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import fixture from './fixtures/coast/history.json' with {type: 'json'};

const ROOT = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'view-copy-rounding-')), 'bundle.mjs');
await build({
  stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {fixed, coastCopy} from './web/view-copy.ts';
    export {historyView} from './packages/coast/src/ui/history.ts';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', plugins: preparedRendererPlugins,
});
const v = await import(pathToFileURL(out).href);
const es = v.coastCopy('es');
const num = (n, d, group) => es.number(n, d, group);

test('binary_decimal_ties_keep_english_value: 60.05, 2.55 and 1.005 round as English does, in fixed and coastCopy.number', () => {
  const cases = [[60.05, 1, '60.0', '60,0'], [2.55, 1, '2.5', '2,5'], [1.005, 2, '1.00', '1,00'],
    // adjacent representable values on either side: no blanket downward rounding passes
    [60.06, 1, '60.1', '60,1'], [60.04, 1, '60.0', '60,0'], [2.56, 1, '2.6', '2,6'], [2.54, 1, '2.5', '2,5'], [1.006, 2, '1.01', '1,01'], [1.004, 2, '1.00', '1,00']];
  for (const [n, d, en, sp] of cases) {
    assert.equal(v.fixed(n, d, 'en'), en, `en ${n}/${d}`);
    assert.equal(v.fixed(n, d, 'es'), sp, `es fixed ${n}/${d}`);
    assert.equal(num(n, d), sp, `es number ${n}/${d}`);
    assert.equal(num(n, d, true), sp, `es grouped number ${n}/${d}`);
  }
});

test('negative_ties_and_signed_zero_keep_sign', () => {
  for (const [n, d, en, sp] of [[-60.05, 1, '-60.0', '-60,0'], [-2.55, 1, '-2.5', '-2,5'], [-60.06, 1, '-60.1', '-60,1'],
    [-0.04, 1, '-0.0', '-0,0'], [-0.004, 2, '-0.00', '-0,00'], [0.04, 1, '0.0', '0,0'], [-0.5, 0, '-1', '-1'], [0.5, 0, '1', '1'], [-1.5, 0, '-2', '-2']]) {
    assert.equal(v.fixed(n, d, 'en'), en, `en ${n}/${d}`);
    assert.equal(v.fixed(n, d, 'es'), sp, `es fixed ${n}/${d}`);
    assert.equal(num(n, d), sp, `es number ${n}/${d}`);
  }
  assert.equal(v.fixed(0, 1, 'es'), '0,0');
  assert.equal(num(0, 1), '0,0');
  // An actual -0 (an already-rounded value from a caller) keeps the sign Intl always gave it; English toFixed prints "0.0".
  assert.equal(v.fixed(-0, 1, 'es'), '-0,0');
  assert.equal(num(-0, 1), '-0,0');
});

test('digits_and_grouping_preserve_contract', () => {
  for (const [d, n, sp] of [[0, 3, '3'], [1, 3, '3,0'], [2, 3, '3,00'], [3, 3, '3,000'], [0, 2.4, '2'], [1, 12.34, '12,3'], [2, 12.345, '12,35'], [3, 0.1234, '0,123']]) {
    assert.equal(v.fixed(n, d, 'es'), sp, `fixed ${n}/${d}`);
    assert.equal(num(n, d), sp, `number ${n}/${d}`);
  }
  // fixed never groups; number groups only when asked (Spanish groups with "." and uses "," for decimals)
  assert.equal(v.fixed(12345.678, 1, 'es'), '12345,7');
  assert.equal(num(12345.678, 1), '12345,7');
  assert.equal(num(12345.678, 1, true), '12.345,7');
  assert.equal(num(1234567, 0, true), '1.234.567');
  // a carry across a power-of-ten boundary
  assert.equal(v.fixed(9.96, 1, 'es'), '10,0');
  assert.equal(v.fixed(99.96, 1, 'es'), '100,0');
  assert.equal(v.fixed(999.996, 2, 'es'), '1000,00');
  assert.equal(num(99999.996, 2, true), '100.000,00');
  assert.equal(v.fixed(9.96, 1, 'en'), '10.0');
  // non-finite values and invalid precision behave as before
  assert.equal(v.fixed(NaN, 1, 'es'), 'NaN');
  assert.equal(num(Infinity, 1), '∞');
  assert.equal(num(-Infinity, 1), '-∞');
  assert.throws(() => v.fixed(1, -1, 'es'), RangeError);
  assert.throws(() => v.fixed(1, 101, 'es'), RangeError);
  assert.equal(v.coastCopy('en'), undefined);
});

// ---- the real History renderer on synthetic hourly values that sit on a binary tie
const NOW = new Date('2026-10-07T15:10:00Z');
const county = {id: 'slo', timezone: 'America/Los_Angeles'};
const source = structuredClone(fixture);
for (const h of source.stations[0].recent.hours) h.waterTempF = 60.05;
const pristine = structuredClone(source);
const view = lang => v.historyView({county, now: NOW}, source, {station: '', metric: 'waterTempF', days: 45}, v.coastCopy(lang));
// the stat values: Latest hourly mean, N-day average (and the later "versus" cell is not a rounded measurement tie)
const stats = html => [...html.matchAll(/<b[^>]*>([^<]*)<small> ([^<]*)<\/small><\/b>/g)].map(m => [m[1], m[2]]);
const paths = html => [...html.matchAll(/<path d="([^"]*)"/g)].map(m => m[1]);
const axis = html => [...html.matchAll(/class="axis">([^<]*)<\/text>/g)].map(m => m[1]);

test('history_latest_and_mean_do_not_change_with_language: 60.05 is 60.0 in English and 60,0 in Spanish; en to es to en restores the bytes', () => {
  const en = view('en'), sp = view('es');
  assert.match(en, /<span>Latest hourly mean<\/span><b style="color:var\(--coast-coral\)">60\.0<small> °F<\/small>/);
  assert.match(en, /<span>45-day average<\/span><b>60\.0<small> °F<\/small>/);
  assert.match(sp, /<span>Último promedio horario<\/span><b style="color:var\(--coast-coral\)">60,0<small> °F<\/small>/);
  assert.match(sp, /<span>Promedio de 45 días<\/span><b>60,0<small> °F<\/small>/);
  assert.ok(!sp.includes('60,1') && !en.includes('60.1'), 'no 60.1 anywhere');
  // every displayed stat number agrees across languages modulo the decimal comma
  const sa = stats(en), sb = stats(sp);
  assert.equal(sa.length, sb.length);
  assert.ok(sa.length >= 2);
  assert.ok(isDeepStrictEqual(sa.map(([n, u]) => [n, u]), sb.map(([n, u]) => [n.replace(',', '.'), u])), 'stat numbers and units agree modulo locale');
  const back = view('en');
  assert.equal(back === en, true, 'en after es is byte-identical to the first English render');
  assert.ok(isDeepStrictEqual(source, pristine), 'source data untouched by either language');
});

test('history_paths_and_existing_copy_unchanged: chart geometry, axis numbers and sample counts do not depend on language', () => {
  const en = view('en'), sp = view('es');
  const pa = paths(en), pb = paths(sp);
  assert.ok(pa.length >= 1 && pa.some(p => p.length > 0));
  assert.ok(isDeepStrictEqual(pa, pb), 'chart path bytes identical across languages');
  const aa = axis(en), ab = axis(sp);
  assert.ok(aa.some(t => /^\d+\.\d$/.test(t)), 'English axis carries one-decimal numbers');
  assert.ok(isDeepStrictEqual(aa.filter(t => /^[\d.]+$/.test(t)), ab.filter(t => /^[\d,]+$/.test(t)).map(t => t.replace(',', '.'))), 'axis numbers agree modulo locale');
  // raw sample counts ("2 / N hourly bins") keep the same integers
  assert.match(en, /2 \/ 1,081 hourly bins · 0\.2% metric coverage/);
  assert.match(sp, /2 \/ 1\.081 intervalos horarios · 0,2% de cobertura/);
});
