import test from 'node:test';
import assert from 'node:assert/strict';
import { legendHTML, detailsHTML, VIEWS } from '../dist/seafloor-layer.js';
import { GRADE_STYLE, FIT_STYLE } from '../dist/seafloor-data.js';

test('terrain and fit legends never share a key, and fit is never called a catch probability', () => {
  const terrain = legendHTML('terrain'), fit = legendHTML('fit_lingcod');
  for (const s of Object.values(GRADE_STYLE)) { assert.ok(terrain.includes(s.color)); assert.ok(!fit.includes(s.color)); }
  for (const s of Object.values(FIT_STYLE)) { assert.ok(fit.includes(s.color)); assert.ok(!terrain.includes(s.color)); }
  assert.match(fit, /not catch probability/);
  assert.deepEqual(VIEWS.map((v) => v.id), ['terrain', 'fit_lingcod', 'fit_rockfish_reef']);
});

test('details carry the required caveats, escape text and keep unknowns unknown', () => {
  const html = detailsHTML({ id: 'x', terrain_grade: 'A', fit_lingcod: 3, fit_rockfish_reef: 'unknown', depth_min_ft: 40, depth_max_ft: 90,
    source_ids: '["<b>src</b>"]', vertical_datum: 'unknown', screen: '{"status":"pass"}' });
  assert.match(html, /Habitat candidate, unverified/);
  assert.match(html, /Nominal depth; verify on your sounder\./);
  assert.match(html, /40–90 ft nominal/);
  assert.match(html, /lingcod: 3 of 3/);
  assert.match(html, /rockfish reef: unknown/);
  assert.match(html, /not a catch probability/);
  assert.match(html, /not a navigation chart/i);
  assert.ok(html.includes('&lt;b&gt;src&lt;/b&gt;'));
  assert.ok(!html.includes('<b>src</b>'));
  assert.match(html, /id="seafloor-weather"/);
});
