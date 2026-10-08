// NAIP aerial source config (FE-45, docs/plans/front-end/design.md § 9, § 11):
// catalog/sources.json, packages/coast's naipSource() and the region flags
// describe one fixed USGS service with one attribution, and the platform build
// carries each region's basemap.aerial into dist/. Offline: no tile is fetched.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, existsSync} from 'node:fs';
import {mapSourceHosts, naipSource} from '../packages/coast/src/map-sources.ts';

const json = path => JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
const naip = json('catalog/sources.json').sources.find(source => source.id === 'usgs-naip');
const regionIds = readdirSync(new URL('../regions/', import.meta.url), {withFileTypes: true})
  .filter(entry => entry.isDirectory() && existsSync(new URL(`../regions/${entry.name}/region.json`, import.meta.url)))
  .map(entry => entry.name);

test('the catalog NAIP host is the one packages/coast allows', () => {
  assert.ok(naip, 'catalog/sources.json has usgs-naip');
  assert.deepEqual(naip.allowed_hosts, ['imagery.nationalmap.gov']);
  assert.ok(mapSourceHosts.includes(`https://${naip.allowed_hosts[0]}`), 'catalog host is in mapSourceHosts');
  assert.equal(new URL(naip.tiles.endpoint).origin, `https://${naip.allowed_hosts[0]}`);
});

test('naipSource() requests the catalog endpoint with the catalog rendering rule and attribution', () => {
  const source = naipSource();
  assert.equal(source.tiles.length, 1);
  for (const template of source.tiles) {
    const url = new URL(template.replace('{bbox-epsg-3857}', '0,0,1,1'));
    assert.equal(`${url.origin}${url.pathname}`, naip.tiles.endpoint);
    assert.ok(mapSourceHosts.includes(url.origin));
    assert.deepEqual(JSON.parse(url.searchParams.get('renderingRule')), {rasterFunction: naip.tiles.rendering_rule});
  }
  assert.equal(source.attribution, naip.rights.attribution);
  assert.equal(naip.rights.license, 'public-domain');
  assert.equal(naip.rights.commercial_use, 'allowed');
  assert.equal(naip.rights.attribution_required, true);
});

test('every aerial region names usgs-naip with a dated acquisition window', () => {
  const aerial = regionIds.filter(id => json(`regions/${id}/region.json`).basemap?.aerial);
  assert.deepEqual(aerial, ['morro-bay'], 'only regions whose coverage was checked offer the aerial base');
  for (const id of aerial) {
    const {source, checked_at, acquired} = json(`regions/${id}/region.json`).basemap.aerial;
    assert.equal(source, naip.id);
    assert.ok(acquired.first <= acquired.last && acquired.last <= checked_at, id);
  }
});

test('the platform build carries basemap.aerial into each published region', () => {
  for (const id of regionIds) {
    const config = json(`regions/${id}/region.json`);
    if (config.status === 'draft') continue;
    assert.deepEqual(json(`dist/regions/${id}/region.json`).basemap, config.basemap, id);
  }
});
