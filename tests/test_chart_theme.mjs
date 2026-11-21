import assert from 'node:assert/strict';
import test from 'node:test';
import {chartStyle, chartThemePaint, ENC_LAYER} from '../web/map/chart.ts';
import {readPalette} from '../web/map/palette.ts';
import {basemapStyle} from '../web/map/style.ts';
import {basemapThemePaint} from '../web/map/theme-restyle.ts';
import {assertThemePaintOracle} from './theme-paint-oracle.mjs';

const page = 'https://s.test/map';
const archive = 'https://s.test/basemap.pmtiles';
const build = palette => chartStyle({palette, archive, page, region: 'morro-bay', base: 'chart'});
const palette = theme => readPalette(name => /^map-.*-(opacity|width)$/.test(name)
  ? (theme === 'dark' ? '0.8' : '0.6') : `${theme}/${name}`);

// A missing builder (e.g. after marks are reorganized) would leave a stale paint;
// re-emitting basemap or ENC paint would put the same layer under two providers.
test('Chart restyles every non-basemap paint in both directions without claiming ENC', () => {
  const palettes = {dark: palette('dark'), light: palette('light')};
  for (const p of Object.values(palettes)) {
    const excluded = new Set([ENC_LAYER, ...basemapStyle(p, {archive, assets: ''}).layers.map(l => l.id)]);
    const edits = chartThemePaint(p);
    assert.ok(edits.every(({layer}) => !excluded.has(layer)));
    assert.deepEqual(new Set(edits.map(({layer}) => layer)),
      new Set(build(p).layers.filter(l => !excluded.has(l.id) && Object.keys(l.paint ?? {}).length).map(l => l.id)));
  }
  assertThemePaintOracle({build, palettes, provider: {
    themePaint: p => [...basemapThemePaint(p), ...chartThemePaint(p)],
  }});
});
