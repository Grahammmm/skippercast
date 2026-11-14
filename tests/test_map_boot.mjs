import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {boot, opensChart} from '../web/app/boot.ts';

const page = query => `https://skippercast.com/map${query}`;
test('SCB-12: direct Chart visits warm early; terrain, unchosen homes and other pages stay lazy', () => {
  for (const query of ['?region=morro-bay', '?region=morro-bay&presentation=chart', '?region=morro-bay&presentation=invalid']) {
    assert.equal(opensChart(page(query), () => null), true);
  }
  for (const query of ['', '?coast=central', '?region=', '?region=../private', '?region=morro-bay&coast=central', '?region=morro-bay&presentation=2d', '?region=morro-bay&presentation=3d']) {
    assert.equal(opensChart(page(query), () => null), false, query);
  }
  assert.equal(opensChart('https://skippercast.com/?region=morro-bay', () => null), false);
  assert.equal(opensChart(page('?region=morro-bay'), () => '3d'), false);
  assert.equal(opensChart(page('?region=morro-bay&presentation=chart'), () => '3d'), true, 'explicit choice overrides storage');
  assert.equal(opensChart(page('?region=morro-bay'), () => { throw new Error('storage denied'); }), true);
});

test('SCB-12: a pending or rejected Chart hint never serializes or prevents the app import', async () => {
  const order = [];
  boot(page('?region=morro-bay'), () => null, () => { order.push('chart'); return new Promise(() => {}); }, async () => { order.push('app'); });
  assert.deepEqual(order, ['chart', 'app']);
  order.length = 0;
  boot(page('?region=morro-bay'), () => null, async () => { order.push('chart'); throw new Error('download failed'); }, async () => { order.push('app'); });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(order, ['chart', 'app']);
  order.length = 0;
  boot(page('?region=morro-bay&presentation=3d'), () => null, async () => { order.push('chart'); }, async () => { order.push('app'); });
  assert.deepEqual(order, ['app']);
});

test('SCB-12: HTML runs the dependency-free Vite bootstrap, not the full shell', () => {
  const source = readFileSync(new URL('../web/app/boot.ts', import.meta.url), 'utf8');
  const html = readFileSync(new URL('../dist/app.html', import.meta.url), 'utf8');
  assert.match(html, /<script type="module" src="\.\.\/web\/app\/boot\.ts"><\/script>/);
  assert.doesNotMatch(source, /^import\s/m, 'no static app graph ahead of the parallel imports');
  assert.match(source, /import\('\.\.\/map\/maplibre\.js'\)/);
  assert.match(source, /import\('\.\/main\.tsx'\)/);
  assert.doesNotMatch(html, /rel="modulepreload"/, 'Vite owns fingerprinted dependencies');
});
