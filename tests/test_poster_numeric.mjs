// RF1950-4 (web/map/poster.ts): numbers that overflow, or a zoom the projection cannot use, are never a poster.
import assert from 'node:assert/strict';
import test from 'node:test';
import {loadPoster, mercator, parsePoster, poster, posterPlacement} from '../web/map/poster.ts';
import {publishedChartFiles} from '../web/chart-files.ts';

const BIG = '9'.repeat(400);
const svg = ({box = '0 0 10 10', zoom = '12', west = '-121', north = '35'} = {}) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${box}" data-zoom="${zoom}" data-west="${west}" data-north="${north}"><path d="M0 0l1 1"/></svg>`;

test('poster_overflowing_dimensions_are_refused', () => {
  assert.ok(parsePoster(svg(), 'r'));
  for (const box of [`0 0 ${BIG} 10`, `0 0 10 ${BIG}`, '0 0 0 10', '0 0 10 -5', '0 0 -10 10'])
    assert.equal(parsePoster(svg({box}), 'r'), null, box.slice(0, 20));
});

test('poster_overflowing_zoom_is_refused', () => {
  for (const zoom of [BIG, `-${BIG}`, '1024', '-2000'])
    assert.equal(parsePoster(svg({zoom}), 'r'), null, zoom.slice(0, 10));
});

test('poster_coordinate_overflow_is_refused', () => {
  for (const o of [{west: BIG}, {north: BIG}, {west: `-${BIG}`}, {north: '86'}, {west: '181'}, {north: '-86'}, {west: 'x'}])
    assert.equal(parsePoster(svg(o), 'r'), null, JSON.stringify(o).slice(0, 30));
  assert.ok(parsePoster(svg({west: '180', north: '85'}), 'r'));
  assert.ok(parsePoster(svg({west: '-180', north: '-85'}), 'r'));
});

test('poster_valid_fractional_zoom_preserves_placement', () => {
  for (const zoom of ['12', '12.5']) {
    const text = svg({zoom}), p = parsePoster(text, 'r');
    assert.ok(p);
    assert.equal(p.zoom, Number(zoom));
    assert.equal(text, svg({zoom}));
    const at = posterPlacement(p, {latitude: 35, longitude: -121, zoom: 12}, 390, 844);
    assert.ok([at.x, at.y, at.scale].every(Number.isFinite));
    const [cx, cy] = mercator(-121, 35, p.zoom), [ox, oy] = mercator(p.west, p.north, p.zoom);
    assert.equal(at.x, 195 + (ox - cx) * at.scale);
    assert.equal(at.y, 422 + (oy - cy) * at.scale);
  }
});

test('poster_loader_does_not_publish_invalid_numeric_file', async () => {
  const before = publishedChartFiles.value;
  const respond = text => async () => new Response(text, {status: 200});
  let calls = 0;
  const counted = text => async () => { calls++; return new Response(text, {status: 200}); };
  try {
    publishedChartFiles.value = null;
    poster.value = null;
    for (const bad of [svg({box: `0 0 ${BIG} 10`}), svg({zoom: BIG}), svg({zoom: '1024'})]) {
      await loadPoster('r', 'https://s.test/map', () => false, respond(bad));
      assert.equal(poster.value, null);
    }
    await loadPoster('r', 'https://s.test/map', () => false, respond(svg()));
    assert.equal(poster.value?.region, 'r');
    poster.value = null;
    await loadPoster('r', 'https://s.test/map', () => true, respond(svg()));
    assert.equal(poster.value, null, 'already drawn');
    publishedChartFiles.value = {region: 'r', files: ['land-water.json']};
    await loadPoster('r', 'https://s.test/map', () => false, counted(svg()));
    assert.equal(calls, 0);
    assert.equal(poster.value, null);
  } finally {
    poster.value = null;
    publishedChartFiles.value = before;
  }
});
